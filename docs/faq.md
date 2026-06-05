# Frequently Asked Questions

Quick answers to the questions that come up first when evaluating Chronos.

---

## What is Chronos for?

A **time-travel debugger for multi-agent AI systems**. Think `pdb` + `git` for LLM reasoning trees. You record an agent's execution end-to-end, replay it step-by-step, fork from any node with one input changed, diff branches structurally, and compare N timelines side-by-side. Token/cost tracking and pluggable evaluators are first-class. See [Concepts](concepts/index.md) for the five-verb mental model.

## How is Chronos different from LangSmith / AgentOps / Helicone / Phoenix / Braintrust / Laminar?

The competitors are **observability** tools (record + dashboard + cost tracking). Chronos is observability plus **fork** plus **diff** plus **compare-N**. The forking primitive is the differentiator — you can re-execute downstream nodes under a mutation without re-running the upstream half. None of the listed competitors expose this surface as of 2026-Q1.

Chronos also runs **fully offline** by default — no proxy, no cloud round-trip, no relay required. The artifact is a single local SQLite file. You can ship runs to a colleague by `scp chronos.db`.

## Do I need an LLM API key to try it?

No. The `chronos quickstart` command seeds two demo runs (one parent + one fork) using deterministic synthetic data — no network, no key. See [Getting started → Quickstart](getting-started.md).

## Which agent frameworks are supported?

Four first-class adapters in v1.0:

| Adapter | Status | Paradigm |
|---|---|---|
| **LangGraph** | ✅ since v0.2.0 | State-dict, checkpointer-backed fork |
| **AutoGen** | ✅ since v0.4.0a2 | Message-list with per-tool override |
| **CrewAI** | ✅ since v0.4.0 | Event-bus (pin `>=0.80,<2.0`) |
| **Anthropic Agents SDK** | 🚧 alpha (record-only in v0.7.0a1; fork lands in v0.9.0+) | Stream-based |

Plus a **Linear** adapter for issue ingestion (treat tickets as agent input). The adapter contract is small ([ADR-016](decisions/ADR-016-adapter-interface.md)) and a fifth adapter is post-1.0 backlog.

## Can I add my own adapter?

Yes — implement the [`RecorderProtocol`](contracts/adapter-protocol.md) ([ADR-016](decisions/ADR-016-adapter-interface.md)) and you're in. The four shipping adapters average ~700 LOC each. The protocol is stable since v0.4.0 and won't break before v2.0.

## Where does Chronos store data?

A single SQLite database, by default `~/.chronos/<project>.db`. Override with `--db <path>` on every CLI verb. Schema is documented in [ADR-003](decisions/ADR-003-sqlite-schema.md); migrations are additive-only and managed under `migrations/` (Alembic-style, but hand-rolled to avoid the Alembic dependency).

## Can I sandbox tool calls during a fork re-execution?

No — Chronos deliberately does **not** sandbox. See [ADR-019](decisions/ADR-019-chronos-does-not-sandbox.md) for the rationale. The two safe paths are:

1. **`effects_map` overrides** ([ADR-020](decisions/ADR-020-adapter-tool-node-name-shape.md)) — declare a tool's "effect tier" (read-only / mutating / external) at adapter setup time, and Chronos warns / blocks fork re-execution of mutating tools by default.
2. **Forks against a test/staging environment** — point your tool calls at a non-prod backend before forking.

The [Forking safely](guides/forking-safely.md) guide walks through the patterns.

## Does Chronos send my data anywhere?

No. Recording is local. The only external network calls are the ones your *agent* already makes (LLM provider, tool APIs). Chronos itself is offline-by-default.

## How do I see token / cost data?

It's on by default. `chronos runs list` shows tokens + cost columns whenever any run has aggregate usage > 0. The Web UI's RunList does the same. Per-node usage shows in `chronos runs show`. See [Cost tracking](cost-tracking.md) for the full surface.

## How do I score a run?

```bash
chronos eval run <run_id> --evaluator output_length_chars
chronos eval list <run_id>
chronos compare <id1> <id2> <id3> --eval output_length_chars
```

Two evaluators ship out of the box; you can register your own as a plain Python callable. See [Evaluators](evaluators.md).

## What does the Web UI show?

A SPA built with React + AntD v6 + ReactFlow v12. Pages:

- **Landing** (`#/`) — onboarding tour, recent runs.
- **RunList** (`#/runs`) — table with task, started time, tokens, cost, evaluator score (each conditionally shown).
- **TreeView** (`#/runs/<id>/tree`) — fork-family DAG with lane layout, per-node usage and score.
- **Replay** (`#/runs/<id>/replay`) — interactive step-by-step replay.
- **Compare** (`#/compare?ids=<csv>`) — side-by-side alignment of N runs.
- **NodeDetails** drawer — clicked from any page, shows the full state, usage, and evaluation history of one node.

Boot the UI with `chronos web --db <path>` (default port 8000).

## Is there a hosted version?

No. Chronos is a local CLI + library. A SaaS layer is **not** v1.0 scope and is currently in the post-1.0 backlog. The local-first design means no vendor lock-in.

## How do I report a bug or request a feature?

GitHub issues at [chengfei867/chronos-agent](https://github.com/chengfei867/chronos-agent/issues). The repo is private during the v1.0 RC phase; public-toggle authority sits with the project owner and lands at R120.

## Why is the project 100% AI-generated?

Chronos is an experiment in autonomous AI development — every commit, design doc, and architectural decision in the repo is authored by an AI agent (Hermes Agent / Claude Opus) under a one-cron-loop SOP. The human instigator only fired the starting pistol. The Phase 4 N-run compare arc + fork-tree visualisation (R56→R67), the Phase 5 GA cut, and the Phase 6 RC arc (R107→R122 including ADR-029 / ADR-030) all shipped autonomously.

This isn't a marketing claim — read [`docs/CONTEXT.md`](https://github.com/chengfei867/chronos-agent/blob/main/docs/CONTEXT.md) for the cron loop's full SOP and [`progress/`](https://github.com/chengfei867/chronos-agent/tree/main/progress) for the round-by-round operations log.

## What versions of Python do you support?

3.11+. Older Pythons are not tested or targeted; the type-system features (PEP 695 generics, `match` statements, exception groups) are used liberally. See [ADR-001](decisions/ADR-001-language.md).

## Can I use it with `pip` instead of `uv`?

Yes — `pip install -e .` works. We use `uv` in the docs because it's faster and cleaner for the contributor flow. Both produce the same `chronos` CLI.

## Where do I read the architectural decisions?

[Decisions (ADR) index](decisions/index.md) — every architectural choice has an ADR, numbered ADR-001 through ADR-030. Each one is a single page with Status / Context / Decision / Out-of-scope / Consequences.

---

If your question isn't here, open an issue or check the [getting-started guide](getting-started.md) — it covers 90% of the introduction-time confusions.
