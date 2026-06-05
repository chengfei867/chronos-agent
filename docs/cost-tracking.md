# Cost & Token Tracking

Chronos surfaces token counts and USD cost as **first-class** information at every layer — recorded once by the adapter, aggregated automatically, and rendered by default in the CLI, the Web UI, and the API. There is no per-provider price table to maintain and no relay-side accounting to configure: whatever your adapter recorded is what Chronos shows.

> Specced in [ADR-029: Cost Visibility](decisions/ADR-029-cost-visibility.md), shipped in **R111** as part of the v1.0 RC arc.

---

## What gets captured

Each `Node` of a recorded run can carry a `Usage` envelope:

```python
class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0          # for o1-style models
    cost_usd_cents: int | None = None  # in cents, sub-cent rounding handled
    model_name: str | None = None
```

The four first-class adapters (LangGraph, Anthropic Agents SDK, CrewAI, AutoGen) extract this envelope automatically from each LLM call, plus the Linear adapter for issue ingestion. You don't write usage-extraction code yourself — the adapter contract is responsible for it. See [ADR-009](decisions/ADR-009-usage-extractor-hook.md) and [ADR-015](decisions/ADR-015-extractor-contract-v2.md).

If your custom adapter doesn't yet emit `Usage`, you can attach it manually via `recorder.attach_usage(node_id, usage)` after the fact — useful for retro-fitting historical runs.

---

## Where you see it

### 1. `chronos runs list` — default-on table columns

When *any* run in your database has `usage_summary.total_tokens > 0`, the listing automatically includes two right-aligned columns:

```
$ chronos runs list
                                    Recent runs
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┓
┃ id (short) ┃ task                       ┃ started ┃ tokens ┃ cost ¢ ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━╇━━━━━━━━┩
│ 4f12a8…    │ summarise the openapi spec │ 2026-…  │    200 │      8 │
│ ab39c1…    │ summarise (fork: thorough) │ 2026-…  │    230 │     11 │
└────────────┴────────────────────────────┴─────────┴────────┴────────┘
```

Pass `--no-usage` to hide the columns explicitly. The legacy `--with-usage` flag is preserved as a deprecated no-op alias for one minor cycle (drops in v1.1).

When **all** runs have zero usage (e.g. a fresh DB seeded only with non-LLM nodes), the columns auto-hide so the listing isn't a wall of `—` placeholders.

### 2. `chronos runs show <id>` — per-node tree

```
$ chronos runs show 4f12a8b3
Run 4f12a8b3 — summarise the openapi spec
└─ plan        (router)        step 0
   └─ research (tool)          step 1
      └─ draft  (llm)          step 2   tokens=200  cost=$0.0008  model=claude-3-haiku
         └─ review (llm)       step 3
            └─ finalize (llm)  step 4
```

The per-node `tokens=` / `cost=` / `model=` annotation appears for every `LLM`-kind node that recorded a `Usage`. Sub-cent costs render in the more readable USD form (`$0.0008`) rather than raw cents.

### 3. `chronos diff` — aggregate comparison

The diff verb prints aggregate totals for both runs as a footer:

```
summary: 0 equal  3 changed  0 added  0 removed
A total: 200 tokens, $0.0008    B total: 230 tokens, $0.0011
```

This makes "did my fork actually cost more?" a one-line answer.

### 4. Web UI — RunList page

The `#/runs` route mirrors the CLI table: tokens and cost columns auto-show when at least one run has aggregate usage > 0. Both columns are sortable. The auto-hide rule is identical to the CLI's, so a fresh local DB doesn't render placeholder columns.

### 5. Web UI — TreeView aggregation

The fork-tree page (`#/runs/<id>/tree`) aggregates token/cost across the entire family DAG, so you can see at a glance whether a deeper fork branch has gotten expensive. Each node card in the tree shows its individual usage and the subtree total.

### 6. Web UI — NodeDetails drawer

Click any node anywhere in the Web UI; the right drawer shows its `Usage` envelope verbatim — prompt/completion/reasoning tokens, USD cost, model name.

---

## Where it lives in the database

Token data is stored on the `nodes` table, in the `usage` JSON column. Per-run aggregation is materialised on demand via `chronos.queries.usage._summarise_usage(nodes)` — there is no denormalised cost column on `runs`. This keeps schema migrations cheap and aggregation logic single-sourced.

---

## What we deliberately do NOT do

- **No per-provider price tables.** OpenAI, Anthropic, and others change their token prices regularly. Chronos defers pricing to whatever your adapter recorded — typically what the provider's response envelope reported. If you need to re-price retroactively, write a one-off script over the `usage` column; Chronos itself stays unopinionated.
- **No time-series cost charts.** That's a v1.1+ "observability" arc. The current visibility is per-run, per-node, and per-fork-subtree, which covers the debugging use case.
- **No cost budgets / alerts.** Chronos is a debugger, not an APM. If you need budgets, layer them on the CLI verbs (`chronos runs list --json | jq` is supported).
- **No cost on non-LLM nodes** by default. `TOOL` and `ROUTER` nodes record `usage = None` unless your adapter explicitly imputes one. This is intentional — tool-call cost is provider-specific and we'd rather show "—" than a fabricated zero.

> Out-of-scope items above are tracked in [ADR-029 §Out of scope](decisions/ADR-029-cost-visibility.md#out-of-scope).

---

## Worked example

End-to-end, against the `builtin-minimal` quickstart:

```bash
# 1. Seed a demo DB with two runs that have synthetic usage data.
chronos quickstart

# 2. List runs — see the columns:
chronos runs list

# 3. Drill into one:
chronos runs show <PARENT_ID>

# 4. Diff parent and fork — note the aggregate footer:
chronos diff <PARENT_ID> <CHILD_ID>

# 5. Open the Web UI for the same data:
chronos web --db ~/.chronos/quickstart.db
# Then visit http://localhost:8000 and click into RunList → a run → TreeView.
```

The `builtin-minimal` parent's `draft` node carries `prompt=120 / completion=80 / cost=8¢` and the fork's `draft` is bumped to `prompt=120 / completion=110 / cost=11¢`, so every surface above renders non-trivial data on first run. (Numbers are illustrative — the demo's `metadata.note` says so explicitly.)

---

## Programmatic access

If you'd rather aggregate yourself, the API exposes the raw `Usage` envelopes:

```python
from chronos.store import SqliteStore
from chronos.queries.usage import summarise_usage

with SqliteStore.open("chronos.db") as store:
    nodes = store.get_nodes_for_run(run_id)
    summary = summarise_usage(nodes)
    print(summary.total_tokens, summary.total_cost_usd_cents)
```

The HTTP API surfaces the same: `GET /runs/{id}` includes a `usage_summary` field, and the runs-list endpoint returns one per run.

---

## See also

- [ADR-029 — Cost Visibility decision](decisions/ADR-029-cost-visibility.md) — the design rationale, scope, and out-of-scope list.
- [Concepts → Record](concepts/index.md#1-record) — how `Usage` rides on the `Node` envelope.
- [CLI reference → `runs list`](cli-reference.md) — flags including `--no-usage`.
- [Evaluators](evaluators.md) — combine cost-per-fork with score-per-fork to pick the winner.
