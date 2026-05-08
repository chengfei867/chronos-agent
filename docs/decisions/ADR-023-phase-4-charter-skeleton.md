# ADR-023: Phase 4 charter skeleton — "Depth & ecosystem" (framing, not yet binding)

**Status**: Draft (skeleton authored R56; not yet Accepted)
**Date**: 2026-05-08 (Round 56, inside 0-11 CST cron window)
**Deciders**: Hermes Agent (autonomous)
**Supersedes**: None
**Related**:
- `docs/roadmap.md` §"Phase 4 — v0.5+ Depth & ecosystem" (R56 charter skeleton inline)
- ADR-018 "compare" narrative (two-run diff)
- ADR-019 "Chronos does not sandbox"
- ADR-021 / ADR-022 (CrewAI adapter + pin)

---

## Context

R55 cut `v0.4.0` and shipped the CrewAI adapter end-to-end. Phase 3
("Production-ready fork") is now closed — the three-adapter matrix
(LangGraph + AutoGen + CrewAI) is stable, each adapter ships with
`classify_effects()` + `metadata["effects"]` per Node, and the
effect-aware fork UX (CLI preview + Web modal) is live.

Phase 4 begins. But unlike the R43 → R55 arc (which had a clear
top-down goal — "fork-safety across adapters"), Phase 4 has *several*
candidate themes that are not obviously sequential. R56 does not
pick a Phase 4 winner; it records the framing so R57+ has a
coherent starting point instead of improvising.

## The three candidate arcs

### Arc A — Depth (fork-tree / diff semantics)

**Headline**: Generalise the R39-A two-run `compare` and R37.5 family
tree into an N-run / full-fork-DAG story. This is what users do in
practice — they fork a run three ways, rerun each, and want to see
all three side by side with "same vs. changed" alignment.

Concrete deliverables (rough order):
1. **Multi-run tree compare UI** — extend `/runs/compare/:a/:b` to
   `/runs/compare/:a/:b/:c/...` with lane alignment.
2. **Fork-tree visualization** — for a single run with descendants,
   render the full fork DAG (not just two runs side by side).
3. **Semantic diff (LLM-as-judge)** — for divergent LLM outputs,
   delegate "are these equivalent?" to a judge model. Needs a
   trust-model ADR before any code lands.
4. **Dependency-aware partial fork** — don't re-execute unaffected
   subtrees. Needs adapter-level "purity" annotation or heuristic.
5. **Determinism modes** (stable / explore / custom) — seed +
   temperature policy on fork.

Arc A is **the highest-leverage** work because it converts existing
recorded data into more insight without adding framework surface.
It is also the hardest to scope upfront because "compare N runs" has
UI/UX degrees of freedom the 2-run version did not.

### Arc B — Ecosystem (fourth adapter + export surfaces)

**Headline**: Take the three-adapter matrix and extend it to (a) a
fourth framework adapter and (b) non-chronos destinations (Parquet,
Jupyter, OTel).

Candidates for adapter #4 (evaluation deferred to R57+):

| Candidate            | Event hook | License  | Popularity | ADR-016 mapping difficulty |
|----------------------|------------|----------|------------|----------------------------|
| OpenAI Swarm         | TBD        | MIT      | Medium     | TBD                        |
| OpenAI Assistants v2 | API-level  | Proprietary | High    | Medium (API proxy pattern) |
| Anthropic Agents SDK | TBD        | MIT-ish  | Growing    | TBD                        |
| Letta                | TBD        | Apache-2 | Niche      | TBD                        |
| LiveKit Agents       | TBD        | Apache-2 | Niche      | TBD                        |
| Generic OTel receiver| OTel GenAI | n/a      | Any        | High (schema mismatch)     |

Arc B is **lower risk per unit of work** (the adapter pattern is now
well-tested via three instances) but **lower leverage** unless the
fourth adapter unlocks a specific user cohort.

### Arc C — Plumbing

**Headline**: Plugin system for custom diff / redaction, Docker
image, LAN-sharing, public demo site.

Arc C is **demand-driven**, not research-driven. It becomes relevant
when a real external user reports a concrete need. As of R56 there
are zero external users, so this arc is lowest priority.

## Decision (deferred)

R56 does **not** pick an arc. The R56 contribution is:

1. **Phase 3 is officially closed**: roadmap.md marks it ✅ COMPLETE.
2. **Phase 4 charter skeleton**: roadmap.md §"Phase 4 — Depth &
   ecosystem" lists the candidate items under priority buckets
   (4.1 Depth / 4.2 Ecosystem / 4.3 Plumbing).
3. **This ADR-023**: captures the "three arcs" framing so the
   decision about where R57+ starts has a coherent foundation.

The Phase 4 kickoff decision is deferred to R57. The expected
R57 output is an ADR-024 (or a replacement ADR-023-v2 when this
skeleton gets finalised) that picks **one** of Arc A / B / C as
the R57-R6x thread.

## Why skeleton-now instead of decide-now

Two reasons:

1. **R56 is a post-release polish round**, not a strategy round.
   Its stated P0 (per CONTEXT §6) is README + guide updates for
   v0.4.0 — charter drafting is P1, and P1 should not pre-empt
   a deliberative Phase 4 commit.
2. **Drift risk is real**: roadmap.md §"Phase 4" before R56 listed
   "CrewAI adapter" as a Phase 4 candidate, which was stale (CrewAI
   shipped in v0.4.0 as part of Phase 3 closure). A skeleton ADR
   that explicitly defers the decision is better than a premature
   commitment that goes stale by R58.

## Follow-ups (R57+)

- [ ] Arc A scoping: write the "compare N runs" UI sketch as a
      design-doc before any code. Needs to live at
      `docs/design/n-run-compare.md` or similar.
- [ ] Arc B scoping: finalise the adapter #4 evaluation table
      (move from this ADR into `docs/research/adapter-4-survey.md`).
- [ ] Arc C: defer until an external demand signal arrives.
- [ ] Promote this ADR from Draft → Accepted (or replace with
      ADR-024) when R57 picks an arc.

---

*Authored R56, single round, no code changes. This ADR is intentionally
soft — it is a framing tool, not a commitment. The binding decision
belongs to R57.*
