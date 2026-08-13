"""Endpoint kinematics for holding a point fixed during Pitch/Yaw changes.

The public stage convention is the one verified on the physical stack:

* +X is forward.
* +Y is right.
* +Z is up.
* +Pitch raises the forward side.
* +Yaw is clockwise when viewed from above.

Those translation directions form a left-handed frame.  Calculations use a
right-handed frame with ``Xc=Xstage``, ``Yc=-Ystage`` and ``Zc=Zstage``.
Angles remain expressed in the public EPICS convention.

This module performs calculations only.  It has no EPICS, Ophyd, controller,
enable, home, stop, or motion side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Optional, Sequence, Tuple


Matrix3 = Tuple[
    Tuple[float, float, float],
    Tuple[float, float, float],
    Tuple[float, float, float],
]

AXIS_NAMES = ("x", "y", "z", "pitch", "yaw")


def _finite_float(value: float, name: str) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be a finite number")
    return converted


@dataclass(frozen=True)
class Vector3:
    """A three-dimensional vector in millimetres."""

    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", _finite_float(self.x, "x"))
        object.__setattr__(self, "y", _finite_float(self.y, "y"))
        object.__setattr__(self, "z", _finite_float(self.z, "z"))

    def __add__(self, other: "Vector3") -> "Vector3":
        return Vector3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vector3") -> "Vector3":
        return Vector3(self.x - other.x, self.y - other.y, self.z - other.z)

    @property
    def norm(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def as_tuple(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass(frozen=True)
class StagePose:
    """Five-axis pose in public EPICS coordinates."""

    x_mm: float
    y_mm: float
    z_mm: float
    pitch_deg: float
    yaw_deg: float

    def __post_init__(self) -> None:
        for field_name in ("x_mm", "y_mm", "z_mm", "pitch_deg", "yaw_deg"):
            object.__setattr__(
                self,
                field_name,
                _finite_float(getattr(self, field_name), field_name),
            )

    def axis_values(self) -> Mapping[str, float]:
        return {
            "x": self.x_mm,
            "y": self.y_mm,
            "z": self.z_mm,
            "pitch": self.pitch_deg,
            "yaw": self.yaw_deg,
        }


@dataclass(frozen=True)
class FixedPointGeometry:
    """Nominal geometry shared by the idealized rotation axes.

    ``pitch_center_above_yaw_surface_mm`` is positive when the common
    Pitch/Yaw axis intersection is above the Yaw table surface.
    """

    pitch_center_above_yaw_surface_mm: float = 38.0

    def __post_init__(self) -> None:
        distance = _finite_float(
            self.pitch_center_above_yaw_surface_mm,
            "pitch_center_above_yaw_surface_mm",
        )
        if distance < 0.0:
            raise ValueError("pitch center distance must be non-negative")
        object.__setattr__(self, "pitch_center_above_yaw_surface_mm", distance)


@dataclass(frozen=True)
class AxisLimits:
    """Inclusive software limits for one stage axis."""

    low: float
    high: float

    def __post_init__(self) -> None:
        low = _finite_float(self.low, "low limit")
        high = _finite_float(self.high, "high limit")
        if low >= high:
            raise ValueError("low limit must be below high limit")
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "high", high)

    def contains(self, value: float) -> bool:
        checked = _finite_float(value, "axis target")
        return self.low <= checked <= self.high


@dataclass(frozen=True)
class FixedPointMove:
    """Calculated endpoint move with no hardware side effects."""

    fixed_point_surface_mm: Vector3
    current_pose: StagePose
    target_pose: StagePose
    delta_pose: StagePose
    fixed_world_before_mm: Vector3
    fixed_world_after_mm: Vector3
    residual_mm: Vector3
    residual_norm_mm: float
    limit_results: Mapping[str, bool]
    all_within_limits: Optional[bool]
    geometry: FixedPointGeometry


def _vector3(values: Sequence[float], name: str) -> Vector3:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must contain exactly three finite numbers")
    try:
        if len(values) != 3:
            raise ValueError
        return Vector3(values[0], values[1], values[2])
    except (TypeError, IndexError, ValueError) as exc:
        raise ValueError(f"{name} must contain exactly three finite numbers") from exc


def stage_translation_to_calculation(stage_mm: Vector3) -> Vector3:
    """Convert public stage X/Y/Z into the internal right-handed frame."""
    return Vector3(stage_mm.x, -stage_mm.y, stage_mm.z)


def calculation_translation_to_stage(calculation_mm: Vector3) -> Vector3:
    """Convert the internal right-handed translation back to stage X/Y/Z."""
    return Vector3(calculation_mm.x, -calculation_mm.y, calculation_mm.z)


def surface_point_to_calculation(
    fixed_point_surface_mm: Sequence[float] | Vector3,
    geometry: FixedPointGeometry = FixedPointGeometry(),
) -> Vector3:
    """Convert a Yaw-surface point to the common-axis calculation frame."""
    point = (
        fixed_point_surface_mm
        if isinstance(fixed_point_surface_mm, Vector3)
        else _vector3(fixed_point_surface_mm, "fixed_point_surface_mm")
    )
    return Vector3(
        point.x,
        -point.y,
        point.z - geometry.pitch_center_above_yaw_surface_mm,
    )


def rotation_matrix(pitch_deg: float, yaw_deg: float) -> Matrix3:
    """Return ``Ry(-Pitch) * Rz(-Yaw)`` for the verified stage signs."""
    pitch = math.radians(_finite_float(pitch_deg, "pitch_deg"))
    yaw = math.radians(_finite_float(yaw_deg, "yaw_deg"))
    cp = math.cos(pitch)
    sp = math.sin(pitch)
    cy = math.cos(yaw)
    sy = math.sin(yaw)

    # Ry(-p) @ Rz(-y), expanded to keep the convention visible and avoid a
    # numerical-library dependency in the hardware-independent model.
    return (
        (cp * cy, cp * sy, -sp),
        (-sy, cy, 0.0),
        (sp * cy, sp * sy, cp),
    )


def _rotate(matrix: Matrix3, vector: Vector3) -> Vector3:
    return Vector3(
        matrix[0][0] * vector.x
        + matrix[0][1] * vector.y
        + matrix[0][2] * vector.z,
        matrix[1][0] * vector.x
        + matrix[1][1] * vector.y
        + matrix[1][2] * vector.z,
        matrix[2][0] * vector.x
        + matrix[2][1] * vector.y
        + matrix[2][2] * vector.z,
    )


def world_fixed_point(
    pose: StagePose,
    fixed_point_surface_mm: Sequence[float] | Vector3,
    geometry: FixedPointGeometry = FixedPointGeometry(),
) -> Vector3:
    """Calculate the fixed point's world position in the right-handed frame."""
    point = surface_point_to_calculation(fixed_point_surface_mm, geometry)
    translation = stage_translation_to_calculation(
        Vector3(pose.x_mm, pose.y_mm, pose.z_mm)
    )
    return translation + _rotate(
        rotation_matrix(pose.pitch_deg, pose.yaw_deg),
        point,
    )


def _normalize_limits(
    limits: Optional[Mapping[str, AxisLimits | Sequence[float]]],
) -> Mapping[str, AxisLimits]:
    if limits is None:
        return {}
    unknown = set(limits) - set(AXIS_NAMES)
    if unknown:
        raise ValueError(f"unknown axis limits: {', '.join(sorted(unknown))}")

    normalized = {}
    for axis, value in limits.items():
        if isinstance(value, AxisLimits):
            normalized[axis] = value
            continue
        if isinstance(value, (str, bytes)):
            raise ValueError(f"limits for {axis} must contain low and high")
        try:
            if len(value) != 2:
                raise ValueError
            normalized[axis] = AxisLimits(value[0], value[1])
        except (TypeError, IndexError, ValueError) as exc:
            raise ValueError(f"limits for {axis} must contain low and high") from exc
    return normalized


def calculate_fixed_point_move(
    *,
    fixed_point_surface_mm: Sequence[float] | Vector3,
    current_xyz_mm: Sequence[float] | Vector3,
    current_pitch_deg: float,
    current_yaw_deg: float,
    target_pitch_deg: float,
    target_yaw_deg: float,
    geometry: FixedPointGeometry = FixedPointGeometry(),
    limits: Optional[Mapping[str, AxisLimits | Sequence[float]]] = None,
) -> FixedPointMove:
    """Calculate the endpoint pose that holds a surface-defined point fixed.

    ``limits`` is an optional mapping using the public EPICS axis names
    ``x``, ``y``, ``z``, ``pitch`` and ``yaw``.  Limit evaluation is
    inclusive and reports results; it never moves or enables an axis.
    """
    fixed_surface = (
        fixed_point_surface_mm
        if isinstance(fixed_point_surface_mm, Vector3)
        else _vector3(fixed_point_surface_mm, "fixed_point_surface_mm")
    )
    current_xyz = (
        current_xyz_mm
        if isinstance(current_xyz_mm, Vector3)
        else _vector3(current_xyz_mm, "current_xyz_mm")
    )
    current_pose = StagePose(
        current_xyz.x,
        current_xyz.y,
        current_xyz.z,
        current_pitch_deg,
        current_yaw_deg,
    )
    target_pitch = _finite_float(target_pitch_deg, "target_pitch_deg")
    target_yaw = _finite_float(target_yaw_deg, "target_yaw_deg")

    point_calculation = surface_point_to_calculation(fixed_surface, geometry)
    fixed_before = world_fixed_point(current_pose, fixed_surface, geometry)
    if (
        target_pitch == current_pose.pitch_deg
        and target_yaw == current_pose.yaw_deg
    ):
        # Preserve an unchanged pose exactly.  A rotate/subtract round trip
        # can otherwise introduce a harmless ~1e-16 mm representation drift
        # at the first trajectory sample.
        target_translation_stage = current_xyz
    else:
        rotated_at_target = _rotate(
            rotation_matrix(target_pitch, target_yaw),
            point_calculation,
        )
        target_translation_calculation = fixed_before - rotated_at_target
        target_translation_stage = calculation_translation_to_stage(
            target_translation_calculation
        )
    target_pose = StagePose(
        target_translation_stage.x,
        target_translation_stage.y,
        target_translation_stage.z,
        target_pitch,
        target_yaw,
    )
    delta_pose = StagePose(
        target_pose.x_mm - current_pose.x_mm,
        target_pose.y_mm - current_pose.y_mm,
        target_pose.z_mm - current_pose.z_mm,
        target_pose.pitch_deg - current_pose.pitch_deg,
        target_pose.yaw_deg - current_pose.yaw_deg,
    )

    fixed_after = world_fixed_point(target_pose, fixed_surface, geometry)
    residual = fixed_after - fixed_before
    normalized_limits = _normalize_limits(limits)
    target_values = target_pose.axis_values()
    limit_results = {
        axis: axis_limits.contains(target_values[axis])
        for axis, axis_limits in normalized_limits.items()
    }
    all_within_limits = all(limit_results.values()) if normalized_limits else None

    return FixedPointMove(
        fixed_point_surface_mm=fixed_surface,
        current_pose=current_pose,
        target_pose=target_pose,
        delta_pose=delta_pose,
        fixed_world_before_mm=fixed_before,
        fixed_world_after_mm=fixed_after,
        residual_mm=residual,
        residual_norm_mm=residual.norm,
        limit_results=limit_results,
        all_within_limits=all_within_limits,
        geometry=geometry,
    )
