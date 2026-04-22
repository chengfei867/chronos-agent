"""Unit tests for chronos.store.SqliteStore.

Covers: schema creation, migration idempotency, CRUD roundtrips, constraint
enforcement, cross-process read-after-write (new connection sees committed data).
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from chronos.core.models import (
    SCHEMA_VERSION,
    Fork,
    Node,
    NodeKind,
    Run,
    RunStatus,
    Usage,
)
from chronos.store import SchemaError, SqliteStore

UTC = UTC


# ---------- fixtures -------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    """Disk-backed store; tmp_path gives us a per-test fresh DB."""
    s = SqliteStore.open(tmp_path / "chronos.db")
    yield s
    s.close()


@pytest.fixture
def mem_store() -> SqliteStore:
    s = SqliteStore.open(":memory:")
    yield s
    s.close()


def _make_run(**overrides: object) -> Run:
    defaults: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "adapter": "langgraph",
        "adapter_thread_id": "t-" + uuid.uuid4().hex[:6],
    }
    defaults.update(overrides)
    return Run(**defaults)  # type: ignore[arg-type]


def _make_node(run_id: str, **overrides: object) -> Node:
    defaults: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "run_id": run_id,
        "step_index": 0,
        "node_name": "plan",
        "kind": NodeKind.LLM,
    }
    defaults.update(overrides)
    return Node(**defaults)  # type: ignore[arg-type]


# ---------- schema + migrations --------------------------------------------


def test_open_creates_schema(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    assert not db.exists()
    SqliteStore.open(db).close()
    assert db.exists()


def test_schema_version_matches_library(mem_store: SqliteStore) -> None:
    assert mem_store.schema_version == SCHEMA_VERSION


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    """Opening the same DB twice must not error or duplicate schema_info rows."""
    db = tmp_path / "idem.db"
    SqliteStore.open(db).close()
    SqliteStore.open(db).close()

    raw = sqlite3.connect(db)
    rows = raw.execute("SELECT COUNT(*) FROM schema_info").fetchone()
    raw.close()
    assert rows[0] == 1


def test_schema_version_mismatch_raises(tmp_path: Path) -> None:
    """A DB from a future major version must be rejected, not silently opened."""
    db = tmp_path / "future.db"
    SqliteStore.open(db).close()
    # Tamper: pretend DB was created by chronos 99.x
    raw = sqlite3.connect(db)
    raw.execute("UPDATE schema_info SET schema_version = '99.0.0' WHERE id = 1")
    raw.commit()
    raw.close()

    with pytest.raises(SchemaError, match="incompatible"):
        SqliteStore.open(db)


# ---------- Run CRUD -------------------------------------------------------


def test_put_and_get_run(mem_store: SqliteStore) -> None:
    run = _make_run(task_description="hello", tags=["a", "b"])
    mem_store.put_run(run)

    got = mem_store.get_run(run.id)
    assert got is not None
    assert got.id == run.id
    assert got.task_description == "hello"
    assert got.tags == ["a", "b"]
    assert got.status is RunStatus.PENDING


def test_get_run_missing_returns_none(mem_store: SqliteStore) -> None:
    assert mem_store.get_run("nonexistent") is None


def test_put_run_is_upsert(mem_store: SqliteStore) -> None:
    """Re-putting with same id should UPDATE, not duplicate."""
    run = _make_run()
    mem_store.put_run(run)

    run_v2 = run.model_copy(update={"status": RunStatus.COMPLETED})
    mem_store.put_run(run_v2)

    assert len(mem_store.list_runs()) == 1
    assert mem_store.get_run(run.id).status is RunStatus.COMPLETED


def test_list_runs_ordered_newest_first(mem_store: SqliteStore) -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    r1 = _make_run(started_at=t0)
    r2 = _make_run(started_at=t0 + timedelta(hours=1))
    r3 = _make_run(started_at=t0 + timedelta(hours=2))
    for r in (r1, r2, r3):
        mem_store.put_run(r)

    listed = mem_store.list_runs()
    assert [r.id for r in listed] == [r3.id, r2.id, r1.id]


def test_run_initial_and_final_state_roundtrip(mem_store: SqliteStore) -> None:
    run = _make_run(
        initial_state={"task": "write haiku", "log": []},
        final_state={"task": "write haiku", "result": "drip drip", "log": ["a", "b"]},
    )
    mem_store.put_run(run)
    got = mem_store.get_run(run.id)
    assert got.initial_state == {"task": "write haiku", "log": []}
    assert got.final_state["result"] == "drip drip"


# ---------- Node CRUD ------------------------------------------------------


def test_put_and_get_node(mem_store: SqliteStore) -> None:
    run = _make_run()
    mem_store.put_run(run)
    node = _make_node(
        run.id,
        step_index=3,
        node_name="research",
        kind=NodeKind.LLM,
        state_after={"research": "some text"},
        model_name="claude-opus-4.7",
        usage=Usage(prompt_tokens=100, completion_tokens=50),
        cost_usd_cents=42,
    )
    mem_store.put_node(node)

    got = mem_store.get_node(node.id)
    assert got is not None
    assert got.node_name == "research"
    assert got.state_after == {"research": "some text"}
    assert got.usage.prompt_tokens == 100
    assert got.cost_usd_cents == 42


def test_get_nodes_for_run_ordered_by_step_index(mem_store: SqliteStore) -> None:
    run = _make_run()
    mem_store.put_run(run)
    n2 = _make_node(run.id, step_index=2, node_name="draft")
    n0 = _make_node(run.id, step_index=0, node_name="plan")
    n1 = _make_node(run.id, step_index=1, node_name="research")
    for n in (n2, n0, n1):
        mem_store.put_node(n)

    ordered = mem_store.get_nodes_for_run(run.id)
    assert [n.node_name for n in ordered] == ["plan", "research", "draft"]


def test_node_foreign_key_enforced(mem_store: SqliteStore) -> None:
    """nodes.run_id must reference an existing run."""
    orphan = _make_node("no-such-run")
    with pytest.raises(sqlite3.IntegrityError):
        mem_store.put_node(orphan)


def test_node_cascade_delete_on_run(mem_store: SqliteStore) -> None:
    run = _make_run()
    mem_store.put_run(run)
    node = _make_node(run.id)
    mem_store.put_node(node)

    # Delete the run via raw connection
    mem_store._conn.execute("DELETE FROM runs WHERE id = ?", (run.id,))

    assert mem_store.get_node(node.id) is None


def test_node_kind_check_constraint(mem_store: SqliteStore) -> None:
    """Invalid kind bypassing pydantic must be rejected by SQL CHECK."""
    run = _make_run()
    mem_store.put_run(run)
    with pytest.raises(sqlite3.IntegrityError):
        mem_store._conn.execute(
            """INSERT INTO nodes (id, run_id, step_index, node_name, kind,
               started_at, state_after_json)
               VALUES (?, ?, 0, 'x', 'bogus_kind', '2026-01-01T00:00:00+00:00', '{}')""",
            (str(uuid.uuid4()), run.id),
        )


# ---------- Fork CRUD ------------------------------------------------------


def test_put_and_get_fork(mem_store: SqliteStore) -> None:
    run_a = _make_run()
    run_b = _make_run(status=RunStatus.FORKED)
    mem_store.put_run(run_a)
    mem_store.put_run(run_b)
    node_a = _make_node(run_a.id, step_index=2, node_name="research")
    mem_store.put_node(node_a)

    fork = Fork(
        id=str(uuid.uuid4()),
        parent_run_id=run_a.id,
        parent_node_id=node_a.id,
        child_run_id=run_b.id,
        edited_fields={"research": "[HIJACKED]"},
        reason="what if research went differently?",
    )
    mem_store.put_fork(fork)

    got = mem_store.get_fork(fork.id)
    assert got is not None
    assert got.edited_fields == {"research": "[HIJACKED]"}
    assert got.reason == "what if research went differently?"

    by_child = mem_store.get_fork_for_child(run_b.id)
    assert by_child is not None
    assert by_child.id == fork.id


def test_fork_unique_on_child(mem_store: SqliteStore) -> None:
    """Each child_run_id can be forked at most once."""
    run_a = _make_run()
    run_b = _make_run()
    mem_store.put_run(run_a)
    mem_store.put_run(run_b)
    node_a = _make_node(run_a.id)
    mem_store.put_node(node_a)

    f1 = Fork(
        id=str(uuid.uuid4()),
        parent_run_id=run_a.id,
        parent_node_id=node_a.id,
        child_run_id=run_b.id,
    )
    f2 = Fork(
        id=str(uuid.uuid4()),
        parent_run_id=run_a.id,
        parent_node_id=node_a.id,
        child_run_id=run_b.id,
    )
    mem_store.put_fork(f1)
    with pytest.raises(sqlite3.IntegrityError):
        mem_store.put_fork(f2)


# ---------- Transactions ---------------------------------------------------


def test_transaction_rolls_back_on_exception(tmp_path: Path) -> None:
    db = tmp_path / "tx.db"
    with SqliteStore.open(db) as store:
        run = _make_run()
        with pytest.raises(RuntimeError, match="boom"), store.transaction():
            store.put_run(run)
            raise RuntimeError("boom")
        assert store.get_run(run.id) is None


def test_transaction_commits_on_success(tmp_path: Path) -> None:
    db = tmp_path / "tx_ok.db"
    with SqliteStore.open(db) as store:
        run = _make_run()
        with store.transaction():
            store.put_run(run)
        assert store.get_run(run.id) is not None


# ---------- Cross-process persistence --------------------------------------


def test_data_persists_across_store_instances(tmp_path: Path) -> None:
    """Write in one Store, close, open fresh Store → data still there.

    This simulates the cross-process case that M1.3's exit criterion
    demands: process A records, process B reads.
    """
    db = tmp_path / "persist.db"
    run = _make_run(task_description="persisted")
    node = _make_node(run.id, node_name="plan", step_index=0)

    with SqliteStore.open(db) as store_a:
        store_a.put_run(run)
        store_a.put_node(node)

    # Entirely new connection
    with SqliteStore.open(db) as store_b:
        got_run = store_b.get_run(run.id)
        got_nodes = store_b.get_nodes_for_run(run.id)
        assert got_run is not None
        assert got_run.task_description == "persisted"
        assert len(got_nodes) == 1
        assert got_nodes[0].node_name == "plan"


# ---------- Context manager ------------------------------------------------


def test_store_usable_as_context_manager(tmp_path: Path) -> None:
    db = tmp_path / "cm.db"
    with SqliteStore.open(db) as s:
        assert s.schema_version == SCHEMA_VERSION
    # After close, new connection still works
    with SqliteStore.open(db) as s2:
        assert s2.list_runs() == []
