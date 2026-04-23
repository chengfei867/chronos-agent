"""Chronos CLI — entry point and command registration.

v0.1 scope: read-only inspection of runs, nodes, and forks (`runs`, `forks
show`, `diff`, `replay`), plus `fork plan` which emits a portable plan
artifact consumed by user code (ADR-008). Write-side execution (`record`,
`fork run`) stays in adapter APIs.

Command surface::

    chronos --version
    chronos info
    chronos runs list [--db PATH] [--limit N] [--json] [--with-usage]
    chronos runs show <run_id> [--db PATH] [--json]
    chronos forks show <fork_id> [--db PATH] [--json]
    chronos diff <run_a> <run_b> [--db PATH] [--json] [--verbose] [--full]
        [--show-usage]
    chronos replay <run_id> [--db PATH] [--no-interactive]
    chronos fork plan <run_id> (--at-node N | --at-index K | --at-node-id ID)
        [--override k=v]... [--override-json JSON] [--child-thread-id T]
        [--reason R] [--tag T]... [--out PATH] [--json] [--allow-new-keys]
        [--db PATH]

All commands honour ``CHRONOS_DB`` env var as a fallback for ``--db``, and
default to ``./chronos.db`` if neither is set.

Module layout (R14 split):
- ``_common.py`` / ``_usage.py``  — shared helpers (DB open, serialise, usage)
- ``runs.py`` / ``forks.py`` / ``diff.py`` / ``replay.py`` / ``fork.py``
  — one implementation module per command group, each exposing a
  ``*_command(...)`` function called from the thin typer wrappers below.
"""

from __future__ import annotations

from pathlib import Path

import typer

from chronos import __version__
from chronos.cli._common import _open_store, console

app = typer.Typer(
    name="chronos",
    help="Time-travel debugger for multi-agent AI systems.",
    no_args_is_help=True,
    add_completion=False,
)

runs_app = typer.Typer(
    name="runs",
    help="Inspect recorded runs.",
    no_args_is_help=True,
)
forks_app = typer.Typer(
    name="forks",
    help="Inspect recorded forks (parent ↔ child lineage).",
    no_args_is_help=True,
)
fork_app = typer.Typer(
    name="fork",
    help="Plan a fork — emit a JSON artifact the user's code consumes.",
    no_args_is_help=True,
)
app.add_typer(runs_app, name="runs")
app.add_typer(forks_app, name="forks")
app.add_typer(fork_app, name="fork")


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"chronos {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Chronos Agent — record, replay, fork, and diff AI agent runs."""


@app.command()
def info() -> None:
    """Print environment diagnostics."""
    console.print(f"[bold]chronos[/bold] {__version__}")
    console.print(
        "Status: pre-alpha (Phase 1 M1.12 -- Node.model alias + "
        "fork plan --emit python (ADR-013 alt C), v0.1.6)"
    )
    console.print(
        "Commands: [green]runs list/show, forks show, diff, replay, fork plan[/green] "
        "available; [dim]record[/dim] [yellow](adapter-level only)[/yellow]"
    )


@app.command("replay")
def replay_cmd(
    run_id: str = typer.Argument(..., help="Run id (see `chronos runs list`)."),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    no_interactive: bool = typer.Option(
        False,
        "--no-interactive",
        help="Force static (non-TTY) rendering — useful for CI / piping / logs.",
    ),
) -> None:
    """Step through a recorded run node-by-node (interactive TUI).

    Keyboard controls: space/→ = next · ← = prev · home/end = first/last · q = quit.

    On a non-TTY stdin/stdout (CI, pipes, ``tee``) the command falls back
    to printing every node's detail view in order. Pass
    ``--no-interactive`` to force that fallback on a TTY too.
    """
    from chronos.cli.replay import replay_command

    replay_command(
        run_id=run_id,
        db=db,
        no_interactive=no_interactive,
        open_store_fn=_open_store,
        console=console,
    )


# ---------------------------------------------------------------------------
# `chronos runs`
# ---------------------------------------------------------------------------


@runs_app.command("list")
def runs_list(
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    limit: int = typer.Option(50, "--limit", "-n", min=1, max=10_000, help="Max rows to return."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
    with_usage: bool = typer.Option(
        False,
        "--with-usage",
        help="Include summed tokens / cost columns. Extra SELECT per run — slower for large DBs.",
    ),
) -> None:
    """List recorded runs (most recent first)."""
    from chronos.cli.runs import runs_list_command

    runs_list_command(
        db=db,
        limit=limit,
        json_out=json_out,
        with_usage=with_usage,
        open_store_fn=_open_store,
        console=console,
    )


@runs_app.command("show")
def runs_show(
    run_id: str = typer.Argument(..., help="Run id (see `chronos runs list`)."),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a tree."),
) -> None:
    """Show one run, including its node tree."""
    from chronos.cli.runs import runs_show_command

    runs_show_command(
        run_id=run_id,
        db=db,
        json_out=json_out,
        open_store_fn=_open_store,
        console=console,
    )


# ---------------------------------------------------------------------------
# `chronos forks`
# ---------------------------------------------------------------------------


@forks_app.command("show")
def forks_show(
    fork_id: str = typer.Argument(..., help="Fork id (see `chronos runs show`)."),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a tree."),
) -> None:
    """Show a fork: parent run + fork point + overrides + child run summary."""
    from chronos.cli.forks import forks_show_command

    forks_show_command(
        fork_id=fork_id,
        db=db,
        json_out=json_out,
        open_store_fn=_open_store,
        console=console,
    )


# ---------------------------------------------------------------------------
# `chronos diff`
# ---------------------------------------------------------------------------


@app.command()
def diff(
    run_a: str = typer.Argument(..., help="First run id (the 'A' side)."),
    run_b: str = typer.Argument(..., help="Second run id (the 'B' side)."),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show per-key state_after diffs inline."
    ),
    full: bool = typer.Option(
        False,
        "--full",
        help=(
            "Compare entire runs even when B is a fork child of A. "
            "Default is to restrict to post-fork-point nodes (upstream is "
            "identical by construction)."
        ),
    ),
    show_usage: bool = typer.Option(
        False,
        "--show-usage",
        help="Include token/cost comparison between run A and run B (ADR-009).",
    ),
) -> None:
    """Structural diff of two recorded runs (ADR-006 alignment)."""
    from chronos.cli.diff import diff_command

    diff_command(
        run_a=run_a,
        run_b=run_b,
        db=db,
        json_out=json_out,
        verbose=verbose,
        full=full,
        show_usage=show_usage,
        open_store_fn=_open_store,
        console=console,
    )


# ---------------------------------------------------------------------------
# `chronos fork plan` — emit fork plan artifact (ADR-008)
# ---------------------------------------------------------------------------


@fork_app.command("plan")
def fork_plan_cmd(
    run_id: str = typer.Argument(..., help="Parent run id (see `chronos runs list`)."),
    at_node: str | None = typer.Option(
        None, "--at-node", help="Fork at node with this name (errors if ambiguous)."
    ),
    at_index: int | None = typer.Option(
        None, "--at-index", help="Fork at this 0-based step index."
    ),
    at_node_id: str | None = typer.Option(
        None, "--at-node-id", help="Fork at the node with this exact id."
    ),
    overrides: list[str] = typer.Option(
        [],
        "--override",
        "-o",
        help="State override as key=value (value is JSON-parsed if possible). Repeatable.",
    ),
    overrides_json: list[str] = typer.Option(
        [],
        "--override-json",
        help="State overrides as a JSON object string; merged last, wins on collisions.",
    ),
    child_thread_id: str | None = typer.Option(
        None,
        "--child-thread-id",
        help="Override the auto-generated child thread id.",
    ),
    reason: str | None = typer.Option(
        None, "--reason", help="Human-readable reason stored on the fork record."
    ),
    tags: list[str] = typer.Option([], "--tag", help="Tag to attach to the child run. Repeatable."),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Path to write the plan JSON (default: ./fork_plan.json).",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit plan JSON to stdout instead of writing a file (no preview).",
    ),
    emit: str = typer.Option(
        "json",
        "--emit",
        help=(
            "Output format: 'json' (default, writes fork_plan.json) or "
            "'python' (writes a pastable fork_stub.py, ADR-013 alt C)."
        ),
    ),
    allow_new_keys: bool = typer.Option(
        False,
        "--allow-new-keys",
        help="Permit override keys that aren't already present in parent state_after.",
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
) -> None:
    """Emit a fork plan JSON artifact (see ADR-008).

    The CLI does not execute your graph. It resolves the fork point,
    validates overrides against the parent node's ``state_after``, and
    writes a small portable plan file. Consume it in your code::

        from chronos.fork_plan import load_plan
        plan = load_plan("fork_plan.json")
        with recorder.fork(graph, **plan.recorder_kwargs()) as ref:
            graph.invoke(None, {"configurable": {"thread_id": plan.child_thread_id}})
    """
    from chronos.cli.fork import fork_plan_command

    fork_plan_command(
        run_id=run_id,
        at_node=at_node,
        at_index=at_index,
        at_node_id=at_node_id,
        overrides=overrides,
        overrides_json=overrides_json,
        child_thread_id=child_thread_id,
        reason=reason,
        tags=tags,
        out=out,
        as_json=as_json,
        emit=emit,
        allow_new_keys=allow_new_keys,
        db=db,
        open_store_fn=_open_store,
        console=console,
    )


if __name__ == "__main__":
    app()
