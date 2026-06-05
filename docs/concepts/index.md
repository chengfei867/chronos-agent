# Core Concepts

Chronos Agent's vocabulary is small and load-bearing. Internalize these five concepts and the rest of the documentation reads in one pass.

> **TL;DR** — Chronos models an agent execution as an immutable **run** of typed **nodes**. From any node you can **fork** a parallel timeline, **diff** two timelines, **compare** N of them, or **replay** a single one step-by-step. Every action persists to a single SQLite file.

---

## 1. Record

A **run** is the recorded execution of one agent invocation, end to end, captured as a sequence of **nodes**. Each node is a typed event — an `LLM` call, a `TOOL` invocation, a `ROUTER` decision, a `STATE` snapshot — with its full input/output state, its parent edges in the reasoning DAG, and (when the adapter supplies it) its token/cost `usage` envelope.

Recording is non-invasive: you wrap your existing LangGraph / Anthropic Agents / CrewAI / AutoGen graph in the matching `Recorder` context manager, the run executes normally, and Chronos transparently captures every step. No proxy, no cloud round-trip, no relay. The artifact is a row in the `runs` table plus N rows in the `nodes` table of a local SQLite database (`chronos.db` by default).

**Shape**: 1 run → N nodes (typically 5–50 for a real agent task) → optional `usage` per node → optional `evaluations` per run.

> **Why immutable?** Re-execution is what diverges a timeline; the original recording is read-only forever. If you want to change something, you `fork` — that creates a *new* run, leaving the parent untouched.

---

## 2. Replay

**Replay** is the operation of stepping through a recorded run interactively, one node at a time, inspecting each state snapshot in isolation. You don't re-execute the agent's logic — you re-render its history.

Two surfaces ship today:

- **CLI** — `chronos replay <run_id>` opens a Textual TUI. Press `→` to advance one node, `←` to step back. Each frame shows the node kind, the diff against the previous state, and (if usage was recorded) the per-node tokens and cost.
- **Web UI** — open the run from the RunList page; the right pane is a node tree, the bottom drawer is the per-node detail. Scrubbing across nodes updates the detail pane immediately.

Replay is read-only. It cannot accidentally re-trigger a side effect — the recorded run already happened, and Chronos never re-runs the original adapter graph.

---

## 3. Fork

**Fork** is the central differentiator. Pick any node in a recorded run, mutate one input (a prompt, a tool argument, a state value, even the LLM model), and Chronos re-executes only the **downstream** nodes under the mutation. Upstream nodes are reused verbatim.

```
parent run:   [plan] → [research] → [draft] → [review] → [finalize]
                                       ↑ fork here, swap "draft" prompt
forked run:   [plan] → [research] → [draft'] → [review'] → [finalize']
              └─ reused ─┘           └────── re-executed ──────┘
```

The forked run is itself a first-class run with its own `run_id` and its own row in the `runs` table. It carries a `parent_run_id` pointer and a `forked_at_node_id`, which is what enables [diffing](#4-diff) two timelines and walking the [fork tree](#fork-tree).

The CLI surface is `chronos fork <parent_id> --at-node <node_id> --override <key>=<value>`. The Web UI's TreeView page exposes the same operation through a "Fork from this node" modal. See [Forking safely](../guides/forking-safely.md) for the mental model around side effects and idempotence.

### Fork tree

When a fork is itself forked (and that grandchild is forked again, etc.) the family becomes a DAG. Chronos lays the family out as a lane-based tree both in the CLI (`chronos tree <root_id>`) and the Web UI's `#/runs/<id>/tree` page. Each node in the tree shows the run's task, its evaluator score (if any), and its aggregate token/cost.

---

## 4. Diff

**Diff** is the structural comparison of two runs — typically a parent and its fork, but any two runs work. Chronos pairs nodes by execution order (with handling for repeated node names from loops, see [ADR-006](../decisions/ADR-006-diff-alignment.md)) and reports four outcomes per pair:

| Tag | Meaning |
|-----|---------|
| `=`   | Equal — both runs produced byte-identical state at this position. |
| `~`   | Changed — same node, divergent state. The diff lists which state keys changed. |
| `+`   | Added — run B has a node that run A doesn't. |
| `-`   | Removed — run A has a node that run B doesn't. |

```bash
chronos diff <PARENT_ID> <CHILD_ID> --db chronos.db --verbose
```

When the child is a fork of the parent, Chronos auto-detects the fork point and only diffs **downstream** nodes (use `--full` to override). This keeps the output focused on what the user actually changed.

---

## 5. Compare

**Compare** generalises diff to **N runs** (up to 32 in v1.0). The CLI verb is `chronos compare <id1> <id2> [<id3> …]`; the Web UI surface is `#/compare?ids=<csv>`. Output:

- An auto-picked **centroid pivot** (the run that minimises pairwise distance to the others), so the comparison anchors on the median timeline rather than an arbitrary first arg.
- A **pairwise distance matrix** in the CLI; the Web UI renders this as a small heatmap.
- A **side-by-side alignment view** — each row is one node position, each column is one run, cells show the per-position state.
- (R115+) An **`--eval <name>` flag** — append a column of evaluator scores and sort runs descending by that score. This is the "which fork is best?" workflow, see [Evaluators](../evaluators.md).

```bash
chronos compare <id1> <id2> <id3> --eval output_length_chars
```

---

## How they compose

The five verbs compose into the canonical chronos workflow:

1. **Record** an agent run — your normal code, wrapped in `Recorder.record()`.
2. **Replay** it to see exactly what happened, node by node.
3. **Fork** at the suspect node, change one thing, let Chronos re-execute downstream.
4. **Diff** parent vs fork to see precisely what your change did.
5. **Compare** parent + N forks side by side, optionally sorted by an **evaluator** score, to pick the winner.

The artifact at the bottom of every operation is the same SQLite database. Re-open it on another machine, re-run any verb, the answers reproduce exactly.

---

## See also

- [Getting started](../getting-started.md) — the 5-minute hands-on tutorial.
- [CLI reference](../cli-reference.md) — full verb-by-verb documentation.
- [Cost tracking](../cost-tracking.md) — how `Usage` is captured, surfaced, and aggregated.
- [Evaluators](../evaluators.md) — pluggable scoring on top of any recorded run.
- [Forking safely](../guides/forking-safely.md) — side-effect awareness for the fork operation.
- [ADR index](../decisions/index.md) — the architectural decision record archive.
