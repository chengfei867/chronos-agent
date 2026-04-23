"""Implementation for ``chronos runs list`` and ``chronos runs show``.

Extracted from ``chronos.cli.__init__`` in R14. The entry-point module owns
the typer command registration and calls into the ``*_command`` functions
here, injecting ``console`` and ``open_store_fn`` so tests can stub them.

Pattern mirrors ``chronos.cli.replay`` and ``chronos.cli.fork``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from chronos.cli._common import (
    _emit_json,
    _fork_to_dict,
    _node_to_dict,
    _run_to_dict,
    _truncate,
)
from chronos.cli._usage import (
    _fmt_node_usage,
    _fmt_usage_inline,
    _RunUsageSummary,
    _sum_usage,
    _summarise_usage,
)
from chronos.store.sqlite import SqliteStore


def runs_list_command(
    *,
    db: Path | None,
    limit: int,
    json_out: bool,
    with_usage: bool,
    open_store_fn: Callable[[Path | None], SqliteStore],
    console: Console,
) -> None:
    """List recorded runs (most recent first)."""
    store = open_store_fn(db)
    try:
        runs = store.list_runs(limit=limit)
        usage_by_run: dict[str, _RunUsageSummary] = {}
        if with_usage:
            for r in runs:
                nodes = store.get_nodes_for_run(r.id)
                usage_by_run[r.id] = _summarise_usage(nodes)
    finally:
        store.close()

    if json_out:
        payload: list[dict[str, Any]] = [_run_to_dict(r) for r in runs]
        if with_usage:
            for item, r in zip(payload, runs, strict=True):
                item["usage_summary"] = usage_by_run[r.id].to_dict()
        _emit_json(payload)
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
    if with_usage:
        table.add_column("tokens", justify="right")
        table.add_column("cost ¢", justify="right")
    table.add_column("task", overflow="fold")
    for r in runs:
        row = [
            r.id,
            r.adapter,
            r.adapter_thread_id,
            r.status.value,
            r.started_at.isoformat(timespec="seconds"),
        ]
        if with_usage:
            summ = usage_by_run[r.id]
            row.append(summ.tokens_cell())
            row.append(summ.cost_cell())
        row.append(_truncate(r.task_description or "", 80))
        table.add_row(*row)
    console.print(table)


def runs_show_command(
    *,
    run_id: str,
    db: Path | None,
    json_out: bool,
    open_store_fn: Callable[[Path | None], SqliteStore],
    console: Console,
) -> None:
    """Show one run, including its node tree."""
    store = open_store_fn(db)
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
    total_usage = _sum_usage(nodes)
    if total_usage is not None:
        root.add(f"[bold]total usage:[/] {_fmt_usage_inline(total_usage)}")
    for n in nodes:
        label = (
            f"[{n.step_index}] [green]{n.node_name}[/] [dim]{n.kind.value}[/] [dim cyan]{n.id}[/]"
        )
        nnode = nlist.add(label)
        if n.parent_node_id:
            nnode.add(f"[dim]parent: {n.parent_node_id}[/]")
        if n.tool_name:
            nnode.add(f"tool: {n.tool_name}")
        if n.usage is not None:
            nnode.add(f"[yellow]usage:[/] {_fmt_node_usage(n)}")
        if n.error_message:
            nnode.add(f"[red]error: {_truncate(n.error_message, 120)}[/]")
    console.print(root)
