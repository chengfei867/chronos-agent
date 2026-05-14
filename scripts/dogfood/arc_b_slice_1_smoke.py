"""R71 dogfood — Arc B slice 1 (Anthropic Agents SDK adapter) live smoke probe.

Purpose
-------
Validate the Phase 4 **Arc B slice 1** scaffold (R70) against the *real*
``claude-agent-sdk`` Python package (PyPI ``>=0.1.80,<1.0``, ADR-026 §7).
Exercises the structural seams the recorder relies on:

1. Import surface — ``ClaudeSDKClient`` / ``query`` / ``UserMessage`` /
   ``AssistantMessage`` / ``SystemMessage`` / ``ResultMessage`` resolve.
2. Async-iterator seam — ``query(prompt, options=...)`` yields a
   ``Message`` stream that the recorder's ``_resolve_iterator`` accepts.
3. Block-type contract (R69 spike #2) — observed ``content`` block
   classes are a subset of ``{TextBlock, ToolUseBlock, ToolResultBlock,
   ThinkingBlock}``. Anything else => print a loud warning so a future
   round can amend ADR-015 (R57 in-place pattern).
4. Recorder round-trip — feed the live stream into
   ``AnthropicAgentsRecorder.record(...)``, then assert the persisted
   ``Run`` + ``Node`` rows are well-formed (kinds in legal set, every
   node has a ``name``).

Run
---
    set -a && . /workspace/.hermes/.env && set +a
    uv run python scripts/dogfood/arc_b_slice_1_smoke.py

Three-tier exit semantics
-------------------------
- **0** — all four seams green, recorder produced a real Run with
  >=2 nodes and at least one assistant message. Release-gate level.
- **2** — auth / relay incompatibility detected (e.g. ``baidu-int``
  OneAPI relay returns ``model='<synthetic>'`` ``error='authentication_failed'``
  for a ``query()`` call, or session never produces an
  ``AssistantMessage`` within the 30s budget). The probe still emits a
  structured report so a future round can pick up exactly where this
  one stopped.
- **1** — hard import / SDK-shape failure. Means the optional extra is
  not installed *or* a contract assumption (R69 spike #2) is broken at
  the type level. Release-blocker.

Why this script gracefully tolerates auth failure
-------------------------------------------------
R71 was scheduled as the first live-smoke round but the cron VM's
configured ``ANTHROPIC_BASE_URL`` (``oneapi-comate.baidu-int.com``) is a
relay built for the Anthropic *messages* API, not for the
``claude-agent-sdk`` *session* protocol that wraps the local
``claude-code`` CLI. The CLI can authenticate against the relay for
``messages``, but the *session subprotocol* used by the SDK (which
expects to talk to the official ``claude.ai`` backend or an Anthropic
``Bedrock``/``Vertex`` endpoint) is *not* part of the OneAPI surface.

Concrete observed failure mode (R71 measurement, see progress doc):

  ``query(prompt='hi', options=ClaudeAgentOptions(max_turns=1))``
  emits exactly:
    1. ``SystemMessage(subtype='init', ...)``
    2. ``AssistantMessage(content=[TextBlock(text='Not logged in · Please run /login')], model='<synthetic>', error='authentication_failed', ...)``
    3. ``ResultMessage(subtype='success', is_error=True, stop_reason='stop_sequence', ...)``

The ``model='<synthetic>'`` marker is the SDK's local-only fallback
when no upstream session can be established — a clear signal that the
relay is rejecting the session-protocol handshake (or the auth header
shape).

This script *detects* that signature and exits 2 with a "blocker"
report. When the user authorises a compatible upstream (direct
``ANTHROPIC_API_KEY`` against ``api.anthropic.com``, or a
session-protocol-aware relay), this same script becomes the R72 alpha
release gate without modification.

Notes
-----
- Wall-clock budget: 30s (per query, hard-capped via ``asyncio.wait_for``).
- Touches no shared state — uses a tmp SQLite DB.
- Costs at most ~1 LLM round-trip (a single ``max_turns=1`` query).
- Set ``CHRONOS_DOGFOOD_DEBUG=1`` for verbose per-message dumps.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Allow running from repo root without `pip install -e .`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))


# ---------------------------------------------------------------------------
# Tier 1 — import surface check
# ---------------------------------------------------------------------------


def check_imports() -> tuple[bool, str]:
    """Return (ok, message). On ok=False, the script must exit 1."""
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ClaudeSDKClient,
            ResultMessage,
            SystemMessage,
            UserMessage,
            query,
        )
    except ImportError as e:
        return (
            False,
            f"claude_agent_sdk not importable: {e!r}. "
            "Install with `uv sync --extra anthropic_agents`.",
        )
    # Touch each name so static checkers / readers see we exercised them.
    _ = (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        SystemMessage,
        UserMessage,
        query,
    )
    return True, "All seven required names resolve from `claude_agent_sdk`."


# ---------------------------------------------------------------------------
# Tier 2 — block-type contract check (R69 spike #2)
# ---------------------------------------------------------------------------


_LEGAL_BLOCK_NAMES = {"TextBlock", "ToolUseBlock", "ToolResultBlock", "ThinkingBlock"}


@dataclass
class StreamObservation:
    """What the probe saw on the wire."""

    message_classes: list[str] = field(default_factory=list)
    block_classes: set[str] = field(default_factory=set)
    saw_assistant: bool = False
    saw_synthetic_model: bool = False
    auth_failed: bool = False
    raw_first_text: str | None = None
    error: str | None = None


async def _probe_stream(runtime_factory, *, budget_s: float = 30.0) -> StreamObservation:
    """Consume up to N messages from a fresh runtime, observing classes."""
    obs = StreamObservation()
    try:
        async for msg in _budgeted(runtime_factory(), budget_s):
            cls = type(msg).__name__
            obs.message_classes.append(cls)
            content = getattr(msg, "content", None)
            if cls == "AssistantMessage":
                obs.saw_assistant = True
                if getattr(msg, "model", None) == "<synthetic>":
                    obs.saw_synthetic_model = True
                if getattr(msg, "error", None) == "authentication_failed":
                    obs.auth_failed = True
            if isinstance(content, list):
                for block in content:
                    bcls = type(block).__name__
                    obs.block_classes.add(bcls)
                    if (
                        bcls == "TextBlock"
                        and obs.raw_first_text is None
                        and getattr(block, "text", None)
                    ):
                        obs.raw_first_text = block.text[:120]
            # Cap message count so a misbehaving stream cannot run away.
            if len(obs.message_classes) >= 20:
                break
    except TimeoutError:
        obs.error = f"stream did not complete within {budget_s:.0f}s"
    except Exception as e:  # pragma: no cover — exceptional path
        obs.error = f"{type(e).__name__}: {e}"
    return obs


async def _budgeted(agen: AsyncIterator[Any], budget_s: float) -> AsyncIterator[Any]:
    """Yield from `agen` but enforce a hard wall-clock cap."""
    end = asyncio.get_event_loop().time() + budget_s
    while True:
        remaining = end - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise TimeoutError("budget exhausted")
        try:
            item = await asyncio.wait_for(agen.__anext__(), timeout=remaining)
        except StopAsyncIteration:
            return
        yield item


# ---------------------------------------------------------------------------
# Tier 3 — recorder round-trip (skipped if Tier 2 detected auth failure)
# ---------------------------------------------------------------------------


async def run_recorder_roundtrip(runtime_factory) -> dict[str, Any]:
    """Drive AnthropicAgentsRecorder over a real query() stream.

    Returns a dict with run_id, node_count, kinds. Raises on failure.
    """
    from chronos.adapters.anthropic_agents import AnthropicAgentsRecorder
    from chronos.store.sqlite import SqliteStore

    db = Path(tempfile.gettempdir()) / "chronos_r71_arc_b_smoke.db"
    if db.exists():
        db.unlink()
    store = SqliteStore.open(str(db))
    rec = AnthropicAgentsRecorder(store=store)

    runtime = runtime_factory()
    # The recorder is a sync context manager that consumes an async iterable
    # on exit via asyncio.run. Since *we* are already in an event loop, we
    # need to delegate to a thread to avoid asyncio.run-from-running-loop.
    loop = asyncio.get_event_loop()

    def _drive() -> str:
        with rec.record(runtime, thread_id="r71-arc-b-smoke") as ref:
            pass  # recorder consumes runtime on exit
        return ref.run_id  # type: ignore[return-value]

    run_id = await loop.run_in_executor(None, _drive)
    nodes = list(store.get_nodes_for_run(run_id))
    return {
        "db": str(db),
        "run_id": run_id,
        "node_count": len(nodes),
        "kinds": [n.kind for n in nodes],
        "names": [n.node_name for n in nodes],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    debug = os.environ.get("CHRONOS_DOGFOOD_DEBUG") == "1"

    print("=" * 70)
    print("R71 Arc B slice 1 — Anthropic Agents SDK live smoke probe")
    print("=" * 70)

    # --- Tier 1 ---
    ok, msg = check_imports()
    print(f"\n[T1] Import surface: {'OK' if ok else 'FAIL'}")
    print(f"     {msg}")
    if not ok:
        return 1

    from claude_agent_sdk import ClaudeAgentOptions, query

    # Default to a model name that the baidu-int OneAPI relay accepts
    # (Bedrock-backed Claude Sonnet 4.6 — note the spaced PascalCase form).
    # Override via CHRONOS_DOGFOOD_MODEL for direct anthropic.com or other relays.
    default_model = os.environ.get("CHRONOS_DOGFOOD_MODEL", "Claude Sonnet 4.6")

    def make_runtime():
        # max_turns=1 caps the cost at a single round-trip.
        return query(
            prompt="Reply with exactly the single word: pong",
            options=ClaudeAgentOptions(max_turns=1, model=default_model),
        )

    # --- Tier 2 ---
    print("\n[T2] Probing query() stream (budget 30s)...")
    obs = asyncio.run(_probe_stream(make_runtime, budget_s=30.0))
    print(f"     message classes seen: {obs.message_classes}")
    print(f"     block classes seen:   {sorted(obs.block_classes)}")
    print(f"     saw assistant:        {obs.saw_assistant}")
    print(f"     synthetic model:      {obs.saw_synthetic_model}")
    print(f"     auth failed:          {obs.auth_failed}")
    if obs.raw_first_text:
        print(f"     first text:           {obs.raw_first_text!r}")
    if obs.error:
        print(f"     error:                {obs.error}")

    # Block-type contract (R69 spike #2) — fail loud on unknown blocks.
    unknown = obs.block_classes - _LEGAL_BLOCK_NAMES
    if unknown:
        print(
            f"\n[T2-FAIL] R69 spike #2 contract violated — unknown blocks: "
            f"{sorted(unknown)}. Amend ADR-015 in-place (R57 pattern) "
            "before continuing."
        )
        return 1

    # Auth / relay incompatibility — expected blocker on baidu-int relay.
    if obs.saw_synthetic_model or obs.auth_failed:
        print(
            "\n[T2-BLOCKER] Detected '<synthetic>' model or "
            "authentication_failed marker. The configured "
            f"ANTHROPIC_BASE_URL ({os.environ.get('ANTHROPIC_BASE_URL', '(unset)')}) "
            "is not compatible with the claude-agent-sdk session "
            "protocol. R72 alpha cannot be cut until the relay is "
            "swapped for a session-protocol-aware upstream OR the user "
            "authorises a direct anthropic.com connection.\n"
            "\n"
            "Recommended next step: see docs/progress/2026-05-XX-round-71.md "
            "for the unblock checklist."
        )
        return 2

    if obs.error and not obs.saw_assistant:
        print(
            f"\n[T2-BLOCKER] Stream produced no AssistantMessage within budget "
            f"({obs.error}). Likely upstream hang — same blocker class as the "
            "synthetic-model case. Exit 2."
        )
        return 2

    # --- Tier 3 ---
    print("\n[T3] Recorder round-trip...")
    try:
        result = asyncio.run(run_recorder_roundtrip(make_runtime))
        print(f"     db:         {result['db']}")
        print(f"     run_id:     {result['run_id']}")
        print(f"     node_count: {result['node_count']}")
        print(f"     kinds:      {result['kinds']}")
        print(f"     names:      {result['names']}")
        # Runtime asserts (R64 invariant: dogfood asserts == release gate).
        assert result["node_count"] >= 2, "expected >=2 nodes"
        legal_kinds = {"llm", "tool", "fn", "router", "fork", "end"}
        for k in result["kinds"]:
            assert k in legal_kinds, f"unknown kind {k!r}"
        for n in result["names"]:
            assert n, "every node must have a non-empty name"
    except Exception as e:
        print(f"[T3-FAIL] recorder round-trip failed: {e!r}")
        if debug:
            traceback.print_exc()
        return 1

    print("\n[OK] All tiers green. R72 alpha release gate is open.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
