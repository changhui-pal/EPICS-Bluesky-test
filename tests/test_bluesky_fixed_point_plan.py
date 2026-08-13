#!/usr/bin/env python3
"""RunEngine tests for fixed-point cleanup and five-axis STOP behavior."""

import threading
import unittest
from unittest import mock

from bluesky import RunEngine
from bluesky.utils import RunEngineInterrupted
from ophyd.signal import Signal
from ophyd.sim import make_fake_device
from ophyd.status import Status

from kohzu_kinematics import AxisLimits, ExecutionPolicy, sample_fixed_point_trajectory
from kohzu_ophyd import (
    OphydFiveAxisBackend,
    SafeStopEpicsMotor,
    fixed_point_trajectory_plan,
)


FakeMotor = make_fake_device(SafeStopEpicsMotor)
ROLES = ("x", "y", "z", "pitch", "yaw")


class BlueskyFixedPointPlanTest(unittest.TestCase):
    def setUp(self):
        self.motors = {}
        self.stop_calls = []
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
            motor.stop = mock.Mock(
                side_effect=lambda *args, r=role, **kwargs: self.stop_calls.append(r)
            )
            self.motors[role] = motor
        self.backend = OphydFiveAxisBackend(
            self.motors, Signal(name="emergency", value=0), safety_checks=True
        )
        limits = {
            "x": AxisLimits(-24.5, 24.5), "y": AxisLimits(-7.35, 7.35),
            "z": AxisLimits(-3.92, 3.92), "pitch": AxisLimits(-3.4, 3.4),
            "yaw": AxisLimits(-173, 173),
        }
        self.trajectory = sample_fixed_point_trajectory(
            fixed_point_surface_mm=(20, 0, 0), current_xyz_mm=(0, 0, 0),
            current_pitch_deg=0, current_yaw_deg=0,
            target_pitch_deg=0.02, target_yaw_deg=0.02,
            duration_s=2, intervals=2, limits=limits,
        )
        self.policy = ExecutionPolicy(
            allow_collision_unchecked=True,
            enforce_safety_checks=True,
            stop_on_failure=True,
        )

    def install_immediate_sets(self):
        for role, motor in self.motors.items():
            def set_value(value, *, r=role):
                self.motors[r].user_readback.sim_put(value)
                status = Status()
                status.set_finished()
                return status
            motor.set = mock.Mock(side_effect=set_value)

    def test_normal_run_completes_and_runengine_cleans_up_motors(self):
        self.install_immediate_sets()

        RunEngine({})(fixed_point_trajectory_plan(
            self.trajectory, self.backend, policy=self.policy
        ))

        self.assertEqual(set(self.stop_calls), set(ROLES))
        self.assertEqual(sum(motor.set.call_count for motor in self.motors.values()), 10)

    def test_unchanged_quantized_axes_are_not_set(self):
        self.install_immediate_sets()
        samples = list(self.trajectory.samples)
        samples[1] = samples[1].__class__(
            **{**samples[1].__dict__, "pose": samples[0].pose}
        )
        trajectory = self.trajectory.__class__(
            **{**self.trajectory.__dict__, "samples": tuple(samples)}
        )

        RunEngine({})(fixed_point_trajectory_plan(
            trajectory, self.backend,
            policy=ExecutionPolicy(
                maximum_linear_step_mm=0.02,
                allow_collision_unchecked=True,
                enforce_safety_checks=True,
                stop_on_failure=True,
            ),
        ))

        self.assertEqual(sum(motor.set.call_count for motor in self.motors.values()), 5)

    def test_plan_exception_sends_stop_to_all_five_axes(self):
        self.install_immediate_sets()
        original = self.backend.verify_safe
        checks = 0

        def fail_second_sample():
            nonlocal checks
            checks += 1
            if checks == 2:
                raise RuntimeError("injected live safety failure")
            original()

        self.backend.verify_safe = fail_second_sample

        with self.assertRaisesRegex(RuntimeError, "live safety"):
            RunEngine({})(fixed_point_trajectory_plan(
                self.trajectory, self.backend, policy=self.policy
            ))

        self.assertTrue(all(role in self.stop_calls for role in ROLES))

    def test_runengine_abort_sends_stop_to_all_five_axes(self):
        move_started = threading.Event()
        pending = []

        for motor in self.motors.values():
            def set_pending(value):
                move_started.set()
                status = Status()
                pending.append(status)
                return status
            motor.set = mock.Mock(side_effect=set_pending)

        engine = RunEngine({})
        abort_finished = threading.Event()

        def abort_when_moving():
            if move_started.wait(timeout=2.0):
                engine.abort("test abort")
            abort_finished.set()

        thread = threading.Thread(target=abort_when_moving)
        thread.start()
        with self.assertRaises(RunEngineInterrupted):
            engine(fixed_point_trajectory_plan(
                self.trajectory, self.backend, policy=self.policy
            ))
        thread.join(timeout=3.0)

        self.assertTrue(abort_finished.is_set())
        self.assertTrue(all(role in self.stop_calls for role in ROLES))


if __name__ == "__main__":
    unittest.main()
