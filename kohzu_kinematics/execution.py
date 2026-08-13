"""Hardware-adapter-independent execution guard for fixed-point trajectories."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Protocol

from .fixed_point import AXIS_NAMES, StagePose
from .trajectory import FixedPointTrajectory, TrajectorySample


class TrajectoryExecutionError(RuntimeError):
    """Raised after a trajectory is rejected or safely stopped."""


class TrajectoryBackend(Protocol):
    """Minimal boundary that a future EPICS or mock backend must implement."""

    def read_pose(self) -> StagePose:
        """Return the current public five-axis pose."""

    def verify_safe(self) -> None:
        """Reject EMG, motion, hardware-limit, LVIO, or disconnect state."""

    def command_sample(self, sample: TrajectorySample, timeout_s: float) -> StagePose:
        """Command all axes, wait for completion, and return the resulting pose."""

    def stop_all(self) -> None:
        """Issue a normal STOP to every participating axis."""


@dataclass(frozen=True)
class ExecutionPolicy:
    """Independent limits applied in addition to EPICS software limits."""

    linear_position_tolerance_mm: float = 0.002
    angular_position_tolerance_deg: float = 0.004
    maximum_linear_step_mm: float = 0.01
    maximum_angular_step_deg: float = 0.02
    sample_timeout_s: float = 2.0
    allow_collision_unchecked: bool = False
    enforce_safety_checks: bool = False
    stop_on_failure: bool = False

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if name in (
                "allow_collision_unchecked", "enforce_safety_checks",
                "stop_on_failure",
            ):
                continue
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")


@dataclass(frozen=True)
class ExecutionResult:
    completed_samples: int
    final_pose: StagePose


def _tolerance(axis: str, policy: ExecutionPolicy) -> float:
    return (
        policy.linear_position_tolerance_mm
        if axis in ("x", "y", "z")
        else policy.angular_position_tolerance_deg
    )


def _pose_mismatches(actual: StagePose, expected: StagePose,
                     policy: ExecutionPolicy) -> Mapping[str, float]:
    actual_values = actual.axis_values()
    expected_values = expected.axis_values()
    return {
        axis: actual_values[axis] - expected_values[axis]
        for axis in AXIS_NAMES
        if abs(actual_values[axis] - expected_values[axis]) > _tolerance(axis, policy)
    }


def require_pose_matches(actual: StagePose, expected: StagePose,
                         policy: ExecutionPolicy, *, context: str) -> None:
    """Raise with axis deltas when two public poses differ beyond policy."""
    mismatch = _pose_mismatches(actual, expected, policy)
    if mismatch:
        details = ", ".join(f"{axis}={delta:+.12g}" for axis, delta in mismatch.items())
        raise TrajectoryExecutionError(f"{context}: {details}")


def validate_execution(trajectory: FixedPointTrajectory,
                       policy: ExecutionPolicy) -> None:
    """Reject a trajectory before the backend receives any command."""
    if not policy.enforce_safety_checks:
        return
    if trajectory.all_within_limits is not True:
        raise TrajectoryExecutionError("software limits were not passed at every sample")
    if not trajectory.collision_checked and not policy.allow_collision_unchecked:
        raise TrajectoryExecutionError("collision checking is incomplete")

    for previous, sample in zip(trajectory.samples, trajectory.samples[1:]):
        before = previous.pose.axis_values()
        after = sample.pose.axis_values()
        for axis in AXIS_NAMES:
            step = abs(after[axis] - before[axis])
            maximum = (
                policy.maximum_linear_step_mm
                if axis in ("x", "y", "z")
                else policy.maximum_angular_step_deg
            )
            if step > maximum:
                raise TrajectoryExecutionError(
                    f"sample {sample.index} {axis} step {step:.12g} exceeds {maximum:.12g}"
                )


def execute_trajectory(trajectory: FixedPointTrajectory,
                       backend: TrajectoryBackend, *,
                       policy: ExecutionPolicy = ExecutionPolicy()) -> ExecutionResult:
    """Execute samples with start/reached-pose checks and stop-on-any-failure."""
    validate_execution(trajectory, policy)
    actual = backend.read_pose()
    if policy.enforce_safety_checks:
        require_pose_matches(
            actual, trajectory.current_pose, policy, context="live start pose changed"
        )

    completed = 0
    try:
        for sample in trajectory.samples[1:]:
            if policy.enforce_safety_checks:
                backend.verify_safe()
            actual = backend.command_sample(sample, policy.sample_timeout_s)
            completed += 1
            if policy.enforce_safety_checks:
                require_pose_matches(
                    actual, sample.pose, policy,
                    context=f"sample {sample.index} endpoint mismatch",
                )
    except BaseException as exc:
        if not policy.stop_on_failure:
            raise
        try:
            backend.stop_all()
        except BaseException as stop_exc:
            raise TrajectoryExecutionError(
                f"trajectory failed ({exc}); STOP also failed ({stop_exc})"
            ) from exc
        if isinstance(exc, TrajectoryExecutionError):
            raise
        raise TrajectoryExecutionError(f"trajectory stopped after failure: {exc}") from exc

    return ExecutionResult(completed_samples=completed, final_pose=actual)
