"""Tests for ``chronos compare`` (R59, Phase 4 Arc A slice 2).

Uses a shared ``seeded_compare_db`` fixture: a pivot run and three other
runs (two forks, one identical twin) to exercise happy path, JSON
contract, restrict-to-downstream toggle, and validation errors.
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

runner = CliRunner()


@pytest.fixture
def seeded_compare_db(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A chronos.db with a pivot + 3 other runs for N-run compare tests.

    * ``pivot`` — 3 nodes: plan → draft → polish.
    * ``other_same`` — identical 3 nodes (all-equal column expected).
    * ``other_changed`` — fork: shares plan+draft, polishes with different state.
    * ``other_added`` — fork: plan+draft identical, inserts ``refine``
      before ``polish`` (added-row expected in the merged alignment).
    """
    db_path = tmp_path / "compare.db"
    t0 = datetime(2026, 5, 9, 6, 0, 0, tzinfo=UTC)
    store = SqliteStore.open(db_path)
    try:
        # Pivot run.
        pivot_id = "run-pivot"
        store.put_run(
            Run(
                id=pivot_id,
                adapter="langgraph",
                adapter_thread_id="t-pivot",
                status=RunStatus.COMPLETED,
                started_at=t0,
                ended_at=t0,
                task_description="write haiku",
                initial_state={"task": "haiku"},
                final_state={"final": "tick"},
                tags=["pivot"],
                metadata={},
            )
        )
        plan_id, draft_id, polish_id = "node-pivot-0", "node-pivot-1", "node-pivot-2"
        for i, (nid, name, parent) in enumerate(
            (
                (plan_id, "plan", None),
                (draft_id, "draft", plan_id),
                (polish_id, "polish", draft_id),
            )
        ):
            store.put_node(
                Node(
                    id=nid,
                    run_id=pivot_id,
                    step_index=i,
                    node_name=name,
                    kind=NodeKind.FN,
                    parent_node_id=parent,
                    started_at=t0,
                    ended_at=t0,
                    state_after={"i": i, "v": 1},
                    metadata={},
                )
            )

        # other_same — 3 nodes with matching state_after (all-equal).
        same_id = "run-other-same"
        store.put_run(
            Run(
                id=same_id,
                adapter="langgraph",
                adapter_thread_id="t-same",
                status=RunStatus.COMPLETED,
                started_at=t0,
                ended_at=t0,
                task_description="twin",
                initial_state={"task": "haiku"},
                final_state={"final": "tick"},
                tags=["twin"],
                metadata={},
            )
        )
        for i, (nid, name, parent) in enumerate(
            (
                ("node-same-0", "plan", None),
                ("node-same-1", "draft", "node-same-0"),
                ("node-same-2", "polish", "node-same-1"),
            )
        ):
            store.put_node(
                Node(
                    id=nid,
                    run_id=same_id,
                    step_index=i,
                    node_name=name,
                    kind=NodeKind.FN,
                    parent_node_id=parent,
                    started_at=t0,
                    ended_at=t0,
                    state_after={"i": i, "v": 1},
                    metadata={},
                )
            )

        # other_changed — fork of pivot at draft, different polish state.
        changed_id = "run-other-changed"
        store.put_run(
            Run(
                id=changed_id,
                adapter="langgraph",
                adapter_thread_id="t-changed",
                status=RunStatus.COMPLETED,
                started_at=t0,
                ended_at=t0,
                task_description="fork: polish differs",
                initial_state={"task": "haiku"},
                final_state={"final": "TOCK"},
                tags=["fork"],
                metadata={"forked_from_run": pivot_id},
            )
        )
        # Single downstream node (polish) with different state_after.
        store.put_node(
            Node(
                id="node-changed-2",
                run_id=changed_id,
                step_index=2,
                node_name="polish",
                kind=NodeKind.FN,
                parent_node_id=draft_id,  # cross-run lineage to pivot's draft
                started_at=t0,
                ended_at=t0,
                state_after={"i": 2, "v": 2},  # differs from pivot's v=1
                metadata={},
            )
        )
        store.put_fork(
            Fork(
                id="fork-changed",
                parent_run_id=pivot_id,
                parent_node_id=draft_id,
                child_run_id=changed_id,
                created_at=t0,
                edited_fields={"v": 2},
                reason="retune polish",
            )
        )

        # other_added — fork at draft, inserts a new "refine" step before polish.
        added_id = "run-other-added"
        store.put_run(
            Run(
                id=added_id,
                adapter="langgraph",
                adapter_thread_id="t-added",
                status=RunStatus.COMPLETED,
                started_at=t0,
                ended_at=t0,
                task_description="fork: extra refine",
                initial_state={"task": "haiku"},
                final_state={"final": "refined tick"},
                tags=["fork"],
                metadata={"forked_from_run": pivot_id},
            )
        )
        store.put_node(
            Node(
                id="node-added-refine",
                run_id=added_id,
                step_index=2,
                node_name="refine",
                kind=NodeKind.FN,
                parent_node_id=draft_id,
                started_at=t0,
                ended_at=t0,
                state_after={"refined": True},
                metadata={},
            )
        )
        store.put_node(
            Node(
                id="node-added-polish",
                run_id=added_id,
                step_index=3,
                node_name="polish",
                kind=NodeKind.FN,
                parent_node_id="node-added-refine",
                started_at=t0,
                ended_at=t0,
                state_after={"i": 2, "v": 1},
                metadata={},
            )
        )
        store.put_fork(
            Fork(
                id="fork-added",
                parent_run_id=pivot_id,
                parent_node_id=draft_id,
                child_run_id=added_id,
                created_at=t0,
                edited_fields={},
                reason="add refine step",
            )
        )
    finally:
        store.close()

    return db_path, {
        "pivot": pivot_id,
        "same": same_id,
        "changed": changed_id,
        "added": added_id,
        "draft": draft_id,
        "polish": polish_id,
    }


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_compare_two_positionals_happy_path(
    seeded_compare_db: tuple[Path, dict[str, str]],
) -> None:
    """N=2 — smallest valid invocation. Should exit 0, print pivot banner."""
    db, ids = seeded_compare_db
    result = runner.invoke(app, ["compare", ids["pivot"], ids["same"], "--db", str(db), "--full"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    out = result.stdout
    assert "Pivot:" in out
    assert ids["pivot"] in out
    # Summary table always printed in text mode.
    assert "Summary" in out


def test_compare_three_positionals_happy_path(
    seeded_compare_db: tuple[Path, dict[str, str]],
) -> None:
    """N=3 — pivot + 2 others. Both other ids appear as columns."""
    db, ids = seeded_compare_db
    result = runner.invoke(
        app,
        [
            "compare",
            ids["pivot"],
            ids["changed"],
            ids["added"],
            "--db",
            str(db),
            "--columns",
            "all",
            "--show-equal",
        ],
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    out = result.stdout
    # Both other run ids should appear in the summary table.
    assert ids["changed"] in out
    assert ids["added"] in out


def test_compare_json_shape_matches_merged_dict(
    seeded_compare_db: tuple[Path, dict[str, str]],
) -> None:
    """--json emits the exact MergedPivotAlignment.to_dict() shape."""
    db, ids = seeded_compare_db
    result = runner.invoke(
        app,
        ["compare", ids["pivot"], ids["changed"], ids["added"], "--db", str(db), "--json"],
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"pivot_id", "other_ids", "alignment", "summary", "warnings"}
    assert payload["pivot_id"] == ids["pivot"]
    assert payload["other_ids"] == [ids["changed"], ids["added"]]
    # summary keyed per other id.
    assert set(payload["summary"].keys()) == {ids["changed"], ids["added"]}
    # Each summary dict has the ADR-006 quadruple.
    for s in payload["summary"].values():
        assert set(s.keys()) == {"equal", "changed", "added", "removed"}


def test_compare_restrict_to_downstream_false_shows_full_diff(
    seeded_compare_db: tuple[Path, dict[str, str]],
) -> None:
    """--full disables per-pair downstream slicing; upstream nodes appear as removed."""
    db, ids = seeded_compare_db
    result = runner.invoke(
        app,
        ["compare", ids["pivot"], ids["changed"], "--db", str(db), "--full", "--json"],
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    payload = json.loads(result.stdout)
    # With --full, changed other has only 1 downstream node (polish), so
    # plan + draft show as "removed" in its column.
    s = payload["summary"][ids["changed"]]
    assert s["removed"] >= 2


def test_compare_n2_summary_matches_chronos_diff_summary(
    seeded_compare_db: tuple[Path, dict[str, str]],
) -> None:
    """R58 regression guard: N=2 summary numerically == `chronos diff` summary."""
    db, ids = seeded_compare_db
    # Run `chronos diff` for reference.
    diff_result = runner.invoke(
        app, ["diff", ids["pivot"], ids["same"], "--db", str(db), "--full", "--json"]
    )
    assert diff_result.exit_code == 0
    diff_payload = json.loads(diff_result.stdout)

    # Run `chronos compare` N=2.
    cmp_result = runner.invoke(
        app, ["compare", ids["pivot"], ids["same"], "--db", str(db), "--full", "--json"]
    )
    assert cmp_result.exit_code == 0
    cmp_payload = json.loads(cmp_result.stdout)

    # The per-column summary for the single other must match the 2-run summary.
    assert cmp_payload["summary"][ids["same"]] == diff_payload["summary"]


def test_compare_added_row_for_fork_with_insert(
    seeded_compare_db: tuple[Path, dict[str, str]],
) -> None:
    """Fork that inserts `refine` produces an insert row in alignment[]."""
    db, ids = seeded_compare_db
    result = runner.invoke(app, ["compare", ids["pivot"], ids["added"], "--db", str(db), "--json"])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    payload = json.loads(result.stdout)
    # An insert row has pivot_step == None and an inserted_after_pivot_step key.
    insert_rows = [r for r in payload["alignment"] if r["pivot_step"] is None]
    assert len(insert_rows) >= 1
    assert all("inserted_after_pivot_step" in r for r in insert_rows)


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_compare_with_only_pivot_errors(
    seeded_compare_db: tuple[Path, dict[str, str]],
) -> None:
    """Typer requires at least one `other_run_ids` positional."""
    db, ids = seeded_compare_db
    result = runner.invoke(app, ["compare", ids["pivot"], "--db", str(db)])
    # Typer's missing-argument error has exit code 2.
    assert result.exit_code == 2


def test_compare_duplicate_other_ids_errors(
    seeded_compare_db: tuple[Path, dict[str, str]],
) -> None:
    """Duplicates are a footgun → exit code 2 with a clear error message."""
    db, ids = seeded_compare_db
    result = runner.invoke(
        app,
        ["compare", ids["pivot"], ids["same"], ids["same"], "--db", str(db)],
    )
    assert result.exit_code == 2
    assert "duplicate" in (result.stdout + (result.stderr or "")).lower()


def test_compare_pivot_id_in_others_errors(
    seeded_compare_db: tuple[Path, dict[str, str]],
) -> None:
    """Pivot id appearing as an other id is 400-style; exit code 2."""
    db, ids = seeded_compare_db
    result = runner.invoke(
        app,
        ["compare", ids["pivot"], ids["pivot"], "--db", str(db)],
    )
    assert result.exit_code == 2
    combined = (result.stdout + (result.stderr or "")).lower()
    assert "pivot" in combined or "both" in combined


def test_compare_missing_pivot_id_errors(
    seeded_compare_db: tuple[Path, dict[str, str]],
) -> None:
    """Pivot id not in store → exit code 1 (runtime 'no such run')."""
    db, ids = seeded_compare_db
    result = runner.invoke(
        app,
        ["compare", "does-not-exist", ids["same"], "--db", str(db)],
    )
    assert result.exit_code == 1
    assert "no such run" in (result.stdout + (result.stderr or "")).lower()


def test_compare_bad_columns_value_errors(
    seeded_compare_db: tuple[Path, dict[str, str]],
) -> None:
    """--columns rejects unknown values with exit code 2."""
    db, ids = seeded_compare_db
    result = runner.invoke(
        app,
        ["compare", ids["pivot"], ids["same"], "--db", str(db), "--columns", "bogus"],
    )
    assert result.exit_code == 2
    combined = (result.stdout + (result.stderr or "")).lower()
    assert "columns" in combined
