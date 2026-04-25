# Fork sandbox feasibility — does Phase 3 actually need E2B / Modal?

**Status:** Research note (R42-A), 2026-04-25
**Author:** Hermes Agent (autonomous)
**Related ADRs:** ADR-005 (fork semantics), ADR-006 (fork algorithm, FROZEN),
ADR-008 (fork artifact JSON-only), ADR-013 (fork auto-execution, FROZEN)
**Related docs:** `docs/roadmap.md` §Phase 3, `docs/research/feasibility.md`,
`docs/research/multi-framework-risks.md` R-6
**Spike:** `tests/spikes/spike8_fork_sideeffect.py`

---

## TL;DR

The current Phase 3 roadmap lists **"side-effectful tool sandboxing (ADR-006;
use E2B or Modal)"** as its first milestone. After re-reading ADR-013 (which
froze fork auto-execution) and running `spike8_fork_sideeffect.py`, I believe
this milestone is **roadmap drift** — it was written before ADR-013, and the
architecture it presupposes (Chronos executes forks) no longer holds.

**Recommendation:** drop "side-effect sandboxing" from Phase 3's top-line
milestones. Replace with two narrower items:

1. **Docs + template** showing users the 3 idiomatic side-effect-mitigation
   patterns (MockTransport, envvar kill-switch, pure/effectful tool split).
   Cost: ~1 round. ROI: immediate.
2. **Instrumentation** — teach Chronos to *label* nodes that touched the
   network / filesystem, so the UI can warn "re-running this branch will
   re-trigger 3 side-effecting nodes" before the user fires off an
   `invoke(None, cfg_child)`. Cost: ~2-3 rounds. ROI: user-visible.

E2B / Modal sandbox integration stays valid only as a *later, optional*
Phase 3 item, and **only if** ADR-013 is reopened first — which requires one
of its documented triggers to fire (none have, as of R41).

---

## Background

### What ADR-013 says (R21)

> *Chronos does not execute forks. The `fork plan` command emits a JSON
> artifact; the user invokes their own graph with those overrides.*

Triggers for reopening: (1) external user request, (2) a framework topology
that can't round-trip through JSON, (3) a Phase-2 adapter that forces the
issue. **Zero of these have fired through R41** (checked commits R22→R41).

### What the roadmap says (`docs/roadmap.md` §Phase 3)

> *Side-effectful tool sandboxing (ADR-006; use E2B or Modal).*

This line predates ADR-013. At the time (pre-R21), there was a live question
about whether Chronos should execute forks. Once ADR-013 said "no", the
sandboxing item lost its natural home in the architecture but was never
re-examined.

### What `multi-framework-risks.md` R-6 already nailed

> *"`fork plan --emit python` … is already the correct UX — Chronos is out
> of the execute path; the user runs their own graph."*

I should have connected this to the Phase 3 item in R41. I didn't. Fixing it
now.

---

## The real question

**If the user runs the graph themselves, what's the actual side-effect
problem Chronos needs to solve?**

There are three candidate problems. Only one of them is Chronos's to own.

| # | Problem | Owner | Chronos action |
|---|---------|-------|----------------|
| P1 | Re-running nodes **before** the fork point re-triggers their side effects (e.g. LangGraph replaying `plan` + `post` when you fork at `final`) | LangGraph checkpointer | Verify — spike8 does this |
| P2 | Containing side effects **inside the fork** (the new branch's nodes that have yet to run) | **User's agent code** — it's their graph running on their machine | Docs + patterns, not infra |
| P3 | Chronos needs to execute forks in a sandbox for its own purposes (automated A/B, CI, replay-for-verification) | **Chronos** — but only if ADR-013 is reopened | Deferred |

Phase 3's current milestone implicitly assumes P3 is live. It isn't.

---

## Spike 8 — empirical check on P1

See `tests/spikes/spike8_fork_sideeffect.py`. Three-node graph (`plan` →
`post` → `final`), where `post` calls `httpx.post` through a
`MockTransport` call counter.

| Phase | Setup | httpx calls | Expected | Result |
|-------|-------|-------------|----------|--------|
| 1 | Fresh recorded run | 1 | 1 | ✅ |
| 2 | Fork AT `post`, override `post_result` (fork AFTER the side effect) | 0 | 0 | ✅ |
| 3 | Fork AT `plan`, override `plan` (fork BEFORE the side effect) | 1 | 1 | ✅ |

**Phase 2 is the money shot.** LangGraph's checkpointer already guarantees
that forking *after* a side-effecting node does not replay it. P1 is
solved, for free, by the framework itself.

(Phase 3 confirms the inverse: forking *before* a side-effecting node does
re-execute it on the new branch — which is the entire point of forking.
Users who fork upstream of `httpx.post` are, by definition, asking for that
fresh call.)

---

## So what should Phase 3 actually ship?

### Keep (narrow, high ROI)

- **PH3-01 (docs)** — Add `docs/guides/side-effects.md` showing the three
  idiomatic mitigation patterns:
  1. **Inject a mock transport** (`httpx.MockTransport`,
     `respx`, LangChain `FakeListLLM`) when forking upstream of an expensive
     tool — 5-line fixture template.
  2. **Envvar kill-switch pattern** — agent code checks `os.environ.get(
     "CHRONOS_DRY_RUN")` and short-circuits destructive tools. Zero-cost,
     composes with any framework.
  3. **Pure / effectful tool split** — encourage users to author tools as
     `(pure_planner, effectful_actuator)` pairs; fork reruns the planner
     cheap, then user decides whether to fire the actuator.

- **PH3-02 (instrumentation)** — Extend `nodes.kind` or add a
  `nodes.effects` column (network / fs / db tags) populated by the adapter
  from tool metadata. Surface in Web UI as a warning badge on ForkPlan:
  *"This fork re-executes 2 network-effectful nodes."* No new dependencies;
  pure metadata work.

### Drop from top-line Phase 3

- **"Side-effectful tool sandboxing (E2B or Modal)"** — parking-lot it.
  Reopen only when ADR-013 triggers fire. Adding E2B today would be
  building a runway for a plane we haven't committed to flying.

### Keep in parking lot (not ruled out, just not now)

- Automated fork execution inside Chronos CI (for regression tests on
  recorded agents). This would reopen ADR-013 cleanly via trigger #3
  ("Phase 2 adapter needs it") — *if* a real Phase 2 adapter ever does.

---

## Budget estimate if we adopt the recommendation

| Item | Rounds | Prereqs |
|------|--------|---------|
| PH3-01 docs + template | 1 | none |
| PH3-02 effect-kind instrumentation + UI badge | 2–3 | `nodes.effects` column; one adapter fills it |
| Update roadmap to reflect R42-A findings | 0.5 | this doc |
| **Total** | **3.5–4.5 rounds** | vs. original "10–20 rounds" E2B/Modal spike |

That's a ~3× time saving on Phase 3 entry, by *not* building something the
architecture doesn't want.

---

## Open questions (for user review)

1. **Should `nodes.effects` be schema-level or annotation-level?** Schema
   means a migration + typed enum. Annotation means free-form tags per
   adapter, lower friction but weaker UI guarantees. My weak preference:
   start annotation, promote to schema if UI needs stronger contracts.
2. **Do we need a dedicated ADR for "Chronos does not sandbox"?** ADR-013
   implies it; a crisp ADR-019 would make the contract explicit to external
   contributors. ~0.5 rounds. Probably worth it.
3. **Roadmap rewrite** — delete or reframe the "E2B/Modal" bullet? I lean
   "reframe" (keep it as a parking-lot item under Phase 4+) so the
   institutional memory survives.

---

## Decision requested

Approve / adjust the recommendation. If approved, R42-B spins up PH3-01
(docs) and PH3-02 (effect-kind instrumentation) as the new Phase 3 on-ramp.

— End of R42-A research note.
