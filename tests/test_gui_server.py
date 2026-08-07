#!/usr/bin/env python3
"""Tests for GUI configuration validation and write allowlisting."""

import importlib.util
import pathlib
import sys
import unittest


PROJECT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kohzu_gui_server", PROJECT / "gui" / "kohzu_gui_server.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeConfirmationAccess:
    """Minimal PV adapter for confirmation guard unit tests."""

    prefix = "TEST:"

    def __init__(self, values):
        self.values = values
        self.writes = []

    def get_one(self, pv, string_array=False, numeric_enum=False):
        return self.values[pv]

    def put_one(self, pv, value):
        self.writes.append((pv, value))
        self.values[pv] = value


class GuiServerTest(unittest.TestCase):
    def test_project_catalog_and_32_axes_are_exposed(self):
        value = MODULE.load_gui_configuration(
            PROJECT / "config" / "stage-models.ini",
            PROJECT / "config" / "axis-assignments.ini")
        self.assertEqual(len(value["models"]), 5)
        self.assertEqual(len(value["axes"]), 32)
        self.assertEqual(value["axes"][1]["assigned_model"], "XA05A-R201")

    def test_api_axis_path_rejects_out_of_range_and_motion_actions(self):
        self.assertIsNone(MODULE.AXIS_PATH.fullmatch("/api/axis/0/status"))
        self.assertIsNone(MODULE.AXIS_PATH.fullmatch("/api/axis/33/status"))
        self.assertIsNone(MODULE.AXIS_PATH.fullmatch("/api/axis/1/move"))
        self.assertIsNotNone(MODULE.AXIS_PATH.fullmatch("/api/axis/32/disable"))
        self.assertIsNotNone(MODULE.AXIS_PATH.fullmatch("/api/axis/1/home"))
        self.assertIsNone(MODULE.AXIS_PATH.fullmatch(
            "/api/axis/1/initial-home"))
        self.assertIsNotNone(MODULE.AXIS_PATH.fullmatch(
            "/api/axis/1/confirmation"))
        self.assertIsNotNone(MODULE.AXIS_PATH.fullmatch(
            "/api/axis/1/origin-method"))
        self.assertIsNotNone(MODULE.RECOVERY_PATH.fullmatch(
            "/api/recovery/release-emg"))
        self.assertIsNone(MODULE.RECOVERY_PATH.fullmatch(
            "/api/recovery/emergency-stop"))

    def test_status_allowlist_excludes_raw_enable_and_motion_writes(self):
        self.assertNotIn("_able", MODULE.STATUS_SUFFIXES)
        self.assertNotIn(".VAL", (":Commissioning:EnableRequest",
                                  ":Commissioning:DisableRequest"))
        self.assertIn("Diag:LastErrorText", MODULE.DIAGNOSTIC_SUFFIXES)

    def test_confirmation_requires_disabled_stopped_axis(self):
        base = "TEST:m1"
        values = {
            base + ":Commissioning:ConfigApplied": "1",
            base + "_able": "1", base + ".DMOV": "1", base + ".MOVN": "0",
        }
        client = FakeConfirmationAccess(values)
        MODULE.ChannelAccess.set_confirmation(client, 1, "home", True)
        self.assertEqual(client.writes[-1],
                         (base + ":Commissioning:HomeEstablished", "1"))

    def test_revoking_confirmation_disables_before_clear(self):
        client = FakeConfirmationAccess({})
        MODULE.ChannelAccess.set_confirmation(
            client, 2, "direction", False)
        self.assertEqual(client.writes, [
            ("TEST:m2:Commissioning:DisableRequest", "1"),
            ("TEST:m2:Commissioning:DirectionVerified", "0")])


if __name__ == "__main__":
    unittest.main()
