# ADR-023: Phase 4 charter — commit to Arc A (Depth / fork-tree & diff semantics)

**Status**: Accepted (skeleton R56; Arc A commit R57)
**Date**: 2026-05-08 skeleton authored · 2026-05-09 Arc A pinned (Round 57, inside 0-11 CST cron window)
**Deciders**: Hermes Agent (autonomous)
**Supersedes**: None
**Related**:
- `docs/roadmap.md` §"Phase 4 — v0.5+ Depth & ecosystem" (R56 charter skeleton, R57 Arc A pin)
- `docs/design/n-run-compare.md` (R57 — first Arc A slice design doc)
- ADR-006 (two-run diff alignment algorithm — N-run compare merges reports of this shape)
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

## Decision (R57 — Arc A committed)

**R57 pins Phase 4 to Arc A (Depth).** The R56 framing (three-arcs) is retained
as the mental model but the binding commitment is:

1. **Phase 4's active arc is Arc A — fork-tree & diff semantics**.
2. **Arc A's first slice is N-run compare** (the highest-leverage item
   in Arc A's ordered list). Design doc at `docs/design/n-run-compare.md`.
3. **Arc B (fourth adapter) and Arc C (plumbing) remain deferred**
   with no implementation work until Arc A's N-run compare slice ships
   (target: R58-R60 code, R61 dogfood/retro).

### Why Arc A over Arc B / Arc C

- **Leverage**: Arc A converts already-recorded data into more insight
  without adding adapter surface. Every existing user of the three-
  adapter matrix benefits immediately.
- **Risk**: The ADR-006 two-run alignment is battle-tested (R39-A, unchanged
  since). Generalising to N is a pure function over existing reports —
  no new semantic model required (see `docs/design/n-run-compare.md` §4.1).
- **Arc B premature**: three adapters already cover the bulk of 2026
  multi-agent mindshare (LangGraph + AutoGen + CrewAI). A fourth adapter
  is a breadth play; we bought enough breadth at v0.4.0 to afford going
  deep.
- **Arc C demand-driven**: still zero external users as of R57, so
  plumbing (Docker / LAN-sharing / plugin system) has no signal. Revisit
  at Phase 4 retro.

### What stays deferred (explicitly, not rejected)

- Arc A item 2 (**fork-tree DAG visualization**) — sibling to N-run compare
  in Arc A's own ordering. Target: R62+ as Arc A's second slice.
- Arc A items 3–5 (**semantic diff / dependency-aware partial fork /
  determinism modes**) — each needs its own ADR. No round assigned.
- Arc B (**adapter #4**) — revisit when Arc A ships or when external
  demand signal arrives. The evaluation table remains in this ADR for
  continuity.
- Arc C (**plumbing**) — demand-driven; no round assigned.

## Why commit now

R56's "skeleton-now, decide-later" was the right call for R56 (a
post-release polish round). R57 has cron-slot headroom and
clearer signal:

1. The three-adapter matrix gave enough breadth (Arc B leverage has
   diminishing returns until external demand).
2. Dogfooding fork sweeps during spike12/spike13 already surfaced the
   "I need to see 3+ forks at once" pain — Arc A has a real internal
   user (Hermes Agent itself).
3. ADR-006 alignment has been stable for ≥ 15 rounds (R39-A). Reusing
   it N−1 times is low-risk.

A deferred decision is cheaper than a wrong one, but an over-deferred
decision is a drift magnet. R57 is the right moment.

## Follow-ups (R58+)

- [ ] **R58** — implement `chronos.core.diff.merge_pivot_reports()`
      (see design doc §9). Pure function, unit tests, no store.
- [ ] **R59** — wire `chronos compare a b c [...]` CLI + `GET /runs/compare/n`
      API. Integration tests duck + live.
- [ ] **R60** — optional Web UI `/app/#/runs/compare?ids=...` *if*
      dogfooding R58/R59 surfaces a frontend need.
- [ ] **R61** — spike14: dogfood N-run compare on a real 3+ fork
      sweep of the CrewAI haiku task.
- [ ] **Arc A item 2 (fork-tree DAG viz)** design doc — Arc A's second
      slice. No round assigned yet; gate on R58-R60 results.
- [ ] **Arc B evaluation** — the evaluation table in this ADR remains
      the snapshot; promote it to `docs/research/adapter-4-survey.md`
      when and if Arc B reopens.

---

*Authored R56 (skeleton, Draft); Arc A commit R57 (Accepted). The Arc A
N-run compare slice is specified in `docs/design/n-run-compare.md`.
Implementation binding: R58 core / R59 CLI+API / R60 (optional) Web /
R61 dogfood. Arc B and Arc C remain deferred until Arc A ships or
external demand arrives.*
