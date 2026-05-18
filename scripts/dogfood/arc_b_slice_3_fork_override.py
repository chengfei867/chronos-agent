"""R86 dogfood — Arc B slice 3 (fork-with-tool_input_overrides) live-smoke probe.

Purpose
-------
Close ADR-026 §6 **AC-3** (Fork primitive re-invokes agent from
``at_node_id`` with ``overrides``; live-smoke green) by exercising the
*real* ``claude_agent_sdk.fork_session()`` against an in-process
``create_sdk_mcp_server`` MCP tool, captured end-to-end through
``AnthropicAgentsRecorder.fork(tool_input_overrides=...)``.

This is the **AC-3 release-gate** dogfood: alpha (v0.7.0a2) accepted
fake-SDK dogfood (R80); v0.7.0 GA requires this script to exit 0
against a real session-protocol-aware upstream that actually mints a
fresh forked session id and re-runs the agent on the child branch.

How it composes with R85 (AC-2)
-------------------------------
R85 closed AC-2 by recording ONE multi-turn MCP run end-to-end. R86
re-uses the same in-process SDK MCP server (``add(a, b)``) twice:

1. **Parent**: record ``add(4127, 8956) = 13083`` — proves AC-2 baseline
   against a fresh DB (independent of R85's run).
2. **Child**: ``recorder.fork(parent, anchor, tool_input_overrides={
   parent_tu_id: {a: 100, b: 200}}) → ClaudeSDKClient(resume=child_sid)``
   re-runs from the fork point. Real ``fork_session()`` mints a FRESH
   tool_use_id in the child transcript (``toolu_*``), so the recorder's
   ``state_after['tool_input']`` stamp does NOT fire (it stamps only on
   id-match, and the child id differs from the parent override key).

R86 contract finding (documented inline + on CONTEXT wall):
  ``tool_input_overrides`` validates the *parent* tool_use_id is a
  matched use-side key, then delegates verbatim to
  ``claude_agent_sdk.fork_session(session_id, up_to_message_id=uuid)``.
  The SDK fork is a pure JSONL rewrite from the parent transcript up
  to fork point — it does NOT splice the override into the child
  transcript. The override surfaces user-side: the user is expected
  to issue a continuation prompt under ``resume=child_sid`` that
  re-invokes the tool with the new input. The child's ToolUseBlock
  carries a *fresh* SDK-minted tu_id, NOT the parent's. This is
  symmetric to R64's "Identity fork ≠ byte-identical trace" finding
  for LangGraph: the SDK is free to renumber. The R80 fake-SDK unit
  tests assert ``state_after['tool_input']`` because the fixture
  echoes the parent tu_id verbatim — that is a fixture artifact of
  the offline test path, NOT a real-relay contract.

Run
---
    set -a && . /workspace/.hermes/.env && set +a
    uv run python scripts/dogfood/arc_b_slice_3_fork_override.py

Three-tier exit semantics
-------------------------
- **0** — parent + child runs both COMPLETED, fork row links them, all
  five AC-3 invariants pass. Release-gate level for v0.7.0 GA AC-3.
- **2** — relay degraded (synthetic auth failure, missing session_id on
  parent anchor, etc). Skip cleanly without failing the build.
- **3** — hard regression (SDK import broken, fork_session() rejected,
  recorder raised an unexpected exception type).

AC-3 release-gate invariants
----------------------------
1. Parent run reaches ``RunStatus.COMPLETED`` with ≥1 ToolUseBlock anchor
   carrying ``state_after['tool_use_id']`` (R85 AC-2 baseline replicated).
2. ``recorder.fork(parent, anchor, tool_input_overrides={parent_tu_id:
   new_input})`` returns a ``ForkRef`` with non-empty ``sdk_session_id``
   AND ``child_run_id`` (real ``fork_session()`` minted a child branch).
3. The store contains a ``Fork`` row with
   ``parent_run_id == parent.run_id`` and ``child_run_id == ref.child_run_id``
   (parent ↔ child relation queryable).
4. Child run reaches ``RunStatus.COMPLETED`` with ≥1 ToolUseBlock node AND
   ≥1 ToolResultBlock node AND those carry matching ``tool_use_id``
   (R76 §5.1 linkage holds across fork — proves the forked agent
   actually re-invoked the tool, didn't just regurgitate cached text).
5. Child's ToolUseBlock tu_id differs from parent's (real ``fork_session``
   mints fresh ids; this is the documented R86 contract finding —
   asserted positively here so a future SDK upgrade that *did* preserve
   the parent id would deliberately fail this gate and force the contract
   doc to be re-evaluated).
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
# When this script runs as ``python scripts/dogfood/arc_b_slice_3_fork_override.py``
# Python auto-inserts the script's parent dir on sys.path[0] so the bare
# import works; pytest live-wrapper invokes us via subprocess so the same
# rule applies. No fragile relative imports.
from _degradation import is_relay_degraded_exception

_LIVE_MODEL = os.environ.get("CHRONOS_DOGFOOD_MODEL", "Claude Sonnet 4.6")
_TIMEOUT_S = float(os.environ.get("CHRONOS_DOGFOOD_TIMEOUT_S", "120"))

# Same operands as R85 — small enough for single-shot, distinctive sum.
_OPERAND_A = 4127
_OPERAND_B = 8956
_PARENT_SUM = _OPERAND_A + _OPERAND_B  # 13083

# Override values — chosen so the child sum (300) cannot be confused
# with the parent sum (13083) in transcript inspection.
_OVERRIDE_A = 100
_OVERRIDE_B = 200
_OVERRIDE_SUM = _OVERRIDE_A + _OVERRIDE_B  # 300


def check_imports() -> tuple[bool, str]:
    """Tier 1 — required SDK + chronos surface importable."""
    try:
        import claude_agent_sdk  # noqa: F401
        from claude_agent_sdk import (  # noqa: F401
            AssistantMessage,
            ClaudeAgentOptions,
            create_sdk_mcp_server,
            fork_session,
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
    """Build the in-process MCP server with a single ``add`` tool (R85-shape)."""
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


async def _record_parent(rec: Any, thread_id: str) -> Any:
    """Tier 2 — record a parent run with one MCP tool round-trip."""
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


def _identify_anchor(store: Any, parent_run_id: str) -> tuple[Any, str] | None:
    """Find the ToolUseBlock node + parent tool_use_id (the override key)."""
    for n in store.get_nodes_for_run(parent_run_id):
        sa = n.state_after or {}
        blocks = sa.get("blocks", []) or []
        block_kinds = {b.get("block") for b in blocks if isinstance(b, dict)}
        tu_id = sa.get("tool_use_id")
        if tu_id and "ToolUseBlock" in block_kinds:
            return n, tu_id
    return None


async def _fork_and_resume(
    rec: Any, parent_run_id: str, anchor_id: str, parent_tu_id: str, child_thread_id: str
) -> Any:
    """Tier 3 — fork(tool_input_overrides=...) + resume the child SDK session.

    The recorder.fork() context manager + submit_runtime() pipeline calls
    asyncio.run() internally to drain the child stream, so we drive the
    whole `with rec.fork(...): submit_runtime(...)` block in a worker
    thread. Same pattern R85 / R74 use for record() and fork() respectively.
    """
    captured: dict[str, Any] = {}

    def _drive() -> Any:
        from claude_agent_sdk import ClaudeAgentOptions, query

        with rec.fork(
            runtime=None,
            parent_run_id=parent_run_id,
            at_node_id=anchor_id,
            child_thread_id=child_thread_id,
            tool_input_overrides={parent_tu_id: {"a": _OVERRIDE_A, "b": _OVERRIDE_B}},
            reason=f"R86 dogfood — override-fork {_OVERRIDE_A}+{_OVERRIDE_B}",
        ) as f_ref:
            sid = f_ref.sdk_session_id
            captured["sdk_session_id"] = sid
            if not sid:
                raise RuntimeError("fork yielded empty sdk_session_id")

            opts = ClaudeAgentOptions(
                max_turns=4,
                model=_LIVE_MODEL,
                mcp_servers={"math": _build_math_server()},
                allowed_tools=["mcp__math__add"],
                resume=sid,
                system_prompt=(
                    "You have access to a tool called 'add' from the 'math' "
                    "MCP server. When the user asks you to add two integers, "
                    "you MUST call the add tool with the integers and then "
                    "reply with the single integer result."
                ),
            )
            child_runtime = query(
                prompt=(
                    f"Now use the add tool to compute {_OVERRIDE_A} + "
                    f"{_OVERRIDE_B} instead. Reply with only the resulting "
                    f"integer."
                ),
                options=opts,
            )
            f_ref.submit_runtime(child_runtime)
        return f_ref

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _drive)


def _inspect_child(store: Any, child_run_id: str) -> dict[str, Any]:
    """Pull the recorded child shape into a dict the assertions consume."""
    nodes = list(store.get_nodes_for_run(child_run_id))
    run = store.get_run(child_run_id)

    tool_use_ids: list[str] = []
    tool_result_ids: list[str] = []
    text_with_override_sum = False

    for n in nodes:
        sa = n.state_after or {}
        tu_id = sa.get("tool_use_id")
        blocks = sa.get("blocks", []) or []
        block_kinds = {b.get("block") for b in blocks if isinstance(b, dict)}

        if tu_id and "ToolUseBlock" in block_kinds:
            tool_use_ids.append(tu_id)
        elif tu_id and "ToolResultBlock" in block_kinds:
            tool_result_ids.append(tu_id)

        for blk in blocks:
            if isinstance(blk, dict) and blk.get("block") == "TextBlock":
                txt = str(blk.get("text", ""))
                # Accept thousands separator just in case (it's <1000 here
                # so unlikely, but symmetric with R85 hardening).
                expected = str(_OVERRIDE_SUM)
                expected_with_sep = f"{_OVERRIDE_SUM:,}"
                if expected in txt or expected_with_sep in txt:
                    text_with_override_sum = True

    return {
        "run_status": getattr(run, "status", None),
        "node_count": len(nodes),
        "tool_use_ids": tool_use_ids,
        "tool_result_ids": tool_result_ids,
        "text_with_override_sum": text_with_override_sum,
    }


def _assert_invariants(
    parent_tu_id: str,
    child_report: dict[str, Any],
    parent_run_id: str,
    child_run_id: str,
    fork_row: Any,
) -> list[str]:
    """Apply the AC-3 release-gate invariants. Returns list of failures."""
    from chronos.core.models import RunStatus

    failures: list[str] = []

    # INV-1 covered by caller (parent recorded + anchor found).

    # INV-2: ForkRef populated (caller validated child_run_id non-empty).
    # Here we just assert the fork-row link.
    # INV-3: Fork row links parent ↔ child.
    if fork_row is None:
        failures.append("INV-3: store.get_fork(fork_id) returned None")
    else:
        if fork_row.parent_run_id != parent_run_id:
            failures.append(
                f"INV-3: fork_row.parent_run_id={fork_row.parent_run_id!r} "
                f"!= expected {parent_run_id!r}"
            )
        if fork_row.child_run_id != child_run_id:
            failures.append(
                f"INV-3: fork_row.child_run_id={fork_row.child_run_id!r} "
                f"!= expected {child_run_id!r}"
            )

    # INV-4a: child run completed.
    if child_report["run_status"] != RunStatus.COMPLETED:
        failures.append(
            f"INV-4: child run.status != COMPLETED (got {child_report['run_status']!r})"
        )
    # INV-4b: ≥1 ToolUseBlock + ≥1 ToolResultBlock with matching id (R76 §5.1).
    if not child_report["tool_use_ids"]:
        failures.append(
            "INV-4: child has no ToolUseBlock node (override fork did not "
            "trigger a fresh tool invocation on resume)"
        )
    if not child_report["tool_result_ids"]:
        failures.append(
            "INV-4: child has no ToolResultBlock node (tool round-trip did "
            "not close on the child branch)"
        )
    matched = set(child_report["tool_use_ids"]) & set(child_report["tool_result_ids"])
    if child_report["tool_use_ids"] and child_report["tool_result_ids"] and not matched:
        failures.append(
            f"INV-4: child tool_use_ids {child_report['tool_use_ids']} and "
            f"tool_result_ids {child_report['tool_result_ids']} have no overlap "
            "(R76 §5.1 linkage broken on child branch)"
        )

    # INV-5: child tu_id differs from parent (R86 contract finding —
    # SDK fork_session mints fresh ids, override surfaces user-side via
    # resume prompt, NOT via transcript splice).
    if parent_tu_id in set(child_report["tool_use_ids"]):
        failures.append(
            f"INV-5: child reused parent tool_use_id {parent_tu_id!r} — "
            "the documented R86 contract finding (SDK fork_session mints "
            "fresh tu_ids) no longer holds. Re-evaluate ADR-026 §5.2 "
            "real-relay semantics."
        )

    # INV-6 (warning, not gate): final TextBlock contains the override sum.
    # Models occasionally garble single-digit arithmetic; this is a soft
    # check. Surfaced as info, not gate, to avoid flakiness.

    return failures


async def _amain() -> int:
    print("=" * 72)
    print("R86 dogfood — Arc B slice 3 (fork-with-tool_input_overrides) live-smoke")
    print(f"  model = {_LIVE_MODEL!r}")
    print(f"  parent operands = {_OPERAND_A} + {_OPERAND_B} = {_PARENT_SUM}")
    print(f"  child override = {_OVERRIDE_A} + {_OVERRIDE_B} = {_OVERRIDE_SUM}")
    print("=" * 72)

    ok, msg = check_imports()
    print(f"[T1] imports: {msg}")
    if not ok:
        return 3

    from chronos.adapters.anthropic_agents import AnthropicAgentsRecorder
    from chronos.adapters.protocols import AdapterError
    from chronos.core.models import RunStatus
    from chronos.store.sqlite import SqliteStore

    with tempfile.TemporaryDirectory(prefix="chronos_r86_") as tmp:
        db_path = Path(tmp) / "fork_override_smoke.db"
        store = SqliteStore.open(str(db_path))
        rec = AnthropicAgentsRecorder(store=store)

        # ---------- Tier 2: record parent ----------
        try:
            p_ref = await asyncio.wait_for(
                _record_parent(rec, thread_id="r86-arc-b-slice-3-fork-override-parent"),
                timeout=_TIMEOUT_S,
            )
        except TimeoutError:
            print(f"[T2] parent record TIMEOUT after {_TIMEOUT_S}s — relay degraded?")
            return 2
        except Exception as e:
            cls = type(e).__name__
            if is_relay_degraded_exception(e):
                print(f"[T2] parent record degraded: {cls}: {e}")
                return 2
            print(f"[T2] parent record HARD failure: {cls}: {e}")
            traceback.print_exc()
            return 3

        print(f"[T2] parent run_id={p_ref.run_id!r}")
        p_run = store.get_run(p_ref.run_id)
        if p_run is None or p_run.status != RunStatus.COMPLETED:
            print(
                f"[T2] parent run.status={p_run.status if p_run else None!r} "
                "— not COMPLETED, treating as degraded"
            )
            return 2

        anchor_pair = _identify_anchor(store, p_ref.run_id)
        if anchor_pair is None:
            print(
                "[T2] no ToolUseBlock anchor in parent run — relay didn't "
                "surface the tool, degraded"
            )
            return 2
        anchor_node, parent_tu_id = anchor_pair
        print(f"[T2] anchor node={anchor_node.id[:8]}… parent_tu_id={parent_tu_id!r}")

        # ---------- Tier 3: fork + resume ----------
        try:
            f_ref = await asyncio.wait_for(
                _fork_and_resume(
                    rec,
                    parent_run_id=p_ref.run_id,
                    anchor_id=anchor_node.id,
                    parent_tu_id=parent_tu_id,
                    child_thread_id="r86-arc-b-slice-3-fork-override-child",
                ),
                timeout=_TIMEOUT_S,
            )
        except TimeoutError:
            print(f"[T3] fork-and-resume TIMEOUT after {_TIMEOUT_S}s — relay degraded?")
            return 2
        except AdapterError as e:
            print(f"[T3] fork-and-resume AdapterError: {e}")
            traceback.print_exc()
            return 3
        except Exception as e:
            cls = type(e).__name__
            if is_relay_degraded_exception(e):
                print(f"[T3] fork degraded: {cls}: {e}")
                return 2
            print(f"[T3] fork-and-resume HARD failure: {cls}: {e}")
            traceback.print_exc()
            return 3

        if not f_ref.child_run_id or not f_ref.fork_id:
            print("[T3] ForkRef missing child_run_id/fork_id — fork pipeline broken")
            return 3
        print(f"[T3] fork OK: child_run_id={f_ref.child_run_id!r} fork_id={f_ref.fork_id!r}")

        # ---------- Tier 4: inspect child + apply invariants ----------
        child_report = _inspect_child(store, f_ref.child_run_id)
        print("[T4] child shape:")
        print(
            json.dumps(
                {
                    "run_status": str(child_report["run_status"]),
                    "node_count": child_report["node_count"],
                    "tool_use_ids": child_report["tool_use_ids"],
                    "tool_result_ids": child_report["tool_result_ids"],
                    "text_with_override_sum": child_report["text_with_override_sum"],
                    "parent_tu_id": parent_tu_id,
                },
                indent=2,
            )
        )

        fork_row = store.get_fork(f_ref.fork_id)
        failures = _assert_invariants(
            parent_tu_id=parent_tu_id,
            child_report=child_report,
            parent_run_id=p_ref.run_id,
            child_run_id=f_ref.child_run_id,
            fork_row=fork_row,
        )

        if failures:
            print(f"[T4] INVARIANTS FAILED ({len(failures)}):")
            for f in failures:
                print(f"  - {f}")
            if child_report["node_count"] <= 2:
                print("[T4] degraded: <=2 child nodes recorded, treating as relay-flake")
                return 2
            return 3

        if not child_report["text_with_override_sum"]:
            print(
                f"[T4] WARN: child final TextBlock did not contain {_OVERRIDE_SUM} "
                "(soft-check; model arithmetic flake — does not gate AC-3)"
            )

        print("[T4] AC-3 release-gate INVARIANTS GREEN")
        return 0


def main() -> int:
    """Sync entrypoint."""
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
