"""Anthropic Agents SDK adapter — public package (R70, ADR-026, Arc B slice 1).

Fourth Chronos adapter, targeting Anthropic's official
``claude-agent-sdk`` (PyPI ``claude-agent-sdk>=0.1.80,<1.0``). Joins
LangGraph (state-graph), AutoGen (message-list), and CrewAI
(event-bus) under :mod:`chronos.adapters` — same
:class:`AdapterProtocol` contract, framework-specific recorder seam.

Recorder seam: the SDK's **async iterator of ``Message`` objects** (R69
spike #2). Both ``ClaudeSDKClient.receive_messages()`` and
``query(prompt, options)`` expose this seam, so the recorder works
unchanged against either of the SDK's two top-level entry points.

R70 scope (``v0.7.0a0`` candidate):

- Optional dep registered in :file:`pyproject.toml`
  (``[project.optional-dependencies] anthropic_agents``) with a
  next-major ``<1.0`` ceiling because the SDK is alpha and patches
  weekly (ADR-026 §7).
- Probe (``HAS_CLAUDE_SDK``, ``CLAUDE_SDK_IMPORT_ERROR``) following the
  ADR-016 / R52 optional-dep precedent.
- :class:`AnthropicAgentsRecorder` with :meth:`record` (real,
  scaffold-tested) and :meth:`fork` (R73 stub, raises
  ``NotImplementedError``).
- Module-level :data:`anthropic_agents_adapter` :class:`AdapterProtocol`
  instance so the dynamic registry in :mod:`chronos.adapters` can
  enumerate it.

R70 explicit non-goals (per CONTEXT §6 / ADR-026 §6):

- No live API call (the recorder accepts a duck-typed runtime in unit
  tests; live smoke is R71).
- No live MCP server.
- No CLI / HTTP API surface change.
- No ``fork()`` semantics — that's R73 via
  ``claude_agent_sdk.fork_session()``.

Usage pattern (designed; live confirmation in R71):

.. code-block:: python

    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
    from chronos.adapters.anthropic_agents import anthropic_agents_adapter

    client = ClaudeSDKClient(options=ClaudeAgentOptions(model="claude-sonnet-4-5"))
    recorder = anthropic_agents_adapter.build_recorder(store)
    with recorder.record(client, thread_id="t1") as ref:
        await client.connect()
        await client.query("...")
        # CM exit drains client.receive_messages() → Run + Nodes
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chronos.adapters.protocols import AdapterError, ForkRef, RunRef

from ._probe import CLAUDE_SDK_IMPORT_ERROR, HAS_CLAUDE_SDK
from .recorder import (
    AnthropicAgentsRecorder,
    AnthropicMessageIterable,
)

if TYPE_CHECKING:
    from chronos.adapters.langgraph_usage import UsageExtractor
    from chronos.core.models import NodeKind
    from chronos.store import SqliteStore


# ---------------------------------------------------------------------------
# Module-level AdapterProtocol instance (ADR-016 P2, R32-B convention)
# ---------------------------------------------------------------------------


class _AnthropicAgentsAdapter:
    """Module-level :class:`AdapterProtocol` implementation for the
    Anthropic Agents SDK.

    Thin factory over :class:`AnthropicAgentsRecorder`. Version
    constraint pins to ``claude-agent-sdk>=0.1.80,<1.0`` per ADR-026 §7
    + R69 spike #3.3b: the SDK is at 0.1.x alpha (Development Status ::
    3 - Alpha), patches weekly with additive Message subclasses, and we
    don't want bump-round churn — so we use a next-major ceiling rather
    than the next-minor ``<2.0`` ADR-022 used for CrewAI 1.x stable.

    Construction channels (mirroring the CrewAI adapter precedent):

    - ``kind_map`` — maps SDK Message class names (e.g.
      ``"AssistantMessage"``, ``"ToolUseBlock"``) to
      :class:`NodeKind`. Missing entries fall back to
      :data:`chronos.adapters.anthropic_agents.recorder._DEFAULT_KIND_MAP`.
    - ``usage_extractor`` — **not used**. The SDK exposes ``usage`` on
      ``AssistantMessage`` / ``ResultMessage`` directly as a dict; the
      recorder projects Anthropic field names
      (``input_tokens``/``output_tokens``) onto Chronos's canonical
      :class:`~chronos.core.models.Usage` schema. Passing a non-``None``
      ``usage_extractor`` raises :class:`AdapterError` to make the
      design choice loud (mirrors AutoGen + CrewAI).
    - ``**adapter_specific``: currently only ``adapter_name: str``
      (default ``"anthropic_agents"``) is supported.
    """

    name: str = "anthropic_agents"
    version_constraint: str = ">=0.1.80,<1.0"

    def build_recorder(
        self,
        store: SqliteStore,
        *,
        kind_map: dict[str, NodeKind] | None = None,
        usage_extractor: UsageExtractor | None = None,
        **adapter_specific: Any,
    ) -> AnthropicAgentsRecorder:
        """Construct an :class:`AnthropicAgentsRecorder` bound to ``store``."""
        if usage_extractor is not None:
            raise AdapterError(
                "anthropic_agents_adapter.build_recorder(): the SDK reads "
                "usage directly from AssistantMessage.usage / "
                "ResultMessage.usage — the ADR-015 usage_extractor callback "
                "is not wired in. Pass None."
            )
        allowed: set[str] = {"adapter_name"}
        extra = set(adapter_specific) - allowed
        if extra:
            raise AdapterError(
                "anthropic_agents_adapter.build_recorder() got unknown "
                f"adapter-specific kwargs: {sorted(extra)}; "
                f"allowed: {sorted(allowed)}"
            )
        adapter_name = adapter_specific.get("adapter_name", "anthropic_agents")
        return AnthropicAgentsRecorder(
            store,
            adapter_name=adapter_name,
            kind_map=kind_map,
        )


anthropic_agents_adapter = _AnthropicAgentsAdapter()
"""Module-level :class:`AdapterProtocol` instance for the Anthropic Agents
SDK adapter.

Satisfies :class:`~chronos.adapters.protocols.AdapterProtocol` structurally
(verified by ``isinstance()`` via ``@runtime_checkable``). Import from
either :mod:`chronos.adapters.anthropic_agents` or :mod:`chronos.adapters`.
"""


__all__ = [
    "CLAUDE_SDK_IMPORT_ERROR",
    "HAS_CLAUDE_SDK",
    "AdapterError",
    "AnthropicAgentsRecorder",
    "AnthropicMessageIterable",
    "ForkRef",
    "RunRef",
    "anthropic_agents_adapter",
]
