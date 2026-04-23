"""Chronos CLI — entry point and read-side commands.

v0.1 scope: read-only inspection of runs, nodes, and forks (`runs`, `forks
show`, `diff`, `replay`), plus `fork plan` which emits a portable plan
artifact consumed by user code (ADR-008). Write-side execution (`record`,
`fork run`) stays in adapter APIs.

Command surface::

    chronos --version
    chronos info
    chronos runs list [--db PATH] [--limit N] [--json]
    chronos runs show <run_id> [--db PATH] [--json]
    chronos forks show <fork_id> [--db PATH] [--json]
    chronos diff <run_a> <run_b> [--db PATH] [--json] [--verbose] [--full]
    chronos replay <run_id> [--db PATH] [--no-interactive]
    chronos fork plan <run_id> (--at-node N | --at-index K | --at-node-id ID)
        [--override k=v]... [--override-json JSON] [--child-thread-id T]
        [--reason R] [--tag T]... [--out PATH] [--json] [--allow-new-keys]
        [--db PATH]

All commands honour ``CHRONOS_DB`` env var as a fallback for ``--db``, and
default to ``./chronos.db`` if neither is set.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from chronos import __version__
from chronos.core.diff import DiffReport, DiffRunNotFoundError, diff_runs
from chronos.core.models import Fork, Node, Run
from chronos.store.sqlite import SqliteStore

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

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_DEFAULT_DB = "chronos.db"


def _resolve_db_path(db: Path | None) -> Path:
    """Resolve DB path: CLI flag > env var > cwd default."""
    if db is not None:
        return db
    env = os.environ.get("CHRONOS_DB")
    if env:
        return Path(env)
    return Path(_DEFAULT_DB)


def _open_store(db: Path | None) -> SqliteStore:
    """Open store, exiting with a friendly error if the file is missing.

    We deliberately do NOT auto-create the file for read commands — creating
    an empty DB on ``runs list`` in the wrong directory is a silent footgun.
    Writers (adapters) are the only callers allowed to initialise a DB.
    """
    path = _resolve_db_path(db)
    if not path.exists():
        console.print(
            f"[red]error:[/] chronos DB not found at [bold]{path}[/]. "
            "Set --db or CHRONOS_DB, or record a run first."
        )
        raise typer.Exit(code=2)
    try:
        return SqliteStore.open(path)
    except Exception as exc:  # pragma: no cover — defensive
        console.print(f"[red]error:[/] failed to open {path}: {exc}")
        raise typer.Exit(code=2) from exc


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _run_to_dict(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "adapter": run.adapter,
        "adapter_thread_id": run.adapter_thread_id,
        "status": run.status.value,
        "started_at": run.started_at.isoformat(),
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "task_description": run.task_description,
        "tags": run.tags,
        "metadata": run.metadata,
        "initial_state": run.initial_state,
        "final_state": run.final_state,
    }


def _node_to_dict(node: Node) -> dict[str, Any]:
    return {
        "id": node.id,
        "run_id": node.run_id,
        "step_index": node.step_index,
        "node_name": node.node_name,
        "kind": node.kind.value,
        "parent_node_id": node.parent_node_id,
        "started_at": node.started_at.isoformat(),
        "ended_at": node.ended_at.isoformat() if node.ended_at else None,
        "state_after": node.state_after,
        "model_name": node.model_name,
        "tool_name": node.tool_name,
        "error_message": node.error_message,
        "metadata": node.metadata,
    }


def _fork_to_dict(fork: Fork) -> dict[str, Any]:
    return {
        "id": fork.id,
        "parent_run_id": fork.parent_run_id,
        "parent_node_id": fork.parent_node_id,
        "child_run_id": fork.child_run_id,
        "created_at": fork.created_at.isoformat(),
        "edited_fields": fork.edited_fields,
        "reason": fork.reason,
    }


def _emit_json(payload: Any) -> None:
    # Use plain ``print`` (not the Rich console) so the output is a clean JSON
    # document consumable by jq / scripts. Rich would otherwise wrap at the
    # terminal width.
    print(json.dumps(payload, indent=2, default=str))


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
    console.print("Status: pre-alpha (Phase 1 M1.10 — fork plan CLI, v0.1.1)")
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
) -> None:
    """List recorded runs (most recent first)."""
    store = _open_store(db)
    try:
        runs = store.list_runs(limit=limit)
    finally:
        store.close()

    if json_out:
        _emit_json([_run_to_dict(r) for r in runs])
        return

    if not runs:
        console.print("[yellow]no runs recorded yet[/]")
        return

    table = Table(
        title=f"Runs ({len(runs)})",
        show_lines=False,
        header_style="bold cyan",
    )
    table.add_column("id", style="cyan", no_wrap=True)
    table.add_column("adapter")
    table.add_column("thread")
    table.add_column("status")
    table.add_column("started_at")
    table.add_column("task", overflow="fold")
    for r in runs:
        table.add_row(
            r.id,
            r.adapter,
            r.adapter_thread_id,
            r.status.value,
            r.started_at.isoformat(timespec="seconds"),
            _truncate(r.task_description or "", 80),
        )
    console.print(table)


@runs_app.command("show")
def runs_show(
    run_id: str = typer.Argument(..., help="Run id (see `chronos runs list`)."),
    db: Path | None = typer.Option(
        None, "--db", help="Path to chronos.db (overrides $CHRONOS_DB)."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a tree."),
) -> None:
    """Show one run, including its node tree."""
    store = _open_store(db)
    try:
        run = store.get_run(run_id)
        if run is None:
            console.print(f"[red]error:[/] no such run: [bold]{run_id}[/]")
            raise typer.Exit(code=1)
        nodes = store.get_nodes_for_run(run_id)
        fork = store.get_fork_for_child(run_id)
    finally:
        store.close()

    if json_out:
        _emit_json(
            {
                "run": _run_to_dict(run),
                "nodes": [_node_to_dict(n) for n in nodes],
                "fork_of": _fork_to_dict(fork) if fork else None,
            }
        )
        return

    header = (
        f"[bold cyan]{run.id}[/] "
        f"[dim]({run.adapter}/{run.adapter_thread_id})[/] "
        f"[yellow]{run.status.value}[/]"
    )
    root = Tree(header)
    root.add(f"task: {run.task_description or '-'}")
    root.add(
        f"started: {run.started_at.isoformat(timespec='seconds')}"
        + (f"    ended: {run.ended_at.isoformat(timespec='seconds')}" if run.ended_at else "")
    )
    if run.tags:
        root.add(f"tags: {', '.join(run.tags)}")
    if fork is not None:
        root.add(
            f"[magenta]forked from[/] {fork.parent_run_id} @ node {fork.parent_node_id} "
            f"[dim](fork {fork.id})[/]"
        )
    nlist = root.add(f"nodes ({len(nodes)})")
    for n in nodes:
        label = (
            f"[{n.step_index}] [green]{n.node_name}[/] [dim]{n.kind.value}[/] [dim cyan]{n.id}[/]"
        )
        nnode = nlist.add(label)
        if n.parent_node_id:
            nnode.add(f"[dim]parent: {n.parent_node_id}[/]")
        if n.tool_name:
            nnode.add(f"tool: {n.tool_name}")
        if n.error_message:
            nnode.add(f"[red]error: {_truncate(n.error_message, 120)}[/]")
    console.print(root)


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
    store = _open_store(db)
    try:
        fork = store.get_fork(fork_id)
        if fork is None:
            console.print(f"[red]error:[/] no such fork: [bold]{fork_id}[/]")
            raise typer.Exit(code=1)
        parent = store.get_run(fork.parent_run_id)
        child = store.get_run(fork.child_run_id)
        child_nodes = store.get_nodes_for_run(fork.child_run_id) if child else []
    finally:
        store.close()

    if json_out:
        _emit_json(
            {
                "fork": _fork_to_dict(fork),
                "parent_run": _run_to_dict(parent) if parent else None,
                "child_run": _run_to_dict(child) if child else None,
                "child_nodes": [_node_to_dict(n) for n in child_nodes],
            }
        )
        return

    root = Tree(f"[bold magenta]Fork[/] {fork.id}")
    root.add(
        f"created: {fork.created_at.isoformat(timespec='seconds')}    reason: {fork.reason or '-'}"
    )
    pnode = root.add(f"[cyan]parent[/] {fork.parent_run_id} @ node {fork.parent_node_id}")
    if parent is not None:
        pnode.add(f"task: {parent.task_description or '-'}")
        pnode.add(f"status: {parent.status.value}")
    else:
        pnode.add("[red]parent run not found in DB[/]")

    cnode = root.add(f"[green]child[/] {fork.child_run_id}")
    if child is not None:
        cnode.add(f"task: {child.task_description or '-'}")
        cnode.add(f"status: {child.status.value}    nodes: {len(child_nodes)}")
        if child_nodes:
            nlist = cnode.add("downstream")
            for n in child_nodes:
                nlist.add(f"[{n.step_index}] [green]{n.node_name}[/] [dim]{n.kind.value} {n.id}[/]")
    else:
        cnode.add("[red]child run not found in DB[/]")

    edits = root.add(f"[yellow]edited_fields[/] ({len(fork.edited_fields)})")
    if not fork.edited_fields:
        edits.add("[dim]<none — pure replay>[/]")
    for k, v in fork.edited_fields.items():
        v_repr = repr(v)
        edits.add(f"[bold]{k}[/] = {_truncate(v_repr, 120)}")
    console.print(root)


# ---------------------------------------------------------------------------
# `chronos diff`
# ---------------------------------------------------------------------------


_TAG_STYLE = {
    "equal": "dim",
    "changed": "yellow",
    "added": "green",
    "removed": "red",
}
_TAG_SYMBOL = {
    "equal": "=",
    "changed": "~",
    "added": "+",
    "removed": "-",
}


def _render_diff_table(report: DiffReport, verbose: bool) -> Table:
    table = Table(
        title=(
            f"Diff {report.run_a.id} → {report.run_b.id}"
            + (" (downstream of fork)" if report.restricted_to_downstream else "")
        ),
        show_lines=verbose,
        header_style="bold cyan",
    )
    table.add_column("", no_wrap=True, width=2)
    table.add_column("tag", no_wrap=True)
    table.add_column("node_name", overflow="fold")
    table.add_column("a (step)", no_wrap=True)
    table.add_column("b (step)", no_wrap=True)
    table.add_column("details", overflow="fold")

    for e in report.entries:
        style = _TAG_STYLE[e.tag]
        sym = _TAG_SYMBOL[e.tag]
        a_step = str(e.a.step_index) if e.a else "—"
        b_step = str(e.b.step_index) if e.b else "—"
        details = ""
        if e.tag == "changed" and e.state_diff is not None:
            parts: list[str] = []
            if e.state_diff.added_keys:
                parts.append(f"+{','.join(e.state_diff.added_keys)}")
            if e.state_diff.removed_keys:
                parts.append(f"-{','.join(e.state_diff.removed_keys)}")
            if e.state_diff.changed_keys:
                parts.append(f"~{','.join(e.state_diff.changed_keys.keys())}")
            details = "  ".join(parts)
            if verbose and e.state_diff.changed_keys:
                long_bits = []
                for k, ab in e.state_diff.changed_keys.items():
                    long_bits.append(
                        f"{k}: {_truncate(repr(ab['a']), 60)} → {_truncate(repr(ab['b']), 60)}"
                    )
                details += "\n" + "\n".join(long_bits)
        table.add_row(
            f"[{style}]{sym}[/]",
            f"[{style}]{e.tag}[/]",
            e.node_name,
            a_step,
            b_step,
            details,
        )
    return table


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
) -> None:
    """Structural diff of two recorded runs (ADR-006 alignment)."""
    store = _open_store(db)
    try:
        try:
            report = diff_runs(store, run_a, run_b, restrict_to_downstream=not full)
        except DiffRunNotFoundError as exc:
            console.print(f"[red]error:[/] no such run: [bold]{exc.run_id}[/]")
            raise typer.Exit(code=1) from exc
    finally:
        store.close()

    if json_out:
        _emit_json(report.to_dict())
        return

    summary = report.summary
    if report.fork is not None and report.restricted_to_downstream:
        console.print(
            f"[magenta]B is forked from A @ node[/] "
            f"[bold]{report.fork_point_node_name}[/] "
            f"[dim](fork {report.fork.id})[/] — diffing downstream only. "
            "Use --full for full-run diff."
        )
    console.print(_render_diff_table(report, verbose=verbose))
    console.print(
        "[bold]summary[/]: "
        f"[dim]{summary['equal']} equal[/]  "
        f"[yellow]{summary['changed']} changed[/]  "
        f"[green]{summary['added']} added[/]  "
        f"[red]{summary['removed']} removed[/]"
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
        allow_new_keys=allow_new_keys,
        db=db,
        open_store_fn=_open_store,
        console=console,
    )


if __name__ == "__main__":
    app()
