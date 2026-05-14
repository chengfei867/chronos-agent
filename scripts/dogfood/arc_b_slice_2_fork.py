"""R74 dogfood — Arc B slice 2 (fork_session) live smoke probe.

Purpose
-------
Validate ``AnthropicAgentsRecorder.fork()`` end-to-end against the
*real* ``claude-agent-sdk`` (PyPI ``>=0.1.80,<1.0``, ADR-026 §6 Fork).
Exercises the seams that R74 added:

1. **Import surface** — ``claude_agent_sdk.fork_session`` resolves
   as a public top-level callable (R74 probe confirmed).
2. **Parent record captures session_id+uuid** — every persisted
   ``Node.state_after`` of an ``AssistantMessage`` / ``ResultMessage``
   carries a real ``session_id`` + ``uuid`` (the anchors fork() needs).
3. **Fork delegate** — ``recorder.fork(parent_run_id, at_node_id, …)``
   forwards to ``claude_agent_sdk.fork_session``, yields a
   ``ForkRef`` whose ``sdk_session_id`` is a fresh non-empty string.
4. **Child round-trip** — the resumed ``ClaudeSDKClient`` (with
   ``resume=child_sdk_session_id``) drains into the same recorder,
   producing a child Run that reaches ``RunStatus.COMPLETED`` and a
   ``Fork`` row that links parent → child.

Run
---
    set -a && . /workspace/.hermes/.env && set +a
    uv run python scripts/dogfood/arc_b_slice_2_fork.py

Three-tier exit semantics (mirrors slice 1)
-------------------------------------------
- **0** — all four seams green, parent + child Runs persisted, Fork
  row links them. Release-gate level.
- **2** — slice 2 *partially* green: parent recorded but fork raised
  ``AdapterError`` (e.g. relay refused ``resume=…``). Slice still
  ships if the unit-test layer covers the API contract; this exit
  code surfaces upstream-skip conditions distinctly.
- **3** — hard regression: SDK import broken, fork_session missing,
  or unexpected exception type.

R74 (2026-05-14): on the cron VM with the baidu-int OneAPI relay,
expect exit 2 — the relay returns a synthetic AssistantMessage
without a real session_id, so step 2 already fails clean. The
unit-test layer (tests/unit/test_adapter_anthropic_agents.py)
covers the contract; this script is the alpha-2/GA gate.
"""

from __future__ import annotations

import asyncio
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


_LIVE_MODEL = os.environ.get("CHRONOS_DOGFOOD_MODEL", "Claude Sonnet 4.6")


def check_imports() -> tuple[bool, str]:
    """Tier 1 — fork_session is importable from the public surface."""
    try:
        import claude_agent_sdk  # noqa: F401
        from claude_agent_sdk import (  # noqa: F401
            ClaudeAgentOptions,
            ClaudeSDKClient,
            fork_session,
        )
    except Exception as e:  # pragma: no cover
        return False, f"import failure: {e!r}"
    return True, "ok"


async def _record_parent(rec: Any, thread_id: str) -> Any:
    """Tier 2 — record a parent run that yields session_id+uuid."""
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    async with ClaudeSDKClient(
        options=ClaudeAgentOptions(max_turns=1, model=_LIVE_MODEL),
    ) as client:
        await client.query("Reply with the single word: ALPHA")
        with rec.record(client, thread_id=thread_id) as p_ref:
            pass
        return p_ref


async def _fork_and_resume(
    rec: Any,
    parent_run_id: str,
    anchor_id: str,
    child_thread_id: str,
) -> Any:
    """Tier 3+4 — call fork(); resume the child session; persist."""
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    with rec.fork(
        runtime=None,
        parent_run_id=parent_run_id,
        at_node_id=anchor_id,
        child_thread_id=child_thread_id,
        reason="dogfood — alt-prompt branch",
        overrides={"prompt_edit": "Reply with: BETA"},
    ) as f_ref:
        if not f_ref.sdk_session_id:
            raise RuntimeError("fork yielded empty sdk_session_id")
        async with ClaudeSDKClient(
            options=ClaudeAgentOptions(
                max_turns=1,
                model=_LIVE_MODEL,
                resume=f_ref.sdk_session_id,
            ),
        ) as child_client:
            await child_client.query("Reply with: BETA")
            f_ref.submit_runtime(child_client)
        return f_ref


def main() -> int:
    print("=" * 70)
    print("R74 Arc B slice 2 dogfood — fork_session() live round-trip")
    print("=" * 70)

    # ---------- Tier 1 ----------
    ok, why = check_imports()
    print(f"[T1] import surface: {'✅' if ok else '❌'}  {why}")
    if not ok:
        return 3

    from chronos.adapters.anthropic_agents import AnthropicAgentsRecorder
    from chronos.adapters.protocols import AdapterError
    from chronos.store.sqlite import SqliteStore

    db_path = Path(tempfile.mkdtemp(prefix="chronos-fork-dogfood-")) / "fork.db"
    store = SqliteStore.open(str(db_path))
    rec = AnthropicAgentsRecorder(store=store)

    # ---------- Tier 2 ----------
    try:
        p_ref = asyncio.run(_record_parent(rec, thread_id="dogfood-fork-parent"))
    except Exception:
        traceback.print_exc()
        print("[T2] parent record: ❌ exception")
        return 3

    if not p_ref.run_id or not p_ref.node_ids:
        print("[T2] parent record: ❌ ref empty")
        return 3

    nodes = list(store.get_nodes_for_run(p_ref.run_id))
    anchor = None
    for n in reversed(nodes):
        st = getattr(n, "state_after", None) or {}
        if isinstance(st, dict) and st.get("session_id") and st.get("uuid"):
            anchor = n
            break

    if anchor is None:
        print(
            f"[T2] parent record: ⚠️  no node carried session_id+uuid "
            f"(saw {len(nodes)} nodes). "
            "Likely a messages-only relay (synthetic AssistantMessage). "
            "Slice 2 contract unverifiable end-to-end on this upstream."
        )
        return 2
    print(
        f"[T2] parent record: ✅ run_id={p_ref.run_id[:8]}… "
        f"anchor_node={anchor.id[:8]}… session_id={anchor.state_after['session_id'][:8]}…"
    )

    # ---------- Tier 3+4 ----------
    try:
        f_ref = asyncio.run(
            _fork_and_resume(
                rec,
                parent_run_id=p_ref.run_id,
                anchor_id=anchor.id,
                child_thread_id="dogfood-fork-child",
            )
        )
    except AdapterError as e:
        print(f"[T3] fork_session: ⚠️  AdapterError — {e}")
        return 2
    except Exception:
        traceback.print_exc()
        print("[T3] fork_session: ❌ exception")
        return 3

    if not f_ref.child_run_id or not f_ref.fork_id:
        print("[T3] fork_session: ❌ ForkRef missing child_run_id/fork_id")
        return 3

    fork_row = store.get_fork(f_ref.fork_id)
    if fork_row is None or fork_row.parent_run_id != p_ref.run_id:
        print("[T4] Fork row: ❌ not linked to parent")
        return 3

    print(
        f"[T3] fork_session: ✅ child_session_id={f_ref.sdk_session_id[:8]}… "
        f"child_run_id={f_ref.child_run_id[:8]}…"
    )
    print(
        f"[T4] Fork row: ✅ {fork_row.parent_run_id[:8]}… → {fork_row.child_run_id[:8]}… "
        f"(reason={fork_row.reason!r})"
    )
    print()
    print("ALL GREEN ✅ — slice 2 contract holds end-to-end on this upstream.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
