# Changelog

All notable changes to Chronos Agent are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
- `examples/linear_pipeline.py` — runnable LangGraph 5-node agent demoing record → fork → diff with a deterministic fake LLM (no API key required).
- `examples/router_loop.py` — runnable LangGraph agent with a conditional edge loop, demoing fork-forced early exit and how the diff aligner handles repeated node names.
- `examples/_fake_llm.py` — pure-function FakeLLM for deterministic demos.
- `docs/getting-started.md` — 5-minute onboarding walkthrough from install to `chronos diff`.
- `docs/cli-reference.md` — every CLI command, flag, exit code, and environment variable documented.
- Rewrite of `README.md` with real install instructions, quickstart, current milestone table, and development commands.
- `.gitignore` now excludes `examples/chronos.db` and `*.db-journal` so demo DB churn isn't committed.

### Notes
- Full M1.9 scope in progress toward **v0.1.0** tag. Known Phase 1.1 gap: `chronos replay` TUI (M1.7) and `chronos fork` CLI wrapper (M1.8 partial).

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
