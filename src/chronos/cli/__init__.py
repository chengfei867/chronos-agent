"""Chronos CLI — entry point and command registration.

v0.1 scope: read-only inspection of runs, nodes, and forks (`runs`, `forks
show`, `diff`, `replay`), plus `fork plan` which emits a portable plan
artifact consumed by user code (ADR-008). Write-side execution (`record`,
`fork run`) stays in adapter APIs.

Command surface::

    chronos --version
    chronos info
    chronos web [--host HOST] [--port N] [--db PATH] [--no-browser]
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
        "Status: Phase 4 Arc A complete (v0.6.0 R65-R67), "
        "Arc B slice 1 GA (R70-R87, anthropic_agents adapter, record + fork + override + MCP + override-fork live-smoke), "
        "adapter-1-3 zero-regression streak R52->R87 = 35 rounds, "
        "v0.7.0"
    )
    console.print(
        "Commands: [green]runs list/show, forks show, diff, replay, fork plan, web[/green] "
        "available; [dim]record[/dim] [yellow](adapter-level only)[/yellow]"
    )


@app.command("web")
def web_cmd(
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Bind address. Default is loopback — don't expose to a network.",
    ),
    port: int = typer.Option(
        8765,
        "--port",
        "-p",
        min=1,
        max=65535,
        help="TCP port to serve on.",
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Don't auto-open a browser tab (useful on headless hosts or over SSH).",
    ),
) -> None:
    """Serve the local HTTP API and open the viewer in your browser.

    Starts a local FastAPI server (read-only, loopback-only) backed by your
    ``chronos.db`` and opens a browser tab at the landing page. From there
    you can hit ``/runs``, ``/runs/{id}/tree``, and ``/docs`` (Swagger UI).

    Install the ``[web]`` extra once: ``uv pip install 'chronos-agent[web]'``.

    Example::

        chronos web                    # default: 127.0.0.1:8765
        chronos web --port 9000        # custom port
        chronos web --no-browser       # don't auto-open a tab (SSH/headless)
    """
    from chronos.cli.web import web_command

    web_command(
        host=host,
        port=port,
        db=db,
        no_browser=no_browser,
        open_store_fn=_open_store,
        console=console,
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
# `chronos tree`
# ---------------------------------------------------------------------------


@app.command("tree")
def tree(
    run_id: str = typer.Argument(..., help="Run id (see `chronos runs list`)."),
    descendants: bool = typer.Option(
        False,
        "--descendants",
        help=(
            "Include every run that descends from this one via forks "
            "(the whole fork family, rooted at run_id)."
        ),
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Emit JSON (byte-for-byte the HTTP response shape)."
    ),
) -> None:
    """Show the fork-family tree rooted at a run (ADR-025)."""
    from chronos.cli.tree import tree_command

    tree_command(
        run_id=run_id,
        db=db,
        descendants=descendants,
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
    """Compare two recorded runs side-by-side (the 'compare' verb — ADR-006 alignment)."""
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
# `chronos compare` — N-run pivot-anchored diff (Phase 4 Arc A, R59)
# ---------------------------------------------------------------------------


@app.command("compare")
def compare_cmd(
    pivot_run_id: str = typer.Argument(
        ..., help="Pivot run id — the 'before' / reference run all others align against."
    ),
    other_run_ids: list[str] = typer.Argument(
        ...,
        help=(
            "One or more other run ids to compare against the pivot. "
            "Minimum 1 other; N > 8 prints a soft warning."
        ),
        show_default=False,
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit the merged alignment as JSON (stable contract — design doc §5.1).",
    ),
    restrict_to_downstream: bool = typer.Option(
        True,
        "--restrict-to-downstream/--full",
        "-R/-F",
        help=(
            "When an other run is a forked child of the pivot, skip the shared prefix. "
            "Default. Applied per (pivot, other) pair. Use --full for apples-to-apples."
        ),
    ),
    columns: str = typer.Option(
        "changed-or-added",
        "--columns",
        help="Which rows to render in text mode: all | changed | changed-or-added.",
    ),
    show_equal: bool = typer.Option(
        False,
        "--show-equal",
        help="In --columns=all text mode, also print rows where every column is equal.",
    ),
    width: int | None = typer.Option(
        None,
        "--width",
        help="Override terminal width for the rendered table (useful in narrow panes).",
    ),
    auto_pivot: bool = typer.Option(
        False,
        "--auto-pivot",
        help=(
            "Pick the pivot automatically via pairwise structural distance "
            "(Arc A slice 4, ADR-024). Under this flag, every positional is "
            "a candidate — no designated pivot. Tie-break: lexicographic run id."
        ),
    ),
    show_matrix: bool = typer.Option(
        False,
        "--show-matrix",
        help=(
            "With --auto-pivot, render the full pairwise distance matrix "
            "instead of the default first-3-rows snippet. No-op without "
            "--auto-pivot."
        ),
    ),
    matrix: bool = typer.Option(
        False,
        "--matrix",
        help=(
            "Emit only the pairwise distance matrix (Arc A slice 5, R65). "
            "All positionals are candidates; no pivot selection, no merged "
            "alignment. Cheaper than --auto-pivot when you only need to see "
            "how far apart N runs are. Mutually exclusive with --auto-pivot."
        ),
    ),
) -> None:
    """Compare N recorded runs against a pivot (fork-sweep debugger).

    First positional is the pivot; all other positionals are aligned
    against it. N=2 is numerically identical to ``chronos diff`` on
    the summary row. See ``docs/design/n-run-compare.md`` for the
    full spec.

    With ``--auto-pivot`` (ADR-024, Arc A slice 4), all positionals are
    treated as candidates and the pivot is selected by argmin mean
    structural distance (tie-break: lex smallest run id).

    With ``--matrix`` (Arc A slice 5, R65), all positionals are treated
    as candidates and only the pairwise distance matrix is printed — no
    centroid selection or merged alignment. Mutually exclusive with
    ``--auto-pivot``.

    Examples::

        chronos compare run_001 run_002                        # N=2
        chronos compare run_001 run_002 run_003 run_004        # N=4
        chronos compare run_001 run_002 run_003 --json         # JSON contract
        chronos compare run_001 run_002 --full                 # don't slice
        chronos compare --auto-pivot run_001 run_002 run_003   # auto-centroid
        chronos compare --matrix run_001 run_002 run_003       # matrix only
    """
    from chronos.cli.compare import compare_command

    compare_command(
        pivot_run_id=pivot_run_id,
        other_run_ids=list(other_run_ids),
        db=db,
        json_out=json_out,
        restrict_to_downstream=restrict_to_downstream,
        columns=columns,
        show_equal=show_equal,
        width=width,
        auto_pivot=auto_pivot,
        show_matrix=show_matrix,
        matrix=matrix,
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
