"""Implementation for ``chronos tree`` — fork-family tree viewer CLI.

Added in R67 (Arc A item 2 CLI closeout per ADR-025). Sibling to the HTTP
surface at ``GET /runs/{run_id}/tree?include_descendants=<bool>``; both
delegate to the pure assemblers in :mod:`chronos.core.tree` and emit the
same v0.6.0-frozen shape.

Two modes:

* **Text (default)** — rich-rendered indented tree.
  * Without ``--descendants``: single run, its nodes by ``parent_node_id`` chain.
  * With ``--descendants``: one sub-tree per descendant run, fork-reasons inline.
* **JSON** (``--json``): byte-for-byte the HTTP response shape, via
  stdlib ``print(json.dumps(...))`` (project invariant — no rich.Console
  for JSON).

Exit codes: 0 ok, 1 missing run, 2 bad args (Typer handles the latter).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.tree import Tree

from chronos.core.tree import assemble_tree, assemble_tree_with_descendants
from chronos.store.sqlite import SqliteStore


def _short(s: str, n: int = 8) -> str:
    """First n chars of an id for display. Full id still in JSON mode."""
    return s[:n] if len(s) > n else s


def _node_label(node: dict[str, Any]) -> str:
    """Render a single node dict as a one-line rich-markup label."""
    step = node.get("step_index", "?")
    name = node.get("node_name", "?")
    kind = node.get("kind", "?")
    nid = node.get("id", "")
    return f"[{step}] [green]{name}[/] [dim]{kind}[/] [dim cyan]{_short(nid)}[/]"


def _build_run_subtree(
    run_id: str,
    tree_payload: dict[str, Any],
    parent_rich: Tree,
    *,
    include_forks: bool,
) -> None:
    """Attach a run's node chain under ``parent_rich``.

    Uses ``edges`` with kind=sequential to reconstruct parent→child links
    within a run. If ``include_forks``, also attaches fork-reason hints
    after the fork-point node (they expand into their own sub-trees
    separately in the caller).
    """
    nodes_for_run = [n for n in tree_payload["nodes"] if n.get("run_id") == run_id]
    nodes_by_id = {n["id"]: n for n in nodes_for_run}

    # Parent within this run: None → root; else a node id.
    children_of: dict[str | None, list[dict[str, Any]]] = {}
    for n in nodes_for_run:
        children_of.setdefault(n.get("parent_node_id"), []).append(n)
    for lst in children_of.values():
        lst.sort(key=lambda n: n.get("step_index", 0))

    # Forks originating at a given parent_node_id (for inline annotation)
    forks_at_node: dict[str, list[dict[str, Any]]] = {}
    if include_forks:
        for fk in tree_payload.get("child_runs", []):
            if fk.get("parent_run_id") == run_id:
                forks_at_node.setdefault(fk["parent_node_id"], []).append(fk)

    # DFS over within-run tree starting from None-parent roots
    def _recurse(rich_parent: Tree, parent_node_id: str | None) -> None:
        for n in children_of.get(parent_node_id, []):
            label = _node_label(n)
            node_rich = rich_parent.add(label)
            # Inline fork hint for this node (only shown in descendants mode)
            for fk in forks_at_node.get(n["id"], []):
                reason = fk.get("reason") or "(no reason)"
                child_short = _short(fk.get("child_run_id", ""))
                node_rich.add(f"[magenta]⮡ fork[/] [yellow]{reason}[/] [dim]→ run {child_short}[/]")
            _recurse(node_rich, n["id"])

    if not nodes_for_run:
        parent_rich.add("[dim](no nodes recorded)[/]")
        return

    _recurse(parent_rich, None)
    # Pick up any nodes whose parent_node_id references a node that exists
    # but wasn't yielded via the None-root path (shouldn't happen under
    # sequential schema but be defensive).
    reachable: set[str] = set()

    def _mark(pid: str | None) -> None:
        for n in children_of.get(pid, []):
            if n["id"] not in reachable:
                reachable.add(n["id"])
                _mark(n["id"])

    _mark(None)
    orphans = [n for n in nodes_for_run if n["id"] not in reachable]
    if orphans:
        orph_rich = parent_rich.add("[dim](orphan nodes — parent not reachable)[/]")
        for n in orphans:
            orph_rich.add(_node_label(n))
    # make unused-param Ruff happy if nodes_by_id wasn't referenced
    _ = nodes_by_id


def _render_text(
    payload: dict[str, Any],
    *,
    descendants: bool,
    console: Console,
) -> None:
    """Render the tree payload as a rich indented tree to ``console``."""
    if not descendants:
        # Single-run mode: payload has no descendant_run_ids / run_summaries.
        root_run_id = payload["run_id"]
        header = (
            f"Run [bold cyan]{_short(root_run_id)}[/] "
            f"[dim]({root_run_id})[/] "
            f"[dim]· {len(payload['nodes'])} nodes, "
            f"{len(payload.get('child_runs', []))} forks out[/]"
        )
        tree = Tree(header)
        _build_run_subtree(root_run_id, payload, tree, include_forks=False)
        # Fork summary footer for single-run (no recursion)
        for fk in payload.get("child_runs", []):
            reason = fk.get("reason") or "(no reason)"
            tree.add(
                f"[magenta]⮡ fork[/] [yellow]{reason}[/] "
                f"[dim]at node {_short(fk['parent_node_id'])} "
                f"→ run {_short(fk['child_run_id'])}[/]"
            )
        console.print(tree)
        return

    # --- Descendants mode: one sub-tree per descendant run -----------------
    descendant_ids: list[str] = payload.get("descendant_run_ids") or [payload["run_id"]]
    run_summaries: dict[str, dict[str, Any]] = payload.get("run_summaries") or {}

    root_id = payload["run_id"]
    header = (
        f"Fork family rooted at [bold cyan]{_short(root_id)}[/] "
        f"[dim]· {len(descendant_ids)} run(s), "
        f"{len(payload['nodes'])} node(s), "
        f"{len(payload.get('child_runs', []))} fork(s)[/]"
    )
    tree = Tree(header)

    # Build parent-of-run map from child_runs so we can nest runs under
    # their parent run visually (not strictly necessary — a flat list of
    # lanes is also legal — but nesting is more readable).
    parent_of_run: dict[str, str | None] = {root_id: None}
    fork_meta_for_child: dict[str, dict[str, Any]] = {}
    for fk in payload.get("child_runs", []):
        parent_of_run[fk["child_run_id"]] = fk["parent_run_id"]
        fork_meta_for_child[fk["child_run_id"]] = fk

    # Attach each descendant run under its parent run (topological via BFS
    # order of descendant_ids, which matches ordering from assembler).
    rich_by_run: dict[str, Tree] = {}
    for rid in descendant_ids:
        summary = run_summaries.get(rid, {})
        adapter = summary.get("adapter", "?")
        status = summary.get("status", "?")
        task_desc = summary.get("task_description") or "(no task)"
        # Truncate long task descriptions for display
        if len(task_desc) > 60:
            task_desc = task_desc[:57] + "..."
        lane_label = (
            f"Run [bold cyan]{_short(rid)}[/] "
            f"[dim]({rid})[/] "
            f"[yellow]{status}[/] [dim]· {adapter}[/]"
        )
        fk_meta = fork_meta_for_child.get(rid)
        if fk_meta:
            reason = fk_meta.get("reason") or "(no reason)"
            lane_label += (
                f"\n  [magenta]forked from[/] "
                f"{_short(fk_meta['parent_run_id'])} at "
                f"{_short(fk_meta['parent_node_id'])} "
                f"[dim]· reason:[/] [yellow]{reason}[/]"
            )
        lane_label += f"\n  [dim]task:[/] {task_desc}"

        parent_rid = parent_of_run.get(rid)
        attach_to = rich_by_run.get(parent_rid, tree) if parent_rid is not None else tree
        lane_rich = attach_to.add(lane_label)
        rich_by_run[rid] = lane_rich
        _build_run_subtree(rid, payload, lane_rich, include_forks=True)

    console.print(tree)


def tree_command(
    *,
    run_id: str,
    db: Path | None,
    descendants: bool,
    json_out: bool,
    open_store_fn: Callable[[Path | None], SqliteStore],
    console: Console,
) -> None:
    """Show the fork-family tree rooted at ``run_id``.

    See ADR-025 §Interface for the frozen contract.
    """
    store = open_store_fn(db)
    try:
        run = store.get_run(run_id)
        if run is None:
            # Mirror HTTP 404. JSON mode uses stderr + exit 1.
            if json_out:
                print(
                    json.dumps({"error": f"no such run: {run_id}"}),
                    file=sys.stderr,
                )
            else:
                console.print(f"[red]error:[/] no such run: [bold]{run_id}[/]")
            raise typer.Exit(code=1)

        if descendants:
            payload = assemble_tree_with_descendants(store, run_id)
        else:
            nodes = store.get_nodes_for_run(run_id)
            forks = store.get_forks_for_parent(run_id)
            payload = assemble_tree(store, run_id, nodes, forks)
    finally:
        store.close()

    if json_out:
        # stdlib JSON only — no rich.Console for machine-readable output.
        # Byte-for-byte the HTTP response shape, so dogfood scripts can
        # pipe CLI and HTTP through the same schema assertion.
        print(json.dumps(payload))
        return

    _render_text(payload, descendants=descendants, console=console)
