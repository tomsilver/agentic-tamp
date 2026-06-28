"""Reproduce TAMPEST baseline coverage over a benchmark parameter grid.

Runs the TAMPEST solver (no agent) across a domain's (d, c) grid for a given
topological refinement and motion planner, recording coverage and per-instance
planning time. For the doors domain this targets the ECAI 2024 Table 2 numbers
(TAMPEST + RRT: 17/24 with No-Refinements, 24/24 with All-Refinements;
1800 s timeout, t_rho = 3 s).

Example::

    python -m agentic_tamp.sweep --domain doors \
        --d 1,2,4,6,8,10 --c 0,1,2,3 --tr all --mp RRT \
        --mp-time 3.0 --timeout 300
"""

import argparse
import csv
import json
import time
from pathlib import Path

from agentic_tamp.baseline import run_baseline
from agentic_tamp.quiet import quiet_ompl

SWEEP_ROOT = Path(__file__).resolve().parent.parent / "results" / "sweeps"


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="TAMPEST baseline coverage sweep.")
    p.add_argument("--domain", default="doors")
    p.add_argument("--dim", default="2D")
    p.add_argument("--d", default="1,2,4,6,8,10", help="comma list of d values")
    p.add_argument("--c", default="0,1,2,3", help="comma list of c values")
    p.add_argument("--tr", default="all", help="topological refinement(s), comma list")
    p.add_argument("--mp", default="RRT", help="motion planner(s), comma list")
    p.add_argument("--mp-time", type=float, default=3.0, help="t_rho per motion call")
    p.add_argument("--timeout", type=float, default=300.0, help="per-instance timeout s")
    p.add_argument("--capacity", type=int, default=None)
    p.add_argument("--tag", default=None, help="label for output files")
    return p.parse_args(argv)


def _ints(s: str) -> list[int]:
    return [int(x) for x in s.split(",") if x.strip()]


def _strs(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def run_sweep(args) -> dict:
    quiet_ompl()
    d_vals = _ints(args.d)
    c_vals = _ints(args.c)
    tr_vals = _strs(args.tr)
    mp_vals = _strs(args.mp)

    rows: list[dict] = []
    total = len(d_vals) * len(c_vals) * len(tr_vals) * len(mp_vals)
    i = 0
    for mp in mp_vals:
        for tr in tr_vals:
            for d in d_vals:
                for c in c_vals:
                    i += 1
                    build_kwargs = dict(
                        domain=args.domain,
                        dim=args.dim,
                        d=d,
                        c=c,
                        mp=mp,
                        tr=tr,
                        capacity=args.capacity,
                    )
                    print(
                        f"[{i}/{total}] {args.domain} d={d} c={c} tr={tr} mp={mp} "
                        f"(timeout {args.timeout}s) ...",
                        flush=True,
                    )
                    res = run_baseline(
                        build_kwargs,
                        timeout=args.timeout,
                        extra_params={"motion_planning_time": args.mp_time},
                    )
                    row = {
                        "domain": args.domain,
                        "d": d,
                        "c": c,
                        "tr": tr,
                        "mp": mp,
                        "solved": res.solved,
                        "status": res.status,
                        "time": round(res.wall_time, 2),
                        "plan_len": res.plan_len,
                        "timed_out": res.timed_out,
                    }
                    rows.append(row)
                    print(
                        f"    -> solved={res.solved} time={res.wall_time:.1f}s "
                        f"len={res.plan_len} status={res.status}",
                        flush=True,
                    )

    # Coverage summary per (mp, tr).
    summary = {}
    for mp in mp_vals:
        for tr in tr_vals:
            sub = [r for r in rows if r["mp"] == mp and r["tr"] == tr]
            solved = sum(1 for r in sub if r["solved"])
            summary[f"{mp}/{tr}"] = {"solved": solved, "total": len(sub)}

    return {
        "domain": args.domain,
        "dim": args.dim,
        "mp_time": args.mp_time,
        "timeout": args.timeout,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "rows": rows,
    }


def _write_outputs(result: dict, tag: str) -> tuple[Path, Path]:
    SWEEP_ROOT.mkdir(parents=True, exist_ok=True)
    base = SWEEP_ROOT / tag
    json_path = base.with_suffix(".json")
    csv_path = base.with_suffix(".csv")
    json_path.write_text(json.dumps(result, indent=2))
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(result["rows"][0].keys()))
        writer.writeheader()
        writer.writerows(result["rows"])
    return json_path, csv_path


def _print_summary(result: dict) -> None:
    print("\n" + "=" * 60)
    print(f"SWEEP: {result['domain']} (t_rho={result['mp_time']}s, "
          f"timeout={result['timeout']}s)")
    print("=" * 60)
    print(f"{'config (mp/tr)':<22}{'coverage':<12}")
    print("-" * 60)
    for key, s in result["summary"].items():
        print(f"{key:<22}{s['solved']}/{s['total']}")
    print("=" * 60)


def main(argv=None) -> None:
    args = _parse_args(argv)
    tag = args.tag or (
        f"{args.domain}_{'_'.join(_strs(args.mp))}_{'_'.join(_strs(args.tr))}"
        f"_t{int(args.timeout)}"
    )
    result = run_sweep(args)
    json_path, csv_path = _write_outputs(result, tag)
    _print_summary(result)
    print(f"\nwrote {json_path}\n      {csv_path}")


if __name__ == "__main__":
    main()
