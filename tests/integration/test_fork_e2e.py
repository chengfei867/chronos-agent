"""Integration test: end-to-end fork via real LangGraph + SQLite + subprocess.

Mirrors the parent-run e2e test pattern: a subprocess writes parent +
fork, we read both back from a fresh handle in the main process.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from chronos.core.models import RunStatus
from chronos.store import SqliteStore

WRITER = Path(__file__).with_name("fork_writer.py")


def test_fork_roundtrips_through_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "fork.db"

    result = subprocess.run(
        [sys.executable, str(WRITER), str(db)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"writer subprocess failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    line = result.stdout.strip().splitlines()[-1]
    parent_id, child_id, fork_id, final_a_snip, final_b_snip = line.split("|")

    # The two final outputs must differ (fork had an effect)
    assert final_a_snip != final_b_snip, "fork produced identical output to parent"

    # --- Fresh handle, fresh process-local reads ---
    with SqliteStore.open(db) as store:
        runs = store.list_runs()
        # Two runs: parent and child
        run_ids = {r.id for r in runs}
        assert parent_id in run_ids
        assert child_id in run_ids
        assert len(runs) == 2

        parent = store.get_run(parent_id)
        child = store.get_run(child_id)
        assert parent.status is RunStatus.COMPLETED
        assert child.status is RunStatus.COMPLETED
        assert child.adapter_thread_id == "fork-t"
        assert parent.adapter_thread_id == "parent-t"

        # Child Run carries lineage metadata
        assert child.metadata["forked_from_run"] == parent_id
        assert child.metadata["overrides_keys"] == ["research"]
        assert "fork" in child.tags
        assert "fork-e2e" in child.tags

        # Child's initial_state holds the seeded (override-applied) research value
        assert child.initial_state["research"].startswith("[FORKED]")

        # --- Node structure of child ---
        parent_nodes = store.get_nodes_for_run(parent_id)
        child_nodes = store.get_nodes_for_run(child_id)
        assert [n.node_name for n in parent_nodes] == [
            "plan",
            "research",
            "draft",
            "critique",
            "polish",
        ]
        # Child re-executed everything AFTER research
        assert [n.node_name for n in child_nodes] == ["draft", "critique", "polish"]
        research_node = next(n for n in parent_nodes if n.node_name == "research")
        # First child node points back to the parent Research node (cross-run pointer)
        assert child_nodes[0].parent_node_id == research_node.id
        # Subsequent: local chain
        assert child_nodes[1].parent_node_id == child_nodes[0].id
        assert child_nodes[2].parent_node_id == child_nodes[1].id
        # step_index continues from parent research's step (= 1) + 1 = 2
        assert [n.step_index for n in child_nodes] == [2, 3, 4]

        # --- Fork record ---
        fork = store.get_fork(fork_id)
        assert fork is not None
        assert fork.parent_run_id == parent_id
        assert fork.child_run_id == child_id
        assert fork.parent_node_id == research_node.id
        assert fork.edited_fields == {
            "research": "[FORKED] totally different research content"
        }
        assert fork.reason == "e2e-test fork at research"

        # Reverse lookup: find fork by child
        fork_by_child = store.get_fork_for_child(child_id)
        assert fork_by_child is not None
        assert fork_by_child.id == fork_id

        # Divergent state: child's final_state differs from parent's in draft/final
        assert parent.final_state["final"] != child.final_state["final"]
        assert parent.final_state["draft"] != child.final_state["draft"]
