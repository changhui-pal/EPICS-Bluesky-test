#!/usr/bin/env python3
"""Review or explicitly execute a fixed-point trajectory through Bluesky."""

from __future__ import annotations

import argparse
import hmac
import pathlib
import sys


PROJECT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from bluesky import RunEngine  # noqa: E402
from ophyd import EpicsSignalRO  # noqa: E402

from kohzu_kinematics import (  # noqa: E402
    CagetNumericReader,
    ExecutionPolicy,
    SnapshotPreflightError,
    calculate_snapshot_dry_run,
    capture_five_axis_snapshot,
    format_trajectory_report,
    trajectory_approval_sha256,
)
from kohzu_ophyd import (  # noqa: E402
    OphydFiveAxisBackend,
    SafeStopEpicsMotor,
    fixed_point_trajectory_plan,
)
from kohzu_runtime import runtime_from_argv  # noqa: E402


def authorize_execution(*, execute: bool, supplied_hash: str | None,
                        expected_hash: str,
                        allow_collision_unchecked: bool,
                        safety_checks: bool = False) -> None:
    """Require all independent execution gates or retain read-only mode."""
    if not execute:
        return
    if not safety_checks:
        return
    if not allow_collision_unchecked:
        raise ValueError("--execute requires --allow-collision-unchecked")
    if supplied_hash is None or not hmac.compare_digest(supplied_hash, expected_hash):
        raise ValueError("--approve-plan-sha256 must exactly match this dry-run")


def parser() -> argparse.ArgumentParser:
    runtime_path, runtime = runtime_from_argv()
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--runtime-config", type=pathlib.Path,
                        default=runtime_path)
    result.add_argument("--prefix", default=runtime.epics_prefix)
    result.add_argument(
        "--epics-bin", type=pathlib.Path,
        default=runtime.epics_bin,
    )
    result.add_argument("--fixed-x", type=float, required=True)
    result.add_argument("--fixed-y", type=float, required=True)
    result.add_argument("--fixed-z", type=float, required=True)
    result.add_argument("--target-pitch", type=float, required=True)
    result.add_argument("--target-yaw", type=float, required=True)
    result.add_argument("--duration", type=float, required=True)
    result.add_argument("--intervals", type=int, required=True)
    result.add_argument("--maximum-age", type=float, default=5.0)
    result.add_argument("--connection-timeout", type=float, default=5.0)
    result.add_argument("--execute", action="store_true")
    result.add_argument("--approve-plan-sha256")
    result.add_argument("--allow-collision-unchecked", action="store_true")
    result.add_argument(
        "--safety-checks", action="store_true",
        help="opt in to the preserved approval/state/STOP safety experiment",
    )
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        snapshot = capture_five_axis_snapshot(
            CagetNumericReader(arguments.epics_bin), prefix=arguments.prefix,
            maximum_age_s=(
                arguments.maximum_age if arguments.safety_checks else 1.0e12
            ),
        )
        result = calculate_snapshot_dry_run(
            snapshot,
            fixed_point_surface_mm=(
                arguments.fixed_x, arguments.fixed_y, arguments.fixed_z,
            ),
            target_pitch_deg=arguments.target_pitch,
            target_yaw_deg=arguments.target_yaw,
            duration_s=arguments.duration,
            intervals=arguments.intervals,
        )
        trajectory = result.trajectory
        approval = trajectory_approval_sha256(
            trajectory, context=f"EPICS prefix={arguments.prefix}"
        )
        continuous_target = result.continuous_trajectory.target_pose
        print(
            "Continuous target before MRES quantization: "
            f"X={continuous_target.x_mm:.9f} Y={continuous_target.y_mm:.9f} "
            f"Z={continuous_target.z_mm:.9f} "
            f"Pitch={continuous_target.pitch_deg:.9f} "
            f"Yaw={continuous_target.yaw_deg:.9f}"
        )
        print(format_trajectory_report(trajectory))
        print(
            "Quantized executable maximum residual: "
            f"{trajectory.maximum_residual_mm:.12g} mm"
        )
        print(f"PLAN SHA256: {approval}")
        if not arguments.execute:
            print("READ-ONLY REVIEW COMPLETE: no hardware writes")
            return 0 if trajectory.all_within_limits else 3

        authorize_execution(
            execute=True, supplied_hash=arguments.approve_plan_sha256,
            expected_hash=approval,
            allow_collision_unchecked=arguments.allow_collision_unchecked,
            safety_checks=arguments.safety_checks,
        )
        motors = {
            role: SafeStopEpicsMotor(
                f"{arguments.prefix}m{axis}", name=f"kohzu_{role}"
            )
            for role, axis in zip(("x", "y", "z", "pitch", "yaw"), range(1, 6))
        }
        for motor in motors.values():
            motor.wait_for_connection(timeout=arguments.connection_timeout)
        emergency = None
        if arguments.safety_checks:
            emergency = EpicsSignalRO(
                arguments.prefix + "Recovery:EmergencyActive",
                name="kohzu_emergency_active",
            )
            emergency.wait_for_connection(timeout=arguments.connection_timeout)
        backend = OphydFiveAxisBackend(
            motors, emergency, safety_checks=arguments.safety_checks
        )
        backend.verify_enabled()
        if arguments.safety_checks:
            backend.verify_safe()
        RunEngine({})(fixed_point_trajectory_plan(
            trajectory, backend,
            policy=ExecutionPolicy(
                allow_collision_unchecked=arguments.allow_collision_unchecked,
                enforce_safety_checks=arguments.safety_checks,
                stop_on_failure=arguments.safety_checks,
            ),
        ))
        print("EXECUTION COMPLETE")
        return 0
    except (ValueError, SnapshotPreflightError, TimeoutError) as exc:
        print(f"Fixed-point run rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
