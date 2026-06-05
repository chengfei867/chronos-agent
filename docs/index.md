# Chronos Agent ⏳

> **Time-Travel Debugger for Multi-Agent AI Systems.**
> Record every reasoning step. Fork at any node. Diff branches. Compare N timelines side by side.
> See the tokens spent and a score for every fork.

[![CI](https://github.com/chengfei867/chronos-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/chengfei867/chronos-agent/actions/workflows/ci.yml)
[![golden-verify](https://github.com/chengfei867/chronos-agent/actions/workflows/golden-verify.yml/badge.svg)](https://github.com/chengfei867/chronos-agent/actions/workflows/golden-verify.yml)

---

## What is this?

`chronos-agent` is a debugger for multi-agent AI systems. Think `pdb` + `git` for LLM reasoning trees:

- **Record** — Transparently capture every node, prompt, tool call, and state transition of an agent run.
- **Fork** — Branch from any recorded node, swap a prompt / tool / model / state value, and re-execute downstream nodes in a parallel timeline.
- **Diff** — Structurally compare two runs (or a run and one of its forks).
- **Compare N** — Line up *up to 32* runs in the Web UI or CLI, with an auto-picked centroid pivot, a pairwise distance matrix, and a side-by-side alignment view.
- **Fork tree** — When a run has children-of-children, see the whole family DAG as a lane-laid-out tree both in the Web UI and via `chronos tree <root_id>`.
- **Replay** — Step through a historical run interactively in a TUI (`chronos replay <run_id>`) or visually in the Web UI.
- **💰 Cost & Token Tracking** — Token counts and USD cost are first-class, surfaced by default in `chronos runs list`, in the per-node tree of `chronos runs show`, and in the Web UI's RunList table. ([ADR-029](decisions/ADR-029-cost-visibility.md), [Cost tracking guide](cost-tracking.md))
- **🎯 Evaluation & Scoring** — Register a Python callable as an *evaluator*, score any recorded run with `chronos eval run`, and rank N forks by that score with `chronos compare --eval <name>`. Two zero-config built-in evaluators ship out of the box. ([ADR-030](decisions/ADR-030-evaluation-scoring.md), [Evaluators guide](evaluators.md))

---

## Five-minute quickstart

```bash
# 1. Install
git clone https://github.com/chengfei867/chronos-agent.git
cd chronos-agent
uv sync

# 2. Seed two runs (one parent + one fork) with synthetic but realistic data:
uv run chronos quickstart

# 3. List them — token + cost columns auto-show:
uv run chronos runs list

# 4. Diff parent vs fork:
uv run chronos diff <PARENT_ID> <CHILD_ID>

# 5. Score them:
uv run chronos eval run <PARENT_ID> --evaluator output_length_chars
uv run chronos compare <PARENT_ID> <CHILD_ID> --eval output_length_chars

# 6. Open the Web UI:
uv run chronos web
# Then visit http://localhost:8000
```

No LLM API key needed — the quickstart uses deterministic synthetic data.

→ Continue with the [Getting started guide](getting-started.md).

---

## Why Chronos?

Existing observability tools (LangSmith, AgentOps, Helicone, Phoenix, Braintrust, Laminar) record agent runs and dashboard them. **Chronos adds three primitives on top**:

| Primitive | What it gives you |
|---|---|
| **Fork** | Re-execute downstream nodes under a one-input change, without re-running the upstream half. |
| **Diff** | Structural comparison of two runs, with auto-detection of fork points and loop alignment. |
| **Compare-N** | Up to 32 runs side-by-side, centroid-pivot, pairwise distance matrix, optional sort by evaluator score. |

All three operate offline against a local SQLite file. No proxy, no relay, no cloud round-trip. You can `scp chronos.db` between machines and the verbs work identically on both ends.

→ See [Concepts](concepts/index.md) for the five-verb mental model.

---

## What's in the docs

- **[Getting started](getting-started.md)** — install, run the quickstart, instrument your first agent.
- **[Concepts](concepts/index.md)** — record / replay / fork / diff / compare in 800 words.
- **[CLI reference](cli-reference.md)** — every verb, every flag.
- **[Cost tracking](cost-tracking.md)** — how `Usage` is captured, surfaced, and aggregated end-to-end.
- **[Evaluators](evaluators.md)** — built-ins, registration patterns, the `compare --eval` workflow.
- **[Adapters](adapters/anthropic_agents.md)** — per-framework setup notes.
- **[Forking safely](guides/forking-safely.md)** — side-effect awareness for `fork`.
- **[Adapter protocol](contracts/adapter-protocol.md)** — implement your own adapter.
- **[FAQ](faq.md)** — quick answers to common questions.
- **[Decisions (ADRs)](decisions/index.md)** — every architectural choice has a one-page rationale.

---

## Status

Chronos is in the **v1.0.0-rc** arc. Phase 6 (R107→R122) is the polish + Cost + Eval round; final acceptance gate is **R122**. The repository is private during the RC phase; public-toggle authority sits with the project owner and lands at the R120 RC1 milestone.

> **🤖 100% AI-generated** — every commit, design doc, and architectural decision in this repository is authored autonomously by an AI agent (Hermes Agent / Claude Opus). The human instigator only fired the starting pistol. See the [`progress/`](https://github.com/chengfei867/chronos-agent/tree/main/progress) directory for the round-by-round operations log.
