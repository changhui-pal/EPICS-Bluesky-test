"""Serialized Ophyd/Bluesky execution for single-axis GUI moves."""

from __future__ import annotations

import concurrent.futures
import queue
import threading


class BlueskyMotionExecutor:
    """Own one RunEngine in one worker while allowing concurrent STOP."""

    def __init__(self, prefix: str, *, runner_factory=None, motor_factory=None,
                 plan_factory=None, move_timeout: float = 180.0):
        self.prefix = prefix
        self.runner_factory = runner_factory
        self.motor_factory = motor_factory
        self.plan_factory = plan_factory
        self.move_timeout = move_timeout
        self.requests = queue.Queue()
        self.motors = {}
        self.active_axis = None
        self.lock = threading.RLock()
        self.thread = threading.Thread(
            target=self._worker, name="kohzu-gui-bluesky", daemon=False,
        )
        self.thread.start()

    def _dependencies(self):
        if self.runner_factory is None:
            from bluesky import RunEngine
            # The GUI owns STOP and process signals. SigintHandler cannot be
            # installed by a RunEngine that intentionally lives off-main-thread.
            self.runner_factory = lambda: RunEngine({}, context_managers=[])
        if self.motor_factory is None:
            from kohzu_ophyd import SafeStopEpicsMotor
            self.motor_factory = lambda pv, name: SafeStopEpicsMotor(pv, name=name)
        if self.plan_factory is None:
            from bluesky import plan_stubs as bps
            self.plan_factory = lambda motor, target: bps.mv(
                motor, target, timeout=self.move_timeout
            )

    def _worker(self):
        try:
            self._dependencies()
            runner = self.runner_factory()
        except BaseException as error:
            while True:
                request = self.requests.get()
                if request is None:
                    return
                _, _, future = request
                future.set_exception(error)
        while True:
            request = self.requests.get()
            if request is None:
                return
            axis, target, future = request
            if not future.set_running_or_notify_cancel():
                continue
            try:
                with self.lock:
                    motor = self._motor(axis)
                    self.active_axis = axis
                runner(self.plan_factory(motor, target))
                with self.lock:
                    if self.active_axis == axis:
                        self.active_axis = None
                future.set_result(target)
            except BaseException as error:
                future.set_exception(error)
            finally:
                with self.lock:
                    if self.active_axis == axis:
                        self.active_axis = None

    def submit(self, axis: int, target: float):
        future = concurrent.futures.Future()
        self.requests.put((axis, target, future))
        return future

    def register_motor(self, axis: int, motor) -> None:
        """Use the panel's already-connected persistent Ophyd motor."""
        with self.lock:
            existing = self.motors.get(axis)
            if existing is not None and existing is not motor:
                raise ValueError(f"axis {axis}: a different motor is registered")
            self.motors[axis] = motor

    def unregister_motor(self, axis: int) -> None:
        with self.lock:
            if self.active_axis == axis:
                raise ValueError(f"axis {axis}: cannot unregister during motion")
            self.motors.pop(axis, None)

    def _motor(self, axis: int):
        """Return one connected motor, creating it exactly once."""
        with self.lock:
            motor = self.motors.get(axis)
            if motor is None:
                motor = self.motor_factory(
                    f"{self.prefix}m{axis}", f"gui_axis_{axis}"
                )
                motor.wait_for_connection(timeout=5.0)
                self.motors[axis] = motor
            return motor

    def jog(self, axis: int, *, forward: bool) -> None:
        """Start motor-record JOG through Ophyd; STOP is a separate request."""
        self._dependencies()
        motor = self._motor(axis)
        signal = motor.jog_forward if forward else motor.jog_reverse
        signal.put(1, wait=False)

    def stop(self, axis: int) -> bool:
        """Stop an instantiated Ophyd motor; return false before first move."""
        with self.lock:
            motor = self.motors.get(axis)
        if motor is None:
            return False
        motor.stop(success=False)
        return True

    def close(self, timeout: float = 5.0) -> None:
        with self.lock:
            motor = self.motors.get(self.active_axis)
        if motor is not None:
            try:
                motor.stop(success=False)
            except BaseException:
                pass
        self.requests.put(None)
        self.thread.join(timeout=timeout)
        if self.thread.is_alive():
            raise RuntimeError("Bluesky motion worker did not stop")
