"""Canonical data model for Chronos traces.

These Pydantic models are the source-of-truth schema. Everything
(adapters, store, diff engine, API) serialises to/from these types.

The table schema in ``src/chronos/store/migrations/001_init.sql`` is the
persistence projection of these models. Keep them in sync; when you change
one, change the other in the same commit and bump SCHEMA_VERSION.

See ``docs/decisions/ADR-003-sqlite-schema.md`` for rationale behind
every field.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# SemVer string — MUST match migrations/NNN_init.sql's inserted value.
SCHEMA_VERSION = "0.1.0"


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class NodeKind(StrEnum):
    """Kinds of nodes in a reasoning tree.

    MUST match the CHECK constraint on ``nodes.kind`` in the SQL schema.
    """

    LLM = "llm"
    TOOL = "tool"
    FN = "fn"
    ROUTER = "router"
    FORK = "fork"
    END = "end"


class RunStatus(StrEnum):
    """Run lifecycle states.

    MUST match the CHECK constraint on ``runs.status`` in the SQL schema.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    FORKED = "forked"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class Usage(BaseModel):
    """Token & cost usage for a single LLM node (where applicable)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens + self.reasoning_tokens


# ---------------------------------------------------------------------------
# Core entities — one pydantic class per table in 001_init.sql
# ---------------------------------------------------------------------------


class Run(BaseModel):
    """A recorded agent execution (maps 1:1 to ``runs`` table)."""

    id: str  # UUID4 str
    adapter: str  # 'langgraph', 'autogen', ...
    adapter_thread_id: str
    status: RunStatus = RunStatus.PENDING
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None
    task_description: str | None = None
    initial_state: dict[str, Any] = Field(default_factory=dict)
    final_state: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_times(self) -> Run:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must be >= started_at")
        return self


class Node(BaseModel):
    """A single executed graph node (maps 1:1 to ``nodes`` table)."""

    id: str  # UUID4 str
    run_id: str
    step_index: int = Field(ge=0)
    node_name: str  # semantic key for alignment (see ADR-002 finding #3)
    kind: NodeKind

    # Causal chain: within-run parent usually; for the first node of a forked
    # run, this points across runs to the fork source node (see ADR-003 §3.5).
    parent_node_id: str | None = None

    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None
    state_after: dict[str, Any] = Field(default_factory=dict)

    # LLM-specific (nullable unless kind == LLM)
    model_name: str | None = None
    usage: Usage | None = None
    cost_usd_cents: int | None = None

    # Tool-specific (nullable unless kind == TOOL)
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: dict[str, Any] | None = None
    error_message: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_times(self) -> Node:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must be >= started_at")
        return self

    @field_validator("node_name")
    @classmethod
    def _non_empty_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("node_name must be non-empty")
        return v


class Fork(BaseModel):
    """Cross-run fork link (maps 1:1 to ``forks`` table)."""

    id: str  # UUID4 str
    parent_run_id: str
    parent_node_id: str
    child_run_id: str
    created_at: datetime = Field(default_factory=_utcnow)
    edited_fields: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None

    @model_validator(mode="after")
    def _check_not_self(self) -> Fork:
        if self.parent_run_id == self.child_run_id:
            raise ValueError("fork parent_run_id and child_run_id must differ")
        return self


__all__ = [
    "SCHEMA_VERSION",
    "Fork",
    "Node",
    "NodeKind",
    "Run",
    "RunStatus",
    "Usage",
]
