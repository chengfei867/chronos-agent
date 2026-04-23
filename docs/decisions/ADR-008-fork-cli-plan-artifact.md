# ADR-008: `chronos fork` CLI — Plan Artifact Pattern

- **Status**: Accepted
- **Date**: 2026-04-23
- **Related**: ADR-005 (fork semantics), ADR-007 (replay TUI)

---

## Context

Round 10 (M1.7) shipped the last inspection verb (`chronos replay <run_id>`),
closing the read-only CLI surface. Round 11 (M1.8) asks: does `chronos fork`
make sense as a CLI wrapper, and if so, what does it do?

The obstacle is structural. `LangGraphRecorder.fork()` is a context manager:

```python
with recorder.fork(
    graph,                # ← caller's compiled LangGraph instance
    parent_run_id=...,
    at_node_id=...,
    overrides={...},
    child_thread_id=...,
) as fork_ref:
    graph.invoke(None, cfg_child)   # ← caller re-executes downstream
```

Two things the CLI cannot do on its own:

1. **Construct the user's `graph`.** Graphs are built in user code
   (`build_graph()` in the examples), with nodes that close over models,
   prompts, tools, RAG indexes, API clients — arbitrary Python state.
   The CLI has no hook to reconstruct that.
2. **Invoke downstream.** Even if the CLI loaded the graph, invoking it
   means executing the user's nodes — LLM calls, tool use, side effects —
   in a CLI process. That's a fundamentally different risk/UX contract
   than `runs show` / `diff` / `replay`, which only read the DB.

---

## Options considered

### A. Inspection-only (`chronos fork inspect <fork_id>`)

Add nothing new — this is already covered by `chronos forks show`.
**Rejected**: no incremental value, and naming `fork` (singular) as an
inspection verb would confuse the CLI grammar.

### B. **Plan artifact** (`chronos fork plan`) — chosen

The CLI doesn't execute anything. It emits a **structured JSON "fork
plan"** that the user's code consumes to call `recorder.fork()`. The
CLI does the parts it's uniquely good at:

- resolving `run_id` → `(parent_run, parent_node)` by node name or index
- validating override keys against `parent_node.state_after`
- filling in sane defaults (e.g., `child_thread_id = f"{parent.thread}-fork-<uuid8>"`,
  `reason` prompt)
- rendering a human-readable preview of what the fork will do
- emitting `fork_plan.json` that is small, diff-able, commit-able

The user's code loads the plan with a tiny helper and hands it to
`recorder.fork()`:

```python
from chronos.fork_plan import load_plan
plan = load_plan("fork_plan.json")
with recorder.fork(graph, **plan.recorder_kwargs()) as ref:
    graph.invoke(None, {"configurable": {"thread_id": plan.child_thread_id}})
```

### C. Dynamic-import runner (`chronos fork run --script foo.py::build_graph`)

CLI dynamically imports user code to construct a graph and run fork in
one shot. Maximally "automatic" but: arbitrary code execution, heavy
coupling to a `build_graph()` contract, fragile (env/cwd/venv
confusion), breaks the read-only guarantee of the rest of the CLI.
**Rejected** — reconsider post-v0.2 if there's real demand.

---

## Decision

Ship **option B**: `chronos fork plan`.

### Command surface

```
chronos fork plan <run_id>
    (--at-node <name> | --at-index <k> | --at-node-id <uid>)
    [--override key=value]...
    [--override-json '{"k": ...}']
    [--child-thread-id <str>]
    [--reason <str>]
    [--tag <str>]...
    [--out <path>]           # default: ./fork_plan.json
    [--json]                 # print the plan to stdout instead of writing
    [--allow-new-keys]       # skip validation for overrides not in state_after
    [--db <path>]
```

Behaviour:

1. **Resolve parent node.** Exactly one of `--at-node` / `--at-index` /
   `--at-node-id` must be given. Ambiguity on `--at-node` (name appears
   more than once, common in router/loop graphs) is an error that asks
   the user to pick `--at-index`.
2. **Parse overrides.** `--override k=v` values parse as JSON first
   (`123`, `true`, `[1,2]`), falling back to raw string. `--override-json`
   merges a full dict. Repeated keys: last wins.
3. **Validate overrides.** Every override key must exist in
   `parent_node.state_after`, unless `--allow-new-keys` is set. Typed
   mismatches (e.g., str where parent had list) emit a `[yellow]warning[/]`
   but don't error — LangGraph schemas allow broadening.
4. **Generate defaults.** `child_thread_id` defaults to
   `f"{parent.adapter_thread_id}-fork-{uuid4().hex[:8]}"`. `reason` is
   optional; empty is OK.
5. **Emit plan.** Write JSON with stable key order:

   ```json
   {
     "chronos_fork_plan_version": 1,
     "parent_run_id": "...",
     "parent_node_id": "...",
     "parent_node_name": "research",
     "parent_node_index": 2,
     "child_thread_id": "linear-fork-ab12cd34",
     "overrides": {"research": "...", "draft": ""},
     "reason": "swap researcher to v2-thorough prompt",
     "tags": ["cli-forked"],
     "generated_at": "2026-04-23T04:50:00+00:00",
     "chronos_version": "0.1.0"
   }
   ```

6. **Preview.** Render a Rich panel showing parent run, node, before/after
   snippets of overridden fields (truncated), so the user catches typos
   before running any code.

### Consumer helper

Ship `chronos.fork_plan.ForkPlan` + `load_plan(path)` so users don't
hand-roll JSON parsing. `ForkPlan.recorder_kwargs()` returns exactly the
kwargs `recorder.fork()` accepts, skipping any fields the recorder
doesn't take (`generated_at`, `chronos_version`, `parent_node_name`,
`parent_node_index`).

### Non-goals (for this round)

- No `chronos fork run`: execution stays in user code (reconsider post-v0.2).
- No multi-fork plans (one plan = one fork).
- No interactive TUI picker for node — would be nice but belongs in a
  later round; `--at-index` is sufficient for now.
- No adapter-agnostic generalization yet: the plan shape is LangGraph-
  specific only where `child_thread_id` is. It still works for future
  adapters that carry a "thread"-equivalent.

---

## Consequences

### Positive

- Preserves the "read-only CLI" invariant: the `chronos` binary never
  executes user graph code.
- The plan JSON is a **portable, commit-able artifact** — great for bug
  reports ("here's the run and the fork I'd try") and reproducibility.
- CLI handles the annoying parts (node resolution, override parsing,
  validation) so the user's fork code stays short.
- Zero new runtime deps.
- Sets precedent for future `chronos experiment`-style artifacts if
  that's where we head in v0.3.

### Negative

- Still a two-step flow (plan → user-side `recorder.fork()`). Option C
  would be one step. Accept this cost; the boundary is clearer.
- Yet another JSON schema we have to version. Mitigated by
  `chronos_fork_plan_version: 1` and a loader that rejects unknown
  versions.

### Follow-ups

- Once there's a second adapter (AutoGen / CrewAI in Phase 2), revisit
  whether `ForkPlan` needs an `adapter` discriminator.
- If users accumulate many fork plans, a `chronos fork list` that scans
  a directory would be a pleasant add.
