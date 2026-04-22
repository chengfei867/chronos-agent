"""Spike 6 — CLI read-side rendering spike.

Probe:
1. Can we populate a SqliteStore with a tiny fixture and re-read it cleanly?
2. Does `rich.table.Table` render okay under Typer's CliRunner (captured stdout)?
3. Does `rich.tree.Tree` print the node hierarchy the way we want?
4. Does mixing `--json` mode (plain stdout) vs rich mode require care? (it does: Rich
   auto-detects non-tty; we must pass a Console() so `--json` uses `print()` or a
   plain console.)

Run:
    uv run python tests/spikes/spike6_cli_readside.py
(Not a pytest — it's a dump-style spike like spike4/spike5.)
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from chronos.core.models import Fork, Node, NodeKind, Run, RunStatus
from chronos.store.sqlite import SqliteStore


def seed(store: SqliteStore) -> tuple[str, str, str]:
    """Create 1 run with 3 nodes + 1 fork + 1 child run with 1 node."""
    parent_id = "run-parent-01"
    child_id = "run-child-01"
    t0 = datetime(2026, 4, 23, 4, 0, 0, tzinfo=UTC)

    parent = Run(
        id=parent_id,
        adapter="langgraph",
        adapter_thread_id="t1",
        status=RunStatus.COMPLETED,
        started_at=t0,
        ended_at=t0,
        task_description="write a haiku about time",
        initial_state={"task": "haiku"},
        final_state={"final": "tick tock..."},
        tags=["spike"],
        metadata={"demo": True},
    )
    store.put_run(parent)
    n_ids = []
    for i, name in enumerate(("plan", "draft", "polish")):
        nid = f"node-parent-{i}"
        n_ids.append(nid)
        store.put_node(
            Node(
                id=nid,
                run_id=parent_id,
                step_index=i,
                node_name=name,
                kind=NodeKind.FN,
                parent_node_id=(n_ids[i - 1] if i > 0 else None),
                started_at=t0,
                ended_at=t0,
                state_after={"step": name, "i": i},
                metadata={},
            )
        )

    child = Run(
        id=child_id,
        adapter="langgraph",
        adapter_thread_id="t1-fork",
        status=RunStatus.COMPLETED,
        started_at=t0,
        ended_at=t0,
        task_description="fork of haiku — try alt draft",
        initial_state={"task": "haiku"},
        final_state={"final": "FORKED tick tock..."},
        tags=["fork"],
        metadata={"forked_from_run": parent_id, "forked_at_node": n_ids[1]},
    )
    store.put_run(child)
    child_node_id = "node-child-0"
    store.put_node(
        Node(
            id=child_node_id,
            run_id=child_id,
            step_index=2,  # continued after draft
            node_name="polish",
            kind=NodeKind.FN,
            parent_node_id=n_ids[1],  # cross-run lineage pointer
            started_at=t0,
            ended_at=t0,
            state_after={"step": "polish", "forked": True},
            metadata={},
        )
    )

    fork_id = "fork-01"
    store.put_fork(
        Fork(
            id=fork_id,
            parent_run_id=parent_id,
            parent_node_id=n_ids[1],
            child_run_id=child_id,
            created_at=t0,
            edited_fields={"draft": "[FORKED] alternative draft"},
            reason="spike6 try alt draft",
        )
    )
    return parent_id, child_id, fork_id


def render_runs_table(console: Console, runs: list[Run]) -> None:
    table = Table(title="Runs", show_lines=False)
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
            r.task_description or "",
        )
    console.print(table)


def render_run_tree(console: Console, run: Run, nodes: list[Node]) -> None:
    root = Tree(
        f"[bold cyan]{run.id}[/] [dim]({run.adapter}/{run.adapter_thread_id})[/] "
        f"[yellow]{run.status.value}[/]"
    )
    root.add(f"task: {run.task_description or '-'}")
    nlist = root.add(f"nodes ({len(nodes)})")
    for n in nodes:
        nlist.add(f"[{n.step_index}] [green]{n.node_name}[/] [dim]{n.kind.value} {n.id}[/]")
    console.print(root)


def render_fork(console: Console, fork: Fork, parent: Run, child: Run) -> None:
    t = Tree(f"[bold magenta]Fork[/] {fork.id}")
    t.add(f"parent run: {parent.id} @ node {fork.parent_node_id}")
    t.add(f"child  run: {child.id}")
    edits = t.add(f"edited_fields ({len(fork.edited_fields)})")
    for k, v in fork.edited_fields.items():
        v_repr = repr(v)
        if len(v_repr) > 60:
            v_repr = v_repr[:57] + "..."
        edits.add(f"[yellow]{k}[/] = {v_repr}")
    t.add(f"reason: {fork.reason or '-'}")
    console.print(t)


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "c.db"
        store = SqliteStore.open(db)
        parent_id, child_id, fork_id = seed(store)

        console = Console()
        print("\n=== runs table ===")
        render_runs_table(console, store.list_runs())

        print("\n=== parent tree ===")
        parent = store.get_run(parent_id)
        assert parent
        render_run_tree(console, parent, store.get_nodes_for_run(parent_id))

        print("\n=== child tree ===")
        child = store.get_run(child_id)
        assert child
        render_run_tree(console, child, store.get_nodes_for_run(child_id))

        print("\n=== fork view ===")
        fork = store.get_fork(fork_id)
        assert fork
        render_fork(console, fork, parent, child)

        print("\n=== JSON mode probe ===")
        runs_json = [
            {
                "id": r.id,
                "adapter": r.adapter,
                "status": r.status.value,
                "started_at": r.started_at.isoformat(),
            }
            for r in store.list_runs()
        ]
        print(json.dumps(runs_json, indent=2))
        store.close()


if __name__ == "__main__":
    main()
