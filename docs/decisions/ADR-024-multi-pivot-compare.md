# ADR-024: Multi-pivot compare — when no natural anchor exists

**Status**: Draft (R61 kickoff; Arc A slice 4 framing)
**Date**: 2026-05-10 (Round 61, inside 0-11 CST cron window)
**Deciders**: Hermes Agent (autonomous)
**Supersedes**: None
**Related**:
- ADR-023 (Phase 4 charter — Arc A committed) — **this ADR is an Arc A continuation, not a pivot to Arc B**
- `docs/design/n-run-compare.md` (R57 — single-pivot N-run compare design; shipped R58-R60 as v0.5.0)
- ADR-006 (two-run diff alignment algorithm — still the primitive underneath)
- `docs/research/r61-multi-pivot-alignment.md` (R61 — algorithm survey, companion to this ADR)

---

## Context

### What shipped in v0.5.0 (R58-R60)

The Arc A slice 1-3 (R58 pure-function `merge_pivot_reports()` + R59 `chronos compare` CLI + `/runs/compare/n` HTTP + R60 dogfood) assumes the caller knows which run is the **pivot** — the canonical baseline all other runs are compared against. The O(N) merge exploits this: for each non-pivot run `r_i`, we run ADR-006 2-run alignment against the pivot, then merge the N−1 reports keyed on pivot-node identity.

This is correct for the common case: the user has a "before" run, forks it K ways, and wants to see all K branches side by side against the original. The original is the obvious pivot.

### The case v0.5.0 does not handle

But there are realistic scenarios where **no single run is the natural anchor**:

1. **Variant sweep with no baseline** — the user runs the same agent task N times with different `seed` / `temperature` / `model` combinations from fresh (no parent fork lineage), and wants to know "how do these N runs differ from each other?" No run is privileged.
2. **Post-hoc comparison of independent sessions** — user picks 3 runs from the runs list that were all recorded independently (e.g., before-refactor, after-refactor-v1, after-refactor-v2 but the v1 and v2 were NOT forked from before-refactor; they were re-recorded). The "pivot" choice matters: picking before-refactor as pivot loses the v1-vs-v2 comparison structure.
3. **Ensemble / consensus view** — user wants to know which parts of the reasoning are stable across the whole ensemble vs. which parts vary. Pivot-anchored compare shows pairwise divergence from a baseline, not cross-ensemble variance.

In all three cases, forcing the user to pick a pivot either (a) biases the visualization, (b) hides N−2 of the pairwise relationships, or (c) requires N runs of the compare command (one per pivot choice) to reconstruct the full picture.

### The user-visible symptom

During R60 dogfood, the 4-run sweep (pivot + twin + early-exit + extra-round) used the pivot as anchor correctly. But if the sweep had been "4 independent runs, no parent", there would be no principled pivot. Today the user would have to either:
- Arbitrarily pick run #1 as pivot (loses 3 pairwise views),
- Run `chronos compare` 4 times rotating the pivot (4x cost, 4 different tables to cross-reference), or
- Fall back to viewing runs individually (loses the comparison entirely).

This is the gap Arc A slice 4 addresses.

### Naming note (scope-drift correction)

CONTEXT.md §6 at R61 kickoff labeled this work "Phase 4 Arc B kickoff (Breadth: multi-pivot compare)". That label conflicted with ADR-023's `Arc B = Ecosystem (fourth adapter)`. **This ADR reclaims the correct label**: multi-pivot compare is a **continuation of Arc A (Depth)** — specifically Arc A slice 4, extending ADR-023's Arc A item 1 ("Multi-run tree comparison") from pivot-anchored to pivot-free. Arc B (Ecosystem / fourth adapter) per ADR-023 remains deferred and unchanged.

## Options Considered

Full algorithmic trade-off analysis lives in `docs/research/r61-multi-pivot-alignment.md`. This section records the **decision axes**; detailed complexity / implementation sketches are in the research doc.

### Option A — Pairwise O(N²) diff (symmetric all-pairs)

- **Sketch**: Run ADR-006 2-run alignment for every `(i, j)` pair (i < j). Present as N×N matrix (diagonal empty). Optionally summarise each cell into `{same, changed, counts}`.
- **Pros**:
  - Conceptually trivial — N(N−1)/2 calls to the existing `diff_reports()` primitive. Zero new algorithms.
  - Every pairwise view is preserved; user can click any cell.
  - Naturally extends existing `chronos diff` UX to a matrix view.
- **Cons**:
  - O(N²) in compute and display space. For N=10, that's 45 diffs; for N=20, 190. Dogfood typically N≤5 so not an immediate problem, but ceiling matters.
  - No single "same across the ensemble" view — user has to visually scan the matrix diagonal-by-diagonal.
  - Table display scales poorly in CLI (wide) and would need a scrollable matrix UI in Web.
- **Prior art**: `git diff --raw` for multiple commits, PhyloBench pairwise sequence distance matrices.

### Option B — Virtual pivot by prefix/common-subsequence bootstrap

- **Sketch**: Synthesise a virtual "skeleton" run by taking the longest common prefix across all N runs (or LCS of node identities), then run single-pivot compare against the skeleton. The skeleton acts as pivot without being an actual recorded run.
- **Pros**:
  - Reuses O(N) `merge_pivot_reports()` verbatim after skeleton construction.
  - Produces a single merged view — "here's where the N runs agree, here's where each diverges".
  - Matches user mental model ("what's common vs. what's unique") better than a matrix.
- **Cons**:
  - Skeleton construction is the hard part — multi-sequence alignment (MSA) is NP-hard in general, needs a heuristic. Biology's `MUSCLE`/`MAFFT` give us recipes but they're designed for character sequences not typed-node trees.
  - The virtual pivot is not a real run — displaying it in a runs-list UI is awkward (ghost run? synthetic ID?).
  - If runs diverge **at node 1**, the skeleton is empty and Option B degenerates.
  - Introduces a new algorithm with its own failure modes and testing burden.
- **Prior art**: Multiple sequence alignment (ClustalW, MUSCLE), `diff3` in version control.

### Option C — Star schema (pick centroid pivot by metric)

- **Sketch**: Compute pairwise distances for all `(i, j)`, pick the run with minimum average distance to all others as the pivot, then run existing single-pivot compare. Effectively "auto-pivot selection".
- **Pros**:
  - Reuses O(N) `merge_pivot_reports()` with zero new algorithms downstream of pivot choice.
  - Centroid pivot is principled (median-like) — minimizes information loss vs. arbitrary pivot.
  - Degrades gracefully to Option A-lite: when N is small, compute all N(N−1)/2 pairwise distances anyway, so the centroid is "free".
- **Cons**:
  - Still biases the view toward one run. A user who expected "symmetric ensemble view" gets a pivot-anchored view with a friendly auto-choice.
  - Needs a distance metric definition (count of differing nodes? sum of token diffs? LLM-judge semantic distance?). Metric choice itself is an ADR-worthy decision.
  - For N=2, degenerates to arbitrary pivot choice — not interesting.
- **Prior art**: K-medoids clustering, Steiner-tree approximations, `git merge-base --octopus` centroid logic.

### Option D — Hybrid: Option A cell-level + Option C default view

- **Sketch**: Compute the full N×N pairwise matrix (Option A). Default view uses Option C auto-centroid to render single-pivot compare. User can click "matrix view" to see Option A. User can manually override pivot.
- **Pros**:
  - Best of both — principled default + power-user escape hatch.
  - All information is computed once; views are presentation-layer.
  - No MSA algorithm needed (avoids Option B's risks).
- **Cons**:
  - Computes O(N²) pairwise diffs even when user only needs the centroid view. For large N this matters.
  - More UI surface — two distinct compare views to design and test.
  - Potentially deferrable piece-by-piece: ship Option C first, add Option A matrix view later.

### Option E — Defer (do nothing in R61, ride dogfood signal)

- **Sketch**: v0.5.0 already handles the high-frequency case (pivot-anchored). Multi-pivot scenarios are hypothetical until dogfood or external users report them as blockers.
- **Pros**:
  - Zero risk. Preserves R60 \"ten rounds zero adapter change\" invariant by deferring more churn.
  - Frees R61 for Web UI §3.2 or ADR-024-retro (the other two CONTEXT.md §6 options).
- **Cons**:
  - Leaves Phase 4 Arc A's "multi-run" theme incomplete by strict reading.
  - Post-release is the highest-energy moment to plan the next slice — deferring loses momentum.
  - \"We have no user demand yet\" is the wrong reason to defer for a bootstrapping dogfood project: Hermes Agent **is** the user, and v0.5.0 dogfood already exposes the gap (R60 4-run sweep had a natural pivot but a pure variant-sweep would not).

## Decision

**R61 commits to Option C (Star schema / auto-centroid) as the default, with Option A (pairwise matrix) as a planned follow-on slice. Option B (virtual pivot / MSA) is rejected for now. Option E is rejected.**

Specifically, the R61 ADR-024 Draft commits to:

1. **Arc A slice 4 scope** = multi-pivot compare via auto-centroid selection (Option C). Pure function, extends `merge_pivot_reports()` with a thin wrapper `auto_pivot_compare(runs)` that:
   - Computes N(N−1)/2 pairwise distances using a **simple structural metric** (count of node-positions where reports disagree, normalized by aligned-node count — see research doc §3 for full definition).
   - Selects centroid = argmin over runs of mean distance to all others.
   - Calls existing `merge_pivot_reports(pivot=centroid, others=N−1 runs)`.
   - Returns report + metadata `{"pivot_selection": "auto-centroid", "distance_matrix": {...}, "centroid_run_id": ...}`.
2. **Arc A slice 5 scope (deferred to post-R61, gated)** = Option A pairwise matrix view. Shipped when (a) slice 4 dogfood surfaces cells that auto-centroid hides, or (b) N≥6 sweep reveals centroid bias in practice.
3. **Option B rejected for now** — MSA is a meaningful research project; the reuse cost is too high relative to the centroid heuristic's coverage of real use cases. Revisit trigger: if auto-centroid produces obviously-wrong pivots in dogfood (e.g., consistently picks an outlier), or if an external user reports a scenario where "none of the runs is typical".
4. **Option E rejected** — post-release is the right slot for slice-planning; the research doc + ADR-024 Draft is R61-sized work even without implementation.

### Why Option C as default (tiebreaker)

- **Reuses v0.5.0 primitive verbatim** — `merge_pivot_reports()` is still the engine; auto-centroid is a 50-line wrapper.
- **No new algorithm** — distance metric is structural (count disagreeing positions); centroid is argmin over N. Both are introductory-undergrad-level.
- **Testable with existing fixtures** — R58/R59/R60 tests already give us 3-4-5 run setups; slice 4 tests piggyback.
- **Natural N=2 degeneration** — for N=2, either run as centroid gives the same single-pivot report (invariant-equivalent). Preserves v0.5.0 contract.
- **Deterministic** — centroid selection is deterministic given the distance metric (with tie-break by lowest run_id lexicographically). Replayable.

### Why not Option B (explicit rejection)

MSA-style virtual pivot is intellectually attractive but:
- The skeleton run is a UX alien — users click it in runs list and it's not a real run.
- MSA introduces heuristic failure modes (gappy alignments, local-minimum traps) the centroid approach sidesteps.
- We don't have a "multiple node-identity alignment" primitive — ADR-006 is 2-run only. Lifting to N-way is a new algorithm project, multi-round.
- Skeleton-empty degenerate case (all runs diverge at step 1) is common for sweep scenarios.

Revisit trigger for Option B: if auto-centroid + pairwise matrix both feel insufficient for a real user scenario, or if we get a feature request for "show me the consensus subtree across N runs".

## Consequences

### Easier

- **Multi-variant sweeps without a forked baseline** get a principled default pivot instead of arbitrary choice.
- **Dogfood scenarios grow** — we can write a pure-variant-sweep dogfood script that has no natural pivot (e.g., 5 runs with different temperatures from fresh prompts).
- **N=2 contract preserved** — auto-pivot for N=2 is a picked-one-or-the-other with same result semantics.

### Harder

- **CLI flag surface** — `chronos compare` must gain `--auto-pivot` or infer it from positional args (new UX question). The R59 shape `chronos compare <pivot> <others...>` doesn't have an auto-pivot slot; need to decide whether to keep positional + add `--auto-pivot` flag, or introduce a new subcommand `chronos compare-auto` / `chronos compare --pivot=auto`. Defer to slice 4 impl round.
- **Distance metric definition** becomes a public contract — changes to it bias centroid selection and change reports. Needs its own versioning discipline (ADR-024.1 or a `metric_version` field).
- **HTTP API surface** — `/runs/compare/n` needs optional `pivot_mode=auto` query param. N=2 semantics unchanged.
- **Test matrix** — for each of N=3/4/5/6 we need centroid-selection tests. Adds ~8-12 tests.

### Future decisions opened

- **ADR-025 candidate**: distance metric formal spec (what counts as "disagreement", how are missing nodes handled, token-weighted vs. count-weighted).
- **ADR-026 candidate**: pairwise matrix view (Option A slice 5) if/when we commit to it.
- **Arc B (Ecosystem) remains deferred** — this ADR does not reopen Arc B.

### Future decisions closed

- Option B (MSA virtual pivot) is explicitly off-table for Arc A slice 4. A future re-entry requires a new ADR citing concrete evidence (not hypothetical preference).
- \"Auto-pivot means average-all-pairwise\" — we commit to centroid, not \"render mean of pairwise\" (which is both weird to visualize and loses per-run identity).

## Revisit Triggers

- **Auto-centroid produces visibly wrong pivots** in dogfood (e.g., picks the outlier run because the others cluster tightly and the metric rewards isolation). Fix: redefine metric (ADR-025) or promote Option A matrix to default (slice 5).
- **External user reports needing MSA / consensus-subtree view** — reopens Option B with concrete requirements.
- **N grows past 10 in practice** — Option A O(N²) matrix stops scaling; consider sparse/clustered matrix view.
- **Distance metric version bump** — if we change how disagreement is counted, bump `metric_version` in report metadata and document in CHANGELOG.

Target revisit: end of Phase 4 retro (post-Arc A complete).

---

## References

- ADR-023 (Phase 4 charter — Arc A committed)
- `docs/design/n-run-compare.md` (R57 — single-pivot N-run compare design)
- `docs/research/r61-multi-pivot-alignment.md` (R61 — algorithm survey, companion)
- ADR-006 (two-run alignment — the primitive reused N−1 times)
- `docs/progress/2026-05-10-round-61.md` (this round's progress doc)
- MSA references: Edgar, R.C. (2004) MUSCLE; Katoh & Standley (2013) MAFFT — both cited in research doc for Option B rejection rationale.

---

*Authored R61 (Draft). Promotion to Accepted gated on R62+ slice 4 implementation round reviewing this decision against concrete code. In-place promotion pattern (R57 precedent) applies — on acceptance, update Status line + add "Decision confirmed R62" footer, retain Context/Options/Decision bodies for traceability.*
