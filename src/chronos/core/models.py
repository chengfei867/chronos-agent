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

# SemVer string — MUST match the latest applied migration's
# ``UPDATE schema_info SET schema_version = '<value>'`` (or, on a fresh DB,
# the most recent ``INSERT OR IGNORE`` in ``001_init.sql``).
#
# History:
#   0.1.0 — R0/Phase 1: runs / nodes / forks tables (001_init.sql).
#   0.2.0 — R115/Phase 6 RC, ADR-030: additive ``evaluations`` table
#           (002_evaluations.sql). Forward-compatible — a 0.1.0 library
#           opening a 0.2.0 DB just ignores the extra table.
SCHEMA_VERSION = "0.2.0"


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
    """Token & cost usage for a single LLM node (where applicable).

    **Note:** this class intentionally only holds token counts. The
    ``model_name`` for an LLM call is **not** stored here -- it lives on
    :attr:`Node.model_name` (or, as a shorthand, :attr:`Node.model`).
    Three independent dogfood scripts wrote ``node.usage.model_name`` and
    got ``None`` before we wrote this docstring; don't be the fourth.
    See ADR-013 / R20 Finding #2.
    """

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
    """Token counts for this LLM call. Note: ``usage.model_name`` does not
    exist -- see :attr:`model_name` / :attr:`model` for that."""
    cost_usd_cents: int | None = None

    # Tool-specific (nullable unless kind == TOOL)
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: dict[str, Any] | None = None
    error_message: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def model(self) -> str | None:
        """Convenience alias for :attr:`model_name`.

        Exists because three separate dogfood scripts reached for
        ``node.usage.model_name`` (wrong) or ``node.model`` (also wrong,
        but less wrong) before we added this. Prefer ``node.model``
        going forward -- it's shorter and harder to confuse with
        :class:`Usage` token fields. See ADR-013 / R20 Finding #2.
        """
        return self.model_name

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


# ---------------------------------------------------------------------------
# Evaluation (ADR-030, R115) — a scored judgement on a recorded run.
# ---------------------------------------------------------------------------


class EvaluationResult(BaseModel):
    """The shape an evaluator callable returns (ADR-030 §Evaluator API).

    Evaluators are user-supplied callables of the form::

        def evaluator(run: Run, nodes: list[Node]) -> EvaluationResult: ...

    All four fields are optional — the evaluator decides what to populate.
    Convention: ``score`` is "higher = better" (the caller picks the scale)
    and ``passed`` is the boolean-evaluator path. ``rationale`` is free-form
    human-readable; ``metadata`` is a JSON-serialisable dict for evaluator-
    specific extras (e.g. the configured key for ``final_state_key_present``).
    """

    score: float | None = None
    passed: bool | None = None
    rationale: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Evaluation(BaseModel):
    """A persisted evaluator result (maps 1:1 to ``evaluations`` table).

    One row per ``(run_id, evaluator_name)`` — re-running an evaluator
    overwrites the prior row (UNIQUE INDEX, ``INSERT … ON CONFLICT DO
    UPDATE``). See ADR-030 §Schema.
    """

    id: str  # UUID4 str
    run_id: str
    evaluator_name: str
    score: float | None = None
    passed: bool | None = None
    rationale: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("evaluator_name")
    @classmethod
    def _non_empty_evaluator_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("evaluator_name must be non-empty")
        return v


__all__ = [
    "SCHEMA_VERSION",
    "Evaluation",
    "EvaluationResult",
    "Fork",
    "Node",
    "NodeKind",
    "Run",
    "RunStatus",
    "Usage",
]
