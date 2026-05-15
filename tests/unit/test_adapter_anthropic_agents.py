"""Unit tests for the Anthropic Agents SDK adapter (R70, ADR-026).

Does NOT require a real ``claude-agent-sdk`` install — the recorder
consumes an async iterator of duck-typed ``Message`` stubs whose runtime
class name drives the kind dispatch (mirroring the CrewAI adapter's
event-class-name dispatch pattern, ADR-021).

Coverage:

1. Structural conformance: ``AnthropicAgentsRecorder`` satisfies
   :class:`RecorderProtocol`; ``anthropic_agents_adapter`` satisfies
   :class:`AdapterProtocol`.
2. ``_extract_usage``: Anthropic field-name projection onto Chronos
   Usage schema (``input_tokens`` → ``prompt_tokens``, cache tokens
   summed, all-zero → ``None``, type-drift → ``AdapterError``).
3. ``_summarise_content``: string, block list (``TextBlock``,
   ``ToolUseBlock``, ``ToolResultBlock``, ``ThinkingBlock``), ``None``.
4. ``_node_name_for``: plain message classes + AssistantMessage with
   single ToolUseBlock gets ``:<tool_name>`` postfix.
5. ``_translate``: NodeKind dispatch, tool_name/tool_input surfacing on
   AssistantMessage + ToolUseBlock, tool_output on UserMessage +
   ToolResultBlock, error_message on is_error=True.
6. ``record()`` happy path against an in-memory async-generator
   runtime: Run + Nodes land in the store with monotonic
   ``step_index``; ``RunStatus.COMPLETED``; ``ref.run_id`` /
   ``ref.node_ids`` populated.
7. ``record()`` failure path: exception inside ``with`` → failed-shell
   Run with ``RunStatus.FAILED`` and re-raise.
8. ``record()`` with ``ClaudeSDKClient``-style runtime exposing
   ``receive_messages()`` (resolves through ``_resolve_iterator``).
9. ``record()`` rejects non-iterable runtime with ``AdapterError``.
10. ``record()`` SDK-drift: non-dict ``usage`` surfaces as
    ``AdapterError`` (not silent Pydantic crash).
11. ``fork()`` raises ``NotImplementedError`` with R73 / ADR-026 pointer
    (R70 scaffold scope — see ADR-026 §6).
12. Adapter factory channels: ``usage_extractor`` rejected, unknown
    ``**adapter_specific`` rejected, ``adapter_name`` plumbed through.
13. Probe: ``HAS_CLAUDE_SDK`` is a bool; when False
    ``CLAUDE_SDK_IMPORT_ERROR`` is a non-None ImportError.
14. Kind map override: custom ``kind_map`` layers over the defaults.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from chronos.adapters.anthropic_agents import (
    CLAUDE_SDK_IMPORT_ERROR,
    HAS_CLAUDE_SDK,
    AnthropicAgentsRecorder,
    anthropic_agents_adapter,
)
from chronos.adapters.anthropic_agents.recorder import (
    _DEFAULT_KIND_MAP,
    _extract_usage,
    _node_name_for,
    _PendingNode,
    _summarise_content,
)
from chronos.adapters.protocols import (
    AdapterError,
    AdapterProtocol,
    RecorderProtocol,
    RunRef,
)
from chronos.core.models import NodeKind, RunStatus
from chronos.store import SqliteStore

# ---------------------------------------------------------------------------
# Stub SDK Message + ContentBlock factory
# ---------------------------------------------------------------------------


@dataclass
class _StubBlockBase:
    """Duck-typed base for content blocks — attrs read via getattr()."""

    text: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None
    tool_use_id: str | None = None
    is_error: bool = False
    content: Any = None
    thinking: str | None = None
    signature: str | None = None
    # ADR-026 §5.1 (R76, slice 3a): ToolUseBlock.id is the cross-Node link
    # anchor; ToolResultBlock carries the matching tool_use_id pointing back
    # to it. Stub block needs this slot for the slice-3a tests.
    id: str | None = None


@dataclass
class _StubMsgBase:
    """Duck-typed base for SDK Messages — attrs read via getattr()."""

    content: Any = None
    model: str | None = None
    usage: dict[str, int] | None = None
    uuid: str | None = None
    session_id: str | None = None
    stop_reason: str | None = None
    total_cost_usd: float | None = None
    duration_ms: int | None = None


def _blk(cls_name: str, **kwargs: Any) -> _StubBlockBase:
    subclass = type(cls_name, (_StubBlockBase,), {})
    return subclass(**kwargs)  # type: ignore[return-value]


def _msg(cls_name: str, **kwargs: Any) -> _StubMsgBase:
    subclass = type(cls_name, (_StubMsgBase,), {})
    return subclass(**kwargs)  # type: ignore[return-value]


async def _aiter(items: list[Any]) -> AsyncIterator[Any]:
    for x in items:
        yield x


@dataclass
class _FakeClient:
    """Minimal ClaudeSDKClient-shape: exposes ``receive_messages()``."""

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


# ---------------------------------------------------------------------------
# 1. Structural conformance
# ---------------------------------------------------------------------------


def test_recorder_satisfies_recorder_protocol(
    recorder: AnthropicAgentsRecorder,
) -> None:
    assert isinstance(recorder, RecorderProtocol)


def test_adapter_satisfies_adapter_protocol() -> None:
    assert isinstance(anthropic_agents_adapter, AdapterProtocol)
    assert anthropic_agents_adapter.name == "anthropic_agents"
    assert "0.1.80" in anthropic_agents_adapter.version_constraint
    assert "<1.0" in anthropic_agents_adapter.version_constraint


# ---------------------------------------------------------------------------
# 2. _extract_usage
# ---------------------------------------------------------------------------


def test_extract_usage_anthropic_field_names() -> None:
    m = _msg("AssistantMessage", usage={"input_tokens": 100, "output_tokens": 40})
    out = _extract_usage(m)
    assert out == {"prompt_tokens": 100, "completion_tokens": 40, "reasoning_tokens": 0}


def test_extract_usage_sums_cache_tokens_into_prompt() -> None:
    m = _msg(
        "AssistantMessage",
        usage={
            "input_tokens": 50,
            "cache_creation_input_tokens": 30,
            "cache_read_input_tokens": 20,
            "output_tokens": 10,
        },
    )
    out = _extract_usage(m)
    assert out == {"prompt_tokens": 100, "completion_tokens": 10, "reasoning_tokens": 0}


def test_extract_usage_thinking_into_reasoning() -> None:
    m = _msg(
        "AssistantMessage",
        usage={"input_tokens": 5, "output_tokens": 5, "thinking_tokens": 7},
    )
    out = _extract_usage(m)
    assert out == {"prompt_tokens": 5, "completion_tokens": 5, "reasoning_tokens": 7}


def test_extract_usage_none_when_missing() -> None:
    m = _msg("UserMessage")
    assert _extract_usage(m) is None


def test_extract_usage_all_zero_returns_none() -> None:
    m = _msg("AssistantMessage", usage={"input_tokens": 0, "output_tokens": 0})
    assert _extract_usage(m) is None


def test_extract_usage_drift_non_dict_raises() -> None:
    m = _msg("AssistantMessage", usage=[1, 2, 3])  # type: ignore[arg-type]
    with pytest.raises(AdapterError, match=r"expected dict for Message\.usage"):
        _extract_usage(m)


def test_extract_usage_chronos_native_fallback() -> None:
    """If a test/stub uses our schema names directly, they still work."""
    m = _msg(
        "AssistantMessage",
        usage={"prompt_tokens": 11, "completion_tokens": 22, "reasoning_tokens": 3},
    )
    out = _extract_usage(m)
    assert out == {"prompt_tokens": 11, "completion_tokens": 22, "reasoning_tokens": 3}


# ---------------------------------------------------------------------------
# 3. _summarise_content
# ---------------------------------------------------------------------------


def test_summarise_content_none() -> None:
    assert _summarise_content(None) == {}


def test_summarise_content_string() -> None:
    assert _summarise_content("hello") == {"text": "hello"}


def test_summarise_content_block_list() -> None:
    blocks = [
        _blk("TextBlock", text="hi"),
        _blk("ToolUseBlock", name="bash", input={"cmd": "ls"}),
        _blk("ThinkingBlock", thinking="reasoning"),
    ]
    out = _summarise_content(blocks)
    assert "blocks" in out
    names = [b["block"] for b in out["blocks"]]
    assert names == ["TextBlock", "ToolUseBlock", "ThinkingBlock"]
    assert out["blocks"][0]["text"] == "hi"
    assert out["blocks"][1]["name"] == "bash"
    assert out["blocks"][1]["input"] == {"cmd": "ls"}
    assert out["blocks"][2]["thinking"] == "reasoning"


def test_summarise_content_unknown_type() -> None:
    out = _summarise_content(42)
    assert "raw" in out


# ---------------------------------------------------------------------------
# 4. _node_name_for
# ---------------------------------------------------------------------------


def test_node_name_for_plain_message() -> None:
    assert _node_name_for(_msg("UserMessage")) == "UserMessage"
    assert _node_name_for(_msg("AssistantMessage")) == "AssistantMessage"
    assert _node_name_for(_msg("ResultMessage")) == "ResultMessage"


def test_node_name_for_assistant_with_tool_use() -> None:
    m = _msg(
        "AssistantMessage",
        content=[_blk("ToolUseBlock", name="bash", input={"cmd": "pwd"})],
    )
    assert _node_name_for(m) == "AssistantMessage:bash"


def test_node_name_for_assistant_with_text_only_no_postfix() -> None:
    m = _msg("AssistantMessage", content=[_blk("TextBlock", text="hello")])
    assert _node_name_for(m) == "AssistantMessage"


# ---------------------------------------------------------------------------
# 5. _translate
# ---------------------------------------------------------------------------


def test_translate_user_message() -> None:
    rec = AnthropicAgentsRecorder.__new__(AnthropicAgentsRecorder)
    rec._kind_map = dict(_DEFAULT_KIND_MAP)
    p = rec._translate(_msg("UserMessage", content="hi"))
    assert isinstance(p, _PendingNode)
    assert p.kind == NodeKind.LLM
    assert p.node_name == "UserMessage"
    assert p.state_after == {"text": "hi"}
    assert p.usage is None


def test_translate_assistant_with_tool_use() -> None:
    rec = AnthropicAgentsRecorder.__new__(AnthropicAgentsRecorder)
    rec._kind_map = dict(_DEFAULT_KIND_MAP)
    blk = _blk("ToolUseBlock", name="bash", input={"cmd": "echo hi"})
    m = _msg(
        "AssistantMessage",
        content=[blk],
        model="claude-sonnet-4-5",
        usage={"input_tokens": 10, "output_tokens": 4},
    )
    p = rec._translate(m)
    assert p.kind == NodeKind.LLM  # AssistantMessage is LLM
    assert p.node_name == "AssistantMessage:bash"
    assert p.tool_name == "bash"
    assert p.tool_input == {"cmd": "echo hi"}
    assert p.model_name == "claude-sonnet-4-5"
    assert p.usage == {"prompt_tokens": 10, "completion_tokens": 4, "reasoning_tokens": 0}


def test_translate_user_with_tool_result() -> None:
    rec = AnthropicAgentsRecorder.__new__(AnthropicAgentsRecorder)
    rec._kind_map = dict(_DEFAULT_KIND_MAP)
    blk = _blk("ToolResultBlock", tool_use_id="tu1", content={"stdout": "ok"})
    p = rec._translate(_msg("UserMessage", content=[blk]))
    assert p.tool_output == {"stdout": "ok"}
    assert p.error_message is None


def test_translate_user_with_tool_error() -> None:
    rec = AnthropicAgentsRecorder.__new__(AnthropicAgentsRecorder)
    rec._kind_map = dict(_DEFAULT_KIND_MAP)
    blk = _blk(
        "ToolResultBlock",
        tool_use_id="tu1",
        is_error=True,
        content="boom",
    )
    p = rec._translate(_msg("UserMessage", content=[blk]))
    assert p.error_message is not None
    assert "boom" in p.error_message


def test_translate_result_message_kind_end() -> None:
    rec = AnthropicAgentsRecorder.__new__(AnthropicAgentsRecorder)
    rec._kind_map = dict(_DEFAULT_KIND_MAP)
    p = rec._translate(
        _msg(
            "ResultMessage",
            stop_reason="end_turn",
            total_cost_usd=0.001,
            usage={"input_tokens": 7, "output_tokens": 3},
        )
    )
    assert p.kind == NodeKind.END
    assert p.state_after.get("stop_reason") == "end_turn"
    assert p.state_after.get("total_cost_usd") == 0.001


def test_translate_unknown_class_falls_back_to_fn() -> None:
    rec = AnthropicAgentsRecorder.__new__(AnthropicAgentsRecorder)
    rec._kind_map = dict(_DEFAULT_KIND_MAP)
    p = rec._translate(_msg("FutureSDKMessage", content="x"))
    assert p.kind == NodeKind.FN  # safe fallback, no AdapterError


# ---------------------------------------------------------------------------
# 6. record() happy path — in-memory async generator runtime
# ---------------------------------------------------------------------------


def test_record_persists_run_and_nodes(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    messages = [
        _msg("UserMessage", content="solve 2+2"),
        _msg(
            "AssistantMessage",
            content=[_blk("TextBlock", text="4")],
            model="claude-sonnet-4-5",
            usage={"input_tokens": 12, "output_tokens": 1},
        ),
        _msg(
            "ResultMessage",
            stop_reason="end_turn",
            usage={"input_tokens": 12, "output_tokens": 1},
        ),
    ]
    runtime = _aiter(messages)

    with recorder.record(runtime, thread_id="t1") as ref:
        assert isinstance(ref, RunRef)
        assert ref.thread_id == "t1"
        assert ref.run_id is None  # populated on exit

    assert ref.run_id is not None
    assert len(ref.node_ids) == 3

    run = store.get_run(ref.run_id)
    assert run is not None
    assert run.adapter == "anthropic_agents"
    assert run.adapter_thread_id == "t1"
    assert run.status == RunStatus.COMPLETED

    nodes = store.get_nodes_for_run(ref.run_id)
    assert [n.step_index for n in nodes] == [0, 1, 2]
    assert [n.node_name for n in nodes] == [
        "UserMessage",
        "AssistantMessage",
        "ResultMessage",
    ]
    assert nodes[1].model_name == "claude-sonnet-4-5"
    assert nodes[1].usage is not None
    assert nodes[1].usage.prompt_tokens == 12
    assert nodes[1].usage.completion_tokens == 1


# ---------------------------------------------------------------------------
# 6.1 record() inter-method contract — state_after seed coordinates (R75)
#
# ADR-026 §5 (R75 amendment) binds record() to stamp uuid + session_id onto
# state_after for AssistantMessage / ResultMessage when the SDK exposes them.
# fork() depends on these as the SDK fork_session() anchor (parent_session_id +
# up_to_message_id). These tests fail loud if a future refactor of record()'s
# metadata-stamping loop drops either key — protecting the R74 fork() invariant
# without going through the fork tests.
# ---------------------------------------------------------------------------


def test_record_state_after_carries_seed_coordinates_for_assistant(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    """ADR-026 §5 (R75): AssistantMessage with uuid+session_id must surface
    both onto Node.state_after. fork() reads exactly these keys."""
    parent_uuid = "11111111-1111-1111-1111-111111111111"
    parent_sid = "sess-aaaaaaaa"
    messages = [
        _msg("UserMessage", content="hi"),
        _msg(
            "AssistantMessage",
            content=[_blk("TextBlock", text="hello")],
            model="claude-sonnet-4-5",
            uuid=parent_uuid,
            session_id=parent_sid,
        ),
    ]
    runtime = _aiter(messages)
    with recorder.record(runtime, thread_id="t-state-asst") as ref:
        pass

    assert ref.run_id is not None
    nodes = store.get_nodes_for_run(ref.run_id)
    asst = next(n for n in nodes if n.node_name == "AssistantMessage")
    assert asst.state_after.get("uuid") == parent_uuid, (
        "ADR-026 §5: AssistantMessage state_after must carry uuid (fork anchor)"
    )
    assert asst.state_after.get("session_id") == parent_sid, (
        "ADR-026 §5: AssistantMessage state_after must carry session_id (fork anchor)"
    )


def test_record_state_after_carries_seed_coordinates_for_result(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    """ADR-026 §5 (R75): ResultMessage with uuid+session_id must surface
    both onto Node.state_after. Forking from a ResultMessage anchor is a
    supported usage pattern (end-of-turn fork)."""
    result_uuid = "22222222-2222-2222-2222-222222222222"
    result_sid = "sess-bbbbbbbb"
    messages = [
        _msg("UserMessage", content="hi"),
        _msg("AssistantMessage", content=[_blk("TextBlock", text="hello")]),
        _msg(
            "ResultMessage",
            stop_reason="end_turn",
            uuid=result_uuid,
            session_id=result_sid,
            total_cost_usd=0.0001,
            duration_ms=42,
        ),
    ]
    runtime = _aiter(messages)
    with recorder.record(runtime, thread_id="t-state-result") as ref:
        pass

    assert ref.run_id is not None
    nodes = store.get_nodes_for_run(ref.run_id)
    result = next(n for n in nodes if n.node_name == "ResultMessage")
    assert result.state_after.get("uuid") == result_uuid
    assert result.state_after.get("session_id") == result_sid
    # observability-only keys also surface (not part of fork contract but present)
    assert result.state_after.get("stop_reason") == "end_turn"
    assert result.state_after.get("total_cost_usd") == 0.0001
    assert result.state_after.get("duration_ms") == 42


# ---------------------------------------------------------------------------
# 6.2 record() tool-use round-trip linkage — state_after.tool_use_id (R76)
#
# ADR-026 §5.1 (R76 amendment, slice 3a entry) binds record() to surface
# ToolUseBlock.id (when an AssistantMessage carries exactly one ToolUseBlock)
# and ToolResultBlock.tool_use_id (when a UserMessage carries exactly one
# ToolResultBlock) onto Node.state_after as ``tool_use_id``. This is the
# cross-Node JOIN anchor for slice 3 tool round-trip queries: a downstream
# consumer asking "which assistant tool-use Node generated this tool-result
# Node?" pivots on equality of state_after['tool_use_id'] without parsing
# the nested state_after.blocks list.
#
# Not a schema change (state_after is JSON-bag) but IS a public contract pin:
# any future narrowing of the metadata-stamping logic must keep
# state_after['tool_use_id'] populated for these two cases. Mismatched /
# orphan tool_result blocks must not break record() — they simply land with
# the linkage anchor still set; downstream JOIN finds no matching use Node
# (asymmetric tolerance, validated by
# test_unmatched_tool_result_does_not_break_record).
# ---------------------------------------------------------------------------


def test_record_tool_use_block_persists_id(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    """ADR-026 §5.1 (R76): AssistantMessage carrying single ToolUseBlock
    surfaces ToolUseBlock.id onto state_after['tool_use_id']."""
    tool_use_id = "toolu_01ABCdefGhi"
    messages = [
        _msg("UserMessage", content="please run pwd"),
        _msg(
            "AssistantMessage",
            content=[
                _blk(
                    "ToolUseBlock",
                    id=tool_use_id,
                    name="bash",
                    input={"cmd": "pwd"},
                )
            ],
            model="claude-sonnet-4-5",
        ),
    ]
    runtime = _aiter(messages)
    with recorder.record(runtime, thread_id="t-tool-use") as ref:
        pass

    assert ref.run_id is not None
    nodes = store.get_nodes_for_run(ref.run_id)
    asst = next(n for n in nodes if n.node_name == "AssistantMessage:bash")
    assert asst.state_after.get("tool_use_id") == tool_use_id, (
        "ADR-026 §5.1: AssistantMessage(ToolUseBlock).state_after must "
        "carry tool_use_id (cross-Node link anchor for slice-3 queries)"
    )
    # And tool_name / tool_input still flow into Node columns (R70 contract).
    assert asst.tool_name == "bash"
    assert asst.tool_input == {"cmd": "pwd"}


def test_record_tool_result_block_links_to_use(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    """ADR-026 §5.1 (R76): UserMessage carrying single ToolResultBlock
    surfaces ToolResultBlock.tool_use_id onto state_after['tool_use_id'].
    Asserts the JOIN: result Node's tool_use_id matches the use Node's
    tool_use_id, byte-for-byte."""
    tool_use_id = "toolu_01XYZuvw"
    messages = [
        _msg("UserMessage", content="please run pwd"),
        _msg(
            "AssistantMessage",
            content=[_blk("ToolUseBlock", id=tool_use_id, name="bash", input={"cmd": "pwd"})],
            model="claude-sonnet-4-5",
        ),
        _msg(
            "UserMessage",
            content=[
                _blk(
                    "ToolResultBlock",
                    tool_use_id=tool_use_id,
                    content={"stdout": "/home/user\n"},
                )
            ],
        ),
    ]
    runtime = _aiter(messages)
    with recorder.record(runtime, thread_id="t-tool-roundtrip") as ref:
        pass

    assert ref.run_id is not None
    nodes = store.get_nodes_for_run(ref.run_id)
    use_node = next(n for n in nodes if n.node_name == "AssistantMessage:bash")
    # Result node lands as the second UserMessage (step_index 2). Filter by
    # presence of tool_output to pick it deterministically.
    result_node = next(n for n in nodes if n.tool_output is not None)
    # Both Nodes carry the SAME tool_use_id — this is the JOIN key.
    assert use_node.state_after.get("tool_use_id") == tool_use_id
    assert result_node.state_after.get("tool_use_id") == tool_use_id
    assert use_node.state_after.get("tool_use_id") == result_node.state_after.get("tool_use_id"), (
        "ADR-026 §5.1: tool_use_id must be byte-identical across linked Nodes"
    )
    # Output round-trip preserved.
    assert result_node.tool_output == {"stdout": "/home/user\n"}


def test_unmatched_tool_result_does_not_break_record(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    """ADR-026 §5.1 (R76): An orphan ToolResultBlock (no matching
    AssistantMessage(ToolUseBlock) earlier in the stream, e.g. a stream
    that began mid-conversation) must NOT break record(); the result Node
    persists with state_after['tool_use_id'] still set (linking to a
    not-yet-seen anchor is a valid client situation when starting from a
    forked / resumed session). Asymmetric tolerance: missing anchor is
    observability loss, not a record() failure."""
    orphan_tu_id = "toolu_orphaned"
    messages = [
        # No prior AssistantMessage(ToolUseBlock) — tool_use_id refers to a
        # message we never observed (resumed / forked session entry).
        _msg(
            "UserMessage",
            content=[
                _blk(
                    "ToolResultBlock",
                    tool_use_id=orphan_tu_id,
                    content={"stdout": "resumed"},
                )
            ],
        ),
    ]
    runtime = _aiter(messages)
    with recorder.record(runtime, thread_id="t-tool-orphan") as ref:
        pass

    assert ref.run_id is not None  # record() succeeded — no AdapterError
    nodes = store.get_nodes_for_run(ref.run_id)
    assert len(nodes) == 1
    orphan = nodes[0]
    # Run completed cleanly even though the use anchor is missing.
    run = store.get_run(ref.run_id)
    assert run is not None
    assert run.status == RunStatus.COMPLETED
    # The linkage anchor is still surfaced — caller can detect orphan by
    # querying for tool_use_id with no matching ToolUseBlock node.
    assert orphan.state_after.get("tool_use_id") == orphan_tu_id
    assert orphan.tool_output == {"stdout": "resumed"}


# ---------------------------------------------------------------------------
# 6.2.1 record() multi-block tool linkage — state_after.tool_use_ids (R77)
# ---------------------------------------------------------------------------
#
# ADR-026 §5.1.1 (R77 amendment, slice 3a-P1) extends the §5.1 single-block
# contract to the multi-block case. When an AssistantMessage carries >1
# ToolUseBlock (batched tool dispatch) the recorder surfaces the ordered
# ids list as `state_after['tool_use_ids']` (plural). The singular
# `state_after['tool_use_id']` is reserved for the len==1 1:1 JOIN anchor —
# multi-block consumers expand 1:N via
# `json_each(state_after->>'tool_use_ids')`. Order matches block order in
# the source message so consumers can pair use[i] <-> result[i] by index.
#
# These three tests pin:
#   - use side: >1 ToolUseBlock -> tool_use_ids list, no singular tool_use_id
#   - result side: >1 ToolResultBlock -> tool_use_ids list, no singular
#   - separation: a stream containing both single-block (singular) and
#     multi-block (plural) messages keeps the two fields cleanly separate
# ---------------------------------------------------------------------------


def test_record_multi_tool_use_block_persists_ids(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    """ADR-026 §5.1.1 (R77): AssistantMessage carrying >1 ToolUseBlock
    surfaces the ordered ids list as state_after['tool_use_ids'] (plural).
    Singular state_after['tool_use_id'] is NOT set in the multi-block case
    (binding contract — R76 §5.1 reserves singular for the 1:1 JOIN anchor).
    """
    ids = ["toolu_01AAA", "toolu_02BBB", "toolu_03CCC"]
    messages = [
        _msg("UserMessage", content="please run several commands"),
        _msg(
            "AssistantMessage",
            content=[
                _blk("ToolUseBlock", id=ids[0], name="bash", input={"cmd": "pwd"}),
                _blk("ToolUseBlock", id=ids[1], name="bash", input={"cmd": "ls"}),
                _blk("ToolUseBlock", id=ids[2], name="bash", input={"cmd": "whoami"}),
            ],
            model="claude-sonnet-4-5",
        ),
    ]
    runtime = _aiter(messages)
    with recorder.record(runtime, thread_id="t-multi-tool-use") as ref:
        pass

    assert ref.run_id is not None
    nodes = store.get_nodes_for_run(ref.run_id)
    asst = next(n for n in nodes if n.node_name.startswith("AssistantMessage"))
    # Plural list set, in source order (NOT sorted).
    assert asst.state_after.get("tool_use_ids") == ids, (
        "ADR-026 §5.1.1: AssistantMessage(>1 ToolUseBlock).state_after must "
        "carry tool_use_ids (plural) in source order"
    )
    # Singular intentionally NOT set in multi-block case (R76 §5.1 binding).
    assert "tool_use_id" not in asst.state_after, (
        "ADR-026 §5.1.1: singular tool_use_id reserved for len==1 (1:1 JOIN); "
        "multi-block must use tool_use_ids (plural) only"
    )


def test_record_multi_tool_result_block_persists_ids(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    """ADR-026 §5.1.1 (R77): UserMessage carrying >1 ToolResultBlock
    surfaces the ordered tool_use_ids list as state_after['tool_use_ids'].
    Asserts JOIN consistency: result-side tool_use_ids list is byte-for-byte
    equal to the use-side list (i-th use <-> i-th result by SDK contract).
    """
    ids = ["toolu_01XXX", "toolu_02YYY"]
    messages = [
        _msg("UserMessage", content="please run two commands"),
        _msg(
            "AssistantMessage",
            content=[
                _blk("ToolUseBlock", id=ids[0], name="bash", input={"cmd": "pwd"}),
                _blk("ToolUseBlock", id=ids[1], name="bash", input={"cmd": "ls"}),
            ],
            model="claude-sonnet-4-5",
        ),
        _msg(
            "UserMessage",
            content=[
                _blk(
                    "ToolResultBlock",
                    tool_use_id=ids[0],
                    content={"stdout": "/home\n"},
                ),
                _blk(
                    "ToolResultBlock",
                    tool_use_id=ids[1],
                    content={"stdout": "a\nb\n"},
                ),
            ],
        ),
    ]
    runtime = _aiter(messages)
    with recorder.record(runtime, thread_id="t-multi-tool-roundtrip") as ref:
        pass

    assert ref.run_id is not None
    nodes = store.get_nodes_for_run(ref.run_id)
    use_node = next(n for n in nodes if n.node_name.startswith("AssistantMessage"))
    # Result Node = the second UserMessage (the one with multi-result blocks).
    # First UserMessage has plain str content; pick the one whose
    # state_after carries tool_use_ids.
    result_node = next(
        n for n in nodes if n.node_name == "UserMessage" and "tool_use_ids" in n.state_after
    )
    # Both Nodes carry SAME ordered ids list — this is the JOIN keyset.
    assert use_node.state_after.get("tool_use_ids") == ids
    assert result_node.state_after.get("tool_use_ids") == ids
    assert use_node.state_after.get("tool_use_ids") == result_node.state_after.get(
        "tool_use_ids"
    ), "ADR-026 §5.1.1: tool_use_ids list must be byte-identical across linked Nodes"
    # Singular not set on either side (multi-block case).
    assert "tool_use_id" not in use_node.state_after
    assert "tool_use_id" not in result_node.state_after


def test_record_mixed_count_keeps_singular_and_plural_separate(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    """ADR-026 §5.1 + §5.1.1 (R76 + R77): a stream mixing single-block and
    multi-block tool messages keeps the singular/plural fields cleanly
    separate per Node — singular Node has only `tool_use_id`, plural Node
    has only `tool_use_ids`. Both contracts hold simultaneously without
    cross-talk; this is the regression guard against a future refactor that
    might collapse the two fields.
    """
    single_id = "toolu_solo"
    multi_ids = ["toolu_pair_a", "toolu_pair_b"]
    messages = [
        _msg("UserMessage", content="first run one command"),
        _msg(
            "AssistantMessage",
            content=[_blk("ToolUseBlock", id=single_id, name="bash", input={"cmd": "id"})],
            model="claude-sonnet-4-5",
        ),
        _msg(
            "UserMessage",
            content=[
                _blk(
                    "ToolResultBlock",
                    tool_use_id=single_id,
                    content={"stdout": "uid=1000\n"},
                )
            ],
        ),
        _msg("UserMessage", content="now two more"),
        _msg(
            "AssistantMessage",
            content=[
                _blk("ToolUseBlock", id=multi_ids[0], name="bash", input={"cmd": "pwd"}),
                _blk("ToolUseBlock", id=multi_ids[1], name="bash", input={"cmd": "ls"}),
            ],
            model="claude-sonnet-4-5",
        ),
    ]
    runtime = _aiter(messages)
    with recorder.record(runtime, thread_id="t-mixed-count") as ref:
        pass

    assert ref.run_id is not None
    nodes = store.get_nodes_for_run(ref.run_id)
    asst_nodes = [n for n in nodes if n.node_name.startswith("AssistantMessage")]
    assert len(asst_nodes) == 2

    # Find singular vs plural deterministically by which key is present.
    singular_node = next(n for n in asst_nodes if "tool_use_id" in n.state_after)
    plural_node = next(n for n in asst_nodes if "tool_use_ids" in n.state_after)

    # Singular Node: ONLY tool_use_id, NOT tool_use_ids.
    assert singular_node.state_after["tool_use_id"] == single_id
    assert "tool_use_ids" not in singular_node.state_after, (
        "ADR-026 §5.1: single-block Node must not carry plural tool_use_ids"
    )
    # Plural Node: ONLY tool_use_ids, NOT tool_use_id.
    assert plural_node.state_after["tool_use_ids"] == multi_ids
    assert "tool_use_id" not in plural_node.state_after, (
        "ADR-026 §5.1.1: multi-block Node must not carry singular tool_use_id"
    )
    # The two fields are mutually exclusive per Node by binding contract.


# ---------------------------------------------------------------------------
# 7. record() failure path
# ---------------------------------------------------------------------------


def test_record_failure_marks_run_failed_and_reraises(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    class BoomError(RuntimeError):
        pass

    ref_holder: list[RunRef] = []

    with pytest.raises(BoomError), recorder.record(_aiter([]), thread_id="tb") as ref:
        ref_holder.append(ref)
        raise BoomError("user code blew up")

    assert ref_holder
    # On failure the ref.run_id is populated via finally's drain (best-effort)
    ref = ref_holder[0]
    if ref.run_id is not None:
        run = store.get_run(ref.run_id)
        assert run is not None
        assert run.status == RunStatus.FAILED


# ---------------------------------------------------------------------------
# 8. record() with ClaudeSDKClient-style runtime
# ---------------------------------------------------------------------------


def test_record_with_claude_sdk_client_shape(
    recorder: AnthropicAgentsRecorder,
    store: SqliteStore,
) -> None:
    client = _FakeClient(
        messages=[
            _msg("UserMessage", content="hi"),
            _msg(
                "AssistantMessage",
                content=[_blk("TextBlock", text="hello back")],
            ),
        ]
    )
    with recorder.record(client, thread_id="tc") as ref:
        pass

    assert ref.run_id is not None
    nodes = store.get_nodes_for_run(ref.run_id)
    assert len(nodes) == 2


# ---------------------------------------------------------------------------
# 9. record() rejects non-iterable runtime
# ---------------------------------------------------------------------------


def test_record_rejects_non_iterable(recorder: AnthropicAgentsRecorder) -> None:
    with (
        pytest.raises(AdapterError, match="recognised SDK message source"),
        recorder.record(object(), thread_id="tx"),
    ):
        pass


# ---------------------------------------------------------------------------
# 10. SDK drift — non-dict usage surfaces as AdapterError
# ---------------------------------------------------------------------------


def test_record_drift_bad_usage_shape(
    recorder: AnthropicAgentsRecorder,
) -> None:
    messages = [
        _msg("AssistantMessage", usage="not-a-dict"),  # type: ignore[arg-type]
    ]
    with (
        pytest.raises(
            AdapterError,
            match=r"expected dict for Message\.usage|failure consuming",
        ),
        recorder.record(_aiter(messages), thread_id="td"),
    ):
        pass


# ---------------------------------------------------------------------------
# 11. fork() raises NotImplementedError (R73 scope)
# ---------------------------------------------------------------------------


def test_fork_happy_path_persists_run_nodes_and_fork_row(
    recorder: AnthropicAgentsRecorder, store: SqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R74: fork() delegates to claude_agent_sdk.fork_session, persists Run+Nodes+Fork."""
    # 1. Record a parent run with one AssistantMessage (carries uuid+session_id)
    parent_uuid = "11111111-1111-1111-1111-111111111111"
    parent_sdk_sid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    asst = _msg(
        "AssistantMessage",
        content=[_blk("TextBlock", text="hello from parent")],
        model="Claude Sonnet 4.6",
        uuid=parent_uuid,
        session_id=parent_sdk_sid,
    )
    parent_runtime = _FakeClient(messages=[asst])
    with recorder.record(parent_runtime, thread_id="thread-parent") as p_ref:
        pass
    assert p_ref.run_id is not None
    parent_run_id = p_ref.run_id
    parent_node_id = p_ref.node_ids[0]

    # 2. Stub claude_agent_sdk.fork_session via sys.modules monkey-patch.
    # The recorder imports inside fork(), so we install a fake module.
    import sys
    import types as _types

    fake_sdk = _types.ModuleType("claude_agent_sdk")
    captured: dict[str, Any] = {}

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
        return _FakeForkResult(session_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    fake_sdk.fork_session = _fake_fork_session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    # 3. Fork & drive child runtime
    child_msg = _msg(
        "AssistantMessage",
        content=[_blk("TextBlock", text="hello from child fork")],
        model="Claude Sonnet 4.6",
        uuid="22222222-2222-2222-2222-222222222222",
        session_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )
    child_runtime = _FakeClient(messages=[child_msg])
    with recorder.fork(
        runtime=None,
        parent_run_id=parent_run_id,
        at_node_id=parent_node_id,
        child_thread_id="thread-child",
        reason="branching to test alt prompt",
        overrides={"prompt_edit": "what if we asked X instead"},
    ) as f_ref:
        # SDK fork happened before yield
        assert captured["session_id"] == parent_sdk_sid
        assert captured["up_to_message_id"] == parent_uuid
        assert f_ref.sdk_session_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # type: ignore[attr-defined]
        # User submits the resumed runtime
        f_ref.submit_runtime(child_runtime)  # type: ignore[attr-defined]

    # 4. Assert ForkRef populated + DB rows correct
    assert f_ref.child_run_id is not None
    assert f_ref.fork_id is not None
    assert len(f_ref.node_ids) == 1

    child_run = store.get_run(f_ref.child_run_id)
    assert child_run is not None
    assert child_run.adapter_thread_id == "thread-child"
    assert child_run.status == RunStatus.COMPLETED

    fork_row = store.get_fork(f_ref.fork_id)
    assert fork_row is not None
    assert fork_row.parent_run_id == parent_run_id
    assert fork_row.parent_node_id == parent_node_id
    assert fork_row.child_run_id == f_ref.child_run_id
    assert fork_row.edited_fields == {"prompt_edit": "what if we asked X instead"}
    assert fork_row.reason == "branching to test alt prompt"


def test_fork_rejects_unknown_parent_run(recorder: AnthropicAgentsRecorder) -> None:
    with (
        pytest.raises(AdapterError, match="parent_run_id="),
        recorder.fork(
            runtime=None,
            parent_run_id="00000000-0000-0000-0000-000000000000",
            at_node_id="00000000-0000-0000-0000-000000000001",
            child_thread_id="child",
        ),
    ):
        pass


def test_fork_rejects_node_from_different_run(
    recorder: AnthropicAgentsRecorder, store: SqliteStore
) -> None:
    # Record two runs; try to fork run-A using run-B's node_id
    asst = _msg(
        "AssistantMessage",
        uuid="aaaa1111-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        session_id="sess-a",
        model="m",
        content=[_blk("TextBlock", text="A")],
    )
    with recorder.record(_FakeClient(messages=[asst]), thread_id="t-a") as ref_a:
        pass
    bsst = _msg(
        "AssistantMessage",
        uuid="bbbb1111-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        session_id="sess-b",
        model="m",
        content=[_blk("TextBlock", text="B")],
    )
    with recorder.record(_FakeClient(messages=[bsst]), thread_id="t-b") as ref_b:
        pass
    assert ref_a.run_id and ref_b.run_id
    with (
        pytest.raises(AdapterError, match="does not belong"),
        recorder.fork(
            runtime=None,
            parent_run_id=ref_a.run_id,
            at_node_id=ref_b.node_ids[0],
            child_thread_id="t-c",
        ),
    ):
        pass


def test_fork_rejects_same_thread_id(recorder: AnthropicAgentsRecorder, store: SqliteStore) -> None:
    asst = _msg(
        "AssistantMessage",
        uuid="cccc1111-cccc-cccc-cccc-cccccccccccc",
        session_id="sess-c",
        model="m",
        content=[_blk("TextBlock", text="C")],
    )
    with recorder.record(_FakeClient(messages=[asst]), thread_id="same") as ref:
        pass
    assert ref.run_id
    with (
        pytest.raises(AdapterError, match="must differ from parent"),
        recorder.fork(
            runtime=None,
            parent_run_id=ref.run_id,
            at_node_id=ref.node_ids[0],
            child_thread_id="same",  # same as parent
        ),
    ):
        pass


def test_fork_rejects_anchor_without_session_id(
    recorder: AnthropicAgentsRecorder,
) -> None:
    """SystemMessage / UserMessage may lack session_id+uuid → fork must reject."""
    sysm = _msg("SystemMessage", content="boot")  # no uuid, no session_id
    with recorder.record(_FakeClient(messages=[sysm]), thread_id="t-sys") as ref:
        pass
    assert ref.run_id
    with (
        pytest.raises(AdapterError, match="no SDK session_id"),
        recorder.fork(
            runtime=None,
            parent_run_id=ref.run_id,
            at_node_id=ref.node_ids[0],
            child_thread_id="t-sys-child",
        ),
    ):
        pass


def test_fork_persists_failed_status_on_user_block_exception(
    recorder: AnthropicAgentsRecorder, store: SqliteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exception inside the with-block → child Run = FAILED, Fork row still written."""
    asst = _msg(
        "AssistantMessage",
        uuid="dddd1111-dddd-dddd-dddd-dddddddddddd",
        session_id="sess-d",
        model="m",
        content=[_blk("TextBlock", text="D")],
    )
    with recorder.record(_FakeClient(messages=[asst]), thread_id="t-d") as ref:
        pass
    assert ref.run_id

    # Stub fork_session
    import sys
    import types as _types

    fake_sdk = _types.ModuleType("claude_agent_sdk")

    @dataclass
    class _R:
        session_id: str

    fake_sdk.fork_session = lambda sid, **kw: _R(  # type: ignore[attr-defined]
        session_id="eeee1111-eeee-eeee-eeee-eeeeeeeeeeee"
    )
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    with (
        pytest.raises(RuntimeError, match="boom"),
        recorder.fork(
            runtime=None,
            parent_run_id=ref.run_id,
            at_node_id=ref.node_ids[0],
            child_thread_id="t-d-child",
        ) as f_ref,
    ):
        raise RuntimeError("boom")

    # Even on failure ref.child_run_id was populated by the finally block
    assert f_ref.child_run_id is not None
    child_run = store.get_run(f_ref.child_run_id)
    assert child_run is not None
    assert child_run.status == RunStatus.FAILED
    # Fork row is still queryable
    fork_row = store.get_fork_for_child(f_ref.child_run_id)
    assert fork_row is not None


# ---------------------------------------------------------------------------
# 12. Adapter factory channels
# ---------------------------------------------------------------------------


def test_adapter_rejects_usage_extractor(store: SqliteStore) -> None:
    with pytest.raises(AdapterError, match="usage_extractor"):
        anthropic_agents_adapter.build_recorder(store, usage_extractor=lambda _: None)


def test_adapter_rejects_unknown_kwarg(store: SqliteStore) -> None:
    with pytest.raises(AdapterError, match="unknown adapter-specific"):
        anthropic_agents_adapter.build_recorder(store, bogus_flag=True)


def test_adapter_plumbs_adapter_name(store: SqliteStore) -> None:
    rec = anthropic_agents_adapter.build_recorder(store, adapter_name="my_custom_name")
    assert rec._adapter_name == "my_custom_name"


def test_adapter_kind_map_override(store: SqliteStore) -> None:
    rec = anthropic_agents_adapter.build_recorder(
        store, kind_map={"AssistantMessage": NodeKind.ROUTER}
    )
    assert rec._kind_map["AssistantMessage"] == NodeKind.ROUTER
    # Defaults preserved for keys not overridden
    assert rec._kind_map["UserMessage"] == NodeKind.LLM


# ---------------------------------------------------------------------------
# 13. Probe
# ---------------------------------------------------------------------------


def test_probe_is_bool() -> None:
    assert isinstance(HAS_CLAUDE_SDK, bool)
    if HAS_CLAUDE_SDK:
        assert CLAUDE_SDK_IMPORT_ERROR is None
    else:
        assert CLAUDE_SDK_IMPORT_ERROR is not None
        assert isinstance(CLAUDE_SDK_IMPORT_ERROR, ImportError)


# ---------------------------------------------------------------------------
# 14. Default kind map sanity
# ---------------------------------------------------------------------------


def test_default_kind_map_contents() -> None:
    assert _DEFAULT_KIND_MAP["UserMessage"] == NodeKind.LLM
    assert _DEFAULT_KIND_MAP["AssistantMessage"] == NodeKind.LLM
    assert _DEFAULT_KIND_MAP["ResultMessage"] == NodeKind.END
    assert _DEFAULT_KIND_MAP["ToolUseBlock"] == NodeKind.TOOL
    assert _DEFAULT_KIND_MAP["ToolResultBlock"] == NodeKind.TOOL
    # ThinkingBlock is NOT in the map — it rides inside AssistantMessage.content
    # per R69 spike #1.5 / ADR-026 §5.
    assert "ThinkingBlock" not in _DEFAULT_KIND_MAP
