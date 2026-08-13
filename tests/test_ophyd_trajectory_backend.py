#!/usr/bin/env python3
"""Fake-Ophyd tests for the five-axis fixed-point backend."""

import unittest
from unittest import mock

from ophyd.signal import Signal
from ophyd.sim import make_fake_device
from ophyd.status import Status

from kohzu_kinematics import (
    AxisLimits,
    ExecutionPolicy,
    StagePose,
    TrajectoryExecutionError,
    execute_trajectory,
    sample_fixed_point_trajectory,
)
from kohzu_kinematics.trajectory import TrajectorySample
from kohzu_ophyd import OphydFiveAxisBackend, SafeStopEpicsMotor


FakeMotor = make_fake_device(SafeStopEpicsMotor)
ROLES = ("x", "y", "z", "pitch", "yaw")


def sample(pose):
    return TrajectorySample(1, 1.0, 1.0, pose, None, None,
                            None, 0.0, {}, True)


class OphydFiveAxisBackendTest(unittest.TestCase):
    def setUp(self):
        self.motors = {}
        for index, role in enumerate(ROLES, 1):
            motor = FakeMotor(f"TEST:m{index}", name=role)
            motor.user_readback.sim_put(0)
            motor.motor_done_move.sim_put(1)
            motor.motor_is_moving.sim_put(0)
            motor.high_limit_switch.sim_put(0)
            motor.low_limit_switch.sim_put(0)
            motor.limit_violation.sim_put(0)
            motor.enabled.sim_put(0)
            motor.user_setpoint.sim_set_limits((-1000, 1000))
            self.motors[role] = motor
        self.emergency = Signal(name="emergency", value=0)
        self.backend = OphydFiveAxisBackend(
            self.motors, self.emergency, safety_checks=True
        )

    def install_immediate_sets(self, calls):
        def make_set(role):
            def set_value(value):
                calls.append((role, value))
                self.motors[role].user_readback.sim_put(value)
                status = Status()
                status.set_finished()
                return status
            return set_value

        patches = [mock.patch.object(motor, "set", make_set(role))
                   for role, motor in self.motors.items()]
        for patcher in patches:
            patcher.start()
        self.addCleanup(lambda: [patcher.stop() for patcher in reversed(patches)])

    def test_read_pose_and_safe_state(self):
        self.motors["x"].user_readback.sim_put(1.2)
        self.motors["pitch"].user_readback.sim_put(0.3)

        self.backend.verify_safe()

        self.assertEqual(self.backend.read_pose(), StagePose(1.2, 0, 0, 0.3, 0))

    def test_emergency_and_axis_state_are_rejected(self):
        self.emergency.put(1)
        with self.assertRaisesRegex(TrajectoryExecutionError, "emergency"):
            self.backend.verify_safe()

    def test_only_operational_enable_lock_is_required(self):
        self.backend.verify_enabled()
        self.motors["z"].enabled.sim_put(1)
        with self.assertRaisesRegex(TrajectoryExecutionError, "z motor is Disabled"):
            self.backend.verify_enabled()
        self.emergency.put(0)
        self.motors["yaw"].high_limit_switch.sim_put(1)
        with self.assertRaisesRegex(TrajectoryExecutionError, "yaw high"):
            self.backend.verify_safe()

    def test_command_issues_all_sets_and_returns_readback(self):
        target = StagePose(1, 2, 3, 0.1, 0.2)
        calls = []
        self.install_immediate_sets(calls)

        actual = self.backend.command_sample(sample(target), timeout_s=1.0)

        self.assertEqual([role for role, _ in calls], list(ROLES))
        self.assertEqual(actual, target)

    def test_full_execution_guard_drives_fake_ophyd_motors(self):
        limits = {
            "x": AxisLimits(-24.5, 24.5), "y": AxisLimits(-7.35, 7.35),
            "z": AxisLimits(-3.92, 3.92), "pitch": AxisLimits(-3.4, 3.4),
            "yaw": AxisLimits(-173, 173),
        }
        trajectory = sample_fixed_point_trajectory(
            fixed_point_surface_mm=(20, 0, 0), current_xyz_mm=(0, 0, 0),
            current_pitch_deg=0, current_yaw_deg=0,
            target_pitch_deg=0.1, target_yaw_deg=0.1,
            duration_s=10, intervals=10, limits=limits,
        )
        calls = []
        self.install_immediate_sets(calls)

        result = execute_trajectory(
            trajectory, self.backend,
            policy=ExecutionPolicy(
                allow_collision_unchecked=True,
                enforce_safety_checks=True,
                stop_on_failure=True,
            ),
        )

        self.assertEqual(result.final_pose, trajectory.target_pose)
        self.assertEqual(len(calls), 50)
        self.assertEqual(calls[-5:], list(zip(ROLES, (
            trajectory.target_pose.x_mm, trajectory.target_pose.y_mm,
            trajectory.target_pose.z_mm, trajectory.target_pose.pitch_deg,
            trajectory.target_pose.yaw_deg,
        ))))

    def test_stop_all_calls_every_motor_even_when_one_fails(self):
        calls = []
        for role, motor in self.motors.items():
            effect = RuntimeError("failed") if role == "z" else None
            motor.stop = mock.Mock(side_effect=effect)
            motor.stop.attach_mock(mock.Mock(side_effect=lambda r=role: calls.append(r)), "seen")

        # Use explicit side effects so call coverage is independent of failure.
        for role, motor in self.motors.items():
            if role != "z":
                motor.stop.side_effect = lambda success=False, r=role: calls.append(r)

        with self.assertRaisesRegex(TrajectoryExecutionError, "z"):
            self.backend.stop_all()

        self.assertTrue(all(motor.stop.called for motor in self.motors.values()))

    def test_constructor_requires_exact_roles(self):
        with self.assertRaisesRegex(ValueError, "exactly"):
            OphydFiveAxisBackend({"x": self.motors["x"]}, self.emergency)

    def test_basic_profile_requires_no_emergency_signal(self):
        backend = OphydFiveAxisBackend(self.motors)
        backend.verify_safe()
        backend.verify_enabled()

    def test_safety_profile_requires_emergency_signal(self):
        with self.assertRaisesRegex(ValueError, "emergency_signal"):
            OphydFiveAxisBackend(self.motors, safety_checks=True)


if __name__ == "__main__":
    unittest.main()
