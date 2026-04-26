"""Unit tests for the AutoGen adapter (R33-A, ADR-017).

Does NOT require a real LLM or the autogen-agentchat runtime — tests use
duck-typed stub messages + a stub ``TaskResult`` to exercise the
``record()`` sync-wrap CM and the message→Node mapping. A separate
integration-lane test (not in this file) covers a real ``Team.run()``
call and is marked ``@pytest.mark.slow``.

Coverage:

1. Happy-path record via ``ref.submit_result(result)`` — nodes match
   messages, state_after is cumulative, kinds are mapped correctly.
2. Fallback path: user forgets ``submit_result`` → recorder reads
   ``runtime.messages``.
3. Usage extraction from ``models_usage`` (RequestUsage-shaped duck).
4. Exception inside ``with`` block → failed-shell Run persisted,
   exception re-raised, ``ref.node_ids == []``.
5. Fork is explicitly not implemented: raises AdapterError with the
   ADR-017 pointer in the message.
6. Structural conformance: ``AutoGenRecorder`` satisfies
   :class:`RecorderProtocol`; ``autogen_adapter`` satisfies
   :class:`AdapterProtocol`.
7. Adapter factory channels: ``usage_extractor`` rejected, unknown
   adapter-specific kwarg rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from chronos.adapters.autogen import AutoGenRecorder, autogen_adapter
from chronos.adapters.protocols import (
    AdapterError,
    AdapterProtocol,
    RecorderProtocol,
)
from chronos.core.models import NodeKind, RunStatus
from chronos.store import SqliteStore

# ---------------------------------------------------------------------------
# Stub AutoGen shapes — duck-typed so we don't depend on autogen_agentchat
# actually being importable in unit tests.
# ---------------------------------------------------------------------------


@dataclass
class _StubUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class _StubMessage:
    """Duck-typed ``BaseChatMessage`` stand-in.

    The recorder only reads ``type(msg).__name__`` for kind dispatch, plus
    ``source`` / ``content`` / ``models_usage``. We expose a
    ``_cls_name`` override so one dataclass can simulate many AutoGen
    message classes (TextMessage, ToolCallRequestEvent, …).
    """

    source: str
    content: str
    models_usage: _StubUsage | None = None
    _cls_name: str | None = None

    def model_dump(self, mode: str = "python") -> dict[str, Any]:
        return {
            "source": self.source,
            "content": self.content,
            "cls": self._cls_name or "TextMessage",
        }


# Factory helpers that set __class__.__name__ by wrapping in a new type —
# simpler than monkey-patching, and keeps ``type(msg).__name__`` honest.


def _make_msg(cls_name: str, **kwargs: Any) -> Any:
    """Create a stub message whose ``type(...).__name__`` == ``cls_name``."""
    cls = type(cls_name, (_StubMessage,), {})
    return cls(**kwargs, _cls_name=cls_name)


@dataclass
class _StubTaskResult:
    messages: list[Any]
    stop_reason: str | None = None


@dataclass
class _StubTeam:
    """Stand-in for AutoGen ``Team`` — carries a ``.messages`` buffer.

    Real ``Team`` objects keep an internal message history after ``run()``;
    the recorder's fallback path reads this buffer.
    """

    messages: list[Any] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "chronos.db"
    with SqliteStore.open(db) as s:
        yield s


@pytest.fixture
def sample_messages() -> list[Any]:
    """A small multi-agent exchange: user → llm → tool → llm."""
    return [
        _make_msg("TextMessage", source="user", content="add 1 and 2"),
        _make_msg(
            "TextMessage",
            source="assistant",
            content="I'll use the calc tool.",
            models_usage=_StubUsage(prompt_tokens=10, completion_tokens=5),
        ),
        _make_msg(
            "ToolCallRequestEvent",
            source="assistant",
            content="calc(1, 2)",
        ),
        _make_msg(
            "ToolCallExecutionEvent",
            source="calc",
            content="3",
        ),
        _make_msg(
            "TextMessage",
            source="assistant",
            content="The answer is 3.",
            models_usage=_StubUsage(prompt_tokens=15, completion_tokens=3),
        ),
    ]


# ---------------------------------------------------------------------------
# 1. Happy path — submit_result
# ---------------------------------------------------------------------------


def test_record_submit_result_persists_run_and_nodes(store, sample_messages):
    recorder = AutoGenRecorder(store)
    team = _StubTeam()
    result = _StubTaskResult(messages=sample_messages)

    with recorder.record(team, thread_id="t-submit") as ref:
        ref.submit_result(result)  # type: ignore[attr-defined]

    # Run landed.
    assert ref.run_id is not None
    run = store.get_run(ref.run_id)
    assert run is not None
    assert run.adapter == "autogen"
    assert run.adapter_thread_id == "t-submit"
    assert run.status == RunStatus.COMPLETED
    assert run.final_state is not None
    assert len(run.final_state["messages"]) == 5

    # Nodes: one per message, correct order, cumulative state_after.
    nodes = store.get_nodes_for_run(ref.run_id)
    assert [n.step_index for n in nodes] == [0, 1, 2, 3, 4]
    assert len(nodes[0].state_after["messages"]) == 1
    assert len(nodes[-1].state_after["messages"]) == 5

    # Kind mapping.
    kinds = [n.kind for n in nodes]
    assert kinds == [
        NodeKind.FN,  # user TextMessage demoted
        NodeKind.LLM,  # assistant TextMessage
        NodeKind.TOOL,  # ToolCallRequestEvent
        NodeKind.TOOL,  # ToolCallExecutionEvent
        NodeKind.LLM,  # final assistant TextMessage
    ]

    # Parent linkage is linear (each points to the prior node).
    assert nodes[0].parent_node_id is None
    for i in range(1, len(nodes)):
        assert nodes[i].parent_node_id == nodes[i - 1].id


# ---------------------------------------------------------------------------
# 2. Fallback path — user forgot submit_result
# ---------------------------------------------------------------------------


def test_record_fallback_to_runtime_messages(store, sample_messages):
    recorder = AutoGenRecorder(store)
    team = _StubTeam(messages=sample_messages)

    with recorder.record(team, thread_id="t-fallback"):
        pass  # user never calls submit_result

    nodes = store.get_nodes_for_run(ref_run_id_from(store, "t-fallback"))
    assert len(nodes) == 5


def ref_run_id_from(store: SqliteStore, thread_id: str) -> str:
    for r in store.list_runs():
        if r.adapter_thread_id == thread_id:
            return r.id
    raise AssertionError(f"no run with thread_id={thread_id!r}")


# ---------------------------------------------------------------------------
# 3. Usage extraction
# ---------------------------------------------------------------------------


def test_usage_extracted_from_models_usage(store, sample_messages):
    recorder = AutoGenRecorder(store)
    team = _StubTeam()
    result = _StubTaskResult(messages=sample_messages)

    with recorder.record(team, thread_id="t-usage") as ref:
        ref.submit_result(result)  # type: ignore[attr-defined]

    nodes = store.get_nodes_for_run(ref.run_id)
    # Nodes 1 and 4 had models_usage set.
    assert nodes[1].usage is not None
    assert nodes[1].usage.prompt_tokens == 10
    assert nodes[1].usage.completion_tokens == 5
    assert nodes[4].usage is not None
    assert nodes[4].usage.prompt_tokens == 15
    # Messages without models_usage → no usage.
    assert nodes[0].usage is None
    assert nodes[2].usage is None
    assert nodes[3].usage is None


# ---------------------------------------------------------------------------
# 4. Exception path
# ---------------------------------------------------------------------------


def test_exception_in_with_block_persists_failed_shell(store):
    recorder = AutoGenRecorder(store)
    team = _StubTeam()

    class BoomError(RuntimeError):
        pass

    with pytest.raises(BoomError), recorder.record(team, thread_id="t-fail") as ref:
        raise BoomError("simulated runtime failure")

    assert ref.run_id is not None
    run = store.get_run(ref.run_id)
    assert run is not None
    assert run.status == RunStatus.FAILED
    assert "simulated runtime failure" in run.metadata.get("error", "")
    assert ref.node_ids == []
    nodes = store.get_nodes_for_run(ref.run_id)
    assert nodes == []


# ---------------------------------------------------------------------------
# 5. Fork not implemented
# ---------------------------------------------------------------------------


def test_fork_raises_adapter_error_with_adr017_pointer(store):
    recorder = AutoGenRecorder(store)
    team = _StubTeam()
    with (
        pytest.raises(AdapterError, match="ADR-017"),
        recorder.fork(
            team,
            parent_run_id="dummy",
            at_node_id="dummy",
            child_thread_id="c",
        ),
    ):
        pass  # pragma: no cover


# ---------------------------------------------------------------------------
# 6. Structural conformance
# ---------------------------------------------------------------------------


def test_recorder_satisfies_recorder_protocol(store):
    recorder = AutoGenRecorder(store)
    assert isinstance(recorder, RecorderProtocol)


def test_module_adapter_satisfies_adapter_protocol():
    assert isinstance(autogen_adapter, AdapterProtocol)
    assert autogen_adapter.name == "autogen"
    assert autogen_adapter.version_constraint.startswith(">=0.7")


# ---------------------------------------------------------------------------
# 7. Factory channels
# ---------------------------------------------------------------------------


def test_factory_rejects_usage_extractor(store):
    def fake_extractor(*a, **k):  # pragma: no cover
        return None

    with pytest.raises(AdapterError, match="models_usage"):
        autogen_adapter.build_recorder(store, usage_extractor=fake_extractor)


def test_factory_rejects_unknown_adapter_specific(store):
    with pytest.raises(AdapterError, match="unknown adapter-specific"):
        autogen_adapter.build_recorder(store, bogus_kwarg=1)


def test_factory_accepts_adapter_name_override(store):
    recorder = autogen_adapter.build_recorder(store, adapter_name="autogen-test")
    team = _StubTeam()
    result = _StubTaskResult(messages=[])
    with recorder.record(team, thread_id="t-name") as ref:
        ref.submit_result(result)  # type: ignore[attr-defined]
    run = store.get_run(ref.run_id)
    assert run is not None
    assert run.adapter == "autogen-test"


# ---------------------------------------------------------------------------
# 8. R48-A / ADR-020 — tool events embed FunctionCall.name in node_name
# ---------------------------------------------------------------------------


def _make_tool_msg(cls_name: str, source: str, content: list[dict[str, Any]]) -> Any:
    """Build a stub tool event with a ``content: list[FunctionCall-dict]``.

    Real AutoGen 0.7 serializes tool event ``content`` as a list of dicts
    with a ``name`` field per call; we replicate that shape to exercise
    the new ``_extract_tool_names`` path. Spike reference:
    ``tests/spikes/spike10_autogen_tool_effects.py``.
    """

    @dataclass
    class _ToolMsg:
        source: str
        content: list[dict[str, Any]]
        models_usage: _StubUsage | None = None

        def model_dump(self, mode: str = "python") -> dict[str, Any]:
            return {"source": self.source, "content": self.content, "cls": cls_name}

    cls = type(cls_name, (_ToolMsg,), {})
    return cls(source=source, content=content)


def test_tool_request_event_embeds_function_name(store):
    """A ToolCallRequestEvent with one FunctionCall → node_name carries it.

    Expected shape: ``{source}:ToolCallRequestEvent:{tool_name}``.
    """
    recorder = AutoGenRecorder(store)
    team = _StubTeam()
    messages = [
        _make_msg("TextMessage", source="user", content="fetch weather for Beijing"),
        _make_tool_msg(
            "ToolCallRequestEvent",
            source="coder",
            content=[
                {
                    "id": "call_1",
                    "arguments": '{"city":"Beijing"}',
                    "name": "fetch_weather_api",
                }
            ],
        ),
        _make_tool_msg(
            "ToolCallExecutionEvent",
            source="coder",
            content=[
                {
                    "content": "sunny 22C",
                    "name": "fetch_weather_api",
                    "call_id": "call_1",
                    "is_error": False,
                }
            ],
        ),
    ]
    result = _StubTaskResult(messages=messages)

    with recorder.record(team, thread_id="t-tool") as ref:
        ref.submit_result(result)  # type: ignore[attr-defined]

    nodes = store.get_nodes_for_run(ref.run_id)
    assert nodes[1].node_name == "coder:ToolCallRequestEvent:fetch_weather_api"
    assert nodes[2].node_name == "coder:ToolCallExecutionEvent:fetch_weather_api"

    # And — the whole point — classify_effects now picks up "network" on
    # the tool nodes because the function name is visible. metadata.effects
    # is populated by the recorder itself, so we read it straight off.
    assert "network" in nodes[1].metadata["effects"], (
        f"tool request node should tag 'network' from fetch_weather_api, "
        f"got {nodes[1].metadata['effects']!r}"
    )
    assert "network" in nodes[2].metadata["effects"]


def test_tool_event_multiple_calls_concatenates_names(store):
    """Parallel tool calls → node_name joins names with ``+``."""
    recorder = AutoGenRecorder(store)
    team = _StubTeam()
    messages = [
        _make_tool_msg(
            "ToolCallRequestEvent",
            source="coder",
            content=[
                {"id": "c1", "arguments": "{}", "name": "read_file"},
                {"id": "c2", "arguments": "{}", "name": "query_db"},
            ],
        ),
    ]
    result = _StubTaskResult(messages=messages)
    with recorder.record(team, thread_id="t-multi") as ref:
        ref.submit_result(result)  # type: ignore[attr-defined]

    nodes = store.get_nodes_for_run(ref.run_id)
    assert nodes[0].node_name == "coder:ToolCallRequestEvent:read_file+query_db"
    # Both tool name keywords fire → fs and db tags.
    effects = nodes[0].metadata["effects"]
    assert "fs" in effects and "db" in effects, f"expected both 'fs' and 'db' tags, got {effects!r}"


def test_tool_event_falls_back_when_name_missing(store):
    """Malformed tool event without name → legacy shape, no crash."""
    recorder = AutoGenRecorder(store)
    team = _StubTeam()
    # content is a plain string (what the old stub tests used) — no list
    messages = [
        _make_msg(
            "ToolCallRequestEvent",
            source="coder",
            content="calc(1,2)",  # string, not list-of-dicts
        ),
    ]
    result = _StubTaskResult(messages=messages)
    with recorder.record(team, thread_id="t-fallback") as ref:
        ref.submit_result(result)  # type: ignore[attr-defined]

    nodes = store.get_nodes_for_run(ref.run_id)
    # No tool names extractable → fall back to legacy "{source}:{cls}".
    assert nodes[0].node_name == "coder:ToolCallRequestEvent"
    # And effects_map still works as a coarse-grained override path.
    assert nodes[0].metadata["effects"] == []


def test_effects_map_still_overrides_new_shape(store):
    """User's explicit effects_map wins, keyed by the (new) full node_name.

    This locks down the interaction: users who know the new shape get
    per-tool overrides; the override path is key-exact so it works with
    whatever node_name we settle on.
    """
    recorder = AutoGenRecorder(
        store,
        effects_map={
            "coder:ToolCallExecutionEvent:fetch_weather_api": ["external"],
        },
    )
    team = _StubTeam()
    messages = [
        _make_tool_msg(
            "ToolCallExecutionEvent",
            source="coder",
            content=[{"content": "ok", "name": "fetch_weather_api", "call_id": "c"}],
        ),
    ]
    result = _StubTaskResult(messages=messages)
    with recorder.record(team, thread_id="t-override") as ref:
        ref.submit_result(result)  # type: ignore[attr-defined]

    nodes = store.get_nodes_for_run(ref.run_id)
    assert nodes[0].metadata["effects"] == ["external"]
