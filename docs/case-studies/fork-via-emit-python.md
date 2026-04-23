# Case Study: Forking a Recorded Run via `chronos fork plan --emit python`

**Round**: R23-A
**Date**: 2026-04-23
**Feature under study**: `chronos fork plan <run_id> --emit python` (shipped in R22, v0.1.5)
**Target**: the R17 supervisor dogfood baseline (parent run `69932676-5b33-46c9-8cf9-ac553af6e25f`)
**LLM provider**: Anthropic Claude Opus 4.7 via OneAPI

## TL;DR

The first real end-to-end exercise of R22's `--emit python` stub generator (against a recorded multi-agent run, not synthetic test graphs) surfaced **three bugs in the generated stub template** within the first execution. All three are now fixed and guarded by regression tests that actually `exec()` the stub rather than just `compile()`-checking it.

The fork workflow now works end-to-end: `chronos fork plan ... --emit python` → fill two `TODO(user)` blocks → `python fork_stub.py` → new child run + fork record land in the parent's SQLite store, ready for `chronos forks show`, `chronos diff`, or any other downstream tooling.

A fourth observation — not a bug, but a DX pitfall — is that whether the child run actually *steps through graph nodes* (as opposed to merely registering the fork) depends entirely on the parent graph having been compiled with a **persistent, cross-run-shared** LangGraph checkpointer. This is worth knowing before you write your first stub.

## Why this exercise?

R22 landed the feature with 10 new tests (7 unit + 3 CLI E2E). All passed. But every one of them checked only that the generated source **compiles** under Python 3.11+ — none actually **ran** it. Running a stub requires a recorder, a graph, and a parent run in a SQLite store, which is exactly what R17's `chronos-dogfood/supervisor/` workspace already has sitting there.

This case study walks through the full use-the-feature-in-anger path: pick a recorded run, ask "what if the supervisor had routed differently?", generate a stub to execute that counterfactual, fill the user-code blocks, and run it.

## Setup

R17's supervisor workspace is already wired up. All we need is the DB and a venv with Chronos installed editable:

```bash
cd /workspace/chronos-dogfood/supervisor
source .venv/bin/activate       # already has chronos + langchain-anthropic

# Sanity: confirm the parent run exists
chronos runs show 69932676-5b33-46c9-8cf9-ac553af6e25f --db dogfood.db | head -20
```

Output shows 3 nodes:

| idx | name | kind |
|-----|------|------|
| 0 | supervisor | llm |
| 1 | research_expert | llm |
| 2 | supervisor | llm |

Fork point: node[0]. The counterfactual is "what if the supervisor had asked the math_expert first on a query that actually needs research?" — we don't need a *good* counterfactual for this exercise, we need a *runnable* one. Empty `overrides` will do.

## Step 1 — Generate the stub

```bash
chronos fork plan 69932676-5b33-46c9-8cf9-ac553af6e25f \
    --at-index 0 \
    --reason "counterfactual: what if supervisor asks math_expert first" \
    --emit python \
    --out fork_stub.py \
    --db dogfood.db
```

The CLI prints a preview, confirms the file was written, and hints at the next step:

```
  written to fork_stub.py
  fill the two TODO(user) blocks, then python fork_stub.py
```

Opening `fork_stub.py`: a ~60-line file with a docstring (provenance: parent_run_id, parent_node, chronos_version, generated_at), two `TODO(user)` comment blocks for the recorder and the graph, and a fully inlined `recorder.fork(...)` call that captures all the fork kwargs as Python literals — no reference to an external JSON file at runtime.

## Step 2 — Fill the TODOs

Two tiny pieces of user code needed:

```python
# (A) Recorder: open the same DB the parent lives in.
from chronos.adapters import LangGraphRecorder
from chronos.store import SqliteStore

store_cm = SqliteStore.open("dogfood.db")
store = store_cm.__enter__()
recorder = LangGraphRecorder(store=store)

# (B) Graph: rebuild the parent's graph factory.
from dogfood_baseline import build_supervisor_app

graph = build_supervisor_app()
```

That's it. The generated block below these two already has the `with recorder.fork(graph, ...)` call wired, the `graph.invoke(None, {"configurable": {"thread_id": ...}})` call sample, and a trailing diagnostic `print(f"fork child run: {ref.child_run_id}")` *after* the `with` block (fields on `ForkRef` are populated on context-manager exit — see Finding #2 below for why that's important).

Save as `fork_stub_filled.py` and run:

```bash
ANTHROPIC_API_KEY=<from .env> python fork_stub_filled.py
```

Output:

```
fork child run: 16ca0fa5-cbec-418b-bd47-7a9546048b01
fork id:        f6b36f40-82c3-45d8-9386-5b8a4e7b393c
new node ids:   []
```

And in the DB:

```bash
chronos runs list --db dogfood.db | grep 16ca0fa5
# 16ca0fa5-cbec-418b-bd47-7a9546048b01  baseline-0fee79a0-fork-8eea5247  ...

chronos forks show 16ca0fa5-cbec-418b-bd47-7a9546048b01 --db dogfood.db
# parent: 69932676-5b33-...   at_node: supervisor[0]   child: 16ca0fa5-...
```

Fork recorded, parent-child relationship intact, `fork_id` traceable. 🎯

## Findings

### Finding #1 — `ref.run_id` was a typo; `ForkRef.child_run_id` is the real field

**Observed**: First run of the stub crashed with `AttributeError: 'ForkRef' object has no attribute 'run_id'` at the final diagnostic print. The `ForkRef` class (`src/chronos/adapters/langgraph.py`) exposes exactly three public fields: `child_run_id`, `fork_id`, `node_ids`. R22's `to_python()` template had written `ref.run_id`, copying the field name from `RunRef` (the return of `recorder.record()`, which *does* have `run_id`).

**Why R22 tests missed it**: R22 had 10 tests for the generator, all of which called `compile(src, ...)` and inspected the compiled source string. None of them `exec`-ed the stub. A field-name typo that only manifests at runtime passes `compile` trivially.

**Fix**: `src/chronos/fork_plan.py::to_python` template now emits `ref.child_run_id`. A regression test in `tests/unit/test_fork_plan.py::test_to_python_uses_child_run_id_not_run_id` asserts the source contains `ref.child_run_id` and does **not** contain `ref.run_id`.

### Finding #2 — `print(ref.child_run_id)` was inside the `with` block; that can never work

**Observed**: After renaming to `ref.child_run_id`, the new failure mode was quieter: the stub ran, but printed `fork child run: None`. The child run was in the DB and the `fork_id` was readable via `chronos forks show`, so the fork *had* happened — the printed `None` was a lie about the state observable at that line.

**Root cause**: In the R22 template, the diagnostic `print(f"...{ref.child_run_id}")` was inside the `with recorder.fork(...) as ref:` block. But the Chronos recorder populates `ref.child_run_id` / `ref.fork_id` / `ref.node_ids` **on context-manager exit**, inside `_fork_from_history`'s `try/finally`. Anything reading `ref.<field>` from inside the block is always reading the pre-population state, which is `None`.

**Fix**: Move the `print` below the `with` block, with a comment explaining the lifecycle. The stub now looks like:

```python
with recorder.fork(graph, ...) as ref:
    graph.invoke(None, {"configurable": {"thread_id": ...}})

# ForkRef fields (``child_run_id``, ``fork_id``, ``node_ids``) are populated
# on context-manager *exit*, so read them after the ``with`` block.
print(f"fork child run: {ref.child_run_id}")
```

Regression test (`test_to_python_executable_with_mocked_recorder_and_graph`) mocks both `recorder` (a CM whose yielded `ref` has `child_run_id` set on exit) and `graph` (no-op `.invoke`), `exec`s the stub, captures stdout, and asserts the real post-exit value reaches the print. **This is the test R22 should have had.**

### Finding #3 — Example import/construction comments used non-public API paths

**Observed**: The commented-out example in the stub's recorder TODO block said:

```python
# from chronos.store.sqlite import SqliteStore
# store = SqliteStore("dogfood.db")
# store.open()
```

Two problems: `chronos.store.sqlite` is the internal implementation module (the public entry lives at `chronos.store`); and `SqliteStore("dogfood.db")` is a type error — the real store has no `__init__(path)`, it's opened via `SqliteStore.open(path)` as a classmethod, and that result is used as a context manager.

**Fix**: The template now shows:

```python
# from chronos.store import SqliteStore
# from chronos.adapters import LangGraphRecorder
# with SqliteStore.open("dogfood.db") as store:
#     recorder = LangGraphRecorder(store=store)
#     # ... fork call goes inside the ``with SqliteStore.open(...)`` scope.
```

Regression test (`test_to_python_example_comments_use_real_import_paths`) asserts the non-public paths never appear in the source and the correct idiom does.

### Finding #4 (DX pitfall, not a bug) — child run had zero new nodes

**Observed**: After all three fixes, the stub ran cleanly and printed:

```
fork child run: 16ca0fa5-cbec-418b-bd47-7a9546048b01
fork id:        f6b36f40-82c3-45d8-9386-5b8a4e7b393c
new node ids:   []
```

Fork recorded. `fork_id` traceable. But `new node ids: []` — the child run didn't execute any graph nodes at all. That's not what a forked run is supposed to look like.

**Root cause**: LangGraph semantics. `recorder.fork(...)` seeds the child thread's checkpoint state via LangGraph's `update_state` at the parent's node[0] snapshot. The stub then calls `graph.invoke(None, {"configurable": {"thread_id": child_thread_id}})`. In LangGraph, `invoke(None, ...)` is the "resume from checkpointed state for this thread" idiom — it reads the checkpointer for that thread_id and continues from wherever the last step left off. If the graph was compiled **without** a checkpointer, or with a checkpointer that doesn't have this thread's state, `invoke(None, ...)` returns immediately without stepping any node.

The R17 baseline (`dogfood_baseline.py::build_supervisor_app()`) *does* compile the workflow with `InMemorySaver` — but it's a **fresh `InMemorySaver` per factory call**. The parent run wrote state to one saver instance; the child run's factory call built a second, empty saver. The seed-then-resume flow never connects.

**Implication**: for `--emit python` fork stubs to produce a fully-stepped child run, the user's graph factory must bind a checkpointer that's either

1. a long-lived in-process instance shared across the parent's `record(...)` and the child's `fork(...)` calls, or
2. a persistent checkpointer — most commonly `SqliteSaver.from_conn_string("checkpoints.db")` — that both parent and child read from the same file.

Neither of these is bad design; both are the normal way to use LangGraph checkpointers. But **the R22 stub doesn't mention it**, `chronos fork --help` doesn't mention it, and you can reasonably read the R17 dogfood baseline as a working example and copy a pattern that *can't* produce a stepping child run.

If you're using Chronos fork and your child runs keep showing `node_ids=[]`, check your checkpointer lifecycle first. The correct shape:

```python
from langgraph.checkpoint.sqlite import SqliteSaver

# Shared across parent and child runs.
checkpointer = SqliteSaver.from_conn_string("checkpoints.db")

def build_supervisor_app():
    workflow = StateGraph(...)
    ...
    return workflow.compile(checkpointer=checkpointer)  # <-- bound, shared
```

**R23-C decision pending**: whether to add this as a third `TODO(user)` comment block in the stub, or surface it only in docs and `chronos fork --help` epilog.

## Looking back: ADR-008 / ADR-013 revisited

The checkpointer-persistence gotcha is a fresh piece of evidence for the broader reason Chronos **does not** auto-execute forks and has formally frozen that direction (ADR-013). The moment Chronos automated the whole fork → resume → collect-nodes loop, it would also own the responsibility of ensuring the user's graph has a correctly-shaped checkpointer, or of wrapping/augmenting the user's factory — which means owning knowledge of the user's state schema, their checkpointer backend, their thread ID conventions, and so on. Every one of those is a new coupling surface.

The `--emit python` stub form keeps all of that visible and under user control. The user *sees* the `graph.invoke(None, {thread_id})` call. The user *writes* the factory. The user *debugs* their own checkpointer. Chronos's surface stays exactly two things: recorder wiring + fork kwargs. The dogfood today is a living demonstration that even the "minimal" automation path still has non-trivial user-environment dependencies; an "execute-fork" path would have had many more, and would have owned them all.

## Artifacts

In the repo (this case study plus the fixes):

- `src/chronos/fork_plan.py` — `to_python()` template fixed.
- `src/chronos/cli/fork.py` — `render_plan_preview` emit-aware.
- `tests/unit/test_fork_plan.py::test_to_python_executable_with_mocked_recorder_and_graph` — the regression-test that would have caught all three bugs.
- `progress/2026-04-23-round-23a.md` — round notes.
- `CHANGELOG.md::[Unreleased]::Fixed (Round 23-A)`.

Out of repo (dogfood workspace):

- `/workspace/chronos-dogfood/supervisor/fork_stub.py` — stub as regenerated after the fixes, good reference shape.
- `/workspace/chronos-dogfood/supervisor/fork_stub_filled.py` — 45-line filled runner used for this case study.
- `/workspace/chronos-dogfood/supervisor/dogfood.db` — now contains parent run `69932676-5b33...` and child run `16ca0fa5-cbec...` side by side.

## What to copy next time

- For any code-generation feature: **the tests must exec the generated code**, not just compile it. Field-name typos, lifecycle ordering, placeholder default-values — all pass `compile` and all fail `exec`.
- Dogfood after every feature, even ones with green tests. R22 had 10 green tests and shipped with three runtime-fatal bugs.
- When writing a stub/template, the stub itself is the user-facing API, not the function that generates the stub. Review the stub as text, not as a generator implementation.
