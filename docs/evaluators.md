# Evaluators

Once Chronos can record, replay, fork, and diff agent runs, the natural next question is: *"I forked five versions of this run with different prompts — **which one is best?**"* Evaluators answer that question.

> Specced in [ADR-030: Evaluation & Scoring](decisions/ADR-030-evaluation-scoring.md), shipped in **R115** as part of the v1.0 RC arc.

An **evaluator** is any Python callable that takes a `Run` plus its `nodes` and returns an `EvaluationResult` — score, pass/fail, free-form rationale, or any combination. Chronos persists the result in a dedicated `evaluations` table, surfaces it in `chronos compare --eval`, and renders a sortable **Score** column in the Web UI's RunList page.

## What ships out of the box

Two zero-config built-in evaluators land in v1.0 to anchor the surface:

| Built-in name | Shape | Useful for |
|---|---|---|
| `output_length_chars` | `score = len(final_state.get("output", ""))` | "Did my fork actually produce more text than the parent?" |
| `final_state_key_present` | `passed = key in final_state` (key is set at registration time) | Boolean asserts — does the run end with the expected state shape? |

Both are listed by `chronos eval list-evaluators` and are usable without writing a line of code.

```bash
$ chronos eval list-evaluators
                       Registered evaluators
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ name                          ┃ description                                ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ output_length_chars          │ Score = char count of final output state.  │
│ final_state_key_present       │ Pass/fail = whether key is in final state. │
└──────────────────────────────┴────────────────────────────────────────────┘
```

## Running an evaluator

```bash
# Score a single run with one evaluator:
chronos eval run <RUN_ID> --evaluator output_length_chars

# Score a run with multiple evaluators in one shot:
chronos eval run <RUN_ID> \
    --evaluator output_length_chars \
    --evaluator final_state_key_present

# List previous results:
chronos eval list <RUN_ID>
```

The result is persisted to the `evaluations` table with a unique `(run_id, evaluator_name)` index — re-running the same evaluator overwrites the prior result rather than duplicating it.

## Comparing N forks by score

The killer combo is `chronos compare --eval`:

```bash
chronos compare <PARENT_ID> <FORK_A_ID> <FORK_B_ID> <FORK_C_ID> \
    --eval output_length_chars
```

The standard compare output gains a right-aligned `Score` column, and the run rows are sorted descending by that score. Empty cells (a run never scored by that evaluator) render as `[dim]—[/]`. Pair this with `--eval-secondary` (planned for v1.1) for tie-breakers.

In the Web UI, the same data is reachable from `#/compare?ids=<csv>` — the table sort and Score column behave identically. Click any score to open the full evaluation history for that run.

## Writing your own evaluator

Implement the protocol — any callable with this signature is an evaluator:

```python
from chronos.core.models import Run, Node
from chronos.eval import EvaluationResult, register

def has_three_research_steps(run: Run, nodes: list[Node]) -> EvaluationResult:
    """Pass when the run has exactly three TOOL nodes named 'research'."""
    research_nodes = [
        n for n in nodes
        if n.kind == "TOOL" and n.name == "research"
    ]
    return EvaluationResult(
        passed=len(research_nodes) == 3,
        score=float(len(research_nodes)),
        rationale=f"Found {len(research_nodes)} 'research' tool nodes (want 3).",
    )

# Register at import time:
register("has_three_research_steps", has_three_research_steps)
```

Then use it:

```bash
chronos eval run <RUN_ID> --evaluator has_three_research_steps
```

`EvaluationResult` is a small Pydantic model:

```python
class EvaluationResult(BaseModel):
    score: float | None = None       # higher = better, conventionally
    passed: bool | None = None        # for boolean evaluators
    rationale: str | None = None      # free-form explanation, truncated in tables
    metadata: dict[str, Any] = {}     # JSON-serialisable, persisted verbatim
```

Set whichever fields make sense for your evaluator. Numeric evaluators set `score`; boolean evaluators set `passed`; mixed evaluators (a score *and* a pass/fail threshold) set both. The CLI table renders the populated fields; null fields display as `—`.

### Registration patterns

Two registration paths are supported:

1. **In-process registration** — `chronos.eval.register(name, fn)` in your own code. Simplest path; the evaluator is in scope only for the running process. Use this from a `conftest.py`-style harness module loaded by `chronos --conf`.
2. **Entry-point registration** — declare your evaluators under the `chronos.evaluators` entry-point group in your package's `pyproject.toml`. They become globally available wherever your package is installed.

```toml
# In your package's pyproject.toml:
[project.entry-points."chronos.evaluators"]
my_eval = "my_pkg.evaluators:my_evaluator_fn"
```

Both paths land in the same registry; `chronos eval list-evaluators` shows the union.

## What's deliberately NOT in v1.0

- **LLM-as-judge evaluators.** They require relay configuration, cost considerations, and a much larger blast radius. Deferred to v1.1; trivially layerable on the registration API once relay-config UX is polished.
- **Dataset-driven evaluation** ("run my agent against 100 fixtures and aggregate"). That's an orthogonal arc — we don't want to compete with LangSmith's dataset surface in v1.0. Use Chronos for one-run-at-a-time scoring; layer batch eval on top with `xargs chronos eval run` if you need it.
- **CI-integrated evaluation gates** — out of v1.0 scope. The CLI verbs are stable enough that a `pytest` fixture invoking them works today; `chronos eval run … --strict` (exit non-zero on `passed=False`) is a v1.1 candidate.
- **Evaluator versioning.** Chronos stores `evaluator_name` only — bumping a behavioral version is the user's responsibility (rename `my_eval` to `my_eval_v2`). This is a documented limit, not a bug.
- **Leaderboards / ranking UI.** The sortable `Score` column on RunList is the entire frontend touch for v1.0. A dedicated leaderboard page is a v1.1+ direction.

> Out-of-scope items above are tracked in [ADR-030 §Out of scope](decisions/ADR-030-evaluation-scoring.md#out-of-scope).

## See also

- [ADR-030 — Evaluation & Scoring decision](decisions/ADR-030-evaluation-scoring.md) — full spec including schema and migration.
- [Cost tracking](cost-tracking.md) — combine score-per-fork with cost-per-fork to pick the *cheapest* fork that beats the bar.
- [Concepts → Compare](concepts/index.md#5-compare) — the surface that `--eval` augments.
- [CLI reference → `eval`](cli-reference.md) — full verb syntax, including `eval list` and `eval run`.
