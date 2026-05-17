"""R81: TDD scaffold for ADR-026 §5.3 (slice 3c — fork-with-tool-result-substitution).

Four-test scaffold mirroring the R79 §5.2 / R80 slice 3b pattern, but
exercising the *result-side* override surface.  §5.3 is the symmetric
mirror of §5.2: where §5.2 rewrites the tool *input* the agent asks
with, §5.3 rewrites the tool *result* the agent gets back — replaying
the agent's reasoning under a hypothetical tool output without
re-invoking the real tool.

Strict-xfail makes R82 a forcing function: when the implementation
lands, every xfail test flips to passing → strict-xfail trips →
R82 round agent removes the markers as part of the same commit.

Test plan (mirrors ADR-026 §5.3 #### Test enforcement):

1. ``test_fork_without_result_overrides_is_identity`` —
   ``tool_result_overrides=None`` and ``={}`` produce a child run
   byte-identical to R74 / R80 fork().  **EXPECTED PASS** on R81 (sanity
   guard; R81 ships a no-op pass-through that falls through to the
   existing identity path).
2. ``test_fork_with_result_override_changes_downstream_result`` —
   overriding a single ``tool_use_id`` rewrites
   ``state_after['tool_result_content']`` on the child Node while
   preserving ``state_after['tool_use_id']``.  **xfail strict (R82)**.
3. ``test_fork_with_result_override_of_unknown_id_raises`` — overriding
   an id absent from the parent's *result-side* keyset raises
   ``AdapterError`` *before* the SDK call (validation #2).  **xfail
   strict (R82)**.
4. ``test_fork_with_result_override_collides_with_input_override_raises``
   — same id present in both ``tool_input_overrides`` and
   ``tool_result_overrides`` raises ``AdapterError`` (validation #3, no
   double-substitution).  **xfail strict (R82)** — currently raises
   ``NotImplementedError`` from the R81 pass-through, not
   ``AdapterError``; flips on R82 validation impl.

R81 ALSO extends ``recorder.fork()`` with a ``tool_result_overrides``
no-op pass-through kwarg so these tests fail with
``NotImplementedError`` rather than ``TypeError: unexpected keyword
argument`` — narrowing R82's diff to a single function body.

Honors R75 writer-side redundancy invariant: each test drives a live
``recorder.record()`` parent run rather than hand-crafting Node rows.

NOTE on stub helpers: this is the FOURTH test file replicating the
duck-typed ``StubBlock`` / ``StubMessage`` / ``aiter_messages`` pattern.  Per
the R58 / R78 convention, the threshold for extracting these to
``tests/unit/fixtures/anthropic_agents.py`` is **three duplications** —
already exceeded.  R81 deliberately defers extraction once more (TDD
round should not also do a cross-file refactor); R82 (or a follow-up
defensive round) MUST extract.  Tracked as next-round defensive TODO.
"""

from __future__ import annotations

import sys
import types as _types
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from chronos.adapters.anthropic_agents import AnthropicAgentsRecorder
from chronos.adapters.protocols import AdapterError
from chronos.core.models import RunStatus
from chronos.store.sqlite import SqliteStore
from tests.unit.fixtures.anthropic_agents_stubs import (
    AssistantMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    aiter_messages,
)


@dataclass
class _FakeClient:
    """Minimal ClaudeSDKClient-shape exposing ``receive_messages()``."""

    messages: list[Any] = field(default_factory=list)

    def receive_messages(self) -> AsyncIterator[Any]:
        return aiter_messages(self.messages)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Any) -> SqliteStore:
    return SqliteStore.open(tmp_path / "chronos.db")


@pytest.fixture
def recorder(store: SqliteStore) -> AnthropicAgentsRecorder:
    return AnthropicAgentsRecorder(store)


@pytest.fixture
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Install a fake ``claude_agent_sdk`` module exposing ``fork_session``."""
    captured: dict[str, Any] = {"next_session_id": "child-sdk-sid-r81-0001"}

    @dataclass
    class _FakeForkResult:
        session_id: str

    def _fake_fork_session(
        session_id: str,
        *,
        up_to_message_id: str | None = None,
        title: str | None = None,
        directory: str | None = None,
    ) -> _FakeForkResult:
        captured["session_id"] = session_id
        captured["up_to_message_id"] = up_to_message_id
        captured["title"] = title
        return _FakeForkResult(session_id=captured["next_session_id"])

    fake = _types.ModuleType("claude_agent_sdk")
    fake.fork_session = _fake_fork_session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake)
    return captured


# ---------------------------------------------------------------------------
# Helpers — record a parent run carrying a closed tool round-trip
# ---------------------------------------------------------------------------


_PARENT_UUID = "11111111-1111-1111-1111-111111111111"
_PARENT_SDK_SID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_TU_ID = "tu_t1_closed"


def _record_parent_with_closed_tool_pair(
    recorder: AnthropicAgentsRecorder,
    *,
    thread_id: str = "thread-parent-r81",
) -> tuple[str, str]:
    """Drive ``recorder.record()`` with a 3-message closed tool round-trip.

    Stream shape (single-block §5.1):

    1. AssistantMessage(ToolUseBlock id="tu_t1_closed", input={"x": 1})
    2. UserMessage(ToolResultBlock tool_use_id="tu_t1_closed", content="ok")
    3. AssistantMessage(TextBlock text="done")  ← carries uuid+sid for fork

    Returns ``(parent_run_id, parent_at_node_id)`` where ``at_node_id``
    is the final AssistantMessage Node (the canonical fork seed).
    """
    asst_use = AssistantMessage(
        content=[
            ToolUseBlock(id=_TU_ID, name="search", input={"x": 1}),
        ],
        model="Claude Sonnet 4.6",
        uuid="aaaa1111-1111-1111-1111-111111111111",
        session_id=_PARENT_SDK_SID,
    )
    user_result = UserMessage(
        content=[
            ToolResultBlock(tool_use_id=_TU_ID, content="ok"),
        ],
        uuid="bbbb2222-2222-2222-2222-222222222222",
        session_id=_PARENT_SDK_SID,
    )
    asst_final = AssistantMessage(
        content=[TextBlock(text="done")],
        model="Claude Sonnet 4.6",
        uuid=_PARENT_UUID,
        session_id=_PARENT_SDK_SID,
    )
    runtime = _FakeClient(messages=[asst_use, user_result, asst_final])
    with recorder.record(runtime, thread_id=thread_id) as ref:
        pass
    assert ref.run_id is not None
    assert len(ref.node_ids) == 3
    return ref.run_id, ref.node_ids[-1]


def _drive_child_branch(
    recorder: AnthropicAgentsRecorder,
    parent_run_id: str,
    at_node_id: str,
    *,
    tool_input_overrides: dict[str, dict[str, Any]] | None = None,
    tool_result_overrides: dict[str, Any] | None = None,
    child_sdk_sid: str = "child-sdk-sid-r81-0001",
    overridden_tool_use_id: str = _TU_ID,
    thread_id: str = "thread-child-r81",
) -> Any:
    """Run the child branch through ``recorder.fork()`` with the given overrides.

    The child stream contains a UserMessage carrying a ``ToolResultBlock``
    so the §5.3 result-side stamp has a target Node to land on.  Mirrors
    the parent's closed-round-trip shape.
    """
    child_user_result = UserMessage(
        content=[
            ToolResultBlock(tool_use_id=overridden_tool_use_id, content="ok"),
        ],
        uuid="dddd4444-4444-4444-4444-444444444444",
        session_id=child_sdk_sid,
    )
    child_asst_final = AssistantMessage(
        content=[TextBlock(text="child done")],
        model="Claude Sonnet 4.6",
        uuid="cccc3333-3333-3333-3333-333333333333",
        session_id=child_sdk_sid,
    )
    child_runtime = _FakeClient(messages=[child_user_result, child_asst_final])
    with recorder.fork(
        runtime=None,
        parent_run_id=parent_run_id,
        at_node_id=at_node_id,
        child_thread_id=thread_id,
        reason="slice 3c xfail probe",
        overrides={},
        tool_input_overrides=tool_input_overrides,
        tool_result_overrides=tool_result_overrides,
    ) as fref:
        fref.submit_runtime(child_runtime)  # type: ignore[attr-defined]
    return fref


# ---------------------------------------------------------------------------
# Test 1 — identity (None / {} default).  EXPECTED PASS in R81.
# The no-op pass-through accepts the kwarg and falls through to R74/R80
# fork semantics when the mapping is empty/None.  Guards R82 against
# regressing the identity contract.
# ---------------------------------------------------------------------------


def test_fork_without_result_overrides_is_identity(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
    fake_sdk: dict[str, Any],
) -> None:
    """``tool_result_overrides=None`` and ``={}`` are identity forks.

    R74/R80 fork() semantics MUST be preserved when the new R82 kwarg is
    absent or empty.  Both invocations should:

    - succeed without raising,
    - produce a child Run in ``RunStatus.COMPLETED``,
    - leave the child's ``state_after['tool_result_content']`` ABSENT
      (not stamped) on the UserMessage Node carrying the
      ``ToolResultBlock`` — i.e. no §5.3 surface side-effect.
    """
    parent_run_id, at_node_id = _record_parent_with_closed_tool_pair(recorder)

    # 1a. tool_result_overrides=None is identity
    fake_sdk["next_session_id"] = "child-sdk-sid-r81-none-0001"
    fref_none = _drive_child_branch(
        recorder,
        parent_run_id,
        at_node_id,
        tool_result_overrides=None,
        child_sdk_sid="child-sdk-sid-r81-none-0001",
        thread_id="thread-child-r81-none",
    )
    assert fref_none.child_run_id is not None
    child_run_none = store.get_run(fref_none.child_run_id)
    assert child_run_none is not None
    assert child_run_none.status == RunStatus.COMPLETED

    # 1b. tool_result_overrides={} is also identity
    fake_sdk["next_session_id"] = "child-sdk-sid-r81-empty-0002"
    fref_empty = _drive_child_branch(
        recorder,
        parent_run_id,
        at_node_id,
        tool_result_overrides={},
        child_sdk_sid="child-sdk-sid-r81-empty-0002",
        thread_id="thread-child-r81-empty",
    )
    assert fref_empty.child_run_id is not None
    child_run_empty = store.get_run(fref_empty.child_run_id)
    assert child_run_empty is not None
    assert child_run_empty.status == RunStatus.COMPLETED

    # In both cases, no §5.3 side-effect on child Node state_after.
    for fref in (fref_none, fref_empty):
        for nid in fref.node_ids:
            node = store.get_node(nid)
            assert node is not None
            sa = node.state_after or {}
            assert "tool_result_content" not in sa
            assert "tool_result_contents" not in sa


# ---------------------------------------------------------------------------
# Test 2 — non-empty override rewrites downstream tool_result_content
# ---------------------------------------------------------------------------


def test_fork_with_result_override_changes_downstream_result(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
    fake_sdk: dict[str, Any],
) -> None:
    """Substitute ``tool_use_id="tu_t1_closed"`` → ``content="rewritten"``.

    Expected child-side state per ADR-026 §5.3 #### Child-side stamp:

    - ``state_after['tool_use_id'] == "tu_t1_closed"`` (UNCHANGED — JOIN
      anchor binding contract preserved across fork).
    - ``state_after['tool_result_content'] == "rewritten"`` (NEW —
      substitution stamp; absent on Nodes that did not have their
      result rewritten).
    """
    parent_run_id, at_node_id = _record_parent_with_closed_tool_pair(recorder)

    fref = _drive_child_branch(
        recorder,
        parent_run_id,
        at_node_id,
        tool_result_overrides={_TU_ID: "rewritten"},
    )
    assert fref.child_run_id is not None

    # Find the child UserMessage Node carrying the overridden ToolResultBlock.
    overridden = None
    for nid in fref.node_ids:
        node = store.get_node(nid)
        if node is None:
            continue
        sa = node.state_after or {}
        if sa.get("tool_use_id") == _TU_ID and "tool_result_content" in sa:
            overridden = node
            break

    assert overridden is not None, (
        "Expected a child Node with state_after['tool_use_id']==tu_t1_closed "
        "AND state_after['tool_result_content'] populated"
    )
    sa = overridden.state_after or {}
    # JOIN anchor preserved
    assert sa.get("tool_use_id") == _TU_ID
    # New §5.3 stamp surfaces the substituted result content
    assert sa.get("tool_result_content") == "rewritten"


# ---------------------------------------------------------------------------
# Test 3 — unknown id raises BEFORE SDK call (validation #2)
# ---------------------------------------------------------------------------


def test_fork_with_result_override_of_unknown_id_raises(
    recorder: AnthropicAgentsRecorder,
    fake_sdk: dict[str, Any],
) -> None:
    """``tool_result_overrides={"<bogus>": ...}`` raises ``AdapterError``.

    The bogus key does not appear in the parent's result-side keyset
    (no UserMessage carries a ToolResultBlock with this tool_use_id), so
    R82's validation #2 must reject it BEFORE invoking the SDK
    fork_session.  ``AdapterError`` is the contract — TypeError /
    KeyError / NotImplementedError fail this test.
    """
    parent_run_id, at_node_id = _record_parent_with_closed_tool_pair(recorder)

    bogus_id = "tu_does_not_exist_anywhere"
    with pytest.raises(AdapterError, match="result-side"):
        _drive_child_branch(
            recorder,
            parent_run_id,
            at_node_id,
            tool_result_overrides={bogus_id: "rewritten"},
        )

    # SDK fork_session must NOT have been called when validation rejects.
    assert "session_id" not in fake_sdk, (
        "fork_session should not have run when tool_result_overrides "
        "contains an unknown id (validation must precede SDK call)"
    )


# ---------------------------------------------------------------------------
# Test 4 — collision with tool_input_overrides raises (validation #3)
# ---------------------------------------------------------------------------


def test_fork_with_result_override_collides_with_input_override_raises(
    recorder: AnthropicAgentsRecorder,
    fake_sdk: dict[str, Any],
) -> None:
    """Same ``tool_use_id`` in both override mappings raises ``AdapterError``.

    Per ADR-026 §5.3 validation #3 (no double-substitution): rewriting
    both the input AND the result of the same tool round-trip is
    contradictory — rewriting the input implies the agent re-asks the
    tool with new input; rewriting the result implies the tool was
    never re-invoked.  ``AdapterError`` is the contract.
    """
    parent_run_id, at_node_id = _record_parent_with_closed_tool_pair(recorder)

    with pytest.raises(AdapterError, match=_TU_ID):
        _drive_child_branch(
            recorder,
            parent_run_id,
            at_node_id,
            tool_input_overrides={_TU_ID: {"x": 99}},
            tool_result_overrides={_TU_ID: "rewritten"},
        )

    # SDK fork_session must NOT have been called when validation rejects.
    assert "session_id" not in fake_sdk, (
        "fork_session should not have run when input/result overrides "
        "collide on the same tool_use_id (validation must precede SDK call)"
    )
