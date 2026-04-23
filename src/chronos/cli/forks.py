"""Implementation for ``chronos forks show``.

Extracted from ``chronos.cli.__init__`` in R14 to match the
implementation-module pattern (see :mod:`chronos.cli.replay` and
:mod:`chronos.cli.fork`).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer
from rich.console import Console
from rich.tree import Tree

from chronos.cli._common import (
    _emit_json,
    _fork_to_dict,
    _node_to_dict,
    _run_to_dict,
    _truncate,
)
from chronos.store.sqlite import SqliteStore


def forks_show_command(
    *,
    fork_id: str,
    db: Path | None,
    json_out: bool,
    open_store_fn: Callable[[Path | None], SqliteStore],
    console: Console,
) -> None:
    """Show a fork: parent run + fork point + overrides + child run summary."""
    store = open_store_fn(db)
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
