#!/usr/bin/env python3
"""Tests for guarded, hardware-independent trajectory execution."""

import unittest

from kohzu_kinematics import (
    AxisLimits,
    ExecutionPolicy,
    StagePose,
    TrajectoryExecutionError,
    execute_trajectory,
    sample_fixed_point_trajectory,
)


class FakeBackend:
    def __init__(self, pose, *, fail_at=None, offset_at=None, unsafe_at=None,
                 stop_fails=False):
        self.pose = pose
        self.fail_at = fail_at
        self.offset_at = offset_at
        self.unsafe_at = unsafe_at
        self.stop_fails = stop_fails
        self.commands = []
        self.stop_calls = 0
        self.safety_checks = 0

    def read_pose(self):
        return self.pose

    def verify_safe(self):
        self.safety_checks += 1
        if self.safety_checks == self.unsafe_at:
            raise RuntimeError("mock hardware limit became active")

    def command_sample(self, sample, timeout_s):
        self.commands.append((sample.index, timeout_s))
        if sample.index == self.fail_at:
            raise TimeoutError("mock timeout")
        self.pose = sample.pose
        if sample.index == self.offset_at:
            self.pose = StagePose(
                self.pose.x_mm + 0.1, self.pose.y_mm, self.pose.z_mm,
                self.pose.pitch_deg, self.pose.yaw_deg,
            )
        return self.pose

    def stop_all(self):
        self.stop_calls += 1
        if self.stop_fails:
            raise RuntimeError("mock STOP failure")


class FixedPointExecutionTest(unittest.TestCase):
    def make_trajectory(self, *, intervals=10, limits=True):
        axis_limits = None
        if limits:
            axis_limits = {
                "x": AxisLimits(-24.5, 24.5), "y": AxisLimits(-7.35, 7.35),
                "z": AxisLimits(-3.92, 3.92), "pitch": AxisLimits(-3.4, 3.4),
                "yaw": AxisLimits(-173.0, 173.0),
            }
        return sample_fixed_point_trajectory(
            fixed_point_surface_mm=(20, 0, 0), current_xyz_mm=(0, 0, 0),
            current_pitch_deg=0, current_yaw_deg=0,
            target_pitch_deg=0.1, target_yaw_deg=0.1,
            duration_s=10, intervals=intervals, limits=axis_limits,
        )

    def policy(self, **changes):
        values = dict(
            allow_collision_unchecked=True,
            enforce_safety_checks=True,
            stop_on_failure=True,
        )
        values.update(changes)
        return ExecutionPolicy(**values)

    def test_normal_execution_reaches_every_sample(self):
        trajectory = self.make_trajectory()
        backend = FakeBackend(trajectory.current_pose)

        result = execute_trajectory(trajectory, backend, policy=self.policy())

        self.assertEqual(result.completed_samples, 10)
        self.assertEqual(result.final_pose, trajectory.target_pose)
        self.assertEqual(backend.stop_calls, 0)

    def test_collision_unchecked_requires_explicit_permission(self):
        trajectory = self.make_trajectory()
        backend = FakeBackend(trajectory.current_pose)

        with self.assertRaisesRegex(TrajectoryExecutionError, "collision"):
            execute_trajectory(
                trajectory, backend,
                policy=ExecutionPolicy(enforce_safety_checks=True),
            )

        self.assertEqual(backend.commands, [])

    def test_basic_profile_bypasses_preserved_safety_guards(self):
        trajectory = self.make_trajectory(intervals=1, limits=False)
        backend = FakeBackend(StagePose(99, 0, 0, 0, 0))

        result = execute_trajectory(trajectory, backend)

        self.assertEqual(result.completed_samples, 1)
        self.assertEqual(backend.stop_calls, 0)

    def test_unknown_limits_rejected_before_command(self):
        trajectory = self.make_trajectory(limits=False)
        backend = FakeBackend(trajectory.current_pose)

        with self.assertRaisesRegex(TrajectoryExecutionError, "software limits"):
            execute_trajectory(trajectory, backend, policy=self.policy())

        self.assertEqual(backend.commands, [])

    def test_changed_start_pose_rejected_without_stop_or_command(self):
        trajectory = self.make_trajectory()
        changed = StagePose(0.1, 0, 0, 0, 0)
        backend = FakeBackend(changed)

        with self.assertRaisesRegex(TrajectoryExecutionError, "start pose changed"):
            execute_trajectory(trajectory, backend, policy=self.policy())

        self.assertEqual(backend.commands, [])
        self.assertEqual(backend.stop_calls, 0)

    def test_oversized_sample_rejected_before_command(self):
        trajectory = self.make_trajectory(intervals=1)
        backend = FakeBackend(trajectory.current_pose)

        with self.assertRaisesRegex(TrajectoryExecutionError, "step"):
            execute_trajectory(trajectory, backend, policy=self.policy())

        self.assertEqual(backend.commands, [])

    def test_timeout_stops_all_axes(self):
        trajectory = self.make_trajectory()
        backend = FakeBackend(trajectory.current_pose, fail_at=3)

        with self.assertRaisesRegex(TrajectoryExecutionError, "mock timeout"):
            execute_trajectory(trajectory, backend, policy=self.policy())

        self.assertEqual(backend.stop_calls, 1)
        self.assertEqual([index for index, _ in backend.commands], [1, 2, 3])

    def test_endpoint_mismatch_stops_all_axes(self):
        trajectory = self.make_trajectory()
        backend = FakeBackend(trajectory.current_pose, offset_at=2)

        with self.assertRaisesRegex(TrajectoryExecutionError, "endpoint mismatch"):
            execute_trajectory(trajectory, backend, policy=self.policy())

        self.assertEqual(backend.stop_calls, 1)

    def test_live_safety_change_stops_before_next_command(self):
        trajectory = self.make_trajectory()
        backend = FakeBackend(trajectory.current_pose, unsafe_at=3)

        with self.assertRaisesRegex(TrajectoryExecutionError, "hardware limit"):
            execute_trajectory(trajectory, backend, policy=self.policy())

        self.assertEqual([index for index, _ in backend.commands], [1, 2])
        self.assertEqual(backend.stop_calls, 1)

    def test_stop_failure_is_reported_with_original_failure(self):
        trajectory = self.make_trajectory()
        backend = FakeBackend(trajectory.current_pose, fail_at=1, stop_fails=True)

        with self.assertRaisesRegex(TrajectoryExecutionError, "STOP also failed"):
            execute_trajectory(trajectory, backend, policy=self.policy())


if __name__ == "__main__":
    unittest.main()
