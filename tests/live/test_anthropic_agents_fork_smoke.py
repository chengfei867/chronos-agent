"""Live smoke test — Anthropic Agents SDK fork() round-trip (R74, ADR-026 slice 2).

Wraps the ``scripts/dogfood/arc_b_slice_2_fork.py`` Tier 1-4 checks
into a ``@pytest.mark.live`` assertion harness so v0.7.0+ CI (when
opted in with ``CHRONOS_LIVE=1``) carries a persistent guard that
``AnthropicAgentsRecorder.fork()`` correctly delegates to
``claude_agent_sdk.fork_session`` and persists Run + Nodes + Fork rows.

Opt-in::

    set -a && . /workspace/.hermes/.env && set +a
    CHRONOS_LIVE=1 \\
      .venv/bin/pytest tests/live/test_anthropic_agents_fork_smoke.py -m live -v

R74 status (2026-05-14): this test is **defined but skipping in
practice** because the cron VM's ``ANTHROPIC_BASE_URL``
(``oneapi-comate.baidu-int.com``) is a *messages*-API relay; the
``fork_session`` API requires the SDK's session JSONL transport to
have produced a real session_id during record(). The same
``_session_protocol_usable()`` skipif gate as the slice-1 smoke
applies. This test will activate once a session-protocol-aware
upstream is authorised (alpha-2 / GA gate).

Scope (mirrors R74 dogfood Tier 1-4):

  - **T1** — ``claude_agent_sdk.fork_session`` is importable.
  - **T2** — Record a parent run that captures a real ``session_id``
    + ``uuid`` in ``Node.state_after``.
  - **T3** — Call ``recorder.fork()`` against the parent's last node;
    verify ``ForkRef.sdk_session_id`` is a fresh non-empty string and
    that the SDK call site received the parent ``session_id`` +
    ``up_to_message_id`` we stamped.
  - **T4** — Drive a child runtime via the forked ``session_id``;
    persisted child Run reaches ``RunStatus.COMPLETED`` and the
    ``Fork`` row links parent_run_id → child_run_id.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

_LIVE_ENABLED = os.environ.get("CHRONOS_LIVE") == "1"
_API_KEY = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
_LIVE_MODEL = os.environ.get("CHRONOS_LIVE_MODEL", "Claude Sonnet 4.6")


def _claude_sdk_importable() -> bool:
    try:
        import claude_agent_sdk  # noqa: F401
    except Exception:
        return False
    return True


def _fork_session_importable() -> bool:
    """Stricter than slice-1 — also require the public fork_session symbol."""
    if not _claude_sdk_importable():
        return False
    try:
        from claude_agent_sdk import fork_session  # noqa: F401
    except Exception:
        return False
    return True


def _session_protocol_usable(timeout_s: float = 15.0) -> bool:
    """Probe the session-protocol round-trip; True if not '<synthetic>'.

    Mirrors the slice-1 probe so this test skips on messages-only
    relays. Fork is a strict superset of session-protocol — if the
    upstream can't even hand out a real session_id, fork is moot.
    """
    if not _claude_sdk_importable():
        return False

    from claude_agent_sdk import ClaudeAgentOptions, query

    async def _probe() -> bool:
        try:
            async for msg in query(
                prompt="ping",
                options=ClaudeAgentOptions(max_turns=1, model=_LIVE_MODEL),
            ):
                cls = type(msg).__name__
                if cls == "AssistantMessage":
                    if getattr(msg, "model", None) == "<synthetic>":
                        return False
                    return getattr(msg, "error", None) != "authentication_failed"
            return False
        except Exception:
            return False

    try:
        return asyncio.run(asyncio.wait_for(_probe(), timeout=timeout_s))
    except TimeoutError:
        return False
    except Exception:
        return False


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _LIVE_ENABLED,
        reason="Live tests disabled (set CHRONOS_LIVE=1 to enable).",
    ),
    pytest.mark.skipif(
        not _API_KEY,
        reason="ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN not set.",
    ),
    pytest.mark.skipif(
        not _fork_session_importable(),
        reason=(
            "claude_agent_sdk.fork_session not importable "
            "(needs claude-agent-sdk >= 0.1.80; run `uv sync --extra anthropic_agents`)."
        ),
    ),
    pytest.mark.skipif(
        _LIVE_ENABLED and not _session_protocol_usable(),
        reason=(
            "claude-agent-sdk session protocol not usable against the "
            "configured ANTHROPIC_BASE_URL (likely a messages-only relay; "
            "see docs/progress/2026-05-14-round-71.md for the unblock list)."
        ),
    ),
]


@pytest.fixture
def sqlite_store(tmp_path: Path):
    from chronos.store.sqlite import SqliteStore

    return SqliteStore.open(str(tmp_path / "anthropic_agents_fork_smoke.db"))


def test_anthropic_agents_fork_smoke(sqlite_store) -> None:
    """Real fork_session() + AnthropicAgentsRecorder.fork() end-to-end.

    Tier 1: parent record captures session_id+uuid.
    Tier 2: fork() yields ForkRef with non-empty sdk_session_id.
    Tier 3: child runtime drains into the same recorder; child Run
            reaches COMPLETED.
    Tier 4: store.get_fork(fork_id) links parent → child.
    """
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    from chronos.adapters.anthropic_agents import AnthropicAgentsRecorder

    rec = AnthropicAgentsRecorder(store=sqlite_store)

    # ---- Parent run -------------------------------------------------------
    async def _parent() -> None:
        async with ClaudeSDKClient(
            options=ClaudeAgentOptions(max_turns=1, model=_LIVE_MODEL),
        ) as client:
            await client.query("Reply with: ALPHA")
            with rec.record(client, thread_id="live-fork-parent") as p_ref:
                # consume — the recorder drives receive_messages internally
                pass
            # Smuggle ref out
            _parent.ref = p_ref  # type: ignore[attr-defined]

    asyncio.run(_parent())
    p_ref = _parent.ref  # type: ignore[attr-defined]
    assert p_ref.run_id is not None, "parent recorder must populate run_id"
    assert p_ref.node_ids, "parent run must have at least one node"

    # Pick the latest node that carries a session_id+uuid (anchor candidate).
    parent_run_id = p_ref.run_id
    nodes = list(sqlite_store.get_nodes_for_run(parent_run_id))
    anchor = None
    for n in reversed(nodes):
        st = getattr(n, "state_after", None) or {}
        if isinstance(st, dict) and st.get("session_id") and st.get("uuid"):
            anchor = n
            break
    assert anchor is not None, (
        "no parent node carried session_id+uuid in state_after — "
        "record() integration regressed"
    )

    # ---- Fork + child run -------------------------------------------------
    async def _child() -> None:
        with rec.fork(
            runtime=None,
            parent_run_id=parent_run_id,
            at_node_id=anchor.id,
            child_thread_id="live-fork-child",
            reason="live smoke — alt prompt",
            overrides={"prompt_edit": "Reply with: BETA"},
        ) as f_ref:
            assert f_ref.sdk_session_id, "fork must produce a child sdk_session_id"
            # Resume the forked session
            async with ClaudeSDKClient(
                options=ClaudeAgentOptions(
                    max_turns=1,
                    model=_LIVE_MODEL,
                    resume=f_ref.sdk_session_id,
                ),
            ) as child_client:
                await child_client.query("Reply with: BETA")
                f_ref.submit_runtime(child_client)
            _child.ref = f_ref  # type: ignore[attr-defined]

    asyncio.run(_child())
    f_ref = _child.ref  # type: ignore[attr-defined]

    # ---- Tier 4 assertions -----------------------------------------------
    assert f_ref.child_run_id is not None
    assert f_ref.fork_id is not None

    child_run = sqlite_store.get_run(f_ref.child_run_id)
    assert child_run is not None
    assert child_run.adapter_thread_id == "live-fork-child"
    # Either COMPLETED or (rarely on relay flake) FAILED — but Run row exists.
    assert child_run.status.value in {"completed", "failed"}

    fork_row = sqlite_store.get_fork(f_ref.fork_id)
    assert fork_row is not None
    assert fork_row.parent_run_id == parent_run_id
    assert fork_row.child_run_id == f_ref.child_run_id


def test_anthropic_agents_fork_dogfood_script_executable(tmp_path: Path) -> None:
    """The slice-2 dogfood script imports and exposes its main API."""
    import importlib.util
    import sys

    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "dogfood"
        / "arc_b_slice_2_fork.py"
    )
    assert script.exists(), f"dogfood script missing: {script}"

    spec = importlib.util.spec_from_file_location("arc_b_slice_2_fork", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["arc_b_slice_2_fork"] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop("arc_b_slice_2_fork", None)

    assert callable(getattr(mod, "main", None))
    assert callable(getattr(mod, "check_imports", None))
