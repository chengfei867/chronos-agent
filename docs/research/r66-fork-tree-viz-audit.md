# R66 — Fork-tree viz audit: what's already shipped, what's missing

**Date**: 2026-05-12 (Round 66, Beijing time ~07:10 CST, inside 0–11 cron window)
**Author**: Hermes Agent (autonomous)
**Companion to**: ADR-025 (drafted this round), `docs/design/fork-tree-viz.md` (drafted this round)
**Trigger**: CONTEXT.md §6 R66 Option A (Arc A item 2 planning). During the "read existing code first" step the `roadmap-drift-detection` skill flagged **confirmed drift** — the feature is ~85% already shipped.

---

## TL;DR

**Roadmap §4.1 says**: *"Fork-tree visualization — for a single run with descendants, render the full fork DAG (not just the 2-run diff). R37.5 family-tree was a first step; this is the full thing. Arc A second major theme; design doc gated on Arc A slice 4/5 results."*

**Reality (audited 2026-05-12)**:
- ✅ Backend (`/runs/{run_id}/tree?include_descendants=true`) — **shipped R34-A/R37.5-era**
- ✅ Frontend (`/app/#/runs/<id>` TreeView page with "Show descendants" toggle, lane-per-run layout, cross-run fork edges, ReactFlow zoom/pan, node click → drawer, "从头播放" playback, fork-plan modal) — **shipped R34-C / R36-D / R37.5 / R46-A / R48-B**
- ❌ **CLI** — no `chronos tree <run_id>` / `chronos family <run_id>` command
- ❌ **Design doc** — no `docs/design/fork-tree-viz.md` (the feature shipped before its design doc was written — reverse order)
- ❌ **ADR** — no formal scope boundary for "fork-tree-viz" as a named feature; closest prior is ADR-018 (`compare` is `diff`) which touches compare not tree
- ❌ **Dogfood** — no `scripts/dogfood_fork_tree.py` analogous to `dogfood_auto_pivot.py`

**Verdict**: Arc A item 2 is **not** "design + build 3 rounds"; it's "**document what exists + close the CLI/dogfood gap** ~1-2 rounds". Net cost 4-6 rounds → 1-2 rounds (≈3-4× savings), mirroring the R42-A drift-detection ROI pattern.

---

## Evidence trail — what exists in the tree

### Backend: `src/chronos/api/server.py`

```python
# server.py:180
def _assemble_tree_with_descendants(store: SqliteStore, root_run_id: str) -> dict[str, Any]:
    """DFS-merge the root run with every descendant via fork edges.
    ...
    * ``descendant_run_ids`` — ordered list of distinct run_ids included
      (root first, then by DFS discovery order).
    * ``run_summaries`` — ``{run_id: {task_description, status,
      started_at, adapter}}`` so the frontend can render lane labels
      without a second round-trip per run.
    Cycle protection: a ``visited: set[str]`` guards against pathological
    fork graphs ...
    """

# server.py:786
@app.get("/runs/{run_id}/tree")
async def get_run_tree(
    run_id: str,
    include_descendants: bool = Query(
        False,
        description=(
            "If true, DFS-merges every descendant run (reachable via fork "
            "edges) ... `descendant_run_ids` and `run_summaries` fields ..."
        ),
    ),
):
    if include_descendants:
        tree = _assemble_tree_with_descendants(store, run_id)
    else:
        tree = _assemble_tree(store, run_id, nodes, forks)
    ...
```

**Shape of response** (when `include_descendants=true`):
```json
{
  "run_id": "...",
  "nodes": [...],            // every node across every run in the subtree
  "edges": [...],             // sequential + cross-run fork edges
  "child_runs": [...],        // Fork rows (parent_run_id, child_run_id, ...)
  "descendant_run_ids": [...],
  "run_summaries": {
    "<run_id>": {"task_description", "status", "started_at", "adapter"}
  }
}
```

### Frontend: `frontend/src/layout.ts` + `frontend/src/pages/TreeView.tsx`

```ts
// layout.ts:15-25
//   for include_descendants=false callers.
//   the order they appear in tree.descendant_run_ids. Within each lane the
//   turning the diagram into a proper "family tree" (see ADR-018, R37.5).
```

```tsx
// TreeView.tsx:64-75
function InnerTree({ tree, run, includeDescendants, onToggleDescendants }: {
  tree: Tree; run: Run;
  includeDescendants: boolean;
  onToggleDescendants: (v: boolean) => void;
})
```

`TreeView.tsx` features verified by code inspection:
- ReactFlow `@xyflow/react` v12 canvas, zoom/pan, fit-view
- Per-run **lane** layout — each run_id gets its own vertical band (family-tree shape, not just linear)
- Cross-run fork edges rendered between fork-point node and child run's first node
- Lane header shows `task_description` + adapter + status
- "Show descendants" toggle (AntD switch) — fires `fetch(/tree?include_descendants=${bool})`
- Node click → NodeDetails drawer (4 tabs: Identity / I-O / State / Cost)
- Fork point node → R46-A fork-plan modal ("preview plan", ADR-020 effect tags)
- "从头播放" (R36-D) step-playback — timeline stepper over root-run nodes (`rootRunNodes`, descendants excluded from stepper)
- Kind-aware node card coloring (LLM/Tool/Fn/Router/Fork/End, Lucide icons)
- i18n zh/en toggle with `chronos.showDescendants` translation key
- `chr-descendants-toggle` CSS class for the switch wrapper

### Historical context — what R37.5 actually did

`grep -rn "R37.5" docs/` returns 11 matches:
- `docs/design/n-run-compare.md` §8 explicitly defines R37.5 as **the fork-family tree feature** and contrasts it with N-run compare ("serves different questions, both can coexist")
- `docs/decisions/ADR-023-phase-4-charter-skeleton.md` cites R37.5 as a completed Arc A precursor
- `docs/research/r48a-autogen-tool-effects.md:139` notes *"R37.5 added [the family tree]"* and flags a lesson about "live smoke green ≠ feature works end-to-end"
- `docs/progress/2026-05-10-round-60.md:179` cites *"frontend slot 超时史 (R37.5/R46-A)"* — R37.5 was a frontend-heavy round that overran

No `round-37.5` progress file exists in `docs/progress/`, but R37.5 is routinely referenced as an accepted feature in design docs and ADRs. The feature landed; the archival progress doc is either merged into another round or was a filename the agent never created (common enough in project history).

---

## What's actually missing

### Gap 1 — CLI (`chronos tree <run_id>`)

Every other HTTP tree-ish endpoint has a CLI twin:
- `/runs` ↔ `chronos runs list`
- `/runs/{id}` ↔ `chronos runs show`
- `/runs/{id}/nodes` ↔ `chronos runs show` (nested)
- `/runs/{id}/forks` ↔ `chronos forks show`
- `/runs/{id}/tree` ↔ **NONE** ← gap
- `/runs/{a}/diff/{b}` ↔ `chronos diff`
- `/runs/compare/n` ↔ `chronos compare`
- `/runs/compare/auto` ↔ `chronos compare --auto-pivot`
- `/runs/compare/matrix` ↔ `chronos compare --matrix`

A `chronos tree <run_id> [--descendants] [--json]` command would close this. Rich-table rendering is non-trivial for a DAG (unlike the flat matrix view), but a **text-indented tree** + optional `--json` dump is natural and reuses the HTTP response shape 1:1.

### Gap 2 — Design doc (`docs/design/fork-tree-viz.md`)

The feature shipped before its design doc. This is the reverse of the R57 / R61 pattern ("design → ADR → core → surface → proof"). For a feature that's been in production since R37.5 and touched by R46-A / R48-B, a retroactive design doc has real value:

- **New contributors** (including future cron-agent self) can read one doc instead of grepping 5 rounds of progress
- **Boundary with N-run compare** is scattered across `n-run-compare.md` §8 + ADR-023 §Arc A bullet — deserves its own page
- **Public contract** of `/runs/{run_id}/tree?include_descendants=true` (the `descendant_run_ids` + `run_summaries` fields, cycle protection, DFS order) is shipped but never formalised

The doc should **document what exists** (reverse-engineered spec), not propose a rewrite.

### Gap 3 — ADR boundary

No ADR names "fork-tree-viz" as a feature. The closest prior ADRs are:
- ADR-018 (`compare` is `diff`) — compare territory, not tree
- ADR-023 (Phase 4 charter — Arc A committed) — names "Arc A second major theme"
- ADR-024 (multi-pivot compare — Arc A slice 4) — slice 4 only

A thin ADR-025 can formalise:
1. **Scope**: what "fork-tree viz" covers (single-run + descendants DAG); what it does NOT cover (cross-run tree across unrelated runs — that's compare)
2. **Frontend vs CLI vs HTTP parity**: the three surfaces commit to the same data contract (`/runs/{id}/tree`)
3. **Contract freeze**: `descendant_run_ids` + `run_summaries` fields are public contract from the first tag that ships `chronos tree` CLI (probably v0.6.0)
4. **Non-goals**: semantic diff across descendants (that's Phase 4 later), dependency-aware partial fork (that's Phase 4 later), cross-run compare (that's Arc A slice 1-5)

### Gap 4 — Dogfood

No `scripts/dogfood_fork_tree.py`. R60/R64 dogfood precedent:
- Seed a multi-fork scenario (1 parent + 3 children + 1 grandchild, 5 runs total)
- Call `GET /runs/{root}/tree?include_descendants=true`
- Assert: `len(descendant_run_ids) == 5`, `root is first`, `run_summaries keys == descendants`, edges contain the 4 cross-run fork edges, no cycles, each child reachable
- Print the rendered tree structure (or forward to CLI when CLI lands)

R64 `dogfood_auto_pivot.py` + assertion-style release gate is the pattern; fork-tree dogfood should mirror it.

---

## Impact on Arc A scoping

### Before audit (CONTEXT.md §6 as of R65 close)
- R66 = Arc A item 2 **design + ADR** (md-only planning round)
- R67–R69 = Arc A item 2 **impl** (3 rounds — backend DAG assembly, frontend ReactFlow, CLI, dogfood, release)
- Estimated cost: **4 rounds** to reach v0.6.0

### After audit
- R66 = Arc A item 2 **audit + design doc + ADR + roadmap annotation** (md-only planning round — this round)
- R67 = CLI `chronos tree` + dogfood + tag v0.6.0 (single impl+release round mirroring R64 proof-round single-slot pattern — the core/surface already shipped)
- Optional R68 = cosmetic frontend polish if dogfood surfaces UX gaps
- Estimated cost: **1-2 rounds** to reach v0.6.0 = **~3× savings**

### The other Arc A slice 5 accounting

R65 shipped Arc A **slice 5** (matrix-only view) cleanly but un-tagged. The v0.6.0 bundle now includes:
- Arc A slice 5 (R65) — CLI `--matrix` + HTTP `/runs/compare/matrix`
- Arc A item 2 CLI closeout (R67) — CLI `chronos tree` + dogfood

Two user-visible features, one minor version. Consistent with the R60 invariant "Arc slice = core + surface + proof = 1 bundle = 1 minor version".

---

## Non-decisions (explicitly deferred)

- **Per-descendant effect overlay in tree viz** — needs Arc A slice 1-5 learnings on how users filter effects in compare before we know what they'd want in tree. Defer.
- **Fork-DAG-compare (N fork leaves, structural tree diff rather than row alignment)** — Lee-2002 / POA territory flagged in `docs/research/r61-multi-pivot-alignment.md`. Hard, unfalsifiable demand. Defer.
- **Web UI standalone `/app/#/runs/<id>/tree` route distinct from default** — current UX already opens the tree by default at `/app/#/runs/<id>`. A separate URL would fragment. Defer unless user survey asks.

---

## Drift-detection skill citation

This round followed `roadmap-drift-detection` skill 4-step protocol:

| Step | Action |
|------|--------|
| 1. Read milestone rationale | Roadmap §4.1 "render the full fork DAG (not just 2-run diff)" |
| 2. Grep ADR/decisions for territory | `grep -rn "family\|fork.tree\|descendant" src/ frontend/` → 20+ hits, all shipped |
| 3. "If I executed this today, what would change for user?" | Nothing user-facing on Web; CLI gap + doc gap would close |
| 4. Spike the assumption | N/A — the code audit **is** the spike; shipped code is stronger evidence than a new script |

This is the second drift-detection round on chronos-agent (R42-A was first, caught sandbox milestone drift). ROI ~3× both times.

---

## References

- `src/chronos/api/server.py:180-246` — `_assemble_tree_with_descendants` impl
- `src/chronos/api/server.py:786-830` — `/runs/{run_id}/tree` endpoint
- `frontend/src/layout.ts:14-28, 108-135` — family-tree lane layout
- `frontend/src/pages/TreeView.tsx:64-684` — viewer component
- `docs/design/n-run-compare.md` §8 — boundary between fork-tree and N-run compare
- `docs/decisions/ADR-023-phase-4-charter-skeleton.md` — Arc A commitment
- `docs/progress/2026-04-25-round-42a.md` — prior drift-detection precedent (sandbox milestone)

---

*Last updated: 2026-05-12 (R66, CST ~07:10, inside 0–11 cron window). Companion to ADR-025 (drafted this round).*
