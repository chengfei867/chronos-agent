"""Smoke tests for CLI entry point."""

from __future__ import annotations

from typer.testing import CliRunner

from chronos.cli import app

runner = CliRunner()


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "chronos" in result.stdout


def test_cli_info() -> None:
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    assert "pre-alpha" in result.stdout.lower()


def test_cli_help_default() -> None:
    result = runner.invoke(app, [])
    # no_args_is_help → typer prints help and exits with code 2 (click convention)
    assert result.exit_code == 2
    assert "time-travel" in result.stdout.lower()


def test_cli_explicit_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "time-travel" in result.stdout.lower()
