"""Build TAMP problem instances and the motion-planning parameters to match.

Wraps TAMPEST's ``benchmarks.get_problem`` so the baseline solver, the agent's
plan validator, and the problem serializer all operate on the identical
instance and the identical motion-planning settings (mirroring ``run.py``).
"""

from dataclasses import dataclass

from benchmarks import get_problem
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


@dataclass(frozen=True)
class MotionParams:
    """Motion-planning settings shared by the solver and the validator.

    Defaults mirror ``tampest/run.py`` so a head-to-head comparison uses the
    same geometric feasibility criterion for both the baseline and the agent.
    """

    motion_planner: SupportedPlanner = SupportedPlanner.RRT
    topological_refinement: SupportedTopologicalRefinement = (
        SupportedTopologicalRefinement.NONE
    )
    motion_planning_time: float = 5.0
    interpolate: bool = False
    simplified: bool = False
    distance: float | None = None
    max_radius_bound: bool = False
    incremental: bool = True
    step_horizon: int = 50

    @staticmethod
    def from_cli(
        mp: str = "RRT", tr: str = "none", mp_time: float = 3.0
    ) -> "MotionParams":
        planner = _PLANNERS[mp]
        distance = 5.0 if planner == SupportedPlanner.STRRTstar else None
        return MotionParams(
            motion_planner=planner,
            topological_refinement=_REFINEMENTS[tr],
            motion_planning_time=mp_time,
            distance=distance,
        )


@dataclass(frozen=True)
class Instance:
    """A single TAMP problem instance plus its identity and motion settings."""

    instance_id: str
    domain: str
    dim: str
    d: int
    c: int
    problem: object  # unified_planning.model.Problem
    motion: MotionParams
    mp: str = "RRT"
    tr: str = "none"
    capacity: int | None = None

    def spec(self) -> dict:
        """JSON-serializable spec the in-container check_move tool reads."""
        return {
            "domain": self.domain,
            "dim": self.dim,
            "d": self.d,
            "c": self.c,
            "mp": self.mp,
            "tr": self.tr,
            "capacity": self.capacity,
            "motion_planning_time": self.motion.motion_planning_time,
        }


def build_instance(
    domain: str = "doors",
    dim: str = "2D",
    d: int = 1,
    c: int = 0,
    *,
    mp: str = "RRT",
    tr: str = "none",
    mp_time: float = 3.0,
    capacity: int | None = None,
    **kwargs,
) -> Instance:
    """Construct a TAMP instance, mirroring ``run.py`` argument handling.

    ``mp_time`` is the per-motion-call budget (t_rho); it is applied both to the
    baseline solver and to the agent's plan validator so both judge motion
    feasibility under the same budget (the ECAI 2024 doors setup uses 3 s).
    """
    extra = dict(kwargs)
    if capacity is not None:
        extra["capacity"] = capacity
    problem = get_problem(domain=domain, dim=dim, d=d, c=c, **extra)
    instance_id = f"{domain}_{dim}_d{d}_c{c}_{mp}_{tr}"
    return Instance(
        instance_id=instance_id,
        domain=domain,
        dim=dim,
        d=d,
        c=c,
        problem=problem,
        motion=MotionParams.from_cli(mp=mp, tr=tr, mp_time=mp_time),
        mp=mp,
        tr=tr,
        capacity=capacity,
    )
