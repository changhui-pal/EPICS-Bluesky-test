"""Persistent Ophyd motor sessions used by the web GUI."""

from __future__ import annotations

import threading
import time


# One canonical mapping is shared by initial snapshots, monitor callbacks and
# writes.  There is deliberately no caget/caput fallback in this module.
SIGNALS = {
    ".RBV": "user_readback", ".VAL": "user_setpoint", ".EGU": "motor_egu",
    "_able": "enabled", ".MOVN": "motor_is_moving", ".DMOV": "motor_done_move",
    ".HLS": "high_limit_switch", ".LLS": "low_limit_switch",
    ".LVIO": "limit_violation", ".LLM": "low_limit_travel",
    ".HLM": "high_limit_travel", ".VELO": "velocity",
    ".JVEL": "jog_velocity", ".JAR": "jog_acceleration",
    ".HVEL": "home_velocity", ".VMAX": "max_velocity",
    ".VBAS": "base_velocity", ".ACCL": "acceleration",
    ".DIR": "user_offset_dir", ".MRES": "motor_resolution",
    ".OFF": "user_offset", ".FOFF": "offset_freeze_switch",
    ".DVAL": "dial_setpoint", ".DRBV": "dial_readback",
    ".RVAL": "raw_setpoint", ".RRBV": "raw_readback",
    ".MSTA": "motor_status", ".SET": "set_use_switch", ".SPMG": "spmg",
    ".TWV": "tweak_value", ".BDST": "backlash_distance",
    ".BVEL": "backlash_velocity", ".BACC": "backlash_acceleration",
    ".RDBD": "retry_deadband", ".RTRY": "retry_count",
    ".DLY": "settle_delay", ".FRAC": "move_fraction",
    ".PREC": "display_precision", ".UREV": "units_per_revolution",
    ".SREV": "steps_per_revolution", ".ERES": "encoder_resolution",
    ".RRES": "readback_resolution", ".UEIP": "use_encoder",
    ".URIP": "use_readback_link",
    ":OriginMethodSelectedRBV": "origin_method",
}
ENUM_LABELS = {
    "_able": ("Enable", "Disable"), ".DIR": ("Pos", "Neg"),
    ".FOFF": ("Variable", "Frozen"), ".SET": ("Use", "Set"),
    ".SPMG": ("Stop", "Pause", "Move", "Go"),
    ".UEIP": ("No", "Yes"), ".URIP": ("No", "Yes"),
}


def _text(value) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value)


def _display(suffix, value):
    labels = ENUM_LABELS.get(suffix)
    if labels and isinstance(value, (int, float)) and int(value) == value \
            and 0 <= int(value) < len(labels):
        return labels[int(value)]
    return _text(value)


class AxisSession:
    """Own one connected motor, its subscriptions, cache and command lock."""

    def __init__(self, axis: int, prefix: str, *, motor_factory=None,
                 update_callback=None, connection_timeout: float = 5.0):
        self.axis = axis
        self.command_lock = threading.RLock()
        self.cache_lock = threading.RLock()
        self.cache: dict[str, str] = {}
        self.update_callback = update_callback
        if motor_factory is None:
            from kohzu_ophyd import SafeStopEpicsMotor
            motor_factory = lambda pv, name: SafeStopEpicsMotor(pv, name=name)
        self.motor = motor_factory(f"{prefix}m{axis}", f"gui_axis_{axis}")
        self.motor.wait_for_connection(timeout=connection_timeout)
        self.signals = {
            suffix: getattr(self.motor, attribute)
            for suffix, attribute in SIGNALS.items()
        }
        self._subscriptions = []
        for suffix, signal in self.signals.items():
            callback = self._callback_for(suffix)
            token = signal.subscribe(callback, run=False)
            self._subscriptions.append((signal, token))
            # Subscribe first, then make the synchronous read authoritative.
            # PyEPICS may queue the subscription's initial callback while a
            # freshly processed motor record is still publishing old values.
            # ``as_string=True`` formats numeric motor fields with PREC.  An
            # unconfigured slot has PREC=0, which would turn MRES=0.0005 into
            # the misleading string "0".  Only enum/text fields request their
            # string representation; numeric values stay numeric.
            value = signal.get(
                as_string=suffix in ENUM_LABELS or suffix == ".EGU",
                use_monitor=False,
            )
            self.cache[suffix] = _display(suffix, value)

        resolution = float(self.cache[".MRES"])
        deadline = time.monotonic() + connection_timeout
        while resolution == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
            resolution = float(self.signals[".MRES"].get(use_monitor=False))
            self.cache[".MRES"] = _text(resolution)
        if resolution == 0:
            self.close()
            raise ValueError(f"axis {axis}: invalid initial MRES=0")

    def _callback_for(self, suffix):
        def changed(value=None, **_kwargs):
            # MRES=0 is never an operable motor configuration.  A newly
            # subscribed CA monitor can deliver the record's pre-apply value
            # after the authoritative synchronous snapshot; do not regress a
            # Ready session to that stale bootstrap value.
            if suffix == ".MRES" and float(value) == 0:
                return
            with self.cache_lock:
                self.cache[suffix] = _display(suffix, value)
                snapshot = dict(self.cache)
            if self.update_callback is not None:
                self.update_callback(self.axis, snapshot)
        return changed

    def snapshot(self) -> dict[str, str]:
        with self.cache_lock:
            return dict(self.cache)

    def put(self, suffix: str, value, *, wait: bool = True):
        with self.command_lock:
            self.signals[suffix].put(value, wait=wait, timeout=5.0)

    def jog(self, *, forward: bool) -> None:
        with self.command_lock:
            signal = self.motor.jog_forward if forward else self.motor.jog_reverse
            # Channel is already connected.  Do not hold the WebSocket command
            # handler until a record-processing completion callback arrives.
            signal.put(1, wait=False)

    def stop(self) -> None:
        self.motor.stop(success=False)

    def close(self) -> None:
        for signal, token in self._subscriptions:
            signal.unsubscribe(token)
        self._subscriptions.clear()
