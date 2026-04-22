"""Canonical data model for Chronos traces.

These Pydantic models are the source-of-truth schema. Everything
(adapters, store, diff engine, API) serialises to/from these types.

Schema version: 0 (unstable, pre-v0.1). Will be frozen at v0.1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = 0


def _utcnow() -> datetime:
    return datetime.now(UTC)


class NodeKind(StrEnum):
    """Kinds of events in a reasoning tree."""

    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    AGENT_STATE = "agent_state"
    ERROR = "error"
    BRANCH = "branch"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class Usage(BaseModel):
    """Token & cost usage for a single node (where applicable)."""

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0


class Node(BaseModel):
    """A single event in a reasoning tree.

    The ``payload`` schema depends on ``kind`` — see
    docs/design/architecture.md for the variant table.
    """

    node_id: str
    run_id: str
    parent_node_id: str | None = None
    step_index: int
    kind: NodeKind
    ts: datetime = Field(default_factory=_utcnow)
    duration_ms: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)
    usage: Usage = Field(default_factory=Usage)
    fingerprint: str = ""


class Run(BaseModel):
    """A recorded agent execution."""

    run_id: str
    name: str = ""
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None
    framework: str = "unknown"
    agent_signature: str = ""
    status: RunStatus = RunStatus.RUNNING
    cost_usd: float = 0.0
    total_tokens: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION


class Fork(BaseModel):
    """Record of a fork relationship between runs."""

    fork_id: str
    source_run_id: str
    source_node_id: str
    forked_run_id: str
    edits: dict[str, Any] = Field(default_factory=dict)
    strategy: str = "stable"  # "stable" | "explore"
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "SCHEMA_VERSION",
    "Fork",
    "Node",
    "NodeKind",
    "Run",
    "RunStatus",
    "Usage",
]
