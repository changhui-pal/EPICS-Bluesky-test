"""Ophyd motor classes used with the KOHZU ARIES/LYNX IOC."""

from __future__ import annotations

import threading
import time

from ophyd import EpicsMotor


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

    def __init__(self, *args, **kwargs):
        # A DMOV monitor may call _done_moving from another CA callback thread.
        # RLock also permits callbacks invoked by this class to query or
        # complete motor state from the same thread without self-deadlocking.
        self._stop_completion_lock = threading.RLock()
        super().__init__(*args, **kwargs)

    def _done_moving(self, success=True, timestamp=None, value=None, **kwargs):
        """Complete a move while excluding an in-progress explicit STOP."""
        with self._stop_completion_lock:
            return super()._done_moving(
                success=success,
                timestamp=timestamp,
                value=value,
                **kwargs,
            )

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
