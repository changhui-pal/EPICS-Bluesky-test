#!/usr/bin/env python3
"""Unit tests for the guarded stage-configuration plan."""

import importlib.util
import pathlib
import sys
import unittest


PROJECT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "stage_apply", PROJECT / "tools" / "stage_config_apply.py")
APPLY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = APPLY
SPEC.loader.exec_module(APPLY)


class FakeChannelAccess:
    """In-memory PV adapter proving preflight occurs before writes."""

    def __init__(self, values):
        self.values = dict(values)
        self.writes = []

    def get(self, pv, numeric_enum=False):
        del numeric_enum
        return self.values[pv]

    def put(self, pv, value):
        self.writes.append((pv, value))
        self.values[pv] = value


class StageConfigApplyTest(unittest.TestCase):
    def test_project_plan_contains_five_assigned_disabled_axes(self):
        plans, warnings = APPLY.build_plans(
            PROJECT / "config" / "stage-models.ini",
            PROJECT / "config" / "axis-assignments.ini", 50000.0)
        self.assertEqual([plan.axis for plan in plans], [1, 2, 3, 4, 5])
        self.assertEqual(warnings, [])
        axis3 = dict(plans[2].fields)
        self.assertEqual(axis3["MRES"], "0.00025")
        self.assertEqual(axis3["LLM"], "-3.92")
        self.assertEqual(axis3[":OriginMethod"], "10")
        self.assertTrue(all(not plan.enabled for plan in plans))

    def test_development_preflight_failure_makes_no_writes(self):
        plan = APPLY.AxisPlan(1, "TEST", (("MRES", "0.001"),))
        client = FakeChannelAccess({
            "TEST:m1_able": "1", "TEST:m1.DMOV": "0",
            "TEST:m1.MOVN": "1",
            "TEST:m1:Commissioning:ConfigApplied": "0"})
        with self.assertRaisesRegex(ValueError, "require Disable"):
            APPLY.apply_plans(
                client, "TEST:", [plan], development_guards=True
            )
        self.assertEqual(client.writes, [])

    def test_basic_apply_writes_only_model_fields(self):
        plan = APPLY.AxisPlan(1, "TEST", (("MRES", "0.001"),))
        client = FakeChannelAccess({"TEST:m1_able": "1"})
        APPLY.apply_plans(client, "TEST:", [plan])
        self.assertEqual(client.writes, [
            ("TEST:m1.MRES", "0.001"),
            ("TEST:m1_able", "0"),
        ])

    def test_disabled_assignment_remains_disabled(self):
        plan = APPLY.AxisPlan(
            1, "TEST", (("MRES", "0.001"),), enabled=False)
        client = FakeChannelAccess({"TEST:m1_able": "1"})
        APPLY.apply_plans(client, "TEST:", [plan])
        self.assertEqual(client.writes, [("TEST:m1.MRES", "0.001")])


if __name__ == "__main__":
    unittest.main()
