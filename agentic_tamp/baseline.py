"""Run the real TAMPEST solver on an instance, mirroring ``run.py``.

Produces the baseline result for the head-to-head comparison: whether the
TAMPEST engine solves the instance, how long it takes, and the plan it returns.
The solve runs in a child process so a per-instance timeout can be enforced
(the SMT/OMPL solve cannot be interrupted cleanly from a thread).
"""

import multiprocessing as mp
import time
from dataclasses import dataclass, field

from agentic_tamp.instances import MotionParams, build_instance
from agentic_tamp.quiet import quiet_ompl


@dataclass
class BaselineResult:
    solved: bool
    status: str
    plan: list[str] = field(default_factory=list)
    plan_len: int = 0
    wall_time: float = 0.0
    error: str | None = None
    timed_out: bool = False


def _register_engines() -> None:
    from unified_planning.shortcuts import get_environment

    env = get_environment()
    try:
        env.factory.add_engine("tampest", "tampest.engine", "TampestEngine")
    except Exception:  # noqa: BLE001 - already registered in this process
        pass
    env.credits_stream = None


def _solve_child(build_kwargs: dict, params: dict, q: "mp.Queue") -> None:
    quiet_ompl()
    import warnings

    warnings.simplefilter("ignore")
    try:
        from unified_planning.shortcuts import OneshotPlanner

        _register_engines()
        inst = build_instance(**build_kwargs)
        m: MotionParams = inst.motion
        engine_params = {
            "motion_planning_time": m.motion_planning_time,
            "interpolate": m.interpolate,
            "simplified": m.simplified,
            "distance": m.distance,
            "motion_planner": m.motion_planner,
            "topological_refinement": m.topological_refinement,
            "max_radius_bound": m.max_radius_bound,
            "incremental": m.incremental,
            "step_horizon": m.step_horizon,
        }
        engine_params.update(params)
        t0 = time.perf_counter()
        with OneshotPlanner(name="tampest", params=engine_params) as planner:
            res = planner.solve(inst.problem)
        wall = time.perf_counter() - t0
        plan = []
        if res.plan is not None:
            for ai in res.plan.actions:
                args = ", ".join(str(o) for o in ai.actual_parameters)
                plan.append(f"{ai.action.name}({args})")
        q.put(
            {
                "solved": res.plan is not None,
                "status": str(res.status),
                "plan": plan,
                "plan_len": len(plan),
                "wall_time": wall,
                "error": None,
            }
        )
    except Exception as exc:  # noqa: BLE001 - report solver failures as data
        import traceback

        q.put(
            {
                "solved": False,
                "status": "ERROR",
                "plan": [],
                "plan_len": 0,
                "wall_time": 0.0,
                "error": f"{exc}\n{traceback.format_exc()}",
            }
        )


def run_baseline(
    build_kwargs: dict,
    timeout: float | None = 300.0,
    extra_params: dict | None = None,
) -> BaselineResult:
    """Solve an instance with TAMPEST in a child process with a timeout.

    ``build_kwargs`` are forwarded to :func:`build_instance` (so the problem is
    constructed inside the child, avoiding pickling a UP problem).
    """
    ctx = mp.get_context("spawn")
    q: mp.Queue = ctx.Queue()
    proc = ctx.Process(
        target=_solve_child, args=(build_kwargs, extra_params or {}, q)
    )
    t0 = time.perf_counter()
    proc.start()
    proc.join(timeout)
    if proc.is_alive():
        proc.terminate()
        proc.join()
        return BaselineResult(
            solved=False,
            status="TIMEOUT",
            wall_time=time.perf_counter() - t0,
            timed_out=True,
            error=f"Baseline exceeded {timeout}s timeout.",
        )
    if q.empty():
        return BaselineResult(
            solved=False,
            status="CRASH",
            wall_time=time.perf_counter() - t0,
            error="Baseline process produced no result (crashed).",
        )
    data = q.get()
    return BaselineResult(
        solved=data["solved"],
        status=data["status"],
        plan=data["plan"],
        plan_len=data["plan_len"],
        wall_time=data["wall_time"],
        error=data["error"],
    )
