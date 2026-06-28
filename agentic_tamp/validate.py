"""Validate a SequentialPlan with TAMPEST's own criteria.

A plan is valid iff:

1. **Task level** — every action's preconditions hold when applied in order
   (checked with ``UPSequentialSimulator``) and the goal holds at the end.
2. **Motion level** — every motion constraint is geometrically feasible: a
   collision-free path exists for the chosen configurations given the door
   positions at that step. This reuses TAMPEST's ``check_plan`` (the same
   checker the solver uses), whose printed diagnostics ("Unreachable
   configurations", "Collision obstacles", ...) are captured as agent feedback.
"""

import contextlib
import io
import warnings
from dataclasses import dataclass

from unified_planning.engines.sequential_simulator import UPSequentialSimulator

from tampest.check_plan import check_plan

from agentic_tamp.instances import MotionParams


@dataclass
class ValidationResult:
    """Outcome of validating a plan, with feedback suitable for the agent."""

    valid: bool
    task_ok: bool
    motion_ok: bool
    feedback: str  # empty when valid; otherwise a diagnostic for the agent
    motion_log: str = ""  # raw check_plan stdout (for logging/inspection)


def _check_task_level(problem, plan) -> tuple[bool, str]:
    """Check preconditions step-by-step and goal at the end."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sim = UPSequentialSimulator(problem, error_on_failed_checks=False)
        state = sim.get_initial_state()
        for i, ai in enumerate(plan.actions):
            unsat, reason = sim.get_unsatisfied_conditions(
                state, ai.action, ai.actual_parameters
            )
            if unsat:
                conds = ", ".join(str(c) for c in unsat)
                return False, (
                    f"Action {i} `{ai}` is not applicable: its preconditions are "
                    f"violated in the current state ({reason}). Unsatisfied: {conds}."
                )
            state = sim.apply(state, ai.action, ai.actual_parameters)
            if state is None:
                return False, f"Action {i} `{ai}` could not be applied."
        unmet_goals = sim.get_unsatisfied_goals(state)
        if unmet_goals:
            goals = ", ".join(str(g) for g in unmet_goals)
            return False, (
                f"The plan executes but the goal is not reached. Unsatisfied "
                f"goals: {goals}."
            )
    return True, ""


def _check_motion_level(problem, plan, motion: MotionParams) -> tuple[bool, str]:
    """Run TAMPEST's check_plan, capturing its diagnostics as feedback."""
    cache: dict = {}
    motion_planning_data: dict = {}
    buf = io.StringIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with contextlib.redirect_stdout(buf):
            is_valid, _durations, _new_conds = check_plan(
                cache,
                problem,
                plan,
                motion.motion_planning_time,
                motion.interpolate,
                motion.simplified,
                motion.distance,
                motion.motion_planner,
                motion.topological_refinement,
                motion.max_radius_bound,
                motion_planning_data,
            )
    return bool(is_valid), buf.getvalue()


def validate_plan(problem, plan, motion: MotionParams) -> ValidationResult:
    """Validate a plan at both the task and motion levels."""
    task_ok, task_feedback = _check_task_level(problem, plan)
    if not task_ok:
        return ValidationResult(
            valid=False, task_ok=False, motion_ok=False, feedback=task_feedback
        )

    motion_ok, motion_log = _check_motion_level(problem, plan, motion)
    if motion_ok:
        return ValidationResult(
            valid=True, task_ok=True, motion_ok=True, feedback="", motion_log=motion_log
        )

    feedback = (
        "The plan is task-level correct but at least one `move` is not "
        "geometrically feasible (a collision-free path does not exist for the "
        "chosen configurations given the door positions at that step). The "
        "motion checker reported:\n\n"
        f"{motion_log.strip()}\n\n"
        "Revise the plan so every move is feasible — e.g. open the blocking "
        "door before moving through it, or route via an intermediate "
        "configuration."
    )
    return ValidationResult(
        valid=False,
        task_ok=True,
        motion_ok=False,
        feedback=feedback,
        motion_log=motion_log,
    )
