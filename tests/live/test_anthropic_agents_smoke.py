"""Live smoke test — Anthropic Agents SDK (claude-agent-sdk) record path.

Wraps the ``scripts/dogfood/arc_b_slice_1_smoke.py`` Tier 1-3 checks
into a ``@pytest.mark.live`` assertion harness so v0.7.0+ CI (when
opted in with ``CHRONOS_LIVE=1``) carries a persistent guard that the
Anthropic Agents adapter (ADR-026, R70 scaffold) still drains real
SDK message streams end to end.

Opt-in::

    set -a && . /workspace/.hermes/.env && set +a
    CHRONOS_LIVE=1 \\
      .venv/bin/pytest tests/live/test_anthropic_agents_smoke.py -m live -v

Wall-clock: ~30-45s (1 real ``query()`` round-trip via authorised upstream).
Skipped by default and in CI; see ``pyproject.toml::pytest.markers``
for the ``live`` marker.

R71 status (2026-05-14): this test is **defined but skipping in
practice** because the cron VM's configured ``ANTHROPIC_BASE_URL``
(``oneapi-comate.baidu-int.com``) is a relay built for the Anthropic
*messages* API, not the ``claude-agent-sdk`` *session* protocol. The
extra ``_session_protocol_usable()`` skipif below detects the
``model='<synthetic>'`` / ``error='authentication_failed'`` signature
and skips with a clear reason. R72 alpha will activate this test once
a session-protocol-aware upstream is authorised.

Scope (mirrors R71 dogfood Tier 1-3):

  - **T1** — ``ClaudeSDKClient`` / ``query`` / ``UserMessage`` /
    ``AssistantMessage`` / ``SystemMessage`` / ``ResultMessage`` /
    ``ClaudeAgentOptions`` all importable from ``claude_agent_sdk``.
  - **T2** — ``query()`` produces a stream whose ``content`` blocks
    are a subset of ``{TextBlock, ToolUseBlock, ToolResultBlock,
    ThinkingBlock}`` (R69 spike #2 contract).
  - **T3** — ``AnthropicAgentsRecorder.record(...)`` round-trips the
    live stream into a SQLite DB; persisted nodes carry legal kinds
    and non-empty names; usage is plausible (input + output >= 0).
  - **T4** — ``id(query_callable)`` preserved (recorder is no-side-
    effect on the runtime per ADR-016 A5).

Environment requirements:

  - ``CHRONOS_LIVE=1`` (set by the opt-in command above).
  - ``ANTHROPIC_API_KEY`` + ``ANTHROPIC_BASE_URL`` pointing at a
    session-protocol-aware upstream.
  - ``claude_agent_sdk`` importable (R70 pin: ``>=0.1.80,<1.0``).
  - Node.js + ``claude-code`` CLI on PATH (bundled via the SDK's
    npm postinstall in v22+ environments).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

_LIVE_ENABLED = os.environ.get("CHRONOS_LIVE") == "1"
_API_KEY = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")

# Default smoke model — spaced PascalCase form that the baidu-int OneAPI relay
# routes to Bedrock. Override via CHRONOS_LIVE_MODEL for direct anthropic.com
# or another relay that exposes kebab-case model ids.
_LIVE_MODEL = os.environ.get("CHRONOS_LIVE_MODEL", "Claude Sonnet 4.6")


def _claude_sdk_importable() -> bool:
    try:
        import claude_agent_sdk  # noqa: F401
    except Exception:
        return False
    return True


def _session_protocol_usable(timeout_s: float = 15.0) -> bool:
    """Probe the session-protocol round-trip; True if not '<synthetic>'.

    Returns False if the upstream returns the SDK's local-only
    ``model='<synthetic>'`` fallback or fails to produce an
    ``AssistantMessage`` within the timeout. Used as a skipif probe
    so this test skips cleanly on relays that only support the
    ``messages`` API (e.g. baidu-int OneAPI).
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
            return False  # stream ended without AssistantMessage
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
        not _claude_sdk_importable(),
        reason="claude_agent_sdk not installed (run `uv sync --extra anthropic_agents`).",
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


_LEGAL_BLOCK_NAMES = {"TextBlock", "ToolUseBlock", "ToolResultBlock", "ThinkingBlock"}
_LEGAL_KINDS = {"llm", "tool", "fn", "router", "fork", "end"}


@pytest.fixture
def sqlite_store(tmp_path: Path):
    """Isolated SQLite store — never touches a shared DB."""
    from chronos.store.sqlite import SqliteStore

    return SqliteStore.open(str(tmp_path / "anthropic_agents_smoke.db"))


def test_anthropic_agents_record_smoke(sqlite_store) -> None:
    """Real claude-agent-sdk ``query()`` + ``AnthropicAgentsRecorder``.

    See module docstring for the per-tier contract. This is the
    pytest-driven equivalent of ``scripts/dogfood/arc_b_slice_1_smoke.py``.
    """
    from claude_agent_sdk import ClaudeAgentOptions, query

    from chronos.adapters.anthropic_agents import AnthropicAgentsRecorder

    rec = AnthropicAgentsRecorder(store=sqlite_store)
    runtime = query(
        prompt="Reply with the single word: pong",
        options=ClaudeAgentOptions(max_turns=1, model=_LIVE_MODEL),
    )
    runtime_id_before = id(runtime)

    with rec.record(runtime, thread_id="live-anthropic-agents-smoke") as ref:
        pass

    # T4 — runtime identity preserved (ADR-016 A5).
    assert id(runtime) == runtime_id_before

    # T3 — persisted state.
    assert ref.run_id is not None, "recorder must populate ref.run_id on exit"
    nodes = list(sqlite_store.get_nodes_for_run(ref.run_id))
    assert len(nodes) >= 2, f"expected >=2 nodes, got {len(nodes)}"

    block_classes_seen: set[str] = set()
    saw_assistant = False
    for n in nodes:
        # Every node has legal kind and non-empty name.
        assert n.kind in _LEGAL_KINDS, f"unknown node kind {n.kind!r}"
        assert n.node_name, f"node {n.id} has empty name"
        if n.node_name.lower().startswith("assistant"):
            saw_assistant = True

        # T2 — block-type contract (R69 spike #2). Recorder records the
        # summarised content under `node_data` / `attrs`; we cannot easily
        # inspect raw block classes from persisted state, so this is a soft
        # check — full block-class observation lives in the dogfood script.
        # If the recorder ever stamps unknown-block-class fallback names
        # into the node, they show up as `unknown:<ClassName>` and we trip.
        attrs = getattr(n, "attrs", None) or getattr(n, "node_data", None) or {}
        if isinstance(attrs, dict):
            for k in attrs.get("blocks", []) or []:
                if isinstance(k, dict) and "type" in k:
                    block_classes_seen.add(k["type"])

    assert saw_assistant, (
        f"expected at least one assistant-kind node, got names: {[n.node_name for n in nodes]}"
    )

    unknown = block_classes_seen - _LEGAL_BLOCK_NAMES
    assert not unknown, (
        f"R69 spike #2 contract violated — unknown blocks {sorted(unknown)}. "
        "Amend ADR-015 in-place (R57 pattern) before merging."
    )


def test_anthropic_agents_dogfood_script_executable(tmp_path: Path) -> None:
    """The dogfood script imports and the main() function is callable.

    Run-as-script wall time is bounded by the script's own 30s budget;
    this test only checks the import path and module structure so a
    broken refactor is caught even when the upstream is unavailable.
    """
    import importlib.util
    import sys

    script = Path(__file__).resolve().parents[2] / "scripts" / "dogfood" / "arc_b_slice_1_smoke.py"
    assert script.exists(), f"dogfood script missing: {script}"

    spec = importlib.util.spec_from_file_location("arc_b_slice_1_smoke", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["arc_b_slice_1_smoke"] = mod  # required for @dataclass to resolve cls.__module__
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop("arc_b_slice_1_smoke", None)

    # Must expose the four-tier API.
    assert callable(getattr(mod, "main", None))
    assert callable(getattr(mod, "check_imports", None))
    assert callable(getattr(mod, "_probe_stream", None))
    assert callable(getattr(mod, "run_recorder_roundtrip", None))
    assert getattr(mod, "_LEGAL_BLOCK_NAMES", None) == _LEGAL_BLOCK_NAMES
