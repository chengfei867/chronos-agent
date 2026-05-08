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
- **R1** — Adapter interface as a typed `Protocol`, ≥1 non-LangGraph reference implementation behind a feature flag. *Contract:* ✅ ADR-016 (R26). *Implementation:* ✅ R28 (`src/chronos/adapters/linear/`, zero-dep linear-pipeline reference adapter, 25 unit tests, structural conformance to `LangGraphRecorder` public shape).
- **R2** — Extractor contract formalised. ✅ ADR-015 (R25).
- **R3** — Dogfood triple (record → fork plan emit → fork plan exec) green on LangGraph *and* the Phase-2 reference adapter, in CI. ✅ R29 (`tests/integration/test_dual_adapter_dogfood.py`, 4 tests, 293/293 suite green; surfaced + fixed a real `__chronos_usage__` API gap as a side-effect).
- **R4** — Written "what breaks at multi-framework boundary" risks doc with mitigations. ✅ R27 (`docs/research/multi-framework-risks.md`, 6 risks × description+evidence+mitigation+owner).

### Key milestones
- [x] Phase-2 reference adapter (linear-pipeline adapter conforming to ADR-016 `RecorderProtocol`, R28 — satisfies ADR-014 R1 *implementation* half)
- [x] AutoGen adapter (record-only, ADR-017 sync-wrap strategy, R33 — `src/chronos/adapters/autogen/`, 10 unit tests, structural `RecorderProtocol` conformance. Fork deferred to Phase 3 per ADR-017 §Decision.)
- [ ] Multi-agent reasoning tree representation (concurrent lanes)
- [x] Local HTTP API (`chronos.api.server`, R34-A — FastAPI `build_app(store)` factory with 6 endpoints: `GET /healthz`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/nodes`, `GET /runs/{id}/forks`, `GET /runs/{id}/tree` (neutral reasoning-tree shape with sequential + cross-run fork edges); 17 unit tests; `[project.optional-dependencies].web` group added. `chronos web` command in R34-B.)
- [x] Web UI basics: reasoning tree viewer (ReactFlow), run list, diff viewer (R34-C — `frontend/` Vite + React 19 + TypeScript 5 + `@xyflow/react` v12 SPA; 108KB gzipped bundle committed under `frontend/dist/` via `.gitignore` whitelist so `uv pip install chronos-agent[web]` ships a working viewer with zero npm deps; `/app/*` StaticFiles mount on `build_app(store)` with 503-fallback when bundle missing; `CHRONOS_FRONTEND_DIST` env override; `types.ts` mirrors pydantic `model_dump(mode="json")` field-for-field; hash routing (`#/`, `#/runs/<id>`); `NodeDetails` drawer with tool_input/output + usage + error; landing page gains "🌲 Open Tree Viewer" CTA. Diff viewer still TODO — lists + tree ship, side-by-side run diff deferred to next round.)
- [x] Web UI polish pass: AntD 6 + Framer Motion + i18n (zh default/EN toggle) + help drawer + concept tooltips + 首次引导 Tour + "从头播放" step-playback feature (R36-D — `frontend/src/{main,App}.tsx` rewired with `ConfigProvider` + dark-first theme (`#0d1117` bg + `#58a6ff` accent); 9 new components under `frontend/src/components/` + 3 pages under `pages/` + `usePlayback` hook; AntD zhCN locale + `react-i18next` with `localStorage: chronos.lang` persistence; `HelpDrawer` + `ConceptTip` cover Run/Node/Fork/Adapter/Usage/Thread for non-technical readers; `OnboardingTour` (once per user, `localStorage: chronos.tour.seen.v1`) walks header controls; `ChronosNodeCard` kind-aware color accents (LLM/Tool/Fn/Router/Fork/End) with Lucide icons; `NodeDetails` split into 4 tabs (Identity/I-O/State/Cost) replacing wall-of-JSON; bundle now 1.39 MB raw / 452 KB gzipped (AntD + Framer Motion cost); `scripts/seed_demo.py` seeds 3 demo runs for one-command E2E. 375/375 backend tests green, tsc + vite build clean, E2E smoke verified.)
- [x] `chronos web` command launches local server + opens browser (R34-B — `src/chronos/cli/web.py`, `web_command(host, port, db, no_browser)` with lazy uvicorn import, DI-injectable `run_server_fn` / `open_browser_fn` for testability, `threading.Timer(1.0)` delayed browser-open after uvicorn binds. Dark-themed `/` landing page in `server.py` (zero-JS, zero-build) linking to `/runs` / `/docs` / `/healthz`. 8 unit tests. Bilingual README + `docs/cli-reference.md` updated.)
- [ ] Fork-batch capability for Sam's (persona) counterfactual research
- [ ] Tag v0.2.0

---

## Phase 3 — v0.3 "Production-ready fork" ✅ COMPLETE (R55, v0.4.0)

**Goal**: Make fork reliable for real-world agents. Chronos does **not** sandbox side effects ([ADR-019](decisions/ADR-019-chronos-does-not-sandbox.md) — trust the user's own sandboxing) — instead it classifies effects and warns honestly so users can decide before forking.

**Final duration**: 11 rounds (R43 → R55) across tags v0.3.0 / v0.3.1 / v0.4.0a1 / v0.4.0a2 / v0.4.0. Phase 3 was scoped as "effect-aware fork UX across all shipping adapters". The last item (CrewAI adapter) landed in v0.4.0 (R55) and completes the three-adapter matrix.

### Key milestones
- [x] **Effect-kind instrumentation + honest warnings** (replaces the original "side-effectful tool sandboxing" bullet per ADR-019, landed R43/R44-A/R45-A across v0.3.0 and v0.3.1)
  - [x] ADR-019 "Chronos does not sandbox fork execution" (R43-B)
  - [x] `docs/guides/side-effects.md` user guide, zh/en (R43-C)
  - [x] Adapter `classify_effects()` heuristic + `metadata["effects"]` on every Node (R44-A, v0.3.0)
  - [x] Web UI: per-node effect Tags + amber warning Alert in NodeDetails drawer (R44-A, v0.3.0)
  - [x] CLI `chronos fork plan`: Downstream side-effects preview Panel (R45-A, v0.3.1)
  - [x] Web UI: TreeView → fork-plan modal with effects summary (R46-A → R47, v0.4.0a1)
  - [x] AutoGen adapter + per-tool `effects_map` override (R48-A, v0.4.0a2, [ADR-020])
  - [x] Frontend `EffectTag` shared component + icons (R48-B, v0.4.0a2)
  - [x] CrewAI adapter — scaffold (R52) + version pin bump (R53, [ADR-022]) + real-LLM spike (R54) + pytest-live wrap (R55), [ADR-021]
- [ ] Determinism modes (stable / explore / custom) — deferred to Phase 4
- [ ] Dependency-aware partial fork — deferred to Phase 4
- [ ] Semantic diff (LLM-as-judge) — deferred to Phase 4
- [ ] Generic OTel receiver (Tier-2 adapter) — deferred to Phase 4
- [ ] Plugin system for custom diff / redaction — deferred to Phase 4
- [x] **Tag v0.3.0** (R44-A) + **v0.3.1** (R45-A) + **v0.4.0a1** (R47) + **v0.4.0a2** (R48-C) + **v0.4.0** (R55)

[ADR-020]: decisions/ADR-020-adapter-tool-node-name-shape.md
[ADR-021]: decisions/ADR-021-crewai-adapter.md
[ADR-022]: decisions/ADR-022-crewai-version-pin-bump.md
[ADR-023]: decisions/ADR-023-phase-4-charter-skeleton.md
[n-run-compare]: design/n-run-compare.md

---

## Phase 4 — v0.5+ "Depth & ecosystem"

**Goal**: Now that the three-adapter matrix is stable and effect-aware, go deeper on the *diff/compare/fork-tree* semantics users actually reason with, and broaden the ecosystem surface.

**Charter**: Phase 4 has three candidate arcs (R56 skeleton). **R57 commits to Arc A (Depth) as the active arc** — see [ADR-023] §"Decision (R57 — Arc A committed)". Arc B and Arc C remain deferred.

### 4.1 Depth — fork-tree semantics (priority: **ACTIVE** — Arc A pinned R57)
- [ ] **Multi-run tree comparison UI** — select N runs, render a merged family tree with lane alignment and cross-lane "same node" bridges. Generalises the R39-A two-run compare to N runs. **Design doc: [n-run-compare][n-run-compare] (R57). Impl plan: R58 core / R59 CLI+API / R60 Web (optional) / R61 dogfood.**
- [ ] **Fork-tree visualization** — for a single run with descendants, render the full fork DAG (not just the 2-run diff). R37.5 family-tree was a first step; this is the full thing. Arc A second slice; design doc R62+ gated on R58-R60 results.
- [ ] **Semantic diff (LLM-as-judge)** — for divergent LLM outputs, let the user delegate "are these equivalent?" to a judge model. Adapter-agnostic. Needs an ADR for trust model.
- [ ] **Dependency-aware partial fork** — don't re-execute unaffected subtrees. Needs adapter-level "purity" annotation or heuristic.
- [ ] **Determinism modes** (stable / explore / custom) — seed + temperature policy on fork.

### 4.2 Ecosystem — broader surface (priority: DEFERRED until Arc A ships or external demand)
- [x] **Third adapter: CrewAI** — shipped in v0.4.0 (R49-R55)
- [ ] **Fourth adapter candidate** — options: OpenAI Assistants API v2, Swarm, Anthropic Agents SDK, Letta, LiveKit Agents. Evaluation table lives in [ADR-023] §Arc B; promoted to `docs/research/adapter-4-survey.md` when Arc B reopens.
- [ ] **Vercel AI SDK adapter (TS)** — requires the Python-or-TS decision (out of scope for Phase 4 unless a clear demand signal arrives).
- [ ] **Generic OTel receiver** (Tier-2 adapter for non-LangGraph/AutoGen/CrewAI agents) — catch-all via OTel GenAI semconv.
- [ ] **Jupyter notebook integration** (`chronos.load_run(id)`).
- [ ] **Export to Parquet / OTel JSON** for ML pipelines.
- [ ] **LAN-sharing of traces** for small teams.
- [ ] **Docker image** for reproducible traces.
- [ ] **Public demo / marketing site**.

### 4.3 Plumbing (priority: DEFERRED — demand-driven)
- [ ] Plugin system for custom diff / redaction.
- [ ] Release cadence shift (R55 has validated 12× — pattern is solid).

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
