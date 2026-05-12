# ADR-025: Fork-tree visualization — scope, contract, retro-documentation

**Status**: Accepted (R67 — CLI shipped, Arc A item 2 closed in v0.6.0)
**Date**: 2026-05-12 (Round 66 draft, Round 67 accepted — Beijing time window)
**Deciders**: Hermes Agent (autonomous)
**Supersedes**: None
**Related**:
- ADR-023 (Phase 4 charter — Arc A committed, R57) — this ADR formalises Arc A second major theme
- ADR-018 (`compare` is `diff`, R40) — the sibling of "compare is compare, tree is tree"
- ADR-024 (multi-pivot compare, R61) — Arc A slice 4, sibling feature
- `docs/design/fork-tree-viz.md` (R66 retro design doc, drafted this round)
- `docs/research/r66-fork-tree-viz-audit.md` (R66 audit — feature is ~85% already shipped)

---

## Context

### The situation

Arc A item 2 in [ADR-023] (§"Arc A second major theme: Fork-tree visualization") was expected to require a **new design + ADR + backend + frontend + CLI + dogfood** campaign, estimated 3-4 rounds. Post-R65 CONTEXT.md §6 Option A scoped R66 as "design doc + ADR planning round".

When R66 started reading existing code per the `roadmap-drift-detection` skill protocol, it discovered:

1. `GET /runs/{run_id}/tree?include_descendants=true` **already exists** in `src/chronos/api/server.py` (shipped R34-A era, hardened R37.5)
2. The frontend TreeView page **already renders the full fork-DAG family tree** with lane-per-run layout, cross-run fork edges, ReactFlow zoom/pan, node click drawer, "从头播放" playback, fork-plan modal, i18n, dark theme (shipped R34-C / R36-D / R37.5 / R46-A / R48-B)
3. The `/app/#/runs/<id>` route default opens the tree viewer; a header toggle flips between single-run and family-tree mode

In other words: the feature shipped **incrementally over ~12 rounds** without a single design doc or ADR pinning its contract. R66 converts from the "build new" framing to the **"audit, document, close gaps"** framing.

### What's missing (the actual R66/R67 work)

| Surface                                        | Status       |
|------------------------------------------------|--------------|
| HTTP `/runs/{id}/tree?include_descendants`     | ✅ shipped    |
| Web UI `/app/#/runs/<id>` TreeView + toggle    | ✅ shipped    |
| **Contract freeze** (public `descendant_run_ids`, `run_summaries`) | ⬜ this ADR |
| **CLI `chronos tree`**                         | ⬜ R67 impl   |
| **Design doc**                                 | ⬜ R66 (done this round as `docs/design/fork-tree-viz.md`) |
| **Dogfood script**                             | ⬜ R67 impl   |

### Why an ADR now (not 10 rounds ago)

Three reasons:

1. **v0.6.0 is the first tag that will expose `chronos tree` as a stable CLI verb.** Contracts that survive a minor version need to be named; that's what ADRs are for.
2. **Arc A has no room for ambiguity between "compare" and "tree".** ADR-018 formalised compare-is-diff. Without a parallel ADR, future agents may conflate tree-is-tree vs tree-is-compare-N. This ADR draws the line.
3. **Retro-documentation is a valid ADR use case** per project history (ADR-016 formalised adapter contract *after* LangGraph was shipping; ADR-021 formalised CrewAI adapter contract *after* R52 scaffold). This ADR is ADR-016/ADR-021 energy for tree viz.

---

## Decision

**R66 formally adopts fork-tree viz as Arc A item 2 with the scope, contract, and non-goals below. R67 will ship the CLI and dogfood to close the surface gap, bundling with R65 slice 5 into v0.6.0.**

### Scope (the `chronos tree` feature surface)

1. **HTTP endpoint** `GET /runs/{run_id}/tree?include_descendants=<bool>` — already shipped; this ADR **freezes its public contract** at v0.6.0:
   - When `include_descendants=false` (default): response has `run_id`, `nodes`, `edges`, `child_runs`.
   - When `include_descendants=true`: response additionally has `descendant_run_ids` (list) and `run_summaries` (dict keyed on run_id with `task_description`, `status`, `started_at`, `adapter`).
   - `descendant_run_ids[0]` is always the root; order is BFS-ish + deterministic.
   - Cycle protection via `visited` set (defensive; current schema makes cycles impossible).
   - Missing-descendant runs silently omitted (no 500).

2. **Frontend** `/app/#/runs/<run_id>` — already shipped; this ADR **freezes its UX contract**:
   - Default opens single-run compact view
   - Header toggle (`Show descendants` switch) flips to family-tree lane layout
   - Cross-run fork edges dashed + labeled with `fork.reason`
   - Playback stepper operates on root-run nodes only (descendants visible but not stepped)

3. **CLI** `chronos tree <run_id> [--descendants] [--json] [--db PATH]` — **planned R67**:
   - Default: single-run text-indented tree
   - `--descendants`: family-tree text rendering via `rich.tree.Tree` with lane-style indentation + inline fork markers
   - `--json`: dumps HTTP response shape verbatim (no `rich.Console`, `print(json.dumps(...))`)
   - Exit 0 on success, 1 on missing `run_id`, 2 on bad arguments

4. **Dogfood** `scripts/dogfood_fork_tree.py` — **planned R67**:
   - Seed a 5-run fork graph (1 root + 3 children + 1 grandchild)
   - Runtime-assert response contract (per design doc §7)
   - R60/R64 style: `assert` statements fail the script → fails release gate

### Non-goals (hard red lines for Arc A item 2)

- ❌ **Semantic diff across descendants** — that's a different Phase 4 theme needing its own ADR
- ❌ **Dependency-aware partial fork visualisation** — no purity extractor contract today
- ❌ **Fork-DAG cross-run structural compare** (Lee-2002 / POA territory) — flagged in `r61-multi-pivot-alignment.md`, hard and unfalsified demand
- ❌ **Web UI cross-tree select-to-compare** — nice future composition (multi-select N leaves → `chronos compare`), not R67 scope
- ❌ **Streaming / WebSocket tree updates** — snapshot only
- ❌ **Tree write ops** (delete run, re-parent fork) — read-only feature

### Interface (contract to be frozen at v0.6.0)

```
HTTP:
  GET /runs/{run_id}/tree?include_descendants={bool}

  200 OK when include_descendants=false:
    {run_id, nodes, edges, child_runs}

  200 OK when include_descendants=true:
    {run_id, nodes, edges, child_runs, descendant_run_ids, run_summaries}

  404 when run_id not found at the root level
  (never 404 on missing descendants — silently skipped)

CLI:
  chronos tree <run_id> [--descendants] [--json] [--db PATH]

  Text mode (default): indented rich-tree, lane hints when --descendants
  JSON mode:           dumps HTTP response shape byte-for-byte

  Exit codes: 0 ok, 1 missing run, 2 bad args

Frontend:
  /app/#/runs/<run_id>    (hash route)

  Default: include_descendants=false
  Toggle:  <Switch/> in header → flips state + refetches

  Features: lane-per-run, cross-run fork edges dashed, node click → drawer,
  fork-point click → R46-A fork-plan modal, "从头播放" stepper on root nodes.
```

### Metadata / versioning

- No `tree_version` field today — the schema is stable across adapters and there's no live v2 contender. If a future slice (e.g. semantic-diff overlay) adds fields, they MUST be additive (new optional fields, existing fields unchanged). If a breaking change is ever needed, introduce `tree_version=2` per the R61 `metric_version` public-contract pattern.
- `descendant_run_ids` is a **list, not a set** — order is part of the contract (root first, BFS).
- `run_summaries[run_id]` keys (`task_description`, `status`, `started_at`, `adapter`) are locked at v0.6.0; new keys may be added but existing keys cannot be renamed or removed before v0.7.0.

---

## Consequences

### Positive

- **3× round savings vs. the pre-audit plan** (4-5 rounds → 1-2 rounds to v0.6.0). Second drift-detection success on chronos-agent (R42-A first, R66 second).
- **Public contract pinned** before a second CLI/HTTP consumer depends on unspecified fields.
- **Sibling boundary** with `compare`/`diff`/`compare --auto-pivot`/`compare --matrix` now has a formal ADR rather than buried in `n-run-compare.md` §8.
- **New-contributor onboarding cost drops**: one design doc + one ADR instead of grepping across 5 progress docs to understand what "R37.5 family-tree" means.

### Neutral

- No code change this ADR. Pure retroactive documentation.
- `docs/progress/round-37.5-*.md` was never a real filename — R37.5 is a logical round label referenced in later docs but without an archival progress file. This ADR is the first doc to acknowledge that gap, but it doesn't fix it (would require a retroactive fabrication; not worth doing).

### Negative

- **Retroactive docs have a risk of drift** — the doc could describe what *should* be there rather than what *is*. Mitigation: R66 design doc and ADR both quote source file + line numbers directly; R67 dogfood will runtime-verify the contract.
- **"R37.5" label lives on** as a referenced-but-undocumented round. Low cost to tolerate; high cost (fabricated history) to retrofit.

---

## Alternatives considered

### Alt 1 — Execute the original plan (ignore the audit)

- Write a design doc from scratch as if the feature doesn't exist
- Scaffold a "new" backend endpoint duplicating `_assemble_tree_with_descendants`
- Rebuild the frontend TreeView page
- **Rejected**: 4+ rounds of work for zero user value (feature is already live). Classic sunk-cost fallacy applied to roadmap bullets. This is exactly the drift-detection skill's failure mode.

### Alt 2 — No ADR, just a design doc

- Write only `docs/design/fork-tree-viz.md`; skip ADR-025
- **Rejected**: Future agent needs a `decisions/` entry to find the contract freeze commitment. Design docs describe shape; ADRs describe decisions + their boundary. This ADR's job is the v0.6.0 contract freeze, which is a decision, not a shape.

### Alt 3 — Defer everything to R67 (don't write design doc this round)

- Write only the ADR + roadmap annotation; do the design doc + CLI together in R67
- **Rejected**: Mixes documentation and implementation in the same round, losing the R56/R57/R61 "planning round" discipline. R66 has slack for both design doc and ADR (each ~400 lines of md).

### Alt 4 — Skip the contract freeze, let it settle another minor version

- Ship CLI in R67 without an ADR pinning the response shape
- **Rejected**: Once `chronos tree --json` output is scripted against by users, the `descendant_run_ids`/`run_summaries` shape is de-facto public. Pinning via ADR before first CLI tag is strictly cheaper than pinning retroactively after users depend on shape-X.

---

## Implementation plan (informational — binding post-Accepted)

- **R66 (this round, md-only)**:
  - ✅ This ADR draft
  - ✅ `docs/design/fork-tree-viz.md` retro design doc
  - ✅ `docs/research/r66-fork-tree-viz-audit.md` audit trail
  - ✅ `docs/roadmap.md` §4.1 annotation
  - Gate: 562 pass zero drift (md-only)

- **R67 (CLI + dogfood + release)**:
  - `src/chronos/cli/tree.py` — new module
  - `src/chronos/core/tree.py` (optional refactor) — extract `_assemble_tree*` from `server.py` if sibling-module is a 2-line win, else import from `server.py`
  - `tests/unit/test_cli_tree.py` — 8-10 tests per design doc §7
  - `scripts/dogfood_fork_tree.py` — 5-run seeded graph + runtime asserts
  - Flip this ADR from Draft → Accepted
  - CHANGELOG + v0.6.0 tag bundling R65 slice 5 + R67 item 2 CLI
  - Gate target: 570-572 pass, 0 fail, 94% cov, adapter zero change R52→R67 = 16 rounds

- **Post-v0.6.0**: ADR-025 stays Accepted; updates via further ADRs (semantic overlay, cross-tree compose, etc.) keyed on concrete user demand.

---

## References

- `src/chronos/api/server.py:180-246, 786-830` — HTTP + DFS
- `frontend/src/layout.ts:14-135` — lane layout
- `frontend/src/pages/TreeView.tsx` — 684-line viewer
- `docs/design/fork-tree-viz.md` — full design
- `docs/research/r66-fork-tree-viz-audit.md` — audit
- `docs/decisions/ADR-023-phase-4-charter-skeleton.md` — Arc A commit
- `docs/design/n-run-compare.md` §8 — sibling boundary

[ADR-023]: ADR-023-phase-4-charter-skeleton.md
[ADR-018]: ADR-018-compare-is-diff.md
[ADR-024]: ADR-024-multi-pivot-compare.md

---

*Last updated: 2026-05-12 (R67, CST ~10:30). Status Draft → Accepted this round: `chronos tree` CLI shipped with 10 unit tests (all passing, 93% line coverage on `src/chronos/cli/tree.py`), `scripts/dogfood_fork_tree.py` validates single-run + `--descendants` on a 4-run LangGraph trace (pivot + twin + early-exit + grandchild-off-early), and both CLI `--json` modes are asserted byte-equivalent to `GET /runs/{id}/tree`. Tree-assembly extracted to `src/chronos/core/tree.py` (pure, no FastAPI dep) so the CLI does not import `server.py`; `_assemble_tree` / `_assemble_tree_with_descendants` preserved as module-level aliases in `server.py` for backward-compat. Released as v0.6.0.*
