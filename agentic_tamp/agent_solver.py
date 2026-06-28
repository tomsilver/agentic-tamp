"""Iteratively solve a TAMP instance with a Claude agent and validate it.

One "round" launches the agent (a batch ``claude`` invocation in the Docker
sandbox) with the problem spec plus a growing history of previously rejected
plans and their validator feedback. The agent writes ``plan.json``; the harness
parses and validates it with TAMPEST's checker. On failure the feedback is
appended to the history and the agent is launched again, up to ``max_rounds``.
This mirrors how TAMPEST itself refines a plan against motion feedback, but the
refinement signal here is delivered to the agent in natural language.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from agentic_tamp.instances import Instance
from agentic_tamp.plan_io import PlanParseError, parse_plan_file
from agentic_tamp.prompts import CLAUDE_MD, SYSTEM_PROMPT, build_user_prompt
from agentic_tamp.sandbox_runner import run_agent, setup_sandbox
from agentic_tamp.serialize import serialize_problem
from agentic_tamp.validate import validate_plan

# Default image: the agentic-tamp-sandbox superset (TAMPEST + Pillow + check_move).
# `tool` mode requires it; `static` benefits from it (precise map inspection).
DEFAULT_IMAGE = "agentic-tamp-sandbox"


@dataclass
class RoundRecord:
    round: int
    agent_ok: bool  # agent produced a plan.json this round
    parsed: bool
    valid: bool
    plan: list[str] = field(default_factory=list)
    feedback: str = ""
    cost_usd: float | None = None
    num_turns: int = 0
    error: str | None = None


@dataclass
class AgentSolveResult:
    solved: bool
    rounds: int
    plan: list[str]
    total_cost_usd: float
    wall_time: float
    model: str
    mode: str
    round_records: list[RoundRecord] = field(default_factory=list)
    error: str | None = None


def _plan_to_strings(plan) -> list[str]:
    out = []
    for ai in plan.actions:
        args = ", ".join(str(o) for o in ai.actual_parameters)
        out.append(f"{ai.action.name}({args})")
    return out


def solve_with_agent(
    instance: Instance,
    sandbox_dir: Path,
    *,
    model: str,
    mode: str = "static",
    max_rounds: int = 3,
    max_budget_usd: float = 5.0,
    image: str | None = None,
) -> AgentSolveResult:
    """Run the iterative agent loop on ``instance``; return the outcome."""
    if mode not in ("static", "tool"):
        raise ValueError(f"Unknown mode: {mode!r}")

    sandbox_dir = Path(sandbox_dir)
    setup_sandbox(sandbox_dir, CLAUDE_MD)

    serialized = serialize_problem(instance.problem, sandbox_dir)
    (sandbox_dir / "problem.md").write_text(serialized.markdown)

    # `tool` mode exposes the in-container check_move tool, which rebuilds the
    # instance from this spec file.
    if mode == "tool":
        (sandbox_dir / "instance.json").write_text(json.dumps(instance.spec(), indent=2))

    image_kwargs = {"image": image or DEFAULT_IMAGE}
    history: list[dict] = []
    records: list[RoundRecord] = []
    total_cost = 0.0
    t0 = time.perf_counter()

    for r in range(1, max_rounds + 1):
        prompt = build_user_prompt(serialized.markdown, mode, history)
        run = run_agent(
            sandbox_dir,
            prompt,
            model=model,
            output_filename="plan.json",
            system_prompt=SYSTEM_PROMPT,
            max_budget_usd=max_budget_usd,
            log_path=sandbox_dir / "agent_log.txt",
            **image_kwargs,
        )
        cost = run.total_cost_usd or 0.0
        total_cost += cost

        if not run.success:
            # Agent errored or never wrote plan.json.
            fb = run.error or "You did not write plan.json."
            records.append(
                RoundRecord(
                    round=r,
                    agent_ok=False,
                    parsed=False,
                    valid=False,
                    feedback=fb,
                    cost_usd=cost,
                    num_turns=run.num_turns,
                    error=run.error,
                )
            )
            if run.rate_limit_reset:
                # Don't keep retrying into a rate limit.
                break
            history.append(
                {"plan_json": "(no plan.json written)", "feedback": fb}
            )
            continue

        plan_path = sandbox_dir / "plan.json"
        plan_json_text = plan_path.read_text()
        try:
            plan = parse_plan_file(plan_path, instance.problem)
        except PlanParseError as exc:
            fb = f"Your plan.json could not be parsed: {exc}"
            records.append(
                RoundRecord(
                    round=r,
                    agent_ok=True,
                    parsed=False,
                    valid=False,
                    feedback=fb,
                    cost_usd=cost,
                    num_turns=run.num_turns,
                )
            )
            history.append({"plan_json": plan_json_text, "feedback": fb})
            continue

        result = validate_plan(instance.problem, plan, instance.motion)
        plan_strs = _plan_to_strings(plan)
        records.append(
            RoundRecord(
                round=r,
                agent_ok=True,
                parsed=True,
                valid=result.valid,
                plan=plan_strs,
                feedback=result.feedback,
                cost_usd=cost,
                num_turns=run.num_turns,
            )
        )
        if result.valid:
            return AgentSolveResult(
                solved=True,
                rounds=r,
                plan=plan_strs,
                total_cost_usd=total_cost,
                wall_time=time.perf_counter() - t0,
                model=model,
                mode=mode,
                round_records=records,
            )
        history.append({"plan_json": plan_json_text, "feedback": result.feedback})

    return AgentSolveResult(
        solved=False,
        rounds=len(records),
        plan=records[-1].plan if records else [],
        total_cost_usd=total_cost,
        wall_time=time.perf_counter() - t0,
        model=model,
        mode=mode,
        round_records=records,
        error=records[-1].error if records else "no rounds executed",
    )
