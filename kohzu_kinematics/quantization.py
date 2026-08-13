"""Quantize continuous fixed-point samples to motor-record user coordinates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Mapping

from .fixed_point import AXIS_NAMES, AxisLimits, StagePose, world_fixed_point
from .trajectory import FixedPointTrajectory


@dataclass(frozen=True)
class AxisQuantization:
    """One motor record's user/dial coordinate relation."""

    mres: float
    offset: float
    direction: int  # 0=Pos, 1=Neg, matching motor record DIR

    def __post_init__(self) -> None:
        if not math.isfinite(self.mres) or self.mres <= 0:
            raise ValueError("MRES must be positive and finite")
        if not math.isfinite(self.offset):
            raise ValueError("OFF must be finite")
        if self.direction not in (0, 1):
            raise ValueError("DIR must be 0 (Pos) or 1 (Neg)")

    def user_target(self, target: float) -> float:
        """Return nearest representable user coordinate, half away from zero."""
        sign = Decimal(1) if self.direction == 0 else Decimal(-1)
        resolution = Decimal(str(self.mres))
        offset = Decimal(str(self.offset))
        dial_pulses = ((Decimal(str(target)) - offset) / sign) / resolution
        pulses = dial_pulses.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return float(offset + sign * pulses * resolution)


def _pose(values: Mapping[str, float]) -> StagePose:
    return StagePose(values["x"], values["y"], values["z"],
                     values["pitch"], values["yaw"])


def quantize_trajectory(
    trajectory: FixedPointTrajectory,
    quantization: Mapping[str, AxisQuantization],
    limits: Mapping[str, AxisLimits] | None = None,
) -> FixedPointTrajectory:
    """Replace every sample by executable user targets and recompute diagnostics."""
    if set(quantization) != set(AXIS_NAMES):
        raise ValueError("quantization must define x, y, z, pitch and yaw")

    poses = []
    for sample in trajectory.samples:
        continuous = sample.pose.axis_values()
        poses.append(_pose({
            axis: quantization[axis].user_target(continuous[axis])
            for axis in AXIS_NAMES
        }))

    dt = trajectory.duration_s / trajectory.intervals
    velocities = [None]
    for before, after in zip(poses, poses[1:]):
        a, b = before.axis_values(), after.axis_values()
        velocities.append({axis: (b[axis] - a[axis]) / dt for axis in AXIS_NAMES})
    accelerations = [None, None]
    for previous, current in zip(velocities[1:], velocities[2:]):
        accelerations.append({
            axis: (current[axis] - previous[axis]) / dt for axis in AXIS_NAMES
        })
    accelerations = accelerations[:len(poses)]

    fixed_before = world_fixed_point(
        trajectory.current_pose, trajectory.fixed_point_surface_mm,
        trajectory.geometry,
    )
    samples = []
    for old, pose, velocity, acceleration in zip(
        trajectory.samples, poses, velocities, accelerations
    ):
        residual = world_fixed_point(
            pose, trajectory.fixed_point_surface_mm, trajectory.geometry
        ) - fixed_before
        limit_results = (
            {axis: limit.contains(pose.axis_values()[axis])
             for axis, limit in limits.items()}
            if limits is not None else dict(old.limit_results)
        )
        all_within = all(limit_results.values()) if limit_results else None
        samples.append(replace(
            old, pose=pose, velocity_from_previous=velocity,
            acceleration_from_previous=acceleration, residual_mm=residual,
            residual_norm_mm=residual.norm, limit_results=limit_results,
            all_within_limits=all_within,
        ))

    current = trajectory.current_pose.axis_values()
    max_velocity = {axis: max(
        (abs(s.velocity_from_previous[axis]) for s in samples
         if s.velocity_from_previous is not None), default=0.0
    ) for axis in AXIS_NAMES}
    max_acceleration = {axis: max(
        (abs(s.acceleration_from_previous[axis]) for s in samples
         if s.acceleration_from_previous is not None), default=0.0
    ) for axis in AXIS_NAMES}
    max_excursion = {axis: max(
        abs(s.pose.axis_values()[axis] - current[axis]) for s in samples
    ) for axis in AXIS_NAMES}

    first_failure = next(
        (s for s in samples if s.all_within_limits is False), None
    )
    return replace(
        trajectory,
        target_pose=poses[-1], samples=tuple(samples),
        maximum_residual_mm=max(s.residual_norm_mm for s in samples),
        maximum_abs_velocity=max_velocity,
        maximum_abs_acceleration=max_acceleration,
        maximum_abs_excursion=max_excursion,
        first_limit_failure_index=(first_failure.index if first_failure else None),
        first_limit_failure_axes=(
            tuple(axis for axis, passed in first_failure.limit_results.items() if not passed)
            if first_failure else ()
        ),
        all_within_limits=(
            all(s.all_within_limits is not False for s in samples)
            if limits is not None else trajectory.all_within_limits
        ),
    )
