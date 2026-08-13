"""Deterministic approval identifiers for reviewed fixed-point trajectories."""

from __future__ import annotations

import hashlib
import json

from .fixed_point import AXIS_NAMES
from .trajectory import FixedPointTrajectory


def trajectory_approval_manifest(trajectory: FixedPointTrajectory, *,
                                 context: str = "") -> dict:
    """Return the complete motion-relevant data covered by operator approval."""
    return {
        "schema": "kohzu-fixed-point-trajectory-v1",
        "context": str(context),
        "fixed_point_surface_mm": [
            trajectory.fixed_point_surface_mm.x,
            trajectory.fixed_point_surface_mm.y,
            trajectory.fixed_point_surface_mm.z,
        ],
        "duration_s": trajectory.duration_s,
        "intervals": trajectory.intervals,
        "collision_checked": trajectory.collision_checked,
        "all_within_limits": trajectory.all_within_limits,
        "geometry": {
            "pitch_center_above_yaw_surface_mm": (
                trajectory.geometry.pitch_center_above_yaw_surface_mm
            ),
        },
        "samples": [
            {
                "index": sample.index,
                "time_s": sample.time_s,
                "pose": {
                    axis: sample.pose.axis_values()[axis] for axis in AXIS_NAMES
                },
            }
            for sample in trajectory.samples
        ],
    }


def trajectory_approval_sha256(trajectory: FixedPointTrajectory, *,
                               context: str = "") -> str:
    """Hash the canonical manifest displayed by dry-run and required to execute."""
    encoded = json.dumps(
        trajectory_approval_manifest(trajectory, context=context),
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
