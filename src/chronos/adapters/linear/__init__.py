"""Linear-pipeline reference adapter (ADR-014 R1 impl, R28).

A minimal, zero-dependency recorder implementation that conforms to
`RecorderProtocol` (ADR-016). Exists to prove the Protocol can be filled
by a non-LangGraph runtime. Event model is intentionally similar to
LangGraph (discrete step → state snapshot); the R27 risks doc R-1
documents this limitation — real event-model divergence testing
requires AutoGen and is deferred to Phase 2 proper.

A `LinearRuntime` is a sequence of ``(node_name, step_fn)`` pairs where
each ``step_fn: dict -> dict`` takes the current state and returns the
next state. `LinearRecorder` wraps execution to capture each step as a
Chronos `Node`.
"""

from __future__ import annotations

from .recorder import (
    AdapterError,
    ForkRef,
    LinearRecorder,
    LinearRuntime,
    RunRef,
    StepFn,
)

__all__ = [
    "AdapterError",
    "ForkRef",
    "LinearRecorder",
    "LinearRuntime",
    "RunRef",
    "StepFn",
]
