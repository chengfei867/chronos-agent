"""Spike 2 — Fork from mid-graph checkpoint with a modified prompt.

Proves: given a completed run, we can
  (a) identify a specific intermediate step (e.g., after node 2 "research")
  (b) restore the state at that step on a NEW thread
  (c) modify the state (swap prompt / swap output)
  (d) re-execute downstream nodes (draft, review, finalize) under the new state
  (e) verify the final result DIFFERS from the original run

This is the core "fork" capability. If this works, Chronos v0.1 is viable.

Exit criterion: test passes; we show two different final outputs from same task.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

# Reuse the same graph shape from Spike 1
from tests.spikes.test_spike1_capture import AgentState, build_graph


@pytest.mark.spike
def test_spike2_fork_at_research_node() -> None:
    """Run once; fork after 'research' with an injected 'hijacked' research; re-run."""
    # Shared saver — both the original run and the fork live here, on different threads.
    saver = InMemorySaver()
    graph = build_graph().compile(checkpointer=saver)

    # --- Original run on thread-A ---
    config_a = {"configurable": {"thread_id": "spike2-orig"}}
    initial: AgentState = {
        "task": "Compose a tweet about chronos-agent.",
        "plan": "",
        "research": "",
        "draft": "",
        "review": "",
        "final": "",
        "log": [],
    }
    result_a = graph.invoke(initial, config_a)
    assert result_a["final"]
    final_a = result_a["final"]

    # --- Identify a mid-graph checkpoint on thread-A ---
    # We want the snapshot RIGHT AFTER 'research' ran, i.e., before 'draft' runs.
    history = list(graph.get_state_history(config_a))
    # history[0] is latest (post-finalize), history[-1] is earliest.
    # Find snapshot where next == ('draft',) — meaning 'research' done, 'draft' pending.
    fork_snapshot = next(
        (s for s in history if s.next == ("draft",)),
        None,
    )
    assert fork_snapshot is not None, (
        "could not find snapshot with next=('draft',); "
        f"available next states: {[s.next for s in history]}"
    )
    assert fork_snapshot.values["research"], "research field should be populated"
    assert not fork_snapshot.values["draft"], "draft field should still be empty"

    # --- Create fork: thread-B copies state from A at fork_snapshot, with edit ---
    # The edit: replace 'research' content with something different.
    config_b = {"configurable": {"thread_id": "spike2-fork"}}

    # Seed thread-B by writing a modified state as if it was the initial input.
    # In LangGraph 1.x we use update_state on the new thread with the fork values
    # then invoke with `None` (meaning: continue from current state).
    forked_state = dict(fork_snapshot.values)
    forked_state["research"] = "[HIJACKED] totally different research content"
    # Log: mark the fork point
    forked_state["log"] = [*fork_snapshot.values["log"], "FORK:research-hijacked"]

    # Update thread-B to have this state; `as_node` lets us pretend the state
    # was produced by 'research' so 'draft' is next.
    graph.update_state(config_b, forked_state, as_node="research")

    # Now invoke on thread-B with None input — it will resume from current state.
    result_b = graph.invoke(None, config_b)

    # --- Assertions ---
    assert result_b["final"], "forked run never completed"
    final_b = result_b["final"]

    assert final_a != final_b, (
        "forked run produced IDENTICAL final to original — fork had no effect!\n"
        f"  original: {final_a!r}\n"
        f"  forked:   {final_b!r}"
    )

    # The 'HIJACKED' injected content should propagate downstream via FakeLLM
    # (which hashes inputs). We expect the draft/review/final in B to have
    # DIFFERENT fingerprints than in A, because research was different.
    a_draft_fp = result_a["draft"].split(":")[1].split("]")[0]
    b_draft_fp = result_b["draft"].split(":")[1].split("]")[0]
    assert a_draft_fp != b_draft_fp, "draft fingerprints should differ after fork"

    # Log should show fork marker plus 3 new log entries (draft, review, finalize)
    b_log = result_b["log"]
    assert "FORK:research-hijacked" in b_log
    post_fork_log = b_log[b_log.index("FORK:research-hijacked") + 1 :]
    post_fork_nodes = [entry.split(":")[0] for entry in post_fork_log]
    assert post_fork_nodes == ["draft", "review", "finalize"], (
        f"expected draft→review→finalize re-execution, got {post_fork_nodes}"
    )

    print("\n✅ Spike 2 PASS — fork produced divergent output")
    print(f"   original final: {final_a!r}")
    print(f"   forked   final: {final_b!r}")
    print(f"   fork log: {b_log}")


@pytest.mark.spike
def test_spike2_fork_preserves_pre_fork_state() -> None:
    """Sanity: forked thread's history at the fork point shares values with source."""
    saver = InMemorySaver()
    graph = build_graph().compile(checkpointer=saver)

    config_a = {"configurable": {"thread_id": "spike2b-orig"}}
    graph.invoke(
        {
            "task": "X",
            "plan": "",
            "research": "",
            "draft": "",
            "review": "",
            "final": "",
            "log": [],
        },
        config_a,
    )
    hist_a = list(graph.get_state_history(config_a))
    fork_snap = next(s for s in hist_a if s.next == ("draft",))

    config_b = {"configurable": {"thread_id": "spike2b-fork"}}
    graph.update_state(config_b, dict(fork_snap.values), as_node="research")

    # Before we invoke B, its current state should have same plan/research as fork_snap
    b_state = graph.get_state(config_b)
    assert b_state.values["plan"] == fork_snap.values["plan"]
    assert b_state.values["research"] == fork_snap.values["research"]
    assert not b_state.values["draft"]
    print("\n✅ Spike 2b PASS — fork preserves pre-fork state fields")
