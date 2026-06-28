"""Head-to-head comparison: TAMPEST solver vs. a Claude agent on one instance.

Example::

    python -m agentic_tamp.compare --domain doors --d 1 --c 0 \
        --models opus,sonnet --modes static --rounds 3
"""

import argparse
import dataclasses
import json
import time
from pathlib import Path

from agentic_tamp.agent_solver import solve_with_agent
from agentic_tamp.baseline import run_baseline
from agentic_tamp.instances import build_instance
from agentic_tamp.quiet import quiet_ompl

RESULTS_ROOT = Path(__file__).resolve().parent.parent / "results"


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Compare TAMPEST vs. agentic TAMP.")
    p.add_argument("--domain", default="doors")
    p.add_argument("--dim", default="2D")
    p.add_argument("--d", type=int, default=1)
    p.add_argument("--c", type=int, default=0)
    p.add_argument("--mp", default="RRT", help="motion planner (RRT, LazyRRT, ...)")
    p.add_argument("--tr", default="none", help="topological refinement")
    p.add_argument("--capacity", type=int, default=None)
    p.add_argument(
        "--models",
        default="opus",
        help="comma-separated agent models (Opus only by default)",
    )
    p.add_argument(
        "--modes",
        default="static,tool",
        help="comma-separated agent modes (static, tool)",
    )
    p.add_argument("--rounds", type=int, default=3, help="max agent feedback rounds")
    p.add_argument("--budget", type=float, default=5.0, help="USD budget per round")
    p.add_argument(
        "--mp-time",
        type=float,
        default=3.0,
        help="per-motion-call budget t_rho (s), used by baseline AND validator",
    )
    p.add_argument("--baseline-timeout", type=float, default=300.0)
    p.add_argument("--image", default=None, help="docker image override")
    p.add_argument("--no-baseline", action="store_true")
    p.add_argument("--no-agent", action="store_true")
    p.add_argument("--out", default=None, help="results json path")
    return p.parse_args(argv)


def _build_kwargs(args) -> dict:
    return dict(
        domain=args.domain,
        dim=args.dim,
        d=args.d,
        c=args.c,
        mp=args.mp,
        tr=args.tr,
        mp_time=args.mp_time,
        capacity=args.capacity,
    )


def _print_table(results: dict) -> None:
    print("\n" + "=" * 72)
    print(f"INSTANCE: {results['instance_id']}")
    print("=" * 72)
    header = f"{'approach':<28}{'solved':<8}{'time(s)':<10}{'plan_len':<10}{'cost($)':<10}"
    print(header)
    print("-" * 72)
    b = results.get("baseline")
    if b is not None:
        print(
            f"{'tampest (baseline)':<28}{str(b['solved']):<8}"
            f"{b['wall_time']:<10.2f}{b['plan_len']:<10}{'-':<10}"
        )
    for a in results.get("agents", []):
        label = f"agent[{a['model']}/{a['mode']}]"
        cost = a["total_cost_usd"]
        print(
            f"{label:<28}{str(a['solved']):<8}{a['wall_time']:<10.2f}"
            f"{len(a['plan']):<10}{cost:<10.3f}"
        )
    print("-" * 72)
    if b is not None and b["plan"]:
        print(f"baseline plan: {b['plan']}")
    for a in results.get("agents", []):
        tag = f"{a['model']}/{a['mode']}"
        print(f"agent[{tag}] plan ({a['rounds']} round(s)): {a['plan']}")
    print("=" * 72 + "\n")


def main(argv=None) -> None:
    quiet_ompl()
    args = _parse_args(argv)
    build_kwargs = _build_kwargs(args)
    instance = build_instance(**build_kwargs)
    run_dir = RESULTS_ROOT / instance.instance_id
    run_dir.mkdir(parents=True, exist_ok=True)

    results: dict = {
        "instance_id": instance.instance_id,
        "domain": args.domain,
        "dim": args.dim,
        "d": args.d,
        "c": args.c,
        "mp": args.mp,
        "tr": args.tr,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "baseline": None,
        "agents": [],
    }

    if not args.no_baseline:
        print(f"[baseline] solving {instance.instance_id} with TAMPEST ...")
        b = run_baseline(build_kwargs, timeout=args.baseline_timeout)
        results["baseline"] = dataclasses.asdict(b)
        print(f"[baseline] solved={b.solved} time={b.wall_time:.2f}s plan={b.plan}")

    if not args.no_agent:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        modes = [m.strip() for m in args.modes.split(",") if m.strip()]
        for mode in modes:
            for model in models:
                tag = f"{model}_{mode}"
                sandbox_dir = run_dir / f"agent_{tag}" / "sandbox"
                print(f"[agent] {model}/{mode}: launching (max {args.rounds} rounds) ...")
                try:
                    res = solve_with_agent(
                        instance,
                        sandbox_dir,
                        model=model,
                        mode=mode,
                        max_rounds=args.rounds,
                        max_budget_usd=args.budget,
                        image=args.image,
                    )
                except NotImplementedError as exc:
                    print(f"[agent] {model}/{mode}: SKIPPED ({exc})")
                    continue
                results["agents"].append(dataclasses.asdict(res))
                print(
                    f"[agent] {model}/{mode}: solved={res.solved} "
                    f"rounds={res.rounds} cost=${res.total_cost_usd:.3f} "
                    f"plan={res.plan}"
                )

    out_path = Path(args.out) if args.out else (run_dir / "results.json")
    out_path.write_text(json.dumps(results, indent=2))
    _print_table(results)
    print(f"results written to {out_path}")


if __name__ == "__main__":
    main()
