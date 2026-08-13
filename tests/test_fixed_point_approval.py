#!/usr/bin/env python3
"""Tests for deterministic reviewed-trajectory identifiers."""

import unittest

from kohzu_kinematics import (
    AxisLimits,
    sample_fixed_point_trajectory,
    trajectory_approval_manifest,
    trajectory_approval_sha256,
)


class FixedPointApprovalTest(unittest.TestCase):
    def trajectory(self, yaw=0.1):
        limits = {axis: AxisLimits(-100, 100)
                  for axis in ("x", "y", "z", "pitch", "yaw")}
        return sample_fixed_point_trajectory(
            fixed_point_surface_mm=(20, 0, 0), current_xyz_mm=(0, 0, 0),
            current_pitch_deg=0, current_yaw_deg=0,
            target_pitch_deg=0.1, target_yaw_deg=yaw,
            duration_s=10, intervals=10, limits=limits,
        )

    def test_hash_is_deterministic_and_64_hex_characters(self):
        first = trajectory_approval_sha256(self.trajectory())
        second = trajectory_approval_sha256(self.trajectory())
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        int(first, 16)

    def test_motion_change_changes_hash(self):
        self.assertNotEqual(
            trajectory_approval_sha256(self.trajectory(0.1)),
            trajectory_approval_sha256(self.trajectory(0.2)),
        )

    def test_device_context_changes_hash(self):
        trajectory = self.trajectory()
        self.assertNotEqual(
            trajectory_approval_sha256(trajectory, context="EPICS prefix=A:"),
            trajectory_approval_sha256(trajectory, context="EPICS prefix=B:"),
        )

    def test_manifest_contains_every_sample_and_collision_state(self):
        trajectory = self.trajectory()
        manifest = trajectory_approval_manifest(trajectory)
        self.assertEqual(len(manifest["samples"]), 11)
        self.assertFalse(manifest["collision_checked"])
        self.assertTrue(manifest["all_within_limits"])


if __name__ == "__main__":
    unittest.main()
