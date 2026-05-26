"""Tests for `chronos quickstart` (R109).

`chronos quickstart` bootstraps a fresh `chronos.db` with the builtin-minimal
demo (1 parent run, 3 nodes, 1 fork → child run) so a brand-new user can do::

    pip install chronos-agent
    chronos quickstart
    chronos runs list           # 2 runs visible
    chronos web                 # explore in browser

It is the writer-side counterpart of the read verbs and is allowed to create
the DB file (writers always are, per `_common.py` policy).

Covers:

* default load (no args) → seeded DB at the resolved path with 2 runs / 6 nodes / 1 fork.
* `--demo builtin-minimal` is identical to the default.
* `--demo <unknown>` exits with a friendly error and exit code 2.
* `--db <path>` honours an explicit DB target (overrides $CHRONOS_DB / cwd).
* Re-running into a non-empty DB fails fast unless `--force` is passed.
* `--force` overwrites: the resulting DB is exactly the demo (idempotent shape).
* The shipped `examples/builtin-minimal/envelopes.jsonl` file is parseable
  (anti-bitrot guard for the file landed alongside this verb).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from chronos.cli import app
from chronos.store.sqlite import SqliteStore

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count(db: Path) -> tuple[int, int, int]:
    """Return (runs, nodes, forks) row counts for a chronos DB."""
    store = SqliteStore.open(db)
    try:
        runs = store.list_runs(limit=10_000)
        nodes = sum(len(store.get_nodes_for_run(r.id)) for r in runs)
        forks = sum(len(store.get_forks_for_parent(r.id)) for r in runs)
        return len(runs), nodes, forks
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Default load
# ---------------------------------------------------------------------------


def test_quickstart_default_creates_seeded_db(tmp_path: Path) -> None:
    db = tmp_path / "chronos.db"
    result = runner.invoke(app, ["quickstart", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert db.exists(), "quickstart should create the DB file"

    runs, nodes, forks = _count(db)
    assert runs == 2, f"expected 2 runs (parent+child), got {runs}"
    assert nodes == 6, f"expected 6 nodes (3 per run), got {nodes}"
    assert forks == 1, f"expected 1 fork edge, got {forks}"


def test_quickstart_default_prints_next_steps(tmp_path: Path) -> None:
    db = tmp_path / "chronos.db"
    result = runner.invoke(app, ["quickstart", "--db", str(db)])
    assert result.exit_code == 0, result.output
    # Friendly hints so the user knows what to do *next*.
    assert "runs list" in result.output, (
        f"expected next-step hint mentioning `runs list`, got:\n{result.output}"
    )


def test_quickstart_seeds_known_run_ids(tmp_path: Path) -> None:
    """The demo IDs are deterministic — assertable by docs/demo-link guides."""
    db = tmp_path / "chronos.db"
    result = runner.invoke(app, ["quickstart", "--db", str(db)])
    assert result.exit_code == 0, result.output

    store = SqliteStore.open(db)
    try:
        run_ids = {r.id for r in store.list_runs(limit=10_000)}
    finally:
        store.close()
    assert "11111111-1111-4111-8111-111111111111" in run_ids
    assert "33333333-3333-4333-8333-333333333333" in run_ids


# ---------------------------------------------------------------------------
# --demo selection
# ---------------------------------------------------------------------------


def test_quickstart_explicit_builtin_minimal_matches_default(tmp_path: Path) -> None:
    db = tmp_path / "chronos.db"
    result = runner.invoke(
        app, ["quickstart", "--demo", "builtin-minimal", "--db", str(db)]
    )
    assert result.exit_code == 0, result.output
    runs, nodes, forks = _count(db)
    assert (runs, nodes, forks) == (2, 6, 1)


def test_quickstart_unknown_demo_exits_2_with_hint(tmp_path: Path) -> None:
    db = tmp_path / "chronos.db"
    result = runner.invoke(
        app, ["quickstart", "--demo", "does-not-exist", "--db", str(db)]
    )
    assert result.exit_code == 2, result.output
    # Actionable hint per CLI-error-polish convention (R108).
    assert "does-not-exist" in result.output
    assert not db.exists(), "failed quickstart must not leave a partial DB"


# ---------------------------------------------------------------------------
# Idempotency / safety
# ---------------------------------------------------------------------------


def test_quickstart_refuses_existing_nonempty_db(tmp_path: Path) -> None:
    db = tmp_path / "chronos.db"
    # Seed once.
    r1 = runner.invoke(app, ["quickstart", "--db", str(db)])
    assert r1.exit_code == 0, r1.output
    # Second time → refuse without --force.
    r2 = runner.invoke(app, ["quickstart", "--db", str(db)])
    assert r2.exit_code != 0, r2.output
    assert "force" in r2.output.lower(), (
        "expected hint mentioning --force, got:\n" + r2.output
    )


def test_quickstart_force_overwrites_existing(tmp_path: Path) -> None:
    db = tmp_path / "chronos.db"
    r1 = runner.invoke(app, ["quickstart", "--db", str(db)])
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(app, ["quickstart", "--db", str(db), "--force"])
    assert r2.exit_code == 0, r2.output
    runs, nodes, forks = _count(db)
    assert (runs, nodes, forks) == (2, 6, 1), (
        "after --force the DB should be exactly the demo (no duplicates)"
    )


# ---------------------------------------------------------------------------
# Help surface
# ---------------------------------------------------------------------------


def test_quickstart_help_contains_example() -> None:
    result = runner.invoke(app, ["quickstart", "--help"])
    assert result.exit_code == 0, result.output
    out = result.output.lower()
    # R108 convention: every verb's --help shows an Example block.
    assert "example" in out
    # R109: surface the --demo flag.
    assert "--demo" in result.output


# ---------------------------------------------------------------------------
# Anti-bitrot guards on the shipped envelopes file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["builtin-minimal"])
def test_shipped_envelopes_file_is_loadable(tmp_path: Path, name: str) -> None:
    """If the demo file is malformed the verb is dead — guard at the file level."""
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "examples" / name / "envelopes.jsonl"
    assert path.exists(), f"shipped demo {name} missing: {path}"
    db = tmp_path / "chronos.db"
    result = runner.invoke(
        app, ["quickstart", "--demo", name, "--db", str(db)]
    )
    assert result.exit_code == 0, result.output
