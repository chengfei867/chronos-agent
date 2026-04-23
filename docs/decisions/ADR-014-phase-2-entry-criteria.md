# ADR-014 — Phase 2 Entry Criteria

- **Status:** Accepted
- **Date:** 2026-04-23
- **Round:** R24
- **Relates to:** ADR-005 (adapter interface), ADR-010/011/012 (extractor contract evolution), ADR-013 (fork-exec stay frozen), `docs/roadmap.md` (Phase 2 milestones)
- **Supersedes:** none (this ADR does NOT change code — it formalizes a gating decision)

## Context

`docs/roadmap.md` names Phase 2 as *"Multi-agent + Web UI, v0.2"* with seven
bullet-point milestones (AutoGen adapter, multi-agent lanes, HTTP API, Web
UI, `chronos web`, fork-batch, v0.2.0 tag). It does **not** say when Phase
1 ends and Phase 2 begins, nor what would make starting Phase 2 a good
bet versus a premature widening of surface area.

Phase 1 has run 14 rounds past its technical MVP (R9 shipped v0.1.0 with
all named milestones). We have accumulated:

- 7 tagged releases (v0.1.0 → v0.1.6)
- 264 tests at 93 % coverage
- 13 ADRs
- 3 external-framework dogfood case studies (supervisor / swarm / bigtool)
- 1 self-hosted case study (fork via `--emit python`)
- 4 076 src LOC, 6 697 test LOC
- 0 external users, 0 GitHub issues, 0 production deployments
- 1 LLM backend (Claude Opus 4.7 via baidu-int OneAPI)
- 1 graph framework supported (LangGraph 1.1.9)

The temptation after each round is to open another Phase-1 line of work
(deeper CLI polish, another dogfood, another invariant). The question
this ADR answers is: **what would have to be true for opening the
AutoGen adapter to be a better use of the next round than another
Phase-1 increment?**

## Why this ADR, why now

Three forcing functions:

1. **R23-A proved the self-hosted dogfood loop works.** `--emit python`
   was exercised against our own R17 supervisor artifact, surfaced three
   real bugs, shipped fixes. Phase 1's internal testability story is
   closed.
2. **R10 near-miss is still the canonical red line.** At R10 this agent
   started `uv add autogen-agentchat` under a "自由发挥" authorization and
   caught itself only after re-reading CONTEXT.md. That event produced
   the rule *"自由发挥 does not override documented roadmap discipline."*
   R24 makes that rule falsifiable instead of vibe-based.
3. **ADR-013 freed the planning budget.** With fork-exec formally off
   the table, "what ships next?" needs a real answer. Without entry
   criteria, the answer drifts.

## Options Considered

### Option A — Open Phase 2 now on time-elapsed alone

Argument: we're at R24, v0.1.6, 93 % coverage, zero blockers. Phase 1
goals are checked off per roadmap. Keep momentum; start AutoGen adapter.

**Rejected.** Time-elapsed is not evidence. Zero external users means
zero external validation that the LangGraph adapter shape we built is
the right *abstract* shape — and Phase 2 bets on generalizing that shape
to AutoGen. Generalizing an unvalidated abstraction is the most
expensive way to discover it was wrong.

### Option B — Require external validation before Phase 2

Argument: mirror ADR-013's trigger-condition-1 ("external GitHub
issue"). Only open Phase 2 when a real user has used v0.1.x and found
its single-framework scope limiting.

**Rejected as sole gate.** Waiting for external users on a private repo
with no announcement is a tautology — there are none because nobody
knows it exists. That's a different decision (ADR-TBD on when to take
the repo public). Making Phase 2 blocked by it conflates two orthogonal
questions.

### Option C — Define a concrete entry checklist

Argument: list the *specific* signals that make AutoGen adapter work
high-leverage vs. premature. Each signal is independently verifiable.
Phase 2 opens when **all required** signals are present; optional
signals raise confidence but don't block.

**Accepted.** This is the pattern ADR-013 used for fork-exec trigger
conditions, reframed from "unfreeze" to "entry gate."

### Option D — Pick a proxy metric (tests, coverage, LOC)

Argument: cheap to check — e.g. "open Phase 2 at 300 tests" or "at
5 000 src LOC."

**Rejected.** These measure throughput, not readiness. We could hit
300 tests in two rounds of Phase-1 polish that don't change Phase 2
readiness at all.

## Decision

Phase 2 opens (AutoGen adapter development begins, `uv add
autogen-agentchat` becomes permitted, Phase 2 milestones in
`docs/roadmap.md` become active planning units) **iff all four required
entry criteria below are satisfied**. Optional criteria are
confidence-raisers; they do not block but their absence should be
explicitly acknowledged in the opening round's progress doc.

### Required (all four must be ✅)

1. **R1 — Adapter interface frozen.** `AdapterProtocol` (or whatever the
   adapter API is called at that point) has an ADR describing its stable
   surface, and at least one **non-trivial change** to the LangGraph
   adapter has been implementable without modifying the
   framework-neutral core (`chronos.core.*`). "Non-trivial" ≥ one
   public-API-visible change. This proves the abstraction boundary is
   real, not aspirational.

   *Current status:* ❌ adapter surface is implicit, no ADR-005 follow-up.
   We have `src/chronos/adapters/langgraph.py` with hand-edited extractor
   registration but no written contract that a second adapter would have
   to honor.

2. **R2 — Extractor contract v2 documented.** ADR-010 / 011 / 012
   collectively define the `UsageExtractor` protocol by evolution. A
   single ADR-TBD must consolidate: pre/post-state access, multi-LLM
   per node (R18/ADR-012), state-serialization boundary (R15/ADR-011),
   and what a framework-agnostic extractor contract looks like. AutoGen's
   message/tool model differs enough from LangGraph's that a
   consolidated v2 contract must be written *before* a second extractor
   is implemented, else the second implementation becomes the de-facto
   spec and drift compounds.

   *Current status:* ❌ contract is scattered across three ADRs + code.

3. **R3 — One adversarial LangGraph dogfood.** We have three topology
   dogfoods (supervisor/swarm/bigtool) that all *worked*. We need one
   dogfood that is **explicitly adversarial** — chosen because we
   predict Chronos will be awkward or wrong — and either it surfaces a
   real gap (fix it) or it doesn't (proves LangGraph adapter is
   battle-tested enough to generalize from). Candidates: streaming
   tokens via `.astream_events` (explicitly noted as untested in R17
   case study); sub-graph nesting (also noted as untested); a graph
   with side-effectful tools that hit real APIs (tests extractor
   robustness under error paths). Pick one; dogfood it; document.

   *Current status:* ❌ not attempted. All three prior dogfoods picked
   canonical topologies.

4. **R4 — CONTEXT.md §4 refreshed for Phase 2 discipline.** The
   current §4 encodes Phase-1 red lines (no AutoGen, no fork-exec).
   Phase 2 needs its own operational red lines — what AutoGen adapter
   is *not* allowed to do (e.g., pull in AutoGen's own serialization
   assumptions), what the Web UI is *not* allowed to do (e.g., mutate
   recorded runs), etc. Opening Phase 2 without refreshing this
   invites a Phase-2 equivalent of the R10 near-miss.

   *Current status:* ❌ §4 is Phase-1-specific.

### Optional (raise confidence, do not block)

- **O1 — Second LLM backend exercised.** Running any existing case
  study via a non-Anthropic backend (OpenAI `gpt-*`, Gemini) once.
  Confirms extractor registration pattern generalizes at the backend
  level. Absence-acknowledgement acceptable: "Phase 2 adapter work
  may surface Anthropic-coupling; revisit if it does."
- **O2 — External user signal.** ≥ 1 GitHub issue, star, or
  acknowledgement from a non-agent user. Raises confidence that
  widening surface area has any market. Private-repo posture makes
  this unlikely pre-Phase-2 and that's okay.
- **O3 — Performance baseline published.** `chronos runs list` on
  a 10k-run DB, `chronos replay` on a 500-step run. Phase 2 adds
  Web UI that will exercise these paths hard; knowing today's
  numbers lets us detect regressions. Nice-to-have, not blocking.

## Evidence quality disclaimer

Same disclaimer as ADR-013: one user, one backend, one framework. The
criteria above are calibrated to that reality:

- R1/R2/R3 are **internally verifiable** — they don't require external
  users, only disciplined self-work.
- R4 is process hygiene.
- The optional list (O1-O3) is where external validation lives;
  intentionally non-blocking so Phase 2 isn't hostage to the
  "go-public" decision.

If Chronos ever gains external users, expect this ADR to be
**superseded** by one that re-weights optional → required.

## Consequences

### Positive

- **Phase 2 is no longer a vibe call.** The four required criteria are
  things we either have or don't; a round's progress doc can just say
  "R1 ✅, R2 ❌ (why), R3 ❌ (why), R4 ❌ (why) — not yet."
- **R24-R27 planning has a target.** Each of R1-R4 is roughly one
  round's work. That gives 4 rounds of clearly-scoped Phase-1.5 work
  before Phase 2 opens, which is approximately where Phase 1 naturally
  slows its marginal returns.
- **Red line hardened.** R10 near-miss ("自由发挥 doesn't override
  roadmap discipline") is now backed by a checklist instead of
  memory. This agent can be handed the authorization to "开始 Phase 2"
  and correctly refuse until the checklist is green.
- **Composes with ADR-013.** Phase 2 entry can reopen fork-exec
  (ADR-013 trigger #3). The two ADRs form a two-stage gate: first get
  Phase 2 entry signed off, then re-evaluate fork-exec in the Phase-2
  context.

### Negative

- **Four rounds of work before the headline feature.** AutoGen adapter
  is the most "feature-list-visible" thing in the Phase 2 bullet list.
  Delaying it means 4+ rounds where the project's elevator pitch
  ("Chronos supports AutoGen too") doesn't advance. Mitigated by
  honest framing: the project isn't chasing feature-count.
- **Locks in a specific order.** Some users might argue "just start
  AutoGen and figure out the adapter interface retroactively."
  ADR-014 rejects that. If this turns out wrong, the ADR gets
  superseded; that's cheap.

### Neutral

- Code is unchanged by this ADR. No version bump required.
- Roadmap.md's Phase 2 bullet list stays as-is; this ADR is the gate,
  not a re-plan.

## Concrete R24 → R2X work breakdown (non-binding forecast)

- **R24** (this round): ship ADR-014 itself + small hygiene fixes
  (e.g., the FORCE_COLOR conftest fixture from v0.1.6 report
  Finding #1).
- **R25 candidate**: tackle **R2** (extractor contract v2 ADR) — it's
  the pre-requisite for R1 (adapter interface ADR) because the adapter
  API subsumes extractor registration.
- **R26 candidate**: tackle **R1** (adapter interface ADR). Write it,
  then prove it by refactoring one non-trivial LangGraph adapter
  change through it.
- **R27 candidate**: tackle **R3** (adversarial dogfood). Top pick:
  `.astream_events` streaming, because R17 explicitly flagged it as
  untested and Web UI will want streaming.
- **R28 candidate**: tackle **R4** (CONTEXT.md §4 Phase-2 refresh) +
  evaluate optional criteria. If all four required are ✅, **Phase 2
  opens in R29**.

This ordering is **non-binding** — unexpected signal (bug discovery,
external issue, reprioritization) can reorder R25-R28. The binding
commitment is the four required criteria, not the round numbers.

## Deferred alternatives (explicitly not done)

### A. "Also gate on a v1.0 stability commitment"
**Deferred.** v1.0 implies a compatibility promise we can't make with
zero external users. v0.x signals breaking-changes-allowed and that's
honest. Phase 2 opens at v0.2.x, not v1.0.

### B. "Set a round-count cap (e.g., open Phase 2 by R30 regardless)"
**Rejected.** Time-boxing forced readiness is option A in disguise.
The whole point of this ADR is to replace "time elapsed" with
"criteria met."

### C. "Include 'go public on GitHub' as a required criterion"
**Deferred to a future ADR.** Going public is a product decision
(branding, license, security posture) that is orthogonal to technical
Phase-2 readiness. Bundling them delays both for the wrong reasons.

## Related R24 work

R24 is the **formalization** round: the ADR itself is the deliverable.
No code change is mandated. A small co-shipped fix (FORCE_COLOR conftest
fixture, closing v0.1.6 report Finding #1) is included to keep the
round from being ADR-only.
