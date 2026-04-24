# CLI Reference

Chronos is installed as the `chronos` command. All subcommands accept `--db PATH` (overrides the `CHRONOS_DB` env var; falls back to `./chronos.db`).

```
chronos [OPTIONS] COMMAND [ARGS]...
```

## Global options

| Flag          | Meaning                           |
|---------------|-----------------------------------|
| `-v` / `--version` | Print version and exit.      |
| `--help`      | Show help for any command/subcmd. |

---

## `chronos info`

Print environment diagnostics (Python version, Chronos version, loaded modules). Useful for bug reports.

```bash
chronos info
```

---

## `chronos web`

Serve the local HTTP API and open a browser tab pointed at it. The fastest path from "I recorded some runs" to "I can see them" — no frontend build step, no config. Requires the optional `[web]` extra (`uv pip install 'chronos-agent[web]'`).

```bash
chronos web [--host HOST] [-p PORT] [--db PATH] [--no-browser]
```

| Flag            | Default         | Meaning                                                           |
|-----------------|-----------------|-------------------------------------------------------------------|
| `--host HOST`   | `127.0.0.1`     | Bind address. Keep on loopback — there is no auth.                |
| `-p`, `--port`  | `8765`          | TCP port.                                                         |
| `--db PATH`     | `./chronos.db` or `$CHRONOS_DB` | Path to the Chronos DB.                           |
| `--no-browser`  | off             | Don't auto-open a tab. Use on headless hosts / over SSH tunnels.  |

Opens a dark-themed landing page at `/` that links to:
- `/runs` — list of recorded runs (JSON)
- `/runs/{id}` / `/runs/{id}/nodes` / `/runs/{id}/forks` / `/runs/{id}/tree` — per-run endpoints
- `/docs` — Swagger UI (interactive API console)
- `/healthz` — liveness + schema version

Stop the server with `Ctrl-C`.

Example:

```bash
chronos web --db examples/chronos.db
# → http://127.0.0.1:8765 opens in your browser
```

Over SSH, forward the port and skip the auto-open:

```bash
# on the server
chronos web --no-browser
# on your laptop
ssh -L 8765:127.0.0.1:8765 remote.host  # then open http://localhost:8765
```

---

## `chronos runs list`

List recorded runs, most recent first.

```bash
chronos runs list [--db PATH] [-n LIMIT] [--json] [--with-usage]
```

| Flag        | Default | Meaning                                       |
|-------------|---------|-----------------------------------------------|
| `--db PATH` | `./chronos.db` or `$CHRONOS_DB` | Path to the Chronos DB. |
| `-n LIMIT`  | 50      | Max rows to return (1–10000).                 |
| `--json`    | off     | Emit newline-terminated JSON instead of a table. |
| `--with-usage` | off  | Aggregate token counts and cost (¢) for each run. One extra SQL fetch per row — opt-in for performance. Requires runs whose adapter was given a `usage_extractor` (see [ADR-009](decisions/ADR-009-usage-extractor-hook.md)). |

Exit codes: `0` success, `2` DB not found.

---

## `chronos runs show <run_id>`

Print the node tree of a single run — one row per node with step index, name, kind, and timing. If any node has captured `usage`, per-node tokens appear inline and a total-usage line prints at the top.

```bash
chronos runs show <run_id> [--db PATH] [--json]
```

Exit codes: `0` success, `1` run id not found, `2` DB not found.

---

## `chronos replay <run_id>`

Step through the nodes of a recorded run interactively. See [ADR-007](decisions/ADR-007-replay-tui-framework.md) for why we use `rich.live` and roll a minimal keyboard reader instead of pulling in a full TUI framework.

```bash
chronos replay <run_id> [--db PATH] [--no-interactive]
```

| Flag                 | Default | Meaning                                                       |
|----------------------|---------|---------------------------------------------------------------|
| `--db PATH`          | `./chronos.db` | DB path.                                              |
| `--no-interactive`   | off     | Force static (non-TTY) rendering. Auto-enabled when stdin/stdout isn't a TTY (CI, pipes, `tee`). |

### Interactive keyboard

| Key                 | Action              |
|---------------------|---------------------|
| `space` / `→` / `↓` | Next node           |
| `←` / `↑`           | Previous node       |
| `home`              | Jump to first node  |
| `end`               | Jump to last node   |
| `q` / `Ctrl-C`      | Quit                |

### Non-interactive mode

When not attached to a TTY (or when `--no-interactive` is passed), `replay` prints every node's detail panel in order so the output can be captured to a file, piped to `jq`/`grep`, or run in CI.

Exit codes: `0`, `1` run id not found, `2` DB not found.

---

## `chronos forks show <fork_id>`

Print a single fork record — parent run, child run, fork-point node, reason, overrides, and lineage.

```bash
chronos forks show <fork_id> [--db PATH] [--json]
```

Exit codes: `0`, `1` fork id not found, `2` DB not found.

---

## `chronos diff <run_a> <run_b>`

Structural diff of two runs (see [ADR-006](decisions/ADR-006-diff-alignment.md) for the alignment algorithm).

```bash
chronos diff <run_a> <run_b> [--db PATH] [--json] [--verbose] [--full] [--show-usage]
```

| Flag          | Default | Meaning                                                     |
|---------------|---------|-------------------------------------------------------------|
| `--db PATH`   | `./chronos.db`| DB path.                                              |
| `--json`      | off     | Emit the frozen ADR-006 JSON schema instead of a table. With `--show-usage` the JSON gains a `usage` field with A/B totals and Δ.  |
| `-v` / `--verbose` | off | Expand every CHANGED node into per-key `key: <a> → <b>` diff. |
| `--full`      | off     | Disable fork-aware slicing. By default, if B is a fork child of A, the diff is restricted to nodes *after* the fork point (because everything before it is identical by construction). Pass `--full` to force a full-run comparison. |
| `--show-usage` | off    | Append a side-by-side A vs B token/cost table with Δ (B − A). Positive deltas render red (regression), negative green (savings). Requires `usage_extractor` was attached at record time ([ADR-009](decisions/ADR-009-usage-extractor-hook.md)). |

### Tags (row prefix column)

| Symbol | Tag      | Meaning |
|--------|----------|---------|
| `=`    | `equal`  | Same node position and identical `state_after`.   |
| `~`    | `changed`| Same node position, **different** `state_after`.  |
| `+`    | `added`  | Node present in B but not A.                      |
| `−`    | `removed`| Node present in A but not B.                      |

### Details column

For `changed` entries, a compact summary `+added,-removed,~changed` of which keys in `state_after` differ. With `--verbose`, each changed key is expanded as `key: <repr(a)> → <repr(b)>` on its own line.

Exit codes: `0`, `1` a run id not found, `2` DB not found.

---

## `chronos fork plan <run_id>`

Emit a portable **fork plan** JSON artifact — a description of a proposed fork that your code consumes via `chronos.fork_plan.load_plan()`. The CLI never executes your graph; see [ADR-008](decisions/ADR-008-fork-cli-plan-artifact.md) for the rationale.

```bash
chronos fork plan <run_id> \
  (--at-node <name> | --at-index <k> | --at-node-id <uid>) \
  [--override key=value]... \
  [--override-json '{"k": ...}'] \
  [--child-thread-id <str>] \
  [--reason <str>] \
  [--tag <str>]... \
  [--out <path>] \
  [--json] \
  [--allow-new-keys] \
  [--db <path>]
```

**Fork-point selector** (exactly one required):

- `--at-node <name>` — by node name. Errors if the name appears more than once (loops/routers).
- `--at-index <k>` — by 0-based `step_index`. Always unambiguous.
- `--at-node-id <uid>` — by the node's SQLite id. Useful when piping.

**Overrides:**

- `--override k=v` — single override. `v` is JSON-parsed first (`3`, `true`, `[1,2]`), falls back to raw string. Repeatable.
- `--override-json '{...}'` — merge a full JSON object. Applied after `--override` tokens, so it wins on collisions.
- `--allow-new-keys` — permit override keys that don't exist in the parent node's `state_after`. Default: reject unknown keys to catch typos.

**Output:**

- Default: write plan to `./fork_plan.json` and print a Rich preview.
- `--out <path>` — write somewhere else.
- `--json` — emit plan JSON to stdout instead (no file, no preview). Ideal for piping.

**Consume the plan in your code:**

```python
from chronos.fork_plan import load_plan

plan = load_plan("fork_plan.json")
with recorder.fork(graph, **plan.recorder_kwargs()) as ref:
    graph.invoke(None, {"configurable": {"thread_id": plan.child_thread_id}})
print("forked →", ref.child_run_id)
```

`plan.recorder_kwargs()` returns exactly the kwargs accepted by `LangGraphRecorder.fork()` — no extra fields leak through.

**Example:**

```bash
chronos fork plan 2d8ba237-... \
    --at-node research \
    --override research="alt-take" \
    --reason "swap researcher prompt" \
    --tag experiment \
    --db chronos.db
# writes fork_plan.json; commit it alongside your experiment script.
```

---

## Token usage & cost tracking (ADR-009, ADR-010)

Chronos stores per-node `usage` (prompt/completion tokens, model name) and `cost_usd_cents` in the SQLite schema. These fields only populate if you supply a `usage_extractor` when constructing the adapter. Three batteries are included, one per common LangChain path:

```python
from chronos.adapters import LangGraphRecorder
from chronos.adapters.langgraph_usage import (
    aimessage_usage_extractor,      # AIMessage.usage_metadata (LC 0.3+ standard)
    anthropic_usage_extractor,      # response_metadata["usage"]  (ChatAnthropic)
    openai_usage_extractor,         # response_metadata["token_usage"] (ChatOpenAI)
)

recorder = LangGraphRecorder(
    store,
    kind_map=NODE_KIND_MAP,
    usage_extractor=anthropic_usage_extractor,
)
```

| Extractor | Reads from | Handles |
|-----------|------------|---------|
| `aimessage_usage_extractor` | `AIMessage.usage_metadata` | LangChain 0.3+ standard shape; `output_token_details.reasoning` |
| `anthropic_usage_extractor` | `response_metadata["usage"]` | Anthropic shape; folds `cache_creation_input_tokens` + `cache_read_input_tokens` into `prompt_tokens` |
| `openai_usage_extractor` | `response_metadata["token_usage"]` | OpenAI shape; surfaces `completion_tokens_details.reasoning_tokens` for o1/o3 |

For mixed providers, compose them with `or`:

```python
def combined(ctx):
    return (
        anthropic_usage_extractor(ctx)
        or openai_usage_extractor(ctx)
        or aimessage_usage_extractor(ctx)
    )
```

For custom providers or offline meters, write your own:

```python
from chronos.adapters.langgraph_usage import UsageContext, UsageResult

def my_extractor(ctx: UsageContext) -> UsageResult | None:
    # ctx.node_name, ctx.pre_values, ctx.post_values, ctx.task
    ...
    return UsageResult(prompt_tokens=..., completion_tokens=..., cost_usd_cents=..., model_name=...)
```

Extractor errors never break capture — any raise is logged at WARNING and the node stores `usage=None`. See [ADR-009](decisions/ADR-009-usage-extractor-hook.md) for the protocol and [ADR-010](decisions/ADR-010-native-usage-extractors.md) for the native extractors' field mappings.

**Surface in CLI:**
- `chronos runs show <id>` — total-usage line + per-node inline tokens.
- `chronos runs list --with-usage` — per-run token/cost columns.
- `chronos diff A B --show-usage` — side-by-side A vs B vs Δ.
- All three also appear in `--json` output when the data is populated.

---

## Environment variables

| Var           | Used by | Meaning                                 |
|---------------|---------|-----------------------------------------|
| `CHRONOS_DB`  | all read commands | Default DB path when `--db` is not passed. |

---

## Quick recipes

**Find the most recent fork child:**

```bash
chronos runs list --json --db chronos.db \
  | jq -r '[.[] | select(.tags | index("fork"))][0].id'
```

**Dump a run as JSON for external analysis:**

```bash
chronos runs show <id> --json --db chronos.db > run.json
```

**Compare two un-related runs (not fork-linked):**

```bash
chronos diff <run_a> <run_b> --db chronos.db
# (fork-aware slicing is only applied when a Fork record exists linking a→b)
```

**Pipe JSON diffs into a script:**

```bash
chronos diff A B --json --db chronos.db | jq '.summary'
```
