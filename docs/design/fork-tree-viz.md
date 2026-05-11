# Fork-tree visualization — design (retroactive, R66)

**Status**: Draft v1 (R66 — Arc A item 2 planning round)
**Owner**: Hermes Agent (autonomous)
**Related ADRs**:
- ADR-023 (Phase 4 charter — Arc A committed, R57)
- ADR-025 (fork-tree-viz scope + contract, R66 drafted this round)
- ADR-018 (`compare` is `diff` — touches tree lane layout in R37.5)
**Related research**: `docs/research/r66-fork-tree-viz-audit.md` (R66 audit — ~85% of this feature shipped before the design doc)
**Companion design doc**: `docs/design/n-run-compare.md` (R57) — sibling feature, different questions (see §8 of that doc and §6 below)

> **Note on retro-documentation**: Unlike `n-run-compare.md` which was written **before** implementation, this document is **retro**. The feature shipped incrementally through R34-A / R34-C / R36-D / R37.5 / R46-A / R48-B. R66 audited the code, surfaced the CLI/dogfood gaps, and wrote this spec to describe **what exists**. Future changes to fork-tree viz should update this doc first (document-first for modifications), not the roadmap.

---

## 1. Problem statement

**User question**: *"This run spawned forks, which spawned forks. Show me the whole family."*

Until v0.1.x, Chronos had a per-run node graph (`/runs/{id}/tree`) but **no view for descendants**. If a run had 3 children and each of those had 2 grandchildren, the user had to open 10 tabs. The information was in the store (fork table, `parent_node_id`), but no surface rendered it.

Fork-tree viz closes that gap: one URL, one CLI call → the entire fork-DAG rooted at a given run.

## 2. Scope

### 2.1 In scope (shipped or about to ship)

1. **Backend** — `GET /runs/{run_id}/tree?include_descendants=true` assembles the fork-DAG via DFS with cycle protection. (✅ shipped)
2. **Frontend** — `/app/#/runs/<id>` page with "Show descendants" toggle. When on, renders lane-per-run with cross-run fork edges. (✅ shipped)
3. **CLI** — `chronos tree <run_id> [--descendants] [--json]` text-indented tree view. (⬜ planned R67)
4. **Dogfood** — `scripts/dogfood_fork_tree.py` creates a 5-run fork graph and runtime-asserts the response shape. (⬜ planned R67)
5. **Contract freeze** — `descendant_run_ids` + `run_summaries` become v0.6.0+ public contract once CLI ships. (⬜ pin with ADR-025)

### 2.2 Out of scope (deferred)

- **Semantic-diff overlay on tree edges** — defer to Phase 4 later theme (ADR needed)
- **Dependency-aware partial fork visualisation** (which nodes would re-execute on fork) — defer; no extractor contract for purity yet
- **Cross-root-run tree** (e.g. "show all my runs as one tree even if no fork lineage") — that's the runs list, not a tree
- **LLM-as-judge equivalence between sibling branches** — separate feature, separate ADR
- **Web UI diff-layer overlay on tree** — possible future, not blocking

### 2.3 Non-goals (hard red line)

- ❌ **Semantic search inside tree** — use `/runs?search=` instead
- ❌ **Write operations (delete run, re-parent fork)** — tree is read-only
- ❌ **Streaming updates** — snapshot at query time, no WebSocket
- ❌ **Infinite/cyclic traversal** — schema prohibits (`fork.parent ≠ fork.child`); cycle guard is defensive only

---

## 3. Data model

### 3.1 Storage (unchanged from v0.1)

No new tables. Fork-tree viz is a pure view over existing state:

```
runs         (id, task_description, status, started_at, adapter, ...)
nodes        (id, run_id, step_index, kind, name, ..., parent_node_id)
forks        (id, parent_run_id, parent_node_id, child_run_id, reason, overrides, created_at)
```

The "tree" is implicit in:
- Within a run: `nodes.step_index` gives sequential order; `parent_node_id` gives graph edges
- Across runs: `forks` rows give cross-run edges (parent's `parent_node_id` node → child's first node)

### 3.2 Assembled response shape (HTTP)

```json
{
  "run_id": "<root_run_id>",
  "nodes": [                        // every node across every run in the subtree
    {"id", "run_id", "step_index", "kind", "name", "metadata", ...}
  ],
  "edges": [                        // sequential within-run + cross-run fork edges
    {"source": "<node_id>", "target": "<node_id>", "kind": "sequential" | "fork"}
  ],
  "child_runs": [                   // Fork rows
    {"fork_id", "parent_run_id", "parent_node_id", "child_run_id", ...}
  ],
  "descendant_run_ids": [           // ordered list (root first, then BFS-ish discovery)
    "<root_run_id>", "<child_1>", "<child_2>", "<grandchild_1>", ...
  ],
  "run_summaries": {                // keyed by run_id for frontend lane headers
    "<run_id>": {
      "task_description": "...",
      "status": "completed" | "failed" | "in_progress",
      "started_at": "2026-05-...",
      "adapter": "langgraph" | "autogen" | "crewai" | "linear"
    }
  }
}
```

**When `include_descendants=false`** (default): `descendant_run_ids` and `run_summaries` are **absent**, `nodes` contains only the root run's nodes, `edges` are sequential-only.

### 3.3 DFS / BFS order

`_assemble_tree_with_descendants` uses a **BFS-ish** stack (`stack.pop(0)`), guaranteeing:
- Root run is always `descendant_run_ids[0]`
- Siblings (children of the same parent) appear before grandchildren
- Discovery order is **deterministic** (given the same fork table, order is repeatable — keyed on `forks` insertion order, which is monotonic by `created_at`)

### 3.4 Cycle protection

`visited: set[str]` guards against pathological graphs. Current schema makes cycles impossible (`fork.parent_run_id ≠ fork.child_run_id` enforced at write time), but defensive guard is kept for future bulk-import scenarios.

### 3.5 Missing-run handling

If a `fork.child_run_id` points to a run that `store.get_run()` returns `None` for (deleted / orphaned), the DFS **skips** it gracefully — no 500, no cascading failure, just the subtree under the missing run is absent from the response. This matches the defensive-read principle from the R63 "Pre-existing-this-slot vs pre-existing-this-round" lesson.

---

## 4. Surface layer

### 4.1 HTTP (shipped)

```
GET /runs/{run_id}/tree?include_descendants=<bool>
```

- 404 if `run_id` not found (base run)
- Never 404 on missing descendants — those are silently skipped per §3.5
- Response shape per §3.2

### 4.2 CLI (planned R67)

```
chronos tree <run_id> [--descendants] [--json] [--db PATH]
```

**Default (no flags)** — single-run text-indented tree:
```
Run <short_id> (langgraph, completed, 2026-05-12T03:56:00)
└── research [step 0, llm, completed]
    └── classify [step 1, llm, completed]
        └── summarize [step 2, llm, completed]
```

**With `--descendants`** — family tree:
```
Run abc123 (langgraph, completed)
├── research [step 0, llm]
│   └── classify [step 1, llm]   ⮡ Fork: twin-seed (xyz789)
│       └── summarize [step 2]
│
├── Run xyz789 (langgraph, completed)  ← fork of abc123 at classify
│   ├── (resume from classify)
│   └── summarize [step 2, llm]        ⮡ Fork: low-temp (def456)
│
└── Run def456 (langgraph, failed)  ← fork of xyz789 at summarize
    └── (resume from summarize)
```

**With `--json`** — dumps the HTTP response shape verbatim for scripting. Rich UI skipped via `print(json.dumps(...))` per project invariant (JSON mode doesn't go through `rich.Console`).

**Implementation sketch**:
- `src/chronos/cli/tree.py` — new module, Typer `tree_command(run_id, descendants, json_mode, db)`
- Reuse `SqliteStore.open()` + call the same `_assemble_tree` / `_assemble_tree_with_descendants` helpers by importing from `chronos.api.server`, **OR** extract them into `chronos.core.tree` first (preferred — decouples CLI from API module). The extraction is a pure refactor; tests can pin behavior identity.
- Rich rendering via `rich.tree.Tree` for the family-tree case
- Fork edges rendered as `⮡ Fork: <reason>` inline after the fork-point node

### 4.3 Web UI (shipped)

`/app/#/runs/<id>` already:
- Defaults to `include_descendants=false` (single-run compact view)
- Has a header toggle (`<Switch/>`) to flip to family tree mode
- Re-fetches the endpoint on toggle (`fetch(/tree?include_descendants=${state})`)
- Layout per `frontend/src/layout.ts` positions each run on its own vertical lane
- Lane header shows run title + adapter + status via `run_summaries[run_id]`
- Cross-run fork edges rendered as dashed grey lines with fork-reason label
- Node click → `NodeDetails` drawer (4 tabs)
- Fork-point click → `ForkPreview` modal (R46-A, ADR-020 effect tags)
- Playback stepper (`usePlayback`) operates on **root-run nodes only** — descendants are visible but not stepped through

**No Web UI changes planned for R67** unless dogfood surfaces a concrete UX gap.

---

## 5. Concrete example — 5-run fork sweep

Scenario: agent runs a task, forks with different temperature, forks again with different model, etc.

```
Run A (root)
├── n1 research
├── n2 classify     ──fork──> Run B (at classify, override temp=0.2)
├── n3 summarize                 ├── (resume)
└── n4 end                       ├── n3' summarize
                                 └── n4' end
                                 ↓
                              ──fork──> Run C (at n3', override model=haiku)
                                          ├── (resume)
                                          ├── n3'' summarize
                                          └── n4'' end

Run D (sibling root, unrelated — NOT in tree(A))
Run E (fork of A at n1) — appears in tree(A)
```

`GET /runs/A/tree?include_descendants=true` returns:
- `descendant_run_ids = [A, E, B, C]` (D is absent — it has no ancestor in A's fork lineage)
- `nodes` = union of A's + E's + B's + C's nodes
- `edges` = sequential within each run + fork edges (A.n1 → E.first, A.n2 → B.first, B.n3' → C.first)
- `run_summaries` = 4 entries

CLI `chronos tree A --descendants` renders this as a text tree with lane-style indentation.

---

## 6. Boundary with N-run compare (Arc A slices 1-5)

The two features are **sibling, not overlap** — same data, different questions.

| User question                                        | Tool                  |
|------------------------------------------------------|-----------------------|
| "What runs descend from this one?"                   | Fork-tree viz (this)  |
| "Is run X in this family?"                           | Fork-tree viz         |
| "These 3 specific runs — how do their outputs differ?" | `chronos compare`     |
| "Pick the centroid of 4 runs for me"                 | `chronos compare --auto-pivot` |
| "Give me the pairwise divergence matrix for 5 runs"  | `chronos compare --matrix` |
| "Show me what B vs A specifically diverged on"       | `chronos diff A B`    |

**Future composition** (not in this round): from the Web UI tree, let the user select N leaf runs → "Compare selected" button → open `/app/#/runs/compare?ids=...`. That UX requires multi-select state in `TreeView.tsx`; deferred.

---

## 7. Test + gate plan for R67

- **Unit** (`tests/unit/test_cli_tree.py`, target +8-10 tests): single-run happy path, `--descendants` flag, `--json` shape, empty descendants (run with no forks), `--db PATH` resolution, missing run (CLI exit 1), deep nesting (4+ levels), fork with missing child
- **Integration** — reuse existing `tests/integration/test_api_server.py` fork-tree tests if any; add CLI↔HTTP shape equivalence test (feed CLI `--json` output through same schema assertion as HTTP integration test)
- **Dogfood** — `scripts/dogfood_fork_tree.py` seeded 5-run graph, runtime-asserts:
  - `len(descendant_run_ids) >= 4` (root + 3+ descendants)
  - `descendant_run_ids[0] == root_run_id`
  - `run_summaries.keys() == set(descendant_run_ids)`
  - Every descendant has at least one node
  - No cycles (visited count == descendant count)
  - Every `fork.child_run_id` appears in `descendant_run_ids`
  - CLI `--json` output byte-parallel with HTTP (fourth cross-layer guard after N=2 argmin quartet — upgrades to **pent**uple)

- **Cov floor** — 94% maintained. CLI addition is ~100 LOC + ~150 LOC tests → cov delta ~0.
- **Adapter** — zero change. R52→R67 = **16 rounds** zero code change target.

---

## 8. Release plan

- R66 (this round): md-only planning (this doc + ADR-025 + research audit + roadmap annotation)
- R67: CLI `chronos tree` + dogfood + `[Unreleased]` CHANGELOG entry
- R67 (same round, time permitting) OR R68: bundle-close with R65 matrix view → **tag v0.6.0**, GitHub Release. Theme: *"Arc A item 2 fork-tree viz (CLI closeout) + slice 5 (pairwise matrix) — the whole family in one command"*

**v0.6.0 scope lock**:
- R65 Arc A slice 5: `chronos compare --matrix` + `/runs/compare/matrix`
- R67 Arc A item 2: `chronos tree` + `/runs/{id}/tree?include_descendants` contract freeze

Per R60 invariant: Arc slice = core + surface + proof = 1 bundle = 1 minor version. Item 2 here piggybacks slice 5 because core (R34-A/R37.5) was done rounds ago; surface is shipped; only CLI+proof are new.

---

## 9. Open questions (none blocking this round)

- **Should `chronos tree` default `--descendants=true` or `--descendants=false`?** — suggest `false` (matches HTTP default, explicit opt-in for possibly-large output). Decide in R67 impl round based on quick sanity check.
- **Should CLI `--descendants` accept `--depth N` to limit recursion?** — defer; no user request, YAGNI.
- **Should the Web UI expose a "back to just this run" breadcrumb from family tree mode?** — it does (toggle off). No new work.

These are R67 impl-round decisions; none are charter-level.

---

## 10. Risks & mitigations

| Risk                                                            | Mitigation                                                     |
|-----------------------------------------------------------------|----------------------------------------------------------------|
| `rich.tree.Tree` rendering breaks at wide terminal widths       | Keep lane width budget; separate print for overflow (R63 finding on truncation hints)|
| Fork-tree has 100+ descendants → wall of text in CLI            | `--depth N` flag (defer) + `--json` is the escape hatch today  |
| CLI `--json` drifts from HTTP shape                             | One cross-layer byte-equivalence test, lock tight              |
| Extracting `_assemble_tree*` from `server.py` regresses HTTP    | Keep HTTP server importing the moved helper; pin via existing `test_api_server.py` tree tests |
| Dogfood flakes on CrewAI (event-bus ThreadPoolExecutor)         | Use linear reference adapter for dogfood (R29 precedent — zero-dep, deterministic) |

---

## 11. References

- `src/chronos/api/server.py:180-246, 786-830` — HTTP + DFS assembly
- `frontend/src/layout.ts:14-135` — lane layout spec
- `frontend/src/pages/TreeView.tsx` — 684-line viewer
- `docs/research/r66-fork-tree-viz-audit.md` — R66 audit trail
- `docs/decisions/ADR-025-fork-tree-viz-scope.md` — this feature's ADR
- `docs/decisions/ADR-023-phase-4-charter-skeleton.md` §Arc A — where this feature was chartered
- `docs/design/n-run-compare.md` §8 — sibling feature boundary

---

*Last updated: 2026-05-12 (R66, CST ~07:20). Retroactive design doc for a feature that shipped R34-A → R48-B. Next update: R67 after CLI lands, flip status Draft → Shipped.*
