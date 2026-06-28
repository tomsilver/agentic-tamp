"""In-container motion-feasibility tool for the agent's `tool` mode.

Reconstructs the TAMP instance from ``/sandbox/instance.json`` and checks
whether a single ``move`` between two configurations is geometrically feasible
under the given door positions, using TAMPEST's own
``MotionPlanner.check_motion_constraint`` — the same check that grades the
final plan. This is intentionally self-contained (no agentic_tamp import) so it
runs against the tampest install baked into the image.

Usage:
    check_move <from_config> <to_config> [<door>=<config> ...]

Doors not mentioned default to their initial positions. Prints FEASIBLE or
INFEASIBLE (with the blocking obstacle).
"""

import json
import os
import sys
from pathlib import Path

try:
    from ompl import util as _ou

    _ou.setLogLevel(_ou.LogLevel.LOG_ERROR)
except Exception:  # noqa: BLE001
    pass

from benchmarks import get_problem
from tampest.motion.motion_planner import MotionPlanner
from tampest.motion.motion_planning_data import (
    SupportedPlanner,
    SupportedTopologicalRefinement,
)

_PLANNERS = {
    "RRT": SupportedPlanner.RRT,
    "LazyRRT": SupportedPlanner.LazyRRT,
    "RRTConnect": SupportedPlanner.RRTConnect,
    "STRRTstar": SupportedPlanner.STRRTstar,
}
_REFINEMENTS = {
    "none": SupportedTopologicalRefinement.NONE,
    "unreach": SupportedTopologicalRefinement.UNREACH,
    "obs": SupportedTopologicalRefinement.OBS,
    "all": SupportedTopologicalRefinement.ALL,
}


def _load_instance(path="instance.json") -> dict:
    return json.loads(Path(path).read_text())


def _find_move_constraint(problem):
    """Return (motion_constraint, movable_type, door_objects) from a move action."""
    for a in problem.actions:
        for mc in getattr(a, "motion_constraints", []):
            doors = list(mc.static_obstacles.keys()) if mc.static_obstacles else []
            return mc, mc.movable.type, doors
    raise SystemExit("No motion constraint found in this problem.")


def main(argv) -> int:
    if len(argv) < 2:
        print("usage: check_move <from_config> <to_config> [<door>=<config> ...]")
        return 2

    from_name, to_name = argv[0], argv[1]
    overrides = {}
    for tok in argv[2:]:
        if "=" not in tok:
            print(f"Bad door spec {tok!r}; expected <door>=<config>.")
            return 2
        dname, cname = tok.split("=", 1)
        overrides[dname] = cname

    spec = _load_instance()
    extra = {
        k: spec[k]
        for k in ("capacity",)
        if k in spec and spec[k] is not None
    }
    problem = get_problem(
        domain=spec["domain"], dim=spec["dim"], d=spec["d"], c=spec["c"], **extra
    )
    objs = {o.name: o for o in problem.all_objects}

    for needed in (from_name, to_name):
        if needed not in objs:
            print(f"INFEASIBLE: unknown configuration '{needed}'.")
            return 1

    mc, movable_type, door_objs = _find_move_constraint(problem)
    robots = list(problem.objects(movable_type))
    if not robots:
        print("INFEASIBLE: no robot object found.")
        return 1
    robot = robots[0]

    # Build obstacle positions: each door at its override or initial config.
    obstacles = {}
    for d in door_objs:
        if d.name in overrides:
            cfg_name = overrides[d.name]
            if cfg_name not in objs:
                print(f"INFEASIBLE: unknown door config '{cfg_name}'.")
                return 1
            obstacles[d] = objs[cfg_name]
        else:
            fe = mc.static_obstacles[d]  # door_at(d)
            obstacles[d] = problem.initial_value(fe).object()

    planner = _PLANNERS.get(spec.get("mp", "RRT"), SupportedPlanner.RRT)
    refinement = _REFINEMENTS.get(
        spec.get("tr", "none"), SupportedTopologicalRefinement.NONE
    )
    distance = 5.0 if planner == SupportedPlanner.STRRTstar else None

    mp = MotionPlanner()
    res = mp.check_motion_constraint(
        {0: robot},
        {0: objs[from_name]},
        {0: objs[to_name]},
        obstacles,
        problem.all_objects,
        planning_time=spec.get("motion_planning_time", 5.0),
        interpolate=False,
        simplified=False,
        distance=distance,
        motion_planner=planner,
        topological_refinement=refinement,
        max_radius_bound=False,
        hull_enabled=True,
    )
    is_valid = res[0]
    unreachable_goals = res[5]
    collision_obstacles = res[6]

    if is_valid:
        print(f"FEASIBLE: move {from_name} -> {to_name} is collision-free.")
        return 0

    blockers = set()
    if isinstance(collision_obstacles, dict):
        for v in collision_obstacles.values():
            for o in v:
                blockers.add(getattr(o, "name", str(o)))
    reason = (
        f" blocked by {sorted(blockers)}" if blockers else " (no collision-free path)"
    )
    door_state = {d.name: obstacles[d].name for d in door_objs}
    print(
        f"INFEASIBLE: move {from_name} -> {to_name}{reason}. "
        f"Door positions used: {door_state}. "
        f"Unreachable goals: {unreachable_goals}."
    )
    return 1


if __name__ == "__main__":
    _code = main(sys.argv[1:])
    sys.stdout.flush()
    sys.stderr.flush()
    # OMPL/FCL C++ static destructors can SIGABRT at normal interpreter exit
    # (after the answer is already printed); os._exit skips them cleanly.
    os._exit(_code)
