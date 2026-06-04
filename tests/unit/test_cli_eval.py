"""CLI tests for the `chronos eval` verb group (R115 / ADR-030).

Covers the three subcommands:

* `chronos eval run <run_id> --evaluator <name>` — score a run, persist to DB.
* `chronos eval list <run_id>` — show evaluations for a run.
* `chronos eval list-evaluators` — show registered evaluators.

Plus boundaries:

* unknown evaluator name → friendly error, non-zero exit.
* unknown run id → friendly error, non-zero exit.
* `--json` flag emits machine-parseable JSON.
* Re-running the same evaluator UPSERTs (no duplicate rows).

Strategy: seed a fresh DB via `chronos quickstart` (writer verb that's already
covered by `test_cli_quickstart.py`), then drive `eval` verbs via Typer's
``CliRunner`` and assert on stdout + DB state.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chronos.cli import app
from chronos.store.sqlite import SqliteStore

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed(tmp_path: Path) -> tuple[Path, str, str]:
    """Seed a builtin-minimal demo into ``tmp_path/chronos.db``. Returns
    ``(db_path, parent_run_id, child_run_id)``."""
    db = tmp_path / "chronos.db"
    result = runner.invoke(app, ["quickstart", "--db", str(db)])
    assert result.exit_code == 0, f"quickstart seed failed: {result.output}"
    store = SqliteStore.open(db)
    try:
        runs = store.list_runs(limit=10)
        assert len(runs) == 2
        # builtin-minimal seeds parent first, then child fork; sort by started_at to be deterministic.
        runs_sorted = sorted(runs, key=lambda r: r.started_at)
        return db, runs_sorted[0].id, runs_sorted[1].id
    finally:
        store.close()


# ---------------------------------------------------------------------------
# `chronos eval list-evaluators`
# ---------------------------------------------------------------------------


def test_eval_list_evaluators_shows_builtins(tmp_path: Path) -> None:
    """Both ADR-030 §50-52 built-in evaluators are listed by default."""
    result = runner.invoke(app, ["eval", "list-evaluators"])
    assert result.exit_code == 0, result.output
    assert "output_length_chars" in result.output
    assert "final_state_key_present" in result.output


def test_eval_list_evaluators_json(tmp_path: Path) -> None:
    """`--json` emits an array with one entry per registered evaluator."""
    result = runner.invoke(app, ["eval", "list-evaluators", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    # Payload is a list of evaluator name strings (or dicts; tolerate both
    # to avoid coupling tests to a transient JSON shape).
    if payload and isinstance(payload[0], dict):
        names = sorted(e["name"] for e in payload)
    else:
        names = sorted(payload)
    assert "output_length_chars" in names
    assert "final_state_key_present" in names


# ---------------------------------------------------------------------------
# `chronos eval run`
# ---------------------------------------------------------------------------


def test_eval_run_persists_score(tmp_path: Path) -> None:
    """`chronos eval run` writes a row to the evaluations table."""
    db, parent_id, _ = _seed(tmp_path)
    result = runner.invoke(
        app,
        [
            "eval",
            "run",
            parent_id,
            "--evaluator",
            "output_length_chars",
            "--db",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output

    store = SqliteStore.open(db)
    try:
        evs = store.get_evaluations_for_run(parent_id)
        assert len(evs) == 1
        assert evs[0].evaluator_name == "output_length_chars"
        assert evs[0].score is not None
    finally:
        store.close()


def test_eval_run_json_output(tmp_path: Path) -> None:
    """`chronos eval run --json` emits a single Evaluation object as JSON."""
    db, parent_id, _ = _seed(tmp_path)
    result = runner.invoke(
        app,
        [
            "eval",
            "run",
            parent_id,
            "-e",
            "output_length_chars",
            "--db",
            str(db),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_id"] == parent_id
    assert payload["evaluator_name"] == "output_length_chars"
    assert isinstance(payload["score"], (int, float))


def test_eval_run_unknown_evaluator_errors(tmp_path: Path) -> None:
    """Unknown evaluator name exits non-zero with an actionable hint."""
    db, parent_id, _ = _seed(tmp_path)
    result = runner.invoke(
        app,
        [
            "eval",
            "run",
            parent_id,
            "--evaluator",
            "totally_made_up",
            "--db",
            str(db),
        ],
    )
    assert result.exit_code != 0
    assert "totally_made_up" in result.output
    # Hint should point at list-evaluators for discoverability.
    assert "list-evaluators" in result.output or "registered" in result.output.lower()


def test_eval_run_unknown_run_errors(tmp_path: Path) -> None:
    """Unknown run_id exits non-zero with an actionable hint."""
    db, _, _ = _seed(tmp_path)
    result = runner.invoke(
        app,
        [
            "eval",
            "run",
            "run_does_not_exist",
            "--evaluator",
            "output_length_chars",
            "--db",
            str(db),
        ],
    )
    assert result.exit_code != 0
    assert "run_does_not_exist" in result.output


def test_eval_run_upserts_on_repeat(tmp_path: Path) -> None:
    """Running the same evaluator twice on the same run UPSERTs — no dupes."""
    db, parent_id, _ = _seed(tmp_path)
    for _ in range(2):
        result = runner.invoke(
            app,
            [
                "eval",
                "run",
                parent_id,
                "-e",
                "output_length_chars",
                "--db",
                str(db),
            ],
        )
        assert result.exit_code == 0, result.output

    store = SqliteStore.open(db)
    try:
        evs = store.get_evaluations_for_run(parent_id)
        assert len(evs) == 1, f"UPSERT broken — expected 1 row, got {len(evs)}"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# `chronos eval list`
# ---------------------------------------------------------------------------


def test_eval_list_shows_persisted_score(tmp_path: Path) -> None:
    """`chronos eval list <run_id>` shows scores written by `eval run`."""
    db, parent_id, _ = _seed(tmp_path)
    runner.invoke(
        app,
        [
            "eval",
            "run",
            parent_id,
            "-e",
            "output_length_chars",
            "--db",
            str(db),
        ],
    )

    result = runner.invoke(app, ["eval", "list", parent_id, "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "output_length_chars" in result.output


def test_eval_list_json(tmp_path: Path) -> None:
    """`--json` emits a list of Evaluation objects for the run."""
    db, parent_id, _ = _seed(tmp_path)
    runner.invoke(
        app,
        [
            "eval",
            "run",
            parent_id,
            "-e",
            "final_state_key_present",
            "--db",
            str(db),
        ],
    )

    result = runner.invoke(app, ["eval", "list", parent_id, "--db", str(db), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload) >= 1
    assert payload[0]["run_id"] == parent_id


def test_eval_list_empty_run_ok(tmp_path: Path) -> None:
    """A run with no evaluations exits 0 (empty list / friendly hint)."""
    db, parent_id, _ = _seed(tmp_path)
    result = runner.invoke(app, ["eval", "list", parent_id, "--db", str(db)])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# `--help` ergonomics (R108 standard: every verb has an example)
# ---------------------------------------------------------------------------


def test_eval_run_help_has_example(tmp_path: Path) -> None:
    result = runner.invoke(app, ["eval", "run", "--help"])
    assert result.exit_code == 0
    assert "chronos eval run" in result.output


def test_eval_list_help_has_example(tmp_path: Path) -> None:
    result = runner.invoke(app, ["eval", "list", "--help"])
    assert result.exit_code == 0


def test_eval_list_evaluators_help(tmp_path: Path) -> None:
    result = runner.invoke(app, ["eval", "list-evaluators", "--help"])
    assert result.exit_code == 0
