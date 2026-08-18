"""Ophyd motor classes used with the KOHZU ARIES/LYNX IOC."""

from __future__ import annotations

import threading
import time

from ophyd import Component as Cpt, EpicsMotor, EpicsSignal, EpicsSignalRO


class SafeStopEpicsMotor(EpicsMotor):
    """Serialize an explicit STOP with motor-record DMOV completion.

    ``EpicsMotor.stop()`` writes ``.STOP`` before completing the active
    ``MoveStatus`` with the caller-provided ``success`` value.  A fast motor
    record can publish ``DMOV=1`` between those operations and complete the
    status successfully first.  This class prevents that race without
    delaying normal moves or EPICS field updates.

    The lock covers only MoveStatus completion.  The motor-record STOP is
    still sent immediately, and the normal DMOV callback resumes as soon as
    the explicit stop has detached and completed the active status.
    """

    # ``_able`` is a GUI-owned soft enable record.  It is writable because a
    # panel session enables it only after every monitored motor PV is connected
    # and disables it before the session is removed.
    enabled = Cpt(EpicsSignal, "_able", kind="omitted", auto_monitor=True)
    jog_forward = Cpt(EpicsSignal, ".JOGF", kind="omitted")
    jog_reverse = Cpt(EpicsSignal, ".JOGR", kind="omitted")

    # Persistent GUI signals.  Keeping these on the motor object means CA
    # channels and subscriptions are created once per panel, not once per HTTP
    # request or screen refresh.
    limit_violation = Cpt(EpicsSignalRO, ".LVIO", kind="omitted", auto_monitor=True)
    jog_velocity = Cpt(EpicsSignal, ".JVEL", kind="config", auto_monitor=True)
    jog_acceleration = Cpt(EpicsSignal, ".JAR", kind="config", auto_monitor=True)
    home_velocity = Cpt(EpicsSignal, ".HVEL", kind="config", auto_monitor=True)
    max_velocity = Cpt(EpicsSignal, ".VMAX", kind="config", auto_monitor=True)
    base_velocity = Cpt(EpicsSignal, ".VBAS", kind="config", auto_monitor=True)
    tweak_value = Cpt(EpicsSignal, ".TWV", kind="config", auto_monitor=True)
    backlash_distance = Cpt(EpicsSignal, ".BDST", kind="config", auto_monitor=True)
    backlash_velocity = Cpt(EpicsSignal, ".BVEL", kind="config", auto_monitor=True)
    backlash_acceleration = Cpt(EpicsSignal, ".BACC", kind="config", auto_monitor=True)
    retry_deadband = Cpt(EpicsSignal, ".RDBD", kind="config", auto_monitor=True)
    retry_count = Cpt(EpicsSignal, ".RTRY", kind="config", auto_monitor=True)
    settle_delay = Cpt(EpicsSignal, ".DLY", kind="config", auto_monitor=True)
    move_fraction = Cpt(EpicsSignal, ".FRAC", kind="config", auto_monitor=True)
    motor_resolution = Cpt(EpicsSignal, ".MRES", kind="config", auto_monitor=True)
    display_precision = Cpt(EpicsSignal, ".PREC", kind="config", auto_monitor=True)
    units_per_revolution = Cpt(EpicsSignal, ".UREV", kind="config", auto_monitor=True)
    steps_per_revolution = Cpt(EpicsSignal, ".SREV", kind="config", auto_monitor=True)
    encoder_resolution = Cpt(EpicsSignal, ".ERES", kind="config", auto_monitor=True)
    readback_resolution = Cpt(EpicsSignal, ".RRES", kind="config", auto_monitor=True)
    use_encoder = Cpt(EpicsSignal, ".UEIP", kind="config", auto_monitor=True)
    use_readback_link = Cpt(EpicsSignal, ".URIP", kind="config", auto_monitor=True)
    spmg = Cpt(EpicsSignal, ".SPMG", kind="config", auto_monitor=True)
    dial_setpoint = Cpt(EpicsSignal, ".DVAL", kind="omitted", auto_monitor=True)
    dial_readback = Cpt(EpicsSignalRO, ".DRBV", kind="omitted", auto_monitor=True)
    raw_setpoint = Cpt(EpicsSignal, ".RVAL", kind="omitted", auto_monitor=True)
    raw_readback = Cpt(EpicsSignalRO, ".RRBV", kind="omitted", auto_monitor=True)
    motor_status = Cpt(EpicsSignalRO, ".MSTA", kind="omitted", auto_monitor=True)
    origin_method = Cpt(
        EpicsSignalRO, ":OriginMethodSelectedRBV", kind="omitted", auto_monitor=True
    )
    origin_method_set = Cpt(
        EpicsSignal, ":OriginMethod", kind="config", auto_monitor=True
    )
    origin_method_actual = Cpt(
        EpicsSignalRO, ":OriginMethodRBV", kind="omitted", auto_monitor=True
    )

    def __init__(self, *args, **kwargs):
        # A DMOV monitor may call _done_moving from another CA callback thread.
        # RLock also permits callbacks invoked by this class to query or
        # complete motor state from the same thread without self-deadlocking.
        self._stop_completion_lock = threading.RLock()
        super().__init__(*args, **kwargs)

    def _done_moving(self, success=True, timestamp=None, value=None, **kwargs):
        """Complete once while excluding STOP and duplicate DMOV callbacks."""
        with self._stop_completion_lock:
            callbacks = list(self._callbacks[self._SUB_REQ_DONE].values())
            self._reset_sub(self._SUB_REQ_DONE)
            if success:
                self._run_subs(
                    sub_type=self.SUB_DONE, timestamp=timestamp, value=value, **kwargs
                )
            callback_kwargs = {
                "obj": self,
                "sub_type": self._SUB_REQ_DONE,
                "success": success,
                "timestamp": timestamp,
            }
            for callback in callbacks:
                callback(**callback_kwargs)

    def stop(self, *, success=False):
        """Stop the motor and preserve the requested MoveStatus outcome."""
        with self._stop_completion_lock:
            # Detach first.  PositionerBase._done_moving() runs callbacks
            # before clearing them, which leaves a small re-entrant window in
            # which a fast DMOV callback can complete the same Status twice.
            callbacks = list(self._callbacks[self._SUB_REQ_DONE].values())
            self._reset_sub(self._SUB_REQ_DONE)

            # The physical stop is still transmitted before clients are told
            # that their pending MoveStatus has completed.
            self.motor_stop.put(1, wait=False)

            if success:
                self._run_subs(
                    sub_type=self.SUB_DONE,
                    timestamp=time.time(),
                    value=None,
                )

            callback_kwargs = {
                "obj": self,
                "sub_type": self._SUB_REQ_DONE,
                "success": success,
                "timestamp": time.time(),
            }
            for callback in callbacks:
                callback(**callback_kwargs)
