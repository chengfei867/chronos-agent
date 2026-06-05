# `chronos` CLI Reference

> Generated as part of **R108 — CLI Polish Track**. Mirrors the rich
> `--help` docstrings that ship with the `chronos` binary. For the
> source of truth, run `chronos <verb> --help`.

`chronos` is the command-line surface of the **chronos-agent** time-travel
debugger. Every verb is read-only against your local `chronos.db` unless
otherwise noted.

## Top-level

```bash
chronos --help          # list verbs
chronos --version       # print version and exit
chronos <verb> --help   # rich per-verb help with Examples + Exit codes
```

`$CHRONOS_DB` (or `--db <path>` on most verbs) selects which SQLite file
to read. Default search order: `--db` flag > `$CHRONOS_DB` > `./chronos.db`.

## Verbs

| Verb | Purpose | Reads | Writes |
| --- | --- | --- | --- |
| [`info`](#info) | Environment diagnostics | — | — |
| [`web`](#web) | Local HTTP API + browser viewer | DB | — |
| [`replay`](#replay) | Step through a run node-by-node (TUI) | DB | — |
| [`tree`](#tree) | Print the fork-family tree | DB | — |
| [`diff`](#diff) | Side-by-side compare of 2 runs | DB | — |
| [`compare`](#compare) | N-way fork-sweep compare (with `--eval` scoring) | DB | — |
| [`eval run`](#eval-run) | Score a recorded run with a registered evaluator | DB | DB |
| [`eval list`](#eval-list) | List a run's persisted evaluations | DB | — |
| [`eval list-evaluators`](#eval-list-evaluators) | List registered evaluators | — | — |
| [`verify-golden`](#verify-golden) | Compare run vs. on-disk fixture | DB + fixture | — |
| [`runs list`](#runs-list) | List recorded runs | DB | — |
| [`runs show`](#runs-show) | Show one run's nodes + metadata | DB | — |
| [`forks show`](#forks-show) | Show a fork's parent ↔ child | DB | — |
| [`fork plan`](#fork-plan) | Emit a fork plan JSON / Python stub | DB | `fork_plan.json` |

### Exit-code conventions

Most verbs follow this contract:

| Code | Meaning |
| --- | --- |
| `0` | Happy path — output printed, no errors. |
| `1` | Logical error: id not found, ambiguous fork point, etc. (actionable hint printed). |
| `2` | Input / environment error: bad flag value, missing/unreadable DB, missing fixture. |
| `3` | (`verify-golden` only) — secret detected in fixture; re-record needed. |

---

### `info`

```
chronos info
```

Prints version, Python runtime, default DB path, and the registered
command surface. Useful as a smoke test or for bug reports.

---

### `web`

```
chronos web [--host 127.0.0.1] [--port 8765] [--db PATH] [--no-browser]
```

Serves the local HTTP API (FastAPI, read-only, loopback by default) and
opens the viewer in a browser tab. From the landing page you can hit
`/runs`, `/runs/{id}/tree`, and `/docs` (Swagger UI).

Install the `[web]` extra once: `uv pip install 'chronos-agent[web]'`.

**Examples**

```bash
chronos web                    # default: 127.0.0.1:8765
chronos web --port 9000        # custom port
chronos web --no-browser       # don't auto-open a tab (SSH/headless)
```

**Exit codes**

- `0` — server started cleanly (Ctrl-C to stop).
- `1` — port already in use, or `[web]` extra not installed (hint: `uv pip install 'chronos-agent[web]'`).
- `2` — chronos.db missing or unreadable.

---

### `replay`

```
chronos replay <run_id> [--db PATH] [--from-index N] [...]
```

Interactive TUI for stepping through a recorded run node-by-node. Shows
state-before / state-after / inputs / outputs at each step.

**Examples**

```bash
chronos replay <run_id>
chronos replay <run_id> --from-index 3
```

**Exit codes**

- `0` — interactive session exited cleanly.
- `1` — no such run (hint: `chronos runs list`).
- `2` — chronos.db missing or unreadable.

---

### `tree`

```
chronos tree <run_id> [--json] [--depth N]
```

Prints the fork-family tree rooted at the given run (ADR-025). Each node
is one run; children are forks of their parent. Use `--json` for
machine-readable output (consumed by the web viewer).

**Examples**

```bash
chronos tree <run_id>
chronos tree <run_id> --json | jq '.nodes | length'
```

**Exit codes**

- `0` — tree printed.
- `1` — no such run (hint: `chronos runs list`).
- `2` — chronos.db missing or unreadable.

---

### `diff`

```
chronos diff <run_a> <run_b> [--full] [--verbose] [--show-usage] [--json]
```

Side-by-side compare of two runs (ADR-006 alignment). When run B is a
fork-child of run A, the shared prefix is hidden by default — pass
`--full` to compare end-to-end.

**Examples**

```bash
chronos diff 7c3f9e2a 9b1d8e4c
chronos diff 7c3f9e2a 9b1d8e4c --full --verbose
chronos diff 7c3f9e2a 9b1d8e4c --json | jq '.summary'
chronos diff 7c3f9e2a 9b1d8e4c --show-usage
```

**Exit codes**

- `0` — table or JSON printed.
- `1` — either run id not found (hint: `chronos runs list`).
- `2` — chronos.db missing or unreadable.

---

### `compare`

```
chronos compare <pivot> <other> [<other> ...] [--full] [--json]
chronos compare --auto-pivot <run> <run> [<run> ...]
chronos compare --matrix <run> <run> [<run> ...]
```

N-way fork-sweep debugger. First positional is the pivot; the rest are
aligned against it. `N=2` is numerically identical to `chronos diff` on
the summary row.

- `--auto-pivot` (ADR-024) — selects the pivot by argmin mean
  structural distance (tie-break: lex-smallest run id).
- `--matrix` (R65) — emits only the pairwise distance matrix, no
  centroid or merged alignment. Mutually exclusive with `--auto-pivot`.

**Examples**

```bash
chronos compare run_001 run_002                        # N=2
chronos compare run_001 run_002 run_003 run_004        # N=4
chronos compare run_001 run_002 run_003 --json
chronos compare run_001 run_002 --full                 # don't slice
chronos compare --auto-pivot run_001 run_002 run_003
chronos compare --matrix run_001 run_002 run_003
```

**Exit codes**

- `0` — happy path.
- `1` — at least one id wasn't found (hint: `chronos runs list`).
- `2` — input validation: bad `--columns`, mutually-exclusive flags,
  fewer than 2 candidate runs, or duplicate ids.

---

### `eval run`

```
chronos eval run <run_id> --evaluator <name> [--db PATH] [--json]
```

Score a recorded run with a registered evaluator (ADR-030). The result is
upserted into the `evaluations` table — re-running with the same
`--evaluator` name overwrites the prior result for that `(run_id,
evaluator_name)` pair.

Built-in evaluators ship with `chronos`:

- `output_length_chars` — emits `score = len(final_state["output"])`.
- `final_state_key_present` — emits `passed = "output" in final_state`.

Third-party packages can register more via the `chronos.evaluators`
entry-point group; list everything that's currently registered with
`chronos eval list-evaluators`.

**Examples**

```bash
chronos eval run <run_id> --evaluator output_length_chars
chronos eval run <run_id> -e final_state_key_present --json
```

**Exit codes**

- `0` — happy path; row persisted.
- `1` — no such run, or unknown evaluator (hint: `chronos eval list-evaluators`).
- `2` — evaluator raised at call time; the DB is untouched.

---

### `eval list`

```
chronos eval list <run_id> [--db PATH] [--json]
```

Prints every evaluation persisted against a run, most recent first
(evaluator name, score, passed flag, rationale, timestamp).

**Examples**

```bash
chronos eval list <run_id>
chronos eval list <run_id> --json | jq .
```

**Exit codes**

- `0` — table or JSON printed (empty when no evaluations).
- `1` — no such run (hint: `chronos runs list`).

---

### `eval list-evaluators`

```
chronos eval list-evaluators [--json]
```

Lists every evaluator currently registered in the running process —
both the chronos built-ins and any plugins discovered through the
`chronos.evaluators` entry-point group.

**Examples**

```bash
chronos eval list-evaluators
chronos eval list-evaluators --json
```

**Exit codes**

- `0` — list printed (one row per evaluator).

---

### `compare --eval`

```
chronos compare <pivot> <other> [<other> ...] --eval <evaluator_name>
```

The standard `chronos compare` (see above) gains an extra `--eval` flag
that appends an "Evaluation: `<name>`" table after the alignment summary.
Each row is one of the compared runs with its persisted score, passed
flag, and rationale; runs that have never been evaluated by `<name>`
render as a dim em-dash.

Use this to answer *"of the N forks I just compared, which one scored
highest?"* without leaving the terminal. Evaluators must have been run
ahead of time (typically via `chronos eval run`).

**Example**

```bash
chronos eval run <run_a> --evaluator output_length_chars
chronos eval run <run_b> --evaluator output_length_chars
chronos compare <run_a> <run_b> --eval output_length_chars
```

The flag stacks with `--auto-pivot` and `--matrix` (mutually exclusive
with each other, both compatible with `--eval`).

---

### `verify-golden`

```
chronos verify-golden <run_id> --golden-dir <dir> [--db PATH]
```

Projects the run to its canonical `RunSummary`, compares byte-for-byte
against `<golden-dir>/expected_run.json`, and audits
`<golden-dir>/envelopes.jsonl` for known-secret shapes (ADR-028 §4).

**Exit codes**

- `0` — byte-equal AND sanitiser-clean.
- `1` — projection mismatch (unified diff printed).
- `2` — missing fixture or unknown run id.
- `3` — secret detected in `envelopes.jsonl` (re-record required).

---

### `runs list`

```
chronos runs list [--db PATH] [--limit N] [--tag TAG]
```

Lists recorded runs (most recent first). Each row shows id, adapter,
status, started_at, and tag chips.

**Examples**

```bash
chronos runs list
chronos runs list --limit 50
chronos runs list --tag prod
```

**Exit codes**

- `0` — table (or empty list) printed.
- `2` — chronos.db missing or unreadable.

---

### `runs show`

```
chronos runs show <run_id> [--db PATH]
```

Renders a single run with its node sequence and any fork that produced
it.

**Exit codes**

- `0` — run printed.
- `1` — no such run (hint: `chronos runs list`).
- `2` — chronos.db missing or unreadable.

---

### `forks show`

```
chronos forks show <fork_id> [--db PATH]
```

Shows a single fork record: parent run, fork point, overrides, child run.

**Exit codes**

- `0` — fork printed.
- `1` — no such fork (hint: `chronos runs list` + `chronos tree <run_id>`).
- `2` — chronos.db missing or unreadable.

---

### `fork plan`

```
chronos fork plan <run_id>
                  (--at-node NAME | --at-index N | --at-node-id ID)
                  [-o KEY=VAL ...] [--override-json JSON ...]
                  [--child-thread-id ID] [--reason TEXT] [--tag T ...]
                  [--out PATH] [--json] [--emit json|python]
                  [--allow-new-keys] [--db PATH]
```

Emits a fork plan artifact (ADR-008). The CLI **does not execute your
graph** — it resolves the fork point, validates overrides against the
parent node's `state_after`, and writes a small portable plan file.

Consume the plan in your code:

```python
from chronos.fork_plan import load_plan
plan = load_plan("fork_plan.json")
with recorder.fork(graph, **plan.recorder_kwargs()) as ref:
    graph.invoke(None, {"configurable": {"thread_id": plan.child_thread_id}})
```

**Examples**

```bash
chronos fork plan <run_id> --at-node tool_call -o retries=3
chronos fork plan <run_id> --at-index 4 --override-json '{"flag": true}'
chronos fork plan <run_id> --at-node-id <node_id> --emit python --out fork.py
chronos fork plan <run_id> --at-index 0 --json | jq .
```

**Exit codes**

- `0` — plan written or printed.
- `1` — fork point not found / ambiguous, override key missing in parent
  state_after (use `--allow-new-keys` if intentional).
- `2` — chronos.db missing or unreadable, or unknown `--emit` value.

---

## See also

- [`docs/CONTEXT.md`](./CONTEXT.md) — full project state and roadmap.
- [`docs/r120-acceptance.md`](./r120-acceptance.md) — R120 hard-acceptance gate.
- [`docs/design/`](./design/) — ADRs and per-feature specs.
- `chronos web` — interactive viewer that mirrors much of this surface.
