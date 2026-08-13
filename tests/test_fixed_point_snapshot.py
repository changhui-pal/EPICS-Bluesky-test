#!/usr/bin/env python3
"""Tests for read-only five-axis snapshot preflight."""

import time
import unittest

from kohzu_kinematics import (
    PVReading,
    SnapshotPreflightError,
    calculate_snapshot_dry_run,
    capture_five_axis_snapshot,
)


class FakeReader:
    def __init__(self, values, omitted=()):
        self.values = values
        self.omitted = set(omitted)
        self.requests = []

    def read(self, pvs):
        self.requests.append(tuple(pvs))
        return {pv: self.values[pv] for pv in pvs if pv not in self.omitted}


def safe_values(now, prefix="MOCK:"):
    positions = {1: 0.1, 2: -0.2, 3: 0.3, 4: 0.0, 5: 0.0}
    limits = {
        1: (-24.5, 24.5),
        2: (-7.35, 7.35),
        3: (-3.92, 3.92),
        4: (-3.429608, 3.429608),
        5: (-173.786, 173.134),
    }
    values = {}
    for axis in range(1, 6):
        base = f"{prefix}m{axis}."
        fields = {
            "RBV": positions[axis], "DMOV": 1, "MOVN": 0,
            "HLS": 0, "LLS": 0, "LVIO": 0,
            "LLM": limits[axis][0], "HLM": limits[axis][1],
            "MRES": (0.000637 if axis == 4 else 0.002 if axis == 5
                     else 0.00025 if axis == 3 else 0.0005),
            "OFF": 0, "DIR": 1 if axis == 3 else 0,
        }
        values.update(
            {base + field: PVReading(value, now - 0.1) for field, value in fields.items()}
        )
    values[prefix + "Recovery:EmergencyActive"] = PVReading(0, now - 0.1)
    return values


class FiveAxisSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.now = time.time()

    def capture(self, values=None, **kwargs):
        reader = FakeReader(values or safe_values(self.now))
        snapshot = capture_five_axis_snapshot(
            reader, prefix="MOCK:", now=self.now, **kwargs
        )
        return reader, snapshot

    def test_capture_requests_only_fixed_numeric_read_allowlist(self):
        reader, snapshot = self.capture()

        self.assertEqual(len(reader.requests), 1)
        requested = reader.requests[0]
        self.assertEqual(len(requested), 56)
        self.assertTrue(all("VAL" not in pv or "LVIO" in pv for pv in requested))
        self.assertTrue(all("_able" not in pv for pv in requested))
        self.assertEqual(set(snapshot.axes), {"x", "y", "z", "pitch", "yaw"})

    def test_snapshot_maps_positions_and_limits(self):
        _, snapshot = self.capture()

        self.assertEqual(snapshot.axes["x"].position, 0.1)
        self.assertEqual(snapshot.axes["y"].axis, 2)
        self.assertEqual(snapshot.axes["pitch"].limits.high, 3.429608)
        self.assertFalse(snapshot.emergency_active)
        self.assertTrue(snapshot.server_timestamps_complete)

    def test_observation_timestamp_provenance_is_preserved(self):
        values = safe_values(self.now)
        values["MOCK:m1.RBV"] = PVReading(
            0.1, self.now - 0.1, server_timestamp_defined=False
        )

        _, snapshot = self.capture(values)

        self.assertFalse(snapshot.server_timestamps_complete)

    def test_emergency_timestamp_is_excluded_from_freshness(self):
        values = safe_values(self.now)
        values["MOCK:Recovery:EmergencyActive"] = PVReading(
            0, self.now - 3600.0, server_timestamp_defined=False
        )

        _, snapshot = self.capture(values, maximum_age_s=5.0)

        self.assertFalse(snapshot.emergency_active)
        self.assertLess(snapshot.maximum_dynamic_age_s, 5.0)
        self.assertTrue(snapshot.server_timestamps_complete)

    def test_stale_dynamic_reading_is_rejected(self):
        values = safe_values(self.now)
        values["MOCK:m3.RBV"] = PVReading(0.3, self.now - 10.0)

        with self.assertRaisesRegex(SnapshotPreflightError, "stale snapshot"):
            self.capture(values, maximum_age_s=5.0)

    def test_alarm_is_rejected(self):
        values = safe_values(self.now)
        values["MOCK:m2.RBV"] = PVReading(
            -0.2, self.now - 0.1, "READ", "INVALID"
        )

        with self.assertRaisesRegex(SnapshotPreflightError, "alarm"):
            self.capture(values)

    def test_intentionally_disabled_motor_status_is_accepted(self):
        values = safe_values(self.now)
        values["MOCK:m2.RBV"] = PVReading(
            -0.2, self.now - 0.1, "DISABLE", "NO_ALARM"
        )

        _, snapshot = self.capture(values)

        self.assertEqual(snapshot.axes["y"].position, -0.2)

    def test_missing_pv_from_reader_is_rejected(self):
        reader = FakeReader(safe_values(self.now), omitted={"MOCK:m4.MOVN"})

        with self.assertRaisesRegex(SnapshotPreflightError, "omitted PVs"):
            capture_five_axis_snapshot(reader, prefix="MOCK:", now=self.now)

    def test_non_binary_status_is_rejected(self):
        values = safe_values(self.now)
        values["MOCK:m1.DMOV"] = PVReading(2, self.now - 0.1)

        with self.assertRaisesRegex(SnapshotPreflightError, "must be 0 or 1"):
            self.capture(values)

    def test_safe_snapshot_allows_dry_run(self):
        _, snapshot = self.capture()
        result = calculate_snapshot_dry_run(
            snapshot,
            fixed_point_surface_mm=(2.0, 1.0, 0.0),
            target_pitch_deg=0.2,
            target_yaw_deg=0.5,
            duration_s=5.0,
            intervals=10,
        )

        self.assertTrue(result.trajectory.all_within_limits)
        self.assertGreater(result.trajectory.maximum_residual_mm, 0)
        self.assertLess(result.continuous_trajectory.maximum_residual_mm, 1e-12)

    def assert_preflight_rejected(self, pv, value, message):
        values = safe_values(self.now)
        values[pv] = PVReading(value, self.now - 0.1)
        _, snapshot = self.capture(values)
        with self.assertRaisesRegex(SnapshotPreflightError, message):
            calculate_snapshot_dry_run(
                snapshot,
                fixed_point_surface_mm=(0.0, 0.0, 0.0),
                target_pitch_deg=0.1,
                target_yaw_deg=0.1,
                duration_s=1.0,
                intervals=2,
            )

    def test_moving_axis_rejects_dry_run(self):
        self.assert_preflight_rejected("MOCK:m2.MOVN", 1, "y axis is not stopped")

    def test_not_done_axis_rejects_dry_run(self):
        self.assert_preflight_rejected("MOCK:m3.DMOV", 0, "z axis is not stopped")

    def test_hardware_limit_rejects_dry_run(self):
        self.assert_preflight_rejected("MOCK:m4.HLS", 1, "pitch hardware limit")

    def test_soft_limit_violation_rejects_dry_run(self):
        self.assert_preflight_rejected("MOCK:m1.LVIO", 1, "x soft-limit")

    def test_emergency_rejects_dry_run(self):
        self.assert_preflight_rejected(
            "MOCK:Recovery:EmergencyActive", 1, "emergency input"
        )


if __name__ == "__main__":
    unittest.main()
