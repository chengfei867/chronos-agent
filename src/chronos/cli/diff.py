"""Implementation for ``chronos diff`` (structural run diff with usage compare).

Extracted from ``chronos.cli.__init__`` in R14. Delta computation itself lives
in :mod:`chronos.core.diff`; this module only renders the result.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from chronos.cli._common import _emit_json, _truncate
from chronos.cli._usage import _RunUsageSummary, _summarise_usage
from chronos.core.diff import DiffReport, DiffRunNotFoundError, diff_runs
from chronos.store.sqlite import SqliteStore

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
    usage_a: _RunUsageSummary | None,
    usage_b: _RunUsageSummary | None,
    *,
    console: Console,
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


def diff_command(
    *,
    run_a: str,
    run_b: str,
    db: Path | None,
    json_out: bool,
    verbose: bool,
    full: bool,
    show_usage: bool,
    open_store_fn: Callable[[Path | None], SqliteStore],
    console: Console,
) -> None:
    """Structural diff of two recorded runs (ADR-006 alignment)."""
    store = open_store_fn(db)
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
        _render_usage_compare(usage_a, usage_b, console=console)
