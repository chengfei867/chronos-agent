"""Chronos adapter implementations.

Adapters translate framework-specific execution traces into Chronos's
canonical :class:`~chronos.core.models.Run` + :class:`~chronos.core.models.Node`
records.

v0.2 ships LangGraph (first-class), Linear (reference), and AutoGen
(record-only, ADR-017). CrewAI is a Phase 3 candidate. The cross-adapter
contract lives in :mod:`chronos.adapters.protocols` (ADR-016).

Module-level :class:`AdapterProtocol` instances (``langgraph_adapter``,
``linear_adapter``, ``autogen_adapter``) are the R32-B landing of
ADR-016 P2 — they let code enumerate adapters and call ``build_recorder()``
uniformly without knowing adapter-specific constructor signatures.
"""

from chronos.adapters.autogen import AutoGenRecorder, autogen_adapter
from chronos.adapters.langgraph import LangGraphRecorder, langgraph_adapter
from chronos.adapters.linear import LinearRecorder, LinearRuntime, linear_adapter
from chronos.adapters.protocols import (
    AdapterError,
    AdapterProtocol,
    ForkRef,
    NodeIdentityResolver,
    RecorderProtocol,
    RunRef,
)

__all__ = [
    "AdapterError",
    "AdapterProtocol",
    "AutoGenRecorder",
    "ForkRef",
    "LangGraphRecorder",
    "LinearRecorder",
    "LinearRuntime",
    "NodeIdentityResolver",
    "RecorderProtocol",
    "RunRef",
    "autogen_adapter",
    "langgraph_adapter",
    "linear_adapter",
]
