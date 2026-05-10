# Research Note — Multi-pivot Alignment Algorithms for N-run Agent Traces

**Round**: R61 (Phase 4 Arc A slice 4 planning)
**Date**: 2026-05-10 (CST, inside 0-11 window)
**Author**: Hermes Agent
**Companion to**: [ADR-024 — Multi-pivot compare](../decisions/ADR-024-multi-pivot-compare.md)
**Status**: Survey (informs ADR-024 Draft; updated when slice 4 implementation lands or new evidence emerges)

---

## 1. Problem Statement

Given N≥2 recorded agent runs with no designated pivot (baseline), produce a compare report that is principled, deterministic, reuses existing primitives where possible, and preserves the v0.5.0 single-pivot contract as a strict N=2 special case.

"Alignment" here means the structural mapping from nodes of one run to nodes of another, following ADR-006's 2-run primitive. The 2-run primitive is our bedrock; everything else in this note is about how to combine its output across multiple pairs.

### Scope

- **In**: Selecting/constructing an anchor for N-way compare, once runs are fixed.
- **Out**: The 2-run alignment algorithm itself (ADR-006, unchanged), semantic equivalence judgments (future ADR-025 territory), token-cost-weighted distance metrics (deferred).

## 2. Primitive recap

ADR-006 `diff_reports(run_a, run_b) → DiffReport` gives us, for a pair of runs:
- **Aligned pairs** — node `a_i` is "same as" node `b_j` under the alignment.
- **Unmatched nodes on each side** — nodes with no counterpart.
- **Per-position verdicts** — `equal | changed | absent_a | absent_b`.

ADR-006 alignment is deterministic, O(|a|·|b|) worst case, and stable under prefix extension (appending a node doesn't re-align earlier ones). These properties carry over to anything built on top.

The R58-R60 shipped primitive `merge_pivot_reports(pivot, [r1, r2, ..., r_{N-1}]) → MergeReport` is a **pivot-anchored** N-way compare: it runs `diff_reports(pivot, r_i)` N−1 times and stitches the reports keyed on pivot-node identity. All non-pivot views hang off the pivot's spine.

## 3. Candidate algorithms

### 3.1 Pairwise O(N²) matrix (ADR-024 Option A)

**Construction**: For all `i < j`, compute `diff_reports(r_i, r_j)`. Present as N×N matrix of DiffReports (symmetric, so actually N(N−1)/2 unique cells).

**Complexity**: O(N²) diffs, each O(|r_i|·|r_j|). If node count is bounded by L, total O(N²·L²).

**Memory**: N(N−1)/2 reports. Each report is O(L) unique content + O(L) metadata. Total O(N²·L).

**Deterministic**: Yes (ADR-006 is deterministic; matrix ordering is `(i, j)` with `i < j`).

**Failure modes**:
- Large N: 10 runs = 45 cells, 20 runs = 190. Display scales poorly.
- No single "ensemble view" — user has to synthesise.
- Symmetric cells are redundant (`(i,j)` = transpose of `(j,i)`), halved by `i < j` convention.

**Verdict**: Intellectually clean; no new algorithm. Chosen as planned **slice 5** (deferred) in ADR-024. Will ship if auto-centroid proves insufficient.

### 3.2 Virtual pivot via LCS / multi-sequence alignment (ADR-024 Option B — REJECTED)

**Construction sketch**: Find a "skeleton run" representing the consensus of all N runs, then run single-pivot compare against the skeleton.

Two sub-variants:
- **3.2a LCS of node identities**: Compute longest common subsequence over the sequence of `(node.kind, node.name)` tuples across all N runs. Skeleton = LCS. Then align each `r_i` against skeleton using ADR-006-style alignment.
- **3.2b Progressive MSA (MUSCLE/MAFFT-style)**: Build a guide tree from pairwise distances, progressively align runs into a skeleton. Classical bioinformatics approach.

**Complexity**:
- LCS of K sequences is O(L^K) in naive DP; approximations exist (ALINEA, star-LCS) at O(K·L²).
- Progressive MSA: O(N²·L²) for pairwise distances + O(N·L²) for progressive align + guide tree construction. Total O(N²·L²). Heuristic — not optimal.

**Memory**: Skeleton is O(L_skeleton) + N alignments O(N·L) = O(N·L).

**Deterministic**: Only with a tie-break discipline. MSA heuristics have multiple local optima; seed + guide-tree construction order matters.

**Failure modes**:
- **Empty skeleton** when runs diverge at step 1: LCS could be empty → degrades to "no view at all". For variant sweeps (common case), this happens regularly.
- **Ghost run UX** — skeleton is not a recorded run. Runs list must show it as synthetic; users get confused when they click through to "see" it.
- **Gappy alignments** — MSA produces alignments with many `-` gaps; interpreting "gap means different" vs. "gap means missing" is fuzzy.
- **New algorithm to test / debug** — we'd be writing our own MSA, or vendoring a biology library (weird dependency profile).

**Verdict**: Rejected in ADR-024. The ghost-run UX, empty-skeleton degenerate case, and new-algorithm cost outweigh the theoretical appeal. Revisit if a concrete user scenario demands a "consensus subtree" view that centroid pivot can't produce.

Prior art worth reading if we ever reopen:
- Edgar, R.C. (2004). *MUSCLE: multiple sequence alignment with high accuracy and high throughput*. NAR 32(5):1792-1797. Progressive MSA baseline; fast.
- Katoh, K. & Standley, D.M. (2013). *MAFFT multiple sequence alignment software version 7*. MBE 30(4):772-780. Better accuracy; slower.
- `diff3` (GNU diffutils): 3-way merge with ancestor. Not MSA but has the "consensus-via-common-ancestor" flavour.

### 3.3 Star schema / centroid pivot (ADR-024 Option C — CHOSEN)

**Construction**:
1. Compute pairwise distance `d(i, j)` for all `i < j` — this is the same O(N²) work as matrix view, but we only need a scalar per pair, not the full report.
2. For each run `i`, mean distance to others: `m_i = (Σ_{j ≠ i} d(i, j)) / (N − 1)`.
3. Centroid = `argmin_i m_i`. Tie-break by lexicographic run_id.
4. Call `merge_pivot_reports(pivot=centroid, others=remaining N−1 runs)`.
5. Return `{report: ..., metadata: {pivot_selection: "auto-centroid", centroid_run_id, distance_matrix, metric_version}}`.

**Distance metric (initial definition, `metric_version = 1`)**:

```
d(r_a, r_b) := |disagreeing_positions| / max(1, |aligned_positions|)

where:
  - aligned_positions = positions in ADR-006 diff(r_a, r_b) with verdict ∈ {equal, changed}
  - disagreeing_positions = positions with verdict = changed, plus all absent_a / absent_b
  - normalization: denominator is |aligned|+|unmatched|, i.e., total positions touched
```

Alternative definitions considered (all deferred to possible ADR-025):
- Token-weighted — sum token deltas instead of counts. Richer but requires token tallies per node.
- Kind-bucketed — weight `llm` mismatches more than `fn` mismatches. Captures "important divergence" but introduces tuning knobs.
- Semantic — LLM-as-judge distance. Arc A item 3 (deferred per ADR-023).

We start with the **counting metric** because it's (a) cheap, (b) obvious, (c) version-tagged for future refinement, (d) equals 0 for identical runs and 1 for totally disjoint runs (clean interval).

**Complexity**: O(N²) diffs (same as matrix) + O(N) argmin + O(N−1) merge. Dominant term O(N²·L²) — same asymptote as matrix but **smaller constant** when the pairwise matrix is computed only for distances (no report-stitching overhead per cell).

Optimisation note: if downstream only uses centroid report, the full DiffReport objects for non-centroid pairs are wasted. Keep them in the in-memory cache (let the caller request matrix view for free later — slice 5 hook).

**Memory**: O(N²) distances (scalars) + 1 centroid MergeReport O(N·L).

**Deterministic**: Yes, given metric + tie-break rule.

**Failure modes**:
- **Outlier-picked-as-centroid** when 3 runs cluster and 1 is distant: centroid is the distant one (closest to "average"). Actually this is fine — the "average" position minimizes total distance, which in a {3-tight + 1-far} case is inside the tight cluster. Wait, let me re-examine: mean distance from far outlier is high; mean distance from any of the 3 tight ones is (2 tight-pair-distances + 1 far-distance)/3. The tight ones will have lower mean. So centroid is in the cluster. ✓ not a failure mode.

  Real failure mode: when **all runs are equidistant** (e.g., 4 totally different runs with no structure), centroid choice is arbitrary → falls through to run_id tie-break. Downstream user doesn't learn anything, but that's an inherent property of the data, not the algorithm.

- **N=2**: only 1 pairwise distance, both runs have equal mean → tie-break to lexicographic-min run_id. Result: centroid is fixed-choice-by-id, merge report = single-pivot report identical to `merge_pivot_reports(run_min_id, [run_other])`. This is a **contract-compatibility point** and we should test it.

- **Same-run duplicates**: `d(i,j) = 0` for identical runs. Either is equally valid centroid, tie-break by id. Same-run-duplicate testing is worth including (edge case for replay-based fixtures).

**Verdict**: **Chosen as ADR-024 slice 4 default**. 50-line wrapper on `merge_pivot_reports`, one new distance function (~30 LOC with docstring), straightforward tests.

### 3.4 Bespoke N-way DP (alternative, discarded without full analysis)

Extending ADR-006's DP to N dimensions produces O(L^N) cells — exponentially expensive. Only viable for N≤3 or heavily pruned. Classical MSA literature abandoned this 30+ years ago in favour of progressive heuristics (§3.2b). We mention it only to flag that "just generalize the 2-run algo" is not a free lunch.

### 3.5 Graph-based consensus (future exploration, not R61)

A recent line of work (e.g., POA — Partial Order Alignment) represents alignment as a DAG rather than a linear sequence. For agent traces, where forks and parallel tool calls are inherently DAG-shaped, this might be a better primitive than sequential alignment in the long run.

Deferred explicitly — not a candidate for R61 ADR-024. Flagged here for future round to consider if/when Arc A depth goals exceed what ADR-006 linear alignment can express (e.g., when we want to compare fork-trees, not just linear runs).

Reference: Lee, C., Grasso, C., & Sharlow, M.F. (2002). *Multiple sequence alignment using partial order graphs*. Bioinformatics 18(3):452-464.

## 4. Comparative summary

| Criterion                      | Option A matrix | Option B MSA      | Option C centroid  | Option D hybrid |
|--------------------------------|-----------------|-------------------|--------------------|-----------------|
| **Compute**                    | O(N²·L²)        | O(N²·L²) heur.    | O(N²·L²)           | O(N²·L²)        |
| **Display scalability**        | Poor for N>10   | Good              | Excellent          | Good (both views) |
| **Reuses merge primitive**     | No              | Partial           | Yes (full)         | Yes             |
| **New algorithms needed**      | None            | MSA heuristic     | Distance metric only | Distance metric |
| **N=2 degenerate behaviour**   | Same as `diff`  | Same as `diff`    | Same as single-pivot | Same as single-pivot |
| **Empty-consensus failure**    | N/A             | Catastrophic      | None               | None            |
| **Ghost-run UX**               | No              | Yes (problematic) | No                 | No              |
| **Deterministic**              | Yes             | With discipline   | Yes                | Yes             |
| **Test burden**                | Low             | High              | Low                | Medium          |
| **R61 Decision**               | Slice 5 gate    | **Rejected**      | **Slice 4 chosen** | Possible slice 4+5 composite |

## 5. Connection to ADR-024 Decision

The survey supports ADR-024's R61 decision:

- **Option C centroid = slice 4 default** because it's the minimum-viable extension that reuses v0.5.0 primitives, produces a single merged view, handles N=2 cleanly, and is deterministic. The initial counting metric is simple enough to ship without a separate ADR; its version tag (`metric_version = 1`) leaves room for ADR-025 to refine.
- **Option A matrix = slice 5 deferred** because it ships cheaply on top of slice 4 (the distance matrix is already computed) but adds UI/display surface we don't need to own yet.
- **Option B MSA = rejected** because the ghost-run UX and empty-skeleton cases outweigh the theoretical elegance, and we lack evidence of a user scenario demanding consensus-subtree view.
- **Option E defer = rejected** because R61 is a post-release planning slot with no competing urgency, and the ADR + research doc is slot-sized work.

## 6. Open questions for R62+ implementation round

1. **CLI surface**: does `chronos compare` grow a `--pivot=auto` flag, or do we introduce `chronos compare-auto`? R59's positional argv shape (`chronos compare <pivot> <others>`) doesn't have a zero-pivot slot. Lean toward `--pivot=auto` flag + making the first positional arg optional when flag is set.
2. **HTTP surface**: `/runs/compare/n?ids=...&pivot=auto`. Straightforward.
3. **Tie-break ordering**: lexicographic ascending by run_id (string comparison). Write a test where two runs have identical mean distances and assert deterministic pick.
4. **Metric boundary tests**: d(r,r) = 0; d(r1, r2) = d(r2, r1) (symmetry); d ∈ [0, 1]; d(disjoint runs) = 1.
5. **Fixture reuse**: R58's `test_merge_pivot_reports` fixtures should extend to auto-centroid tests. Do NOT piggyback — create a new scenario (R59 lesson).
6. **Dogfood script**: write `scripts/dogfood_compare_auto.py` — 4 independent same-task runs with different seeds, no forking. Natural use case for auto-pivot.
7. **CHANGELOG impact**: R62 slice 4 likely cuts v0.5.1 (post-release polish) or v0.6.0-alpha. Depends on whether HTTP contract changes count as minor or patch.

## 7. References

### Cited
- Edgar (2004) MUSCLE — progressive MSA baseline
- Katoh & Standley (2013) MAFFT — accuracy-tuned MSA
- Lee, Grasso & Sharlow (2002) POA — partial-order alignment, DAG-native
- GNU `diff3` — 3-way merge with common ancestor
- `git merge-base --octopus` — N-way common ancestor selection

### Internal
- [ADR-006](../decisions/ADR-006-diff-alignment.md) — 2-run alignment primitive (primary reuse surface)
- [ADR-023](../decisions/ADR-023-phase-4-charter-skeleton.md) — Phase 4 Arc A commitment
- [ADR-024](../decisions/ADR-024-multi-pivot-compare.md) — this note's companion
- [n-run-compare design doc](../design/n-run-compare.md) — R57 single-pivot design

---

*R61 survey. Will be updated (not rewritten) when R62+ implementation validates or falsifies the Option C choice against real dogfood data.*
