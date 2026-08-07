#!/usr/bin/env python3
"""Unit tests for the stage catalog and persistent axis-slot validator."""

import importlib.util
import pathlib
import tempfile
import unittest


PROJECT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "stage_validator", PROJECT / "tools" / "validate_stage_config.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def axis_slots(axis_one: str = "enabled = false") -> str:
    """Return all 32 required sections with an optional axis-1 body."""
    sections = [f"[axis:1]\n{axis_one}\n"]
    sections.extend(
        f"[axis:{axis}]\nenabled = false\n" for axis in range(2, 33))
    return "\n".join(sections)


VALID_MODEL = """
[model:TEST_HALF_STEP]
description = Synthetic model used only by unit tests
egu = mm
mres = 0.0005
low_limit = -10
high_limit = 10
vmax = 5
default_velocity = 2
base_velocity = 0.05
acceleration_time = 0.5
"""


class StageConfigValidatorTest(unittest.TestCase):
    def validate_text(self, models: str, axes: str, warnings=None):
        """Write isolated fixtures and run the public validation entry point."""
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            model_path = root / "models.ini"
            axis_path = root / "axes.ini"
            model_path.write_text(models, encoding="utf-8")
            axis_path.write_text(axes, encoding="utf-8")
            return VALIDATOR.validate(
                model_path, axis_path, 50000.0, warnings)

    def test_empty_catalog_and_disabled_slots_are_valid(self):
        self.assertEqual(self.validate_text("", axis_slots()), (0, 0))

    def test_enabled_axis_references_valid_model(self):
        axis_one = """enabled = true
model = TEST_HALF_STEP
direction = Pos
sensors = S2,L-
home_method = 4"""
        self.assertEqual(
            self.validate_text(VALID_MODEL, axis_slots(axis_one)), (1, 1))

    def test_model_over_sys16_produces_change_warning(self):
        model = VALID_MODEL.replace("vmax = 5", "vmax = 30")
        warnings = []
        self.assertEqual(self.validate_text(model, axis_slots(), warnings), (1, 0))
        self.assertEqual(len(warnings), 1)
        self.assertIn("SYS.16=60000", warnings[0])

    def test_enabled_axis_requires_known_model(self):
        axis_one = """enabled = true
model = UNKNOWN
direction = Pos
home_method = 4"""
        with self.assertRaisesRegex(ValueError, "unknown model"):
            self.validate_text(VALID_MODEL, axis_slots(axis_one))

    def test_method_10_needs_no_sensor(self):
        axis_one = """enabled = true
model = TEST_HALF_STEP
direction = Pos
sensors = none
home_method = 10"""
        self.assertEqual(
            self.validate_text(VALID_MODEL, axis_slots(axis_one)), (1, 1))

    def test_method_sensor_compatibility_is_user_responsibility(self):
        axis_one = """enabled = true
model = TEST_HALF_STEP
direction = Pos
sensors = L-
home_method = 4"""
        self.assertEqual(
            self.validate_text(VALID_MODEL, axis_slots(axis_one)), (1, 1))

    def test_faulty_sensor_cannot_also_be_available(self):
        axis_one = """enabled = true
model = TEST_HALF_STEP
direction = Pos
sensors = S2,L-
faulty_sensors = S2
home_method = 4"""
        with self.assertRaisesRegex(ValueError, "also marked faulty"):
            self.validate_text(VALID_MODEL, axis_slots(axis_one))

    def test_runtime_mask_matches_selectable_methods(self):
        sensors = frozenset(("S2", "L+", "L-"))
        self.assertEqual(VALIDATOR.allowed_home_methods(sensors), [4, 7, 8, 10])
        self.assertEqual(VALIDATOR.home_method_mask(sensors), 712)

    def test_all_slots_are_required(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            self.validate_text("", "[axis:1]\nenabled = false\n")


if __name__ == "__main__":
    unittest.main()
