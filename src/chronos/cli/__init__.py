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
from dataclasses import dataclass
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


# ---------------------------------------------------------------------------
# Usage summaries (ADR-009)
# ---------------------------------------------------------------------------


@dataclass
class _RunUsageSummary:
    """Aggregated usage across a run's nodes for table rendering."""

    nodes_with_usage: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd_cents: int = 0
    any_cost: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens + self.reasoning_tokens

    def tokens_cell(self) -> str:
        if self.nodes_with_usage == 0:
            return "[dim]—[/]"
        return str(self.total_tokens)

    def cost_cell(self) -> str:
        if not self.any_cost:
            return "[dim]—[/]"
        return str(self.cost_usd_cents)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes_with_usage": self.nodes_with_usage,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd_cents": self.cost_usd_cents if self.any_cost else None,
        }


def _summarise_usage(nodes: list[Node]) -> _RunUsageSummary:
    summ = _RunUsageSummary()
    for n in nodes:
        if n.usage is None:
            continue
        summ.nodes_with_usage += 1
        summ.prompt_tokens += n.usage.prompt_tokens
        summ.completion_tokens += n.usage.completion_tokens
        summ.reasoning_tokens += n.usage.reasoning_tokens
        if n.cost_usd_cents is not None:
            summ.any_cost = True
            summ.cost_usd_cents += n.cost_usd_cents
    return summ


def _sum_usage(nodes: list[Node]) -> _RunUsageSummary | None:
    summ = _summarise_usage(nodes)
    return summ if summ.nodes_with_usage > 0 else None


def _fmt_usage_inline(summ: _RunUsageSummary) -> str:
    parts = [
        f"{summ.prompt_tokens} prompt",
        f"{summ.completion_tokens} completion",
    ]
    if summ.reasoning_tokens:
        parts.append(f"{summ.reasoning_tokens} reasoning")
    parts.append(f"= [bold]{summ.total_tokens}[/] tokens")
    if summ.any_cost:
        parts.append(f"[bold]{summ.cost_usd_cents}¢[/]")
    parts.append(f"across {summ.nodes_with_usage} node(s)")
    return ", ".join(parts)


def _fmt_node_usage(node: Node) -> str:
    assert node.usage is not None
    u = node.usage
    parts = [f"{u.prompt_tokens}+{u.completion_tokens}"]
    if u.reasoning_tokens:
        parts.append(f"(+{u.reasoning_tokens} reasoning)")
    parts.append(f"= {u.prompt_tokens + u.completion_tokens + u.reasoning_tokens} tokens")
    if node.cost_usd_cents is not None:
        parts.append(f"{node.cost_usd_cents}¢")
    if node.model_name:
        parts.append(f"[dim]{node.model_name}[/]")
    return " ".join(parts)


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
        "usage": (
            {
                "prompt_tokens": node.usage.prompt_tokens,
                "completion_tokens": node.usage.completion_tokens,
                "reasoning_tokens": node.usage.reasoning_tokens,
            }
            if node.usage is not None
            else None
        ),
        "cost_usd_cents": node.cost_usd_cents,
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
    with_usage: bool = typer.Option(
        False,
        "--with-usage",
        help="Include summed tokens / cost columns. Extra SELECT per run — slower for large DBs.",
    ),
) -> None:
    """List recorded runs (most recent first)."""
    store = _open_store(db)
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
        payload = [_run_to_dict(r) for r in runs]
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


def _render_usage_compare(
    usage_a: _RunUsageSummary | None, usage_b: _RunUsageSummary | None
) -> None:
    """Render a side-by-side token/cost comparison for `diff --show-usage`."""
    if (usage_a is None or usage_a.nodes_with_usage == 0) and (
        usage_b is None or usage_b.nodes_with_usage == 0
    ):
        console.print("[dim]usage: no usage recorded on either side.[/]")
        return

    t = Table(title="Usage comparison (A vs B)", header_style="bold cyan")
    t.add_column("metric")
    t.add_column("A", justify="right")
    t.add_column("B", justify="right")
    t.add_column("Δ (B − A)", justify="right")  # noqa: RUF001

    def _cell(v: int) -> str:
        return str(v)

    def _delta(a: int, b: int) -> str:
        d = b - a
        if d == 0:
            return "[dim]0[/]"
        colour = "green" if d < 0 else "red"
        sign = "+" if d > 0 else ""
        return f"[{colour}]{sign}{d}[/]"

    a = usage_a or _RunUsageSummary()
    b = usage_b or _RunUsageSummary()

    t.add_row(
        "prompt",
        _cell(a.prompt_tokens),
        _cell(b.prompt_tokens),
        _delta(a.prompt_tokens, b.prompt_tokens),
    )
    t.add_row(
        "completion",
        _cell(a.completion_tokens),
        _cell(b.completion_tokens),
        _delta(a.completion_tokens, b.completion_tokens),
    )
    if a.reasoning_tokens or b.reasoning_tokens:
        t.add_row(
            "reasoning",
            _cell(a.reasoning_tokens),
            _cell(b.reasoning_tokens),
            _delta(a.reasoning_tokens, b.reasoning_tokens),
        )
    t.add_row(
        "[bold]total tokens[/]",
        f"[bold]{a.total_tokens}[/]",
        f"[bold]{b.total_tokens}[/]",
        _delta(a.total_tokens, b.total_tokens),
    )
    if a.any_cost or b.any_cost:
        t.add_row(
            "[bold]cost ¢[/]",
            f"[bold]{a.cost_usd_cents if a.any_cost else '—'}[/]",
            f"[bold]{b.cost_usd_cents if b.any_cost else '—'}[/]",
            _delta(a.cost_usd_cents, b.cost_usd_cents),
        )
    t.add_row(
        "nodes w/ usage",
        _cell(a.nodes_with_usage),
        _cell(b.nodes_with_usage),
        _delta(a.nodes_with_usage, b.nodes_with_usage),
    )
    console.print(t)


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
    store = _open_store(db)
    try:
        try:
            report = diff_runs(store, run_a, run_b, restrict_to_downstream=not full)
        except DiffRunNotFoundError as exc:
            console.print(f"[red]error:[/] no such run: [bold]{exc.run_id}[/]")
            raise typer.Exit(code=1) from exc
        usage_a: _RunUsageSummary | None = None
        usage_b: _RunUsageSummary | None = None
        if show_usage:
            usage_a = _summarise_usage(store.get_nodes_for_run(run_a))
            usage_b = _summarise_usage(store.get_nodes_for_run(run_b))
    finally:
        store.close()

    if json_out:
        payload = report.to_dict()
        if show_usage:
            payload["usage"] = {
                "a": usage_a.to_dict() if usage_a else None,
                "b": usage_b.to_dict() if usage_b else None,
                "delta_tokens": (
                    (usage_b.total_tokens if usage_b else 0)
                    - (usage_a.total_tokens if usage_a else 0)
                ),
            }
        _emit_json(payload)
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
    if show_usage:
        _render_usage_compare(usage_a, usage_b)


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
