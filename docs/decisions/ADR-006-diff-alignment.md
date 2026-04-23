# ADR-006: Diff Alignment Algorithm

- **Status**: Accepted
- **Date**: 2026-04-23 (Round 7)
- **Supersedes / Related**: ADR-003 (node.node_name as semantic key), ADR-005 (fork step_index restarts)

---

## Context

Milestone M1.8 introduces `chronos diff <run_a> <run_b>`: a structural
diff between two recorded `Run`s. The command must tell the user which
nodes are common, which differ, and which were added/removed — so the
value of a `fork` is visible without eyeballing two `runs show` trees.

The heart of a structural diff is **alignment**: pairing up nodes
across the two runs before comparing them. Alignment decides what we
mean by "the same node": wrong choice and every subsequent comparison
is garbage. Every later diff consumer — rich table output, `--json`
mode, the future Web UI diff viewer, an eventual semantic-diff layer
— will inherit the alignment decision made here.

This ADR exists because the obvious candidate (step_index alignment)
is demonstrably wrong.

---

## Candidates Considered

### A. step_index alignment

> Pair `parent.nodes[i]` with `child.nodes[i]`.

Fails by construction on fork children. ADR-005 established that a
forked Run's nodes keep the parent's step_index on their first
downstream node (e.g. fork at parent step 1 → child's first node has
step_index 2, not 0). Two independent consequences both kill this
approach:

1. A child-of-fork has **no prefix nodes** (steps 0..fork_point-1 live
   only on the parent). Index-by-index pairing would align parent[0]
   (`ingest`) with child[0] (`draft`) — clearly nonsense.
2. Even for two independent top-level runs that happen to share a
   structure, a single insert or re-order in one run cascades into
   spurious "CHANGED" markers for every subsequent node.

Already ruled out by Round 5/6 findings.

### B. node_name + step_index tiebreak alignment (**chosen**)

> Use `node_name` as the semantic key. When the same node_name occurs
> multiple times in one run (loops), pair repeats by order of
> occurrence. Implement via `difflib.SequenceMatcher` over the
> sequence of node_names.

ADR-003 §semantic keys already declared `node_name` as the stable
cross-run identifier (unlike `id` and `step_index` which are
per-execution). This ADR binds the diff layer to that contract.

### C. Myers / custom LCS

> Write a bespoke sequence-alignment algorithm (Myers' O(ND) or an
> affine-gap aligner).

Richer opcode output, but stdlib `difflib` is already a good Ratcliff-
Obershelp implementation, and spike 7 showed its output is **identical
to what a Myers aligner would produce** on every canonical Chronos
case. No reason to carry bespoke code.

### D. Hash-based alignment (state_after content-addressed)

> Pair nodes whose `state_after` hashes match.

Defeats the whole point of diff — we want to *discover* where states
changed, not require them to be identical first. Save for a future
"identical branches auto-collapse" optimisation on the Web UI side.

---

## Spike 7 — Empirical Evidence

`tests/spikes/spike7_diff_alignment.py` ran five canonical cases
using `difflib.SequenceMatcher(a=names_parent, b=names_child).get_opcodes()`
and manually verified the opcode stream against the expected diff
summary:

| Case | Shape | Expected | Actual |
|---|---|---|---|
| 1. Parent vs child-of-fork (common tail) | 5-node parent, child re-runs 4 nodes after fork | ingest REMOVED; research/draft/polish/end CHANGED | ✅ |
| 2. Fork child with early exit | Overrides cause child to skip a node and finish early | ingest/research/polish REMOVED; draft CHANGED; end CHANGED | ✅ |
| 3. Cycles with repeated node_names | Loop ran one more iteration in run B | 3 EQUAL at start, repeats paired in order, extra `router/worker` as ADDED | ✅ |
| 4. Identical runs | Sanity | all EQUAL | ✅ |
| 5. Structural mismatch | Two runs with different prefixes, same suffix | prefix REMOVED; shared suffix CHANGED | ✅ |

Case 3 is the load-bearing one: SequenceMatcher naturally pairs
loop-repeated node_names by order of occurrence because it works on
sequences, not sets. No bespoke loop handling needed.

---

## Decision

1. **Alignment key**: the ordered sequence `[n.node_name for n in run.nodes]`
   (ordered by `step_index` ascending — already the store's return order).
2. **Algorithm**: `difflib.SequenceMatcher(a=names_a, b=names_b, autojunk=False)`.
3. **Opcode → diff-category mapping**:
   - `equal` → emit one pair per matched position. If the paired nodes'
     `state_after` payloads are equal, tag as **`equal`**; otherwise
     tag as **`changed`** (same name, same position in the alignment,
     but the post-state differs — e.g. fork override took effect).
   - `replace` → emit `removed` for each parent node in `a[i1:i2]`
     and `added` for each child node in `b[j1:j2]`. We deliberately
     do **not** try to pair replace-block members heuristically (e.g.
     "same kind" or "same tool_name") because every heuristic is one
     ambiguous fork edit away from being wrong. A downstream Web UI
     pass can re-pair if it wants.
   - `delete` → `removed` for every node in `a[i1:i2]`.
   - `insert` → `added` for every node in `b[j1:j2]`.
4. **state_after comparison** (inside `equal` → `changed` split):
   dict deep-equality on `state_after`. Strings are *not* normalised;
   JSON-encode-and-compare is rejected because `state_after` is already
   JSON-roundtripped by the store. A future semantic diff layer
   (Phase 3) may relax this to LLM-as-judge.
5. **Fork-aware shortcut** (`chronos diff <parent> <child_of_fork>`):
   when B is the child of a fork of A, use `get_fork_for_child(B)` to
   find the fork point, then slice A's nodes to the downstream only
   (`step_index >= fork.parent_node.step_index`). Everything upstream
   is definitionally identical and displaying it is noise. Gated on
   the fork record existing — if the two runs aren't in a parent-child
   relationship we fall through to the full alignment.
6. **JSON schema** (the shape consumers will depend on):
   ```json
   {
     "run_a": {"id": "...", "node_count": 5},
     "run_b": {"id": "...", "node_count": 4},
     "fork_of": {"id": "...", "parent_node_id": "...", "parent_node_name": "research"},
     "entries": [
       {
         "tag": "equal" | "changed" | "added" | "removed",
         "node_name": "draft",
         "a": {"id": "...", "step_index": 2, "state_after": {...}} | null,
         "b": {"id": "...", "step_index": 2, "state_after": {...}} | null,
         "state_diff": {
           "added_keys": ["reviewer_hint"],
           "removed_keys": [],
           "changed_keys": {"draft": {"a": "...", "b": "..."}}
         } | null
       }
     ],
     "summary": {"equal": 1, "changed": 3, "added": 0, "removed": 1}
   }
   ```

---

## Consequences

### Positive
- Zero new dependencies — stdlib only.
- `node_name` is already the store-invariant semantic key (ADR-003),
  so this decision reinforces existing contracts rather than
  introducing new ones.
- Symmetric by construction: `diff(A, B)` produces the transpose of
  `diff(B, A)`. No "base" vs "head" asymmetry bias.
- JSON schema frozen early. Web UI diff viewer, IDE extensions, and
  the eventual `chronos export` command can all target the same
  shape without waiting for a v2.

### Negative / accepted risks
- `node_name` collisions in loops rely on **order of occurrence**
  pairing; if a loop iteration is inserted *in the middle* of a run,
  alignment will pair iteration 3 of A with iteration 2 of B (marking
  the wrong iteration as inserted). Acceptable because (a) LangGraph
  loops are deterministic modulo state, so mid-loop insertion is rare
  in practice, and (b) the wrong-iteration-paired case still produces
  a correct summary of inserted/changed nodes, just with slightly
  confusing individual pairs. Revisit if users hit this in real graphs.
- `replace` regions don't attempt to pair nodes across the split. If
  a user renames one node, we show REMOVED `old_name` + ADDED
  `new_name` rather than a single "RENAMED" marker. Acceptable for
  v0.1; a rename-detection pass is a Phase 3 semantic-diff concern.
- `state_after` deep-equality treats structurally-different-but-
  semantically-equal payloads (e.g. `[1, 2]` vs `[2, 1]` for a set)
  as CHANGED. Correct default; users can opt into looser comparisons
  in a later release.

### Neutral
- `replace` opcodes from SequenceMatcher are linearised into
  remove+add pairs. This preserves the alignment's ordering but means
  the `entries` list does not 1-to-1 mirror the opcode stream. Fine.

---

## Compliance Test

The spike codifies the acceptance bar. The implementation in
`chronos.core.diff` MUST reproduce the same `summary` dict for each
of spike 7's five cases. The unit test suite for M1.8 is built on
fixtures that mirror cases 1–5 plus the fork-aware shortcut (case 6).

If a future change breaks any of these six cases, this ADR is
invalidated and must be superseded.

---

*Author: Hermes Agent (Round 7). Empirical basis:*
*`tests/spikes/spike7_diff_alignment.py` — all 5 cases pass as of*
*this commit.*
