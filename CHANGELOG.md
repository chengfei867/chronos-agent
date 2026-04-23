# Changelog

All notable changes to Chronos Agent are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Fixed (Round 23-A) — `fork plan --emit python` stub executability

Dogfood of R22 against the R17 supervisor baseline (`chronos-dogfood/supervisor`) exposed three bugs that slipped past R22 because tests only `compile()`-checked the generated stub, never `exec`-ed it. All three are fixed with regression tests that actually run the stub:

- Stub used `ref.run_id`, but `ForkRef` exposes `child_run_id` (plus `fork_id`, `node_ids`). Any real execution of the stub would `AttributeError` at the final print line. Now correctly uses `ref.child_run_id`.
- Final `print(...)` was placed *inside* the `with recorder.fork(...)` block, but `ForkRef` fields are populated on context-manager **exit** — so the print always fired before population and printed `None`. Print moved below the `with` block with a comment explaining the lifecycle.
- Example import/construction comments suggested `from chronos.store.sqlite import SqliteStore` + `SqliteStore("..."); store.open()`, neither of which is the public API. Corrected to `from chronos.store import SqliteStore` + `SqliteStore.open(path)` context-manager idiom (matches how `chronos-dogfood/supervisor/dogfood_baseline.py` actually opens its store).
- CLI `render_plan_preview` previously printed the same `consume in code with from chronos.fork_plan import load_plan` hint for both `--emit json` and `--emit python`. Now emit-aware: the python path tells users to fill the two `TODO(user)` blocks and `python <stub>`.

### Tests

- `test_fork_plan.py` gained 3 regression tests (22 → 25): one actually `exec`s the stub with a mocked recorder + graph and asserts the print line reaches stdout with the correct value; two assert the comment/import and field-name invariants at source level.
- `test_fork_cli.py` assertion for the stale "paste-ready Python stub written to" message replaced with the new preview-based hint check.
- Full suite: **263 / 263 pass, 93% coverage**, ruff/format/mypy all green.

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
