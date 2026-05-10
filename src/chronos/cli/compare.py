"""Implementation for ``chronos compare`` — N-run pivot-anchored diff.

R59 — Phase 4 Arc A slice 2. Wraps :func:`chronos.core.diff.merge_pivot_reports`
(R58 pure core) with a text/JSON renderer. See
``docs/design/n-run-compare.md`` §3.1 and §6 for the UX spec.

Layout:

* ``pivot_run_id`` is the first positional. All others align against it.
* For each other, we build a ``DiffReport`` via ``diff_runs`` (ADR-006
  alignment), then fold them with ``merge_pivot_reports``.
* ``--format json`` emits the exact ``MergedPivotAlignment.to_dict()``
  shape — the CLI *locks* the JSON contract (design doc §3.3).
* ``--format text`` (default) renders a ``rich.table.Table`` with
  per-column tags.

N=2 is numerically identical to ``chronos diff`` summary (R58 regression
guard, tests in ``test_merge_pivot.py``). We do **not** alias
``chronos diff`` → ``chronos compare`` in R59 (OQ-1 deferred to ADR-025).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from chronos.cli._common import _emit_json
from chronos.core.auto_pivot import AutoPivotReport, auto_pivot_compare
from chronos.core.diff import (
    DiffRunNotFoundError,
    MergedPivotAlignment,
    diff_runs,
    merge_pivot_reports,
)
from chronos.store.sqlite import SqliteStore

# Column filter literal (matches design doc §3.1 `--columns` flag).
_COLUMNS_CHOICES = ("all", "changed", "changed-or-added")

# Text-mode colour mapping (design doc §6.3). Keep in sync with
# ``_TAG_STYLE`` / ``_TAG_SYMBOL`` in ``cli/diff.py`` — we add
# ``absent`` (dim, no-op cell) which the 2-run diff doesn't need.
_TAG_STYLE = {
    "equal": "dim",
    "changed": "yellow",
    "added": "green",
    "removed": "red",
    "absent": "dim",
}
_TAG_SYMBOL = {
    "equal": "=",
    "changed": "≠",  # intentional Unicode in user-facing cell
    "added": "+",
    "removed": "−",  # noqa: RUF001  — U+2212 minus per design doc §6.3
    "absent": " ",
}

# Soft warning when N > 8 (design doc §3.1 "No positional upper limit at
# parse time; a soft warning prints at N > 8"). 8 is chosen to line up
# with typical terminal widths at N+1 = 9 columns.
_SOFT_N_WARN = 8


def _row_has_divergence(per_run: dict[str, dict[str, object]]) -> bool:
    """True if any cell is not ``equal`` or ``absent``."""
    return any(cell.get("tag") not in ("equal", "absent") for cell in per_run.values())


def _row_has_change_or_add(per_run: dict[str, dict[str, object]]) -> bool:
    """True if any cell is ``changed`` or ``added`` (or ``removed``)."""
    return any(cell.get("tag") in ("changed", "added", "removed") for cell in per_run.values())


def _render_cell(cell: dict[str, object]) -> str:
    tag = str(cell.get("tag", "absent"))
    style = _TAG_STYLE.get(tag, "dim")
    sym = _TAG_SYMBOL.get(tag, "?")
    return f"[{style}]{sym} {tag}[/]"


def _render_merged_table(
    merged: MergedPivotAlignment,
    *,
    columns_mode: str,
    show_equal: bool,
    width: int | None,
) -> Table:
    title_parts = [f"Compare pivot={merged.pivot_run_id} vs {len(merged.other_run_ids)} other(s)"]
    table = Table(
        title=" ".join(title_parts),
        show_lines=False,
        header_style="bold cyan",
        width=width,
    )
    table.add_column("step", no_wrap=True, width=5)
    table.add_column("node", overflow="fold")
    for oid in merged.other_run_ids:
        table.add_column(oid, overflow="fold")

    for row in merged.alignment:
        per_run = row["per_run"]
        # Filter by columns_mode (design doc §3.1).
        if columns_mode == "changed" and not any(
            cell.get("tag") == "changed" for cell in per_run.values()
        ):
            continue
        if columns_mode == "changed-or-added" and not _row_has_change_or_add(per_run):
            continue
        # --show-equal default off: skip rows that are all-equal/absent when
        # columns_mode == "all".
        if columns_mode == "all" and not show_equal and not _row_has_divergence(per_run):
            continue

        pivot_step = row.get("pivot_step")
        pivot_node_name = row.get("pivot_node_name")
        if pivot_step is None:
            # Insert row — pivot columns are empty; surface anchor hint.
            anchor = row.get("inserted_after_pivot_step")
            step_cell = "[green]+[/]"
            anchor_str = "before pivot" if anchor == -1 else f"after pivot step {anchor}"
            inserted_name = row.get("inserted_node_name", "?")
            node_cell = f"[green]+ {inserted_name}[/] [dim]({anchor_str})[/]"
        else:
            step_cell = str(pivot_step)
            node_cell = str(pivot_node_name or "—")

        cells = [_render_cell(per_run[oid]) for oid in merged.other_run_ids]
        table.add_row(step_cell, node_cell, *cells)
    return table


def _render_summary(merged: MergedPivotAlignment, console: Console) -> None:
    """Pretty-print per-other summary counts. Mirrors `DiffReport.summary`."""
    t = Table(title="Summary (per other)", header_style="bold cyan", show_lines=False)
    t.add_column("run")
    t.add_column("equal", justify="right")
    t.add_column("changed", justify="right")
    t.add_column("added", justify="right")
    t.add_column("removed", justify="right")
    for oid in merged.other_run_ids:
        s = merged.summary.get(oid, {"equal": 0, "changed": 0, "added": 0, "removed": 0})
        t.add_row(
            oid,
            f"[dim]{s['equal']}[/]",
            f"[yellow]{s['changed']}[/]",
            f"[green]{s['added']}[/]",
            f"[red]{s['removed']}[/]",
        )
    console.print(t)


def _render_distance_matrix(
    report: AutoPivotReport,
    console: Console,
    *,
    full: bool,
) -> None:
    """Pretty-print the pairwise distance matrix (design: ADR-024 §Interface).

    Default shows the first 3 rows; ``full=True`` (``--show-matrix``) renders
    every pair. Each row is ``(run_a, run_b, distance)`` with canonical
    ``min_id < max_id`` orientation — same as ``AutoPivotReport.distance_matrix``.
    """
    pairs = sorted(report.distance_matrix.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    total_pairs = len(pairs)
    truncated = not full and total_pairs > 3
    if truncated:
        pairs = pairs[:3]
    title = f"Pairwise distance matrix (metric v{report.metric_version})"
    t = Table(title=title, header_style="bold cyan", show_lines=False)
    t.add_column("run_a")
    t.add_column("run_b")
    t.add_column("distance", justify="right")
    for (a, b), d in pairs:
        t.add_row(a, b, f"{d:.4f}")
    console.print(t)
    # Emit the truncation hint on its own line so it is not subject to
    # rich Table title width truncation at narrow terminals (R63 test
    # regression: default `CliRunner()` terminal defaulted to ~80 cols
    # and swallowed the suffix when it lived in the Table title).
    if truncated:
        console.print(f"[dim](showing 3 of {total_pairs} pairs — pass --show-matrix for full)[/]")


def compare_command(
    *,
    pivot_run_id: str,
    other_run_ids: list[str],
    db: Path | None,
    json_out: bool,
    restrict_to_downstream: bool,
    columns: str,
    show_equal: bool,
    width: int | None,
    open_store_fn: Callable[[Path | None], SqliteStore],
    console: Console,
    auto_pivot: bool = False,
    show_matrix: bool = False,
) -> None:
    """N-run pivot-anchored compare (ADR-023 Arc A, design doc §3.1).

    Wraps ``merge_pivot_reports`` with text/JSON rendering. The CLI
    *locks* the JSON contract so later API wrappers can't drift.

    When ``auto_pivot=True`` (CLI ``--auto-pivot`` flag, Arc A slice 4,
    ADR-024), the positionals are treated as **candidates** rather than
    ``<pivot> <other...>``: the centroid is computed from pairwise
    structural distance (metric v1) and the merge is delegated to
    ``auto_pivot_compare``. JSON mode emits the full
    :class:`AutoPivotReport.to_dict()` shape (a **superset** of the
    pivot-anchored JSON — the ``merged`` sub-object is byte-for-byte
    identical to the R58/R59 contract).
    """
    if columns not in _COLUMNS_CHOICES:
        console.print(
            f"[red]error:[/] --columns must be one of {_COLUMNS_CHOICES}; got {columns!r}"
        )
        raise typer.Exit(code=2)

    if auto_pivot:
        _run_auto_pivot(
            pivot_run_id=pivot_run_id,
            other_run_ids=other_run_ids,
            db=db,
            json_out=json_out,
            restrict_to_downstream=restrict_to_downstream,
            columns=columns,
            show_equal=show_equal,
            width=width,
            show_matrix=show_matrix,
            open_store_fn=open_store_fn,
            console=console,
        )
        return

    # Input validation: positional count + dedup. Both are also enforced
    # in `merge_pivot_reports`, but we prefer friendly CLI-level errors.
    if len(other_run_ids) == 0:
        console.print(
            "[red]error:[/] need at least 2 runs: `chronos compare <pivot> <other> [<other> ...]`"
        )
        raise typer.Exit(code=2)
    seen: set[str] = set()
    for oid in other_run_ids:
        if oid == pivot_run_id:
            console.print(f"[red]error:[/] run id {oid!r} appears as both pivot and other")
            raise typer.Exit(code=2)
        if oid in seen:
            console.print(f"[red]error:[/] duplicate run id: {oid!r}")
            raise typer.Exit(code=2)
        seen.add(oid)

    store = open_store_fn(db)
    try:
        reports = []
        for oid in other_run_ids:
            try:
                reports.append(
                    diff_runs(
                        store,
                        pivot_run_id,
                        oid,
                        restrict_to_downstream=restrict_to_downstream,
                    )
                )
            except DiffRunNotFoundError as exc:
                console.print(f"[red]error:[/] no such run: [bold]{exc.run_id}[/]")
                raise typer.Exit(code=1) from exc
    finally:
        store.close()

    merged = merge_pivot_reports(pivot_run_id, other_run_ids, reports)

    # Soft warning for large N (design doc §3.1, §7.1 last row).
    if len(other_run_ids) > _SOFT_N_WARN:
        merged.warnings.append(
            f"N={len(other_run_ids) + 1} is large; table may not fit in a typical terminal."
        )

    if json_out:
        _emit_json(merged.to_dict())
        return

    # Text mode ---------------------------------------------------------
    console.print(
        f"[bold]Pivot:[/] {merged.pivot_run_id}  [dim]({len(merged.other_run_ids)} other run(s))[/]"
    )
    for w in merged.warnings:
        console.print(f"[magenta]⚠ {w}[/]")

    console.print(
        _render_merged_table(
            merged,
            columns_mode=columns,
            show_equal=show_equal,
            width=width,
        )
    )
    _render_summary(merged, console)


def _run_auto_pivot(
    *,
    pivot_run_id: str,
    other_run_ids: list[str],
    db: Path | None,
    json_out: bool,
    restrict_to_downstream: bool,
    columns: str,
    show_equal: bool,
    width: int | None,
    show_matrix: bool,
    open_store_fn: Callable[[Path | None], SqliteStore],
    console: Console,
) -> None:
    """Auto-pivot branch of ``chronos compare --auto-pivot`` (Arc A slice 4).

    In this mode the first positional is **not** the designated pivot — it
    is simply the first candidate. We combine ``[pivot_run_id] + other_run_ids``
    into a single candidate list, then delegate to
    :func:`chronos.core.auto_pivot.auto_pivot_compare`. The centroid emerges
    from the data (ADR-024 §Decision).
    """
    candidates = [pivot_run_id, *other_run_ids]

    # Need ≥ 2 candidates (pivot + at least one other).
    if len(candidates) < 2:
        console.print(
            "[red]error:[/] --auto-pivot needs at least 2 run ids: "
            "`chronos compare --auto-pivot <id> <id> [<id> ...]`"
        )
        raise typer.Exit(code=2)

    # Dedup: any repetition is a user error regardless of position.
    seen: set[str] = set()
    for rid in candidates:
        if rid in seen:
            console.print(f"[red]error:[/] duplicate run id: {rid!r}")
            raise typer.Exit(code=2)
        seen.add(rid)

    store = open_store_fn(db)
    try:
        try:
            report = auto_pivot_compare(
                candidates,
                store,
                restrict_to_downstream=restrict_to_downstream,
            )
        except DiffRunNotFoundError as exc:
            console.print(f"[red]error:[/] no such run: [bold]{exc.run_id}[/]")
            raise typer.Exit(code=1) from exc
    finally:
        store.close()

    # Soft warning for large N (mirrors design doc §3.1, §7.1; source of
    # truth is the CLI because core's auto_pivot_compare is metric-only).
    if len(candidates) > _SOFT_N_WARN + 1:
        report.merged.warnings.append(
            f"N={len(candidates)} is large; table may not fit in a typical terminal."
        )

    if json_out:
        _emit_json(report.to_dict())
        return

    # Text mode ---------------------------------------------------------
    console.print(
        f"[bold]Auto-pivot:[/] centroid = [cyan]{report.centroid_run_id}[/]  "
        f"[dim](selected from {len(candidates)} candidates, metric v{report.metric_version})[/]"
    )
    for w in report.merged.warnings:
        console.print(f"[magenta]⚠ {w}[/]")

    _render_distance_matrix(report, console, full=show_matrix)

    console.print(
        _render_merged_table(
            report.merged,
            columns_mode=columns,
            show_equal=show_equal,
            width=width,
        )
    )
    _render_summary(report.merged, console)
