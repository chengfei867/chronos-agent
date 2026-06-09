"""Unit tests for `chronos doctor` (R110).

Covers:

* Help text shape (Typer wiring + docstring landed).
* All-green path on a freshly-seeded quickstart DB (exit 0).
* Warning-only path when chronos.db is missing (exit 0; ⚠️ row visible).
* Missing-examples-dir path (warning row, exit 0).
* Forced ❌ exit when the DB schema is incompatible (exit 1) — synthesised
  by writing a fake `schema_info.schema_version` value at test setup.
* Missing-optional-extra path produces a ⚠️ row, NOT ❌ (extras are optional).
"""

from __future__ import annotations

import sqlite3
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from chronos.cli import app
from chronos.cli.doctor import (
    _check_examples,
    _check_optional_extras,
    _check_python_version,
    doctor_command,
)

runner = CliRunner()


def _capture_console() -> tuple[Console, StringIO]:
    buf = StringIO()
    return Console(file=buf, width=120, force_terminal=False, no_color=True), buf


# ---------------------------------------------------------------------------
# Help / wiring
# ---------------------------------------------------------------------------


def test_doctor_help_includes_example_and_exit_codes() -> None:
    result = runner.invoke(app, ["doctor", "--help"])
    assert result.exit_code == 0
    out = result.stdout
    assert "Example" in out
    assert "Exit codes" in out
    assert "--db" in out


def test_doctor_listed_in_top_level_help() -> None:
    """`chronos --help` advertises the new verb."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "doctor" in result.stdout


def test_info_status_line_lists_doctor() -> None:
    """R110 ratchet: info() now lists doctor among the available commands."""
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    assert "doctor" in result.stdout.lower()


# ---------------------------------------------------------------------------
# All-green path on seeded quickstart DB
# ---------------------------------------------------------------------------


def test_doctor_happy_path_exit_zero(tmp_path: Path) -> None:
    """Seed a fresh DB via quickstart, then doctor must exit 0 with all-green DB rows."""
    db = tmp_path / "chronos.db"
    quickstart_result = runner.invoke(app, ["quickstart", "--db", str(db)])
    assert quickstart_result.exit_code == 0, quickstart_result.stdout

    console, buf = _capture_console()
    code = doctor_command(db=db, console=console)
    out = buf.getvalue()

    assert code == 0
    assert "Python version" in out
    assert "chronos package" in out
    assert "SQLite library" in out
    assert "DB schema" in out
    # 2 runs / 6 nodes / 1 fork from the builtin-minimal demo.
    assert "2 runs" in out
    assert "6 nodes" in out
    assert "1 forks" in out
    # no ❌ rows.
    assert "❌" not in out


# ---------------------------------------------------------------------------
# Warning-only path when chronos.db is absent
# ---------------------------------------------------------------------------


def test_doctor_missing_db_is_warning_not_failure(tmp_path: Path) -> None:
    """No DB at the resolved path → ⚠️ row + exit 0 (not a hard failure)."""
    db = tmp_path / "absent.db"
    assert not db.exists()

    console, buf = _capture_console()
    code = doctor_command(db=db, console=console)
    out = buf.getvalue()

    assert code == 0
    assert "⚠️" in out
    assert "not found" in out
    # Hint should point at quickstart.
    assert "quickstart" in out


# ---------------------------------------------------------------------------
# Schema-mismatch path (the only realistic ❌ in this test environment)
# ---------------------------------------------------------------------------


def test_doctor_schema_mismatch_is_failure(tmp_path: Path) -> None:
    """Forge a DB with a future-major schema_version — doctor must fail with exit 1."""
    db = tmp_path / "future.db"
    # Seed via quickstart (real schema), then overwrite schema_info to a future major.
    quickstart_result = runner.invoke(app, ["quickstart", "--db", str(db)])
    assert quickstart_result.exit_code == 0

    conn = sqlite3.connect(db)
    try:
        conn.execute("UPDATE schema_info SET schema_version = '99.0.0'")
        conn.commit()
    finally:
        conn.close()

    # Bypass _open_store_fn's strict schema-version check by using a minimal opener
    # that returns a SqliteStore with the open() path doing version-check itself.
    # Actually: SqliteStore.open() rejects on major mismatch (raises). So our doctor
    # must catch that and surface it as a ❌ row. Use the default open_store_fn; the
    # exception path in _check_database fires.
    from chronos.store.sqlite import SqliteStore

    def opener(path: Path) -> SqliteStore:
        return SqliteStore.open(path)

    console, buf = _capture_console()
    code = doctor_command(db=db, console=console, open_store_fn=opener)
    out = buf.getvalue()

    assert code == 1
    assert "❌" in out
    # Either the open raises (caught by the failed-to-open branch) or schema
    # row reports the mismatch directly — both produce a ❌ around the DB row.
    assert "schema" in out.lower() or "open" in out.lower()


# ---------------------------------------------------------------------------
# Examples directory missing → warning row
# ---------------------------------------------------------------------------


def test_check_examples_missing_dir_is_warning(tmp_path: Path) -> None:
    row = _check_examples(tmp_path / "does-not-exist")
    assert row.status == "warn"
    assert "not found" in row.detail


def test_check_examples_empty_dir_is_warning(tmp_path: Path) -> None:
    """Existing `examples/` with no demos shows a warning, not a failure."""
    (tmp_path / "examples").mkdir()
    row = _check_examples(tmp_path / "examples")
    assert row.status == "warn"
    assert "no demos" in row.detail.lower()


def test_check_examples_with_demo_is_ok(tmp_path: Path) -> None:
    demos = tmp_path / "examples"
    demos.mkdir()
    demo_a = demos / "alpha"
    demo_a.mkdir()
    (demo_a / "envelopes.jsonl").write_text("{}\n", encoding="utf-8")
    row = _check_examples(demos)
    assert row.status == "ok"
    assert "alpha" in row.detail


# ---------------------------------------------------------------------------
# Optional extras: missing one is a warning, never a failure
# ---------------------------------------------------------------------------


def test_check_optional_extras_returns_rows() -> None:
    """All five tracked extras should produce a row each."""
    rows = _check_optional_extras()
    extras_seen = {r.label for r in rows}
    # The label format is `Extra: [<name>]`.
    for extra in ("web", "langgraph", "anthropic_agents", "autogen", "crewai"):
        assert any(f"[{extra}]" in label for label in extras_seen), extras_seen


def test_check_optional_extras_missing_is_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    """If one extra fails to import, the row is `warn`, not `fail`."""
    import importlib

    real_import = importlib.import_module

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "fastapi":
            raise ImportError("simulated missing fastapi")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    rows = _check_optional_extras()
    web_row = next(r for r in rows if "[web]" in r.label)
    assert web_row.status == "warn"
    assert "not installed" in web_row.detail
    assert web_row.hint is not None and "uv pip install" in web_row.hint


# ---------------------------------------------------------------------------
# Python version check (sanity — current env always passes)
# ---------------------------------------------------------------------------


def test_check_python_version_current_env_is_ok() -> None:
    """The test runner is, by definition, Python ≥ 3.11 (per pyproject)."""
    row = _check_python_version()
    assert row.status == "ok"
    assert "≥ 3.11" in row.detail


# ---------------------------------------------------------------------------
# R121 F14: Rich-markup escape regression — hint text containing ``[extra]``
# (e.g. ``chronos-agent[web]``) used to be silently consumed by the Rich
# parser when ``console.print`` saw it as a markup tag, so the rendered
# install-hint became ``\`uv pip install 'chronos-agent'\``` (extras eaten).
# After the fix in ``doctor_command``, hints (and labels and detail) flow
# through ``_escape_markup`` before being interpolated into the print
# template — bracketed names render literally.
# ---------------------------------------------------------------------------


def test_doctor_render_preserves_extras_in_hint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Rendered output must contain the literal ``[web]`` token in the
    install hint when the ``web`` extra is missing — verifies F14 fix."""
    import importlib

    real_import = importlib.import_module

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "fastapi":
            raise ImportError("simulated missing fastapi")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    from chronos.store.sqlite import SqliteStore

    db = tmp_path / "doctor.db"
    SqliteStore.open(db).close()

    console, buf = _capture_console()
    doctor_command(db=db, console=console, examples_root=tmp_path / "no-examples")
    out = buf.getvalue()

    # Label must keep its bracketed extra name visible.
    assert "Extra: [web]" in out
    # Hint must keep the install command's ``[web]`` extra visible — this
    # is the user-actionable string that the Rich parser used to eat.
    assert "chronos-agent[web]" in out
    # And the broken pre-fix string must NOT appear (extras stripped out).
    assert "chronos-agent'" not in out  # would mean `[web]` got eaten
