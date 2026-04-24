"""AutoGen adapter (ADR-017, R33-A) — sync-wrap strategy for async-first SDK.

AutoGen's ``autogen-agentchat`` exposes ``Team.run()`` / ``Team.run_stream()``
as coroutines with no sync equivalents. Rather than bifurcate the
``RecorderProtocol`` into sync+async families (rejected Path B in ADR-017),
this adapter keeps the sync CM contract and documents the ``asyncio.run()``
pattern at call sites:

.. code-block:: python

    from chronos.adapters.autogen import autogen_adapter

    with autogen_adapter.build_recorder(store).record(team, thread_id="t1") as ref:
        result = asyncio.run(team.run(task="say hi"))
        ref.submit_result(result)  # optional but recommended

On exit the recorder walks ``result.messages`` and persists one
:class:`~chronos.core.models.Node` per ``BaseChatMessage``. Fork is
deliberately **not** implemented in v0.2.0 (see ADR-017 §Decision).

R33-A scope: record-only. Fork support is tracked as a Phase 3 candidate
in the roadmap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chronos.adapters.protocols import AdapterError, RunRef

from .recorder import AutoGenRecorder

if TYPE_CHECKING:
    from chronos.adapters.langgraph_usage import UsageExtractor
    from chronos.core.models import NodeKind
    from chronos.store import SqliteStore


# ---------------------------------------------------------------------------
# Module-level AdapterProtocol instance (ADR-016 P2, R32-B convention)
# ---------------------------------------------------------------------------


class _AutoGenAdapter:
    """Module-level :class:`AdapterProtocol` implementation for AutoGen.

    Thin factory over :class:`AutoGenRecorder`. Version constraint targets
    ``autogen-agentchat>=0.7,<0.8`` — the 0.7 line is where the
    ``Team.run() -> TaskResult`` shape stabilized, which ADR-017 depends on.

    Construction channels:

    - ``kind_map`` — if provided, maps AutoGen ``BaseChatMessage`` subclass
      names (e.g. ``"TextMessage"``, ``"ToolCallSummaryMessage"``) to
      :class:`NodeKind`. Missing entries fall back to
      :meth:`AutoGenRecorder._default_kind_for`.
    - ``usage_extractor`` — currently **not used**. AutoGen exposes
      ``BaseChatMessage.models_usage`` directly (a
      :class:`autogen_core.models.RequestUsage` with ``prompt_tokens``
      /``completion_tokens``), so the recorder reads usage off the message
      without bridging through ADR-015's callback-based extractor. Passing
      a non-``None`` value raises :class:`AdapterError` to make this loud.
    - ``**adapter_specific``: ``adapter_name: str`` (default ``"autogen"``)
      is the only allowed key — mirrors the Linear adapter.
    """

    name: str = "autogen"
    version_constraint: str = ">=0.7,<0.8"

    def build_recorder(
        self,
        store: SqliteStore,
        *,
        kind_map: dict[str, NodeKind] | None = None,
        usage_extractor: UsageExtractor | None = None,
        **adapter_specific: Any,
    ) -> AutoGenRecorder:
        """Construct an :class:`AutoGenRecorder` bound to ``store``.

        See class docstring for channel semantics.
        """
        if usage_extractor is not None:
            raise AdapterError(
                "autogen_adapter.build_recorder(): AutoGen reads usage "
                "directly from BaseChatMessage.models_usage — the ADR-015 "
                "usage_extractor callback is not wired in. Pass None."
            )
        allowed: set[str] = {"adapter_name"}
        extra = set(adapter_specific) - allowed
        if extra:
            raise AdapterError(
                "autogen_adapter.build_recorder() got unknown adapter-specific "
                f"kwargs: {sorted(extra)}; allowed: {sorted(allowed)}"
            )
        adapter_name = adapter_specific.get("adapter_name", "autogen")
        return AutoGenRecorder(store, adapter_name=adapter_name, kind_map=kind_map)


autogen_adapter = _AutoGenAdapter()
"""Module-level :class:`AdapterProtocol` instance for the AutoGen adapter.

Satisfies :class:`~chronos.adapters.protocols.AdapterProtocol` structurally
(verified by ``isinstance()`` via ``@runtime_checkable``). Import from
either :mod:`chronos.adapters.autogen` or :mod:`chronos.adapters`.
"""


__all__ = [
    "AdapterError",
    "AutoGenRecorder",
    "RunRef",
    "autogen_adapter",
]
