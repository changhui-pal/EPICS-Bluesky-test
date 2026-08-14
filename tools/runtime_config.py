#!/usr/bin/env python3
"""Read one validated value from config/runtime.ini for shell launchers."""

import argparse
import configparser
import pathlib
import sys


PROJECT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from kohzu_runtime import DEFAULT_RUNTIME_PATH, load_runtime_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=pathlib.Path, default=DEFAULT_RUNTIME_PATH)
    parser.add_argument("--get", required=True)
    arguments = parser.parse_args()
    try:
        print(load_runtime_config(arguments.config).get(arguments.get))
    except (ValueError, KeyError, configparser.Error, OSError) as error:
        print(f"Cannot read runtime configuration: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
