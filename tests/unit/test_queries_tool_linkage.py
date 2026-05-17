"""Unit tests for ``chronos.queries.tool_linkage`` (R78, slice 3a-P2).

Tests the orphan-detection helpers that surface the "consumer-side"
view of ADR-026 §5.1's fourth contract clause (orphan tolerance).

Tests intentionally drive the live :meth:`AnthropicAgentsRecorder.record`
pipeline rather than hand-crafting Node objects — this honors the R75
writer-side redundancy invariant (any future narrowing of the
metadata-stamping loop fails loud here, not silently in production).

Test plan (4 tests):

1. ``test_unmatched_tool_results_finds_orphan_only`` — a stream with
   one matched pair + one orphan result; helper returns just the
   orphan.
2. ``test_unmatched_tool_results_empty_when_all_matched`` — fully
   matched streams (single-block + multi-block) return ``[]``.
3. ``test_unmatched_tool_uses_symmetric`` — symmetric mirror: an
   AssistantMessage(ToolUseBlock) with no matching ToolResultBlock is
   surfaced by ``unmatched_tool_uses``.
4. ``test_helpers_handle_multi_block_keyset`` — orphan detection
   honors both single-block (``tool_use_id``) and multi-block
   (``tool_use_ids``) keysets in the same run, mixed.
"""

from __future__ import annotations

from typing import Any

import pytest

from chronos.adapters.anthropic_agents import AnthropicAgentsRecorder
from chronos.queries import unmatched_tool_results, unmatched_tool_uses
from chronos.store.sqlite import SqliteStore
from tests.unit.fixtures.anthropic_agents_stubs import (
    AssistantMessage,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    aiter_messages,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Any) -> SqliteStore:
    return SqliteStore.open(tmp_path / "chronos.db")


@pytest.fixture
def recorder(store: SqliteStore) -> AnthropicAgentsRecorder:
    return AnthropicAgentsRecorder(store)


# ---------------------------------------------------------------------------
# 1. unmatched_tool_results — returns only orphan result Nodes
# ---------------------------------------------------------------------------


def test_unmatched_tool_results_finds_orphan_only(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    """ADR-026 §5.1 fourth clause (R76): an orphan ToolResultBlock (no
    matching prior ToolUseBlock in the same run) is tolerated by
    record() and surfaced by ``unmatched_tool_results``. A matched pair
    in the same run is NOT surfaced.
    """
    matched_id = "toolu_matched"
    orphan_id = "toolu_orphan"
    messages = [
        UserMessage(content="please run pwd"),
        AssistantMessage(
            content=[ToolUseBlock(id=matched_id, name="bash", input={"cmd": "pwd"})],
            model="claude-sonnet-4-5",
        ),
        UserMessage(
            content=[
                ToolResultBlock(tool_use_id=matched_id, content={"stdout": "/h\n"}),
            ],
        ),
        # Orphan: tool_use_id refers to a ToolUseBlock we never observed
        # (resumed-session entry simulation).
        UserMessage(
            content=[
                ToolResultBlock(tool_use_id=orphan_id, content={"stdout": "?\n"}),
            ],
        ),
    ]
    with recorder.record(aiter_messages(messages), thread_id="t-orphan-only") as ref:
        pass

    orphans = unmatched_tool_results(store, ref.run_id)
    assert len(orphans) == 1, f"expected 1 orphan, got {len(orphans)}"
    orphan_node = orphans[0]
    assert orphan_node.node_name == "UserMessage"
    assert orphan_node.state_after.get("tool_use_id") == orphan_id


# ---------------------------------------------------------------------------
# 2. unmatched_tool_results — empty when fully matched
# ---------------------------------------------------------------------------


def test_unmatched_tool_results_empty_when_all_matched(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    """A run with every ToolResultBlock cleanly paired (single-block +
    multi-block both honored) returns an empty list."""
    single_id = "toolu_single"
    multi_ids = ["toolu_m1", "toolu_m2"]
    messages = [
        UserMessage(content="single command"),
        AssistantMessage(
            content=[ToolUseBlock(id=single_id, name="bash", input={"cmd": "id"})],
            model="claude-sonnet-4-5",
        ),
        UserMessage(content=[ToolResultBlock(tool_use_id=single_id, content={"stdout": ""})]),
        UserMessage(content="batch please"),
        AssistantMessage(
            content=[
                ToolUseBlock(id=multi_ids[0], name="bash", input={"cmd": "pwd"}),
                ToolUseBlock(id=multi_ids[1], name="bash", input={"cmd": "ls"}),
            ],
            model="claude-sonnet-4-5",
        ),
        UserMessage(
            content=[
                ToolResultBlock(tool_use_id=multi_ids[0], content={"stdout": "/h\n"}),
                ToolResultBlock(tool_use_id=multi_ids[1], content={"stdout": "a\n"}),
            ],
        ),
    ]
    with recorder.record(aiter_messages(messages), thread_id="t-all-matched") as ref:
        pass

    assert unmatched_tool_results(store, ref.run_id) == []
    # And no use-side orphans either.
    assert unmatched_tool_uses(store, ref.run_id) == []


# ---------------------------------------------------------------------------
# 3. unmatched_tool_uses — symmetric mirror (use without matching result)
# ---------------------------------------------------------------------------


def test_unmatched_tool_uses_symmetric(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    """An AssistantMessage(ToolUseBlock) whose tool_use_id has no matching
    ToolResultBlock in the same run is surfaced by
    ``unmatched_tool_uses`` — the symmetric mirror of
    ``unmatched_tool_results``. This is the slice-3b time-travel
    scenario: fork rewinds before the result arrived."""
    answered_id = "toolu_answered"
    pending_id = "toolu_pending"
    messages = [
        UserMessage(content="run two commands"),
        AssistantMessage(
            content=[
                ToolUseBlock(id=answered_id, name="bash", input={"cmd": "pwd"}),
            ],
            model="claude-sonnet-4-5",
        ),
        UserMessage(
            content=[ToolResultBlock(tool_use_id=answered_id, content={"stdout": "/h\n"})],
        ),
        # Pending: tool use with no matching result (run cuts off here).
        AssistantMessage(
            content=[
                ToolUseBlock(id=pending_id, name="bash", input={"cmd": "sleep 99"}),
            ],
            model="claude-sonnet-4-5",
        ),
    ]
    with recorder.record(aiter_messages(messages), thread_id="t-pending-use") as ref:
        pass

    pending = unmatched_tool_uses(store, ref.run_id)
    assert len(pending) == 1
    assert pending[0].state_after.get("tool_use_id") == pending_id
    # The matched use is NOT surfaced.
    assert all(n.state_after.get("tool_use_id") != answered_id for n in pending)
    # And the answered side has no result-side orphans.
    assert unmatched_tool_results(store, ref.run_id) == []


# ---------------------------------------------------------------------------
# 4. Both helpers honor multi-block keyset (tool_use_ids)
# ---------------------------------------------------------------------------


def test_helpers_handle_multi_block_keyset(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    """Orphan detection honors the multi-block (``tool_use_ids``)
    keyset (ADR-026 §5.1.1). A multi-block result Node that is *partially*
    matched (one id matches, one doesn't) is surfaced as an orphan —
    any unmatched element triggers detection. Symmetric on the
    use side."""
    matched_id = "toolu_m_match"
    orphan_id = "toolu_m_orphan"
    messages = [
        # Single-block use (only the matched id has a use anchor in this
        # run; the orphan id will refer to a use we never observe).
        UserMessage(content="hi"),
        AssistantMessage(
            content=[
                ToolUseBlock(id=matched_id, name="bash", input={"cmd": "pwd"}),
            ],
            model="claude-sonnet-4-5",
        ),
        # Multi-block result Node carrying BOTH the matched id and the
        # orphan id. Per ADR-026 §5.1.1 mutual exclusivity, this Node
        # gets state_after['tool_use_ids'] (plural). Any unmatched
        # element makes the whole Node an orphan.
        UserMessage(
            content=[
                ToolResultBlock(tool_use_id=matched_id, content={"stdout": "/h\n"}),
                ToolResultBlock(tool_use_id=orphan_id, content={"stdout": "?\n"}),
            ],
        ),
    ]
    with recorder.record(aiter_messages(messages), thread_id="t-multi-orphan") as ref:
        pass

    orphans = unmatched_tool_results(store, ref.run_id)
    assert len(orphans) == 1
    orphan_node = orphans[0]
    # The Node carries the plural keyset (multi-block contract).
    assert "tool_use_ids" in orphan_node.state_after
    assert orphan_node.state_after["tool_use_ids"] == [matched_id, orphan_id]
    # Singular must NOT be set on multi-block Node (binding mutual exclusivity).
    assert "tool_use_id" not in orphan_node.state_after
