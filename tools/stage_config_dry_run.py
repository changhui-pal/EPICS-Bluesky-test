#!/usr/bin/env python3
"""Render reviewed stage assignments as a non-executable motor-record report."""

import argparse
import configparser
import math
import pathlib
import sys

import validate_stage_config as validator


def format_value(value: float) -> str:
    """Keep configuration values compact without hiding meaningful precision."""
    return format(value, ".12g")


def build_report(models_path: pathlib.Path, axes_path: pathlib.Path,
                 prefix: str, sys16_limit: float) -> str:
    """Validate inputs and return a report that contains no executable commands."""
    warnings = []
    models = validator.load_models(models_path, sys16_limit, warnings)
    validator.validate_axes(axes_path, models)
    axes = validator.read_ini(axes_path)

    lines = [
        "KOHZU STAGE CONFIGURATION DRY RUN",
        "NO IOC OR CONTROLLER VALUES WERE CHANGED",
        f"Assumed current SYS.16: {format_value(sys16_limit)} pulse/s",
        "",
    ]
    for warning in warnings:
        lines.append(f"WARNING: {warning}")
    if warnings:
        lines.append("")

    enabled_count = 0
    for axis in range(1, 33):
        section = axes[f"axis:{axis}"]
        if not section.getboolean("enabled"):
            continue
        enabled_count += 1
        model = models[section["model"].strip()]
        direction = section["direction"].strip()
        sensors = validator.parse_sensors(section, "sensors")
        home_method = section.getint("home_method", fallback=4)
        record = f"{prefix}m{axis}"
        required_sys16 = math.ceil(model.vmax / model.mres)
        lines.extend((
            f"Axis {axis}: model={model.name}",
            f"  record={record}",
            f"  DESC={model.description}",
            f"  EGU={model.egu}",
            f"  MRES={format_value(model.mres)} {model.egu}/pulse",
            f"  LLM={format_value(model.low_limit)} {model.egu}",
            f"  HLM={format_value(model.high_limit)} {model.egu}",
            f"  VMAX={format_value(model.vmax)} {model.egu}/s",
            f"  VELO={format_value(model.default_velocity)} {model.egu}/s",
            f"  VBAS={format_value(model.base_velocity)} {model.egu}/s",
            f"  ACCL={format_value(model.acceleration_time)} s",
            f"  DIR={direction}",
            f"  declared sensors={','.join(sorted(sensors)) or 'none'}",
            "  selectable home methods=1..15 (user responsibility)",
            f"  user-selected controller SYS.2 home_method={home_method}",
            f"  required SYS.16 >= {required_sys16} pulse/s",
            "  final state=DISABLED pending operator review and re-home",
            "",
        ))
    if enabled_count == 0:
        lines.append("No enabled axes; no motor-record field assignments generated.")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    project = pathlib.Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=pathlib.Path,
                        default=project / "config" / "stage-models.ini")
    parser.add_argument("--axes", type=pathlib.Path,
                        default=project / "config" / "axis-assignments.ini")
    parser.add_argument("--prefix", default="KOHZU:")
    parser.add_argument("--sys16-limit", type=float, default=50000.0)
    arguments = parser.parse_args()
    try:
        report = build_report(arguments.models, arguments.axes,
                              arguments.prefix, arguments.sys16_limit)
    except (ValueError, KeyError, configparser.Error) as error:
        print(f"Cannot create dry run: {error}", file=sys.stderr)
        return 1
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
