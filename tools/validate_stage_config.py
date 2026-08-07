#!/usr/bin/env python3
"""Validate KOHZU stage models and persistent axis assignments.

This tool only reads configuration. It never writes EPICS records or sends a
controller command, so it is safe to run before an IOC or hardware is present.
"""

import argparse
import configparser
import math
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Dict, List


MODEL_PREFIX = "model:"
AXIS_PREFIX = "axis:"
MODEL_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
SENSOR_NAMES = frozenset(("S1", "S2", "S3", "L+", "L-", "Z"))

# Required inputs are taken from ARIES/LYNX manual section 3-9. Method 10
# intentionally has no sensor requirement and sets the present position to 0.
HOME_METHOD_SENSORS = {
    1: frozenset(("S1", "S3")),
    2: frozenset(("S3",)),
    3: frozenset(("S1", "S2", "L-")),
    4: frozenset(("S2", "L-")),
    5: frozenset(("S1", "L+")),
    6: frozenset(("S1", "L-")),
    7: frozenset(("L+",)),
    8: frozenset(("L-",)),
    9: frozenset(("S1",)),
    10: frozenset(),
    11: frozenset(("Z",)),
    12: frozenset(("Z", "S3")),
    13: frozenset(("Z", "S2")),
    14: frozenset(("Z", "L+")),
    15: frozenset(("Z", "L-")),
}


@dataclass(frozen=True)
class StageModel:
    """Validated values used to populate one motor record."""

    name: str
    description: str
    egu: str
    mres: float
    low_limit: float
    high_limit: float
    vmax: float
    default_velocity: float
    base_velocity: float
    acceleration_time: float


def read_ini(path: pathlib.Path) -> configparser.ConfigParser:
    """Read an INI file without silently accepting a missing path."""
    parser = configparser.ConfigParser(interpolation=None)
    if not path.is_file():
        raise ValueError(f"configuration file does not exist: {path}")
    try:
        with path.open("r", encoding="utf-8") as stream:
            parser.read_file(stream)
    except (OSError, configparser.Error) as error:
        raise ValueError(f"cannot read {path}: {error}") from error
    return parser


def finite_float(section: configparser.SectionProxy, key: str) -> float:
    """Return a required finite floating-point option."""
    try:
        value = section.getfloat(key)
    except (ValueError, configparser.Error) as error:
        raise ValueError(f"[{section.name}] {key} must be a number") from error
    if value is None or not math.isfinite(value):
        raise ValueError(f"[{section.name}] {key} must be finite")
    return value


def parse_sensors(section: configparser.SectionProxy, key: str) -> frozenset:
    """Parse a comma-separated ARIES sensor inventory.

    The literal ``none`` is useful for an axis such as a manually referenced
    stage. Unknown sensor names are rejected instead of being silently ignored.
    """
    raw = section.get(key, "").strip()
    if not raw or raw.lower() == "none":
        return frozenset()
    sensors = frozenset(item.strip().upper() for item in raw.split(",") if item.strip())
    unknown = sorted(sensors - SENSOR_NAMES)
    if unknown:
        raise ValueError(f"[{section.name}] {key} has unknown sensors: {unknown}")
    return sensors


def allowed_home_methods(sensors: frozenset) -> List[int]:
    """Return methods whose complete sensor requirement is available."""
    return [method for method, required in HOME_METHOD_SENSORS.items()
            if required <= sensors]


def home_method_mask(sensors: frozenset) -> int:
    """Encode selectable methods using bit 0 for ARIES Method 1."""
    return sum(1 << (method - 1) for method in allowed_home_methods(sensors))


def wtb_time_range_ms(top_speed_pps: float) -> tuple:
    """Return manual section 3-1-3 time bounds for a top pulse speed."""
    ranges = (
        (20, 10, 100), (250, 10, 1000), (500000, 10, 10000),
        (1000000, 20, 20000), (2000000, 40, 40000),
        (5000000, 100, 100000),
    )
    for upper_speed, minimum_ms, maximum_ms in ranges:
        if top_speed_pps <= upper_speed:
            return minimum_ms, maximum_ms
    raise ValueError("top speed exceeds the WTB protocol maximum")


def load_models(path: pathlib.Path, sys16_limit: float,
                warnings: List[str] = None) -> Dict[str, StageModel]:
    """Load model sections and validate physical and pulse-domain limits."""
    parser = read_ini(path)
    models: Dict[str, StageModel] = {}
    for section_name in parser.sections():
        if not section_name.startswith(MODEL_PREFIX):
            raise ValueError(f"unexpected section [{section_name}] in model catalog")
        name = section_name[len(MODEL_PREFIX):]
        if not MODEL_NAME.fullmatch(name):
            raise ValueError(f"invalid model name: {name!r}")
        section = parser[section_name]
        description = section.get("description", "").strip()
        egu = section.get("egu", "").strip()
        if not description or not egu:
            raise ValueError(f"[{section_name}] description and egu are required")

        model = StageModel(
            name=name,
            description=description,
            egu=egu,
            mres=finite_float(section, "mres"),
            low_limit=finite_float(section, "low_limit"),
            high_limit=finite_float(section, "high_limit"),
            vmax=finite_float(section, "vmax"),
            default_velocity=finite_float(section, "default_velocity"),
            base_velocity=finite_float(section, "base_velocity"),
            acceleration_time=finite_float(section, "acceleration_time"),
        )
        if model.mres <= 0:
            raise ValueError(f"[{section_name}] mres must be positive; use DIR for reversal")
        if model.low_limit >= model.high_limit:
            raise ValueError(f"[{section_name}] low_limit must be below high_limit")
        if not (0 < model.base_velocity <= model.default_velocity <= model.vmax):
            raise ValueError(
                f"[{section_name}] require 0 < base_velocity <= default_velocity <= vmax")
        if model.acceleration_time <= 0:
            raise ValueError(f"[{section_name}] acceleration_time must be positive")

        base_pps = model.base_velocity / model.mres
        default_pps = model.default_velocity / model.mres
        vmax_pps = model.vmax / model.mres
        if base_pps < 1 or default_pps < 2:
            raise ValueError(f"[{section_name}] converted WTB speeds are too low")
        if base_pps * 2 > default_pps:
            raise ValueError(f"[{section_name}] base speed exceeds 50% of default speed")
        if vmax_pps > 5000000:
            raise ValueError(
                f"[{section_name}] vmax converts to {vmax_pps:g} pps, "
                "above the absolute WTB maximum 5000000 pps")
        if vmax_pps > sys16_limit and warnings is not None:
            warnings.append(
                f"[{section_name}] vmax requires at least SYS.16="
                f"{math.ceil(vmax_pps)} pulse/s; current validation value is "
                f"{sys16_limit:g}. Review stage/driver safety before changing SYS.16.")
        minimum_ms, maximum_ms = wtb_time_range_ms(default_pps)
        acceleration_ms = model.acceleration_time * 1000.0
        if not minimum_ms <= acceleration_ms <= maximum_ms:
            raise ValueError(
                f"[{section_name}] acceleration_time is outside "
                f"{minimum_ms}..{maximum_ms} ms for its default speed")
        models[name] = model
    return models


def validate_axes(path: pathlib.Path, models: Dict[str, StageModel]) -> int:
    """Require 32 stable slots and validate every enabled assignment."""
    parser = read_ini(path)
    seen = set()
    enabled_count = 0
    for section_name in parser.sections():
        if not section_name.startswith(AXIS_PREFIX):
            raise ValueError(f"unexpected section [{section_name}] in axis assignments")
        try:
            axis = int(section_name[len(AXIS_PREFIX):])
        except ValueError as error:
            raise ValueError(f"invalid axis section [{section_name}]") from error
        if axis < 1 or axis > 32 or axis in seen:
            raise ValueError(f"axis number must be unique and within 1..32: {axis}")
        seen.add(axis)
        section = parser[section_name]
        try:
            enabled = section.getboolean("enabled")
        except (ValueError, configparser.Error) as error:
            raise ValueError(f"[{section_name}] enabled must be true or false") from error
        # Empty disabled slots are valid persistent placeholders. Assigned
        # disabled slots are still checked so commissioning data cannot rot.
        model_name = section.get("model", "").strip()
        if not enabled and not model_name:
            continue
        if model_name not in models:
            raise ValueError(f"[{section_name}] unknown model: {model_name!r}")
        if enabled:
            enabled_count += 1
        direction = section.get("direction", "").strip()
        if direction not in ("Pos", "Neg"):
            raise ValueError(f"[{section_name}] direction must be Pos or Neg")
        sensors = parse_sensors(section, "sensors")
        faulty_sensors = parse_sensors(section, "faulty_sensors")
        overlap = sorted(sensors & faulty_sensors)
        if overlap:
            raise ValueError(
                f"[{section_name}] sensors also marked faulty: {overlap}")
        try:
            # ARIES defaults SYS.2 to method 4; make the same default explicit.
            home_method = section.getint("home_method", fallback=4)
        except (ValueError, configparser.Error) as error:
            raise ValueError(
                f"[{section_name}] home_method must be an integer") from error
        if home_method not in HOME_METHOD_SENSORS:
            raise ValueError(f"[{section_name}] home_method must be within 1..15")
        # Sensor inventory is retained for operator documentation, but it does
        # not restrict SYS.2. Choosing a suitable method is the user's duty.

    missing = sorted(set(range(1, 33)) - seen)
    if missing:
        raise ValueError(f"axis assignments must retain all 32 slots; missing {missing}")
    return enabled_count


def validate(models_path: pathlib.Path, axes_path: pathlib.Path,
             sys16_limit: float, warnings: List[str] = None) -> tuple:
    """Validate both files and return catalog and enabled-axis counts."""
    if not math.isfinite(sys16_limit) or sys16_limit < 2:
        raise ValueError("SYS.16 validation limit must be at least 2 pulse/s")
    models = load_models(models_path, sys16_limit, warnings)
    enabled_count = validate_axes(axes_path, models)
    return len(models), enabled_count


def main() -> int:
    project = pathlib.Path(__file__).resolve().parents[1]
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument(
        "--models", type=pathlib.Path,
        default=project / "config" / "stage-models.ini")
    argument_parser.add_argument(
        "--axes", type=pathlib.Path,
        default=project / "config" / "axis-assignments.ini")
    argument_parser.add_argument(
        "--sys16-limit", type=float, default=50000.0,
        help="current comparison value in pulse/s; default is factory SYS.16=50000")
    arguments = argument_parser.parse_args()
    try:
        warnings: List[str] = []
        model_count, enabled_count = validate(
            arguments.models, arguments.axes, arguments.sys16_limit, warnings)
    except ValueError as error:
        print(f"Stage configuration invalid: {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"Stage configuration warning: {warning}")
    print(
        f"Stage configuration valid: {model_count} models, "
        f"{enabled_count} enabled axes, current SYS.16 comparison "
        f"{arguments.sys16_limit:g} pulse/s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
