# ADR-030: Evaluation & Scoring — fork-comparison judgement layer

**Status**: Proposed (drafted by user-decision in chat, R109 close-out, 2026-05-26)
**Date**: 2026-05-26 (Beijing, in chat session — to be ratified by next in-window cron round)
**Supersedes**: nothing
**Depends on**: [ADR-006][ADR-006] (diff/compare semantics — evaluator output stacks alongside structural diff), [ADR-024][ADR-024] (multi-pivot compare — natural surface for batch scoring), [ADR-029][ADR-029] (Cost Visibility — companion arc, runs in adjacent slot)
**Related**: [r120-acceptance.md][acceptance]
**Feeds**: v1.0.0-rc1, README "Evaluation" feature row

---

## Context

Once chronos can record, replay, fork, and diff agent runs (Phase 5 close), the natural follow-up question for any user is: *"I forked 5 versions of this run with different prompts — **which one is best?**"* Today the answer requires eyeballing the diff. LangSmith and AgentOps both ship a first-class **Evaluator / Scoring** primitive for exactly this question; chronos has no equivalent.

This ADR commits chronos to a **minimal-but-honest** evaluator surface: a hookable scoring function applied to one or more runs, results stored alongside the run, surfaced in CLI compare and the frontend fork-tree. Explicitly *not* a full eval framework — that's a v2.0+ direction.

The slot for this work was approved by the user in chat (2026-05-26) alongside ADR-029, in answer to *"is the product feature-rich enough?"*. Both ADRs land in Phase 6 RC, extending the R107→R120 plan by two rounds → R107→R122.

---

## Decision

**One slot — slot R114.5 (folded into R115 in the round counter; "R114.5" is shorthand only) — to add an evaluator hook + storage + CLI/frontend surfacing**, scoped tightly to "the user supplies a Python callable, chronos runs it on each requested run and persists a numeric score plus an optional rationale string."

Concrete acceptance:

### Schema

- New SQLite table `evaluations` (added via a new Alembic-style migration in `migrations/`):
  - `id TEXT PRIMARY KEY` (UUID4)
  - `run_id TEXT NOT NULL REFERENCES runs(id)` (1 run can have many evals)
  - `evaluator_name TEXT NOT NULL` (e.g. `"length_under_280_chars"`, `"llm_judge_helpfulness"`)
  - `score REAL` (nullable; convention: higher = better, callers pick the scale)
  - `passed INTEGER` (0/1, nullable; for boolean evaluators)
  - `rationale TEXT` (nullable; free-form explanation)
  - `metadata JSON DEFAULT '{}'`
  - `created_at TIMESTAMP NOT NULL`
- New Pydantic `Evaluation` class in `core/models.py`.
- One unique index `(run_id, evaluator_name)` — re-running an evaluator overwrites the prior result via `INSERT … ON CONFLICT DO UPDATE`.

### Evaluator API

- A user-supplied evaluator is any callable matching:
  ```python
  def evaluator(run: Run, nodes: list[Node]) -> EvaluationResult: ...
  ```
  where `EvaluationResult` is a small Pydantic model with optional `score`, `passed`, `rationale`, `metadata` — i.e. the evaluator decides what shape to produce.
- Evaluators are **registered, not auto-discovered** — register via `chronos.eval.register("name", fn)` or via an entry-point group `chronos.evaluators` (for plugin packaging). No magic glob of the user's CWD.
- Ship **two built-in evaluators** to anchor the surface:
  1. `output_length_chars` — emits `score = len(final_state.get("output", ""))`. Trivial, always works, useful for "did my fork actually produce more text?" comparisons.
  2. `final_state_key_present` — emits `passed = key in final_state`. Configurable via metadata (the key name is supplied at registration time). Demonstrates the boolean-evaluator path.
- LLM-judge evaluators are **explicitly out of scope for this slot** — they require relay configuration, cost considerations, and a much larger blast radius. ADR mentions them as a v1.1+ direction.

### CLI

- New command: `chronos eval run <run_id> --evaluator <name> [--evaluator <name> ...]`
  - Resolves each evaluator name from the registry, runs it, persists the result.
  - Prints a table: `evaluator | score | passed | rationale (truncated)`.
  - Returns exit 1 if any evaluator raised; 0 otherwise (running counts as success even if `passed=False`).
- New command: `chronos eval list <run_id>` — shows previously persisted evaluations for a run.
- **`chronos compare` gains an `--eval <name>` flag** — when set, the compare table appends a column with that evaluator's score for each run, sorted descending. Empty cells (run never evaluated by that evaluator) render as `[dim]—[/]`.
- New entries in `cli-reference.md`.

### Frontend

- **`TreeView` (fork tree) page**: each run node in the tree gets an optional badge showing the latest score from the most-recently-run evaluator if any. Tooltip shows full evaluator name + rationale.
- **`RunList` page** gains a sortable "Score" column (latest evaluator's score, dim if absent).
- No new page — re-using the existing surfaces keeps the change minimal.

### API

- `GET /runs/{id}/evaluations` returns the evaluation list.
- `POST /runs/{id}/evaluations` accepts `{evaluator_name, score?, passed?, rationale?, metadata?}` for direct API-side persistence (exposes the storage layer for power users; the CLI is the recommended path).

### Tests

- Migration test: creates the `evaluations` table on a fresh DB and on an upgraded existing DB.
- Unit test: register evaluator → run → persist → re-run → row updates (not duplicates).
- Unit test: `chronos eval run` with two evaluators on a seeded run.
- Unit test: `chronos compare --eval` appends the column correctly.
- Spike (`tests/spikes/spike21_eval_compare_pipeline.py`): record a run, run two evaluators, run `chronos compare --eval`, assert table contents.

### Docs

- New section in README: "🎯 Evaluation".
- New page in docs site: `evaluators.md` covering the registration API + the two built-ins + a worked example writing a custom evaluator.
- `docs/cli-reference.md` updated with the new commands.

---

## Out of scope

- LLM-as-judge evaluators (deferred to v1.1).
- Dataset-driven evaluation (LangSmith-style "run my agent against 100 fixtures and aggregate") — orthogonal arc.
- Continuous evaluation in CI — out of v1.0 scope but trivially layerable on the CLI verb later.
- Evaluator versioning — we store `evaluator_name` only; bumping a behavioral version is the user's responsibility (rename the evaluator). Documented as a known limit.
- A "leaderboard" UI — not in v1.0; the sortable Score column is the entire frontend touch.

---

## Consequences

**Positive**

- Closes the second-largest perceived gap vs. LangSmith / AgentOps in one slot, with a deliberately small surface.
- Plays directly to chronos's differentiator: every fork can have its own evaluator output, making the fork-tree comparison story concrete.
- Built-in evaluators give README/docs a working demo without requiring users to write code.

**Negative**

- A new SQLite table is a schema change — Phase 6 RC was supposed to be polish-only. Mitigated by the migration being purely additive (never alters existing tables) and shipped behind the existing migrations machinery.
- Two new CLI verbs increases the surface area we have to keep stable for v1.0. Counter: `eval run` and `eval list` are conventional verb shapes; the risk of needing a breaking change before v1.1 is low.
- The frontend `RunList` Score column is "latest evaluator wins" — when a run has been scored by multiple evaluators, the displayed column may flicker depending on order. Acceptable for v1.0; the docs call this out and the full eval list is one click away in the run detail.

**Round-counter impact**

This slot adds one round to the Phase 6 RC plan. Combined with ADR-029 (also one round), the R107→R120 plan extends to **R107→R122**. R122 becomes the new RC1 / acceptance round. R120 acceptance contract is updated correspondingly (see r120-acceptance.md → r122-acceptance.md rename + content additions).

[ADR-006]: ADR-006-diff-compare-semantics.md
[ADR-024]: ADR-024-multi-pivot-compare.md
[ADR-029]: ADR-029-cost-visibility.md
[acceptance]: ../r120-acceptance.md
