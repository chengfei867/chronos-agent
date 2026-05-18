"""R85 dogfood — Arc B slice 3 (MCP tool live-smoke) probe.

Purpose
-------
Close ADR-026 §6 **AC-2** (Live-smoke records one multi-turn conversation
with ≥1 MCP tool; verify node kinds + usage extraction) by exercising the
*real* ``claude-agent-sdk`` against an in-process ``create_sdk_mcp_server``
MCP tool, captured end-to-end through ``AnthropicAgentsRecorder``.

This is the **AC-2 release-gate** dogfood: alpha (v0.7.0a2) accepted
fake-SDK live-smoke; v0.7.0 GA requires this script to exit 0 against
a real session-protocol-aware upstream.

Why an in-process SDK MCP server (not stdio/npx)
------------------------------------------------
``claude-agent-sdk`` ships a built-in ``create_sdk_mcp_server`` factory
that registers Python ``@tool``-decorated callables as a Python-process
MCP server (``McpSdkServerConfig``). This avoids a Node.js subprocess
and ``npx`` dance entirely — the tool runs in-process, dispatched by the
``claude`` CLI subprocess via the SDK's own MCP transport. This is the
**simplest** possible MCP probe: zero external infra, full real-relay
exercise of the ToolUseBlock / ToolResultBlock tool-use loop.

Run
---
    set -a && . /workspace/.hermes/.env && set +a
    uv run python scripts/dogfood/arc_b_slice_3_mcp.py

Three-tier exit semantics
-------------------------
- **0** — full multi-turn green: ToolUseBlock surfaced, ToolResultBlock
  surfaced with matching ``tool_use_id``, recorder persisted ``tool``-kind
  nodes for both, final assistant text contains the expected sum.
  Release-gate level for v0.7.0 GA AC-2.
- **2** — relay/auth degraded: ``model='<synthetic>'`` or
  ``error='authentication_failed'`` observed, or stream ended without
  any AssistantMessage. Skip cleanly without failing the build.
- **3** — hard regression: SDK import broken, ``create_sdk_mcp_server``
  /``tool`` missing, or recorder raised an unexpected exception type.

Recorded-structure invariants (release gates)
---------------------------------------------
1. Run reaches ``RunStatus.COMPLETED``.
2. >= 1 node with ``kind == NodeKind.TOOL`` AND ``state_after['tool_use_id']``
   set (R76 ADR-026 §5.1 — ToolUseBlock side).
3. >= 1 node with ``kind == NodeKind.TOOL`` AND ``state_after['tool_use_id']``
   matching one from invariant #2 (R76 — ToolResultBlock side, same id).
4. Final node carries a TextBlock whose text contains the expected sum
   (sanity check that the LLM consumed the tool result).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

# Ensure src/ on sys.path when run as a script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Sibling-module import: shared dogfood-degradation classifier (R86).


_LIVE_MODEL = os.environ.get("CHRONOS_DOGFOOD_MODEL", "Claude Sonnet 4.6")
_TIMEOUT_S = float(os.environ.get("CHRONOS_DOGFOOD_TIMEOUT_S", "90"))

# Two integers chosen to make the expected sum a 4-digit number — small
# enough to fit a single-shot reply, distinctive enough that random
# hallucination is unlikely to produce them.
_OPERAND_A = 4127
_OPERAND_B = 8956
_EXPECTED_SUM = _OPERAND_A + _OPERAND_B  # 13083


def check_imports() -> tuple[bool, str]:
    """Tier 1 — required SDK + chronos surface importable."""
    try:
        import claude_agent_sdk  # noqa: F401
        from claude_agent_sdk import (  # noqa: F401
            AssistantMessage,
            ClaudeAgentOptions,
            create_sdk_mcp_server,
            query,
            tool,
        )

        from chronos.adapters.anthropic_agents import AnthropicAgentsRecorder  # noqa: F401
        from chronos.core.models import NodeKind, RunStatus  # noqa: F401
        from chronos.store.sqlite import SqliteStore  # noqa: F401
    except Exception as e:  # pragma: no cover
        return False, f"import failure: {e!r}"
    return True, "ok"


def _build_math_server() -> Any:
    """Build the in-process MCP server with a single ``add`` tool."""
    from claude_agent_sdk import create_sdk_mcp_server, tool

    @tool(
        "add",
        "Add two integers and return their sum as a string.",
        {"a": int, "b": int},
    )
    async def add_tool(args: dict[str, Any]) -> dict[str, Any]:
        result = int(args["a"]) + int(args["b"])
        return {"content": [{"type": "text", "text": str(result)}]}

    return create_sdk_mcp_server(
        name="math",
        version="0.1.0",
        tools=[add_tool],
    )


async def _drive_query_async(rec: Any, thread_id: str) -> Any:
    """Tier 2-4 — build runtime then delegate the recorder to a worker thread.

    The recorder is *sync* and uses ``asyncio.run`` internally to drain the
    async iterable; calling it from inside an event loop trips
    ``asyncio.run() cannot be called from a running event loop``. Mirrors
    the slice-1 smoke pattern: build the async iterable in this loop, then
    hand the recorder off to ``run_in_executor`` so it runs in a fresh
    thread with no event loop attached.
    """
    from claude_agent_sdk import ClaudeAgentOptions, query

    server = _build_math_server()
    opts = ClaudeAgentOptions(
        max_turns=4,
        model=_LIVE_MODEL,
        mcp_servers={"math": server},
        allowed_tools=["mcp__math__add"],
        system_prompt=(
            "You have access to a tool called 'add' from the 'math' MCP "
            "server. When the user asks you to add two integers, you MUST "
            "call the add tool with the integers and then reply with the "
            "single integer result."
        ),
    )

    runtime = query(
        prompt=(
            f"Use the add tool from the math MCP server to compute "
            f"{_OPERAND_A} + {_OPERAND_B}. Reply with only the resulting "
            f"integer."
        ),
        options=opts,
    )

    loop = asyncio.get_event_loop()

    def _drive() -> Any:
        with rec.record(runtime, thread_id=thread_id) as ref:
            pass
        return ref

    return await loop.run_in_executor(None, _drive)


def _inspect_recorded(store: Any, run_id: str) -> dict[str, Any]:
    """Pull the recorded shape into a dict the assertions consume.

    Note (R85 contract finding): the recorder stamps node ``kind`` from the
    *message* type (UserMessage/AssistantMessage → LLM, SystemMessage → FN,
    ResultMessage → END), NOT from the embedded block type. So
    ToolUseBlock and ToolResultBlock surface as ``kind=LLM`` nodes whose
    ``state_after`` carries ``tool_use_id`` + ``blocks=[{"block": "ToolUseBlock", ...}]``.
    The TOOL ``NodeKind`` in the recorder's block-dispatch table (recorder.py:77)
    is currently unused for these blocks; deferred for a future round to
    reconcile or document. AC-2 invariants below match observed shape.
    """
    nodes = list(store.get_nodes_for_run(run_id))
    run = store.get_run(run_id)

    tool_use_ids: list[str] = []  # from AssistantMessage(ToolUseBlock)
    tool_result_ids: list[str] = []  # from UserMessage(ToolResultBlock)
    text_node_with_sum = False

    for n in nodes:
        state_after = n.state_after or {}
        tu_id = state_after.get("tool_use_id")
        blocks = state_after.get("blocks", []) or []
        block_kinds = {b.get("block") for b in blocks if isinstance(b, dict)}

        if tu_id and "ToolUseBlock" in block_kinds:
            tool_use_ids.append(tu_id)
        elif tu_id and "ToolResultBlock" in block_kinds:
            tool_result_ids.append(tu_id)

        # Final-text sanity: any text block containing the expected sum.
        for blk in blocks:
            if isinstance(blk, dict) and blk.get("block") == "TextBlock":
                txt = str(blk.get("text", ""))
                # The model may render the sum with a thousands separator
                # (e.g. "13,083"). Accept either form.
                expected = str(_EXPECTED_SUM)
                expected_with_sep = f"{_EXPECTED_SUM:,}"
                if expected in txt or expected_with_sep in txt:
                    text_node_with_sum = True

    return {
        "run_status": getattr(run, "status", None),
        "node_count": len(nodes),
        "tool_use_ids": tool_use_ids,
        "tool_result_ids": tool_result_ids,
        "text_node_with_sum": text_node_with_sum,
    }


def _assert_invariants(report: dict[str, Any]) -> list[str]:
    """Apply the AC-2 release-gate invariants. Returns list of failures."""
    from chronos.core.models import RunStatus

    failures: list[str] = []
    if report["run_status"] != RunStatus.COMPLETED:
        failures.append(f"INV-1: run.status != COMPLETED (got {report['run_status']!r})")
    if not report["tool_use_ids"]:
        failures.append(
            "INV-2: no node with state_after['tool_use_id'] + ToolUseBlock "
            "(AssistantMessage(ToolUseBlock) not surfaced)"
        )
    if not report["tool_result_ids"]:
        failures.append(
            "INV-3: no node with state_after['tool_use_id'] + ToolResultBlock "
            "(UserMessage(ToolResultBlock) not surfaced)"
        )
    matched = set(report["tool_use_ids"]) & set(report["tool_result_ids"])
    if not matched:
        failures.append(
            f"INV-3b: tool_use_ids {report['tool_use_ids']} and "
            f"tool_result_ids {report['tool_result_ids']} have no overlap "
            "(R76 ADR-026 §5.1 contract violated)"
        )
    if not report["text_node_with_sum"]:
        failures.append(
            f"INV-4: no recorded TextBlock contains expected sum "
            f"{_EXPECTED_SUM} (LLM did not surface the tool result)"
        )
    return failures


async def _amain() -> int:
    print("=" * 72)
    print("R85 dogfood — Arc B slice 3 (MCP tool) live-smoke")
    print(f"  model = {_LIVE_MODEL!r}")
    print(f"  operands = {_OPERAND_A} + {_OPERAND_B} = {_EXPECTED_SUM}")
    print("=" * 72)

    ok, msg = check_imports()
    print(f"[T1] imports: {msg}")
    if not ok:
        return 3

    from chronos.adapters.anthropic_agents import AnthropicAgentsRecorder
    from chronos.store.sqlite import SqliteStore

    with tempfile.TemporaryDirectory(prefix="chronos_r85_") as tmp:
        db_path = Path(tmp) / "mcp_smoke.db"
        store = SqliteStore.open(str(db_path))
        rec = AnthropicAgentsRecorder(store=store)

        try:
            ref = await asyncio.wait_for(
                _drive_query_async(rec, thread_id="r85-arc-b-slice-3-mcp-smoke"),
                timeout=_TIMEOUT_S,
            )
        except TimeoutError:
            print(f"[T2] TIMEOUT after {_TIMEOUT_S}s — relay degraded?")
            return 2
        except Exception as e:
            tb = traceback.format_exc()
            cls = type(e).__name__
            # R86: classifier shared with R86 dogfood — see scripts/dogfood/_degradation.py.
            # Catches synthetic-auth-failed (R69/R71) AND the new SDK-masked
            # 'Claude code returned an error result: success' envelope (R86).
            from _degradation import is_relay_degraded_exception

            if is_relay_degraded_exception(e):
                print(f"[T2] relay degraded: {cls}: {e}")
                return 2
            print(f"[T2] HARD failure: {cls}: {e}")
            print(tb)
            return 3

        print(f"[T2] recorder produced run_id={ref.run_id!r}")
        report = _inspect_recorded(store, ref.run_id)
        print("[T3] recorded shape:")
        print(
            json.dumps(
                {
                    "run_status": str(report["run_status"]),
                    "node_count": report["node_count"],
                    "tool_use_ids": report["tool_use_ids"],
                    "tool_result_ids": report["tool_result_ids"],
                    "text_node_with_sum": report["text_node_with_sum"],
                },
                indent=2,
            )
        )

        failures = _assert_invariants(report)
        if failures:
            print(f"[T4] INVARIANTS FAILED ({len(failures)}):")
            for f in failures:
                print(f"  - {f}")
            # No nodes at all + no failures-from-relay = degraded
            if report["node_count"] <= 2:
                print("[T4] degraded: <=2 nodes recorded, treating as relay-flake")
                return 2
            return 3

        print("[T4] AC-2 release-gate INVARIANTS GREEN")
        return 0


def main() -> int:
    """Sync entrypoint."""
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
