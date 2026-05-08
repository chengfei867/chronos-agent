# N-run compare — design doc (Phase 4 Arc A scoping)

**Status**: Draft design (R57, 2026-05-09 CST)
**Author**: Hermes Agent (autonomous)
**Scope**: Generalise the R39-A two-run `compare` verb to arbitrary N ≥ 2 runs.
**Related**:
- ADR-006 (two-run diff alignment algorithm — the foundation)
- ADR-018 (“compare” narrative, two-run shape)
- ADR-023 (Phase 4 charter, promotes to Accepted with Arc A commit in this round)
- R39-A progress doc (shipped `/runs/compare?a=X&b=Y` + `/app/#/runs/<a>/diff/<b>`)
- R37.5 progress doc (fork-family tree — sibling UX concept, **distinct**; see §8)

---

## 0. TL;DR

Today Chronos can compare **exactly 2 runs**. Users in practice fork a
single run 3–5 ways (e.g. sweep temperature, try 3 prompts, swap the
tool) and want to see **all of them at once** with “same vs. changed”
highlighting — not N·(N−1)/2 pairwise tabs.

This doc specifies the CLI-first N-run compare: its UX, its alignment
semantics, its API shape, its SQL-or-merge boundary, and its
non-goals. Zero code lands in this round; the purpose is to lock the
shape so R58+ can implement against it.

---

## 1. Problem statement

After v0.4.0 the fork-tree has **breadth**: users fork more than twice
from the same parent run. The Web compare UI (R39-A) and the CLI
`chronos diff A B` verb both hard-code 2-run input:

```
/runs/compare?a=<id>&b=<id>           # API — two params
/app/#/runs/<a>/diff/<b>              # Web — two-segment path
chronos diff <run_a> <run_b>          # CLI — exactly two positionals
```

**Concrete user complaints (projected; no external users yet — based
on the author's own dogfooding of spike12/13 fork sweeps)**:

1. Sweeping 3 temperatures (0.0 / 0.3 / 0.7) → must open 3 tabs, eyeball.
2. A→B→C chain (fork of a fork): no way to see all 3 aligned; R39-A
   only walks 1 edge at a time.
3. Re-running the same task under LangGraph vs. AutoGen vs. CrewAI
   with identical prompts (adapter-equivalence dogfood) — no diff at all.

Arc A's highest-leverage deliverable (per ADR-023 §Arc A item 1) is
addressing these.

---

## 2. Goals & non-goals

### 2.1 Goals

- **CLI first**: `chronos compare a b c [...]` — the lowest-friction surface.
- **API stable shape**: one endpoint returns everything the Web UI needs.
- **Alignment is O(N) not O(N²)**: pick a pivot, align every other run against it.
- **Schema preservation**: no new columns in `runs` / `nodes` / `forks`. Purely derived.
- **Adapter-agnostic**: the three-adapter matrix (LangGraph, AutoGen, CrewAI) all work the same under N-run compare because ADR-006 alignment already is.
- **Graceful degradation to 2-run**: when N=2, output is a superset of today's `DiffReport` — no regression for existing users.

### 2.2 Non-goals (explicit)

- ❌ **Semantic diff** (LLM-as-judge): deferred to ADR-023 Arc A item 3.
- ❌ **Fork-tree / DAG visualization**: sibling feature (ADR-023 Arc A item 2), **not** this doc. See §8 for the distinction.
- ❌ **Web UI implementation**: CLI + API this arc; Web arrives R60+.
- ❌ **Mutating operations** (re-fork from N-run view, bulk re-run): keep this pure read.
- ❌ **Cross-adapter *structural* normalisation**: two runs on different adapters are *comparable* by user-level `task_description` but the structural alignment treats them as "completely different run shapes" (graceful; it should not crash).
- ❌ **Performance target for N ≥ 20**: we assume N ≤ 8 for the design. Bigger N is explicitly TBD Phase 5.

---

## 3. UX sketch

### 3.1 CLI — the primary surface

```
$ chronos compare <pivot_run_id> <other_run_id> [<other_run_id> ...] [options]
```

Decisions:

- **First positional is the pivot** (the "before"). All other positionals align against it. This mirrors `git rebase <upstream>` where the first arg frames the rest.
- **Minimum 2 positionals** (backwards-compat: 2 = today's `chronos diff`).
- **No positional upper limit at parse time**; a soft warning prints at N > 8.

Flags:

| Flag                             | Default | Purpose                                                                       |
|----------------------------------|---------|-------------------------------------------------------------------------------|
| `--restrict-to-downstream/-R`    | `true`  | Same semantic as today's 2-run: skip shared prefix when applicable.           |
| `--format {text,json}`           | `text`  | Machine-readable output for pipes / JSON tooling.                             |
| `--columns {all,changed,changed-or-added}` | `changed-or-added` | Which rows to print in text mode.                              |
| `--show-equal`                   | off     | In text mode, also print `equal` rows (noisy; useful for debugging).          |
| `--width <n>`                    | auto    | Column width override for narrow terms.                                       |

Text output (N=3 sketch, each column = one run):

```
Pivot: run_001  (langgraph, success, "write a haiku about cats")
                A                    B                    C
                run_001 (pivot)      run_002              run_003
step node       kind  effects        kind  effects        kind  effects        status
───────────────────────────────────────────────────────────────────────────────────────
 0   start      llm   [read:task]    llm   [read:task]    llm   [read:task]    = = =
 1   plan       llm   [write:plan]   llm   [write:plan]   llm   [write:plan]   = = =
 2   draft      llm   [write:draft]  llm   [write:draft]  llm   [write:draft]  ≠ ≠ =
 3   refine     llm   [write:final]  llm   [write:final]  —     —              = ≠ − (removed in C)
 4   —          —     —              —     —              llm   [write:final']  − − +

Summary:  A vs. B: 1 changed / 0 added / 0 removed
          A vs. C: 1 changed / 1 added / 1 removed
          A vs. B vs. C: 2 rows diverge anywhere
```

JSON output: §5 below.

### 3.2 Web — deferred, but sketch the URL now so the API doesn't paint into a corner

```
/app/#/runs/compare?ids=a,b,c[,...]
```

- Query-param list, not path segments: N is variable so a path segment
  encoding (`.../diff/a/b/c/...`) blows up the route pattern.
- The existing `/app/#/runs/<a>/diff/<b>` is kept as a sugar redirect
  to `.../compare?ids=<a>,<b>` so R39-A links don't 404.

Layout sketch (R60+ implementation):

- Sticky left lane = pivot (always labelled "pivot").
- Subsequent lanes = other runs, in positional order.
- Rows = pivot-indexed steps.
- Cells in a row visually highlighted when any non-pivot cell differs from pivot at that row.
- Per-cell click → existing 2-run drill-down (pivot vs. that specific column) = reuses R39-A machinery.

### 3.3 Why CLI first, Web later

1. CLI is fast to ship and test (no frontend round-trip).
2. CLI is what dogfooding uses (the author sweeps forks in scripts).
3. Locking API shape via CLI forces the JSON contract to be language-neutral before the Web UI bakes assumptions into React props.

---

## 4. Alignment semantics

### 4.1 The pivot-anchored O(N) design

Given runs `[pivot, r1, r2, ..., r_{N-1}]`:

1. For each `r_i`, compute today's `DiffReport(pivot, r_i)` using
   the exact ADR-006 algorithm. This reuses *all* the existing code
   and guarantees N=2 is a strict superset.
2. Merge the N−1 reports on the pivot's step index. The pivot row
   is the spine; each `r_i`'s report contributes its own column
   (`kind`, `effects`, `status-vs-pivot`).
3. A row's **cross-run status** is derived per-column:
   - `=` : this `r_i` matches pivot at this pivot-step.
   - `≠` : changed.
   - `−` : pivot has a node here, `r_i` does not.
   - `+` : `r_i` inserts a node between pivot steps (rendered as a half-row with pivot column empty).

Complexity:

- **Work**: N−1 calls to existing `diff_runs(pivot, r_i)`. Each call is O(L_p + L_i) per ADR-006. Total O(N · L_max).
- **Not O(N²)**: we do **not** compute pairwise diffs between non-pivot runs. The user clicks into a 2-run drill-down for that, and that drill-down is one `diff_runs(r_i, r_j)` call on demand.
- **Memory**: linear in output rows (N × max(L_p, L_i_max)).

### 4.2 What "pivot" means for fork-family vs. arbitrary runs

Two user intents:

| Intent                       | Pivot selection                                         | restrict_to_downstream |
|------------------------------|---------------------------------------------------------|------------------------|
| Fork sweep: compare children | pivot = **parent run**; others = forked children        | `true` (default)       |
| Adapter equivalence          | pivot = **reference adapter run**; others = alt adapters| `false`                |
| Arbitrary runs (any N)       | pivot = **first positional**; user's explicit choice    | `false` recommended    |

When the user passes a forked child as `a` and its parent as `b` (or
arbitrary mixes with forks), `restrict_to_downstream` auto-detects
fork ancestry *per pair* — same semantic as today's 2-run, applied
N−1 times. If some children are forks of pivot and some aren't,
each pair behaves independently; this is a feature, not a bug.

### 4.3 Misaligned adapters — graceful degradation

If `pivot.adapter != r_i.adapter`, today's `diff_runs` already works
(it aligns by node_name + kind per ADR-006). Results will mostly be
"everything is `removed` + everything is `added`" with some coincidental
equals on generic names like `start`. That's the right thing: the user
asked for the compare, they get it, they learn their adapters don't
align by node name. Add a `WARN`-level message in CLI text output:

```
⚠ Runs A and C use different adapters (langgraph vs. crewai).
  Structural alignment will mostly show "removed / added".
  For adapter-equivalence analysis, consider task-level judgement.
```

### 4.4 N=2 compatibility

When exactly 2 positionals are passed:

- Text output is visually equivalent to today's `chronos diff` 2-column view. (We may actually make `chronos diff A B` an alias to `chronos compare A B` in the implementation round; ADR-006 stays.)
- JSON output is a **superset** of today's `DiffReport.to_dict()`: same top-level keys, plus new `pivot_id` / `others[]` / `alignment[]`. The 2-run API `/runs/compare?a=X&b=Y` keeps returning today's shape verbatim for back-compat (see §5.2).

---

## 5. Data & API shape

### 5.1 The N-run endpoint

```
GET /runs/compare/n?ids=<id1>,<id2>[,<id3>,...]
    [&restrict_to_downstream=true]
```

Why a **new path** (`/runs/compare/n`) instead of reusing `/runs/compare`:

- The 2-run endpoint returns `{diff, tree_a, tree_b}` — `tree_a`/`tree_b` are literal keys. Extending that to N without breaking clients is ugly.
- A sibling path keeps the 2-run endpoint frozen (R39-A tests stay green) and avoids conditional response shapes.

Query params:

- `ids` (required): **comma-separated** list of run_ids, ≥ 2. First is pivot. Duplicates 400.
- `restrict_to_downstream` (optional, default `true`): applied per (pivot, r_i) pair.

Response shape:

```json
{
  "pivot_id": "run_001",
  "other_ids": ["run_002", "run_003"],
  "runs": {
    "run_001": { "id": "...", "adapter": "langgraph", "status": "success", "task_description": "..." },
    "run_002": { "id": "...", "adapter": "langgraph", "status": "success", "task_description": "..." },
    "run_003": { "id": "...", "adapter": "langgraph", "status": "success", "task_description": "..." }
  },
  "trees": {
    "run_001": { /* same shape as /runs/{id}/tree */ },
    "run_002": { /* ... */ },
    "run_003": { /* ... */ }
  },
  "diffs": {
    "run_002": { /* full DiffReport(pivot=run_001, other=run_002).to_dict() */ },
    "run_003": { /* full DiffReport(pivot=run_001, other=run_003).to_dict() */ }
  },
  "alignment": [
    {
      "pivot_step": 0,
      "pivot_node_name": "start",
      "per_run": {
        "run_002": {"tag": "equal",   "node_id": "..."},
        "run_003": {"tag": "equal",   "node_id": "..."}
      }
    },
    {
      "pivot_step": 2,
      "pivot_node_name": "draft",
      "per_run": {
        "run_002": {"tag": "changed", "node_id": "..."},
        "run_003": {"tag": "equal",   "node_id": "..."}
      }
    },
    {
      "pivot_step": null,
      "pivot_node_name": null,
      "inserted_after_pivot_step": 3,
      "per_run": {
        "run_002": {"tag": "absent"},
        "run_003": {"tag": "added",   "node_id": "...", "node_name": "final'"}
      }
    }
  ],
  "summary": {
    "run_002": {"equal": 2, "changed": 1, "added": 0, "removed": 0},
    "run_003": {"equal": 1, "changed": 1, "added": 1, "removed": 1}
  },
  "warnings": []
}
```

Key decisions:

- `runs` / `trees` are **dicts keyed by id**, not arrays. Order is
  in `[pivot_id, *other_ids]`. Dicts make per-run lookup O(1) client-side.
- `diffs` is populated for pairs `(pivot, r_i)` only — never `(r_i, r_j)`. O(N) endpoints for O(N) work.
- `alignment[]` is the **merged view** — the thing the Web UI renders row by row. Clients that want the raw 2-run reports still have `diffs`.
- `warnings` is a list of strings (currently: adapter-mismatch warnings, N-too-large warnings, etc.).

### 5.2 Back-compat for the 2-run endpoint

`/runs/compare?a=X&b=Y` stays exactly as today. R39-A tests do not change. Web UI route `/app/#/runs/<a>/diff/<b>` hits this endpoint unchanged.

New route `/app/#/runs/compare?ids=...` (R60+) hits `/runs/compare/n`.

### 5.3 Store API — use `get_nodes_for_run` + client-side merge, **do not** change schema

Today's `SqliteStore.get_nodes_for_run(run_id)` is sufficient.
`compare/n` implementation = for each id in `ids`, fetch nodes +
forks once, then run the merge in Python. No new SQL, no new
migrations, no new columns. This upholds the "Schema evolution
backwards-compatible within a minor version" cross-phase commitment
(roadmap §Cross-Phase Commitments item 5).

**Why not a single big SQL join**:

1. The alignment algorithm (ADR-006) is Python-side today. A SQL
   version would duplicate logic and diverge.
2. N is small (≤ 8 in our design envelope); N round-trips to SQLite
   on the same process is cheap (<5ms each warm).
3. When we eventually add Postgres or LAN-sharing (Phase 4.2
   Ecosystem), keeping the alignment Python-side means no DB dialect
   branch.

### 5.4 Caching — out of scope for R58 impl

A future `diff_cache` table keyed on `(hash(run_a), hash(run_b))` is
tempting but premature. We ship the Python-side loop first, measure,
then decide.

---

## 6. CLI text-mode rendering

### 6.1 Layout constraints

- Terminal width is a hard constraint: 3 runs × (kind + effects) fits in ~80 chars marginally. 5 runs almost certainly overflows.
- Solution: **auto-collapse columns at width overflow** — collapse effects to a short tag count like `+2eff`, and offer `--format json` as the escape hatch for scripts.
- For N > 3, default to showing `--columns changed-or-added` only (saves vertical).

### 6.2 Libraries

Use `rich.table.Table` already imported across the CLI. No new deps.

### 6.3 Colour semantics (reuse, don't invent)

- `=` dim grey
- `≠` yellow (match existing diff colour)
- `−` red
- `+` green
- Adapter-mismatch warning line: magenta, prefixed `⚠`.

---

## 7. Edge cases & open questions

### 7.1 Edges with decisions

| Case                                               | Decision                                                    |
|----------------------------------------------------|-------------------------------------------------------------|
| N=1                                                | Error with helpful message: "need at least 2 runs".          |
| Duplicate ids                                      | 400. Silent dedup is a footgun.                              |
| Pivot id not in store                              | 404 (same as today's 2-run).                                 |
| One of the others not in store                     | 404 with the missing id named (don't partially succeed).     |
| All others are forks of pivot                      | Default `restrict_to_downstream=true`; classic fork sweep.   |
| Mixed forks + unrelated runs                       | Per-pair auto-detect — independent behaviour per column.     |
| Two different adapters                             | Warn, continue — §4.3.                                       |
| Same run id listed twice (pivot == others[k])      | 400 (see above).                                             |
| N = 20                                             | Warn in CLI / in `warnings[]`; do it anyway. (Hard-cap TBD.) |

### 7.2 Open questions (defer to implementation rounds R58/R59)

- **OQ-1**: Should CLI `chronos diff A B` become a strict alias for `chronos compare A B`? Default: yes, with a deprecation notice in v0.6; do *not* remove before v1.0. Needs ADR-025 if we decide to deprecate.
- **OQ-2**: Should `/runs/compare` (2-arg) become an alias for `/runs/compare/n?ids=a,b`? **No** — API surface freezes a shape, aliases burn audit surface area. Keep both, test both.
- **OQ-3**: Do we want a `--pivot auto` that picks the most-referenced parent run? Interesting, not P0. Defer.
- **OQ-4**: Effect-tag cross-run diff visual (e.g. `[read:task] vs. [write:task]` at same node)? Already covered by today's `DiffEntry.state_diff`; the merged view just shows the per-column tag.
- **OQ-5**: Machine output for CI (e.g. "fail if >0 changed"): add `--exit-code` flag that returns non-zero on divergence? Nice-to-have, R59+.

---

## 8. Relationship to R37.5 fork-family tree (and why they are different features)

The R37.5 fork-family visualization renders the **DAG of forks**: given one run, show it plus its descendants plus the edges between (fork node, child run). The leaves aren't aligned; the rendering is *structural* (DAG), not *row-by-row*.

N-run compare renders a **table**: N columns, pivot-indexed rows, alignment tags per cell.

They serve different questions:

| Question user is asking                          | Tool            |
|--------------------------------------------------|-----------------|
| "What descendants did this run spawn?"           | R37.5 fork tree |
| "Which forks' outputs diverged, and where?"      | N-run compare   |
| "Is this run a fork of that one?"                | Run detail view |
| "These 3 arbitrary runs — which diverges?"       | N-run compare   |

Both can coexist and in fact the Web UI R60+ may launch N-run compare
*from* a fork-tree node (multi-select N leaves → "compare selected").
Arc A delivers them in order: **N-run compare first** (this doc),
fork-tree second (a later design doc in the same arc).

---

## 9. Implementation plan (preview, binding once ADR-023 Accepted)

The code work is **not** this round. Once ADR-023 is Accepted and
pins Arc A, the implementation rounds look like:

- **R58** — core: `chronos.core.diff.merge_pivot_reports(reports)` function; returns the `alignment[]` list. Unit tests against synthetic 2/3/5-run fixtures. Pure, no store. Landing bar: `diff.py` gets ~150 lines, 10+ new unit tests, 2-run `DiffReport` untouched.
- **R59** — CLI + API wiring: `chronos compare a b c [...]` + `GET /runs/compare/n`. Reuses R58 merge. Rich-table text renderer. JSON output mirrors §5.1. Landing bar: ~200 lines CLI + ~50 lines API, 8+ integration tests (duck + live with existing fixtures).
- **R60** — optional Web UI path: `/app/#/runs/compare?ids=...`. Reuses existing R39-A components. Only if dogfooding R58/R59 surfaces a frontend need.
- **R61?** — retro / spike14 (dogfood R58/R59 on a 5-fork sweep against the CrewAI haiku task).

All three code rounds should maintain: **474 pass / 3 skip / 94% cov floor**, adapter code untouched (the R52 CrewAI scaffold zero-change streak continues), `ForkPlan` / `Extractor` / `Adapter interface` contracts untouched.

---

## 10. Risks & mitigations

| Risk                                                                | Mitigation                                                                  |
|---------------------------------------------------------------------|-----------------------------------------------------------------------------|
| N-run merge diverges from ADR-006 semantics over time               | The merge is a *pure function of* existing 2-run reports. No separate semantics.  |
| Large N blows up terminal / browser                                 | Soft cap at 8, graceful `--columns` collapse, `warnings[]` on wire.         |
| API shape changes in R59 impl force Web re-work                     | Lock the JSON shape now (§5.1) and test-freeze it in R59 impl.              |
| User expects pairwise diff grid                                     | Explicit docs: "We are O(N) against pivot, click a column for pairwise."    |
| Adapter-mismatch → mostly-useless output                            | Warn clearly (§4.3); don't silently return nonsense.                        |
| 2-run CLI `chronos diff A B` regressed during unification           | Keep a duck-level acceptance test that `diff A B` and `compare A B` give identical top-level summary counts.     |

---

## 11. Success criteria

The Arc A N-run compare slice is **done** when:

1. `chronos compare a b c [...]` works for 2 ≤ N ≤ 8, text + JSON.
2. `GET /runs/compare/n?ids=...` returns the §5.1 shape, stable across R58/R59.
3. A dogfood round (R61?) uses it on a 3+ fork sweep of a real recorded task (ideally the CrewAI haiku task from spike13) and writes a retro that says "this is what I use instead of opening 3 tabs".
4. Test gates hold: 474+ pass, 94%+ coverage, mypy clean, ruff clean.
5. No schema migration. No changes to `ForkPlan`, `Extractor`, or `Adapter interface`.
6. No regression on the 2-run compare (`/runs/compare?a=X&b=Y` byte-identical).

---

## 12. Appendix: rejected alternatives

- **A. Matrix of pairwise diffs (O(N²))**: N·(N−1)/2 reports. Visually
  nice but quadratic work for no insight users don't get from clicking
  into pivot-anchored drill-downs. Rejected.
- **B. In-SQL alignment via a view**: couples alignment to SQLite
  dialect; blocks Postgres/Parquet futures. Rejected (see §5.3).
- **C. "Tree-aware" pivot auto-selection**: compute the LUB of the fork
  ancestry of all N ids, use it as pivot. Clever but fragile when
  ancestry spans unrelated runs. Accept user-provided pivot, keep the
  auto-pivot as OQ-3 for later.
- **D. Web-first ship**: skip CLI, go straight to React. Rejected —
  CLI locks the JSON contract before React props harden.
- **E. New SQL columns** for "fork_generation" / "sibling_index": would
  make some queries cheaper but violates the cross-phase schema
  stability commitment. Purely derived for now; revisit post-v1.

---

*Written R57, single round, zero code. Following this doc, ADR-023 is
promoted Draft → Accepted with Arc A committed. The binding
implementation decisions live in the §9 plan.*
