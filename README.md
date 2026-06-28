# agentic-tamp

Solve **individual** Task-and-Motion-Planning (TAMP) instances with a Claude
agent, and compare it head-to-head against the
[TAMPEST](https://github.com/fbk-pso/tampest) solver.

## Why this exists

A personal exploration with two goals: (1) an excuse to get hands-on with
**TAMPEST** and its benchmark domains, and (2) out of curiosity, a head-to-head
comparison against **Claude as an agentic TAMP solver** — i.e. just handing the
model the same problem inputs a TAMP planner gets and seeing whether it can
produce valid plans. It is research code, not a polished tool (see the caveat at
the top of `RESULTS.md`).

The agent points at one concrete instance (not a generalized policy over a
distribution) and receives the **same inputs** TAMPEST's solver gets: the
unified-planning task model plus the geometry — SE2 configurations, footprints,
motion models, and the occupancy-grid map. It must emit a plan, which is graded
by TAMPEST's own `check_plan` (task-level applicability + goal, and motion-level
collision-free feasibility) — so both sides are judged by an identical
feasibility criterion.

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
- **Docker sandbox.** The agent runs in a Docker container with a
  network-egress firewall and a write-restricted `/sandbox` working directory;
  on macOS the Claude Code OAuth token is read from the Keychain. See
  `agentic_tamp/sandbox_runner.py`.

## Agent modes

- `static` — the agent reasons about geometry purely from the spec and the
  occupancy-map image; feasibility is checked after it submits.
- `tool` — additionally exposes an in-container `check_move` that runs TAMPEST's
  real motion check, so the agent can test feasibility while planning. Requires
  the tampest-enabled sandbox image (see `docker/`).

## Setup

```bash
uv venv --python 3.10 .venv
source .venv/bin/activate
uv pip install --prerelease=allow unified-planning
uv pip install "tampest @ git+https://github.com/fbk-pso/tampest.git"  # OMPL, pysmt, tempest, ...
uv pip install z3-solver==4.15.0 setuptools
```

The agent run also needs the sandbox Docker image built once:

```bash
bash docker/build.sh    # builds the agentic-tamp-sandbox image
```

> **Note:** `docker/Dockerfile` currently builds `FROM` a base image that
> provides the Claude Code CLI and a network-egress firewall; that base is not
> yet bundled in this repo, so building the image standalone requires such a
> base to be available. TODO: make the sandbox image fully self-contained.

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
| `agentic_tamp/sandbox_runner.py` | Launch the `claude` CLI in the Docker sandbox. |
| `agentic_tamp/prompts.py` | System / user prompts and feedback formatting. |
| `agentic_tamp/agent_solver.py` | The iterative solve loop. |
| `agentic_tamp/compare.py` | CLI entry point + comparison table. |
