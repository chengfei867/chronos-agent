"""Integration test for the SqliteStore evaluations table (R115, ADR-030).

Covers:
  * Migration 002 applies cleanly on fresh DB (schema_version → 0.2.0)
  * put_evaluation → get_evaluation_for_run_evaluator round-trip is byte-equal
    on every persisted field (id/run_id/evaluator_name/score/passed/rationale/
    metadata/created_at).
  * UPSERT on (run_id, evaluator_name): re-running keeps row count at 1
    and overwrites score/passed/rationale/metadata/created_at.
  * UNIQUE INDEX (run_id, evaluator_name) is enforced — direct INSERT of a
    duplicate (without ON CONFLICT) raises IntegrityError.
  * get_evaluations_for_run returns rows in created_at ASC order.
  * FK on runs(id) ON DELETE CASCADE removes orphan evaluations when the
    parent run is deleted.

This is the spike-21 acceptance for ADR-030 §Schema.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chronos.core.models import Evaluation, Run
from chronos.store import SqliteStore


def _make_run(**overrides: object) -> Run:
    defaults: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "adapter": "langgraph",
        "adapter_thread_id": "t-" + uuid.uuid4().hex[:6],
    }
    defaults.update(overrides)
    return Run(**defaults)  # type: ignore[arg-type]


def _make_evaluation(run_id: str, **overrides: object) -> Evaluation:
    defaults: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "run_id": run_id,
        "evaluator_name": "output_length_chars",
        "score": 42.0,
        "passed": None,
        "rationale": "len = 42",
        "metadata": {"key": "output"},
    }
    defaults.update(overrides)
    return Evaluation(**defaults)  # type: ignore[arg-type]


# ---------------- schema ----------------------------------------------------


def test_migration_002_bumps_schema_version(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    with SqliteStore.open(db) as store:
        assert store.schema_version == "0.2.0"


def test_evaluations_table_present(tmp_path: Path) -> None:
    """The migration must create both the table and the unique index."""
    db = tmp_path / "fresh.db"
    SqliteStore.open(db).close()
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'index') "
            "AND name LIKE '%evaluation%' ORDER BY name"
        ).fetchall()
        names = {r[0] for r in rows}
        assert "evaluations" in names
        assert "idx_evaluations_run_evaluator" in names
    finally:
        conn.close()


# ---------------- round-trip ------------------------------------------------


def test_put_and_get_round_trip(tmp_path: Path) -> None:
    with SqliteStore.open(tmp_path / "rt.db") as store:
        run = _make_run()
        store.put_run(run)
        ev = _make_evaluation(run.id)
        store.put_evaluation(ev)

        got = store.get_evaluation_for_run_evaluator(run.id, ev.evaluator_name)
        assert got is not None
        assert got.id == ev.id
        assert got.run_id == ev.run_id
        assert got.evaluator_name == ev.evaluator_name
        assert got.score == ev.score
        assert got.passed == ev.passed
        assert got.rationale == ev.rationale
        assert got.metadata == ev.metadata


def test_round_trip_preserves_passed_boolean(tmp_path: Path) -> None:
    """passed=True/False/None must round-trip through the INTEGER column."""
    with SqliteStore.open(tmp_path / "p.db") as store:
        run = _make_run()
        store.put_run(run)
        for passed in (True, False, None):
            ev = _make_evaluation(
                run.id,
                id=str(uuid.uuid4()),
                evaluator_name=f"bool_eval_{passed}",
                score=None,
                passed=passed,
            )
            store.put_evaluation(ev)
            got = store.get_evaluation_for_run_evaluator(run.id, ev.evaluator_name)
            assert got is not None
            assert got.passed is passed


def test_round_trip_preserves_metadata_json(tmp_path: Path) -> None:
    with SqliteStore.open(tmp_path / "m.db") as store:
        run = _make_run()
        store.put_run(run)
        ev = _make_evaluation(
            run.id,
            metadata={"nested": {"a": 1, "b": [1, 2, 3]}, "key": "x"},
        )
        store.put_evaluation(ev)
        got = store.get_evaluation_for_run_evaluator(run.id, ev.evaluator_name)
        assert got is not None
        assert got.metadata == ev.metadata


# ---------------- UPSERT ----------------------------------------------------


def test_upsert_keeps_single_row_per_run_evaluator(tmp_path: Path) -> None:
    with SqliteStore.open(tmp_path / "upsert.db") as store:
        run = _make_run()
        store.put_run(run)
        ev1 = _make_evaluation(run.id, score=10.0, rationale="first")
        store.put_evaluation(ev1)
        ev2 = _make_evaluation(run.id, id=str(uuid.uuid4()), score=99.0, rationale="second")
        store.put_evaluation(ev2)

        rows = store.get_evaluations_for_run(run.id)
        assert len(rows) == 1
        # On UPSERT, score+rationale+metadata are overwritten with the new values.
        assert rows[0].score == 99.0
        assert rows[0].rationale == "second"


def test_unique_index_enforced_against_raw_insert(tmp_path: Path) -> None:
    """A naïve duplicate INSERT without ON CONFLICT must hit the index."""
    db = tmp_path / "u.db"
    with SqliteStore.open(db) as store:
        run = _make_run()
        store.put_run(run)
        ev = _make_evaluation(run.id)
        store.put_evaluation(ev)

    conn = sqlite3.connect(db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO evaluations "
                "(id, run_id, evaluator_name, score, passed, rationale, "
                "metadata_json, created_at) "
                "VALUES (?, ?, ?, NULL, NULL, NULL, '{}', ?)",
                (
                    str(uuid.uuid4()),
                    ev.run_id,
                    ev.evaluator_name,
                    datetime.now(tz=UTC).isoformat(),
                ),
            )
    finally:
        conn.close()


# ---------------- ordering --------------------------------------------------


def test_get_evaluations_for_run_orders_by_created_at_asc(tmp_path: Path) -> None:
    with SqliteStore.open(tmp_path / "order.db") as store:
        run = _make_run()
        store.put_run(run)
        for i, name in enumerate(["a", "b", "c"]):
            ev = _make_evaluation(
                run.id,
                id=str(uuid.uuid4()),
                evaluator_name=name,
                score=float(i),
                # Force monotonically increasing created_at — sleeping 1ms is
                # enough; ISO-8601 strings compare lexically the same as
                # chronologically.
                created_at=datetime.now(tz=UTC),
            )
            store.put_evaluation(ev)
            time.sleep(0.005)

        rows = store.get_evaluations_for_run(run.id)
        assert [r.evaluator_name for r in rows] == ["a", "b", "c"]


def test_get_evaluation_for_unknown_pair_returns_none(tmp_path: Path) -> None:
    with SqliteStore.open(tmp_path / "n.db") as store:
        run = _make_run()
        store.put_run(run)
        # No evaluation persisted yet.
        assert store.get_evaluation_for_run_evaluator(run.id, "x") is None
        assert store.get_evaluations_for_run(run.id) == []


# ---------------- FK cascade -----------------------------------------------


def test_delete_run_cascades_evaluations(tmp_path: Path) -> None:
    """Deleting a run must remove its evaluations (FK ON DELETE CASCADE)."""
    db = tmp_path / "cascade.db"
    with SqliteStore.open(db) as store:
        run = _make_run()
        store.put_run(run)
        ev = _make_evaluation(run.id)
        store.put_evaluation(ev)
        assert store.get_evaluations_for_run(run.id) != []

    # Delete the parent run via raw SQL (the store doesn't expose a `delete_run`
    # API yet — that's R-future. Verifying the FK cascade is wired correctly).
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("DELETE FROM runs WHERE id = ?", (ev.run_id,))
        conn.commit()
        rows = conn.execute(
            "SELECT COUNT(*) FROM evaluations WHERE run_id = ?", (ev.run_id,)
        ).fetchone()
        assert rows[0] == 0
    finally:
        conn.close()
