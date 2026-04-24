"""Chronos adapter implementations.

Adapters translate framework-specific execution traces into Chronos's
canonical :class:`~chronos.core.models.Run` + :class:`~chronos.core.models.Node`
records.

v0.2 ships LangGraph (first-class) and Linear (reference). Additional
adapters (AutoGen, CrewAI) are in flight. The cross-adapter contract
lives in :mod:`chronos.adapters.protocols` (ADR-016).
"""

from chronos.adapters.langgraph import LangGraphRecorder
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
    "NodeIdentityResolver",
    "RecorderProtocol",
    "RunRef",
]
