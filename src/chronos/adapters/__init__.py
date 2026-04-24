"""Chronos adapter implementations.

Adapters translate framework-specific execution traces into Chronos's
canonical :class:`~chronos.core.models.Run` + :class:`~chronos.core.models.Node`
records.

v0.2 ships LangGraph (first-class) and Linear (reference). Additional
adapters (AutoGen, CrewAI) are in flight. The cross-adapter contract
lives in :mod:`chronos.adapters.protocols` (ADR-016).

Module-level :class:`AdapterProtocol` instances (``langgraph_adapter``,
``linear_adapter``) are the R32-B landing of ADR-016 P2 — they let code
enumerate adapters and call ``build_recorder()`` uniformly without
knowing adapter-specific constructor signatures.
"""

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
    "ForkRef",
    "LangGraphRecorder",
    "LinearRecorder",
    "LinearRuntime",
    "NodeIdentityResolver",
    "RecorderProtocol",
    "RunRef",
    "langgraph_adapter",
    "linear_adapter",
]
