#!/usr/bin/env python3
"""Tests for the minimal axis/model panel GUI backend."""

import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


PROJECT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kohzu_gui_server", PROJECT / "gui" / "kohzu_gui_server.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class GuiServerTest(unittest.TestCase):
    def test_project_catalog_and_32_axes_are_exposed(self):
        value = MODULE.load_gui_configuration(
            PROJECT / "config" / "stage-models.ini")
        self.assertEqual(len(value["models"]), 5)
        self.assertEqual(value["axes"], list(range(1, 33)))
        self.assertEqual(value["models"][0]["name"], "XA05A-L202")

    def test_plan_has_only_model_owned_fields(self):
        plan = MODULE.build_model_plan(
            7, "RA04A-W01", PROJECT / "config" / "stage-models.ini")
        fields = dict(plan.fields)
        self.assertEqual(plan.axis, 7)
        self.assertEqual(plan.model, "RA04A-W01")
        self.assertEqual(fields["MRES"], "0.002")
        self.assertNotIn("DIR", fields)
        self.assertNotIn(":OriginMethod", fields)

    def test_invalid_axis_and_model_are_rejected(self):
        path = PROJECT / "config" / "stage-models.ini"
        with self.assertRaisesRegex(ValueError, "1..32"):
            MODULE.build_model_plan(33, "RA04A-W01", path)
        with self.assertRaisesRegex(ValueError, "unknown"):
            MODULE.build_model_plan(1, "NOT-A-MODEL", path)

    def test_apply_uses_shared_single_axis_apply(self):
        applicator = object.__new__(MODULE.ModelApplicator)
        applicator.client = mock.Mock()
        applicator.client.get.side_effect = lambda pv, numeric_enum=False: (
            "1" if pv.endswith((".DMOV", "_able")) else "0")
        applicator.prefix = "TEST:"
        applicator.models_path = PROJECT / "config" / "stage-models.ini"
        with mock.patch.object(MODULE.stage_apply, "apply_plans") as apply:
            result = applicator.apply(3, "ZA05A-W101")
        plans = apply.call_args.args[2]
        self.assertEqual(len(plans), 1)
        self.assertEqual((plans[0].axis, plans[0].model), (3, "ZA05A-W101"))
        self.assertEqual(result, {
            "axis": 3, "model": "ZA05A-W101",
            "record": "TEST:m3", "enabled": True,
        })

    def make_store(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        axes = pathlib.Path(temporary.name) / "axes.ini"
        axes.write_text("".join(
            f"[axis:{axis}]\nenabled = false\n" for axis in range(1, 33)
        ), encoding="utf-8")
        return MODULE.AssignmentStore(
            axes, PROJECT / "config" / "stage-models.ini"), axes

    def test_assignment_create_shutdown_and_delete_lifecycle(self):
        store, _ = self.make_store()
        applicator = mock.Mock()
        applicator.apply.side_effect = lambda axis, model: {
            "axis": axis, "model": model, "record": f"TEST:m{axis}",
            "enabled": True,
        }
        manager = MODULE.PanelManager(store, applicator)

        manager.create(6, "RA04A-W01")
        self.assertEqual(store.panels(), [
            {"axis": 6, "model": "RA04A-W01", "enabled": True}])
        self.assertEqual(manager.shutdown(), [])
        self.assertEqual(store.panels(), [
            {"axis": 6, "model": "RA04A-W01", "enabled": False}])

        restarted = MODULE.PanelManager(store, applicator)
        restarted.restore()
        self.assertTrue(store.panels()[0]["enabled"])
        restarted.delete(6)
        self.assertEqual(store.panels(), [])
        self.assertEqual(applicator.disable.call_count, 2)

    def test_new_assignment_gets_valid_axis_defaults(self):
        store, path = self.make_store()
        store.assign(12, "XA05A-L202", enabled=True)
        parser = MODULE.validator.read_ini(path)
        section = parser["axis:12"]
        self.assertEqual(section["direction"], "Pos")
        self.assertEqual(section["sensors"], "none")
        self.assertEqual(section["home_method"], "4")

    def test_status_is_read_in_one_allowlisted_ca_call(self):
        applicator = object.__new__(MODULE.ModelApplicator)
        applicator.prefix = "TEST:"
        applicator.client = mock.Mock()
        applicator.client.caget = pathlib.Path("/epics/caget")
        output = "\n".join(str(index) for index in range(
            len(MODULE.STATUS_SUFFIXES))) + "\n"
        completed = mock.Mock(stdout=output)
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run:
            values = applicator.read_status(4)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["/epics/caget", "-t", "-S"])
        self.assertEqual(command[3], "TEST:m4.RBV")
        self.assertIn("TEST:m4_able", command)
        self.assertIn("TEST:m4.RRBV", command)
        self.assertIn("TEST:m4.OFF", command)
        self.assertEqual(values[".RBV"], "0")
        self.assertEqual(len(values), len(MODULE.STATUS_SUFFIXES))

    def test_status_requires_active_panel(self):
        store, _ = self.make_store()
        manager = MODULE.PanelManager(store, mock.Mock())
        with self.assertRaisesRegex(ValueError, "does not exist"):
            manager.status(9)


if __name__ == "__main__":
    unittest.main()
