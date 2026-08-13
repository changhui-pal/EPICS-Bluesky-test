#!/usr/bin/env python3
"""Tests for fixed-point trajectory sampling and dry-run reports."""

import math
import unittest

from kohzu_kinematics import (
    format_trajectory_report,
    sample_fixed_point_trajectory,
)


class FixedPointTrajectoryTest(unittest.TestCase):
    def make_trajectory(self, **overrides):
        arguments = {
            "fixed_point_surface_mm": (5.0, 3.0, 2.0),
            "current_xyz_mm": (0.2, -0.1, 0.3),
            "current_pitch_deg": 0.0,
            "current_yaw_deg": 0.0,
            "target_pitch_deg": 2.0,
            "target_yaw_deg": 10.0,
            "duration_s": 5.0,
            "intervals": 10,
        }
        arguments.update(overrides)
        return sample_fixed_point_trajectory(**arguments)

    def test_intervals_include_both_endpoints(self):
        trajectory = self.make_trajectory(intervals=4)

        self.assertEqual(len(trajectory.samples), 5)
        self.assertEqual(trajectory.samples[0].fraction, 0.0)
        self.assertEqual(trajectory.samples[-1].fraction, 1.0)
        self.assertEqual(trajectory.samples[0].time_s, 0.0)
        self.assertEqual(trajectory.samples[-1].time_s, 5.0)

    def test_pitch_and_yaw_are_linearly_sampled(self):
        trajectory = self.make_trajectory(
            current_pitch_deg=-2.0,
            current_yaw_deg=5.0,
            target_pitch_deg=2.0,
            target_yaw_deg=-15.0,
            intervals=4,
        )

        self.assertEqual(
            [sample.pose.pitch_deg for sample in trajectory.samples],
            [-2.0, -1.0, 0.0, 1.0, 2.0],
        )
        self.assertEqual(
            [sample.pose.yaw_deg for sample in trajectory.samples],
            [5.0, 0.0, -5.0, -10.0, -15.0],
        )

    def test_first_sample_matches_current_pose(self):
        trajectory = self.make_trajectory()

        self.assertEqual(trajectory.samples[0].pose, trajectory.current_pose)

    def test_every_sample_holds_point_fixed(self):
        trajectory = self.make_trajectory(
            fixed_point_surface_mm=(12.3, -7.8, 4.5),
            current_pitch_deg=-1.0,
            current_yaw_deg=20.0,
            target_pitch_deg=3.0,
            target_yaw_deg=-40.0,
            intervals=100,
        )

        self.assertLess(trajectory.maximum_residual_mm, 1e-12)
        self.assertTrue(
            all(sample.residual_norm_mm < 1e-12 for sample in trajectory.samples)
        )

    def test_velocity_uses_sample_time_step(self):
        trajectory = self.make_trajectory(
            current_pitch_deg=0.0,
            current_yaw_deg=0.0,
            target_pitch_deg=10.0,
            target_yaw_deg=-20.0,
            duration_s=5.0,
            intervals=10,
        )

        self.assertIsNone(trajectory.samples[0].velocity_from_previous)
        for sample in trajectory.samples[1:]:
            self.assertAlmostEqual(
                sample.velocity_from_previous["pitch"], 2.0, places=12
            )
            self.assertAlmostEqual(
                sample.velocity_from_previous["yaw"], -4.0, places=12
            )
        self.assertAlmostEqual(trajectory.maximum_abs_velocity["pitch"], 2.0)
        self.assertAlmostEqual(trajectory.maximum_abs_velocity["yaw"], 4.0)

    def test_acceleration_is_finite_difference_diagnostic(self):
        trajectory = self.make_trajectory(intervals=4)

        self.assertIsNone(trajectory.samples[0].acceleration_from_previous)
        self.assertIsNone(trajectory.samples[1].acceleration_from_previous)
        self.assertTrue(
            all(
                sample.acceleration_from_previous is not None
                for sample in trajectory.samples[2:]
            )
        )
        self.assertAlmostEqual(
            trajectory.maximum_abs_acceleration["pitch"], 0.0, places=12
        )
        self.assertAlmostEqual(
            trajectory.maximum_abs_acceleration["yaw"], 0.0, places=12
        )

    def test_limit_failure_reports_first_sample_and_axes(self):
        trajectory = self.make_trajectory(
            target_pitch_deg=4.0,
            target_yaw_deg=10.0,
            intervals=4,
            limits={
                "x": (-100.0, 100.0),
                "y": (-100.0, 100.0),
                "z": (-100.0, 100.0),
                "pitch": (-3.0, 3.0),
                "yaw": (-180.0, 180.0),
            },
        )

        self.assertFalse(trajectory.all_within_limits)
        self.assertEqual(trajectory.first_limit_failure_index, 4)
        self.assertEqual(trajectory.first_limit_failure_axes, ("pitch",))

    def test_limit_pass_is_checked_at_every_sample(self):
        trajectory = self.make_trajectory(
            limits={
                "x": (-100.0, 100.0),
                "y": (-100.0, 100.0),
                "z": (-100.0, 100.0),
                "pitch": (-3.0, 3.0),
                "yaw": (-20.0, 20.0),
            }
        )

        self.assertTrue(trajectory.all_within_limits)
        self.assertIsNone(trajectory.first_limit_failure_index)
        self.assertEqual(trajectory.first_limit_failure_axes, ())

    def test_limits_not_supplied_are_not_evaluated(self):
        trajectory = self.make_trajectory()

        self.assertIsNone(trajectory.all_within_limits)
        self.assertTrue(
            all(sample.all_within_limits is None for sample in trajectory.samples)
        )

    def test_empty_limit_mapping_is_not_evaluated(self):
        trajectory = self.make_trajectory(limits={})

        self.assertIsNone(trajectory.all_within_limits)
        self.assertIsNone(trajectory.first_limit_failure_index)

    def test_report_is_explicitly_dry_run_and_not_collision_checked(self):
        trajectory = self.make_trajectory(intervals=2)
        report = format_trajectory_report(trajectory)

        self.assertIn("NO HARDWARE WRITES", report)
        self.assertIn("joint-space linear", report)
        self.assertIn("Software limits: NOT EVALUATED", report)
        self.assertIn("Collision checked: false", report)
        self.assertIn("finite differences exclude start/stop", report)

    def test_report_identifies_limit_failure(self):
        trajectory = self.make_trajectory(
            target_pitch_deg=5.0,
            intervals=5,
            limits={"pitch": (-2.5, 2.5)},
        )
        report = format_trajectory_report(trajectory)

        self.assertIn("Software limits: FAIL at sample 3 axes=pitch", report)

    def test_collision_check_is_always_false(self):
        self.assertFalse(self.make_trajectory().collision_checked)

    def test_invalid_duration_and_intervals_are_rejected(self):
        for duration in (0.0, -1.0, math.nan):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.make_trajectory(duration_s=duration)
        for intervals in (0, -1, 1.5, True):
            with self.subTest(intervals=intervals), self.assertRaises(ValueError):
                self.make_trajectory(intervals=intervals)


if __name__ == "__main__":
    unittest.main()
