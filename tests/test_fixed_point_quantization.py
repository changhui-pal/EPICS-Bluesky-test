#!/usr/bin/env python3
"""Tests for motor-record user-coordinate trajectory quantization."""

import unittest

from kohzu_kinematics import (
    AxisLimits,
    AxisQuantization,
    quantize_trajectory,
    sample_fixed_point_trajectory,
)


class FixedPointQuantizationTest(unittest.TestCase):
    def test_positive_and_negative_direction_with_offset(self):
        positive = AxisQuantization(0.5, 0.1, 0)
        negative = AxisQuantization(0.5, 0.1, 1)
        self.assertEqual(positive.user_target(1.34), 1.1)
        self.assertEqual(negative.user_target(1.34), 1.1)

    def test_half_pulse_rounds_away_from_zero_in_dial_coordinates(self):
        axis = AxisQuantization(1.0, 0.0, 0)
        self.assertEqual(axis.user_target(10.5), 11.0)
        self.assertEqual(axis.user_target(-10.5), -11.0)

    def test_every_sample_is_representable_and_residual_is_recomputed(self):
        limits = {axis: AxisLimits(-100, 100)
                  for axis in ("x", "y", "z", "pitch", "yaw")}
        continuous = sample_fixed_point_trajectory(
            fixed_point_surface_mm=(20, 0, 0), current_xyz_mm=(0, 0, 0),
            current_pitch_deg=0, current_yaw_deg=0,
            target_pitch_deg=0.1, target_yaw_deg=0.1,
            duration_s=10, intervals=10, limits=limits,
        )
        configurations = {
            "x": AxisQuantization(0.0005, -0.000663219, 0),
            "y": AxisQuantization(0.0005, -0.000349066, 0),
            "z": AxisQuantization(0.00025, -0.000349072, 1),
            "pitch": AxisQuantization(0.000637, 0.001, 0),
            "yaw": AxisQuantization(0.002, 0.001, 0),
        }

        quantized = quantize_trajectory(continuous, configurations, limits)

        for sample in quantized.samples:
            for axis, value in sample.pose.axis_values().items():
                config = configurations[axis]
                sign = 1 if config.direction == 0 else -1
                pulses = (value - config.offset) / (sign * config.mres)
                self.assertAlmostEqual(pulses, round(pulses), places=9)
        self.assertGreater(quantized.maximum_residual_mm, 0)
        self.assertTrue(quantized.all_within_limits)


if __name__ == "__main__":
    unittest.main()
