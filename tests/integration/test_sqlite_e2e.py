"""Integration test: LangGraph spike1 pipeline → SQLite → cross-process read.

This is the M1.3 exit criterion from docs/roadmap.md:

    An agent run can be fully captured to chronos.db and later reopened from
    a completely separate process, with every node, state, and usage field
    intact.

We invoke ``fixtures_writer.py`` in a subprocess to simulate the real
deployment topology (recorder writes, CLI/API reads from a *different*
process). Exec-boundary + file-backed WAL is the contract we actually ship.
"""

from __future__ import annotations

import itertools
import subprocess
import sys
from pathlib import Path

from chronos.core.models import NodeKind, RunStatus
from chronos.store import SqliteStore

WRITER = Path(__file__).with_name("fixtures_writer.py")


def test_spike1_pipeline_roundtrips_through_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "chronos.db"

    result = subprocess.run(
        [sys.executable, str(WRITER), str(db)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"writer subprocess failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    run_id = result.stdout.strip().splitlines()[-1]
    assert db.exists()

    # Parent process reads from scratch — no shared in-memory state
    with SqliteStore.open(db) as store:
        runs = store.list_runs()
        assert len(runs) == 1
        run = runs[0]
        assert run.id == run_id
        assert run.status is RunStatus.COMPLETED
        assert run.task_description == "write a haiku about rain"
        assert "task" in run.initial_state
        assert run.final_state is not None
        assert "final" in run.final_state  # polish produced the final poem

        nodes = store.get_nodes_for_run(run.id)
        assert len(nodes) == 5
        assert [n.node_name for n in nodes] == [
            "plan",
            "research",
            "draft",
            "critique",
            "polish",
        ]
        assert [n.step_index for n in nodes] == [0, 1, 2, 3, 4]
        assert all(n.kind is NodeKind.LLM for n in nodes)

        # Causal chain
        assert nodes[0].parent_node_id is None
        for prev, curr in itertools.pairwise(nodes):
            assert curr.parent_node_id == prev.id

        # State progressively accumulates across nodes (ADR-004 §Finding 4)
        assert "plan" in nodes[0].state_after
        assert "final" in nodes[4].state_after

        # Every node carries the langgraph checkpoint chain in metadata
        for n in nodes:
            assert n.metadata.get("checkpoint_id") is not None
            assert n.metadata.get("parent_checkpoint_id") is not None

        # NOTE (ADR-004): usage/model_name/cost are NOT populated by the v0.1
        # LangGraph adapter because StateSnapshot doesn't expose them. These
        # fields are reserved for M2 provider-specific spans. Users who want
        # them in v0.1 must embed usage dicts inside their graph state.
        assert all(n.usage is None for n in nodes)
        assert all(n.model_name is None for n in nodes)


def test_concurrent_readers_see_committed_writes(tmp_path: Path) -> None:
    """Two separate SqliteStore handles against the same file must see
    each other's committed writes (WAL journal mode should handle this)."""
    db = tmp_path / "concurrent.db"

    with SqliteStore.open(db) as writer:
        from chronos.core.models import Run

        run = Run(id="r1", adapter="x", adapter_thread_id="t")
        writer.put_run(run)

    with SqliteStore.open(db) as reader:
        assert reader.get_run("r1") is not None


def test_schema_info_survives_reopen(tmp_path: Path) -> None:
    """Reopening a DB many times must not drift schema_version or bloat schema_info."""
    db = tmp_path / "reopen.db"
    for _ in range(5):
        with SqliteStore.open(db) as s:
            assert s.schema_version == "0.1.0"

    import sqlite3

    raw = sqlite3.connect(db)
    (count,) = raw.execute("SELECT COUNT(*) FROM schema_info").fetchone()
    raw.close()
    assert count == 1
