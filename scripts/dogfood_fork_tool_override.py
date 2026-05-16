#!/usr/bin/env python3
"""R80 dogfood — ADR-026 §5.2 (slice 3b) ``fork(tool_input_overrides=...)``.

Demonstrates the *value* of the slice on a single happy path: record a
parent run that issues one tool-use ``tu_calc_42`` with ``input={'q':
2+2}``, then fork it twice — once with overrides ``{}`` (identity, R74
guard) and once with ``{'tu_calc_42': {'q': 7+8}}`` (substitution).

Verifies, in-process and assertively:

1. Identity fork: child Node ``state_after`` has ``tool_use_id`` but NO
   ``tool_input`` key — preserves R74 byte-identity.
2. Substituting fork: child Node ``state_after`` carries
   ``tool_input == {'q': 15}`` AND keeps ``tool_use_id``.
3. Overriding an unknown id raises ``AdapterError`` synchronously.
4. Overriding an orphan use-side id (no matching ``ToolResultBlock``)
   raises ``AdapterError`` synchronously.

This is a *unit-shape* dogfood (FakeSDK, in-memory SQLite). The
analogous live-network dogfood lives in
``tests/live/test_anthropic_agents_fork_smoke.py`` and gates on
``CHRONOS_LIVE=1``.

Run::

    uv run python scripts/dogfood_fork_tool_override.py

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

# --- Stub SDK shapes (mirrors test fixtures) -------------------------------


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
        "next_session_id": "child-sid-dogfood",
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


def _record_parent(recorder: AnthropicAgentsRecorder, tu_id: str) -> tuple[str, str]:
    """Record a parent run with one closed tool use → returns (run_id, anchor_node_id)."""
    parent_msgs = [
        AssistantMessage(
            content=[
                TextBlock(text="Computing 2+2."),
                ToolUseBlock(id=tu_id, name="calculator", input={"q": "2+2"}),
            ],
            uuid="parent-asst-uuid-1",
            session_id="parent-sid-1",
            model="claude-sonnet-4-5-20250929",
        ),
        UserMessage(
            content=[ToolResultBlock(tool_use_id=tu_id, content="4")],
            uuid="parent-user-uuid-1",
            session_id="parent-sid-1",
        ),
        AssistantMessage(
            content=[TextBlock(text="The answer is 4.")],
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
    # Anchor on the Node that issued the tool_use_id (kind="llm" per
    # AssistantMessage translation, see recorder._translate).
    anchor = next(n for n in nodes if (n.state_after or {}).get("tool_use_id") == tu_id)
    return run_id, anchor.id


# --- Build child stream that mirrors the parent shape ----------------------


def _child_messages(tu_id: str, override_input: dict[str, Any] | None) -> list[Any]:
    """Child SDK stream — same shape, ``tool_use_id`` must round-trip."""
    return [
        AssistantMessage(
            content=[
                TextBlock(text="Recomputing."),
                ToolUseBlock(
                    id=tu_id,
                    name="calculator",
                    # Child SDK transcript may lag the override — recorder
                    # stamps state_after['tool_input'] from override map,
                    # not from the SDK input. We deliberately pass the
                    # *parent's* input here to prove the override path.
                    input={"q": "2+2"},
                ),
            ],
            uuid="child-asst-uuid-1",
            session_id="child-sid-dogfood",
            model="claude-sonnet-4-5-20250929",
        ),
        UserMessage(
            content=[ToolResultBlock(tool_use_id=tu_id, content="15")],
            uuid="child-user-uuid-1",
            session_id="child-sid-dogfood",
        ),
        AssistantMessage(
            content=[TextBlock(text="The answer is 15.")],
            uuid="child-asst-uuid-2",
            session_id="child-sid-dogfood",
            model="claude-sonnet-4-5-20250929",
            stop_reason="end_turn",
        ),
    ]


# --- Driver ----------------------------------------------------------------


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        store = SqliteStore.open(Path(td) / "chronos.db")
        recorder = AnthropicAgentsRecorder(store)

        tu_anchor = "tu_calc_42"
        parent_run_id, anchor_node_id = _record_parent(recorder, tu_anchor)
        print(f"[parent] run_id={parent_run_id[:8]} anchor={anchor_node_id[:8]}")

        # ---- Step 1: identity fork (R74 byte-identity guard) -------------
        captured = _install_fake_sdk(_child_messages(tu_anchor, None))
        with recorder.fork(
            captured["child_client"],
            parent_run_id=parent_run_id,
            at_node_id=anchor_node_id,
            child_thread_id="child-identity",
            tool_input_overrides=None,
        ) as ref:
            ref.submit_runtime(captured["child_client"])
        child_id_run = ref.child_run_id
        assert child_id_run is not None
        child_id_nodes = store.get_nodes_for_run(child_id_run)
        anchor_child = next(
            n for n in child_id_nodes if (n.state_after or {}).get("tool_use_id") == tu_anchor
        )
        assert "tool_input" not in (anchor_child.state_after or {}), (
            f"identity fork must not stamp tool_input, got {anchor_child.state_after!r}"
        )
        print("[identity] OK — child has tool_use_id but no tool_input key")

        # ---- Step 2: substituting fork (the meat) ------------------------
        new_input = {"q": "7+8"}
        captured = _install_fake_sdk(_child_messages(tu_anchor, new_input))
        with recorder.fork(
            captured["child_client"],
            parent_run_id=parent_run_id,
            at_node_id=anchor_node_id,
            child_thread_id="child-override",
            tool_input_overrides={tu_anchor: new_input},
        ) as ref:
            ref.submit_runtime(captured["child_client"])
        child_ov_run = ref.child_run_id
        assert child_ov_run is not None
        child_ov_nodes = store.get_nodes_for_run(child_ov_run)
        anchor_ov = next(
            n for n in child_ov_nodes if (n.state_after or {}).get("tool_use_id") == tu_anchor
        )
        sa = anchor_ov.state_after or {}
        assert sa.get("tool_use_id") == tu_anchor, f"tool_use_id lost: {sa!r}"
        assert sa.get("tool_input") == new_input, f"override not stamped: {sa!r} vs {new_input!r}"
        print(f"[override] OK — state_after['tool_input']={sa['tool_input']!r}")

        # ---- Step 3: unknown id raises ----------------------------------
        captured = _install_fake_sdk([])
        try:
            with recorder.fork(
                captured["child_client"],
                parent_run_id=parent_run_id,
                at_node_id=anchor_node_id,
                child_thread_id="child-bad-1",
                tool_input_overrides={"tu_does_not_exist": {"q": "?"}},
            ):
                raise AssertionError("should not reach")
        except AdapterError as e:
            assert "tu_does_not_exist" in str(e), f"missing key in msg: {e}"
            print("[unknown-id] OK — AdapterError raised pre-SDK")

        # ---- Step 4: orphan id raises ------------------------------------
        # Build a fresh parent that LEAVES the tool_use unmatched (no
        # ToolResultBlock follow-up). Then attempt to override its tu_id.
        orphan_anchor = "tu_orphan_99"
        orphan_msgs = [
            AssistantMessage(
                content=[
                    ToolUseBlock(id=orphan_anchor, name="calculator", input={"q": "1+1"}),
                ],
                uuid="orphan-asst-uuid-1",
                session_id="orphan-sid-1",
                model="claude-sonnet-4-5-20250929",
            ),
        ]
        with recorder.record(_FakeClient(messages=orphan_msgs), thread_id="orphan-thread") as ref:
            pass
        orphan_run_id = ref.run_id
        assert orphan_run_id is not None
        orphan_nodes = store.get_nodes_for_run(orphan_run_id)
        orphan_anchor_node = next(
            n for n in orphan_nodes if (n.state_after or {}).get("tool_use_id") == orphan_anchor
        )
        captured = _install_fake_sdk([])
        try:
            with recorder.fork(
                captured["child_client"],
                parent_run_id=orphan_run_id,
                at_node_id=orphan_anchor_node.id,
                child_thread_id="child-bad-2",
                tool_input_overrides={orphan_anchor: {"q": "?"}},
            ):
                raise AssertionError("should not reach")
        except AdapterError as e:
            assert "orphan" in str(e).lower(), f"orphan reason missing: {e}"
            print("[orphan] OK — AdapterError raised pre-SDK")

        store.close()

    print("\n✅ R80 slice 3b dogfood — all 4 paths green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
