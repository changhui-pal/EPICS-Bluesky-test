#!/usr/bin/env python3
"""Black-box tests for the non-executable stage assignment report."""

import pathlib
import subprocess
import tempfile
import unittest


PROJECT = pathlib.Path(__file__).resolve().parents[1]
TOOL = PROJECT / "tools" / "stage_config_dry_run.py"


def axis_slots() -> str:
    """Assign one synthetic model while retaining every persistent slot."""
    sections = ["""[axis:1]
enabled = true
model = TEST
direction = Neg
sensors = L+
home_method = 7
"""]
    sections.extend(
        f"[axis:{axis}]\nenabled = false\n" for axis in range(2, 33))
    return "\n".join(sections)


MODEL = """
[model:TEST]
description = Synthetic dry-run model
egu = mm
mres = 0.0005
low_limit = -10
high_limit = 10
vmax = 30
default_velocity = 2
base_velocity = 0.05
acceleration_time = 0.5
"""


class StageConfigDryRunTest(unittest.TestCase):
    def test_report_contains_fields_and_sys16_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            models = root / "models.ini"
            axes = root / "axes.ini"
            models.write_text(MODEL, encoding="utf-8")
            axes.write_text(axis_slots(), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(TOOL), "--models", str(models),
                 "--axes", str(axes), "--prefix", "TEST:"],
                check=True, capture_output=True, text=True)
        output = result.stdout
        self.assertIn("NO IOC OR CONTROLLER VALUES WERE CHANGED", output)
        self.assertIn("WARNING:", output)
        self.assertIn("SYS.16=60000", output)
        self.assertIn("record=TEST:m1", output)
        self.assertIn("MRES=0.0005 mm/pulse", output)
        self.assertIn("DIR=Neg", output)
        self.assertIn("SYS.2 home_method=7", output)
        self.assertIn("final state=DISABLED", output)
        self.assertNotIn("dbpf", output)

    def test_method_10_report_has_no_required_sensor(self):
        axes_text = axis_slots().replace(
            "sensors = L+\nhome_method = 7",
            "sensors = none\nhome_method = 10")
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            models = root / "models.ini"
            axes = root / "axes.ini"
            models.write_text(MODEL, encoding="utf-8")
            axes.write_text(axes_text, encoding="utf-8")
            result = subprocess.run(
                ["python3", str(TOOL), "--models", str(models),
                 "--axes", str(axes)],
                check=True, capture_output=True, text=True)
        self.assertIn("declared sensors=none", result.stdout)
        self.assertIn("selectable home methods=1..15 (user responsibility)",
                      result.stdout)
        self.assertIn("SYS.2 home_method=10", result.stdout)


if __name__ == "__main__":
    unittest.main()
