# Agentic TAMP vs. TAMPEST — Results

> ⚠️ **Caveat:** all of this code and these experiments were Claude-generated and
> have **not been carefully reviewed or independently verified yet**. Treat the
> harness, the validation, and the numbers below as preliminary until audited.

**Question:** can a Claude agent, given the *same inputs* a TAMP solver gets for one
instance, produce valid plans — and how does it compare to TAMPEST (SMT-based)?

## Setup

- **Agent** gets the serialized UP problem (types, objects, fluents, init, goal,
  actions) + geometry (SE2 configs, footprints, occupancy-grid map as image +
  ASCII grid). It emits `plan.json`; we validate with TAMPEST's own `check_plan`
  (task-level applicability/goal **and** motion-level collision-free feasibility).
  Invalid plans feed the diagnostics back for up to N rounds.
- **Two agent modes:** `static` (reason from the spec only) and `tool` (also gets
  an in-container `check_move` that runs TAMPEST's real motion check).
- **Model:** Opus only. **Baseline:** TAMPEST engine, `tr=all`, RRT.
- **Parity:** both sides judge motion feasibility at the same budget (t_ρ = 3 s,
  matching the ECAI 2024 paper). Per-instance timeout 300 s (paper used 1800 s).
- Agent runs in a Docker sandbox (network firewall limiting egress to the Claude
  API + a write-restricted `/sandbox` working directory).

## Findings

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

Both scaling axes break TAMPEST: doors `d` (more doors), rover `d` (more
samples/rovers) **and** rover `c` (denser imaging → longer plans). This matches
the paper, which solves only 14/50 rover instances and explicitly blames "SMT
scalability issues when plans include many actions."

**2. The agent one-shot every instance** — including a 180-action multi-rover plan
with consumable camera calibration. The **iterative feedback loop never fired**:
Opus did not emit an invalid plan on any doors/rover instance. (Loop is built and
verified separately; just unexercised here.)

**3. Tool ≥ static, increasingly at scale.** Offloading geometry to `check_move`
is cheaper/faster, and the gap widens with plan length (d10 c4: tool **2.3× faster,
2× cheaper** than static). Tool is also structurally safer — it checks feasibility
instead of assuming it.

**4. Why the agent scales where SMT doesn't.** It pattern-matches the regular
structure (door chains, per-sample imaging) and *semantically prunes distractors*
— e.g. the doors `c=1` "connection configs" that balloon the SMT search are
irrelevant to the goal, so the agent simply ignores them.

## Caveats

- doors/rover are **structured, near-monotone** domains that favor LLM
  pattern-matching and punish SMT scaling. This is "LLM beats SMT on large
  structured instances," **not** "LLM is a better TAMP solver in general."
- The agent inherits no soundness/completeness guarantees; validity here is only
  as strong as `check_plan` (RRT at t_ρ = 3 s). It produces one plan, not a proof
  of (in)feasibility.
- 300 s timeout (vs paper's 1800 s) slightly understates baseline coverage near
  the cliff; but d=10 baselines time out even solo, so the qualitative result holds.

## Baseline doors coverage (partial sweep, tr=all, RRT, 300 s)

Solved 17/21 run before stopping; failures concentrate at large `d` and `c=1`
(d6c1, d8c1, d8c3, d10c0). The hard column is `c=1` (extra reachable configs).

## Reproduce

```bash
python -m agentic_tamp.compare --domain rover --d 8 --c 0 \
    --models opus --modes static,tool --tr all --mp-time 3
```
Raw per-run JSON is under `results/<instance_id>/results.json`.
