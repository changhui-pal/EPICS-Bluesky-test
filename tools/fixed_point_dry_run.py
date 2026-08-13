#!/usr/bin/env python3
"""Read five motor states and print a fixed-point trajectory dry-run."""

from __future__ import annotations

import argparse
import pathlib
import sys


PROJECT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from kohzu_kinematics import (  # noqa: E402
    CagetNumericReader,
    SnapshotPreflightError,
    calculate_snapshot_dry_run,
    capture_five_axis_snapshot,
    format_trajectory_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only five-axis fixed-point trajectory dry-run"
    )
    parser.add_argument("--prefix", default="MOCK:")
    parser.add_argument(
        "--epics-bin",
        type=pathlib.Path,
        default=pathlib.Path("/usr/local/epics/base-7.0.7/bin/linux-x86_64"),
    )
    parser.add_argument("--fixed-x", type=float, required=True)
    parser.add_argument("--fixed-y", type=float, required=True)
    parser.add_argument("--fixed-z", type=float, required=True)
    parser.add_argument("--target-pitch", type=float, required=True)
    parser.add_argument("--target-yaw", type=float, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--intervals", type=int, required=True)
    parser.add_argument("--maximum-age", type=float, default=5.0)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        reader = CagetNumericReader(arguments.epics_bin)
        snapshot = capture_five_axis_snapshot(
            reader,
            prefix=arguments.prefix,
            maximum_age_s=arguments.maximum_age,
        )
        result = calculate_snapshot_dry_run(
            snapshot,
            fixed_point_surface_mm=(
                arguments.fixed_x,
                arguments.fixed_y,
                arguments.fixed_z,
            ),
            target_pitch_deg=arguments.target_pitch,
            target_yaw_deg=arguments.target_yaw,
            duration_s=arguments.duration,
            intervals=arguments.intervals,
        )
    except (ValueError, SnapshotPreflightError) as exc:
        print(f"Dry-run rejected: {exc}", file=sys.stderr)
        return 2

    print(
        f"Snapshot prefix={snapshot.prefix} maximum_dynamic_age="
        f"{snapshot.maximum_dynamic_age_s:.3f} s "
        f"server_timestamps_complete={str(snapshot.server_timestamps_complete).lower()}"
    )
    continuous_target = result.continuous_trajectory.target_pose
    print(
        "Continuous target before MRES quantization: "
        f"X={continuous_target.x_mm:.9f} Y={continuous_target.y_mm:.9f} "
        f"Z={continuous_target.z_mm:.9f} "
        f"Pitch={continuous_target.pitch_deg:.9f} "
        f"Yaw={continuous_target.yaw_deg:.9f}"
    )
    print(format_trajectory_report(result.trajectory))
    print(
        "Quantized executable maximum residual: "
        f"{result.trajectory.maximum_residual_mm:.12g} mm"
    )
    return 0 if result.trajectory.all_within_limits else 3


if __name__ == "__main__":
    raise SystemExit(main())
