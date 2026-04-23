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

## Phase 1 — v0.1 MVP "Single-agent Record & Replay" ✅ COMPLETE (shipped through R25; current tag `v0.1.6`)

**Goal**: First working end-to-end demo — record a LangGraph agent, list runs, inspect a node, replay (read-only).

**Estimated duration**: 6–10 rounds (~2-4 days wall-time)
**Actual**: 25+ rounds. Phase 1 overran the estimate because we (a) pulled forward usage extraction from Phase 2 (ADR-009 → ADR-015), (b) stabilised via three dogfood rounds (R17/R18), (c) reshaped the fork CLI (ADR-008 plan-artifact, ADR-013 exec-frozen), and (d) spent R24–R26 formalising the contracts (ADR-014 entry criteria, ADR-015 extractor contract, ADR-016 adapter interface) before opening Phase 2. The overrun is deliberate technical debt repayment — each extension is traceable to an ADR.

**Phase 1 → Phase 2 gate**: open iff ADR-014's four entry criteria are green. See Phase 2 section below for current status.

### Milestones

#### M1.1 — PoC Spikes (1 round) ✅ DONE (Rounds 1–2)
- [x] Spike 1: LangGraph 5-node agent, checkpointer-based state capture
- [x] Spike 2: Restore from checkpoint with prompt swap, re-execute
- [x] Spike 3: Structural diff of two runs
- [x] Spike outcomes documented in `progress/2026-04-22-round-1.md` and `round-2.md`
      (the original plan called for `spikes-result.md` — merged into per-round progress docs instead)

**Exit criteria**: All 3 spikes pass on a toy LangGraph agent. ✅

#### M1.2 — Project skeleton (1 round) ✅ DONE (Round 3)
- [x] `pyproject.toml` + `uv`-based env
- [x] `src/chronos/` layout (`core`, `adapters`, `cli`, `store`, `api`)
- [x] Ruff + pytest + mypy configured
- [x] GitHub Actions CI (`.github/workflows/ci.yml` — lint + test on push)
- [ ] `make` / `just` dev commands (not shipped; `uv run` covers the gap — de-scoped)

**Exit criteria**: `uv run pytest` green on empty scaffold; CI green. ✅

#### M1.3 — Canonical schema + SQLite store (1–2 rounds) ✅ DONE (Round 3)
- [x] `chronos.store` module with SQLite schema from `architecture.md`
- [x] Pydantic models for `Run`, `Node`, `Fork`, `Tag`
- [x] Migrations approach (versioned SQL in `chronos.store.schema`)
- [x] Unit tests for schema + CRUD
- [x] ADR-003: SQLite schema (covers what "trace schema versioning" was meant to be)

**Exit criteria**: Can write and read arbitrary canonical events. ✅

#### M1.4 — LangGraph adapter (2 rounds) ✅ DONE (Round 4, extended through Round 25)
- [x] `chronos.adapters.langgraph` module
- [x] Callback integration capturing LLM calls + tool calls via checkpointer snapshots
- [x] Checkpointer bridge for state snapshots
- [x] Integration test: record a 5-node LangGraph agent, verify all events persisted
- [x] ADR-004: snapshot→node mapping algorithm
- [x] **Usage extraction** (originally deferred to M2, delivered in Phase 1 ahead of schedule):
      ADR-009 (`usage_extractor` hook), ADR-010 (native extractors),
      ADR-011 (`_jsonable` boundary), ADR-012 (multi-LLM-per-node), consolidated into
      ADR-015 (extractor contract v2, R25).

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

#### M1.7 — Replay (read-only) (1 round) ✅ DONE (Round ~8, stabilised through R17 dogfood)
- [x] `chronos replay <run_id>` — step through nodes interactively in TUI
- [x] Keyboard controls: space/→ = next, ← = previous, q = quit
- [x] Use `rich` for TUI (ADR-007 picked `rich.Live` over `textual` — see ADR-007)

**Exit criteria**: Replay a 20-node run smoothly. ✅

#### M1.8 — Diff (structural) + `chronos fork` CLI (2 rounds) ✅ DONE
- [x] `chronos diff <run_A> <run_B>` — structural alignment by node name (Round 7)
- [x] Summary output + `--verbose` full node-by-node (Round 7)
- [x] `chronos fork plan` — plan-artifact approach instead of `--set-state` (Round ~21, ADR-008)
      with `--emit python` code generation (Round 22, ADR-013 keeps exec frozen as JSON-only)
- [x] Unit tests on known diff fixtures + CLI tests (Round 7, 30 tests)
- [x] ADR-006: diff alignment algorithm (Round 7, Accepted)
- [x] ADR-008: fork CLI plan-artifact (R21)
- [x] ADR-013: fork auto-execution stays frozen (R22)

**Exit criteria**: Meaningful diff of two related runs + CLI-driven fork workflow (Alex's story 1 end-to-end). ✅
(**Note**: the original `--set-state k=v` one-shot form was rejected in R21;
the plan-artifact `fork plan emit → edit → fork plan exec` loop is the shipped interface.)

#### M1.9 — Documentation + Release (1 round) ✅ DONE (v0.1.0 tagged Round ~9; currently at v0.1.6)
- [x] `docs/getting-started.md` — install + first run in 5 minutes
- [x] `docs/cli-reference.md` — all commands
- [x] `examples/` — sample agents
- [x] Update README with real install instructions
- [x] Tag `v0.1.0` through `v0.1.6` (see `CHANGELOG.md`)

**v0.1 exit criteria**: Alex's story (cost regression detection in 5 minutes) is end-to-end walkable using only the CLI. ✅

---

## Phase 2 — v0.2 "Multi-agent + Web UI"

**Goal**: Cover multi-agent reasoning trees and introduce basic Web UI.

**Estimated duration**: 10–15 rounds

**Gated by ADR-014 entry criteria** (all four must be green before any Phase-2 code lands):
- **R1** — Adapter interface as a typed `Protocol`, ≥1 non-LangGraph reference implementation behind a feature flag. *Contract:* ✅ ADR-016 (R26). *Implementation:* pending (target R28–R29).
- **R2** — Extractor contract formalised. ✅ ADR-015 (R25).
- **R3** — Dogfood triple (record → fork plan emit → fork plan exec) green on LangGraph *and* the Phase-2 reference adapter, in CI. ⏳ pending (blocked on R1 impl).
- **R4** — Written "what breaks at multi-framework boundary" risks doc with mitigations. ⏳ pending (target R27).

### Key milestones
- [ ] Phase-2 reference adapter (e.g. AutoGen or a minimal linear-pipeline adapter) conforming to ADR-016 `RecorderProtocol` (satisfies ADR-014 R1 *implementation* half)
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

*Document owner: Hermes Agent. Roadmap is revisited at end of every phase **and whenever drift is detected mid-phase** (lesson from R26: ~18 rounds elapsed between last roadmap refresh and first reality check).*
