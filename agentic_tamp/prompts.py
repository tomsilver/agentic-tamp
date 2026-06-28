"""Prompt construction for the agentic TAMP solver."""

from agentic_tamp.plan_io import PLAN_FORMAT_DOC

SYSTEM_PROMPT = (
    "You are an expert at Task and Motion Planning (TAMP). You are given a "
    "single planning instance: a symbolic task model (types, objects, fluents, "
    "initial state, goal, and actions) together with the geometry that the "
    "actions' motion constraints depend on (SE2 configurations, robot/door "
    "footprints, motion models, and an occupancy-grid map). Your job is to "
    "output a single plan — a sequence of grounded actions — that reaches the "
    "goal such that (a) every action's preconditions hold when applied in "
    "order, and (b) every motion constraint is geometrically feasible: a "
    "collision-free path exists for the chosen configurations given the "
    "obstacle (e.g. door) positions at that step.\n\n"
    "Think carefully about geometry. A direct move between two configurations "
    "may be blocked by a closed door or a wall; you may need to first perform "
    "an action that changes the world (e.g. open a door) or route through an "
    "intermediate configuration. Use the Read tool to open the occupancy-map "
    "image and inspect the obstacle layout before committing to a plan."
)

# CLAUDE.md placed in the sandbox.
CLAUDE_MD = (
    "You are solving ONE task-and-motion-planning instance in this directory.\n"
    "- The problem is described in `problem.md`.\n"
    "- Occupancy-map image(s) are under `maps/` — open them with the Read tool.\n"
    "- Write your final answer to `plan.json` using RELATIVE paths only.\n"
    "- Never write files outside this directory.\n"
)


def _history_section(history: list[dict]) -> str:
    """Render prior failed attempts and their validator feedback."""
    if not history:
        return ""
    blocks = [
        "## Previous attempts (these FAILED — do not repeat them)",
        "",
    ]
    for i, h in enumerate(history, 1):
        blocks.append(f"### Attempt {i}")
        blocks.append("Plan you proposed:")
        blocks.append("```json")
        blocks.append(h["plan_json"])
        blocks.append("```")
        blocks.append("Why it failed:")
        blocks.append(h["feedback"])
        blocks.append("")
    return "\n".join(blocks)


def _tool_section(mode: str) -> str:
    """Mode-specific instructions about feasibility tooling."""
    if mode == "tool":
        return (
            "## Feasibility tool\n\n"
            "You can test whether a single `move` is geometrically feasible "
            "before committing to it. In a Bash shell, run:\n\n"
            "    check_move <from_config> <to_config> [<door>=<config> ...]\n\n"
            "Each `<door>=<config>` sets that door's position for the check "
            "(e.g. `d0=o0` means door d0 is open); doors you omit stay at their "
            "initial positions. It prints FEASIBLE or INFEASIBLE (with the "
            "blocking obstacle). This is the SAME motion check used to grade "
            "your plan, so verify every move under the door positions in effect "
            "at that step before writing plan.json.\n\n"
            "Examples:\n"
            "    check_move s b0            # move with all doors at initial state\n"
            "    check_move b0 g d0=o0      # move from b0 to g with door d0 open\n\n"
        )
    return (
        "## Geometry\n\n"
        "There is no feasibility tool available; reason about feasibility "
        "yourself from the configurations, footprints, and the occupancy-map "
        "image. Your plan will be graded by a motion planner, so be careful "
        "that every move is actually collision-free.\n\n"
    )


def build_user_prompt(problem_markdown: str, mode: str, history: list[dict]) -> str:
    """Assemble the per-round user prompt."""
    parts = [
        "Solve the following TAMP instance. The full description is also saved "
        "in `problem.md` in your working directory, and the occupancy map is "
        "under `maps/` (open it with the Read tool).",
        "",
        problem_markdown,
        "",
        _tool_section(mode),
        _history_section(history),
        "## Output",
        "",
        PLAN_FORMAT_DOC,
        "",
        "First inspect the map image, reason about which moves are feasible and "
        "what must change in the world to enable them, then write the final "
        "`plan.json`. Make sure `plan.json` always contains your best current "
        "attempt before you finish.",
    ]
    return "\n".join(parts)
