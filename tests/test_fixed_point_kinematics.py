#!/usr/bin/env python3
"""Tests for the idealized five-axis fixed-point endpoint model."""

import math
import unittest

from kohzu_kinematics import (
    AxisLimits,
    FixedPointGeometry,
    StagePose,
    Vector3,
    calculate_fixed_point_move,
    rotation_matrix,
    surface_point_to_calculation,
    world_fixed_point,
)


class FixedPointKinematicsTest(unittest.TestCase):
    def assertVectorAlmostEqual(self, actual, expected, places=12):
        self.assertAlmostEqual(actual.x, expected[0], places=places)
        self.assertAlmostEqual(actual.y, expected[1], places=places)
        self.assertAlmostEqual(actual.z, expected[2], places=places)

    def test_surface_origin_is_38_mm_below_common_axis(self):
        point = surface_point_to_calculation((0.0, 0.0, 0.0))

        self.assertEqual(point, Vector3(0.0, 0.0, -38.0))

    def test_user_right_is_negative_internal_y(self):
        point = surface_point_to_calculation((1.0, 2.0, 3.0))

        self.assertEqual(point, Vector3(1.0, -2.0, -35.0))

    def test_zero_rotation_is_identity(self):
        self.assertEqual(
            rotation_matrix(0.0, 0.0),
            ((1.0, 0.0, -0.0), (-0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        )

    def test_positive_yaw_turns_forward_point_toward_stage_right(self):
        pose = StagePose(0.0, 0.0, 0.0, 0.0, 90.0)
        # qz=38 places the test point at the common-axis height so only its
        # radial X/Y motion is relevant.
        world = world_fixed_point(pose, (20.0, 0.0, 38.0))

        # World values use the internal frame, where stage right is -Yc.
        self.assertVectorAlmostEqual(world, (0.0, -20.0, 0.0))

    def test_positive_pitch_raises_forward_point(self):
        pose = StagePose(0.0, 0.0, 0.0, 90.0, 0.0)
        world = world_fixed_point(pose, (20.0, 0.0, 38.0))

        self.assertVectorAlmostEqual(world, (0.0, 0.0, 20.0))

    def test_zero_angle_target_needs_no_translation(self):
        move = calculate_fixed_point_move(
            fixed_point_surface_mm=(20.0, 10.0, 5.0),
            current_xyz_mm=(0.0, 0.0, 0.0),
            current_pitch_deg=0.0,
            current_yaw_deg=0.0,
            target_pitch_deg=0.0,
            target_yaw_deg=0.0,
        )

        self.assertEqual(move.target_pose, move.current_pose)
        self.assertLess(move.residual_norm_mm, 1e-12)

    def test_point_on_yaw_axis_needs_no_yaw_translation(self):
        move = calculate_fixed_point_move(
            fixed_point_surface_mm=(0.0, 0.0, 12.0),
            current_xyz_mm=(3.0, -2.0, 1.0),
            current_pitch_deg=0.0,
            current_yaw_deg=15.0,
            target_pitch_deg=0.0,
            target_yaw_deg=123.0,
        )

        self.assertVectorAlmostEqual(
            Vector3(move.target_pose.x_mm, move.target_pose.y_mm, move.target_pose.z_mm),
            (3.0, -2.0, 1.0),
        )
        self.assertLess(move.residual_norm_mm, 1e-12)

    def test_off_axis_yaw_generates_expected_stage_compensation(self):
        move = calculate_fixed_point_move(
            fixed_point_surface_mm=(20.0, 0.0, 38.0),
            current_xyz_mm=(0.0, 0.0, 0.0),
            current_pitch_deg=0.0,
            current_yaw_deg=0.0,
            target_pitch_deg=0.0,
            target_yaw_deg=90.0,
        )

        self.assertAlmostEqual(move.target_pose.x_mm, 20.0, places=12)
        self.assertAlmostEqual(move.target_pose.y_mm, -20.0, places=12)
        self.assertAlmostEqual(move.target_pose.z_mm, 0.0, places=12)
        self.assertLess(move.residual_norm_mm, 1e-12)

    def test_surface_origin_pitch_uses_38_mm_lever_arm(self):
        move = calculate_fixed_point_move(
            fixed_point_surface_mm=(0.0, 0.0, 0.0),
            current_xyz_mm=(0.0, 0.0, 0.0),
            current_pitch_deg=0.0,
            current_yaw_deg=0.0,
            target_pitch_deg=90.0,
            target_yaw_deg=0.0,
        )

        self.assertAlmostEqual(move.target_pose.x_mm, -38.0, places=12)
        self.assertAlmostEqual(move.target_pose.y_mm, 0.0, places=12)
        self.assertAlmostEqual(move.target_pose.z_mm, -38.0, places=12)
        self.assertLess(move.residual_norm_mm, 1e-12)

    def test_arbitrary_endpoint_residual_is_negligible(self):
        move = calculate_fixed_point_move(
            fixed_point_surface_mm=(12.3, -4.5, 8.9),
            current_xyz_mm=(1.2, -0.7, 2.1),
            current_pitch_deg=-1.25,
            current_yaw_deg=47.0,
            target_pitch_deg=2.75,
            target_yaw_deg=-31.0,
        )

        self.assertLess(move.residual_norm_mm, 1e-12)

    def test_round_trip_returns_to_original_translation(self):
        first = calculate_fixed_point_move(
            fixed_point_surface_mm=(3.0, 5.0, 7.0),
            current_xyz_mm=(0.5, -0.25, 1.5),
            current_pitch_deg=0.0,
            current_yaw_deg=0.0,
            target_pitch_deg=2.0,
            target_yaw_deg=-15.0,
        )
        returned = calculate_fixed_point_move(
            fixed_point_surface_mm=(3.0, 5.0, 7.0),
            current_xyz_mm=(
                first.target_pose.x_mm,
                first.target_pose.y_mm,
                first.target_pose.z_mm,
            ),
            current_pitch_deg=first.target_pose.pitch_deg,
            current_yaw_deg=first.target_pose.yaw_deg,
            target_pitch_deg=0.0,
            target_yaw_deg=0.0,
        )

        self.assertAlmostEqual(returned.target_pose.x_mm, 0.5, places=12)
        self.assertAlmostEqual(returned.target_pose.y_mm, -0.25, places=12)
        self.assertAlmostEqual(returned.target_pose.z_mm, 1.5, places=12)
        self.assertLess(returned.residual_norm_mm, 1e-12)

    def test_custom_geometry_changes_pitch_lever_arm(self):
        move = calculate_fixed_point_move(
            fixed_point_surface_mm=(0.0, 0.0, 0.0),
            current_xyz_mm=(0.0, 0.0, 0.0),
            current_pitch_deg=0.0,
            current_yaw_deg=0.0,
            target_pitch_deg=90.0,
            target_yaw_deg=0.0,
            geometry=FixedPointGeometry(40.0),
        )

        self.assertAlmostEqual(move.target_pose.x_mm, -40.0, places=12)
        self.assertAlmostEqual(move.target_pose.z_mm, -40.0, places=12)

    def test_limit_report_uses_public_stage_coordinates(self):
        move = calculate_fixed_point_move(
            fixed_point_surface_mm=(20.0, 0.0, 38.0),
            current_xyz_mm=(0.0, 0.0, 0.0),
            current_pitch_deg=0.0,
            current_yaw_deg=0.0,
            target_pitch_deg=0.0,
            target_yaw_deg=90.0,
            limits={
                "x": AxisLimits(-24.5, 24.5),
                "y": (-7.35, 7.35),
                "z": (-3.92, 3.92),
                "pitch": (-3.429608, 3.429608),
                "yaw": (-173.786, 173.134),
            },
        )

        self.assertEqual(
            move.limit_results,
            {"x": True, "y": False, "z": True, "pitch": True, "yaw": True},
        )
        self.assertFalse(move.all_within_limits)

    def test_no_limits_reports_not_evaluated(self):
        move = calculate_fixed_point_move(
            fixed_point_surface_mm=(0.0, 0.0, 0.0),
            current_xyz_mm=(0.0, 0.0, 0.0),
            current_pitch_deg=0.0,
            current_yaw_deg=0.0,
            target_pitch_deg=0.0,
            target_yaw_deg=0.0,
        )

        self.assertEqual(move.limit_results, {})
        self.assertIsNone(move.all_within_limits)

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            calculate_fixed_point_move(
                fixed_point_surface_mm=(0.0, math.nan, 0.0),
                current_xyz_mm=(0.0, 0.0, 0.0),
                current_pitch_deg=0.0,
                current_yaw_deg=0.0,
                target_pitch_deg=0.0,
                target_yaw_deg=0.0,
            )
        with self.assertRaises(ValueError):
            calculate_fixed_point_move(
                fixed_point_surface_mm=(0.0, 0.0),
                current_xyz_mm=(0.0, 0.0, 0.0),
                current_pitch_deg=0.0,
                current_yaw_deg=0.0,
                target_pitch_deg=0.0,
                target_yaw_deg=0.0,
            )
        with self.assertRaises(ValueError):
            FixedPointGeometry(-1.0)
        with self.assertRaises(ValueError):
            AxisLimits(1.0, 1.0)
        with self.assertRaises(ValueError):
            calculate_fixed_point_move(
                fixed_point_surface_mm=(0.0, 0.0, 0.0),
                current_xyz_mm=(0.0, 0.0, 0.0),
                current_pitch_deg=0.0,
                current_yaw_deg=0.0,
                target_pitch_deg=0.0,
                target_yaw_deg=0.0,
                limits={"roll": (-1.0, 1.0)},
            )


if __name__ == "__main__":
    unittest.main()
