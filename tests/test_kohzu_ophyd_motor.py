#!/usr/bin/env python3
"""Tests for KOHZU-specific Ophyd motor status handling."""

import threading
import unittest
from unittest import mock

from ophyd.sim import make_fake_device

from kohzu_ophyd import SafeStopEpicsMotor


FakeSafeStopEpicsMotor = make_fake_device(SafeStopEpicsMotor)


class SafeStopEpicsMotorTest(unittest.TestCase):
    def setUp(self):
        self.motor = FakeSafeStopEpicsMotor("TEST:m1", name="motor")
        self.motor.user_setpoint.sim_set_limits((-24.5, 24.5))
        self.motor.user_readback.sim_put(0.0)
        self.motor.motor_done_move.sim_put(1)
        self.motor.motor_is_moving.sim_put(0)
        self.motor.low_limit_switch.sim_put(0)
        self.motor.high_limit_switch.sim_put(0)
        self.motor.direction_of_travel.sim_put(1)

    def start_move(self):
        status = self.motor.set(10.0)
        self.motor.motor_done_move.sim_put(0)
        self.motor.motor_is_moving.sim_put(1)
        return status

    def finish_physical_stop(self):
        self.motor.motor_is_moving.sim_put(0)
        self.motor._done_moving(success=True)

    def test_normal_dmov_completion_succeeds(self):
        status = self.start_move()
        self.motor.user_readback.sim_put(10.0)
        self.motor.motor_is_moving.sim_put(0)
        self.motor._done_moving(success=True)

        self.assertTrue(status.done)
        self.assertTrue(status.success)

    def test_duplicate_dmov_completion_is_ignored(self):
        status = self.start_move()
        self.motor.user_readback.sim_put(10.0)
        self.motor.motor_is_moving.sim_put(0)
        self.motor._done_moving(success=True)
        self.motor._done_moving(success=True)

        self.assertTrue(status.done)
        self.assertTrue(status.success)

    def test_stop_false_fails_pending_move(self):
        status = self.start_move()
        self.motor.stop(success=False)
        self.finish_physical_stop()

        self.assertTrue(status.done)
        self.assertFalse(status.success)

    def test_stop_true_succeeds_pending_move(self):
        status = self.start_move()
        self.motor.stop(success=True)
        self.finish_physical_stop()

        self.assertTrue(status.done)
        self.assertTrue(status.success)

    def test_concurrent_dmov_waits_for_explicit_stop_outcome(self):
        status = self.start_move()
        callback_started = threading.Event()
        callback_finished = threading.Event()

        def concurrent_completion():
            callback_started.set()
            self.motor._done_moving(success=True)
            callback_finished.set()

        callback_thread = None

        def send_stop(_value, wait=False):
            nonlocal callback_thread
            callback_thread = threading.Thread(target=concurrent_completion)
            callback_thread.start()
            self.assertTrue(callback_started.wait(timeout=1.0))
            self.assertFalse(callback_finished.is_set())

        with mock.patch.object(self.motor.motor_stop, "put", send_stop):
            self.motor.stop(success=False)

        callback_thread.join(timeout=1.0)
        self.assertFalse(callback_thread.is_alive())
        self.assertTrue(callback_finished.is_set())
        self.assertTrue(status.done)
        self.assertFalse(status.success)


if __name__ == "__main__":
    unittest.main()
