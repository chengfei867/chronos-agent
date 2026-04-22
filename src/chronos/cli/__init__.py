"""Chronos CLI entry point (minimal skeleton — commands added in M1.5+)."""

from __future__ import annotations

import typer
from rich.console import Console

from chronos import __version__

app = typer.Typer(
    name="chronos",
    help="Time-travel debugger for multi-agent AI systems.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


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
    console.print("Status: pre-alpha (Phase 1 M1.2 — project skeleton)")
    console.print(
        "Commands: [dim]record, list, inspect, diff, fork[/dim] [yellow](not yet implemented)[/yellow]"
    )


if __name__ == "__main__":
    app()
