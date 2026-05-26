# ADR-029: Cost & Token Tracking — visibility uplift

**Status**: Proposed (drafted by user-decision in chat, R109 close-out, 2026-05-26)
**Date**: 2026-05-26 (Beijing, in chat session — to be ratified by next in-window cron round)
**Supersedes**: nothing
**Depends on**: [ADR-009][ADR-009] (CLI usage rendering — `_RunUsageSummary` and `--with-usage` flag), [ADR-013][ADR-013] (`Usage` schema — `prompt_tokens` / `completion_tokens` / `reasoning_tokens` / `cost_usd_cents`), [ADR-016][ADR-016] (adapter `RecorderProtocol` — adapters already emit `node.usage`)
**Related**: [r120-acceptance.md][acceptance] (Phase 6 RC must-pass list), [ADR-030][ADR-030] (Evaluation/Scoring — companion arc)
**Feeds**: v1.0.0-rc1, README "Cost Tracking" feature row

---

## Context

User-driven discovery in chat (2026-05-26): when asked "is the product feature-rich enough?", initial answer claimed Cost Tracking was a gap. **In-place dogfood inspection proved the opposite** — every layer below the user-facing surface is already wired:

| Layer | Status |
|---|---|
| Pydantic schema (`Usage`, `Node.cost_usd_cents`) | ✅ complete since ADR-013 |
| 4 first-class adapters (LangGraph / Anthropic Agents / CrewAI / AutoGen) emit `node.usage` | ✅ |
| Linear adapter emits usage | ✅ |
| CLI `runs list --with-usage` (token + cost columns) | ✅ behind opt-in flag |
| CLI `runs show` per-node tree displays usage | ✅ via `_fmt_node_usage` |
| CLI `diff` compares per-run aggregate tokens & cost | ✅ |
| Frontend `NodeDetails` panel shows tokens + USD cost | ✅ |
| Frontend `TreeView` aggregates cost across the fork tree | ✅ |
| i18n (zh/en) terminology + ConceptTip glossary entry | ✅ |

The functionality exists. What's missing is **visibility** — the average user starting from `chronos quickstart` sees no token data because:

1. `runs list` hides the tokens / cost columns by default (opt-in `--with-usage`).
2. The `builtin-minimal` quickstart demo seeds nodes with `usage = None`, so even `runs list --with-usage` shows `—`.
3. Neither README nor the docs site mentions Cost Tracking as a feature — competitors (LangSmith, AgentOps, Helicone) advertise it as a top-tier capability, so a cursory comparison places chronos behind despite chronos being at parity.

The fix is small (one cron slot) and high-leverage. This ADR records the scope so the round agent doesn't drift into building a new system on top of the existing one.

---

## Decision

**One slot — slot R110.5 (folded into R111 in the round counter; "R110.5" is shorthand only) — to surface Cost & Token tracking as a first-class user-visible feature**, with zero new schema, zero new adapter work, and zero new dependencies.

Concrete acceptance:

### CLI

- **`chronos runs list` defaults to showing the `tokens` and `cost ¢` columns** when *any* run in the listing has aggregate usage > 0. When all listed runs have zero usage (e.g. fresh DB, no LLM nodes), keep the columns hidden to avoid a wall of `—`s.
- **Add `--no-usage` flag** to opt out (parity with the previous `--with-usage` opt-in, now inverted). Keep `--with-usage` as a deprecated no-op alias for one minor cycle, then drop in v1.1.
- **`chronos runs show` already** displays per-node usage in the node tree — verify visually after the demo seed change (next bullet) and add a spike or unit assertion that the rendered output contains `tokens=` for the LLM node in the seeded `builtin-minimal` parent run.

### Quickstart demo

- **`builtin-minimal` parent run gains realistic but synthetic usage data** on its `draft` (LLM kind) node:
  - `prompt_tokens=120`, `completion_tokens=80`, `reasoning_tokens=0` → `total=200`
  - `cost_usd_cents=8` (i.e. $0.0008) — picked so the `$0.00xx` formatting in `NodeDetails` exercises sub-cent rounding.
  - `model_name="claude-3-haiku-20240307"` (a real public model name, harmless, illustrative).
- The forked **child run's** `draft` node gets a different usage profile (`prompt=120, completion=110, total=230, cost=11`) so the diff and tree-aggregation visualizations have non-trivial data to render.
- The seed file format change is local to the quickstart loader — no on-disk database migration, no API contract change.

### Frontend

- **`RunList` page** (`frontend/src/pages/RunList.tsx`) gains two right-aligned columns: `Tokens` and `Cost (USD)`, populated from the `usage_summary` field returned by the API for each run. Hidden when all rows are zero, mirroring the CLI behaviour.
- The existing `NodeDetails` and `TreeView` cost surfacing **stays as-is** — no rework needed.

### API

- The runs-list endpoint must return aggregate `usage_summary` per run (it may already do so via `_summarise_usage` reuse on the server side; verify and patch if missing).

### Docs

- **README adds a "💰 Cost & Token Tracking" feature row** in the feature matrix, with one sentence + a screenshot of `runs list` showing populated columns.
- **`docs/getting-started.md`** gains a "What you'll see in the demo" section that calls out the token columns explicitly.
- **`docs/cli-reference.md`** updates the `runs list` entry to document the new defaulting behaviour and the `--no-usage` flag.

### Tests

- One new unit test in `tests/unit/test_cli_runs.py`: `runs list` against a DB containing one run with `Usage(prompt=10, completion=20)` shows the `tokens` column with value `30`.
- One new unit test: `runs list` against a DB with all-zero-usage runs **does not** show the tokens column.
- One new spike (`tests/spikes/spike20_quickstart_demo_has_usage.py`) asserts that the `builtin-minimal` quickstart loader populates `node.usage` on at least one node per run.

---

## Out of scope

- New cost-source plumbing — adapters already emit, we do not add per-provider price tables (LangSmith / Helicone manage these dynamically; chronos stays "whatever the adapter recorded").
- Time-series / charting of cost over time — that is a v1.1+ "observability" arc, not a Phase 6 RC concern.
- Cost budgets / alerts — same.
- Token-level streaming visualization in Replay — orthogonal feature.

---

## Consequences

**Positive**

- The largest perceived gap vs. LangSmith disappears in one slot.
- Every layer below the surface was already correct; this slot is pure visibility uplift, lowest possible risk-to-reward.
- README feature parity table becomes accurate.

**Negative**

- The `--with-usage` flag becomes a deprecated no-op for one cycle — minor doc churn.
- Default-on column adds two columns to `runs list` width budget; in narrow terminals this may push the `task` column to wrap. Mitigated by the all-zero-rows hide rule.
- Synthetic usage data in the quickstart demo could be misread as "this is what a real run looks like" — mitigated by a one-line "(synthetic illustrative numbers)" footnote in the seeded run's `metadata.note`.

**Round-counter impact**

This slot extends the R107→R120 13-round Phase 6 RC plan by one round → R107→R121. The user has approved the extension in chat alongside the companion ADR-030 (which adds a second slot, taking the final terminus to R122).

[ADR-009]: ADR-009-cli-usage-rendering.md
[ADR-013]: ADR-013-usage-schema.md
[ADR-016]: ADR-016-recorder-protocol.md
[ADR-030]: ADR-030-evaluation-scoring.md
[acceptance]: ../r120-acceptance.md
