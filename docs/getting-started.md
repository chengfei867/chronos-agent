# Getting Started

**Chronos Agent** is a time-travel debugger for multi-agent AI systems — a `pdb` and `git` for agent reasoning trees. This guide gets you from zero to a working **record → fork → diff** demo in under 5 minutes.

> Today Chronos supports **LangGraph** agents. Additional framework adapters (AutoGen, CrewAI, raw OpenAI tool-loops) are on the Phase 2 roadmap.

---

## Prerequisites

- Python **3.11+**
- [`uv`](https://docs.astral.sh/uv/) (recommended) — or a plain venv + pip
- No LLM API key needed for the examples (they use a deterministic fake LLM)

---

## 1. Install

```bash
git clone https://github.com/chengfei867/chronos-agent.git
cd chronos-agent
uv sync
```

Verify the CLI is on your path:

```bash
uv run chronos --version
```

---

## 2. Your first run: record → fork → diff

We ship two runnable example agents in [`examples/`](../examples/). The linear pipeline is the shortest path to seeing Chronos's value:

```bash
uv run python examples/linear_pipeline.py
```

This does three things:

1. **Records** a baseline run of a 5-node LangGraph agent (`plan → research → draft → review → finalize`) — every node's state snapshot is persisted to `examples/chronos.db`.
2. **Forks** the run at the `research` node, swapping in an alternative LLM persona (`v2-thorough`).
3. Re-executes the downstream nodes (`draft`, `review`, `finalize`) under the new research context.

The script prints the parent run id, the fork-child run id, and ready-to-paste CLI commands. Copy one:

```bash
chronos diff <PARENT_ID> <CHILD_ID> --db examples/chronos.db
```

You should see something like:

```
B is forked from A @ node research (fork …) —
diffing downstream only. Use --full for full-run diff.

┏━━━━┳━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃    ┃ tag     ┃ node_name ┃ a (step) ┃ b (step) ┃ details            ┃
┡━━━━╇━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ ~  │ changed │ draft     │ 2        │ 2        │ ~draft,log,research │
│ ~  │ changed │ review    │ 3        │ 3        │ ~draft,log,review…  │
│ ~  │ changed │ finalize  │ 4        │ 4        │ ~draft,final,log…   │
└────┴─────────┴───────────┴──────────┴──────────┴────────────────────┘
summary: 0 equal  3 changed  0 added  0 removed
```

**This is the core loop**: make a change, fork the prior run, diff the results — no full re-run of upstream nodes, no guesswork about what actually differs downstream.

Add `--verbose` to see the state-field-level deltas:

```bash
chronos diff <PARENT_ID> <CHILD_ID> --db examples/chronos.db --verbose
```

---

## 3. A non-linear example (loops)

LangGraph agents often have loops — the classic pattern is a planner that decides whether to run another research round or finalize. `examples/router_loop.py` demonstrates how Chronos handles repeated node names:

```bash
uv run python examples/router_loop.py
```

The baseline does 3 research rounds; the fork forces early-exit after round 1. The diff correctly pairs loop iterations by order of occurrence (see [ADR-006](decisions/ADR-006-diff-alignment.md) for the alignment algorithm).

---

## 4. Using Chronos in your own agent

The recorder is a context manager around an existing LangGraph graph:

```python
from chronos.adapters import LangGraphRecorder
from chronos.core.models import NodeKind
from chronos.store import SqliteStore

with SqliteStore.open("chronos.db") as store:
    recorder = LangGraphRecorder(
        store,
        kind_map={"plan": NodeKind.LLM, "tool": NodeKind.TOOL},
    )

    with recorder.record(
        graph,
        thread_id="run-1",
        task_description="your task here",
        tags=["prod"],
    ) as ref:
        result = graph.invoke(input_state, {"configurable": {"thread_id": "run-1"}})

    print("recorded run id:", ref.run_id)
```

To fork a recorded run:

```python
nodes = store.get_nodes_for_run(ref.run_id)
target = next(n for n in nodes if n.node_name == "research")

with recorder.fork(
    graph,
    parent_run_id=ref.run_id,
    at_node_id=target.id,
    overrides={"research": "alternative content"},
    child_thread_id="fork-1",
    reason="try a different prompt",
) as fork_ref:
    graph.invoke(None, {"configurable": {"thread_id": "fork-1"}})

print("child run id:", fork_ref.child_run_id)
print("fork id:", fork_ref.fork_id)
```

Then from the terminal:

```bash
chronos runs list --db chronos.db
chronos runs show <run_id> --db chronos.db
chronos forks show <fork_id> --db chronos.db
chronos diff <parent> <child> --db chronos.db
```

---

## 5. Next steps

- **CLI reference**: [`docs/cli-reference.md`](cli-reference.md)
- **Architecture**: [`docs/design/architecture.md`](design/architecture.md) — record/fork/diff internals
- **Roadmap**: [`docs/roadmap.md`](roadmap.md) — v0.1 → v0.3
- **ADRs**: [`docs/decisions/`](decisions/) — every design choice, with rationale

---

## Troubleshooting

**`No such option: --db`** — `--db` is a per-command flag, not a top-level one. Use `chronos runs list --db chronos.db`, not `chronos --db chronos.db runs list`. (A top-level alternative is the `CHRONOS_DB` environment variable.)

**`error: database file not found`** — your `--db` path doesn't exist, or your examples never ran successfully. Re-run `uv run python examples/linear_pipeline.py`.

**`run id not found`** — double-check you're pointing at the right `--db`. Run ids from `examples/chronos.db` won't exist in a different db file.

Anything else? Open an issue at <https://github.com/chengfei867/chronos-agent/issues>.
