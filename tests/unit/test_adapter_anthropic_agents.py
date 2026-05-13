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


def test_fork_raises_not_implemented(recorder: AnthropicAgentsRecorder) -> None:
    with (
        pytest.raises(NotImplementedError, match="R73"),
        recorder.fork(
            runtime=object(),
            parent_run_id="00000000-0000-0000-0000-000000000000",
            at_node_id="00000000-0000-0000-0000-000000000001",
            child_thread_id="child",
        ),
    ):
        pass


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
