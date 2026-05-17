#!/usr/bin/env python3
"""R82 dogfood — ADR-026 §5.3 (slice 3c) ``fork(tool_result_overrides=...)``.

Symmetric mirror of R80's ``dogfood_fork_tool_override.py``: rewrite the
**result** half of the tool round-trip instead of the input half. Same
4-path coverage:

1. Identity fork (``tool_result_overrides=None``): child result-side
   Node ``state_after`` has ``tool_use_id`` but NO ``tool_result_content``
   key — preserves R74 byte-identity (also enforced by unit test #1).
2. Substituting fork: child result-side Node ``state_after`` carries
   ``tool_result_content == 'overridden-42'`` AND keeps ``tool_use_id``.
3. Overriding an unknown id raises ``AdapterError`` synchronously
   pre-SDK, error message contains ``"result-side"``.
4. Overriding a key that ALSO appears in ``tool_input_overrides``
   raises ``AdapterError`` synchronously (collision rule, §5.3 #3).

This is a *unit-shape* dogfood (FakeSDK, in-memory SQLite). The
analogous live-network dogfood will land alongside slice 4.

Run::

    uv run python scripts/dogfood_fork_tool_result_override.py

Exits 0 on success; non-zero with traceback on any assertion failure.
"""

from __future__ import annotations

import sys
import tempfile
import types as _types
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chronos.adapters.anthropic_agents import AnthropicAgentsRecorder
from chronos.adapters.protocols import AdapterError
from chronos.store.sqlite import SqliteStore

# --- Stub SDK shapes (mirrors R80 dogfood / unit fixtures) -----------------


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


class UserMessage(_StubMessage):
    pass


class AssistantMessage(_StubMessage):
    pass


def _aiter(messages: list[Any]) -> AsyncIterator[Any]:
    async def _gen() -> AsyncIterator[Any]:
        for m in messages:
            yield m

    return _gen()


@dataclass
class _FakeClient:
    messages: list[Any] = field(default_factory=list)

    def receive_messages(self) -> AsyncIterator[Any]:
        return _aiter(self.messages)


# --- Install fake claude_agent_sdk module ----------------------------------


def _install_fake_sdk(child_messages: list[Any]) -> dict[str, Any]:
    captured: dict[str, Any] = {
        "next_session_id": "child-sid-r82-dogfood",
        "fork_calls": [],
    }
    fake_mod = _types.ModuleType("claude_agent_sdk")

    @dataclass
    class _FakeForkResult:
        session_id: str

    def fork_session(session_id: str, /, **kwargs: Any) -> _FakeForkResult:
        captured["fork_calls"].append({"session_id": session_id, **kwargs})
        return _FakeForkResult(session_id=captured["next_session_id"])

    fake_mod.fork_session = fork_session
    fake_mod.UserMessage = UserMessage
    fake_mod.AssistantMessage = AssistantMessage
    fake_mod.ToolUseBlock = ToolUseBlock
    fake_mod.ToolResultBlock = ToolResultBlock
    fake_mod.TextBlock = TextBlock
    sys.modules["claude_agent_sdk"] = fake_mod

    captured["child_client"] = _FakeClient(messages=child_messages)
    return captured


# --- Build a parent run with one closed tool round-trip --------------------


def _record_parent(recorder: AnthropicAgentsRecorder, tu_id: str) -> tuple[str, str, str]:
    """Record a parent run with one closed tool use → returns
    (run_id, llm_anchor_node_id, result_node_id)."""
    parent_msgs = [
        AssistantMessage(
            content=[
                TextBlock(text="Computing 6*7."),
                ToolUseBlock(id=tu_id, name="calculator", input={"q": "6*7"}),
            ],
            uuid="parent-asst-uuid-1",
            session_id="parent-sid-1",
            model="claude-sonnet-4-5-20250929",
        ),
        UserMessage(
            content=[ToolResultBlock(tool_use_id=tu_id, content="42")],
            uuid="parent-user-uuid-1",
            session_id="parent-sid-1",
        ),
        AssistantMessage(
            content=[TextBlock(text="The answer is 42.")],
            uuid="parent-asst-uuid-2",
            session_id="parent-sid-1",
            model="claude-sonnet-4-5-20250929",
            stop_reason="end_turn",
        ),
    ]
    client = _FakeClient(messages=parent_msgs)
    with recorder.record(client, thread_id="parent-thread") as ref:
        pass
    run_id = ref.run_id
    assert run_id is not None
    nodes = recorder._store.get_nodes_for_run(run_id)
    # LLM-side anchor (carries singular tool_use_id from the AssistantMessage)
    llm_anchor = next(n for n in nodes if (n.state_after or {}).get("tool_use_id") == tu_id)
    # Result-side Node (UserMessage carrying ToolResultBlock); per recorder
    # convention, both use- and result-side Nodes stamp tool_use_id, but
    # the result-side has kind "tool" / "user" — we just pick whichever Node
    # is the second hit on the anchor id. Easier: pick by step_index ordering.
    result_node = next(
        n
        for n in nodes
        if (n.state_after or {}).get("tool_use_id") == tu_id and n.id != llm_anchor.id
    )
    return run_id, llm_anchor.id, result_node.id


# --- Build child stream that mirrors the parent shape ----------------------


def _child_messages(tu_id: str) -> list[Any]:
    """Child SDK stream — same shape as parent."""
    return [
        AssistantMessage(
            content=[
                TextBlock(text="Recomputing."),
                ToolUseBlock(id=tu_id, name="calculator", input={"q": "6*7"}),
            ],
            uuid="child-asst-uuid-1",
            session_id="child-sid-r82-dogfood",
            model="claude-sonnet-4-5-20250929",
        ),
        UserMessage(
            content=[ToolResultBlock(tool_use_id=tu_id, content="42")],
            uuid="child-user-uuid-1",
            session_id="child-sid-r82-dogfood",
        ),
        AssistantMessage(
            content=[TextBlock(text="The answer is 42.")],
            uuid="child-asst-uuid-2",
            session_id="child-sid-r82-dogfood",
            model="claude-sonnet-4-5-20250929",
            stop_reason="end_turn",
        ),
    ]


# --- Driver ----------------------------------------------------------------


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        store = SqliteStore.open(Path(td) / "chronos.db")
        recorder = AnthropicAgentsRecorder(store)

        tu_anchor = "tu_calc_r82"
        parent_run_id, llm_anchor_id, _result_node_id = _record_parent(recorder, tu_anchor)
        print(f"[parent] run_id={parent_run_id[:8]} llm_anchor={llm_anchor_id[:8]}")

        # ---- Step 1: identity fork (R74 byte-identity guard) -------------
        captured = _install_fake_sdk(_child_messages(tu_anchor))
        with recorder.fork(
            captured["child_client"],
            parent_run_id=parent_run_id,
            at_node_id=llm_anchor_id,
            child_thread_id="child-identity-r82",
            tool_result_overrides=None,
        ) as ref:
            ref.submit_runtime(captured["child_client"])
        child_id_run = ref.child_run_id
        assert child_id_run is not None
        child_id_nodes = store.get_nodes_for_run(child_id_run)
        # Find result-side Node in child (UserMessage carrying ToolResultBlock).
        child_result_nodes = [
            n for n in child_id_nodes if (n.state_after or {}).get("tool_use_id") == tu_anchor
        ]
        # At least 2 (LLM + result-side both stamp); identity must NOT have
        # tool_result_content on any of them.
        for n in child_result_nodes:
            assert "tool_result_content" not in (n.state_after or {}), (
                f"identity fork must not stamp tool_result_content, got {n.state_after!r}"
            )
        print("[identity] OK — child has tool_use_id but no tool_result_content key")

        # ---- Step 2: substituting fork (the meat) ------------------------
        override_value = "overridden-42"
        captured = _install_fake_sdk(_child_messages(tu_anchor))
        with recorder.fork(
            captured["child_client"],
            parent_run_id=parent_run_id,
            at_node_id=llm_anchor_id,
            child_thread_id="child-override-r82",
            tool_result_overrides={tu_anchor: override_value},
        ) as ref:
            ref.submit_runtime(captured["child_client"])
        child_ov_run = ref.child_run_id
        assert child_ov_run is not None
        child_ov_nodes = store.get_nodes_for_run(child_ov_run)
        # The substitution must surface on the result-side Node (UserMessage),
        # NOT the LLM-side. Find the Node where state_after['tool_result_content']
        # is set.
        stamped = [n for n in child_ov_nodes if "tool_result_content" in (n.state_after or {})]
        assert len(stamped) == 1, (
            f"expected exactly 1 stamped result-side Node, got {len(stamped)}: "
            f"{[(n.id, n.state_after) for n in stamped]}"
        )
        sa = stamped[0].state_after or {}
        assert sa.get("tool_use_id") == tu_anchor, f"tool_use_id lost: {sa!r}"
        assert sa.get("tool_result_content") == override_value, (
            f"override not stamped: {sa!r} vs {override_value!r}"
        )
        print(f"[override] OK — state_after['tool_result_content']={sa['tool_result_content']!r}")

        # ---- Step 3: unknown id raises ("result-side" in message) -------
        captured = _install_fake_sdk([])
        try:
            with recorder.fork(
                captured["child_client"],
                parent_run_id=parent_run_id,
                at_node_id=llm_anchor_id,
                child_thread_id="child-bad-r82-1",
                tool_result_overrides={"tu_no_such": "ignored"},
            ):
                raise AssertionError("should not reach")
        except AdapterError as e:
            msg = str(e)
            assert "tu_no_such" in msg, f"missing key in msg: {e}"
            assert "result-side" in msg, f"'result-side' missing in error: {e}"
            assert not captured["fork_calls"], "SDK fork called despite validation failure"
            print("[unknown-id] OK — AdapterError raised pre-SDK with 'result-side'")

        # ---- Step 4: input/result collision raises ----------------------
        captured = _install_fake_sdk([])
        try:
            with recorder.fork(
                captured["child_client"],
                parent_run_id=parent_run_id,
                at_node_id=llm_anchor_id,
                child_thread_id="child-bad-r82-2",
                tool_input_overrides={tu_anchor: {"q": "9*9"}},
                tool_result_overrides={tu_anchor: "double-rewrite"},
            ):
                raise AssertionError("should not reach")
        except AdapterError as e:
            msg = str(e)
            assert tu_anchor in msg, f"colliding id missing in msg: {e}"
            assert not captured["fork_calls"], "SDK fork called despite validation failure"
            print(
                f"[collision] OK — AdapterError raised pre-SDK, colliding id {tu_anchor!r} in error"
            )

        store.close()

    print("\n✅ R82 slice 3c dogfood — all 4 paths green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
