"""Bluesky plan wrapper for guarded fixed-point trajectories."""

from __future__ import annotations

from bluesky import plan_stubs as bps
from bluesky import preprocessors as bpp

from kohzu_kinematics import (
    ExecutionPolicy,
    require_pose_matches,
    validate_execution,
)

from .trajectory_backend import OphydFiveAxisBackend, ROLE_TO_ATTRIBUTE


def fixed_point_trajectory_plan(trajectory, backend: OphydFiveAxisBackend, *,
                                policy: ExecutionPolicy = ExecutionPolicy()):
    """Move through a reviewed trajectory under RunEngine status control.

    This plan never enables or homes an axis. On exception, abort, halt or
    generator close after motion begins, its finalizer sends STOP to all five
    motors. Bluesky itself may also call ``stop()`` on movables during normal
    RunEngine cleanup; repeated normal STOP commands are required to be safe.
    """
    validate_execution(trajectory, policy)
    backend.verify_enabled()
    if policy.enforce_safety_checks:
        require_pose_matches(
            backend.read_pose(), trajectory.current_pose, policy,
            context="live start pose changed",
        )
    state = {"started": False, "completed": False}

    def body():
        previous_targets = trajectory.samples[0].pose.axis_values()
        for sample in trajectory.samples[1:]:
            if policy.enforce_safety_checks:
                backend.verify_safe()
            targets = sample.pose.axis_values()
            arguments = []
            for role in ROLE_TO_ATTRIBUTE:
                if targets[role] != previous_targets[role]:
                    arguments.extend((backend.motors[role], targets[role]))
            previous_targets = targets
            if not arguments:
                continue
            state["started"] = True
            yield from bps.mv(*arguments, timeout=policy.sample_timeout_s)
            if policy.enforce_safety_checks:
                require_pose_matches(
                    backend.read_pose(), sample.pose, policy,
                    context=f"sample {sample.index} endpoint mismatch",
                )
        state["completed"] = True

    def cleanup():
        if policy.stop_on_failure and state["started"] and not state["completed"]:
            for role in ROLE_TO_ATTRIBUTE:
                yield from bps.stop(backend.motors[role])

    return (yield from bpp.finalize_wrapper(body(), cleanup()))
