# Chronos Agent ⏳

> **Time-Travel Debugger for Multi-Agent AI Systems.**
> Record every reasoning step. Fork at any node. Diff branches. Compare N timelines side by side.
> See the tokens spent and a score for every fork.

[English](./README.md) · [简体中文](./README.zh-CN.md)

**🤖 100% AI-generated** — every commit, design doc, and architectural decision in this repository is authored autonomously by an AI agent (Hermes Agent / Claude Opus). The human instigator only fired the starting pistol. Phase 4 Arc A — the *N-run compare* surface (slices 1-5) plus the fork-tree visualisation — was shipped end-to-end across rounds R56–R67 in fully autonomous cron slots. Phase 6 RC (R107→R122) — including ADR-029 Cost Visibility (R111) and ADR-030 Evaluation/Scoring (R115) — is being driven the same way under one cron loop.

[![CI](https://github.com/chengfei867/chronos-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/chengfei867/chronos-agent/actions/workflows/ci.yml)
[![golden-verify](https://github.com/chengfei867/chronos-agent/actions/workflows/golden-verify.yml/badge.svg)](https://github.com/chengfei867/chronos-agent/actions/workflows/golden-verify.yml)

---

## What is this?

`chronos-agent` is a debugger for multi-agent AI systems. Think `pdb` + `git` for LLM reasoning:

- **Record** — Transparently capture every node, prompt, tool call, and state transition of an agent run.
- **Fork** — Branch from any recorded node, swap a prompt / tool / model / state value, and re-execute the downstream nodes in a parallel timeline.
- **Diff** — Structurally compare two runs (or a run and one of its forks) — which nodes diverged, which state keys changed, and how.
- **Compare N** — Line up *up to 32* runs in the Web UI or CLI, with an auto-picked centroid pivot, a pairwise distance matrix, and a side-by-side alignment view (Phase 4 Arc A).
- **Fork tree** — When a run has children-of-children, see the whole family DAG as a lane-laid-out tree both in the Web UI and via `chronos tree <root_id>`.
- **Replay** — Step through a historical run interactively in a TUI (`chronos replay <run_id>`) or visually in the Web UI.
- **💰 Cost & Token Tracking** — Token counts and USD cost are first-class, surfaced by default in `chronos runs list`, in the per-node tree of `chronos runs show`, and in the Web UI's RunList table. ([ADR-029](./docs/decisions/ADR-029-cost-visibility.md))
- **🎯 Evaluation & Scoring** — Register a Python callable as an *evaluator*, score any recorded run with `chronos eval run`, and rank N forks by that score with `chronos compare --eval <name>`. Two zero-config built-in evaluators ship out of the box. ([ADR-030](./docs/decisions/ADR-030-evaluation-scoring.md))

## Feature matrix

| Capability                                                          | Milestone             | Status                                                                            |
|---------------------------------------------------------------------|-----------------------|-----------------------------------------------------------------------------------|
| Spikes (capture/fork/diff)                                          | M1.1                  | ✅ all 3 green                                                                     |
| Core four-verb loop (record/replay/fork/diff)                       | M1.*                  | ✅ shipped in v0.1.x                                                               |
| **💰 Cost & Token Tracking — visible by default** (R111, ADR-029)   | v0.9.0+               | ✅ `chronos runs list` shows tokens + cost ¢; Web UI RunList ditto; per-node tree |
| **🎯 Evaluation & Scoring** (R115, ADR-030)                         | v0.9.0+               | ✅ `chronos eval run/list/list-evaluators` + `compare --eval`; 2 built-ins; Score column |
| Adapter contract v2 ([ADR-015] / [ADR-016])                         | v0.2.0a               | ✅ Phase-2 unblocked                                                               |
| **LangGraph adapter**                                               | v0.2.0                | ✅ state-dict paradigm (checkpointer-backed fork)                                  |
| **AutoGen adapter**                                                 | v0.4.0a2              | ✅ message-list paradigm + per-tool `effects_map` override ([ADR-020])             |
| **CrewAI adapter**                                                  | v0.4.0                | ✅ event-bus paradigm, pin `>=0.80,<2.0` ([ADR-021] / [ADR-022])                   |
| **Anthropic Agents SDK adapter**                                    | v0.7.0a1+             | 🚧 alpha — record-only ([ADR-026]); fork in slice 2                                |
| **Linear adapter** (issue tracker as agent input)                   | v0.8.0+               | ✅ ingestion + golden-trace verified                                               |
| Web UI — TreeView + Run Info + playback                             | v0.2.0                | ✅ AntD v6 + ReactFlow v12, zh/en i18n                                             |
| Multi-run family tree + lane layout                                 | v0.2.0                | ✅ R37.5                                                                           |
| Compare: side-by-side diff viewer (UI)                              | v0.2.1                | ✅ R39-A — [ADR-018] "compare" narrative                                           |
| **Effect-aware fork UX** — adapter tags, CLI preview, Web modal     | v0.3.0 → v0.4.0       | ✅ PH3-02 + PH3-03 + PH3-04, see [`docs/guides/forking-safely.md`][forksafely]     |
| **Phase 4 Arc A — N-run compare (slices 1-5)**                      | v0.5.0 → v0.6.0       | ✅ alignment, auto-pivot, matrix ([ADR-024])                                       |
| **Phase 4 Arc A item 2 — `chronos tree` CLI + fork-tree viz**       | v0.6.0                | ✅ family-tree lane layout in CLI + Web UI ([ADR-025])                             |
| `chronos quickstart` + `examples/builtin-minimal/` (R109)           | v0.9.0                | ✅ zero-API-key seed of 2 runs + 1 fork                                            |
| `chronos doctor` env/DB/schema diagnostic (R110)                    | v0.9.0                | ✅ pre-flight check                                                                |
| Onboarding tour, theme + language toggles, bookmarks                | v0.9.0                | ✅ frontend P0 cleanup R112-R114                                                   |
| Release pipeline (semver, tags, changelog)                          | ongoing               | ✅ [`chronos-release-pattern`] skill, 14× validated through R73                    |

[forksafely]: ./docs/guides/forking-safely.md
[ADR-015]: ./docs/decisions/ADR-015-extractor-contract-v2.md
[ADR-016]: ./docs/decisions/ADR-016-adapter-interface.md
[ADR-018]: ./docs/decisions/ADR-018-compare-is-diff.md
[ADR-020]: ./docs/decisions/ADR-020-adapter-tool-node-name-shape.md
[ADR-021]: ./docs/decisions/ADR-021-crewai-adapter.md
[ADR-022]: ./docs/decisions/ADR-022-crewai-version-pin-bump.md
[ADR-024]: ./docs/decisions/ADR-024-multi-pivot-compare.md
[ADR-025]: ./docs/decisions/ADR-025-fork-tree-viz-scope.md
[ADR-026]: ./docs/decisions/ADR-026-arc-b-scope.md

## Quickstart (5 minutes)

```bash
# 1. Install (zero API key needed for the demo).
pip install 'chronos-agent[web]'

# 2. Seed a 2-run, 1-fork demo into ./chronos.db.
chronos quickstart

# 3. List the seeded runs — token + cost ¢ columns are shown by default (ADR-029).
chronos runs list
```

```text
                                                                Runs (2)
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳───────────────────────────────────────────────────┓
┃ id                                   ┃ adapter   ┃ status    ┃ tokens ┃ cost ¢ ┃ task                                              ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇───────────────────────────────────────────────────┩
│ 33333333-3333-4333-8333-333333333333 │ langgraph │ completed │    230 │     11 │ builtin-minimal: forked at draft with tone=formal │
│ 11111111-1111-4111-8111-111111111111 │ langgraph │ completed │    200 │      8 │ builtin-minimal: greet -> draft -> finalize       │
└──────────────────────────────────────┴───────────┴───────────┴────────┴────────┴───────────────────────────────────────────────────┘
```

```bash
# 4. Diff the parent vs. the fork — see exactly which node + state key flipped.
chronos diff 11111111-1111-4111-8111-111111111111 33333333-3333-4333-8333-333333333333

# 5. Score both runs with a built-in evaluator (ADR-030).
chronos eval list-evaluators
chronos eval run 11111111-1111-4111-8111-111111111111 --evaluator output_length_chars
chronos eval run 33333333-3333-4333-8333-333333333333 --evaluator output_length_chars

# 6. Rank the two forks side by side, sorted by that evaluator.
chronos compare 11111111-1111-4111-8111-111111111111 \
                33333333-3333-4333-8333-333333333333 \
                --eval output_length_chars

# 7. Browse it all in the Web UI (RunList → Tokens / Cost / Score columns,
#    TreeView, Compare/Diff, family fork tree).
chronos web
# → http://127.0.0.1:8765 opens automatically
```

That's it — five minutes from `pip install` to a scored, forked, diffed agent run.
See [`docs/getting-started.md`](./docs/getting-started.md) for the full walkthrough,
[`docs/cli-reference.md`](./docs/cli-reference.md) for every command, and
[`docs/decisions/`](./docs/decisions/) for every architectural decision.

## See it in action

The Web UI ships in the `chronos web` command — one binary, zero Node.js required at install time.

**Run list** — every captured run, with **default-on Tokens + Cost** columns (ADR-029) and a **Score** column when evaluators have been run (ADR-030):

![RunList](./docs/assets/screenshot-runs-list.png)

**Single-run reasoning tree** — nodes for every LLM call, tool call, router decision, with token counts and cost:

![TreeView](./docs/assets/screenshot-tree-single-run.png)

**Family tree** — when a run has forks, see all timelines stacked as lanes with cross-lane fork edges:

![Family tree](./docs/assets/screenshot-family-tree.png)

**Compare two runs** — pick any two runs from the list, hit Compare, get a side-by-side diff with an alignment list:

![DiffView](./docs/assets/screenshot-diff-view.png)

## 💰 Cost & Token Tracking (ADR-029)

Every adapter (LangGraph, AutoGen, CrewAI, Anthropic Agents, Linear) emits `Usage` (`prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `cost_usd_cents`, `model_name`) on the nodes it records. R111 (ADR-029) made that data **visible by default**:

- `chronos runs list` shows **`tokens`** and **`cost ¢`** columns whenever the listed runs have any LLM usage. On all-zero databases the columns auto-hide so you don't see a wall of em-dashes.
- `chronos runs show` already renders per-node usage in the node tree.
- `chronos diff` and `chronos compare` aggregate token + cost deltas between runs.
- The Web UI `RunList` page shows the same two columns on the right; the per-node `NodeDetails` panel surfaces a USD-formatted cost.
- Pass `--no-usage` (or `chronos runs list --json` for machine-readable output) to opt out.

The `chronos quickstart` demo seeds *synthetic* but realistic numbers (parent run = 200 tokens / $0.0008, child run = 230 tokens / $0.0011) so the column rendering exercises immediately, no API key required.

## 🎯 Evaluation & Scoring (ADR-030)

R115 (ADR-030) added a *deliberately small* evaluator surface — just enough to answer the central question: *"of the N forks I just generated, which one is best?"*

```python
# Anatomy of an evaluator (chronos.eval.types.Evaluator):
def my_evaluator(run: Run, nodes: list[Node]) -> EvaluationResult:
    final = run.final_state or {}
    return EvaluationResult(
        score=len(final.get("output", "")),
        passed=None,
        rationale=f"len(final_state['output']) = {len(final.get('output', ''))}",
    )
```

Register it under a name and persist its score:

```bash
chronos eval list-evaluators                          # see what's registered
chronos eval run <run_id> -e output_length_chars      # built-in #1 (LLM-free, always works)
chronos eval run <run_id> -e final_state_key_present  # built-in #2 (boolean)
chronos eval list <run_id>                            # show this run's persisted scores
chronos compare <a> <b> <c> --eval output_length_chars
```

The compare table now appends an "Evaluation: `<name>`" row with each candidate's score, passed flag, and rationale. The Web UI `RunList` page surfaces the same data as a sortable **Score** column.

What's *out of scope* for v1.0 (deferred to v1.1+): LLM-as-judge evaluators, dataset-driven evaluation harnesses, leaderboard UI. The schema, registration API, and CLI verb shape are stable.

## Status

**Phase 6 RC (R107 → R122)** is in progress. R107 cut `v0.9.0` GA. R108-R110 polished the CLI surface (rich `--help`, `chronos quickstart`, `chronos doctor`). R111 shipped ADR-029 Cost Visibility full-stack. R112-R114 closed frontend P0 polish. R115 shipped ADR-030 Evaluation/Scoring full-stack. R116 (this round) ships bilingual READMEs + the docs/demo arc preface. R117-R118 follow with a docs site (GH Pages) and ≥3 demo packs. R119 is end-to-end dogfood; R120 cuts `v1.0.0-rc1`. R121 is RC buffer; R122 is final acceptance.

**Earlier**: Phase 4 Arc A — *N-run compare* — shipped at `v0.6.0`. Phase 4 Arc B slice 1 — *Anthropic Agents SDK adapter (record-only)* — alpha at `v0.7.0a1`. Phase 5 — Linear adapter + golden-trace verification — at `v0.8.0`. Three earlier-phase adapters (LangGraph + AutoGen + CrewAI) and the effect-aware fork UX continue to ship unchanged.

Detailed milestones: [`docs/roadmap.md`](./docs/roadmap.md). Design decisions: [`docs/decisions/`](./docs/decisions/). Per-cron-cycle progress: [`progress/`](./progress/).

## Why now?

2026 is the year multi-agent systems go to production. Yet when they fail, the dominant debugging tool is "read the trace and hope you spot it, then rerun the whole thing". There is no `pdb`. There is no `git rebase -i`. That's the gap `chronos-agent` fills — and ADR-029 Cost + ADR-030 Evaluation extend it from "what happened?" to "how much did it cost?" + "which fork was best?".

## Why N-run compare matters (Phase 4 Arc A)

Most agent-observability tooling stops at "show me one trace" or "show me the diff between two traces." But once your prompt-engineering loop kicks in, you have ten variants of the same agent against the same input — and the question is *not* "which two are different" but "which one is the centroid and how far is each variant from it." Phase 4 Arc A built that surface. `chronos compare --auto-pivot run_A run_B run_C ... run_J` picks the centroid for you, lays out a pairwise distance matrix in the terminal (`--matrix`), and the Web UI surfaces it as a heatmap. Pair it with `--eval <name>` and you get a centroid-relative *and* score-ranked view of N forks in one command.

## Why 100% AI?

This is an experiment in **agentic software engineering at full autonomy**. An AI agent is the sole developer — not "copilot" style assistance, but **end-to-end ownership**: research, design, code, docs, ops, releases. Every commit trail, ADR, and progress log is a public record of what AI can build when left alone.

See [`docs/CONTEXT.md`](./docs/CONTEXT.md) — the onboarding document the AI reads at the start of every autonomous cycle.

---

## Repository Layout

```
chronos-agent/
├── README.md                  ← English (you are here)
├── README.zh-CN.md            ← 简体中文
├── pyproject.toml
├── src/chronos/
│   ├── adapters/              ← framework adapters (LangGraph + AutoGen + CrewAI + Anthropic Agents + Linear)
│   ├── api/                   ← FastAPI Web UI backend (/runs, /runs/compare, /runs/compare/auto, /runs/compare/matrix, /runs/{id}/evaluations, …)
│   ├── cli/                   ← `chronos` typer app (runs/diff/fork/replay/web/compare/tree/eval/quickstart/doctor)
│   ├── core/                  ← models, diff engine, auto_pivot, tree
│   ├── eval/                  ← evaluator protocol + 2 built-ins + registry (ADR-030)
│   └── store/                 ← SQLite canonical store (with `evaluations` table)
├── frontend/                  ← Web UI (React + AntD v6 + ReactFlow v12, bundled into the wheel)
├── examples/                  ← runnable demos (no API key required)
│   ├── builtin-minimal/       ← `chronos quickstart` seed (2 runs + 1 fork)
│   ├── linear_pipeline.py     ← record → fork → diff on a 5-node graph
│   └── router_loop.py         ← same, on a graph with loops
├── scripts/
│   ├── seed_demo.py           ← 10-second demo DB (5 runs, 3-gen fork chain)
│   └── dogfood/               ← living-design-doc dogfood scripts (per slice)
├── tests/
│   ├── unit/                  ← 600+ unit tests (duck-typed fakes)
│   ├── integration/           ← real SqliteStore + real LangGraph
│   ├── live/                  ← real-LLM smoke tests, opt-in via CHRONOS_LIVE=1
│   └── spikes/                ← empirical validation scripts (M1.1 + per-adapter + spike20 cost + spike21 eval)
├── docs/
│   ├── assets/                ← README screenshots
│   ├── getting-started.md     ← 5-minute onboarding
│   ├── cli-reference.md       ← every command documented (incl. eval verbs)
│   ├── CONTEXT.md             ← AI agent onboarding entry point
│   ├── adapters/              ← per-adapter install / config / usage / limits
│   ├── research/              ← competitive analysis, feasibility, risks
│   ├── design/                ← user stories, architecture, diagrams
│   ├── decisions/             ← Architecture Decision Records (ADRs)
│   └── roadmap.md
├── progress/                  ← per-cron-cycle summaries
└── CHANGELOG.md
```

---

## Development

```bash
uv sync
uv run pytest            # 745+ tests (live tests skipped without CHRONOS_LIVE=1)
uv run ruff check .
uv run ruff format .
uv run mypy src/         # src is typed; tests are not
```

Frontend rebuild (only when changing `frontend/src/**`):

```bash
cd frontend
npm ci --registry=https://registry.npmmirror.com --include=dev
npm run build            # output goes to frontend/dist/, committed to the repo
```

---

## License

MIT (added on first public release).

---

*🤖 Built autonomously by AI. Overseen by [@chengfei867](https://github.com/chengfei867).*
