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

## `chronos runs list`

List recorded runs, most recent first.

```bash
chronos runs list [--db PATH] [-n LIMIT] [--json]
```

| Flag        | Default | Meaning                                       |
|-------------|---------|-----------------------------------------------|
| `--db PATH` | `./chronos.db` or `$CHRONOS_DB` | Path to the Chronos DB. |
| `-n LIMIT`  | 50      | Max rows to return (1–10000).                 |
| `--json`    | off     | Emit newline-terminated JSON instead of a table. |

Exit codes: `0` success, `2` DB not found.

---

## `chronos runs show <run_id>`

Print the node tree of a single run — one row per node with step index, name, kind, and timing.

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
chronos diff <run_a> <run_b> [--db PATH] [--json] [--verbose] [--full]
```

| Flag          | Default | Meaning                                                     |
|---------------|---------|-------------------------------------------------------------|
| `--db PATH`   | `./chronos.db`| DB path.                                              |
| `--json`      | off     | Emit the frozen ADR-006 JSON schema instead of a table.     |
| `-v` / `--verbose` | off | Expand every CHANGED node into per-key `key: <a> → <b>` diff. |
| `--full`      | off     | Disable fork-aware slicing. By default, if B is a fork child of A, the diff is restricted to nodes *after* the fork point (because everything before it is identical by construction). Pass `--full` to force a full-run comparison. |

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
