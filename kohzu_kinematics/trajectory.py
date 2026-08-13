"""Hardware-independent trajectory sampling and dry-run reporting."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Optional, Sequence, Tuple

from .fixed_point import (
    AXIS_NAMES,
    AxisLimits,
    FixedPointGeometry,
    StagePose,
    Vector3,
    calculate_fixed_point_move,
)


AxisValues = Mapping[str, float]


def _finite_float(value: float, name: str) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be a finite number")
    return converted


def _axis_difference(later: StagePose, earlier: StagePose) -> Mapping[str, float]:
    later_values = later.axis_values()
    earlier_values = earlier.axis_values()
    return {axis: later_values[axis] - earlier_values[axis] for axis in AXIS_NAMES}


def _axis_scale(values: Mapping[str, float], scale: float) -> Mapping[str, float]:
    return {axis: values[axis] * scale for axis in AXIS_NAMES}


@dataclass(frozen=True)
class TrajectorySample:
    """One endpoint-corrected sample in a dry-run trajectory."""

    index: int
    fraction: float
    time_s: float
    pose: StagePose
    velocity_from_previous: Optional[AxisValues]
    acceleration_from_previous: Optional[AxisValues]
    residual_mm: Vector3
    residual_norm_mm: float
    limit_results: Mapping[str, bool]
    all_within_limits: Optional[bool]


@dataclass(frozen=True)
class FixedPointTrajectory:
    """Sampled joint-space path with fixed-point and limit diagnostics."""

    fixed_point_surface_mm: Vector3
    current_pose: StagePose
    target_pose: StagePose
    duration_s: float
    intervals: int
    samples: Tuple[TrajectorySample, ...]
    maximum_residual_mm: float
    maximum_abs_velocity: AxisValues
    maximum_abs_acceleration: AxisValues
    maximum_abs_excursion: AxisValues
    first_limit_failure_index: Optional[int]
    first_limit_failure_axes: Tuple[str, ...]
    all_within_limits: Optional[bool]
    collision_checked: bool
    geometry: FixedPointGeometry


def sample_fixed_point_trajectory(
    *,
    fixed_point_surface_mm: Sequence[float] | Vector3,
    current_xyz_mm: Sequence[float] | Vector3,
    current_pitch_deg: float,
    current_yaw_deg: float,
    target_pitch_deg: float,
    target_yaw_deg: float,
    duration_s: float,
    intervals: int,
    geometry: FixedPointGeometry = FixedPointGeometry(),
    limits: Optional[Mapping[str, AxisLimits | Sequence[float]]] = None,
) -> FixedPointTrajectory:
    """Sample a linear Pitch/Yaw path while correcting X/Y/Z endpoints.

    ``intervals`` equal segments produce ``intervals + 1`` samples including
    both endpoints.  Velocity and acceleration are finite-difference
    diagnostics, not a controller-ready acceleration profile.  In
    particular, acceleration discontinuities before the first and after the
    final sample are not represented.
    """
    duration = _finite_float(duration_s, "duration_s")
    if duration <= 0.0:
        raise ValueError("duration_s must be positive")
    if isinstance(intervals, bool) or not isinstance(intervals, int) or intervals < 1:
        raise ValueError("intervals must be a positive integer")

    current_pitch = _finite_float(current_pitch_deg, "current_pitch_deg")
    current_yaw = _finite_float(current_yaw_deg, "current_yaw_deg")
    target_pitch = _finite_float(target_pitch_deg, "target_pitch_deg")
    target_yaw = _finite_float(target_yaw_deg, "target_yaw_deg")
    time_step = duration / intervals

    moves = []
    for index in range(intervals + 1):
        fraction = index / intervals
        pitch = current_pitch + (target_pitch - current_pitch) * fraction
        yaw = current_yaw + (target_yaw - current_yaw) * fraction
        moves.append(
            calculate_fixed_point_move(
                fixed_point_surface_mm=fixed_point_surface_mm,
                current_xyz_mm=current_xyz_mm,
                current_pitch_deg=current_pitch,
                current_yaw_deg=current_yaw,
                target_pitch_deg=pitch,
                target_yaw_deg=yaw,
                geometry=geometry,
                limits=limits,
            )
        )

    velocities = [None]
    for index in range(1, len(moves)):
        delta = _axis_difference(moves[index].target_pose, moves[index - 1].target_pose)
        velocities.append(_axis_scale(delta, 1.0 / time_step))

    accelerations = [None, None]
    for index in range(2, len(moves)):
        velocity_change = {
            axis: velocities[index][axis] - velocities[index - 1][axis]
            for axis in AXIS_NAMES
        }
        accelerations.append(_axis_scale(velocity_change, 1.0 / time_step))
    accelerations = accelerations[:len(moves)]

    samples = tuple(
        TrajectorySample(
            index=index,
            fraction=index / intervals,
            time_s=index * time_step,
            pose=move.target_pose,
            velocity_from_previous=velocities[index],
            acceleration_from_previous=accelerations[index],
            residual_mm=move.residual_mm,
            residual_norm_mm=move.residual_norm_mm,
            limit_results=move.limit_results,
            all_within_limits=move.all_within_limits,
        )
        for index, move in enumerate(moves)
    )

    maximum_abs_velocity = {
        axis: max(
            (abs(sample.velocity_from_previous[axis]) for sample in samples
             if sample.velocity_from_previous is not None),
            default=0.0,
        )
        for axis in AXIS_NAMES
    }
    maximum_abs_acceleration = {
        axis: max(
            (abs(sample.acceleration_from_previous[axis]) for sample in samples
             if sample.acceleration_from_previous is not None),
            default=0.0,
        )
        for axis in AXIS_NAMES
    }
    current_pose = moves[0].current_pose
    current_values = current_pose.axis_values()
    maximum_abs_excursion = {
        axis: max(
            abs(sample.pose.axis_values()[axis] - current_values[axis])
            for sample in samples
        )
        for axis in AXIS_NAMES
    }

    first_failure_index = None
    first_failure_axes: Tuple[str, ...] = ()
    limits_evaluated = any(
        sample.all_within_limits is not None for sample in samples
    )
    if limits_evaluated:
        for sample in samples:
            failed = tuple(
                axis
                for axis in AXIS_NAMES
                if axis in sample.limit_results and not sample.limit_results[axis]
            )
            if failed:
                first_failure_index = sample.index
                first_failure_axes = failed
                break
        all_within_limits: Optional[bool] = first_failure_index is None
    else:
        all_within_limits = None

    return FixedPointTrajectory(
        fixed_point_surface_mm=moves[0].fixed_point_surface_mm,
        current_pose=current_pose,
        target_pose=moves[-1].target_pose,
        duration_s=duration,
        intervals=intervals,
        samples=samples,
        maximum_residual_mm=max(sample.residual_norm_mm for sample in samples),
        maximum_abs_velocity=maximum_abs_velocity,
        maximum_abs_acceleration=maximum_abs_acceleration,
        maximum_abs_excursion=maximum_abs_excursion,
        first_limit_failure_index=first_failure_index,
        first_limit_failure_axes=first_failure_axes,
        all_within_limits=all_within_limits,
        collision_checked=False,
        geometry=geometry,
    )


def format_trajectory_report(trajectory: FixedPointTrajectory) -> str:
    """Format a deterministic human-reviewable dry-run report."""
    fixed = trajectory.fixed_point_surface_mm
    current = trajectory.current_pose
    target = trajectory.target_pose
    lines = [
        "Fixed-point trajectory dry-run (NO HARDWARE WRITES)",
        (
            "Fixed point in Yaw-surface frame [mm]: "
            f"({fixed.x:.6f}, {fixed.y:.6f}, {fixed.z:.6f})"
        ),
        (
            "Current pose: "
            f"X={current.x_mm:.6f} mm Y={current.y_mm:.6f} mm "
            f"Z={current.z_mm:.6f} mm Pitch={current.pitch_deg:.6f} deg "
            f"Yaw={current.yaw_deg:.6f} deg"
        ),
        (
            "Target pose:  "
            f"X={target.x_mm:.6f} mm Y={target.y_mm:.6f} mm "
            f"Z={target.z_mm:.6f} mm Pitch={target.pitch_deg:.6f} deg "
            f"Yaw={target.yaw_deg:.6f} deg"
        ),
        (
            f"Path: joint-space linear, duration={trajectory.duration_s:.6f} s, "
            f"intervals={trajectory.intervals}, samples={len(trajectory.samples)}"
        ),
        f"Maximum fixed-point residual: {trajectory.maximum_residual_mm:.12g} mm",
    ]

    for label, values, linear_unit, angular_unit in (
        ("Maximum absolute excursion", trajectory.maximum_abs_excursion, "mm", "deg"),
        ("Maximum sampled velocity", trajectory.maximum_abs_velocity, "mm/s", "deg/s"),
        (
            "Maximum sampled acceleration",
            trajectory.maximum_abs_acceleration,
            "mm/s^2",
            "deg/s^2",
        ),
    ):
        lines.append(
            f"{label}: "
            f"X={values['x']:.6f} {linear_unit} "
            f"Y={values['y']:.6f} {linear_unit} "
            f"Z={values['z']:.6f} {linear_unit} "
            f"Pitch={values['pitch']:.6f} {angular_unit} "
            f"Yaw={values['yaw']:.6f} {angular_unit}"
        )

    if trajectory.all_within_limits is None:
        lines.append("Software limits: NOT EVALUATED")
    elif trajectory.all_within_limits:
        lines.append("Software limits: PASS at every sample")
    else:
        lines.append(
            "Software limits: FAIL at sample "
            f"{trajectory.first_limit_failure_index} "
            f"axes={','.join(trajectory.first_limit_failure_axes)}"
        )
    lines.extend(
        (
            "Collision checked: false",
            (
                "Acceleration note: finite differences exclude start/stop "
                "profile discontinuities."
            ),
        )
    )
    return "\n".join(lines)
