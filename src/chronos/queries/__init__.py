"""Consumer-side query helpers over the Chronos store.

This package collects small, dependency-free helpers that read the
``state_after`` JSON bag (or other Node fields) and surface common
slice-3 / debugging questions without forcing every consumer to write
the same JOIN by hand.

Helpers here are **internal API** — not part of the published HTTP /
CLI / adapter contracts. They may evolve freely between minor versions.

History:
    - R78 (slice 3a-P2): orphan-detection helpers for Anthropic Agents
      adapter tool-linkage Nodes (ADR-026 §5.1 / §5.1.1).
"""

from __future__ import annotations

from chronos.queries.tool_linkage import (
    unmatched_tool_results,
    unmatched_tool_uses,
)

__all__ = [
    "unmatched_tool_results",
    "unmatched_tool_uses",
]
