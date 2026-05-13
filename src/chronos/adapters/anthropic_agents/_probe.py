"""Optional-dependency probe for the Anthropic Agents SDK adapter.

R70 (ADR-026, Arc B slice 1). The Anthropic Agents SDK (``claude-agent-sdk``)
is an **optional** extra per ADR-016 convention — the probe lets the rest
of the codebase (unit tests, CLI info-line, dynamic adapter listing)
know whether the runtime dep is importable without forcing every
Chronos install to carry it.

Mirrors the CrewAI / AutoGen probe shape:

- ``HAS_CLAUDE_SDK`` — ``True`` iff ``import claude_agent_sdk`` succeeds.
- ``CLAUDE_SDK_IMPORT_ERROR`` — the captured ``ImportError`` (or ``None``),
  so downstream error messages can quote the underlying reason.

Usage:

.. code-block:: python

    from chronos.adapters.anthropic_agents._probe import HAS_CLAUDE_SDK

    if not HAS_CLAUDE_SDK:
        pytest.skip("claude-agent-sdk not installed")

The probe runs at import time. It is cheap (one try/except) and
side-effect-free: no network, no subprocess, no CLI resolution. The
Node.js ``claude-code`` CLI resolvability is an R71 live-smoke
concern (per R69 spike #3.4) and is probed separately there.
"""

from __future__ import annotations

HAS_CLAUDE_SDK: bool
CLAUDE_SDK_IMPORT_ERROR: ImportError | None

try:
    import claude_agent_sdk as _sdk  # noqa: F401 — probe import only

    HAS_CLAUDE_SDK = True
    CLAUDE_SDK_IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover — covered by env-gated tests
    HAS_CLAUDE_SDK = False
    CLAUDE_SDK_IMPORT_ERROR = exc


def install_hint() -> str:
    """Return a user-facing install-hint string for AdapterError messages."""
    return (
        "claude-agent-sdk is not installed. Install the Anthropic Agents "
        "adapter with: `pip install chronos-agent[anthropic_agents]` "
        "(or `uv sync --extra anthropic_agents`). "
        "See ADR-026 / docs/adapters/anthropic_agents.md for details."
    )


__all__ = [
    "CLAUDE_SDK_IMPORT_ERROR",
    "HAS_CLAUDE_SDK",
    "install_hint",
]
