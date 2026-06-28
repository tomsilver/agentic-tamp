# agentic-tamp

Solve **individual** Task-and-Motion-Planning (TAMP) instances with a Claude
agent, and compare it head-to-head against the real
[TAMPEST](https://github.com/fbk-pso/tampest) solver.

Unlike [`~/robocode`](../robocode) — which trains one generalized policy over a
*distribution* of problems — this project points the agent at one concrete
instance. The agent receives the **same inputs** TAMPEST's solver gets (the
unified-planning task model plus the geometry: SE2 configurations, footprints,
motion models, and the occupancy-grid map), and must emit a plan. The plan is
graded by TAMPEST's own `check_plan` (task-level applicability + goal, and
motion-level collision-free feasibility) — so both sides are judged by an
identical feasibility criterion.

## How it works

```
build_instance ──► serialize_problem ──► [sandbox: problem.md + maps/*.png]
      │                                          │
      │                                   Claude agent (Docker) ──► plan.json
      │                                          │
      ▼                                          ▼
  TAMPEST solver (baseline)            parse + validate_plan (check_plan)
      │                                          │  invalid → feedback ─┐
      ▼                                          ▼                      │
   BaselineResult                          valid? ── yes ──► solved     │
                                                 └────────── no ────────┘ (retry, ≤ max_rounds)
```

- **Iterative feedback.** When a plan is rejected, the validator's diagnostics
  (e.g. *"Unreachable configurations: {0: [g]}, Collision obstacles: {0: [d0]}"*)
  are fed back to the agent in natural language and it tries again, up to
  `--rounds` times. This mirrors how TAMPEST refines a plan against motion
  feedback.
- **Docker sandbox.** Reuses the `robocode-sandbox` image and sandboxing
  approach from `~/robocode` (network firewall, write-restricted `/sandbox`,
  macOS-Keychain OAuth). See `agentic_tamp/sandbox_runner.py`.

## Agent modes

- `static` *(implemented)* — the agent reasons about geometry purely from the
  spec and the occupancy-map image; feasibility is checked after the fact.
- `tool` *(scaffolded, not yet wired)* — additionally exposes an in-container
  `check_move.py` so the agent can test motion feasibility while planning.
  Requires a tampest-enabled image (see `docker/`, TODO).

## Setup

```bash
uv venv --python 3.10 .venv
source .venv/bin/activate
uv pip install --prerelease=allow unified-planning
uv pip install -e ~/tampest          # pulls OMPL, pysmt, tempest, ...
uv pip install z3-solver==4.15.0 setuptools
```

The agent run also needs the Docker image built once (from the robocode repo):

```bash
bash ~/robocode/docker/build.sh    # builds robocode-sandbox
```

and a logged-in Claude CLI on the host (`claude login`) so the OAuth token is
available in the Keychain.

## Usage

```bash
# Head-to-head on the small doors instance (baseline + both models)
python -m agentic_tamp.compare --domain doors --d 1 --c 0 \
    --models opus,sonnet --modes static --rounds 3

# Just the baseline, or just the agent:
python -m agentic_tamp.compare --domain doors --d 1 --c 0 --no-agent
python -m agentic_tamp.compare --domain doors --d 1 --c 0 --no-baseline
```

Results (per-round records, plans, costs, timings) are written to
`results/<instance_id>/results.json` and a summary table is printed.

## Layout

| File | Role |
|------|------|
| `agentic_tamp/instances.py` | Build a TAMP instance + matching motion params (mirrors `run.py`). |
| `agentic_tamp/serialize.py` | UP `Problem` → Markdown spec; export occupancy maps into the sandbox. |
| `agentic_tamp/plan_io.py` | Parse the agent's `plan.json` → `SequentialPlan`. |
| `agentic_tamp/validate.py` | Task-level (simulator) + motion-level (`check_plan`) validation; diagnostics → feedback. |
| `agentic_tamp/baseline.py` | Run the TAMPEST solver in a child process with a timeout. |
| `agentic_tamp/sandbox_runner.py` | Launch the `claude` CLI in the Docker sandbox (adapted from robocode). |
| `agentic_tamp/prompts.py` | System / user prompts and feedback formatting. |
| `agentic_tamp/agent_solver.py` | The iterative solve loop. |
| `agentic_tamp/compare.py` | CLI entry point + comparison table. |
