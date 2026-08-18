#!/usr/bin/env python3
"""Create missing local configuration files from tracked safe examples."""

from __future__ import annotations

import argparse
import pathlib


PROJECT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = PROJECT / "config"


def create_from_example(example: pathlib.Path, target: pathlib.Path) -> bool:
    """Create target exclusively from example, returning whether it was made."""
    if target.exists():
        return False
    if not example.is_file():
        raise FileNotFoundError(f"configuration example not found: {example}")
    contents = example.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as output:
            output.write(contents)
    except FileExistsError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-target",
        type=pathlib.Path,
        default=CONFIG / "runtime.ini",
    )
    parser.add_argument(
        "--assignments-target",
        type=pathlib.Path,
        default=CONFIG / "axis-assignments.ini",
    )
    arguments = parser.parse_args()

    pairs = (
        (CONFIG / "runtime.example.ini", arguments.runtime_target),
        (
            CONFIG / "axis-assignments.example.ini",
            arguments.assignments_target,
        ),
    )
    try:
        for example, target in pairs:
            if create_from_example(example, target):
                print(f"Created local configuration: {target}")
    except OSError as error:
        print(f"Cannot initialize local configuration: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
