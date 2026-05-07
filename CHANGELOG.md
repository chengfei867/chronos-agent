# Changelog

All notable changes to Chronos Agent are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added (R54 — spike13 real-LLM CrewAI smoke)

- **`tests/spikes/spike13_crewai_tool_effects.py`** (new, ~470 lines) — real-LLM end-to-end smoke for the R52 CrewAI adapter scaffold against CrewAI 1.14.3 + baidu-int OneAPI `GLM-5`. Builds a 2-agent crew (investigator + summarizer) with three effect-tagged tools (`fetch_weather_api` → `network`, `read_file` → `fs`, `query_db` → `db`), drives it through `CrewAIRecorder.record()`, and asserts F1–F6: (F1) `scoped_handlers()` CM exit leaves no handler leak, (F2) >=4 nodes recorded — actual run produced 13, (F3) tool node `effects=['network']` via the R44-A keyword classifier, (F4) all LLMCallCompleted nodes carry non-zero `Usage.prompt_tokens + completion_tokens`, (F5) `id(crew)` preserved pre/post (ADR-016 A5), (F6) `chronos runs list` + `chronos runs show` exit 0 against the live-recorded SQLite DB. Standalone script (not a pytest) due to 15–60 s wall-clock and real-LLM network dependency — R55 P0 will wrap it into `tests/live/test_crewai_smoke.py` with `@pytest.mark.live` + `CHRONOS_LIVE=1` gate.
- **R52 scaffold survives real traffic with zero code changes.** ADR-021 §D1–§D7 empirically validated on CrewAI 1.14.3 + real LLM. Only one tool fires per run (LLM chooses one for the given question); full 3-way classifier coverage remains in `tests/unit/test_effects.py` (R44-A pure-function tests).
- **OneAPI + CrewAI recipe discovered:** use `LLM(provider="openai", model="GLM-5", base_url=..., api_key=...)` — **not** `model="openai/GLM-5"`. The `openai/` prefix routes through LiteLLM's native-provider constants table, which rejects non-OpenAI model names and falls back to LiteLLM (not installed in this environment). Explicit `provider="openai"` bypasses the constants check and routes to CrewAI's native `OpenAICompletion` client, which speaks OneAPI's `/v1/chat/completions` cleanly. Captured in the spike docstring and CONTEXT §5 OneAPI recipes block.
- Gate: 474 passed / 2 skipped / 94% coverage (no pytest delta — spike13 is a standalone script). `mypy src` clean (29 files). `ruff check` + `ruff format --check` clean (75 files). Ships with v0.4.0 non-alpha once R55 P0 (pytest-live wrap) lands.

### Documentation (R54 — promote CrewAI event-bus characterization to research doc)

- **`docs/research/r51-crewai-event-bus-characterization.md`** (new, ~240 lines) — consolidated research note stitching the three layers of CrewAI event-bus empirical evidence against ADR-021's D1–D8 claims: spike12 (synthetic 8-event probe, CrewAI 0.80+) + spike13a (1.14.3 surface probe) + spike13 (real-LLM end-to-end). Includes a claims-vs-empirics table: D1–D7 all validated by both synthetic and real-LLM traffic; D8 (pin `<1.0`) was the only claim overturned and was explicitly labelled pre-emptive in ADR-021 — ADR-022 (R53) revised it to `<2.0`. Mirrors the `r48a-autogen-tool-effects.md` pattern (numbered by the work it describes, not the round that published it — hence `r51-*` even though R54 wrote it). Documents known gaps (single-tool live coverage, no `kickoff_async` or agent-level events or fork probe, LiteLLM fallback out of scope) for future rounds.

### Changed (R53 — ADR-022: CrewAI pin upper bound `<1.0` → `<2.0`)

- **`docs/decisions/ADR-022-crewai-version-pin-bump.md`** (new, ~250 lines) — revises ADR-021 §D8. CrewAI shipped 1.x during Phase 3 (environment already has 1.14.3 installed); the R52 pin `<1.0` was blocking any resolver that saw 1.x. `tests/spikes/spike13a_crewai14_event_bus_probe.py` (new, ~160 lines, no real LLM) probes 1.14.3's event-bus surface — `crewai_event_bus`, `scoped_handlers()`, `flush(timeout=...)`, `on(EventType)(handler)`, `ToolUsage*/LLMCall*/Task*/CrewKickoffCompleted` imports, end-to-end `CrewAIRecorder.record()` CM with stubbed crew + synthetic event — and confirms CrewAI 1.x is a **source-compatible superset** of 0.80+. The R52 scaffold needs no surgery.
- **`pyproject.toml [project.optional-dependencies].crewai`** — `crewai>=0.80,<1.0` → `crewai>=0.80,<2.0` with an inline comment pointing at ADR-022 for rationale.
- **`src/chronos/adapters/crewai/__init__.py::_CrewAIAdapter.version_constraint`** — `">=0.80,<1.0"` → `">=0.80,<2.0"`. Class docstring updated.
- **`src/chronos/adapters/crewai/recorder.py`** — the `ImportError → AdapterError` hint string for missing `crewai` now reads `crewai>=0.80,<2.0` to match the live pin.
- `test_adapter_crewai.py::test_constraint_declared` stays green — it asserts the floor (`"0.80" in version_constraint`), not the ceiling, so the pin bump is drop-in.
- Gate: 474 passed / 2 skipped / 94% coverage (no test delta). `mypy src` clean (29 files). `ruff check` + `ruff format --check` clean. Ships with v0.4.0 non-alpha once R54 P0 (real-LLM smoke, formerly R53 P0) is green.

### Added (R52 — CrewAI adapter scaffold)

- **`src/chronos/adapters/crewai/`** (new package, ~840 lines) — CrewAI adapter scaffold implementing ADR-021 decisions D1–D8. `CrewAIRecorder.record()` is a sync context manager that subscribes to `crewai_event_bus` inside `scoped_handlers()` (D1, auto-detach on exit), buffers node-building work in a `threading.Lock`-protected list (D2, handles the `ThreadPoolExecutor` dispatch discovered in spike12 §F4), and drains to `SqliteStore` in a single transaction after `crewai_event_bus.flush(timeout=flush_timeout_s)` (D1 barrier). Handlers are wired for the seven canonical event classes (`Task{Started,Completed}Event`, `ToolUsage{Started,Finished}Event`, `LLMCall{Started,Completed}Event`, `CrewKickoffCompletedEvent`); `CrewKickoffCompletedEvent` import is tolerated as optional because it has moved across CrewAI minor versions.
- **Three-segment `node_name` per ADR-020 / ADR-021 §D3** — tool events: `{agent_role}:{EventClassName}:{tool_name}`; LLM events: `{agent_role}:{EventClassName}:{call_id}`; task events: `{agent_role}:{EventClassName}:{task_name}`; end: `*:{EventClassName}:kickoff`. The R44-A effects classifier only fires on TOOL-kind nodes, so LLM/Task/End identity-token segments are classifier-inert by construction.
- **`crewai_adapter` singleton** — module-level `AdapterProtocol` instance (ADR-016 P2, R32-B convention). `usage_extractor` channel is deliberately unsupported per ADR-021 §D7 (CrewAI exposes `usage` directly on `LLMCallCompletedEvent`); passing a non-None value raises `AdapterError`. Unknown `**adapter_specific` kwargs also raise `AdapterError` so typos are loud.
- **`fork()` raises `AdapterError`** — record-only parity with AutoGen's R33-A stance. CrewAI fork is tracked as an ADR-021 follow-up.
- **`pyproject.toml`** — adds `[project.optional-dependencies] crewai = ["crewai>=0.80,<1.0"]`, not pulled into required deps. Lower bound is where `scoped_handlers()`, `Future`-returning `emit()`, and top-level `tool_name` / `agent_role` are all stable; upper bound pre-empts CrewAI's pre-1.0 event-schema churn.
- **`tests/unit/test_adapter_crewai.py`** (new, 711 lines, 32 tests) — duck-typed unit suite: handler semantics, buffer/drain invariants, `ThreadPoolExecutor(max_workers=4)` rapid-fire regression test verifying same-class events aren't dropped under contention (ADR-021 follow-up F4 fence), end-to-end record CM via a `_FakeEventBus` stand-in, `fork()` deferred-error behaviour, `AdapterProtocol` structural conformance, factory kwarg validation, and `node_name` builder edge cases. Zero `import crewai` — runs without the optional dep installed.

### Fixed (R52 — `tests/unit/test_cli.py` regression under click/typer upgrades)

- **`tests/unit/test_cli.py`** — `CliRunner()` → `CliRunner(mix_stderr=False)` at module level so tests that read `result.stderr` on missing-DB / missing-run paths keep working under `click>=8.2`, which flipped the default to `mix_stderr=True` (raises `ValueError` on `result.stderr` access otherwise). `test_cli_help_default` drops the `exit_code == 2` assertion because `typer>=0.22`'s `no_args_is_help` now exits 0 and prints help to stdout; the help-text assertion remains as the load-bearing check. Version-agnostic instead of pinning `click<8.2` / `typer<0.22`. This bug was pre-existing on R50's tip (`b86d163`) — R51 surfaced it, R52 fixes it.

- Gate: 474 passed / 2 skipped / 94% coverage (+32 vs R51 baseline, all CrewAI scaffold). `mypy src` clean (29 files, +2 vs R51). `ruff check` + `ruff format --check` clean. Ships with the next non-alpha release.

### Docs (R51 — ADR-021 CrewAI adapter interface)

- **`docs/decisions/ADR-021-crewai-adapter.md`** (new, 349 lines) — codifies the CrewAI adapter design based on the `spike12_crewai_events.py` empirical findings (F1–F6). Event-bus recorder via `crewai_event_bus.scoped_handlers()`, `threading.Lock` + list buffer with `flush(timeout=...)` barrier to handle CrewAI's `ThreadPoolExecutor` dispatch, three-segment `node_name` per ADR-020 (`{agent_role}:{EventClassName}:{tool_name}`), sync-first `Crew.kickoff` (no ADR-017 asyncio wrap — CrewAI only uses async for opt-in `kickoff_async`), default `kind_map` covering `{Task*, ToolUsage*, LLMCall*, CrewKickoffCompleted}`, `usage_extractor` callback unsupported (raises `AdapterError`), version pin `crewai>=0.80,<1.0`. 4 rejected alternatives (listener-class subclassing, monkey-patch `kickoff`, force-sync dispatch, inherit ADR-017). 5 follow-ups tracked including R52 scaffold and R53 real-LLM smoke.
- **`tests/spikes/spike12_crewai_events.py`** — cosmetic `ruff format` sweep (3 hunks — assertion-message string joins and redundant f-string wraps). Zero behaviour change; F1–F6 still all pass.
- No source code, schema, API, CLI, or frontend change. Ships with the next non-alpha release (v0.4.0).

### Docs (R50 — LangGraph kind_map warning + fork-modal screenshot refresh)

- **`src/chronos/adapters/langgraph.py`** — `LangGraphRecorder.__init__` docstring gains a prominent `.. warning::` block explaining that un-mapped nodes default to `NodeKind.FN`, which silently short-circuits the Phase 3 effects classifier to `effects=[]`. Users who rely on fork-modal effect annotation MUST supply `kind_map` entries marking any I/O-doing node as `NodeKind.TOOL`. Cross-references `docs/research/r49-langgraph-adr020-audit.md` (spike 11). No code or behaviour change — docstring only.
- **`docs/images/fork-modal/{01,02,03}.png`** — all three fork-plan-modal screenshots re-captured against v0.4.0a2. They now show the R48-B effect-tag badge icons (Brain / Globe / HardDrive / Database / ExternalLink) rather than the R47-A plain-text tags. Capture recipe unchanged; seed script `scripts/seed_r47a_effects.py` reused as-is.
- Gate unchanged: 442 passed / 2 skipped / 94% coverage. No version bump — ships with the next non-alpha release.

## [0.4.0a2] — 2026-04-27 (Round 48-A + Round 48-B)

**Theme**: **Phase 3 UX polish** — two small-footprint rounds bundled into one alpha cut. R48-A fixes a silent classifier regression in the AutoGen adapter (tool-event `node_name`s now carry the function name, so PH3-02 effect classification actually fires on AutoGen runs) and codifies ADR-020 so future message-based adapters can't repeat the mistake. R48-B lifts the fork-safety UX from "functional" to "scannable" by giving every effect tag a lucide icon badge and extracting a shared `EffectTag` frontend component. Pure frontend + adapter-internal changes; schema, API, and CLI contracts unchanged from v0.4.0a1.

### Added (R48-B — Effect-tag badge icons)

- **`frontend/src/components/NodeDetails.tsx`** — effect tags in the node-details drawer and the fork-plan modal now render with a small leading lucide icon per family: `llm → Brain`, `network → Globe`, `fs → HardDrive`, `db → Database`, `external → ExternalLink`. Unknown tags fall back to plain text (no icon) so adapter authors who invent new effect families don't break rendering.
- **`EffectTag` component** — extracted as a named export from `NodeDetails.tsx` and reused in `ForkPlanModal.tsx` so the drawer, the plan modal tag-count histogram, and the dangerous-sample rows all share one rendering path. The modal's `dangerous_samples` list previously showed tags as a single comma-separated text string; it now shows one icon-bearing chip per tag.
- Color palette unchanged (purple/orange/gold/volcano/red). Schema and API responses unchanged. Pure frontend change; backend tests unaffected (442 pass / 2 skip, 94% coverage).

### Fixed (R48-A — AutoGen effects classifier blind on tool events)

- **`src/chronos/adapters/autogen/recorder.py`** — tool event `node_name`s now embed the FunctionCall name as a third segment: `{source}:{EventClass}:{tool_name[+tool_name...]}` (e.g. `coder:ToolCallExecutionEvent:fetch_weather_api`). Previously the recorder emitted only `{source}:{EventClass}` with no tool-name signal, so the PH3-02 effects classifier's keyword regexes matched zero patterns and **every AutoGen tool node silently got `effects=[]`**. Phase 3's fork-safety warning pipeline was effectively blind on AutoGen in v0.3.0 through v0.4.0a1. LangGraph was fine because graph-level node names are already function-shaped.
- **4 new unit tests** in `tests/unit/test_adapter_autogen.py` cover the new shape: single tool, parallel tools (joined with `+`), fallback when name is unextractable, and per-tool `effects_map` override.
- **`tests/spikes/spike10_autogen_tool_effects.py`** — reproducible real-LLM spike (229 lines) that drove a `RoundRobinGroupChat` through three tools (`fetch_weather_api`, `read_file`, `query_db`) against OneAPI/Claude Opus 4.7 and verified the classifier fires correctly post-fix.
- **`docs/research/r48a-autogen-tool-effects.md`** — investigation note (162 lines) with pre-fix / post-fix classifier output.

### Added (R48-A)

- **`docs/decisions/ADR-020-adapter-tool-node-name-shape.md`** — codifies the three-segment convention `{source_or_agent}:{Kind_or_ClassName}:{tool_name[+tool_name...]}` for all message-based adapters. Graph-based adapters (LangGraph) whose `node_name` is already function-shaped are exempt.
- **`docs/guides/forking-safely.md` §6** — new bilingual section on per-tool `effects_map` overrides, with a "Discovery path" debug snippet for users whose overrides aren't firing.

### Breaking (soft)

- **AutoGen `effects_map` keys targeting the pre-R48-A two-segment shape become silent no-ops.** E.g. `{"coder:ToolCallExecutionEvent": ["external"]}` now matches zero nodes. Migration: inspect `node.node_name` on a recent run and update keys to the three-segment shape. Existing code that relied on effect classification working on AutoGen at all didn't, so very little real-world code should hit this path.

## [0.4.0a1] — 2026-04-26 (Round 46-A + Round 46-B + Round 47-A + Round 47-B)

**Theme**: **Phase 3 fork-safety bundle** — Web UI fork-from-tree modal (PH3-04), Phase 3 charter sign-off, three publishable dogfood screenshots, and the first full-length user-facing guide `docs/guides/forking-safely.md` explaining when Chronos warns you vs. stays silent and why it deliberately doesn't sandbox. This is an **alpha** release because R48+ may extend the Phase 3 story (AutoGen adapter rewrite, effect-tag badge redesign). Everything shipped here is production-shaped; the alpha label only reserves room for follow-ons.

### Added (R46-A — Web UI fork modal, PH3-04)

- **`/runs/{run_id}/nodes/{node_id}/fork-plan` endpoint** — new FastAPI route in `chronos.api.server`. Returns `{plan, effects_summary}` where `plan` is the JSON `ForkPlan.to_dict()` payload (schema marker `chronos_fork_plan_version=1`) and `effects_summary` matches the CLI's R45-A aggregator: `{total, dangerous_count, tag_counts, dangerous_samples}`. Wraps the same pure helpers (`build_plan`, `build_effects_summary`) the CLI uses; no behavioral divergence.
- **`ForkPlanModal` React component** (`frontend/src/components/ForkPlanModal.tsx`) — AntD Modal with three sections: plan JSON viewer, downstream count + tag-count histogram, orange Alert when `dangerous_count > 0` listing the sample `(step, name, tags)` rows. Green Alert when downstream is clean, neutral message when the fork targets the last node of the run.
- **"Fork here" entry point** — TreeView node right-drawer now has a "Fork here" button that opens the modal with the current node pre-selected. Drawer stays open so you can keep browsing node details while the modal is up (intentional; matches how users actually decide).
- **i18n keys** — full `forkModal.*` section in `frontend/src/i18n/{zh,en}.ts`.

### Added (R46-B — Phase 3 charter sign-off)

- **`docs/roadmap.md` Phase 3 charter** — commit `93b76fd` rewrote the roadmap's Phase 3 criteria to match what actually shipped: ADR-019 (Chronos does not sandbox), effect-aware UX, fork-plan CLI preview, Web modal. The old "side-effectful tool sandboxing" bullet was replaced with "Effect-kind instrumentation + honest warnings" crediting R43/R44-A/R45-A.

### Added (R47-A — dogfood screenshots for the fork modal)

- **`docs/images/fork-modal/01-warning.png`** — worst-case warning modal: 4 dangerous downstream nodes out of 5 total, all 4 family tags present (db, network, fs, external). Orange Alert, concrete sample rows.
- **`docs/images/fork-modal/02-safe-pure-llm.png`** — happy path: 3 downstream nodes, 0 dangerous, green Alert "none carry dangerous tags (per ADR-019)".
- **`docs/images/fork-modal/03-safe-last-node.png`** — edge case: forking at the last node of a run, 0 downstream, green Alert "This is the last node of the run — nothing downstream to re-run."
- **`scripts/seed_r47a_effects.py`** — reproducible seed script (197 lines) that creates the three runs the screenshots came from. Run with `uv run python scripts/seed_r47a_effects.py --db dogfood.db` to regenerate.

### Added (R47-B — `docs/guides/forking-safely.md`, 391 lines, bilingual)

- **English + 中文 sections** explaining Chronos's three-tier safety model: adapter-level effect tags (PH3-02), `chronos fork plan` CLI preview panel (PH3-03), Web UI fork modal warning banner (PH3-04).
- **TL;DR decision table** up front: "I want to fork — what does Chronos check for me?" → maps user intent to which safety layer covers it.
- **"Why Chronos doesn't sandbox"** section cross-linking [ADR-019](../decisions/ADR-019-chronos-does-not-sandbox.md) and [ADR-013](../decisions/ADR-013-fork-auto-execution-stay-frozen.md).
- **README pointer** — `README.md` Phase 3 row now links to this guide via `[forksafely]: ./docs/guides/forking-safely.md` reference link.

### Notes

- R45-A's `chronos info` status line bumped to `v0.4.0a1` + headline "fork modal + forking-safely guide".
- Test suite **438 pass / 2 skip** (no new tests this release — all four rounds were UI/docs).
- `ruff check`, `ruff format --check`, `mypy src/` all green.

## [0.3.1] — 2026-04-25 (Round 45-A)

**Theme**: **Phase 3 on-ramp PH3-03** — the `chronos fork plan` CLI now previews which **dangerous downstream nodes** a fork would re-execute. Before this release, users got effect tags in the Web UI (v0.3.0) but the CLI fork preview was silent about downstream risk. v0.3.1 closes that gap.

### Added (R45-A — Fork-plan side-effects preview)

- **`build_effects_summary(downstream_nodes)`** — new pure helper in `chronos.cli.fork`. Aggregates `metadata["effects"]` across a node list and returns `{total, dangerous_count, tag_counts, dangerous_samples}`. The samples field caps at 3 concrete `(step, name, effects)` tuples so the CLI can show examples, not just an abstract count. Defensive against malformed metadata (non-list `effects` is treated as empty).
- **`render_effects_preview(summary, console)`** — new renderer that prints a yellow-bordered `Downstream side-effects preview` panel **before** the overrides table in `chronos fork plan` output. Shows the dangerous count out of total, a per-tag breakdown (e.g. `db=1, external=1, fs=1, network=2`), up to 3 concrete node examples, and an ADR-019 disclaimer that Chronos does not sandbox fork execution. Silent when `total == 0` (forking at the last node) or `dangerous_count == 0` (pure-LLM downstream) — no false-alarm noise.
- **`fork_plan_command` integration** — per-run linear downstream (`step_index > parent.step_index`) is now computed after the parent node resolves, summarised via `build_effects_summary`, and threaded to both `render_plan_preview` call sites (JSON and Python emit modes) via the new `effects_summary` kwarg. Backwards compatible: callers that don't pass the kwarg get the pre-R45-A behaviour.
- **8 new unit tests** (`tests/unit/test_fork_cli.py`) covering the helper (empty, pure-LLM, mixed dangerous, sample cap at 3, malformed metadata) and the CLI (dangerous preview shown with ADR-019 reference, silent when no downstream, silent when only LLM downstream). Full suite: **435 pass / 2 skip / 94% coverage** (up from 427 in v0.3.0). `cli/fork.py` coverage rose to **97%**.

### Fixed

- `tests/unit/test_cli.py::test_cli_info` was pinned to `phase 2` but the CLI `info()` status line was bumped to `Phase 3` in R44-A. R44-A's own green bar run missed this because the test was skipped by the coverage-filtered run; R45-A caught it on full-suite verify and updated the assertion to `phase 3`.

### Rationale

R44-A shipped the effect-annotation plumbing and a visual badge in the UI drawer, but the CLI fork workflow — which is the actual entry point for fork plans per ADR-013 (JSON artifact, CLI-only consumption) — had no awareness of downstream risk. Users could happily fork at step 0 of a 10-step run where 6 of those steps hit paid APIs, with nothing in the preview to flag it. R45-A closes the loop: every `chronos fork plan` invocation now shows, in 4-6 lines of CLI output, exactly how many dangerous nodes will re-fire and what their names are.

This is **honest warning, not safety theatre** (ADR-019). Chronos still does not sandbox. The panel's disclaimer line explicitly says so. If a user wants to re-send an email, they can. The goal is that they see it coming.

### Non-goals

- No *blocking* of dangerous forks — even `external`-heavy downstream just warns, never exits 1. Users with idempotent side effects should be free to fork.
- No DAG-topological downstream (graph walk from the fork point following `parent_node_id` edges). Per-run linear downstream (`step_index > parent`) was chosen because (a) it matches how `replay`/`fork` consumers actually think about "what comes after", and (b) branching DAG analysis is Phase 4 territory.

### Files

- **Modified**: `src/chronos/cli/fork.py` (+2 helpers, +1 `render_plan_preview` kwarg, +6 lines in `fork_plan_command`), `tests/unit/test_fork_cli.py` (+8 tests, new `seeded_db_with_effects` fixture), `tests/unit/test_cli.py` (1-line phase-marker fix).

## [0.3.0] — 2026-04-25 (Round 44-A)

**Theme**: **Phase 3 on-ramp PH3-02** — adapters now annotate each node with an `effects` list (`network`/`fs`/`db`/`external`/`llm`), and the Web UI surfaces side-effect warnings on dangerous nodes. This is the first step toward fork confidence: before replaying a node, users can see whether the original execution touched the real world. Following ADR-019 (R43-B) the project remains **explicitly non-sandboxed** — warnings are the honest answer, not fake safety.

### Added (R44-A — Effect annotations & Fork warnings)

- **`src/chronos/adapters/effects.py`** — new `classify_effects(kind, node_name, override=None)` heuristic. Detects five effect tags from `NodeKind` + `node_name` regex: `llm` (from `NodeKind.LLM`), `network` (http/api/fetch/request/get/post/…), `fs` (read/write/file/path/save/load/…), `db` (db/postgres/redis/sql/…), `external` (send_slack/send_email/run_shell/subprocess/…). Snake_case compound names (`http_get`, `send_slack_notification`, `http_write_db`) are matched via `(_\w+)?` and `\b\w*keyword\w*\b` patterns — plain `\bword\b` fails here because `_` is a word char. Also exports `DANGEROUS_EFFECTS_DEFAULT = {network, fs, db, external}` — **`llm` is deliberately excluded** because forking is precisely for re-running LLM reasoning. `count_dangerous_downstream(store, run_id, from_step)` helper for the fork-plan preview.
- **Adapter integration** — both `LangGraphRecorder` and the AutoGen `Recorder` now accept an optional `effects_map: dict[str, list[str]]` kwarg (per-node override) and write `metadata["effects"]` on every recorded node via `classify_effects(...)`. Zero SQL migration required: the `metadata_json` column has existed since v0.1.0, and `Node.model_dump()` auto-exposes the field through the API.
- **UI effects badge in `NodeDetails`** — when a selected node carries `metadata.effects`, the drawer now renders a **"Side effects"** row with colored tags (`llm=purple`, `network=orange`, `fs=gold`, `db=volcano`, `external=red`). If any tag is in `DANGEROUS_EFFECTS_DEFAULT`, an amber `<Alert warning>` banner above the identity table explains that forking here will **re-run the real-world operation** (re-charge, re-send email, re-write a record) and suggests forking from a pure node for reasoning-only exploration.
- **Danger-styled Fork button** — when `NodeDetails` is wired with an `onFork` prop (future fork-from-tree flow) and the node is dangerous, the button renders with AntD `danger` styling and appends `· re-triggers side effects` to the label. This code path is predicated on downstream integration; the warning Alert is the user-visible primary signal in v0.3.0.
- **i18n (zh/en)** — new namespace `effects.*`: `tags.{llm,network,fs,db,external}`, `forkWarning.{title,body,buttonHint}`, plus `help.concepts.effects` for the `ConceptTip` glossary and `nodeDetails.fields.effects` for the drawer row label.
- **41 unit tests** (`tests/unit/test_effects.py`) covering the classifier (LLM kind, each of the four keyword families, override precedence, snake_case compound names, the `_` word-boundary edge case) and `count_dangerous_downstream`. Full suite: **427 pass / 2 skip / 94% coverage** (up from 386 in v0.2.1).

### Rationale

PH3-02 was locked in R43 after R42-A's sandbox spike (→ `tests/spikes/spike8_sandbox.py`) confirmed that re-running agent code safely is a ~100x bigger project than Chronos itself (Docker/gVisor layer, credential mocking, network egress control). ADR-019 codified the no-sandbox stance: Chronos records and replays *narratives*, not real-world side effects. Effect tags are the honest compromise — we can't prevent double-sends, but we can make sure users know which nodes will fire when they fork.

### Non-goals

- No runtime effect *interception* (dry-run mode, effect stubs, network egress filter) — Phase 4 territory if ever.
- No automatic fork-is-dangerous refusal — users may intentionally want to re-send the email. Warn, don't block.

### Files

- **New**: `src/chronos/adapters/effects.py`, `tests/unit/test_effects.py`.
- **Modified**: `src/chronos/adapters/langgraph.py`, `src/chronos/adapters/autogen/recorder.py`, `frontend/src/components/NodeDetails.tsx`, `frontend/src/components/ConceptTip.tsx`, `frontend/src/i18n/{zh,en}.ts`.

## [0.2.1] — 2026-04-25 (Round 39-A + Round 40 + Round 41)

**Theme**: Complete the **record / fork / diff / compare** four-verb loop in the Web UI, formalize "compare" as the narrative verb around the existing `diff` machinery, and refresh the README with screenshots that actually show what the tool does.

### Added (Round 39-A — Side-by-side Diff viewer)

- **`GET /runs/compare`** — new FastAPI endpoint backing the Web UI's side-by-side view. Accepts `a` and `b` run IDs (plus `downstream_only: bool`), returns a `CompareResponse` with the aligned entries, per-entry diff tags (`same` / `changed` / `added` / `missing`) and top-level summary counts. The alignment reuses `core/diff.py` unchanged (ADR-006 frozen since v0.1.x) — this endpoint is the *read-side* the UI has been missing. Route ordering matters: registered **before** `/runs/{run_id}` so `/runs/compare` doesn't get swallowed as a run ID literal. Covered by 6 new unit tests (`tests/unit/test_api_server.py`).
- **DiffView page** (`frontend/src/pages/DiffView.tsx`, ~420 LOC). New hash route `#/runs/<a>/diff/<b>` renders two stacked ReactFlow panels (RUN A top, RUN B bottom) sharing the same layout primitives as the single-run TreeView. Summary badge (`相同 / 改变 / 新增 / 缺失` counts), alignment list table below the graphs, and an **Alert banner** explicitly calling out when B is a fork of A and what the "Downstream only" toggle hides. Auto-swap fallback: if the user navigates to `/runs/<child>/diff/<parent>`, the page silently swaps A/B via `history.replaceState` so the fork direction renders correctly (no banner, no toast — just works).
- **Compare button in RunList** (`frontend/src/pages/RunList.tsx`). AntD `rowSelection` with a FIFO cap of 2 — selecting a third run evicts the oldest. Compare button disabled until exactly 2 are selected, then navigates to the diff route. Row click still opens the single-run view thanks to an `onRow` guard that bails when the target is a `.ant-table-selection-column` checkbox cell.
- **`DiffNodeDetails` drawer** (`frontend/src/components/DiffNodeDetails.tsx`). Click any node in either diff panel to open a drawer with a field-level red/green JSON diff (additions green-tinted, removals red-tinted, unchanged rows collapsed). For nodes that exist on only one side, shows "A side only" / "B side only" chrome instead of attempting a diff. Picks its own field-level diff via a lightweight object-walk (not using `core/diff.py` since that's node-level).
- **Legend panel — diff mode variant** (`frontend/src/components/Legend.tsx`). New `showDiff?: boolean` prop renders a 4-swatch diff vocabulary (same / changed / added / missing) with a one-line hint. Separate `localStorage` key (`chronos.legend.expanded.v1.diff`) so diff-mode legend defaults to collapsed — the dual-panel layout is narrow, don't waste vertical pixels on legend in default state.
- **i18n (zh/en)** — new namespaces: `diff.*` (page chrome), `diffTag.*` (same/changed/added/missing), `diffHint.*` (legend hint copy), `legend.diff` (legend block title).

### Added (Round 40 — "compare" narrative + ADR-018)

- **ADR-018: "compare" is the narrative verb for structural run comparison** (`docs/decisions/0018-compare-verb-over-diff.md`). Resolves the tension between the install-era CLI (`chronos diff`, kept for muscle memory) and the new Web UI (where "Compare" reads more naturally to non-programmers). Decision: **narrative/docs use "compare"; CLI/API keep "diff"** for stability. No code moved, no endpoints renamed — this is a naming-in-docs decision only.
- **Progress doc** (`progress/2026-04-25-round-40.md`) spelling out the follow-up backlog: R41-A (README screenshots + Compare section rewrite), R41-B (`chronos diff` docstring surfacing "compare"), R41-C (v0.2.1 release cut).

### Added (Round 41-A — README refresh)

- **Four Web UI screenshots** in `docs/assets/` — RunList, single-run TreeView, family tree (3-lane fork chain), DiffView with side-by-side panels and alignment list. Captured against the `scripts/seed_demo.py` 5-run demo DB so the screenshots are reproducible by anyone cloning the repo.
- **README Web UI hero section** (English + 中文) linking to the screenshots, re-ordering the intro so the four-verb loop (record / fork / diff / **compare**) is the first thing a reader sees. Status table refreshed to v0.2.x with explicit R39-A / ADR-018 rows. Repository Layout updated to include `frontend/` and `src/chronos/api/`.

### Changed (Round 41-B)

- **`chronos diff --help` docstring** now mentions "compare verb" explicitly so a reader arriving from the README's *Compare* section can grep the CLI and find the entry point. One-line docstring tweak; zero behaviour change.

### Docs / Process

- **Skill**: `chronos-docs-screenshots` (in `~/.hermes/skills/`) captures the full 4-shot playbook including the AntD Switch `ariaChecked`-race pitfall, ReactFlow fit-view framing constraints with a 478-px canvas, and the tool-call budget split rule for cron rounds that both capture and rewrite.

## [0.2.0] — 2026-04-24 (Round 36-D + Round 37.5 + Round 38)

### Added (Round 38 — Tree view polish pass)

- **Legend panel** (`frontend/src/components/Legend.tsx`, ~200 LOC). Top-right floating panel, collapsible via a chip button. Documents every visual vocabulary element the TreeView uses: **node kinds** (LLM Call, Tool Call, Function, Router, Fork, End) with icon + short i18n description, **node statuses** (Running, Completed, Error, Placeholder) with the same color dot the real nodes use, and **edge kinds** (Sequential solid, Fork dashed). Non-technical readers no longer need to guess why one edge is dashed and another isn't — the vocabulary is right there, one click away. zh/en strings in `i18n/{zh,en}.ts` under a new `legend.*` namespace.
- **Edge click → selection highlight** (`TreeView.tsx`). New `selectedEdgeId` state + `onEdgeClick` toggle + `onNodeClick` auto-clear. Selected edge gets accent color (`#58a6ff` for sequential / `#c678f7` for fork), 2.6px stroke, and a single 6px `drop-shadow` glow; unselected edges fade to 0.65 opacity. Intentionally understated after user feedback — no dash-flow animation, no triple-layer glow, just enough to read "this one is selected".
- **SelectedEdgePanel floating card** (top-left `<Panel>` in ReactFlow). When an edge is selected, a small card appears showing edge kind + from-node → to-node (using real `node_name` not IDs) + a one-sentence plain-language explanation ("Sequential step: A finishes, then B runs" / "Fork: a new run starts from this node as a branch"). Close button clears the selection. Left border + gradient background use the same accent as the selected edge so the two pieces read as one UI object.
- **ConceptTip coverage extended** to 4 more UI chrome elements: **Run ID header** (already had it), **Step counter** (`Step 0 / 5` button), **Framework label** in Run Info, **Cost (USD) label** in Run Info. All four are now `<button>` elements with a tooltip on hover/focus — keyboard accessible, screen-reader readable. `ConceptKey` union extended with `step`, `framework`, `timeline` (last one reserved for R39 playback narrative). zh/en descriptions added to `concepts.*`.
- **Dot-grid background** (`ReactFlow` `BackgroundVariant.Dots`, gap 22, size 1.6, color `#3a4556`). Replaces the previous solid `#0d1117` backdrop. Gives the canvas just enough depth cue to feel navigable without competing with the node cards. Dot color tuned after a DOM spot-check confirmed the initial `#2a3441` was below the visible threshold on most monitors.

### Changed (Round 38)

- **`layout.ts` — edges now carry `data.kind`** (`"sequential"` or `"fork"`). Pre-R38, edge metadata was inferred from the edge ID prefix (`seq-*` vs. `fork-*`) which meant any client code that wanted to branch on kind had to string-parse the ID. R38 adds explicit `data` because the new `rfEdges` memo in `TreeView` needs to look up kind to pick the accent color + the right SelectedEdgePanel copy. Also gives R39 a clean hook for per-kind interaction behaviors without regex on IDs.
- **Unselected edge opacity lifted from 0.5 → 0.65**. The initial selection highlight was implemented by fading the unselected edges, but 0.5 was far enough that users reported the sibling edges felt "broken / greyed out" rather than "just de-emphasized". 0.65 reads as "still present, just not the focus" which is the intended affordance.

### Design (Round 38)

- **Why plain solid highlight, not a flowing-dash animation** — the first draft used `stroke-dasharray: 8 6 !important; animation: chr-edge-dash-flow 0.8s linear infinite` which looked slick in isolation but clashed with the naturally-dashed fork edges (dashed fork + flowing dashes on selected = the fork stops reading as a fork). User feedback was explicit: *"整体就这条虚线有点违和其他的还好"*. Dropped the animation; just the color + glow does the job and the fork/sequential contrast stays legible.
- **Why stop at 2.6px stroke + single-layer glow, not triple-stack** — earlier drafts used 4.5px with 3-layer drop-shadow to achieve "dramatic" selection feedback. User priority ended up being the opposite: *"功能正常 + 交互流畅 > 视觉惊艳"* and *"只要不是 bug、能力上确实、交互上逻辑有问题其实都还好"*. Calibrated to the minimum that still communicates "this is selected" — 2.6px is noticeably thicker than the 2.0px unselected, single 6px glow at 0.55 opacity reads as a soft halo without drawing attention from the node cards.
- **Why the SelectedEdgePanel lives top-left, not as an inline tooltip** — inline tooltips on SVG edges need to follow the edge midpoint on pan/zoom, which means fighting ReactFlow's coordinate system. A fixed `<Panel>` position is stable, doesn't flicker during drag, and reads as a "what am I looking at" sidebar — the same role the Run Info card plays for the overall run. Left side balances the Legend panel on the right.
- **Why arbitrate vision feedback via screenshot-to-user, not via `browser_vision` alone** — during R38 the `browser_vision` tool gave contradictory scores (7.5 → 6.5 → 5.5) for cosmetically similar screens while an independent `vision_analyze` call on the same cached image scored 8-8.5. Rather than endlessly iterate on a single flaky judge, R38 introduced a working rule: when vision output is ambiguous or conflicts with DOM self-check, ship the screenshot to the user with 3-4 focal questions and let the human arbitrate. This cut the polish loop from ~7 iterations to 1.

### Added (Round 37.5 — Real-LLM smoke + multi-run fork family tree)

- **Live real-LLM smoke test** (`tests/live/test_real_llm_smoke.py`, ~180 LOC). A triple-guarded suite (`@pytest.mark.live` + `CHRONOS_LIVE=1` + `OPENAI_API_KEY`) that records an actual LangGraph run against GLM-5 via the internal OneAPI gateway, asserts that nodes come back with non-empty `state_after`, token usage fields, and measurable `duration_ms`. Gives us a CI-skippable but on-demand sanity check that the recorder still works end-to-end against a real model, not just mocked transport. Default test run (380 pass / 2 skip) leaves both live cases skipped — they run only when the env is wired.
- **`GET /runs/{id}/tree?include_descendants=true`** — new query parameter on the tree endpoint. When set, the server runs a DFS over the fork graph rooted at the given run and returns a **merged** `{nodes, edges}` payload where every node is tagged with its owning `run_id`, plus two new top-level fields: `descendant_run_ids: string[]` (run IDs in DFS order, starting with the root) and `run_summaries: { [run_id]: { id, status, framework, task, started_at } }`. A `visited: set[str]` guards against cycles even though the DB schema shouldn't allow them. Default (`include_descendants=false`) is byte-identical to the pre-R37.5 response — no breaking change for existing consumers. Covered by 5 new unit tests in `tests/unit/test_api_server.py` (single-layer, two-layer, cycle-protection, no-fork degradation, run_id presence).
- **Multi-run "family tree" layout in the viewer** (`frontend/src/layout.ts`, ~230 LOC, rewritten). When `tree.nodes` span multiple `run_id`s, the layout produces horizontal **super-lanes**, one per run, stacked top-to-bottom in the order they appear in `descendant_run_ids`. Within each lane the classic depth-column BFS layout is reused verbatim, so a lane in multi-run mode looks identical to the full single-run view. Fork edges naturally become cross-lane flying connectors — the "alternate timeline" metaphor is now spatially obvious. Returns a third array `lanes: {runId, y, height, title, kind: "root"|"fork"}[]` so the page can render lane-background bands.
- **"Show full fork tree" toggle + `LaneBackground` component** (`frontend/src/pages/TreeView.tsx`). New AntD `Switch` on the toolbar wired to a `useEffect` that refetches with `include_descendants` when flipped. A new `LaneBackground` component uses `useViewport` from `@xyflow/react` to render translucent lane bands + lane header strips (run kind + adapter chip + truncated task description) that stay in sync with ReactFlow's pan/zoom. Selecting nodes in fork lanes works — `selectedNode` now reads from `tree.nodes` rather than the root-run-only `orderedNodes`. Playback stays scoped to the root run so "Play from start" tells a coherent narrative.
- **`i18n` plural support** — `en.ts` now has `nodeCount_one`/`nodeCount_other` + `forkCount_one`/`forkCount_other` keys via i18next's plural ICU format, so the Run Info card correctly renders "1 fork" / "2 forks" / "5 nodes" / "1 node". Chinese has no plural rule so `zh.ts` remains single-form. New keys for the toggle + lane headers + runs-in-tree badge: `tree.showDescendants`, `tree.showDescendantsTip`, `tree.runsInTree` (with `{{count}}` interpolation), `tree.laneRoot`, `tree.laneFork`.
- **Seed demo expanded to a 3-generation fork chain** (`scripts/seed_demo.py`). Was: 3 runs (completed / failed / running). Now: 5 runs — run1 (Tokyo, 5 nodes, fork root) → run4 (fork of run1, "re-plan with 5 days", 4 nodes) → run5 (fork of run4, "same plan cheaper model", 3 nodes) — giving the new family-tree view something interesting to render out of the box. Running `python scripts/seed_demo.py && chronos web --db /tmp/chronos-demo.db` is now a 10-second demo of the killer feature.

### Changed (Round 37.5)

- **Edge rendering in `layout.ts` — fixed a pre-existing visibility bug**. Sequential and fork edges were using CSS custom properties `--accent` and `--fork`, which were **never defined** anywhere in the stylesheet (the real variables are `--chr-accent` and `--chr-purple`). SVG falls back to `stroke: none` when a variable doesn't resolve, so every edge in every run on `main` was effectively invisible — users were relying on horizontal node order alone to read flow. Fixed by pointing at the correct variable names, bumping `strokeWidth` from 1.5 to 2 (sequential) / 2.2 (fork), and adding an `arrowclosed` `markerEnd` on both kinds so direction is explicit. ReactFlow's `colorMode="dark"` also now gets passed explicitly, which matches the rest of the app shell.
- **Frontend bundle grew to 455.99 KB gzipped** (was 452.54 KB at R36-D). The new super-lane layout + `LaneBackground` + `useViewport` hook + the extra i18n keys add ~3 KB gzipped — well under the chunking threshold.

### Design (Round 37.5)

- **Why merge into a single `{nodes, edges}` graph instead of returning subtrees** — ReactFlow rendering works off a flat node+edge list; the viewer would have had to flatten a tree-of-subtrees on the client anyway. Tagging each node with `run_id` and exposing `descendant_run_ids` + `run_summaries` at the top level gives the frontend everything it needs to partition into lanes without losing the single-graph layout invariants. The fork edges already carry `child_run_id`, so cross-lane routing falls out for free.
- **Why horizontal super-lanes, not a vertical timeline** — agent runs read left-to-right (the existing single-run layout is depth-columns), so stacking runs vertically preserves directional muscle memory. A vertical lane metaphor would have required rotating every node card and re-thinking the fork edge geometry, for no payoff. Cross-lane fork edges become visually obvious "drop down into the alternate timeline" connectors, which matches the mental model the README's "time machine" narrative already sets up.
- **Why DFS over BFS for descendants** — BFS would have returned runs in wave order ({root}, {all-run-1-children}, {all-run-2-children}...), which looks fine for 2 generations but scrambles left-to-right reading order when a fork has grandchildren. DFS preserves the "read top-to-bottom, each run comes right after its parent" ordering, which matches how users draw family trees on paper. Both are `O(nodes + edges)`; the choice is purely about lane ordering.
- **Why browser visual review is mandatory, not optional** — R37.5-C3 caught a pre-existing `stroke: none` bug that had been live on `main` for multiple rounds. API tests were green (5 edges returned, 5 edges rendered as DOM nodes), the headless snapshot showed the edges, but visually they were completely invisible on the dark background because the CSS variable didn't resolve. Relying on API response + DOM existence as a pass signal is not enough for a UI project — "interface green ≠ what the user sees is correct" (R37.5 rule).



### Added (Round 36-D — Web UI polish pass)

- **Ant Design 6 + Framer Motion + i18n + help system + guided tour** — full rewrite of the viewer's visual layer. New entry: `frontend/src/main.tsx` mounts `ConfigProvider` with a dark-first theme (`colorPrimary: #58a6ff`, `colorBgBase: #0d1117`, `colorBgElevated: #1c2128`) and an AntD locale bound to the user's language choice (`zhCN` default, `enUS` via toggle). `App.tsx` is a hash-routed shell with three routes (`#/home` landing, `#/` run list, `#/runs/<id>` tree) and `AnimatePresence` page transitions (250ms opacity + 12px y-axis slide). Non-technical readers can actually understand what they're looking at now — every jargon word has a `ConceptTip` popover, the help drawer explains Run/Node/Fork/Adapter/Usage/Thread with 2–3 sentences each, and the first-visit `OnboardingTour` (`localStorage: chronos.tour.seen.v1`) walks new users through the header controls.
- **`src/i18n/zh.ts` + `en.ts` + `index.ts`** — full Chinese + English translation tables (~450 lines each) covering app chrome, status/node-kind labels, landing copy, runs table, tree toolbar, node-details tabs, help center (what-is + 6 concept cards + how-to + 4 FAQ entries), and the tour script. `i18next-browser-languagedetector` resolves the language from `localStorage: chronos.lang` first, then navigator, defaulting to `zh`. Every string the user sees goes through `t()` — no hard-coded English sneaks through the rewrite.
- **4 new pages + 9 new components** (`frontend/src/pages/{Landing,RunList,TreeView}.tsx`, `frontend/src/components/{AppHeader,AppFooter,HelpDrawer,ConceptTip,OnboardingTour,NodeDetails}.tsx` + `components/nodes/{ChronosNodeCard,PlaceholderNode}.tsx`, `hooks/usePlayback.ts`, `theme.ts`). `Landing` renders a glow-lit hero with a gradient title (`#58a6ff → #a371f7 → #f778ba`), Framer-Motion-staggered 3-step narrative cards (record → browse → fork), and a feature strip listing supported adapters. `RunList` is an AntD `Table` with status `Badge`, framework `Tag`, searchable/filterable, click-row-to-drill, explanatory empty state for new users. `TreeView` splits into a left `RunInfo` card (status + adapter + task + `Statistic` grid for node/fork count + total cost), a full-bleed ReactFlow canvas in the middle, and an on-demand `NodeDetails` drawer on the right.
- **"Play from start" / 从头播放 — the killer feature for non-technical readers** (`frontend/src/hooks/usePlayback.ts`, ~60 LOC). Given nodes sorted by `step_index`, the hook yields `{playing, index, play, pause, reset}`; `TreeView` wires it into `ChronosNodeCard`'s `isPlaying` / `isPlayed` flags and auto-pans the ReactFlow viewport to the current node on each step (`rf.setCenter(x, y, {zoom: 1.1, duration: 600})`). Visual grammar: a 900ms/step cadence, unplayed nodes dim to 50% opacity via `:has()` selector, the currently-playing node gets a 1.04× scale bump + `@keyframes chr-pulse` halo animation, already-played nodes stay at full opacity. Watching it feels like observing the agent think in slow-motion — exactly the "time machine" narrative the README promises, now demonstrable in 10 seconds.
- **NodeDetails Tabs rewrite** (`components/NodeDetails.tsx`, ~200 LOC). The wall-of-JSON drawer is gone. Four tabs: **标识 / Identity** (AntD `Descriptions` with node ID + name + kind + timestamps + duration + parent), **输入输出 / Input-Output** (error alert on top if present, then tool_name + tool_input + tool_output in copy-buttoned code blocks), **状态 / State** (pretty-printed `state_after`), **成本元数据 / Cost & Metadata** (model name, usage tokens grid, cost, metadata JSON). Every code block has a floating copy button wired to `navigator.clipboard.writeText` + AntD `message.success` toast.
- **Custom ReactFlow node (`ChronosNodeCard`)** — kind-aware color accent on the left border (LLM purple / Tool blue / Fn green / Router gold / Fork pink / End muted), Lucide icon + kind tag header, step-index badge, truncated node name (ellipsis with `Tooltip` fallback for the full text), optional model name + error subtitle. A dashed `PlaceholderNode` renders for unresolved fork branches (child run has no nodes yet) to preserve the `layout.ts` placeholder contract.
- **Header controls** (`AppHeader.tsx`) — brand logo (`🕰️ Chronos Agent` with tagline), runs-page nav button (tour-anchored), help drawer trigger (tour-anchored), language dropdown 中/EN (tour-anchored), theme toggle dark↔light via `ThemeContext`, API docs button (→ `/docs`), GitHub button (→ public repo). All controls have AntD `Tooltip` + `aria-label` for accessibility.
- **`scripts/seed_demo.py`** (~140 LOC, not shipped in the package) — seeds a demo DB with 3 runs: a completed LangGraph trip-planner with 5 nodes showing every `NodeKind` (LLM → Tool → LLM → Router → End), a failed AutoGen scrape with 3 nodes + error message, a running Linear report. Enables one-command E2E smoke: `python scripts/seed_demo.py --db /tmp/demo.db && chronos web --db /tmp/demo.db`.
- **9.6 KB `styles.css`** — CSS custom properties for both themes (`:root` dark palette + `[data-theme="light"]` override), gradient hero background with radial glow, step-card hover transform (`translateY(-4px) + box-shadow`), concept-tip dashed underline, ReactFlow control button overrides to match the dark palette, chronos node card pulse + dim-unplayed sibling rule (`:has(.is-playing) .chr-node-card:not(.is-played):not(.is-playing) { opacity: 0.5 }`), responsive breakpoint at 768px (hero font shrinks, tree sidebar hides).

### Changed (Round 36-D)

- **Viewer bundle size grew from 108 KB gzipped (R34-C) to 452 KB gzipped** — expected trade-off for the Ant Design 6 component library + Framer Motion animation runtime. Absolute size is 1.39 MB raw / 452.54 KB gzipped (`dist/assets/index-BUhoIdUw.js`). Still fits comfortably in the local-viewer use case (single-user, localhost, no mobile constraints); a future round can code-split via `manualChunks` if warranted. CSS grew from ~6 KB to 23.11 KB / 4.53 KB gzipped.
- **Chinese is now the default language** with English a one-click toggle away, matching the user base. Language preference persists via `localStorage: chronos.lang`; theme preference via `localStorage: chronos.theme`; tour-seen flag via `localStorage: chronos.tour.seen.v1`. All three stores are independent and safe to clear individually.
- **`frontend/src/RunList.tsx`, `TreeView.tsx`, `NodeDetails.tsx`** (the R34-C single-file pages) are **removed** — their roles are split across `pages/` + `components/` with proper separation of concerns. `api.ts`, `types.ts`, `layout.ts` are kept **verbatim** from R34-C: the API contract and the hand-rolled BFS layout algorithm are stable and still correct; only the rendering layer changed.

### Design (Round 36-D)

- **Why Ant Design 6 and not a newer framework-agnostic alternative (Radix, Mantine, shadcn/ui)** — Ant Design ships a complete zh_CN locale out of the box including date/time formatters, `Table` pagination labels, `Empty` state messages, `Tour` button labels, etc. For a Chinese-default viewer that might also show English, that integration is worth the bundle-size premium. Secondary reason: `Tour`, `Drawer`, `Descriptions`, `Collapse`, `Tabs`, `Statistic` are all in the same library with a consistent token system — no cherry-picking from three packages with clashing design languages.
- **Why Framer Motion and not CSS animations** — two features need orchestration that CSS alone can't do cleanly: (1) page-to-page `AnimatePresence` exit-then-enter transitions on hash-route changes, (2) staggered `whileInView` card entrance on the landing page. Both are idiomatic in Framer Motion; hand-rolling them with CSS would mean manually tracking mount/unmount state in React — not worth the maintenance cost for a UX polish layer.
- **Why the "play from start" feature lives in a hook, not the page** — `usePlayback(totalSteps)` exposes a pure state machine (`{playing, index, play, pause, reset}`) driven by a `setTimeout` chain. Keeping timing logic out of `TreeView.tsx` means the page only has to translate `index` into visual state (which node to highlight, where to pan). Side benefit: the hook is trivially unit-testable once we add a frontend test harness (not in this round).
- **Why `layout.ts` is kept intact** — the hand-rolled BFS-by-depth layout algorithm from R34-C handles forks and unresolved-branch placeholders correctly and produces deterministic positions. It's ~180 LOC with zero runtime dependencies. Swapping in dagre / elkjs would add 80+ KB gzipped for what would visually be a lateral move; if we ever grow to thousands of nodes in a single run (we won't, because a single agent task rarely exceeds 30 steps), that's the day to reconsider.
- **Why `ChronosNodeCard` uses a CSS-variable accent (`--accent`) rather than inline styles** — each node instance sets `style={{ "--accent": KIND_COLORS[kind] }}` once, and the CSS reaches for `var(--accent, var(--chr-accent))` in ~4 different selectors (left border, kind icon, focus ring, hover). Changing the accent in one place updates all surfaces. Trade-off: TypeScript needs the `["--accent" as string]` cast because `style` doesn't officially type CSS custom properties.
- **"从头播放" pan semantics deliberately avoid fitting the viewport to each node** — we `setCenter(x, y, {zoom: 1.1, duration: 600})`, NOT `fitView`. Reason: `fitView` rescales the whole graph to fit the single highlighted node, which is disorienting — the user loses the context of where in the overall tree they are. `setCenter` keeps the zoom steady so the tree's shape remains visible while the camera glides along the path.

### Verified (Round 36-D)

- **`cd frontend && npm run build`** — `tsc -b && vite build` both clean. Output: `dist/index.html` (0.53 KB), `dist/assets/index-CGVMMv-C.css` (23.11 KB / 4.53 KB gz), `dist/assets/index-BUhoIdUw.js` (1390.40 KB / 452.54 KB gz). Vite flags the >500 KB warning as expected; accepted as a local-viewer trade-off (see Changed note above).
- **`ruff check src tests` → All checks passed**; **`ruff format --check src tests` → 61 files already formatted**; **`mypy src` → Success, no issues found in 26 source files**; **`pytest -q` → 375 passed in 11.51s**. Backend untouched in this round, so the green bar is confirmation of no collateral damage — the frontend rewrite stayed properly scoped to `frontend/src/**`.
- **E2E smoke** — `python scripts/seed_demo.py --db /tmp/chronos-demo.db` wrote 3 runs + 8 nodes successfully; `uv run chronos web --db /tmp/chronos-demo.db --port 8765 --host 127.0.0.1 --no-browser` started cleanly (`Uvicorn running on http://127.0.0.1:8765`, watch-pattern fired); `curl /runs` returned the 3 seeded runs with full JSON; `curl /app/` returned the new `index.html` referencing `/app/assets/index-BUhoIdUw.js` + `index-CGVMMv-C.css`; `curl /app/assets/index-BUhoIdUw.js` → HTTP 200, 1,390,403 bytes (matches on-disk `dist/` size exactly — the committed bundle is what's actually served); `curl /runs/<id>/tree` → full neutral-tree JSON with 5 nodes. No live browser test in this environment (Chrome unavailable in the agent sandbox); the user will visually verify on their local machine after pulling the commit.

## [0.2.0b0] — 2026-04-24 (Round 31 + Round 32 + Round 33 + Round 34-A + Round 34-B + Round 34-C)

### Added (Round 34-C)

- **ReactFlow viewer bundle — `frontend/`** (~500 LOC TSX + CSS, 108KB gzipped after build). New self-contained Vite + React 19 + TypeScript 5 + `@xyflow/react` v12 SPA under `frontend/` with two routes: `#/` lists recorded runs in a clickable table (ID, adapter, status tag, relative-time, task description), and `#/runs/<run_id>` renders the reasoning tree as a ReactFlow DAG (sequential edges solid, cross-run fork edges dashed with a `child_run_id` label), plus a side drawer `NodeDetails` that reveals identity / tool_input / tool_output / usage + cost / error / state_after / metadata / timestamps when a node is clicked. Hash-routing (not HTML5 history) so no server-side rewrite is needed — the FastAPI mount is pure static serving. Custom node renderer per `NodeKind` (`llm`, `tool`, `fn`, `router`, `fork`, `end`) with colored kind-badge + derived `previewOf(node)` that hunts through `tool_output → tool_input → state_after → metadata` for the first conventional string key (`text` / `answer` / `output` / `result` / `content`) so a useful 36-char preview shows on the canvas without demanding a dedicated `content_preview` field on the API contract (neutral tree stays minimal). Dark palette matches the R34-B landing page and the README (`#0d1117` background, `#58a6ff` accents) so screenshots look cohesive across surfaces.
- **`frontend/dist/` committed to git via whitelist** — `.gitignore` rewrite adds `!frontend/dist/` + `!frontend/dist/**` as the **last** pattern so it wins over the earlier generic `dist/` glob (git's last-match-wins ordering — verified with `git check-ignore -v` and `git add --dry-run`). Rationale: the Node toolchain is only needed to *build* the viewer, not to *use* it. Users installing via `uv pip install chronos-agent[web]` get a working `/app` tree viewer with zero npm dependencies, which is non-negotiable for the "GitHub-virality 5-minute quickstart" thesis (R33). The `frontend/.gitignore` whitelists only `dist/` — `node_modules/`, `.vite/`, `.tsbuildinfo` stay ignored.
- **`/app/*` StaticFiles mount on the FastAPI app** (`src/chronos/api/server.py`). `build_app(store)` now resolves `frontend/dist/` via `_find_frontend_dist()` — honors `CHRONOS_FRONTEND_DIST` env override first (for dev or alternate bundle paths), else falls back to `<repo_root>/frontend/dist` computed from `__file__.parents[3]`. Found → `app.mount("/app", StaticFiles(directory=..., html=True), name="viewer")` so `/app/` serves `index.html` and `/app/assets/<hash>.{js,css}` serves the bundle chunks. Missing → a `/app` + `/app/{rest:path}` handler returns **503 with `{error: "viewer_bundle_missing", detail: ...}`** including a `cd frontend && npm install && npm run build` remediation hint, rather than 404'ing silently. Failure mode is explicit by design: REST API, `/healthz`, and the landing page keep working regardless of bundle presence.
- **Landing page CTA to the viewer** (`src/chronos/api/server.py:_INDEX_HTML`) — prominent blue-gradient "🌲 Open Tree Viewer" button (`/app/`) alongside a secondary "API Docs" button (`/docs`). First-time users now see the tree viewer as the obvious next click after `chronos web` opens their browser; the endpoint list stays below for API consumers.

### Design (Round 34-C)

- **`@xyflow/react` v12, not `reactflow` v11** — the `reactflow` npm package was frozen in 11.11.4 and officially rebranded to `@xyflow/react` v12 (same team, same API surface, active development). Pinning to v12 keeps us on the supported branch; the import path `import { ReactFlow, Background, Controls, MiniMap } from "@xyflow/react"` plus `import "@xyflow/react/dist/style.css"` is the current canonical form. No compatibility shims needed.
- **Frontend types.ts mirrors `model_dump(mode="json")` output verbatim** — earlier drafts used shorter names (`framework`, `thread_id`, `finished_at`, `name`, `content_preview`, `extracted`) that diverged from the pydantic `Run` / `Node` / `Fork` models. R34-C rewrites `frontend/src/types.ts` to match the backend contract field-for-field (`adapter`, `adapter_thread_id`, `ended_at`, `node_name`, `tool_name`/`tool_input`/`tool_output`, `error_message`, `cost_usd_cents`, `metadata`, etc.) so the frontend stays truthful about what the API actually returns. Source-of-truth comment at the top of the file points readers back to `src/chronos/core/models.py` when drift is suspected.
- **Layout is a frontend concern, not baked into `/tree`** — `frontend/src/layout.ts` computes ReactFlow `position: {x, y}` from the sequential + fork graph with a simple topological level-by-level layout (BFS from root, 220px horizontal per level, 140px vertical per sibling). The API contract stays position-free — a different viewer (d3, Cytoscape, Graphviz, plain SVG) can render the same `/tree` JSON without our layout choices leaking in.
- **Hash routing, not HTML5 history** — the server-side mount is dumb StaticFiles; it doesn't rewrite unknown paths back to `index.html`. Hash routing (`#/`, `#/runs/<id>`) keeps everything client-side and side-steps the need for a catch-all server rewrite rule, which would otherwise collide with the 503-on-missing-dist fallback semantics.
- **Why `CHRONOS_FRONTEND_DIST` env override exists** — two concrete use cases: (1) dev iteration with a live `vite dev` server where the override points at an out-of-tree dist dir, and (2) distribution packaging that ships `dist/` under `site-packages/chronos/frontend/dist` instead of the repo-relative path. The `parents[3]` fallback is intentional about NOT walking up arbitrarily, so site-packages installs without a bundled `dist/` correctly return `None` → 503, rather than silently finding a stale bundle on the dev's machine.

### Tests (Round 34-C)

- `tests/unit/test_api_server.py` (+4 tests, total **375/375 pass**; api/server.py coverage **100%**). New cases: `test_app_mount_serves_index_when_dist_present` builds a fake `dist/` with a stub `index.html` + `assets/index.js` in a tmp_path, sets `CHRONOS_FRONTEND_DIST` via `monkeypatch.setenv`, builds a FRESH app (the top-level `client` fixture was built before the monkeypatch), and confirms `/app/` returns the stub HTML with `text/html` content-type and `/app/assets/index.js` returns the asset body; `test_app_mount_returns_503_when_dist_missing` points the override at a nonexistent path, builds a fresh client, and verifies `/app`, `/app/`, `/app/index.html`, `/app/deep/nested` all return 503 with `{error: "viewer_bundle_missing"}` and that `/healthz` + `/runs` still return 200 (REST API unaffected); `test_find_frontend_dist_resolver` unit-tests the resolver in isolation — valid override with index.html wins, override missing index.html returns None (explicit fail, not silent repo-root fallback), nonexistent override path returns None; `test_landing_page_advertises_viewer` asserts `href="/app/"` + "Tree Viewer" text appear in the landing HTML so the CTA never regresses silently. Lint/type: ruff clean after `ruff format src/chronos/api/server.py tests/unit/test_api_server.py`, mypy strict on 26 source files (unchanged count).
- **Live end-to-end smoke against real built bundle** (ad-hoc, not in suite) — seeded `/tmp/chr-smoke/s.db` with 2 runs (5 nodes, one with tool_input/tool_output, one with state_after text) via real `put_run`/`put_node` calls on a `SqliteStore`. Started `chronos web --db /tmp/chr-smoke/s.db --port 18766 --no-browser` as a background process. Curl'd 9 paths: `/` → 200, `/app/` → 200 + real `index.html` referencing the current asset hashes, `/app/index.html` → 200, `/app/assets/index-yV9Orvf-.js` → 200, `/runs` → 200 JSON with both runs, `/runs/demo-run-1` → 200, `/runs/demo-run-1/tree` → 200 JSON with 3 nodes + 2 sequential edges, `/healthz` → 200, `/docs` → 200. Confirms the full stack wires end-to-end: Vite build → committed `dist/` → `_find_frontend_dist()` → `StaticFiles` mount → real HTTP → correct asset-hash references in served HTML.

### Added (Round 34-A)

- **Local HTTP API — `chronos.api.server`** (`src/chronos/api/server.py`, ~230 LOC including module docstring). FastAPI app factory `build_app(store: SqliteStore) -> FastAPI` that mounts **six** read-only endpoints over a Chronos store: `GET /healthz` (trivial liveness probe + `schema_version` echo, no store touch); `GET /runs?limit=N` (list runs, most-recent-first, matching `SqliteStore.list_runs` 1:1; `limit` validated by FastAPI `Query(ge=1, le=1000)` → 422 on out-of-range); `GET /runs/{id}` (single Run + ordered Nodes with 404-if-missing); `GET /runs/{id}/nodes` (ordered Nodes only, same order — for UIs that paginate or diff-compare without round-tripping the Run); `GET /runs/{id}/forks` (forks where this run is the parent — 200 with `count=0` for leaf runs, 404 only if the run itself is missing); `GET /runs/{id}/tree` (the contract endpoint — neutral reasoning-tree shape, see §Design). Every `/runs/{id}/...` path is 404-strict on the run (not 200-with-`null`), so a viewer can distinguish "no such run" from "run exists but has no nodes/forks". Response bodies use pydantic's own `model_dump(mode="json")` so `datetime` → ISO-8601 and `StrEnum` → its string value come for free. Store is captured in each route's closure via `build_app(store)` — **no module-level global, no side-effect lifecycle**; callers (tests, `chronos web` in R34-B) own open/close. `pyproject.toml` new `[project.optional-dependencies].web` group (`fastapi>=0.110`, `uvicorn>=0.30`, `httpx>=0.27`). Top-level `chronos.api` package re-exports `build_app`.
- **`SqliteStore.get_forks_for_parent(parent_run_id) -> list[Fork]`** (`src/chronos/store/sqlite.py`) — mirrors `get_fork_for_child` on the other side of the fork relation, ordered by `created_at ASC`. Added for `/runs/{id}/tree` and `/runs/{id}/forks` endpoints; cleaner than ad-hoc SQL in the server layer.

### Design (Round 34-A)

- **Neutral reasoning-tree shape, not ReactFlow-specific** — `/runs/{id}/tree` returns `{run_id, nodes: [<full Node dict>], edges: [...], child_runs: [<full Fork dict>]}` where edges come in two flavors: `{"from": <parent_node_id>, "to": <node_id>, "kind": "sequential"}` for within-run parent-child chains, and `{"from": <parent_node_id>, "to": <child_first_node_id>, "kind": "fork", "fork_id", "child_run_id", "edited_fields"}` for cross-run fork edges. The shape is a strict superset of what ReactFlow needs (frontend computes `position` / `type` locally) and is framework-neutral — nothing about the viewer is baked into the API contract. A fork edge to a child run with no nodes yet (e.g. still running) has `to: null` so the frontend can render "unresolved branch" instead of mis-pointing. `child_runs` is a parallel summary for UIs that want to lazy-load children without re-fetching the full tree.
- **`SqliteStore.open()` now opens the connection with `check_same_thread=False`** — FastAPI dispatches sync endpoints onto a worker thread-pool, so the `TestClient`-or-`uvicorn`-driven reads happen off the thread that opened the store. SQLite itself is thread-safe in its default "serialized" mode; the `sqlite3` module's `check_same_thread` is a Python-layer guard, not an engine-layer one. We hold a single shared connection in autocommit + explicit `transaction()` CM, so flipping the Python guard is safe and matches how every local-server SQLite project on PyPI configures connections. Inline comment at the `sqlite3.connect()` call documents this for anyone auditing the change. No other code path was affected.
- **Route handlers are sync `def`** (not `async def`) — FastAPI runs sync handlers in a worker thread-pool, which is the correct fit for blocking SQLite I/O (doesn't block the event loop). With `check_same_thread=False` set above, this combination is idiomatic FastAPI + SQLite.
- **`build_app(store)` factory, one app per store, no singleton** — each call returns a fresh `FastAPI` instance closed over the given store. Tests exercise this explicitly (`test_build_app_binds_distinct_stores`): two apps bound to two stores don't cross-talk. Prevents the classic "module-level `app = FastAPI()` + global state" trap that makes production bindings hard to test.

### Tests (Round 34-A)

- `tests/unit/test_api_server.py` (17 tests). A two-run fork scenario (parent with 3 nodes → fork → child with 2 nodes) is built via real `put_run` / `put_node` / `put_fork` calls on a temp-file `SqliteStore` (no mocks — the real value of this suite is proving SELECT-shaped reads round-trip correctly through pydantic). Coverage: `/healthz` (1); `/runs` — both runs returned, `limit` respected, `limit=0` → 422 (3); `/runs/{id}` — run + ordered nodes + 404 (2); `/runs/{id}/nodes` — ordered by `step_index` ASC + 404 (2); `/runs/{id}/forks` — parent returns its fork with `edited_fields` intact, leaf run returns `count=0` with 200 not 404, unknown run 404 (3); `/runs/{id}/tree` — sequential edges match parent_node_id chain exactly (2 edges for 3-node chain), cross-run fork edge has `{from: n2, to: c1_first, kind: "fork", fork_id, child_run_id, edited_fields}`, `child_runs` summary lists forks-out, leaf run has no fork edges, 404 (5); `build_app` factory isolation — two apps against two stores don't share state (1). Total suite **363/363 pass** (+17 from R33's 346); ruff clean, mypy strict on 26 src files.
- **Live uvicorn smoke-test** (ad-hoc, not in suite) — `uvicorn.Server` bound to 127.0.0.1:18734 serves `/healthz` + `/runs` over real HTTP in a daemon thread. Confirmed the `check_same_thread=False` fix works end-to-end, not just under `TestClient`.

### Added (Round 34-B)

- **`chronos web` CLI command** (`src/chronos/cli/web.py`, ~180 LOC). One-command on-ramp that turns a recorded `chronos.db` into a browseable surface — prints a banner, starts the R34-A FastAPI app via uvicorn against the resolved DB, and opens a browser tab at the landing page. Signature: `chronos web [--host HOST] [-p PORT] [--db PATH] [--no-browser]`; defaults `127.0.0.1:8765`. Reuses `_open_store` / `_resolve_db_path` from `cli._common` so DB resolution (flag > `$CHRONOS_DB` > `./chronos.db`) matches every other subcommand verbatim. **Lazy uvicorn import** inside `web_command` so a base install without the `[web]` extra still runs `chronos --help` and every non-web subcommand without ImportError; hitting `chronos web` without the extra produces a friendly install hint instead of a traceback. **Browser auto-open via `threading.Timer(1.0, ...)`** on a daemon thread — uvicorn's public API has no caller-side "after startup" hook, so we schedule the `webbrowser.open` call ~1s after `uvicorn.run()` starts, which is empirically enough for loopback bind. `webbrowser.open` returning `False` (headless platforms) emits a rich notice and falls through to serving normally. `--no-browser` flag short-circuits the Timer entirely. **`reload=True` intentionally NOT supported** — uvicorn's reloader spawns a subprocess that re-imports the module path, which would lose our closure-bound store; `chronos web` is an inspection tool, not a dev server for editing `server.py`. Store lifecycle bound to the request to serve: `open → build_app(store) → uvicorn.run → store.close()` in a `finally` so a uvicorn startup crash still releases the SQLite handle.
- **`/` landing page on the FastAPI app** (`src/chronos/api/server.py`) — dark-themed single-file HTML served at the API root (not `include_in_schema`, so `/docs` stays clean). Zero external assets, zero JS build step: the whole page is a module-level `_INDEX_HTML` constant so packaging stays trivial (no `package_data` wiring). Palette matches the README (`#0d1117` background, GitHub-dark blue links) so future screenshots look cohesive. Links to every read endpoint (`/runs`, `/runs/{id}/nodes`, `/runs/{id}/forks`, `/runs/{id}/tree`, `/healthz`), the Swagger UI (`/docs`) and ReDoc (`/redoc`), plus CLI-equivalent commands for users who prefer the terminal. This is a fallback viewer that R34-C's real frontend will mount over a separate prefix and leave in place for `/` requests.
- **Bilingual README quickstart + `docs/cli-reference.md` entry** — English + 中文 quickstart sections both add a third step showing `uv pip install 'chronos-agent[web]'` then `chronos web --db ...`. CLI reference doc gains a full `chronos web` section with the flag table, endpoint links, landing page description, and an SSH port-forward recipe for remote hosts.

### Design (Round 34-B)

- **Why `chronos web` instead of asking users to run uvicorn themselves** — `uvicorn chronos.api.server:app` can't work as-is because `build_app(store)` is a factory that needs a store, not a module-level `app`. Exposing a module-level `app` would force an implicit default DB path and bake "one store per process" into the contract, which conflicts with the R34-A isolation invariant (two apps against two stores don't cross-talk). A dedicated subcommand owns DB resolution + browser-open + banner + uvicorn invocation as one unit, reusing the same helpers as every other `chronos` subcommand, which is the minimum-friction path to "runs recorded → browser open".
- **Dependency injection for uvicorn.run and webbrowser.open** — `web_command` accepts optional `run_server_fn` / `open_browser_fn` parameters defaulting to module-level `_default_run_server` / `_default_open_browser` wrappers. Unit tests inject spies that record call args without binding a port or spawning a browser process. This matches the DI pattern every other CLI module in `chronos.cli.*` already uses (`open_store_fn`, `console`) — no new mocking strategy, no patching via `unittest.mock`. The typer-wired CliRunner tests monkey-patch the module-level defaults instead (demonstrates both seams).
- **Path resolved for the banner, not store-attribute-read** — the banner prints the DB path that was actually opened. We call `_resolve_db_path(db)` ourselves (rather than reading e.g. `store._path`, which doesn't exist on `SqliteStore`) so the banner truthfully shows what `$CHRONOS_DB` or the default-cwd fallback resolved to. Users debugging a "wrong DB" confusion would otherwise see `None` in the banner and have no visible signal of what was actually opened.

### Tests (Round 34-B)

- `tests/unit/test_cli_web.py` (8 tests). Split into `TestWebCommand` (direct `web_command(...)` calls with spy `run_server_fn` + `open_browser_fn` injected — no typer wiring, no socket bind) and `TestWebCLI` (via `typer.testing.CliRunner` with `monkeypatch.setattr` on the module-level defaults — exercises the registration + option parsing layer). Coverage: uvicorn invoked with default host/port and a FastAPI `app` carrying the 6 R34-A routes; custom `--host 0.0.0.0` + `--port 9001` propagate; browser opens with correct URL after Timer fires (pytest sleeps 1.2s to wait out the 1.0s Timer); `--no-browser` suppresses the open even after Timer delay; `webbrowser.open` returning `False` is non-fatal (emits notice, doesn't raise); missing `--db` path causes `typer.Exit` before uvicorn is ever called; `chronos web --help` works without requiring `[web]` extras at import time (pins the lazy-import design); end-to-end typer-wired invocation reaches the spy uvicorn with the right port. Total suite **371/371 pass** (+8 from R34-A's 363); ruff clean, ruff format clean, mypy strict on 26 src files (unchanged count — new module didn't widen the src surface because it imports cleanly under strict).
- **Live smoke-test against a real empty DB** (ad-hoc, not in suite) — started `chronos web --db /tmp/smoke.db --port 18766 --no-browser` as a background process, curl'd `/healthz` (→ `{"status":"ok","schema_version":"0.1.0"}`), `/` (→ 200, 2525 bytes of landing HTML), `/runs` (→ `{"runs":[],"count":0}`). Confirmed end-to-end wiring: CLI flag → `_open_store` → `build_app(store)` → uvicorn bind → HTTP response matches R34-A TestClient contracts.

### Added (Round 33)

- **AutoGen adapter (record-only)** — `src/chronos/adapters/autogen/__init__.py` + `recorder.py` ship `AutoGenRecorder` (implements `RecorderProtocol`) and `autogen_adapter = _AutoGenAdapter()` module-level singleton satisfying `AdapterProtocol` (verified by `isinstance()` via `@runtime_checkable`). `name="autogen"`, `version_constraint=">=0.7,<0.8"`. **Strategy**: users write `with recorder.record(team, thread_id=...) as ref: asyncio.run(team.run(task=...))` — the sync `RecorderProtocol` context manager wraps AutoGen's async-first API via `asyncio.run()` at the user call-site, walking `TaskResult.messages` on CM exit to build the Node tree. Two channels accepted for delivering the result to the recorder: primary `ref.submit_result(result)` (explicit) or fallback `runtime.messages` attribute (if the user forgets). Message→NodeKind map covers `TextMessage` (source-aware: user→FN, assistant→LLM), `ToolCall*` events→TOOL, `HandoffMessage`→ROUTER, `StopMessage`→END, with merge-over-default user overrides via `kind_map`. Usage extracted from AutoGen's per-message `models_usage.RequestUsage` (bypasses ADR-015 callback path — `build_recorder(usage_extractor=...)` raises `AdapterError` to make this loud). Each Node's `state_after = {"messages": [...cumulative serialized messages...]}` since AutoGen's state IS its message history. `fork()` structurally conforms but raises `AdapterError("...See ADR-017 §Decision")` (Phase 3 candidate). `pyproject.toml` new `[project.optional-dependencies].autogen` group (`autogen-agentchat>=0.7.5`, `autogen-ext>=0.7.5`). Top-level `chronos.adapters` package re-exports `AutoGenRecorder` + `autogen_adapter`. **First adapter implementing ADR-017 sync-wrap strategy; third adapter shipping under ADR-016 — AutoGen was the highest-risk entry in R27's multi-framework risks doc (R-4 async mismatch) and it landed without mutating the sync Protocol family.**

### Added (Round 33) — ADR

- **ADR-017 — AutoGen Adapter Sync Wrap Strategy** (`docs/decisions/ADR-017-autogen-adapter-sync-wrap.md`, ~9.6 KB, Accepted). Decides Path A (users call `asyncio.run()` at the Chronos boundary; `RecorderProtocol` stays sync) over Path B (introduce a parallel `AsyncRecorderProtocol` family). Four-reason rationale ordered for a GitHub-breakout OSS project: DX first (one idiom users already know), single Protocol family = single audit surface, 3-min spike proved `TaskResult.messages` is post-hoc sufficient (streaming is Phase 3+ UI work), Path B remains available as a strict superset if later needed. Rollback plan: if Phase 2 dogfood reveals `asyncio.run()` too painful (FastAPI/Jupyter loop-already-running), add `AsyncRecorderProtocol` in v0.3 as a superset without breaking sync callers. **Resolves risks-doc R-4 (async vs sync) without mutating ADR-016.**

### Tests (Round 33)

- `tests/unit/test_adapter_autogen.py` (10 tests): duck-typed `_StubMessage` / `_StubTaskResult` / `_StubTeam` — **does NOT import `autogen_agentchat`** so the core test suite doesn't need the optional dep. Covers: happy-path `submit_result` with multi-message TaskResult producing the right NodeKind chain; `runtime.messages` fallback when `submit_result` is omitted; usage extraction from `models_usage.RequestUsage`; exception during recorded block → failed-shell Run persistence + re-raise; `fork()` raises `AdapterError` citing ADR-017; structural `isinstance(autogen_adapter, AdapterProtocol)` + `isinstance(rec, RecorderProtocol)` conformance; factory `build_recorder(usage_extractor=...)` raises `AdapterError` with the right channel hint; unknown `**adapter_specific` kwarg rejection (R32 Linear pattern); custom `kind_map` overrides merge over defaults; zero-message TaskResult produces Run with 0 nodes (visibility over silent success). Total suite **346/346 pass** (+10 from R32's 336); mypy strict + ruff clean on 24 src files.

### Fixed (Round 33)

- **`SqliteStore.put_run()` + `ON DELETE CASCADE` pitfall documented in adapter code** — discovered while implementing AutoGen recorder: `put_run()` uses `INSERT OR REPLACE`, which at the SQLite level is "DELETE then INSERT"; `nodes.run_id REFERENCES runs(id) ON DELETE CASCADE` means a second `put_run()` in the same transaction cascade-deletes every Node we just inserted. Fix in `autogen/recorder.py::_persist_run_and_nodes`: compute final state + serialized message list BEFORE opening the transaction, then write the Run exactly once as `COMPLETED` with `ended_at` + `final_state` set up front, then insert Nodes. Long inline comment documents the trap for future adapters. **Lesson (now in CONTEXT.md §5 "old facts"): never call `put_run()` twice in the same transaction; if mid-flight status updates are needed later, add an `update_run_status()` store method that doesn't cascade.**

### Added (Round 32)

- **Module-level `AdapterProtocol` instances** — `langgraph_adapter` (`src/chronos/adapters/langgraph.py`) and `linear_adapter` (`src/chronos/adapters/linear/__init__.py`) now ship as importable singletons satisfying `chronos.adapters.protocols.AdapterProtocol` structurally (verified by `isinstance()` via `@runtime_checkable`). Each carries canonical `name` (`"langgraph"` / `"linear"`), `version_constraint` (`">=1.1,<2"` / `""` — empty string per ADR-016 P2 for zero-dep adapters), and a uniform `build_recorder(store, *, kind_map=None, usage_extractor=None, **adapter_specific)` factory. LangGraph routes both `kind_map` and `usage_extractor` to the recorder constructor and raises `AdapterError` on any unknown `**adapter_specific` kwarg. Linear raises `AdapterError` on `kind_map` (lives on `LinearRuntime`, not the recorder) or `usage_extractor` (Linear uses the `__chronos_usage__` state-key hint, not an extractor callback) with a helpful message directing the caller to the right channel; accepts `adapter_name` as the one documented `**adapter_specific` kwarg. Top-level `chronos.adapters` package re-exports both instances + adds them to `__all__`. **First concrete implementations of ADR-016 P2 `AdapterProtocol` — upgrades the Protocol from "contract with no live instance" to "contract with two shipping impls". Prep for future adapter registry / CLI `chronos adapters list` commands; also templates the shape AutoGen's `autogen_adapter` will follow.**

### Tests (Round 32)

- `tests/unit/test_adapter_instances.py` (21 tests, 5 test classes): **TestMetadata** — `name` / `version_constraint` documented values for both adapters. **TestAdapterProtocolConformance** — `isinstance(langgraph_adapter, AdapterProtocol)` + `isinstance(linear_adapter, AdapterProtocol)` + both `build_recorder()` outputs pass `isinstance(rec, RecorderProtocol)`. **TestLangGraphBuildRecorder** — `kind_map` / `usage_extractor` forwarding, default-kwargs path, `AdapterError` on unknown `**adapter_specific`. **TestLinearBuildRecorder** — default adapter_name, custom adapter_name via `**adapter_specific`, three `AdapterError` paths (kind_map non-None, usage_extractor non-None, unknown kwarg). **TestTopLevelExports** — top-level `ca.langgraph_adapter is langgraph_adapter` identity, both in `ca.__all__`, enumerable-roster smoke test. Total suite 336/336 (+21 from R31's 315); 93% coverage; mypy strict + ruff clean.

### Changed (Round 31)

- **`src/chronos/adapters/protocols.py` introduced** (ADR-016 rollout step 2) — single canonical home for `RunRef` / `ForkRef` / `AdapterError` dataclasses and the three documented ADR-016 Protocols (`RecorderProtocol`, `AdapterProtocol`, `NodeIdentityResolver`). All three Protocols carry `@runtime_checkable` for cheap `isinstance()` smoke tests; real signature-level conformance is still verified by the existing `inspect.signature` tests in `tests/unit/test_adapter_linear.py`. **Strictly additive / backward-compatible**: `chronos.adapters.langgraph` and `chronos.adapters.linear.recorder` now re-import `RunRef` / `ForkRef` / `AdapterError` from the new module and re-export them unchanged; any existing import path (`from chronos.adapters.langgraph import RunRef`, `from chronos.adapters.linear import AdapterError`, etc.) keeps working. The top-level `chronos.adapters` package now also exposes the three Protocols + the shared dataclasses/error for direct import. Eliminates the R28 L4 pre-existing tech-debt ticket (two parallel `RunRef` / `ForkRef` / `AdapterError` class hierarchies) before the AutoGen adapter lands and adds a third.

### Added (Round 31)

- **`tests/unit/test_adapter_protocols.py`** (~220 LOC, 22 tests). Four test classes covering: (1) **canonical-identity** — `lg_mod.RunRef is RunRef`, `lin_mod.ForkRef is ForkRef`, `lg_mod.AdapterError is AdapterError` and `lin_mod.AdapterError is AdapterError` via literal `is` identity assertions, plus cross-adapter `isinstance` compatibility; (2) **dataclass-shape** — default field values, `node_ids` list is not shared between instances (`default_factory` correctness), `ForkRef` requires positional args; (3) **Protocol conformance** — `LangGraphRecorder` / `LinearRecorder` pass `isinstance(x, RecorderProtocol)` via `@runtime_checkable`, duck-typed stubs satisfy `AdapterProtocol` and `NodeIdentityResolver`, `cast(RecorderProtocol, rec)` smoke test exercises ADR-016 rollout step 2's type-safety claim on both adapters; (4) **public-surface** — `protocols.__all__` is exhaustive, `chronos.adapters` package-level `__all__` advertises all seven public names (3 Protocols + 2 dataclasses + `AdapterError` + `LangGraphRecorder`).

## [0.2.0a0] — 2026-04-24 (Round 24 + Round 25 + Round 26 + Round 27 + Round 28 + Round 29 + Round 30)

**Theme**: Phase 2 entry bundle. Six rounds of contract formalisation + one dogfood + one reference adapter + one release cut. ADR-014 scorecard: **R1 ✅ / R2 ✅ / R3 ✅ / R4 ✅ — 4/4 green, Phase 2 formally unblocked.** Adapter interface (ADR-016) + extractor contract v2 (ADR-015) are now the stable v0.2.x public contracts for framework authors; first reference adapter (Linear pipeline, zero-dep) ships as the concrete R1 impl; multi-framework risks catalog (R27) stands as the Phase-2 gotchas reader; dual-adapter CI dogfood (R29) enforces the interface by running two implementations through it. Zero new features beyond what R24-R29 already landed — R30 is a pure packaging cut.

### Release (Round 30)

- `__version__` / `pyproject.toml::version` / CLI status line bumped `0.1.6` → `0.2.0a0`. CLI status string updated to reference Phase 2 entry: "Phase 2 entry — adapter interface stable (ADR-016), reference Linear adapter, dual-adapter CI dogfood (ADR-014 4/4 green), v0.2.0a0". No feature code changed in R30 — all the substance was landed R24-R29 and sat in `[Unreleased]` until this cut.

### Added (Round 29)

- **Dual-adapter CI dogfood** (`tests/integration/test_dual_adapter_dogfood.py`, ~540 LOC, 4 tests). Three scenarios run symmetrically against both `LangGraphRecorder` and `LinearRecorder` via a deterministic `FakeLLM`, asserting equivalence at the persisted `Run` / `Node` / `Fork` row level (not in-memory adapter state): **Scenario A** — record 4-step research→draft→critique→polish pipeline, both adapters produce equivalent `Run + 4×Node` with sequential `parent_node_id` chain (targets risks-doc R-1 event-model drift); **Scenario B** — fork at the `research` node with `{"research": "HIJACKED-research"}` override, asserts both adapters (LangGraph via `update_state(as_node=...) + invoke(None, …)` checkpointer resume; Linear via re-execution from the override point) produce child runs whose first node carries the override through to `state_after`, validating ADR-016's **postcondition-only** fork contract (targets R-2 fork portability); **Scenario C** — usage metering with matching sha256-derived fake tokens wired via `UsageExtractor` callback on LangGraph side and `__chronos_usage__` state-key hint on Linear side, asserts identical `Node.usage` rows across both adapters (targets R-3 usage gaps). Plus one trivial sanity marker test. **Resolves ADR-014 R3 ✅ — the 4th and final Phase-2 entry criterion is now green. ADR-014 scorecard: R1 ✅ / R2 ✅ / R3 ✅ / R4 ✅ — Phase 2 formally unblocked at R30.**

### Changed (Round 29)

- **`LinearRecorder` usage-hint API generalized** (`src/chronos/adapters/linear/recorder.py`). The `__chronos_usage__` state-dict key now accepts three shapes for parity with the LangGraph adapter's ADR-015 `UsageResult` contract: `dict` (unpacked into `Usage(**hint)`); `Usage` instance (used as-is); or any duck-typed object exposing `prompt_tokens` / `completion_tokens` / `reasoning_tokens` / `cost_usd_cents` / `model_name` attrs (e.g. the adapter-layer `UsageResult` dataclass — imported via duck typing to avoid a hard dep from this zero-dep adapter onto `langgraph_usage.py`). Previous behavior (dict-only) is preserved as one of the three branches; all existing tests unchanged. **This gap was surfaced by the Round 29 dogfood test (Scenario C) — a concrete secondary win of ADR-014 R3's "test the interface by running two implementations through it" mandate; exactly the kind of asymmetry unit tests on either adapter in isolation could not catch.** Docstring §"Usage metering" updated to enumerate all three accepted shapes and explain the duck-typing rationale.

### Docs (Round 29)

- **R29 verdict section appended to `docs/research/multi-framework-risks.md`** (~80 LOC). Each risk updated with post-dogfood verdict: **R-1** ⚠️ partially confirmed (persisted-shape equivalence proven but Linear is a LangGraph simplification by construction — true event-model divergence requires AutoGen; severity unchanged at Medium); **R-2** ✅ confirmed sufficient (postcondition-only fork contract is the correct abstraction; severity lowered High → Medium-Low, effectively resolved for Phase 2); **R-3** ⚠️ API parity achieved + Linear adapter gap fixed as above, real-LLM provider parity testing still future work (severity unchanged at Medium); **R-4** / **R-5** / **R-6** unchanged (not exercised by R29); **no new risks (R-7) surfaced** — all failures encountered during R29 were test-author typos (field name `parent_node_id` vs. `parent_id`) or the R-3 API gap, not architectural surprises. Final ADR-014 checklist delta section recording all 4/4 criteria green.

### Added (Round 28)

- **Linear-pipeline reference adapter** (`src/chronos/adapters/linear/`, ~385 LOC across `__init__.py` + `recorder.py`, zero external dependencies). Implements ADR-016 `RecorderProtocol` with the same public shape as `LangGraphRecorder`: `record(runtime, *, thread_id, …)` and `fork(runtime, *, parent_run_id, at_node_id, overrides, child_thread_id, …)` context managers, populating `RunRef` / `ForkRef` dataclasses on exit. `LinearRuntime` is a plain ordered list of `(node_name, step_fn: dict → dict)` pairs with duplicate-name detection; `LinearRecorder` iterates steps inline, captures `state_before / state_after` per step into `Node` rows, persists `Run + Nodes + Fork` in a single `store.transaction()`. Fork semantics mirror the Protocol postcondition (parent `state_after` + `overrides` → seeded state → re-execute `runtime.steps[fork_index+1:]`); no checkpointer involved, validating R27 risks-doc R-2 mitigation (fork-by-re-execution is a legal mechanism). Optional usage metering via a `__chronos_usage__` dict key in a step's return value — extracted into `Node.usage` and popped from `state_after` to keep diffs clean (matches ADR-015 Layer 1 `UsageResult MAY be None` semantics). Failed step functions persist a zero-node `status=FAILED` Run shell for visibility then re-raise; contract violations (non-dict return, mismatched parent run/node, same-thread-id fork, duplicate node names) raise `AdapterError`. **Resolves the *implementation* half of ADR-014 R1** — the contract (R26) + impl (R28) are both green. **ADR-014 scorecard: R1 ✅ / R2 ✅ / R3 ❌ / R4 ✅ — 3/4 green, R29 closes R3.**

### Tests (Round 28)

- `tests/unit/test_adapter_linear.py` (25 tests, 99% coverage on the new module): `TestLinearRuntime` (4: duplicate-name rejection, `step_index_of` lookups, kind_map default); `TestRecordHappy` (7: single-step persistence, multi-step parent-id chain, default empty initial_state, kind_map application, usage-hint extraction+pop, task/tags propagation, num_steps metadata); `TestRecordErrors` (2: non-dict return → `AdapterError`, exception → failed shell Run); `TestFork` (8: middle-node tail resume, last-node empty child, unknown parent/node validation, cross-parent at_node_id, same-thread-id rejection, non-linear parent rejection, fork-time step exception → failed child); `TestProtocolConformance` (4: `inspect.signature` shared-kwargs check vs. `LangGraphRecorder` for both `record()` and `fork()`, plus `RunRef`/`ForkRef` lifecycle shape). Total suite **289/289 pass, 94% coverage** (up from 264/264, 93%).

### Added (Round 27)

- **Research note — Multi-Framework Portability Risks** (`docs/research/multi-framework-risks.md`, ~14 KB). First document in a new `docs/research/` tree, distinct from ADRs because the content is a living risk register (with review cadence appending verdicts as adapters land), not a single Accepted decision. Catalogs **six risks** the adapter interface (ADR-016) contract alone cannot answer: **R-1** event-model drift (Medium; LangGraph checkpoint snapshots vs. AutoGen message stream vs. CrewAI task DAG — owner ADR-016, mitigated by `NodeIdentityResolver` + explicit \"no cross-framework diff invariant\" non-promise); **R-2** fork primitive fundamentally non-portable (**High**; ADR-016 `fork()` Protocol intentionally specifies *postcondition only* — child run starts from parent `state_after` + overrides — not mechanism; Phase 2 red line: no `chronos.core.*` may call LangGraph checkpointer methods; adapters without fork support must raise `AdapterError(\"fork not supported\")` at call time, citing R23-A `InMemorySaver` empirical trap); **R-3** usage metering gaps (Medium; ADR-015 Layer 1 already permits `UsageResult=None`, Layer 4 accumulation policy invariant — CI double-dogfood at R28-R29 will assert non-zero usage for real-LLM runs, citing R18 multi-LLM-per-node undercount that inspired ADR-012); **R-4** async vs sync execution (Medium; Deferred ADR-017 triggered by the first AutoGen adapter PR — parallel `AsyncRecorderProtocol` hierarchy, not a mutation of the sync Protocol); **R-5** deterministic replay not cross-framework (Low, Phase 3; `chronos replay` gains an `--adapter langgraph` guard at R28-R29, defaulting to error-with-helpful-message on non-LangGraph runs); **R-6** side-effect strategy (Low, Phase 3; status quo of `fork plan --emit python` stub with explicit TODO blocks is the correct UX, defers `@chronos.pure` taxonomy to a speculative ADR-019). Includes summary table, Phase 2 entry checklist delta (**3/4 contract+doc criteria now green** after R27; R1 impl + R3 remain as R28-R29), and review-cadence clause committing to append pass/fail verdicts when the reference adapter lands. **Resolves ADR-014 R4** — the final contract/doc-side Phase 2 entry criterion. No code changes.

### Added (Round 26)

- **ADR-016 — Adapter Interface (Protocol-Based Contract for Framework Recorders)** (`docs/decisions/ADR-016-adapter-interface.md`, ~15 KB, Accepted). Defines three `typing.Protocol` classes in a future `src/chronos/adapters/protocols.py`: **`RecorderProtocol`** (framework-agnostic `record()` / `fork()` context-manager contract with five lifecycle invariants — atomicity, idempotency, `AdapterError` as the only legal framework-leak, silent-noop on empty runs, failed-run persistence + re-raise); **`AdapterProtocol`** (module-level plugin shape: `build_recorder()` + `name` + `version_constraint` + `**adapter_specific` pressure-release kwargs); **`NodeIdentityResolver`** (Phase-2-facing hook for per-framework `(node_name, node_kind)` derivation). Includes a framework-portability table (LangGraph / AutoGen / CrewAI) across six axes (execution model, node identity, state, fork primitive, usage origin, determinism), five rejected alternatives (`abc.ABC` base class, single merged Protocol, drop `NodeIdentityResolver`, fold `UsageExtractor` into Recorder, typed `Runtime` Protocol), and a five-step rollout ending in ADR-014 gate check. Parameter rename `graph=` → `runtime=` at the contract level; `LangGraphRecorder` keeps `graph=` as a positional-compatible alias so no user call sites break. **Resolves the *contract* half of ADR-014 R1** (4/4 Phase 2 entry criteria: R1 contract ✅ / impl ❌, R2 ✅, R3 ❌, R4 ❌). No code changes in this round — contract precedes implementation deliberately.

### Changed (Round 26) — roadmap alignment

- `docs/roadmap.md` large refresh correcting ~18 rounds of checkbox drift. **Phase 1** header now reads "✅ COMPLETE (shipped through R25; current tag `v0.1.6`)" with a retrospective note on the 25+-round actual duration vs. 6-10-round estimate, attributing the overrun to (a) pulling forward usage extraction (ADR-009 → ADR-015), (b) three dogfood rounds, (c) fork-CLI reshape (ADR-008, ADR-013), (d) R24-R26 contract formalisation. **M1.1 / M1.2 / M1.3** checkboxes updated from `[ ]` to `[x]` with round attribution (spike outcomes merged into per-round progress docs, not a standalone `spikes-result.md`; `make`/`just` explicitly de-scoped as `uv run` covers the gap). **M1.4** usage-extraction sub-bullet added (originally deferred to M2, delivered ahead in Phase 1 via ADR-009 → ADR-015). **M1.7** (Replay) and **M1.8** (Diff + fork CLI) and **M1.9** (Documentation + Release) all updated to ✅ DONE with ADR-008 / ADR-013 / ADR-006 / ADR-007 cross-references and a note that the shipped `fork plan` interface supersedes the original `--set-state k=v` design. **Phase 2** key-milestones section rewritten: replaced the stale "AutoGen adapter (ADR-005 on adapter interface)" bullet (ADR-005 is fork semantics; never was the adapter interface) with an ADR-014 criteria status table (R1/R2/R3/R4 with per-gate target rounds) and an updated top-of-phase bullet referencing ADR-016 and explicitly allowing a minimal linear-pipeline adapter as the R1 impl reference. **Footer** gains a "drift detected mid-phase → refresh immediately" rule (lesson learned: 18 rounds elapsed between last refresh and this one).

### Added (Round 25)

- **ADR-015 — Extractor Contract v2 (Framework-Agnostic Consolidation)** (`docs/decisions/ADR-015-extractor-contract-v2.md`, ~17 KB, Accepted). Consolidates ADR-009 (R12 hook), ADR-010 (R15 native extractors), ADR-011 (R17 serialization boundary), ADR-012 (R18 multi-LLM-per-node) into a single five-layer contract: **Layer 1** data shape (`UsageContext` / `UsageResult` frozen dataclasses, framework-agnostic invariant); **Layer 2** protocol & lifecycle (six lifecycle invariants including "a buggy extractor must NEVER abort a recording"); **Layer 3** serialization boundary (recursive pydantic→dict `_jsonable` algorithm, invariant across all adapters); **Layer 4** multi-call-per-node delta-accumulation policy (invariant; slicing SHAPE is framework-specific); **Layer 5** convenience extractor naming + provider field-mapping tables (Anthropic / OpenAI / LangChain std) + duck-typing rule + `cost_usd_cents = None` default. Includes a framework-portability matrix showing exactly which layers AutoGen / CrewAI adapters must honor verbatim vs. specialize. Resolves ADR-014 R2 ✅ (1/4 Phase 2 entry criteria now green).

### Changed (Round 25) — ADR breadcrumbs

- `ADR-009-usage-extractor-hook.md`, `ADR-010-native-usage-extractors.md`, `ADR-011-state-serialization-boundary.md`, `ADR-012-multi-llm-per-node-usage.md` each gain a `Consolidated into: ADR-015 (R25)` header line pointing future readers at the authoritative spec while preserving the original decision context. No content changes to the predecessor ADRs beyond the breadcrumb — they remain the historical record for *why* each layer of the contract was adopted.

---

### Added (Round 24)

- **ADR-014 — Phase 2 Entry Criteria** (`docs/decisions/ADR-014-phase-2-entry-criteria.md`). Formalises when Phase 2 (AutoGen adapter, Web UI, multi-agent lanes) is allowed to begin. Four **required** criteria: R1 adapter interface frozen (with ADR + one non-trivial change implementable without touching `chronos.core.*`), R2 extractor contract v2 consolidated into a single ADR, R3 one *adversarial* LangGraph dogfood (candidate: `.astream_events` streaming, explicitly flagged untested in R17 case study), R4 `docs/CONTEXT.md` §4 refreshed for Phase-2 operational red lines. Three **optional** confidence-raisers: O1 second LLM backend exercised, O2 external user signal, O3 performance baseline. All four required are ❌ as of R24 — non-binding work breakdown puts Phase 2 opening around R29. Ties back to R10 near-miss (agent caught itself mid-`uv add autogen-agentchat` under "自由发挥") by replacing vibe-based discipline with a falsifiable checklist.

### Fixed (Round 24) — test harness color-env pollution

- `tests/conftest.py` (new file) adds a top-level autouse fixture that neutralises five shell color env vars (`FORCE_COLOR`, `NO_COLOR`, `CLICOLOR`, `CLICOLOR_FORCE`, `PY_COLORS`), sets `TERM=dumb`/`COLUMNS=80`, and monkeypatches the module-level `chronos.cli._common.console` **and** `chronos.cli.console` to a fresh no-color `Console(force_terminal=False, no_color=True, color_system=None, width=80, highlight=False)`. Restores automatically per pytest `monkeypatch` semantics. Fixes v0.1.6 demo-report Finding #1: five CLI tests (`test_{diff,runs,replay}_help_surfaces`, `test_cli_fork_plan_json_to_stdout`, `test_cli_fork_plan_emit_python_writes_valid_stub`) failed when developers ran `pytest` with `FORCE_COLOR=1` exported (common for terminal-capture workflows), because `rich` emitted ANSI sequences that broke `substring in result.stdout` assertions across line wraps. The fix is test-harness-only; user CLI invocations retain colors as before. Verified: **264/264 pass with `FORCE_COLOR=1` set**.

---

## [0.1.6] — 2026-04-23 (Round 23-A + Round 23-B + Round 23-C)

**Theme**: R22's `fork plan --emit python` survives first real use. Dogfood of the feature against the R17 supervisor baseline (parent run `69932676-5b33...`) surfaced three bugs the R22 tests missed (they only `compile()`-checked, never `exec`-ed), plus one DX pitfall worth documenting. All four addressed before cut.

### Fixed (Round 23-A) — `fork plan --emit python` stub executability

Three bugs in the generated stub template, caught by real end-to-end use:

- Stub used `ref.run_id`, but `ForkRef` exposes `child_run_id` (plus `fork_id`, `node_ids`). Any real execution of the stub would `AttributeError` at the final print line. Now correctly uses `ref.child_run_id`.
- Final `print(...)` was placed *inside* the `with recorder.fork(...)` block, but `ForkRef` fields are populated on context-manager **exit** — so the print always fired before population and printed `None`. Print moved below the `with` block with a comment explaining the lifecycle.
- Example import/construction comments suggested `from chronos.store.sqlite import SqliteStore` + `SqliteStore("..."); store.open()`, neither of which is the public API. Corrected to `from chronos.store import SqliteStore` + `SqliteStore.open(path)` context-manager idiom.
- CLI `render_plan_preview` previously printed the same `consume in code with from chronos.fork_plan import load_plan` hint for both `--emit json` and `--emit python`. Now emit-aware: the python path tells users to fill the two `TODO(user)` blocks and `python <stub>`.

### Added (Round 23-C) — checkpointer-persistence warning in the stub

The stub's graph `TODO(user)` block now includes an `IMPORTANT:` note explaining that child runs only step through graph nodes if the parent and the fork share a persistent or cross-call-live LangGraph checkpointer. An `InMemorySaver` rebuilt per factory call registers the fork record but produces `node_ids=[]`. Note recommends `SqliteSaver.from_conn_string(...)` and points at the case study.

### Documentation (Round 23-B)

- New case study: `docs/case-studies/fork-via-emit-python.md` walks through the full use-in-anger path — generate → fill → run → inspect — with the three R22 bugs and the checkpointer-persistence pitfall explained in detail. Also revisits why ADR-008 / ADR-013 chose the stub-emission path over execute-fork automation.

### Tests

- `test_fork_plan.py` gained 4 regression tests (22 → 26): one actually `exec`s the stub with a mocked recorder + graph and asserts the print line reaches stdout with the correct value; three assert text-level invariants (correct imports, correct `ref` field, checkpointer warning present).
- `test_fork_cli.py` assertion for the stale "paste-ready Python stub written to" message replaced with the new preview-based hint check.
- Full suite: **264 / 264 pass, 93% coverage**, ruff/format/mypy all green.

### Evidence

End-to-end verified: `chronos fork plan 69932676-5b33... --emit python --out fork_stub.py --db dogfood.db` → fill 2 TODO blocks → `python fork_stub_filled.py` → new child run `16ca0fa5-cbec-418b-bd47-7a9546048b01` + fork `f6b36f40-82c3-45d8-9386-5b8a4e7b393c` land in the DB alongside the parent.

---

## [0.1.5] — 2026-04-23 (Round 21 + Round 22)

**Theme**: ADR-013 landed + ADR-013 deferred alt C shipped. After three rounds of dogfood weak-consistent evidence (R17/R18/R20), Chronos formally freezes `fork=JSON-only` (ADR-013), then ships the middle-ground path the evidence suggested: `chronos fork plan --emit python` generates a self-contained, pastable stub that inlines fork kwargs as Python literals. No execute-fork crossed.

### Added (Round 22) — `fork plan --emit python`
- New CLI option: `chronos fork plan <run_id> ... --emit python` writes a paste-ready Python stub (default `./fork_stub.py`, override with `--out`). Default `--emit json` unchanged.
- New public API: `ForkPlan.to_python(*, recorder_var="recorder", graph_var="graph") -> str` renders the plan as valid Python 3.11+ source. Callable from user code without going through the CLI.
- Stub includes: provenance docstring (parent_run_id, parent_node, chronos_version, generated_at); two `TODO(user)` markers for Recorder + graph construction; fork kwargs inlined as Python literals (no JSON file dependency at runtime); `graph.invoke(None, {"configurable": {"thread_id": ...}})` call sample; final `print(f"fork child run: {ref.run_id}")`.
- 10 new tests: 7 unit (valid Python, inlined kwargs, TODO markers, provenance, custom variable names, no-reason placeholder, trailing-newline contract) + 3 CLI (end-to-end stub file, default filename, invalid format error).
- Implements ADR-013 deferred alternative C: middle ground between raw JSON (too bare) and execute-fork (ADR-008 rejected, ADR-013 frozen).

### Added (Round 21) — `Node.model` convenience property
- New read-only property `Node.model` returns `self.model_name`. Shorter, canonical form. Prefer `node.model` in user code.
- Docstring cross-refs added to `Usage` class and `Node.usage` field, explicitly calling out that `model_name` is **not** a `Usage` field — it lives on `Node`. Addresses R20 Finding #2 (three independent dogfood scripts wrote `node.usage.model_name` and got `None`).
- 3 new tests guard the property + enforce the guardrail that `Usage.model_name` stays rejected (ADR-013 affirmation).

### Documentation (Round 21) — ADR-013 (fork auto-execution: stay frozen)
- ADR-013 formalizes the stop-thinking-about-it decision on execute-fork, based on R17+R18+R20 three-round weak-consistent dogfood evidence (zero execute-fork demand across supervisor / swarm / bigtool topologies).
- Affirms ADR-008 "fork=JSON-only" boundary; documents explicit trigger conditions for reopening.
- Third-party case study: `docs/case-studies/langgraph-bigtool.md` (R20 dogfood #3).

### Tests
- 250 → 260 (+10).
- Coverage: 93% (unchanged).
- `src/chronos/fork_plan.py` coverage: 99% (was 99%).

---

## [0.1.4] — 2026-04-23 (Round 17 + Round 18)

**Theme**: Real-world dogfood finds silent token undercount. Two consecutive rounds of using Chronos on real 1000+ ★ LangGraph ecosystem libraries (`langgraph-supervisor-py`, `langgraph-swarm-py`) surfaced bugs that 242 green unit tests had not caught. Numbers that looked valid were wrong by up to ~50%. Now fixed.

### Fixed (Round 18) — multi-LLM-per-node token accumulation (ADR-012)
- All three LangGraph usage extractors (`aimessage_usage_extractor`, `anthropic_usage_extractor`, `openai_usage_extractor`) previously used "last AIMessage wins" semantics, which silently under-counted tokens by 30-70% on graphs where a single super-step issues multiple LLM calls. Swarm-style graphs (`create_react_agent` sub-graphs embedded in a parent swarm) are the most common trigger.
- Concrete evidence: on `langgraph-swarm-py`, Bob-node usage was reported as `1222 prompt + 99 completion` when the true usage was `2275 + 211` (46% of prompt tokens, 53% of completion tokens silently dropped).
- **Fix**: extractors now diff `UsageContext.post_values["messages"]` against `UsageContext.pre_values["messages"]` and sum usage across **all** new `AIMessage` objects, not just the last one. `UsageContext.pre_values` was exposed in R15 (ADR-011) but had never been used — R18 makes it earn its keep.
- No public API change. No data-model change. Preserves all prior semantics (cache tokens fold into `prompt_tokens`; `reasoning_tokens` sub-field of `completion_tokens`; `None` for non-LLM nodes).
- ADR-012 — multi-LLM-per-node usage accumulation (extends ADR-009 contract without signature change).
- 5 regression tests added: swarm Bob-node scenario, pre-history protection, OpenAI path, non-LLM node `None` return, initial-step fallback.
- R17 supervisor dogfood re-run confirms no regression; `research_expert` now reports `1957+283` (was `1755+271` — a previously-unnoticed ~10% undercount in the old code path, also now accurate).
- Case study published: `docs/case-studies/langgraph-swarm.md`.

### Fixed (Round 17) — state serialization + JSON-to-pydantic coercion (ADR-011)
- First real-world dogfood target: `langgraph-supervisor-py`. Three showstopper bugs surfaced on the very first run, all of them invisible to the unit suite.
- `LangGraphRecorder` now recursively coerces pydantic models to `dict` before SQLite write-back (`TypeError: Object of type HumanMessage is not JSON serializable`). Extractors now accept both `AIMessage` pydantic objects and dict-coerced messages (ADR-011).
- Case study published: `docs/case-studies/langgraph-supervisor.md`.

### Numbers
- Tests: 236 → **247 pass** (+5 R17 regression, +6 R18 regression; 2 R18 tests renamed in-place since semantics changed from "last wins" to "sum all new"). Coverage **93%**. Ruff + format clean.
- Version bumped `0.1.3` → `0.1.4` in `src/chronos/__init__.py` and `pyproject.toml`.
- CLI status line updated: `"Phase 1 M1.11 — usage extractor hook + native Anthropic/OpenAI adapters + multi-LLM-per-node accumulation, v0.1.4"`.
- Git tag `v0.1.4` pushed to `origin` (private repo, gh-proxy.com mirror).

### Notes
- No schema changes. `UsageExtractor` Protocol signature from ADR-009 unchanged — R18 only extends the documented accumulation semantics.
- M1.11 milestone kept (R17 + R18 fix latent bugs in the same capability; not a new milestone).
- ADR-008 (execute-fork boundary): 2 consecutive dogfood rounds produced **zero** demand for auto-executing forked plans. Boundary stays frozen — evidence now based on real usage, not speculation.
- **Core lesson (now project DNA)**: N green unit tests + M showstopper bugs can coexist; unit tests do not replace dogfood. R18 re-validated this even *after* R17 had sharpened the tests.

---

## [0.1.3] — 2026-04-23 (Round 14 + Round 15 + Round 16)

**Theme**: Three-extractor family + Anthropic prompt caching fidelity. The `usage_extractor` hook shipped in v0.1.2 now has first-class convenience implementations for the two most common LLM SDKs alongside the LangChain-standard one — and the interior CLI was split up so further growth stays tractable.

### Added (Round 15) — native Anthropic / OpenAI usage extractors (ADR-010)
- `chronos.adapters.langgraph_usage.anthropic_usage_extractor` — reads `AIMessage.response_metadata["usage"]` (the shape Anthropic's SDK produces); folds `cache_creation_input_tokens` + `cache_read_input_tokens` into `prompt_tokens`. (Anthropic's API reports cache tokens **separately** from `input_tokens`; forgetting to sum them under-reports prompt usage by 10-100× when prompt caching is on.)
- `chronos.adapters.langgraph_usage.openai_usage_extractor` — reads `AIMessage.response_metadata["token_usage"]` (OpenAI Chat Completions shape); captures `completion_tokens_details.reasoning_tokens` as a sub-detail so `prompt_tokens + completion_tokens == total_tokens` stays invariant (o1 / o3 models).
- Both new extractors implement the existing `UsageExtractor` Protocol from ADR-009 — **zero** protocol change, pure additive feature. Cross-provider composition via the documented `anthropic or openai or aimessage` short-circuit pattern.
- Duck-typed: no hard dependency on the `anthropic` or `openai` SDK packages (users without them can still use the extractors).
- ADR-010 — native usage extractors design (chose sibling extractors over extending `aimessage_usage_extractor` / automatic cascade / hard-dep typed responses).
- 21 new unit tests: 8 anthropic + 7 openai + 3 composition pattern. Totals: **236/236 pass, 94% coverage**; `langgraph_usage.py` at 100%.
- Docs: `docs/getting-started.md` §4b rewritten with three-extractor family; `docs/cli-reference.md` token-usage section gets an extractor comparison table.

### Refactored (Round 14) — CLI file split
- `src/chronos/cli/__init__.py`: **848 → 348 lines (-59%)**, command groups split into sibling modules.
- New shared helpers: `cli/_common.py` (DB open + serialise + shared `console`) and `cli/_usage.py` (usage summary dataclass).
- Per-command impl modules: `cli/runs.py`, `cli/forks.py`, `cli/diff.py`; joining the already-split `cli/replay.py` and `cli/fork.py`. All expose `*_command(console, open_store_fn, ...)` with DI — pattern frozen for future commands.
- `__init__.py` now only does typer app registration + thin wrappers. **Zero** test changes required — the refactor is validated by the existing suite staying green.
- No new ADR (pure refactor). No version bump at the time (bundled into v0.1.3).

### Added (Round 16) — v0.1.3 release cut
- Version bumped `0.1.2` → `0.1.3` in `src/chronos/__init__.py` and `pyproject.toml`.
- CLI status line updated: `"Phase 1 M1.11 — usage extractor hook + native Anthropic/OpenAI adapters, v0.1.3"`.
- Git tag `v0.1.3` pushed to `origin` (private repo, gh-proxy.com mirror).
- No code changes this round — pure release packaging for R14 + R15 work.

### Notes
- No schema changes. `UsageExtractor` Protocol from ADR-009 unchanged — this release proves the protocol accommodates multiple implementations cleanly.
- M1.11 milestone kept (R15 is extension of the same capability, not a new milestone).

---

## [0.1.2] — 2026-04-23 (Round 12 + Round 13)

**Theme**: Token usage & cost visibility. The four-verb loop (record/replay/fork/diff) gains a sibling capability — **know what each run cost**.

### Added (Round 12) — M1.11 usage extractor hook + CLI token/cost surfaces
- `usage_extractor: UsageExtractor | None` kwarg on `LangGraphRecorder.__init__` — callable protocol `(UsageContext) -> UsageResult | None` invoked per node to populate the previously-dormant `Node.usage` and `Node.cost_usd_cents` schema fields (added in M1.1, zero references until now).
- New module `chronos.adapters.langgraph_usage` — `UsageContext` / `UsageResult` frozen dataclasses, `UsageExtractor` Protocol, plus `aimessage_usage_extractor` convenience implementation that reads LangChain `AIMessage.usage_metadata` / `response_metadata`.
- Failure tolerance: extractor raises are logged at WARNING and stored as `usage=None` — capture never breaks (tested).
- `chronos runs show <id>` — total-usage summary line + per-node inline token counts when data is present.
- `chronos runs list --with-usage` — opt-in flag adds `tokens` and `cost¢` columns (per-run SUM). Opt-in because it costs one extra node-fetch per row.
- `chronos diff A B --show-usage` — side-by-side A vs B vs Δ token/cost table, colorized (green = savings, red = regression). JSON mode gains a `usage` subtree with deltas.
- `_node_to_dict` (JSON output) always exposes `usage` and `cost_usd_cents` when populated — machine readers get it free.
- Examples updated: both `examples/linear_pipeline.py` and `examples/router_loop.py` wire a demo extractor and print `--with-usage` / `--show-usage` in their "Try these commands" block (dogfood auto-picks them up).
- ADR-009 — usage-extractor hook design (chose callable protocol over global callback / adapter subclass / middleware chain / runtime LLM-call interception).
- 21 new unit tests (`test_usage_extractor.py`): dataclass frozen semantics, `aimessage_usage_extractor` happy-path + edge cases, hook null/None/success/raise paths, CLI rendering. Totals: **216/216 pass, 94% coverage**.

### Notes
- No schema changes — pure fill of existing-but-unused fields, fully backward compatible (runs without an extractor keep recording identically).

### Added (Round 13) — v0.1.2 release cut
- Version bumped `0.1.1` → `0.1.2` in `src/chronos/__init__.py` and `pyproject.toml`.
- Git tag `v0.1.2` pushed to `origin` (private repo, gh-proxy.com mirror).
- No code changes this round — pure release packaging per R12 plan.

---

## [0.1.1] — 2026-04-23 (Round 10 + Round 11)

Phase 1 follow-up: the **record / replay / fork / diff four-verb loop** is now end-to-end in CLI (not just library). Shipped in two rounds:

### Added (Round 11) — M1.10 `chronos fork` CLI + fork plan artifact
- `chronos fork plan <run_id>` — emit a portable **fork plan** JSON artifact describing a proposed fork (parent run, fork-point node, overrides, child thread id, reason, tags). CLI never executes user code; plans are consumed via `chronos.fork_plan.load_plan()` in the user's script, which then calls `recorder.fork(graph, **plan.recorder_kwargs())`. Fork-point selectable via `--at-node <name>` (unique-name check), `--at-index <k>` (step index, always unambiguous), or `--at-node-id <uid>`.
- Override ergonomics: repeatable `--override k=v` (JSON-parsed first, falls back to raw string), `--override-json '{...}'` for bulk merges, `--allow-new-keys` to opt out of the default "reject unknown keys" typo guard.
- `--out <path>` (default `./fork_plan.json`) for file output with Rich preview; `--json` for stdout streaming (pipe-friendly).
- New `chronos.fork_plan` module: `ForkPlan` dataclass, `load_plan()`/`dump_plan()` helpers with schema version + `recorder_kwargs()` adapter that returns exactly the kwargs accepted by `LangGraphRecorder.fork()`. Deep-copies overrides to prevent plan mutation.
- ADR-008 — `chronos fork` CLI plan-artifact design (chose plan-file over inspection-only, over `--script` dynamic import).
- 55 new unit tests (`test_fork_plan.py` + `test_fork_cli.py`). Totals: **195/195 pass, 93% coverage**. Dogfood: **14/14 green** (2 new fork-plan commands auto-picked up from examples).

### Added (Round 10) — M1.7 replay TUI + dogfood CI
- `chronos replay <run_id>` — interactive step-through of any recorded run. Uses `rich.live` for the TUI; keyboard controls: `space`/`→` next, `←` prev, `home`/`end` jump, `q` quit. Falls back to static node-by-node rendering when stdin/stdout isn't a TTY (CI, pipes, `tee`). `--no-interactive` forces static mode.
- `scripts/dogfood.sh` — end-to-end dogfood: runs every `examples/*.py`, extracts the "Try these commands:" block, re-executes each suggested command, and scans for `chronos --db` docstring drift (the R9 bug class). Wired into GitHub Actions CI on Python 3.11.
- ADR-007 — replay TUI framework selection (`rich.live` chosen; `textual`, `prompt_toolkit`, `curses`, pager-only rejected with rationale).
- 26 new unit tests for the replay module (pure render + cursor logic + Typer CLI).

### Notes
- With M1.7 + M1.10 shipped, the record/replay/fork/diff "four-verb loop" is now end-to-end **in CLI** (not just library). Candidate tag: **v0.1.1**.

---

## [0.1.0] — 2026-04-23 (Round 9)

First tagged release. Phase 1 MVP complete: record → fork → diff across a LangGraph agent, all inspectable from the CLI.

### Added (Round 8/9) — M1.9 examples, docs, release polish
- `examples/linear_pipeline.py` — runnable LangGraph 5-node agent demoing record → fork → diff with a deterministic fake LLM (no API key required).
- `examples/router_loop.py` — runnable LangGraph agent with a conditional edge loop, demoing fork-forced early exit and how the diff aligner handles repeated node names.
- `examples/_fake_llm.py` — pure-function FakeLLM for deterministic demos.
- `docs/getting-started.md` — 5-minute onboarding walkthrough from install to `chronos diff`.
- `docs/cli-reference.md` — every CLI command, flag, exit code, and environment variable documented.
- Rewrite of `README.md` with real install instructions, quickstart, current milestone table, and development commands.
- `.gitignore` now excludes `examples/chronos.db` and `*.db-journal` so demo DB churn isn't committed.

### Fixed (Round 9)
- Docstring drift: `chronos --db X cmd` → `chronos cmd --db X` in three example docstrings (R8 missed these; dogfood script in R10 now catches this class of bug).

---

## [0.0.x] — Internal pre-release (Rounds 1–7)

### Added (Round 7) — M1.8 structural diff
- `chronos.core.diff` module (`DiffEntry`, `DiffReport`, `align_nodes`, `diff_runs`).
- `chronos diff <run_a> <run_b>` CLI command with `--json`, `--verbose`, `--full`, and fork-aware default slicing.
- ADR-006 — diff alignment algorithm (`difflib.SequenceMatcher` over `node_name` sequence) + frozen JSON schema.
- 30 new tests (21 diff unit + 9 CLI integration). Total: 112/112 pass, 92% coverage.

### Added (Round 6) — M1.6 CLI read-side
- `chronos runs list` / `chronos runs show` / `chronos forks show` with rich tables and `--json` machine-readable output.
- `CHRONOS_DB` env var for default DB path.

### Added (Round 5) — M1.5 fork primitive
- `LangGraphRecorder.fork(...)` context manager — seeded child thread via `graph.update_state(as_node=...)`, parent→child lineage recorded in `forks` table and cross-run `parent_node_id`.
- ADR-005 — fork semantics.

### Added (Round 4) — M1.4 LangGraph adapter
- `chronos.adapters.langgraph.LangGraphRecorder` — checkpointer-based state capture via `graph.get_state_history()` on context-manager exit.
- ADR-004 — snapshot → node mapping algorithm.

### Added (Round 3) — M1.3 SQLite canonical store
- Pydantic models for `Run`, `Node`, `Fork`, `Tag`.
- SQLite schema (`chronos.store.sqlite`) with upsert semantics for Runs/Nodes, append-only for Forks.
- ADR-003 — canonical event schema; ADR-002 — trace schema versioning.

### Added (Round 2) — M1.2 scaffolding
- `pyproject.toml` + `uv`-based dev environment.
- Ruff + pytest + mypy wired; GitHub Actions CI.

### Added (Round 1) — Phase 0 research
- Competitor landscape (20+ tools across 4 tiers).
- Feasibility research (determinism, checkpoint capture, diff semantics, multi-framework risk).
- Architecture doc, user stories, risk register.
- ADR-001 — Python chosen over TypeScript for Phase 1 (LangGraph alignment, Pydantic ecosystem).
