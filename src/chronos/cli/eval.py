"""Implementation for ``chronos eval run`` and ``chronos eval list`` (R115, ADR-030).

Mirrors the cli/runs.py pattern: this module owns the *_command functions; the
typer wrappers and argument shapes live in cli/__init__.py.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from chronos.cli._common import _emit_json
from chronos.eval import (
    get as get_evaluator,
)
from chronos.eval import (
    list_registered,
    load_entry_points,
    run_evaluator,
)
from chronos.store.sqlite import SqliteStore


def eval_run_command(
    *,
    run_id: str,
    evaluator: str,
    db: Path | None,
    json_out: bool,
    open_store_fn: Callable[[Path | None], SqliteStore],
    console: Console,
) -> None:
    """Run a registered evaluator against a recorded run, persist + print result.

    Exit codes:
      0 — happy path (evaluator ran, row stored, single-row table or JSON printed).
      1 — runtime "no such run" / "no such evaluator" — message includes hint
          (``chronos runs list`` or ``chronos eval list-evaluators``).
      2 — evaluator itself raised — its exception is printed verbatim and the
          DB is left untouched.
    """
    # Discover plugin-packaged evaluators so users can `pip install chronos-eval-foo`
    # and have its names show up here. Built-ins were registered at import time.
    load_entry_points()

    try:
        get_evaluator(evaluator)
    except KeyError as e:
        console.print(f"[red]error:[/] {e}")
        raise typer.Exit(code=1) from None

    store = open_store_fn(db)
    try:
        run = store.get_run(run_id)
        if run is None:
            console.print(f"[red]error:[/] no such run: [bold]{run_id}[/]")
            console.print("[dim]Hint:[/] list available runs with `chronos runs list`.")
            raise typer.Exit(code=1)
        nodes = store.get_nodes_for_run(run_id)
        try:
            evaluation = run_evaluator(evaluator, run, nodes)
        except Exception as exc:
            console.print(
                f"[red]error:[/] evaluator {evaluator!r} raised: "
                f"[yellow]{type(exc).__name__}[/]: {exc}"
            )
            raise typer.Exit(code=2) from None
        store.put_evaluation(evaluation)
        # Re-read so we surface the canonical id (UPSERT may have left the
        # original id in place).
        stored = store.get_evaluation_for_run_evaluator(run_id, evaluator)
        assert stored is not None
    finally:
        store.close()

    if json_out:
        _emit_json(stored.model_dump(mode="json"))
        return

    table = Table(
        title=f"Evaluation: {evaluator}",
        show_lines=False,
        header_style="bold cyan",
    )
    table.add_column("field", style="cyan", no_wrap=True)
    table.add_column("value")
    table.add_row("run_id", stored.run_id)
    table.add_row("evaluator", stored.evaluator_name)
    table.add_row("score", _fmt_score(stored.score))
    table.add_row("passed", _fmt_passed(stored.passed))
    table.add_row("rationale", stored.rationale or "—")
    table.add_row("created_at", stored.created_at.isoformat(timespec="seconds"))
    console.print(table)


def eval_list_command(
    *,
    run_id: str,
    db: Path | None,
    json_out: bool,
    open_store_fn: Callable[[Path | None], SqliteStore],
    console: Console,
) -> None:
    """List every evaluation recorded against ``run_id``."""
    store = open_store_fn(db)
    try:
        run = store.get_run(run_id)
        if run is None:
            console.print(f"[red]error:[/] no such run: [bold]{run_id}[/]")
            console.print("[dim]Hint:[/] list available runs with `chronos runs list`.")
            raise typer.Exit(code=1)
        evaluations = store.get_evaluations_for_run(run_id)
    finally:
        store.close()

    if json_out:
        _emit_json([e.model_dump(mode="json") for e in evaluations])
        return

    if not evaluations:
        console.print(f"[yellow]no evaluations recorded for run {run_id}[/]")
        console.print(
            "[dim]Hint:[/] register an evaluator and run "
            "`chronos eval run <run_id> --evaluator <name>`."
        )
        return

    table = Table(
        title=f"Evaluations for {run_id} ({len(evaluations)})",
        show_lines=False,
        header_style="bold cyan",
    )
    table.add_column("evaluator", style="cyan", no_wrap=True)
    table.add_column("score", justify="right")
    table.add_column("passed")
    table.add_column("rationale", overflow="fold")
    table.add_column("created_at")
    for ev in evaluations:
        table.add_row(
            ev.evaluator_name,
            _fmt_score(ev.score),
            _fmt_passed(ev.passed),
            ev.rationale or "",
            ev.created_at.isoformat(timespec="seconds"),
        )
    console.print(table)


def eval_list_evaluators_command(
    *,
    json_out: bool,
    console: Console,
) -> None:
    """Print every registered evaluator name (built-ins + plugins).

    Triggers entry-point discovery so plugin-packaged evaluators show up.
    """
    load_entry_points()
    names = list_registered()

    if json_out:
        _emit_json(names)
        return

    if not names:
        console.print("[yellow]no evaluators registered[/]")
        return

    table = Table(
        title=f"Registered evaluators ({len(names)})",
        show_lines=False,
        header_style="bold cyan",
    )
    table.add_column("name", style="cyan", no_wrap=True)
    for name in names:
        table.add_row(name)
    console.print(table)


# ---------------------------------------------------------------------------
# Helpers — score / passed cell rendering. Kept module-private so the
# ``compare --eval`` decorator can reuse them.
# ---------------------------------------------------------------------------


def _fmt_score(score: float | None) -> str:
    if score is None:
        return "—"
    # Integer-valued floats render without trailing ``.0`` for a tidier table
    # (output_length_chars almost always returns whole numbers).
    if score == int(score):
        return str(int(score))
    return f"{score:.4f}"


def _fmt_passed(passed: bool | None) -> str:
    if passed is None:
        return "—"
    return "[green]✓[/]" if passed else "[red]✗[/]"


def annotate_with_evaluation(
    *,
    run_ids: list[str],
    evaluator: str,
    db: Path | None,
    open_store_fn: Callable[[Path | None], SqliteStore],
    auto_run: bool = True,
) -> dict[str, dict[str, Any] | None]:
    """For each ``run_id``, return ``{evaluator, score, passed, rationale}``.

    Resolution order:
      1. Look up ``(run_id, evaluator_name)`` in the evaluations table.
      2. If absent and ``auto_run`` is true, invoke the evaluator and persist.
      3. If the evaluator is unknown OR the run is missing, the corresponding
         entry is ``None`` (sentinel — the caller decides how to render).

    Used by ``chronos compare --eval <name>`` to attach a score column.
    """
    load_entry_points()

    out: dict[str, dict[str, Any] | None] = {}
    try:
        get_evaluator(evaluator)
    except KeyError:
        # Don't error here — compare still works without scores. The CLI
        # wrapper is responsible for surfacing a hint.
        return dict.fromkeys(run_ids)

    store = open_store_fn(db)
    try:
        for run_id in run_ids:
            run = store.get_run(run_id)
            if run is None:
                out[run_id] = None
                continue
            existing = store.get_evaluation_for_run_evaluator(run_id, evaluator)
            if existing is None and auto_run:
                nodes = store.get_nodes_for_run(run_id)
                try:
                    evaluation = run_evaluator(evaluator, run, nodes)
                except Exception:
                    out[run_id] = None
                    continue
                store.put_evaluation(evaluation)
                existing = evaluation
            if existing is None:
                out[run_id] = None
            else:
                out[run_id] = {
                    "evaluator": existing.evaluator_name,
                    "score": existing.score,
                    "passed": existing.passed,
                    "rationale": existing.rationale,
                }
    finally:
        store.close()
    return out


__all__ = [
    "annotate_with_evaluation",
    "eval_list_command",
    "eval_list_evaluators_command",
    "eval_run_command",
]
