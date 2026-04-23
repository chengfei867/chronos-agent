# Changelog

All notable changes to Chronos Agent are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

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
