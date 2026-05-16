"""R79: TDD scaffold for ADR-026 §5.2 (slice 3b — fork-with-tool-substitution).

Four ``pytest.mark.xfail(strict=True)`` tests describing the
``fork(..., tool_input_overrides=...)`` semantics that R80 will
implement. Strict-xfail makes R80 a forcing function: when the
implementation lands, every test flips to passing → strict-xfail trips
→ R80 round agent removes the markers as part of the same commit.

Test plan (mirrors ADR-026 §5.2 #### Test enforcement section):

1. ``test_fork_without_overrides_is_identity`` — ``tool_input_overrides=
   None`` and ``={}`` produce a child run byte-identical to R74 fork().
   **EXPECTED PASS** (sanity guard; ships green on R79 because the no-op
   pass-through falls through to the R74 verbatim fork path).
2. ``test_fork_with_override_changes_downstream_input`` — overriding a
   single ``tool_use_id`` rewrites ``state_after['tool_input']`` on the
   child Node while preserving ``state_after['tool_use_id']``. **xfail
   strict** — fails until R80 ships.
3. ``test_fork_with_override_of_unknown_id_raises`` — overriding an id
   absent from the parent's use-side keyset raises ``AdapterError``
   *before* the SDK call (validation #2). **xfail strict** — currently
   raises ``NotImplementedError`` from the R79 pass-through, not
   ``AdapterError``; flips on R80 validation impl.
4. ``test_fork_with_override_of_orphan_use_id_raises`` — overriding an
   id returned by ``unmatched_tool_uses(store, parent_run_id)`` raises
   ``AdapterError`` (validation #3, slice-3a→3b coupling). **xfail
   strict** — same shape as #3.

R79 ALSO optionally extends ``recorder.fork()`` with a no-op pass-through
kwarg so these tests fail with ``NotImplementedError`` rather than
``TypeError: unexpected keyword argument`` — narrowing R80's diff to a
single function body. See R79 progress doc for the decision.

Honors R75 writer-side redundancy invariant: each test drives a live
``recorder.record()`` parent run rather than hand-crafting Node rows.
This means any silent narrowing of ``recorder.py:_translate``'s
metadata-stamp loop trips here too.

NOTE on stub helpers: this is the THIRD test file replicating the
duck-typed ``_StubBlock`` / ``_StubMessage`` / ``_aiter`` pattern (after
``test_adapter_anthropic_agents.py`` and ``test_queries_tool_linkage.py``).
Per the R58 / R78 convention, the threshold for extracting these to
``tests/unit/fixtures/anthropic_agents.py`` is **three duplications**.
R79 inlines them once more (deliberate scope discipline — TDD round
should not also do a cross-file refactor); R80 (or a follow-up
defensive round) MUST extract.
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
from chronos.queries import unmatched_tool_uses
from chronos.store.sqlite import SqliteStore

# ---------------------------------------------------------------------------
# Stub message / block builders — duck-typed (no claude_agent_sdk import).
# Class name drives the recorder's kind dispatch (mirrors CrewAI ADR-021).
# ---------------------------------------------------------------------------


@dataclass
class _StubBlock:
    text: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None
    id: str | None = None
    tool_use_id: str | None = None
    content: Any = None


class TextBlock(_StubBlock):
    pass


class ToolUseBlock(_StubBlock):
    pass


class ToolResultBlock(_StubBlock):
    pass


@dataclass
class _StubMessage:
    content: Any = None
    usage: Any = None
    model: str | None = None
    stop_reason: str | None = None
    total_cost_usd: float | None = None
    duration_ms: int | None = None
    uuid: str | None = None
    session_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class UserMessage(_StubMessage):
    pass


class AssistantMessage(_StubMessage):
    pass


def _aiter(messages: list[_StubMessage]) -> AsyncIterator[_StubMessage]:
    async def _gen() -> AsyncIterator[_StubMessage]:
        for m in messages:
            yield m

    return _gen()


@dataclass
class _FakeClient:
    """Minimal ClaudeSDKClient-shape exposing ``receive_messages()``."""

    messages: list[Any] = field(default_factory=list)

    def receive_messages(self) -> AsyncIterator[Any]:
        return _aiter(self.messages)


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
    """Install a fake ``claude_agent_sdk`` module exposing ``fork_session``.

    Returns a ``captured`` dict that the test can inspect to verify
    fork_session args, and a ``next_session_id`` slot the test can set
    to control the child SDK session id.
    """
    captured: dict[str, Any] = {"next_session_id": "child-sdk-sid-0001"}

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
    thread_id: str = "thread-parent",
) -> tuple[str, str]:
    """Drive ``recorder.record()`` with a 3-message closed tool round-trip.

    Stream shape (single-block §5.1):

    1. AssistantMessage(ToolUseBlock id="tu_t1_closed", input={"x": 1})
    2. UserMessage(ToolResultBlock tool_use_id="tu_t1_closed", content="ok")
    3. AssistantMessage(TextBlock text="done")  ← carries uuid+sid for fork

    Returns ``(parent_run_id, parent_at_node_id)`` where ``at_node_id``
    is the final AssistantMessage Node (the canonical fork seed —
    ``state_after`` carries SDK ``session_id`` + ``uuid``).
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


def _record_parent_with_orphan_tool_use(
    recorder: AnthropicAgentsRecorder,
    *,
    thread_id: str = "thread-orphan",
) -> tuple[str, str, str]:
    """Drive ``recorder.record()`` with an UNCLOSED tool use (no result Node).

    The AssistantMessage(ToolUseBlock) is recorded but no UserMessage
    with a matching ToolResultBlock follows — this is the slice-3a
    "use-side orphan" surfaced by ``unmatched_tool_uses``.

    Returns ``(parent_run_id, at_node_id, orphan_tool_use_id)``.
    """
    orphan_id = "tu_orphan_no_result"
    asst_use = AssistantMessage(
        content=[
            ToolUseBlock(id=orphan_id, name="search", input={"x": 1}),
        ],
        model="Claude Sonnet 4.6",
        uuid=_PARENT_UUID,
        session_id=_PARENT_SDK_SID,
    )
    runtime = _FakeClient(messages=[asst_use])
    with recorder.record(runtime, thread_id=thread_id) as ref:
        pass
    assert ref.run_id is not None
    assert len(ref.node_ids) == 1
    return ref.run_id, ref.node_ids[0], orphan_id


def _drive_child_branch(
    recorder: AnthropicAgentsRecorder,
    parent_run_id: str,
    at_node_id: str,
    *,
    tool_input_overrides: dict[str, dict[str, Any]] | None = None,
    child_sdk_sid: str = "child-sdk-sid-0001",
    overridden_tool_use_id: str = _TU_ID,
) -> Any:
    """Run the child branch through ``recorder.fork()`` with the given overrides.

    The child stream is one AssistantMessage carrying a ``ToolUseBlock``
    whose ``id`` is ``overridden_tool_use_id``. The child's ``input``
    dict is whatever the recorder chooses to stamp — R80 will substitute
    if ``tool_input_overrides`` is non-empty; R79 (no impl yet) raises
    ``NotImplementedError`` from the no-op pass-through.

    Returns the populated ``ForkRef``.
    """
    child_msg = AssistantMessage(
        content=[
            ToolUseBlock(id=overridden_tool_use_id, name="search", input={"x": 1}),
        ],
        model="Claude Sonnet 4.6",
        uuid="cccc3333-3333-3333-3333-333333333333",
        session_id=child_sdk_sid,
    )
    child_runtime = _FakeClient(messages=[child_msg])
    with recorder.fork(
        runtime=None,
        parent_run_id=parent_run_id,
        at_node_id=at_node_id,
        child_thread_id="thread-child",
        reason="slice 3b xfail probe",
        overrides={},
        tool_input_overrides=tool_input_overrides,
    ) as fref:
        fref.submit_runtime(child_runtime)  # type: ignore[attr-defined]
    return fref


# ---------------------------------------------------------------------------
# Test 1 — identity (None / {} default). EXPECTED PASS in R79 already:
# the no-op pass-through accepts the kwarg and falls through to R74 fork
# semantics when the mapping is empty/None. This test guards against R80
# regressing that identity contract.
# ---------------------------------------------------------------------------


def test_fork_without_overrides_is_identity(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
    fake_sdk: dict[str, Any],
) -> None:
    """``tool_input_overrides=None`` and ``={}`` are identity forks.

    R74 fork() semantics MUST be preserved when the new R80 kwarg is
    absent or empty. Both invocations should:

    - succeed without raising,
    - produce a child Run in ``RunStatus.COMPLETED``,
    - leave the child's ``state_after['tool_input']`` ABSENT (not
      stamped) on the AssistantMessage Node carrying the
      ``ToolUseBlock`` — i.e. no §5.2 surface side-effect.
    """
    parent_run_id, at_node_id = _record_parent_with_closed_tool_pair(recorder)

    # 1a. tool_input_overrides=None is identity
    fake_sdk["next_session_id"] = "child-sdk-sid-none-0001"
    fref_none = _drive_child_branch(
        recorder,
        parent_run_id,
        at_node_id,
        tool_input_overrides=None,
        child_sdk_sid="child-sdk-sid-none-0001",
    )
    assert fref_none.child_run_id is not None
    child_run_none = store.get_run(fref_none.child_run_id)
    assert child_run_none is not None
    assert child_run_none.status == RunStatus.COMPLETED

    # 1b. tool_input_overrides={} is also identity
    fake_sdk["next_session_id"] = "child-sdk-sid-empty-0002"
    fref_empty = _drive_child_branch(
        recorder,
        parent_run_id,
        at_node_id,
        tool_input_overrides={},
        child_sdk_sid="child-sdk-sid-empty-0002",
    )
    assert fref_empty.child_run_id is not None
    child_run_empty = store.get_run(fref_empty.child_run_id)
    assert child_run_empty is not None
    assert child_run_empty.status == RunStatus.COMPLETED

    # In both cases, no §5.2 side-effect on child Node state_after.
    for fref in (fref_none, fref_empty):
        for nid in fref.node_ids:
            node = store.get_node(nid)
            assert node is not None
            assert "tool_input" not in (node.state_after or {})


# ---------------------------------------------------------------------------
# Test 2 — non-empty override rewrites downstream tool_input (the meat)
# ---------------------------------------------------------------------------


def test_fork_with_override_changes_downstream_input(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
    fake_sdk: dict[str, Any],
) -> None:
    """Substitute ``tool_use_id="tu_t1_closed"`` → ``input={"x": 99}``.

    Expected child-side state per ADR-026 §5.2 #### Stamp on child Nodes:

    - ``state_after['tool_use_id'] == "tu_t1_closed"`` (UNCHANGED — JOIN
      anchor binding contract preserved across fork).
    - ``state_after['tool_input'] == {"x": 99}`` (NEW — substitution
      stamp; absent on Nodes that did not have their input rewritten).
    """
    parent_run_id, at_node_id = _record_parent_with_closed_tool_pair(recorder)

    fref = _drive_child_branch(
        recorder,
        parent_run_id,
        at_node_id,
        tool_input_overrides={_TU_ID: {"x": 99}},
    )
    assert fref.child_run_id is not None

    # Find the child AssistantMessage Node carrying the overridden ToolUseBlock.
    overridden = None
    for nid in fref.node_ids:
        node = store.get_node(nid)
        if node is None:
            continue
        sa = node.state_after or {}
        if sa.get("tool_use_id") == _TU_ID:
            overridden = node
            break

    assert overridden is not None, (
        "Expected a child Node with state_after['tool_use_id']==tu_t1_closed"
    )
    sa = overridden.state_after or {}
    # JOIN anchor preserved
    assert sa.get("tool_use_id") == _TU_ID
    # New §5.2 stamp surfaces the substituted input
    assert sa.get("tool_input") == {"x": 99}


# ---------------------------------------------------------------------------
# Test 3 — unknown id raises BEFORE SDK call (validation #2)
# ---------------------------------------------------------------------------


def test_fork_with_override_of_unknown_id_raises(
    recorder: AnthropicAgentsRecorder,
    fake_sdk: dict[str, Any],
) -> None:
    """``tool_input_overrides={"<bogus>": ...}`` raises ``AdapterError``.

    The bogus key does not appear in the parent's use-side keyset, so
    fork() MUST raise *before* delegating to ``fork_session``.
    Verified by checking ``fake_sdk["session_id"]`` is unset (i.e. our
    fake fork_session never ran).
    """
    parent_run_id, at_node_id = _record_parent_with_closed_tool_pair(recorder)

    with (
        pytest.raises(AdapterError, match="tool_input_overrides"),
        recorder.fork(
            runtime=None,
            parent_run_id=parent_run_id,
            at_node_id=at_node_id,
            child_thread_id="thread-child-bogus",
            reason="should not run",
            overrides={},
            tool_input_overrides={"tu_does_not_exist": {"x": 99}},
        ),
    ):
        pytest.fail("fork() should have raised AdapterError before yielding")

    # SDK never invoked — fail-fast contract.
    assert "session_id" not in fake_sdk


# ---------------------------------------------------------------------------
# Test 4 — orphan use-id raises (slice-3a→3b coupling, validation #3)
# ---------------------------------------------------------------------------


def test_fork_with_override_of_orphan_use_id_raises(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
    fake_sdk: dict[str, Any],
) -> None:
    """Overriding an id surfaced by ``unmatched_tool_uses`` raises.

    ADR-026 §5.2 validation #3 (slice-3a→3b coupling pre-condition):
    the use→result round-trip must have *closed* in the parent run.
    R78's ``unmatched_tool_uses(store, parent_run_id)`` enumerates the
    unclosed ones; fork() MUST reject any override key in that set.
    """
    parent_run_id, at_node_id, orphan_id = _record_parent_with_orphan_tool_use(recorder)

    # Pre-condition: orphan helper actually surfaces the id (R78 contract).
    orphan_nodes = unmatched_tool_uses(store, parent_run_id)
    assert any((n.state_after or {}).get("tool_use_id") == orphan_id for n in orphan_nodes), (
        "test setup invariant: orphan_id must appear in unmatched_tool_uses"
    )

    with (
        pytest.raises(AdapterError, match="tool_input_overrides"),
        recorder.fork(
            runtime=None,
            parent_run_id=parent_run_id,
            at_node_id=at_node_id,
            child_thread_id="thread-child-orphan",
            reason="should not run",
            overrides={},
            tool_input_overrides={orphan_id: {"x": 99}},
        ),
    ):
        pytest.fail("fork() should have raised AdapterError on orphan id")

    # SDK never invoked.
    assert "session_id" not in fake_sdk
