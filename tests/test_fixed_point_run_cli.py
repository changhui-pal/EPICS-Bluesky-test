#!/usr/bin/env python3
"""Tests for independent actual-execution approval gates."""

import importlib.util
import pathlib
import unittest


PROJECT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fixed_point_run", PROJECT / "tools" / "fixed_point_run.py"
)
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


class FixedPointRunAuthorizationTest(unittest.TestCase):
    def test_read_only_mode_requires_no_approval(self):
        RUN.authorize_execution(
            execute=False, supplied_hash=None, expected_hash="abc",
            allow_collision_unchecked=False,
        )

    def test_execute_requires_collision_acknowledgement(self):
        with self.assertRaisesRegex(ValueError, "allow-collision"):
            RUN.authorize_execution(
                execute=True, supplied_hash="abc", expected_hash="abc",
                allow_collision_unchecked=False, safety_checks=True,
            )

    def test_execute_requires_exact_hash(self):
        with self.assertRaisesRegex(ValueError, "exactly match"):
            RUN.authorize_execution(
                execute=True, supplied_hash="wrong", expected_hash="abc",
                allow_collision_unchecked=True, safety_checks=True,
            )

    def test_execute_accepts_all_gates(self):
        RUN.authorize_execution(
            execute=True, supplied_hash="abc", expected_hash="abc",
            allow_collision_unchecked=True, safety_checks=True,
        )

    def test_basic_execute_requires_no_safety_approval(self):
        RUN.authorize_execution(
            execute=True, supplied_hash=None, expected_hash="abc",
            allow_collision_unchecked=False, safety_checks=False,
        )


if __name__ == "__main__":
    unittest.main()
