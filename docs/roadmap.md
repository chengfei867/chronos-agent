# Roadmap — Chronos Agent

**Last updated**: 2026-04-22 (Round 1 — post-research)

> This roadmap has been refined after completing Phase 0 research.
> Each phase lists concrete deliverables, exit criteria, and estimated rounds (4-hour cron cycles).

---

## Phase 0 — Research & Design ✅ (complete end of Round 1)

**Goal**: Turn idea into documented, falsifiable engineering spec.

**Deliverables**:
- [x] `docs/CONTEXT.md` — Onboarding doc for future rounds
- [x] `README.md` — Bilingual public intro
- [x] `docs/research/competitors.md` — 20+ competitors analyzed across 4 tiers
- [x] `docs/research/feasibility.md` — 4 hard questions answered with approach
- [x] `docs/research/risks.md` — Risk register with top-5 prioritization
- [x] `docs/design/user-stories.md` — 4 personas, 4 stories, CLI + Web UI walkthroughs
- [x] `docs/design/architecture.md` — Layered architecture + Mermaid diagrams + data model
- [x] `docs/decisions/ADR-000-template.md` — ADR template
- [x] `docs/decisions/ADR-001-language.md` — Python chosen
- [x] `docs/roadmap.md` — This file

**Exit criteria**: All deliverables merged on `main`. ✅

---

## Phase 1 — v0.1 MVP "Single-agent Record & Replay"

**Goal**: First working end-to-end demo — record a LangGraph agent, list runs, inspect a node, replay (read-only).

**Estimated duration**: 6–10 rounds (~2-4 days wall-time)

### Milestones

#### M1.1 — PoC Spikes (1 round)
- [ ] Spike 1: LangGraph 5-node agent, checkpointer-based state capture
- [ ] Spike 2: Restore from checkpoint with prompt swap, re-execute
- [ ] Spike 3: Structural diff of two runs
- [ ] Write `progress/spikes-result.md` — any spike failure triggers ADR

**Exit criteria**: All 3 spikes pass on a toy LangGraph agent.

#### M1.2 — Project skeleton (1 round)
- [ ] `pyproject.toml` + `uv`-based env
- [ ] `src/chronos/` layout (`core`, `adapters`, `cli`, `store`)
- [ ] Ruff + pytest + mypy configured
- [ ] GitHub Actions CI (lint + test on push)
- [ ] `make` or `just` dev commands

**Exit criteria**: `uv run pytest` green on empty scaffold; CI green.

#### M1.3 — Canonical schema + SQLite store (1–2 rounds)
- [ ] `chronos.store` module with SQLite schema from `architecture.md`
- [ ] Pydantic models for `Run`, `Node`, `Fork`, `Tag`
- [ ] Migrations approach (simple versioned SQL scripts)
- [ ] Unit tests for schema + CRUD
- [ ] ADR-002: trace schema versioning

**Exit criteria**: Can write and read arbitrary canonical events.

#### M1.4 — LangGraph adapter (2 rounds) ✅ DONE (Round 4)
- [x] `chronos.adapters.langgraph` module
- [x] Callback integration capturing LLM calls + tool calls (state snapshots via checkpointer — LLM call granularity deferred to M2 when LangGraph exposes usage)
- [x] Checkpointer bridge for state snapshots
- [x] Integration test: record a 5-node LangGraph agent, verify all events persisted
- [x] ADR-004: snapshot→node mapping algorithm (side-effect policy deferred to Phase 2)

**Exit criteria**: Recording a LangGraph run captures >95% of meaningful events. ✅

#### M1.5 — Fork primitive (adapter-level) ✅ DONE (Round 5)
> **Note**: Original roadmap ordering had Fork as M1.8 and CLI as M1.5. After shipping M1.4 we realised the fork primitive is the killer feature and shouldn't wait behind 3 milestones of CLI/replay/diff. Promoted to M1.5; CLI renumbered to M1.6. See `progress/2026-04-23-round-5.md` + ADR-005.
- [x] `LangGraphRecorder.fork(graph, *, parent_run_id, at_node_id, overrides, child_thread_id, reason)` context manager
- [x] Snapshot restore via `graph.update_state(cfg, values, as_node=X)`
- [x] Re-execute downstream nodes with edits applied
- [x] Tag forked run with lineage (cross-Run `parent_node_id`, `Fork` row in `forks` table)
- [x] Unit tests (9 duck-typed) + integration test (spike-1 5-node graph, fork at research, assert `final_a != final_b`)
- [x] ADR-005: fork semantics

**Exit criteria**: User can programmatically fork a recorded run and produce a divergent child run with persisted lineage. ✅ (CLI `chronos fork` is M1.8 — the adapter layer is done; CLI wiring lands then.)

#### M1.6 — CLI: runs list / show + forks show (1 round) ✅ DONE (Round 6)
- [x] `chronos runs list [--limit N] [--json]`
- [x] `chronos runs show <id> [--json]` — node tree
- [x] `chronos forks show <fork_id> [--json]` — parent/child + overrides
- [x] Pretty `rich` output + `--json` flag
- [x] CLI integration tests (typer `CliRunner`) — 20 tests, full matrix

**Exit criteria**: Users can inspect any recorded run or fork from the terminal without writing Python. ✅

#### M1.7 — Replay (read-only) (1 round)
- [ ] `chronos replay <run_id>` — step through nodes interactively in TUI
- [ ] Keyboard controls: space/→ = next, ← = previous, q = quit
- [ ] Use `rich` or `textual` for TUI

**Exit criteria**: Replay a 20-node run smoothly.

#### M1.8 — Diff (structural) + `chronos fork` CLI (2 rounds)
- [ ] `chronos diff <run_A> <run_B>` — structural alignment by node name
- [ ] Summary output + `--verbose` full node-by-node
- [ ] `chronos fork <run> --at <node> --set-state k=v` — CLI wrapper on M1.5 primitive
- [ ] Unit tests on known diff fixtures + CLI tests
- [ ] ADR-006: diff alignment algorithm

**Exit criteria**: Meaningful diff of two related runs + CLI-driven fork workflow (Alex's story 1 end-to-end).

#### M1.9 — Documentation + Release (1 round)
- [ ] `docs/getting-started.md` — install + first run in 5 minutes
- [ ] `docs/cli-reference.md` — all commands
- [ ] `examples/` — 2 sample agents
- [ ] Update README with real install instructions
- [ ] Tag `v0.1.0`

**v0.1 exit criteria**: Alex's story (cost regression detection in 5 minutes) is end-to-end walkable using only the CLI.

---

## Phase 2 — v0.2 "Multi-agent + Web UI"

**Goal**: Cover multi-agent reasoning trees and introduce basic Web UI.

**Estimated duration**: 10–15 rounds

### Key milestones
- [ ] AutoGen adapter (ADR-005 on adapter interface)
- [ ] Multi-agent reasoning tree representation (concurrent lanes)
- [ ] Local HTTP API (`chronos.api.server`)
- [ ] Web UI basics: reasoning tree viewer (ReactFlow), run list, diff viewer
- [ ] `chronos web` command launches local server + opens browser
- [ ] Fork-batch capability for Sam's (persona) counterfactual research
- [ ] Tag v0.2.0

---

## Phase 3 — v0.3 "Production-ready fork"

**Goal**: Make fork reliable for real-world agents.

**Estimated duration**: 10–20 rounds

### Key milestones
- [ ] Side-effectful tool sandboxing (ADR-006; use E2B or Modal)
- [ ] Determinism modes (stable / explore / custom)
- [ ] Dependency-aware partial fork (don't re-execute unaffected subtree)
- [ ] Semantic diff (LLM-as-judge for divergent responses)
- [ ] Generic OTel receiver (Tier-2 adapter for non-LangGraph/AutoGen agents)
- [ ] Plugin system for custom diff / redaction
- [ ] Tag v0.3.0

---

## Phase 4 — v0.4+ "Ecosystem"

**Goal**: Expand ecosystem, plug into team workflows.

### Candidate items (no order yet)
- [ ] CrewAI adapter
- [ ] Vercel AI SDK adapter (TS)
- [ ] Jupyter notebook integration (`chronos.load_run(id)`)
- [ ] Export to Parquet / OTel JSON for ML pipelines
- [ ] LAN-sharing of traces for small teams
- [ ] Docker image for reproducible traces
- [ ] Public demo / marketing site

---

## Phase 5+ — v1.0 and Beyond (Vague on purpose)

- Cloud-hosted option (opt-in SaaS)
- Team features (shared trace libraries, comments, RBAC)
- Pricing / commercial model experiments

---

## Cross-Phase Commitments

1. **Every PR/commit** updates `progress/<date>-round-N.md`
2. **Every external decision** gets an ADR before code lands
3. **No phase exits** without dogfood: Hermes Agent must itself use the newly shipped capability in a subsequent round
4. **Risk register** (`docs/research/risks.md`) reviewed at every phase gate
5. **Schema evolution** always backwards-compatible within a minor version

---

## Retrospectives

Each phase ends with:
- `progress/retro-phase-<N>.md` — what went right, what went wrong, what to change
- Update to `docs/CONTEXT.md` if any learnings change the project's north star

---

*Document owner: Hermes Agent. Roadmap is revisited at end of every phase.*
