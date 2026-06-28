# agentic-tamp

> ⚠️ **Caveat:** all of this code and these experiments were Claude-generated and
> have **not been carefully reviewed or independently verified yet**. Treat the
> harness, the validation, and the numbers below as preliminary until audited.

Solve **individual** Task-and-Motion-Planning (TAMP) instances with a Claude
agent, and compare it head-to-head against the
[TAMPEST](https://github.com/fbk-pso/tampest) solver.

## Why this exists

A personal exploration with two goals: (1) an excuse to get hands-on with
**TAMPEST** and its benchmark domains, and (2) out of curiosity, a head-to-head
comparison against **Claude as an agentic TAMP solver** — i.e. just handing the
model the same problem inputs a TAMP planner gets and seeing whether it can
produce valid plans. It is research code, not a polished tool (see the caveat at
the top).

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

## Results

> Preliminary — see the caveat at the top.

**Question:** can a Claude agent, given the *same inputs* a TAMP solver gets for
one instance, produce valid plans — and how does it compare to TAMPEST
(SMT-based)? Numbers below use **Opus** for the agent and **TAMPEST** (`tr=all`,
RRT) for the baseline, both judging motion feasibility at the same budget
(t_ρ = 3 s, matching the ECAI 2024 paper), with a 300 s per-instance timeout
(the paper used 1800 s).

**1. Small instances → TAMPEST wins; large instances → it cliffs and the agent doesn't.**

| domain | instance | baseline | agent static | agent tool |
|--------|----------|:--------:|:------------:|:----------:|
| doors | d1 c0 | ✅ 11 s | ✅ 49 s | — |
| doors | d2 c0 | ✅ 39 s | ✅ 103 s | ✅ 49 s |
| doors | d10 c0 | ❌ **timeout** | ✅ 111 s | ✅ 60 s |
| doors | d10 c1 | ❌ **timeout** | ✅ 82 s | ✅ 64 s |
| doors | d10 c2 | ❌ **timeout** | ✅ 121 s | ✅ 68 s |
| doors | d10 c3 | ❌ **timeout** | ✅ 141 s | ✅ 76 s |
| rover | d2 c0 | ✅ 13 s | ✅ 68 s | ✅ 68 s |
| rover | d4 c0 | ✅ 36 s | ✅ 100 s | ✅ 51 s |
| rover | d8 c0 | ❌ **timeout** | ✅ 125 s (32 acts) | ✅ 83 s |
| rover | d4 c4 | ❌ **timeout** | ✅ 141 s (72 acts) | ✅ 143 s |
| rover | d10 c4 | ❌ **timeout** | ✅ 445 s (**180 acts**) | ✅ 194 s |

All agent solves above were a single round. Both scaling axes break TAMPEST:
doors `d` (more doors), rover `d` (more samples/rovers) **and** rover `c` (denser
imaging → longer plans). This matches the paper, which solves only 14/50 rover
instances and explicitly blames "SMT scalability issues when plans include many
actions."

**2. The agent one-shot every instance** — including a 180-action multi-rover plan
with consumable camera calibration. The **iterative feedback loop never fired**:
Opus did not emit an invalid plan on any doors/rover instance. (The loop is built
and verified separately; just unexercised here.)

**3. Tool ≥ static, increasingly at scale.** Offloading geometry to `check_move`
is cheaper/faster, and the gap widens with plan length (d10 c4: tool **2.3× faster,
2× cheaper** than static). Tool is also structurally safer — it checks feasibility
instead of assuming it.

**4. Why the agent scales where SMT doesn't.** It pattern-matches the regular
structure (door chains, per-sample imaging) and *semantically prunes distractors*
— e.g. the doors `c=1` "connection configs" that balloon the SMT search are
irrelevant to the goal, so the agent simply ignores them.

### What this does *not* show

- doors/rover are **structured, near-monotone** domains that favor LLM
  pattern-matching and punish SMT scaling. This is "LLM beats SMT on large
  structured instances," **not** "LLM is a better TAMP solver in general."
- The agent inherits no soundness/completeness guarantees; validity here is only
  as strong as `check_plan` (RRT at t_ρ = 3 s). It produces one plan, not a proof
  of (in)feasibility.
- The 300 s timeout (vs the paper's 1800 s) understates baseline coverage near the
  cliff; but the d=10 baselines time out even solo, so the qualitative result holds.

A partial baseline doors sweep (tr=all, RRT, 300 s) solved 17/21 before stopping;
failures concentrate at large `d` and the `c=1` column (extra reachable configs):
d6c1, d8c1, d8c3, d10c0.

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
