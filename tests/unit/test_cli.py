"""Smoke + read-side tests for the Chronos CLI.

Covers:
* Root app: --version, info, implicit help (no args), --help
* `runs list`: empty DB, populated DB, --json, --limit, missing DB file
* `runs show`: existing run (rich + json), missing run, fork-of annotation
* `forks show`: existing fork (rich + json), missing fork
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chronos.cli import app
from chronos.core.models import Fork, Node, NodeKind, Run, RunStatus
from chronos.store.sqlite import SqliteStore

# R52/R62: click<8.3 needed `CliRunner(mix_stderr=False)` to keep stderr
# separate; click>=8.3 **removed** the kwarg (stderr is always separate). The
# runner below keeps working across both by passing no argument.
runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """An initialised chronos.db with migrations applied but no rows."""
    p = tmp_path / "empty.db"
    SqliteStore.open(p).close()
    return p


@pytest.fixture
def seeded_db(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A chronos.db with a parent run (3 nodes), a fork, and a child run (1 node).

    Returns:
        (db_path, ids-dict) where ids has keys ``parent``, ``child``, ``fork``,
        ``parent_node_draft`` (the fork point).
    """
    db_path = tmp_path / "seeded.db"
    t0 = datetime(2026, 4, 23, 4, 0, 0, tzinfo=UTC)
    parent_id = "run-p-1"
    child_id = "run-c-1"
    fork_id = "fork-1"
    draft_id = "node-p-1"

    store = SqliteStore.open(db_path)
    try:
        store.put_run(
            Run(
                id=parent_id,
                adapter="langgraph",
                adapter_thread_id="t1",
                status=RunStatus.COMPLETED,
                started_at=t0,
                ended_at=t0,
                task_description="write haiku",
                initial_state={"task": "haiku"},
                final_state={"final": "tick"},
                tags=["demo"],
                metadata={},
            )
        )
        for i, (nid, name) in enumerate(
            (("node-p-0", "plan"), (draft_id, "draft"), ("node-p-2", "polish"))
        ):
            store.put_node(
                Node(
                    id=nid,
                    run_id=parent_id,
                    step_index=i,
                    node_name=name,
                    kind=NodeKind.FN,
                    parent_node_id=(f"node-p-{i - 1}" if i > 0 else None),
                    started_at=t0,
                    ended_at=t0,
                    state_after={"i": i},
                    metadata={},
                )
            )
        store.put_run(
            Run(
                id=child_id,
                adapter="langgraph",
                adapter_thread_id="t1-fork",
                status=RunStatus.COMPLETED,
                started_at=t0,
                ended_at=t0,
                task_description="fork: alt draft",
                initial_state={"task": "haiku"},
                final_state={"final": "FORKED tick"},
                tags=["fork"],
                metadata={"forked_from_run": parent_id},
            )
        )
        store.put_node(
            Node(
                id="node-c-0",
                run_id=child_id,
                step_index=2,
                node_name="polish",
                kind=NodeKind.FN,
                parent_node_id=draft_id,  # cross-run lineage pointer
                started_at=t0,
                ended_at=t0,
                state_after={"forked": True},
                metadata={},
            )
        )
        store.put_fork(
            Fork(
                id=fork_id,
                parent_run_id=parent_id,
                parent_node_id=draft_id,
                child_run_id=child_id,
                created_at=t0,
                edited_fields={"draft": "[FORKED] alt"},
                reason="try alt draft",
            )
        )
    finally:
        store.close()

    return db_path, {
        "parent": parent_id,
        "child": child_id,
        "fork": fork_id,
        "parent_node_draft": draft_id,
    }


# ---------------------------------------------------------------------------
# Smoke (preserved from M1.2)
# ---------------------------------------------------------------------------


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "chronos" in result.stdout


def test_cli_info() -> None:
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    # Status line moves with the release — R60 rolled it from "Phase 3" to
    # "Phase 4 Arc A" alongside the v0.5.0 cut. Assert on stable tokens: the
    # "chronos" program name + the current phase marker. Don't pin the exact
    # version string; other tests cover that.
    assert "chronos" in result.stdout.lower()
    assert "phase 4" in result.stdout.lower()


def test_cli_help_default() -> None:
    result = runner.invoke(app, [])
    # R52: typer>=0.22 flipped `no_args_is_help` behavior — it now prints help
    # to stdout and exits 0 (previously exit 2 per the click convention). We
    # no longer assert on the exit code to keep the test version-agnostic;
    # the help-text assertion is the load-bearing check.
    assert "time-travel" in result.stdout.lower()


def test_cli_explicit_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "time-travel" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Error paths: missing DB
# ---------------------------------------------------------------------------


def test_runs_list_missing_db(tmp_path: Path) -> None:
    missing = tmp_path / "nope.db"
    result = runner.invoke(app, ["runs", "list", "--db", str(missing)])
    assert result.exit_code == 2
    # Combine stdout+stderr defensively: Typer/Click can route errors either way
    combined = (result.stdout + (result.stderr or "")).lower()
    assert "not found" in combined or "no such" in combined


# ---------------------------------------------------------------------------
# `runs list`
# ---------------------------------------------------------------------------


def test_runs_list_empty(empty_db: Path) -> None:
    result = runner.invoke(app, ["runs", "list", "--db", str(empty_db)])
    assert result.exit_code == 0
    assert "no runs" in result.stdout.lower()


def test_runs_list_rich(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, ids = seeded_db
    result = runner.invoke(app, ["runs", "list", "--db", str(db)])
    assert result.exit_code == 0
    assert ids["parent"] in result.stdout
    assert ids["child"] in result.stdout
    assert "langgraph" in result.stdout
    assert "completed" in result.stdout


def test_runs_list_json(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, ids = seeded_db
    result = runner.invoke(app, ["runs", "list", "--db", str(db), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert len(data) == 2
    run_ids = {r["id"] for r in data}
    assert run_ids == {ids["parent"], ids["child"]}
    # Shape sanity
    for r in data:
        assert set(r).issuperset({"id", "adapter", "status", "started_at", "task_description"})


def test_runs_list_limit(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, _ = seeded_db
    result = runner.invoke(app, ["runs", "list", "--db", str(db), "--limit", "1", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert len(data) == 1


def test_runs_list_env_var_db(
    monkeypatch: pytest.MonkeyPatch, seeded_db: tuple[Path, dict[str, str]]
) -> None:
    db, ids = seeded_db
    monkeypatch.setenv("CHRONOS_DB", str(db))
    result = runner.invoke(app, ["runs", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert {r["id"] for r in data} == {ids["parent"], ids["child"]}


# ---------------------------------------------------------------------------
# `runs show`
# ---------------------------------------------------------------------------


def test_runs_show_rich(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, ids = seeded_db
    result = runner.invoke(app, ["runs", "show", ids["parent"], "--db", str(db)])
    assert result.exit_code == 0
    # Header
    assert ids["parent"] in result.stdout
    # Node names rendered
    for name in ("plan", "draft", "polish"):
        assert name in result.stdout
    # Not a forked run — should NOT show "forked from"
    assert "forked from" not in result.stdout.lower()


def test_runs_show_child_displays_fork_lineage(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, ids = seeded_db
    result = runner.invoke(app, ["runs", "show", ids["child"], "--db", str(db)])
    assert result.exit_code == 0
    assert ids["child"] in result.stdout
    assert "forked from" in result.stdout.lower()
    assert ids["parent"] in result.stdout  # parent referenced
    assert ids["fork"] in result.stdout


def test_runs_show_json(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, ids = seeded_db
    result = runner.invoke(app, ["runs", "show", ids["parent"], "--db", str(db), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["run"]["id"] == ids["parent"]
    assert len(payload["nodes"]) == 3
    assert [n["node_name"] for n in payload["nodes"]] == ["plan", "draft", "polish"]
    assert payload["fork_of"] is None  # parent is not a forked child


def test_runs_show_json_child_has_fork_of(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, ids = seeded_db
    result = runner.invoke(app, ["runs", "show", ids["child"], "--db", str(db), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["fork_of"] is not None
    assert payload["fork_of"]["id"] == ids["fork"]
    assert payload["fork_of"]["parent_run_id"] == ids["parent"]
    assert payload["fork_of"]["parent_node_id"] == ids["parent_node_draft"]


def test_runs_show_missing(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, _ = seeded_db
    result = runner.invoke(app, ["runs", "show", "nope-nope", "--db", str(db)])
    assert result.exit_code == 1
    assert "no such run" in (result.stdout + (result.stderr or "")).lower()


# ---------------------------------------------------------------------------
# `forks show`
# ---------------------------------------------------------------------------


def test_forks_show_rich(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, ids = seeded_db
    result = runner.invoke(app, ["forks", "show", ids["fork"], "--db", str(db)])
    assert result.exit_code == 0
    out = result.stdout
    assert ids["parent"] in out
    assert ids["child"] in out
    assert "draft" in out  # the edited field key
    assert "try alt draft" in out  # the reason


def test_forks_show_json(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, ids = seeded_db
    result = runner.invoke(app, ["forks", "show", ids["fork"], "--db", str(db), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["fork"]["id"] == ids["fork"]
    assert payload["parent_run"]["id"] == ids["parent"]
    assert payload["child_run"]["id"] == ids["child"]
    assert payload["fork"]["edited_fields"] == {"draft": "[FORKED] alt"}
    assert len(payload["child_nodes"]) == 1
    assert payload["child_nodes"][0]["node_name"] == "polish"


def test_forks_show_missing(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, _ = seeded_db
    result = runner.invoke(app, ["forks", "show", "fork-nope", "--db", str(db)])
    assert result.exit_code == 1
    assert "no such fork" in (result.stdout + (result.stderr or "")).lower()


# ---------------------------------------------------------------------------
# Sub-app help surfaces
# ---------------------------------------------------------------------------


def test_runs_subapp_help() -> None:
    result = runner.invoke(app, ["runs", "--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout.lower()
    assert "show" in result.stdout.lower()


def test_forks_subapp_help() -> None:
    result = runner.invoke(app, ["forks", "--help"])
    assert result.exit_code == 0
    assert "show" in result.stdout.lower()


# ---------------------------------------------------------------------------
# `chronos diff` (M1.8)
# ---------------------------------------------------------------------------


def test_diff_fork_child_restricted_default(seeded_db: tuple[Path, dict[str, str]]) -> None:
    """Default fork-aware mode slices A to downstream-only."""
    db, ids = seeded_db
    result = runner.invoke(app, ["diff", ids["parent"], ids["child"], "--db", str(db)])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    out = result.stdout
    # fork annotation banner
    assert "forked from a @ node" in out.lower() or "forked from a" in out.lower()
    # single diff row: polish — same name, different state_after
    assert "polish" in out
    assert "changed" in out.lower()
    # summary line
    assert "summary" in out.lower()


def test_diff_fork_child_full_mode(seeded_db: tuple[Path, dict[str, str]]) -> None:
    """--full disables the fork-downstream slice, showing REMOVED for prefix."""
    db, ids = seeded_db
    result = runner.invoke(app, ["diff", ids["parent"], ids["child"], "--db", str(db), "--full"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    out = result.stdout.lower()
    assert "removed" in out  # parent nodes plan + draft aren't on child
    assert "plan" in out
    assert "draft" in out
    assert "polish" in out


def test_diff_json_shape(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, ids = seeded_db
    result = runner.invoke(app, ["diff", ids["parent"], ids["child"], "--db", str(db), "--json"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {
        "run_a",
        "run_b",
        "fork_of",
        "restricted_to_downstream",
        "entries",
        "summary",
    }
    assert payload["restricted_to_downstream"] is True
    assert payload["fork_of"]["parent_node_name"] == "draft"
    # After slicing, A's "polish" vs B's "polish" — 1 changed entry
    assert payload["summary"]["changed"] == 1
    assert payload["summary"]["removed"] == 0
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["tag"] == "changed"
    assert payload["entries"][0]["node_name"] == "polish"


def test_diff_json_full_mode(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, ids = seeded_db
    result = runner.invoke(
        app,
        [
            "diff",
            ids["parent"],
            ids["child"],
            "--db",
            str(db),
            "--json",
            "--full",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["restricted_to_downstream"] is False
    # plan REMOVED, draft REMOVED, polish CHANGED
    assert payload["summary"] == {"equal": 0, "changed": 1, "added": 0, "removed": 2}


def test_diff_missing_run_a(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, ids = seeded_db
    result = runner.invoke(app, ["diff", "run-nope", ids["child"], "--db", str(db)])
    assert result.exit_code == 1
    combined = (result.stdout + (result.stderr or "")).lower()
    assert "run-nope" in combined
    assert "no such run" in combined


def test_diff_missing_run_b(seeded_db: tuple[Path, dict[str, str]]) -> None:
    db, ids = seeded_db
    result = runner.invoke(app, ["diff", ids["parent"], "missing-B", "--db", str(db)])
    assert result.exit_code == 1
    combined = (result.stdout + (result.stderr or "")).lower()
    assert "missing-b" in combined


def test_diff_missing_db(tmp_path: Path) -> None:
    result = runner.invoke(app, ["diff", "x", "y", "--db", str(tmp_path / "nope.db")])
    assert result.exit_code == 2
    combined = (result.stdout + (result.stderr or "")).lower()
    assert "chronos db not found" in combined


def test_diff_verbose_flag_expands_state_diff(
    seeded_db: tuple[Path, dict[str, str]],
) -> None:
    db, ids = seeded_db
    result = runner.invoke(
        app,
        [
            "diff",
            ids["parent"],
            ids["child"],
            "--db",
            str(db),
            "--verbose",
        ],
    )
    assert result.exit_code == 0
    # verbose mode should print inline state_after deltas containing the
    # key name(s) that differ. Parent polish state_after = {"i": 2},
    # child polish state_after = {"forked": True}. Both keys differ.
    out = result.stdout.lower()
    assert "forked" in out or "→" in result.stdout or "->" in result.stdout


def test_diff_help_surfaces() -> None:
    result = runner.invoke(app, ["diff", "--help"])
    assert result.exit_code == 0
    assert "diff" in result.stdout.lower()
    assert "--full" in result.stdout
    assert "--json" in result.stdout
    assert "--verbose" in result.stdout
    assert "show" in result.stdout.lower()
