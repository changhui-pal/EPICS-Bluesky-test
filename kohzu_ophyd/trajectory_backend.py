"""Ophyd adapter for the hardware-independent fixed-point execution guard."""

from __future__ import annotations

from functools import reduce
import operator
from typing import Mapping

from ophyd.status import wait

from kohzu_kinematics import StagePose, TrajectoryExecutionError

from .motor import SafeStopEpicsMotor


ROLE_TO_ATTRIBUTE = {
    "x": "x_mm", "y": "y_mm", "z": "z_mm",
    "pitch": "pitch_deg", "yaw": "yaw_deg",
}


class OphydFiveAxisBackend:
    """Execute one sampled endpoint through five ``SafeStopEpicsMotor`` objects.

    Construction alone connects no additional PVs and performs no writes.
    Enable and HOME remain external commissioning responsibilities.
    """

    def __init__(self, motors: Mapping[str, SafeStopEpicsMotor], emergency_signal=None,
                 *, safety_checks: bool = False):
        missing = set(ROLE_TO_ATTRIBUTE) - set(motors)
        extra = set(motors) - set(ROLE_TO_ATTRIBUTE)
        if missing or extra:
            raise ValueError(
                f"motors must contain exactly {tuple(ROLE_TO_ATTRIBUTE)}; "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )
        self.motors = dict(motors)
        if safety_checks and emergency_signal is None:
            raise ValueError("emergency_signal is required with safety_checks")
        self.emergency_signal = emergency_signal
        self.safety_checks = bool(safety_checks)

    @staticmethod
    def _value(signal, name: str) -> float:
        if not getattr(signal, "connected", True):
            raise TrajectoryExecutionError(f"{name} is disconnected")
        return float(signal.get())

    def read_pose(self) -> StagePose:
        values = {
            role: self._value(motor.user_readback, f"{role} RBV")
            for role, motor in self.motors.items()
        }
        return StagePose(values["x"], values["y"], values["z"],
                         values["pitch"], values["yaw"])

    def verify_safe(self) -> None:
        if not self.safety_checks:
            return
        if self._value(self.emergency_signal, "EmergencyActive") != 0:
            raise TrajectoryExecutionError("emergency input is active")
        for role, motor in self.motors.items():
            checks = (
                (motor.motor_done_move, 1, "DMOV is not done"),
                (motor.motor_is_moving, 0, "MOVN is active"),
                (motor.high_limit_switch, 0, "high hardware limit is active"),
                (motor.low_limit_switch, 0, "low hardware limit is active"),
                (motor.limit_violation, 0, "soft-limit violation is active"),
            )
            for signal, expected, message in checks:
                if self._value(signal, f"{role} state") != expected:
                    raise TrajectoryExecutionError(f"{role} {message}")

    def verify_enabled(self) -> None:
        """Require the one operational motor lock; no commissioning flags."""
        for role, motor in self.motors.items():
            if self._value(motor.enabled, f"{role} _able") != 0:
                raise TrajectoryExecutionError(f"{role} motor is Disabled")

    def command_sample(self, sample, timeout_s: float) -> StagePose:
        targets = sample.pose.axis_values()
        # Issue every set before waiting, avoiding a serialized move/wait loop.
        statuses = [self.motors[role].set(targets[role]) for role in ROLE_TO_ATTRIBUTE]
        combined = reduce(operator.and_, statuses)
        wait(combined, timeout=timeout_s)
        return self.read_pose()

    def stop_all(self) -> None:
        errors = []
        for role, motor in self.motors.items():
            try:
                motor.stop(success=False)
            except BaseException as exc:
                errors.append(f"{role}: {exc}")
        if errors:
            raise TrajectoryExecutionError("; ".join(errors))
