"""Read-only five-axis snapshots and fixed-point dry-run preflight."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import pathlib
import subprocess
import time
from typing import Mapping, Protocol, Sequence, Tuple

from .fixed_point import AxisLimits, FixedPointGeometry
from .trajectory import FixedPointTrajectory, sample_fixed_point_trajectory
from .quantization import AxisQuantization, quantize_trajectory


AXIS_ROLES = {"x": 1, "y": 2, "z": 3, "pitch": 4, "yaw": 5}
DYNAMIC_FIELDS = ("RBV", "DMOV", "MOVN", "HLS", "LLS", "LVIO")
CONFIG_FIELDS = ("LLM", "HLM", "MRES", "OFF", "DIR")


@dataclass(frozen=True)
class PVReading:
    """One numeric Channel Access reading with server timestamp."""

    value: float
    timestamp: float
    status: str = "NO_ALARM"
    severity: str = "NO_ALARM"
    server_timestamp_defined: bool = True

    def __post_init__(self) -> None:
        for name in ("value", "timestamp"):
            try:
                converted = float(getattr(self, name))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"PV {name} must be finite") from exc
            if not math.isfinite(converted):
                raise ValueError(f"PV {name} must be finite")
            object.__setattr__(self, name, converted)


class NumericPVReader(Protocol):
    """Minimal injectable interface used by the snapshot layer."""

    def read(self, pvs: Sequence[str]) -> Mapping[str, PVReading]:
        """Return one reading for every requested PV or raise on disconnect."""


@dataclass(frozen=True)
class AxisSnapshot:
    role: str
    axis: int
    position: float
    done: bool
    moving: bool
    high_limit_active: bool
    low_limit_active: bool
    soft_limit_violation: bool
    limits: AxisLimits
    quantization: AxisQuantization
    newest_dynamic_timestamp: float
    oldest_dynamic_timestamp: float


@dataclass(frozen=True)
class FiveAxisSnapshot:
    prefix: str
    captured_at: float
    axes: Mapping[str, AxisSnapshot]
    emergency_active: bool
    emergency_timestamp: float
    maximum_dynamic_age_s: float
    server_timestamps_complete: bool


@dataclass(frozen=True)
class SnapshotDryRun:
    snapshot: FiveAxisSnapshot
    continuous_trajectory: FixedPointTrajectory
    trajectory: FixedPointTrajectory


class SnapshotPreflightError(RuntimeError):
    """Raised before calculation when the read-only hardware state is unsafe."""


class CagetNumericReader:
    """Read numeric PVs using only EPICS ``caget`` wide-mode requests."""

    def __init__(self, epics_bin: pathlib.Path, timeout_s: float = 3.0):
        self.caget = epics_bin / "caget"
        if not self.caget.is_file():
            raise ValueError(f"caget not found in {epics_bin}")
        if timeout_s <= 0 or not math.isfinite(timeout_s):
            raise ValueError("timeout_s must be positive and finite")
        self.timeout_s = float(timeout_s)

    @staticmethod
    def _timestamp(text: str, observed_at: float) -> Tuple[float, bool]:
        if text == "<undefined>":
            # Passive motor records can retain an undefined record timestamp
            # while their fields are synchronously readable and updated by
            # driver callbacks. In that case freshness means the successful
            # completion time of this CA get, not a server event timestamp.
            return observed_at, False
        # caget uses local ISO time.  A timezone suffix, when present, is
        # honored; otherwise use the local system timezone consistently with
        # caget and time.time().
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.astimezone(timezone.utc).timestamp(), True

    def read(self, pvs: Sequence[str]) -> Mapping[str, PVReading]:
        if not pvs:
            return {}
        command = [
            str(self.caget), "-w", str(self.timeout_s), "-a", "-n", "-F", "\t", *pvs
        ]
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_s + 1.0,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise SnapshotPreflightError("Channel Access snapshot read failed") from exc

        readings = {}
        observed_at = time.time()
        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) != 5:
                raise SnapshotPreflightError("unexpected caget wide-mode output")
            pv, timestamp_text, value_text, status, severity = fields
            try:
                timestamp, timestamp_defined = self._timestamp(
                    timestamp_text, observed_at
                )
                readings[pv] = PVReading(
                    float(value_text), timestamp, status, severity,
                    timestamp_defined,
                )
            except ValueError as exc:
                raise SnapshotPreflightError(f"invalid numeric PV value for {pv}") from exc
        missing = [pv for pv in pvs if pv not in readings]
        if missing:
            raise SnapshotPreflightError(
                "snapshot omitted PVs: " + ", ".join(missing)
            )
        return readings


def _binary(reading: PVReading, pv: str) -> bool:
    if reading.value not in (0.0, 1.0):
        raise SnapshotPreflightError(f"{pv} must be 0 or 1")
    return bool(reading.value)


def capture_five_axis_snapshot(
    reader: NumericPVReader,
    *,
    prefix: str,
    now: float | None = None,
    maximum_age_s: float = 5.0,
) -> FiveAxisSnapshot:
    """Capture and validate one complete read-only five-axis snapshot."""
    captured_at = time.time() if now is None else float(now)
    if not math.isfinite(captured_at):
        raise ValueError("now must be finite")
    if maximum_age_s <= 0 or not math.isfinite(maximum_age_s):
        raise ValueError("maximum_age_s must be positive and finite")

    pvs = []
    for axis in AXIS_ROLES.values():
        base = f"{prefix}m{axis}."
        pvs.extend(base + field for field in DYNAMIC_FIELDS + CONFIG_FIELDS)
    emergency_pv = f"{prefix}Recovery:EmergencyActive"
    pvs.append(emergency_pv)
    readings = reader.read(pvs)
    missing = [pv for pv in pvs if pv not in readings]
    if missing:
        raise SnapshotPreflightError(
            "snapshot omitted PVs: " + ", ".join(missing)
        )

    for pv, reading in readings.items():
        # EPICS caget wide mode leaves both columns empty for NO_ALARM on
        # some Base builds. A motor record intentionally held by SDIS reports
        # DISABLE/NO_ALARM; this is the required preflight operating state,
        # not an alarm severity.
        alarm_clear = (
            (reading.status, reading.severity) == ("NO_ALARM", "NO_ALARM")
            or (reading.status, reading.severity) == ("DISABLE", "NO_ALARM")
            or (reading.status, reading.severity) == ("", "")
        )
        if not alarm_clear:
            raise SnapshotPreflightError(
                f"{pv} alarm is {reading.status}/{reading.severity}"
            )

    axes = {}
    dynamic_timestamps = []
    for role, axis in AXIS_ROLES.items():
        base = f"{prefix}m{axis}."
        dynamic = {field: readings[base + field] for field in DYNAMIC_FIELDS}
        timestamps = [reading.timestamp for reading in dynamic.values()]
        dynamic_timestamps.extend(timestamps)
        axes[role] = AxisSnapshot(
            role=role,
            axis=axis,
            position=dynamic["RBV"].value,
            done=_binary(dynamic["DMOV"], base + "DMOV"),
            moving=_binary(dynamic["MOVN"], base + "MOVN"),
            high_limit_active=_binary(dynamic["HLS"], base + "HLS"),
            low_limit_active=_binary(dynamic["LLS"], base + "LLS"),
            soft_limit_violation=_binary(dynamic["LVIO"], base + "LVIO"),
            limits=AxisLimits(
                readings[base + "LLM"].value,
                readings[base + "HLM"].value,
            ),
            quantization=AxisQuantization(
                readings[base + "MRES"].value,
                readings[base + "OFF"].value,
                int(readings[base + "DIR"].value),
            ),
            newest_dynamic_timestamp=max(timestamps),
            oldest_dynamic_timestamp=min(timestamps),
        )

    emergency = readings[emergency_pv]
    # EmergencyActive is event-driven (I/O Intr), so an unchanged Clear value
    # can legitimately retain the IOC-start timestamp. Validate its value,
    # alarm and successful CA read, but exclude its timestamp from freshness.
    oldest = min(dynamic_timestamps)
    if oldest > captured_at + 1.0:
        raise SnapshotPreflightError("snapshot timestamp is in the future")
    # Undefined passive-record timestamps use the synchronous CA observation
    # completion time, which can be slightly later than capture start.
    maximum_age = max(0.0, captured_at - oldest)
    if maximum_age > maximum_age_s:
        raise SnapshotPreflightError(
            f"stale snapshot: maximum dynamic age {maximum_age:.3f} s"
        )

    return FiveAxisSnapshot(
        prefix=prefix,
        captured_at=captured_at,
        axes=axes,
        emergency_active=_binary(emergency, emergency_pv),
        emergency_timestamp=emergency.timestamp,
        maximum_dynamic_age_s=maximum_age,
        server_timestamps_complete=all(
            readings[pv].server_timestamp_defined
            for pv in pvs
            if pv.endswith(tuple("." + field for field in DYNAMIC_FIELDS))
        ),
    )


def calculate_snapshot_dry_run(
    snapshot: FiveAxisSnapshot,
    *,
    fixed_point_surface_mm: Sequence[float],
    target_pitch_deg: float,
    target_yaw_deg: float,
    duration_s: float,
    intervals: int,
    geometry: FixedPointGeometry = FixedPointGeometry(),
) -> SnapshotDryRun:
    """Run trajectory calculation only after a safe snapshot preflight."""
    failures = []
    if snapshot.emergency_active:
        failures.append("controller emergency input is active")
    for role in AXIS_ROLES:
        axis = snapshot.axes.get(role)
        if axis is None:
            failures.append(f"missing {role} axis")
            continue
        if not axis.done or axis.moving:
            failures.append(f"{role} axis is not stopped")
        if axis.high_limit_active or axis.low_limit_active:
            failures.append(f"{role} hardware limit is active")
        if axis.soft_limit_violation:
            failures.append(f"{role} soft-limit violation is active")
    if failures:
        raise SnapshotPreflightError("; ".join(failures))

    axes = snapshot.axes
    limits = {role: axis.limits for role, axis in axes.items()}
    continuous = sample_fixed_point_trajectory(
        fixed_point_surface_mm=fixed_point_surface_mm,
        current_xyz_mm=(axes["x"].position, axes["y"].position, axes["z"].position),
        current_pitch_deg=axes["pitch"].position,
        current_yaw_deg=axes["yaw"].position,
        target_pitch_deg=target_pitch_deg,
        target_yaw_deg=target_yaw_deg,
        duration_s=duration_s,
        intervals=intervals,
        geometry=geometry,
        limits=limits,
    )
    trajectory = quantize_trajectory(
        continuous,
        {role: axis.quantization for role, axis in axes.items()},
        limits=limits,
    )
    return SnapshotDryRun(
        snapshot=snapshot,
        continuous_trajectory=continuous,
        trajectory=trajectory,
    )
