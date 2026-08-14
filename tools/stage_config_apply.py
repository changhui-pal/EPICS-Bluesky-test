#!/usr/bin/env python3
"""Prepare assigned motor records from the reviewed stage catalog.

The default mode prints a plan and performs no Channel Access operations.
Actual writes require ``--apply``. Basic apply requires the bootstrap lock,
writes and verifies model fields, then follows each assignment's enabled state. The old
commissioning checks remain available only through ``--development-guards``.
"""

import argparse
import configparser
import math
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Sequence, Tuple

import validate_stage_config as validator


PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9:_-]+$")
COMMISSIONING_FLAGS = (
    "ConfigApplied", "DirectionVerified", "SensorsVerified",
    "LimitsVerified", "HomeEstablished")


@dataclass(frozen=True)
class AxisPlan:
    """One fully validated motor-record configuration to apply."""

    axis: int
    model: str
    fields: Tuple[Tuple[str, str], ...]
    enabled: bool = True


def format_value(value: float) -> str:
    """Preserve useful model precision in Channel Access writes."""
    return format(value, ".12g")


def build_plans(models_path: pathlib.Path, axes_path: pathlib.Path,
                sys16_limit: float) -> Tuple[List[AxisPlan], List[str]]:
    """Validate files and prepare every assigned slot, enabled or disabled.

    Assignment is defined by a non-empty model. The enabled flag is the desired
    runtime state recorded by the GUI/server lifecycle.
    """
    warnings: List[str] = []
    models = validator.load_models(models_path, sys16_limit, warnings)
    validator.validate_axes(axes_path, models)
    axes = validator.read_ini(axes_path)
    plans: List[AxisPlan] = []
    for axis in range(1, 33):
        section = axes[f"axis:{axis}"]
        model_name = section.get("model", "").strip()
        if not model_name:
            continue
        model = models[model_name]
        direction = section["direction"].strip()
        home_method = section.getint("home_method", fallback=4)
        jog_acceleration = (
            model.default_velocity - model.base_velocity
        ) / model.acceleration_time
        fields = (
            ("DESC", model.description),
            ("EGU", model.egu),
            ("DIR", direction),
            ("MRES", format_value(model.mres)),
            ("LLM", format_value(model.low_limit)),
            ("HLM", format_value(model.high_limit)),
            ("VMAX", format_value(model.vmax)),
            ("VELO", format_value(model.default_velocity)),
            ("JVEL", format_value(model.default_velocity)),
            ("JAR", format_value(jog_acceleration)),
            ("HVEL", format_value(model.default_velocity)),
            ("VBAS", format_value(model.base_velocity)),
            ("ACCL", format_value(model.acceleration_time)),
            (":OriginMethod", str(home_method)),
        )
        plans.append(AxisPlan(
            axis, model_name, fields, section.getboolean("enabled")))
    return plans, warnings


class ChannelAccess:
    """Small caget/caput adapter using argument arrays, never a shell."""

    def __init__(self, epics_bin: pathlib.Path):
        self.caget = epics_bin / "caget"
        self.caput = epics_bin / "caput"
        if not self.caget.is_file() or not self.caput.is_file():
            raise ValueError(f"caget/caput not found in {epics_bin}")

    def get(self, pv: str, numeric_enum: bool = False) -> str:
        # Request enough floating-point digits to verify catalog values rather
        # than the record's display PREC (for example 3.429608 vs 3.42961).
        # This option does not alter string or enum output.
        command = [str(self.caget), "-t"]
        if numeric_enum:
            command.append("-n")
        else:
            command.extend(("-g", "12"))
        command.append(pv)
        result = subprocess.run(command, check=True, capture_output=True,
                                text=True, timeout=5.0)
        return result.stdout.strip()

    def put(self, pv: str, value: str) -> None:
        subprocess.run([str(self.caput), "-t", pv, value], check=True,
                       capture_output=True, text=True, timeout=5.0)


def require_disabled_and_stopped(client: ChannelAccess, prefix: str,
                                 plans: Sequence[AxisPlan]) -> None:
    """Complete all read-only safety checks before the first field write."""
    problems = []
    for plan in plans:
        record = f"{prefix}m{plan.axis}"
        try:
            able = client.get(f"{record}_able", numeric_enum=True)
            dmov = client.get(f"{record}.DMOV")
            movn = client.get(f"{record}.MOVN")
            # Requiring this PV also prevents applying to an IOC that has not
            # loaded the guarded commissioning database.
            client.get(f"{record}:Commissioning:ConfigApplied",
                       numeric_enum=True)
        except (subprocess.SubprocessError, OSError) as error:
            problems.append(f"axis {plan.axis}: preflight read failed: {error}")
            continue
        if able != "1" or dmov != "1" or movn != "0":
            problems.append(
                f"axis {plan.axis}: require Disable=1, DMOV=1, MOVN=0; "
                f"got {able}, {dmov}, {movn}")
    if problems:
        raise ValueError("; ".join(problems))


def apply_plans(client: ChannelAccess, prefix: str,
                plans: Sequence[AxisPlan], *,
                development_guards: bool = False) -> None:
    """Apply model fields without deferring MRES processing to first motion.

    SDIS keeps motor-record special processing pending while ``_able`` is
    Disable.  In particular, a pending MRES change makes the next process call
    issue LOAD_POS and can translate OFF and user limits.  Apply each model in
    SET mode while record processing is temporarily enabled;
    this consumes the MRES change through GET_INFO without writing a controller
    position.  Every exit path returns the axis to Disable.
    """
    if development_guards:
        require_disabled_and_stopped(client, prefix, plans)
    else:
        # Use the project's single operational _able lock while runtime model
        # fields are injected. No commissioning flags participate.
        for plan in plans:
            pv = f"{prefix}m{plan.axis}_able"
            if client.get(pv, numeric_enum=True) != "1":
                raise ValueError(
                    f"axis {plan.axis}: set _able=Disable before model apply"
                )
    for plan in plans:
        record = f"{prefix}m{plan.axis}"
        able_pv = f"{record}_able"
        original_set = client.get(f"{record}.SET", numeric_enum=True)
        if original_set not in {"0", "1"}:
            raise ValueError(
                f"axis {plan.axis}: unexpected SET state {original_set!r}")
        # DEVELOPMENT SAFETY GUARDS (disabled by default): keep this path for
        # later experiments without making commissioning PVs operational gates.
        if development_guards:
            if client.get(f"{record}_able", numeric_enum=True) != "1":
                raise ValueError(f"axis {plan.axis}: unexpectedly enabled before apply")
            client.put(f"{record}:Commissioning:InvalidateHomeRequest", "1")
            for flag in COMMISSIONING_FLAGS:
                pv = f"{record}:Commissioning:{flag}"
                client.put(pv, "0")
                if client.get(pv, numeric_enum=True) != "0":
                    raise ValueError(
                        f"axis {plan.axis}: failed to reset commissioning {flag}")
        primary_error = None
        try:
            client.put(f"{record}.SET", "Set")
            client.put(able_pv, "Enable")
            if client.get(able_pv, numeric_enum=True) != "0":
                raise ValueError(
                    f"axis {plan.axis}: temporary Enable failed during apply")
            for suffix, value in plan.fields:
                pv = (record + suffix if suffix.startswith(":")
                      else record + "." + suffix)
                client.put(pv, value)
                actual = client.get(pv)
                if suffix in ("DESC", "EGU", "DIR"):
                    matches = actual == value
                else:
                    try:
                        matches = math.isclose(float(actual), float(value),
                                               rel_tol=1e-10, abs_tol=1e-12)
                    except ValueError:
                        matches = False
                if not matches:
                    raise ValueError(
                        f"axis {plan.axis}: {suffix} readback {actual!r} "
                        f"does not match {value!r}")
        except BaseException as error:
            primary_error = error
            raise
        finally:
            cleanup_errors = []
            try:
                client.put(f"{record}.SET", "Set" if original_set == "1" else "Use")
            except BaseException as error:
                cleanup_errors.append(f"SET restore failed: {error}")
            try:
                client.put(able_pv, "Disable")
            except BaseException as error:
                cleanup_errors.append(f"Disable restore failed: {error}")
            if cleanup_errors and primary_error is None:
                raise ValueError(
                    f"axis {plan.axis}: " + "; ".join(cleanup_errors))
        if development_guards:
            if client.get(able_pv, numeric_enum=True) != "1":
                raise ValueError(
                    f"axis {plan.axis}: unexpectedly enabled during apply")
            applied_pv = f"{record}:Commissioning:ConfigApplied"
            client.put(applied_pv, "1")
            if client.get(applied_pv, numeric_enum=True) != "1":
                raise ValueError(
                    f"axis {plan.axis}: ConfigApplied readback failed")
    if not development_guards:
        for plan in plans:
            if plan.enabled:
                client.put(f"{prefix}m{plan.axis}_able", "0")


def render_plan(prefix: str, plans: Sequence[AxisPlan], warnings: Sequence[str]) -> str:
    """Return a human-reviewable plan containing no executable commands."""
    lines = [
        "KOHZU STAGE CONFIGURATION APPLY PLAN",
        "DEFAULT MODE: NO IOC OR CONTROLLER VALUES WERE CHANGED",
        "Basic mode applies model fields, then follows assignment enabled state.",
        "No HOME, ORG, motion, STOP, or controller-setting command is issued.",
        "",
    ]
    lines.extend(f"WARNING: {warning}" for warning in warnings)
    if warnings:
        lines.append("")
    for plan in plans:
        lines.append(f"Axis {plan.axis}: {prefix}m{plan.axis} model={plan.model}")
        lines.extend(f"  {suffix}={value}" for suffix, value in plan.fields)
        state = "ENABLED" if plan.enabled else "DISABLED"
        lines.append(f"  final state after basic --apply={state}")
        lines.append("")
    if not plans:
        lines.append("No assigned axes found.")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    project = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project))
    from kohzu_runtime import runtime_from_argv
    runtime_path, runtime = runtime_from_argv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-config", type=pathlib.Path,
                        default=runtime_path)
    parser.add_argument("--models", type=pathlib.Path,
                        default=project / "config" / "stage-models.ini")
    parser.add_argument("--axes", type=pathlib.Path,
                        default=project / "config" / "axis-assignments.ini")
    parser.add_argument("--prefix", default=runtime.epics_prefix)
    parser.add_argument("--sys16-limit", type=float, default=50000.0)
    parser.add_argument("--epics-bin", type=pathlib.Path,
                        default=runtime.epics_bin)
    parser.add_argument("--apply", action="store_true",
                        help="perform guarded CA writes; otherwise print only")
    parser.add_argument(
        "--development-guards", action="store_true",
        help="re-enable legacy Disable/stopped/commissioning checks",
    )
    arguments = parser.parse_args()
    try:
        if not PREFIX_PATTERN.fullmatch(arguments.prefix):
            raise ValueError("prefix contains unsupported characters")
        if not math.isfinite(arguments.sys16_limit) or arguments.sys16_limit < 2:
            raise ValueError("SYS.16 validation limit must be at least 2")
        plans, warnings = build_plans(arguments.models, arguments.axes,
                                      arguments.sys16_limit)
        print(render_plan(arguments.prefix, plans, warnings), end="")
        if arguments.apply:
            if not plans:
                raise ValueError("no assigned axes to apply")
            client = ChannelAccess(arguments.epics_bin)
            apply_plans(
                client, arguments.prefix, plans,
                development_guards=arguments.development_guards,
            )
            print(f"Applied {len(plans)} axis configurations")
    except (ValueError, KeyError, configparser.Error,
            subprocess.SubprocessError, OSError) as error:
        print(f"Stage configuration apply failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
