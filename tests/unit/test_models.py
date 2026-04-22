"""Smoke tests for core data model.

These lock in the pydantic↔SQL schema contract. If you change
``src/chronos/core/models.py`` or ``migrations/001_init.sql``, update
these tests in the same commit.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from chronos import __version__
from chronos.core import SCHEMA_VERSION, Fork, Node, NodeKind, Run, RunStatus, Usage

# --- version / constants ---------------------------------------------------


def test_version_is_set() -> None:
    assert __version__
    assert isinstance(__version__, str)


def test_schema_version_is_semver_string() -> None:
    # Matches the value INSERTed in migrations/001_init.sql.
    assert SCHEMA_VERSION == "0.1.0"


# --- Run -------------------------------------------------------------------


def _new_run(**overrides: object) -> Run:
    defaults = {
        "id": str(uuid.uuid4()),
        "adapter": "langgraph",
        "adapter_thread_id": "thread-xyz",
    }
    defaults.update(overrides)
    return Run(**defaults)  # type: ignore[arg-type]


def test_run_defaults() -> None:
    run = _new_run()
    assert run.status is RunStatus.PENDING
    assert isinstance(run.started_at, datetime)
    assert run.ended_at is None
    assert run.tags == []
    assert run.metadata == {}


def test_run_ended_before_started_rejected() -> None:
    start = datetime.fromisoformat("2026-01-01T12:00:00+00:00")
    end = start - timedelta(seconds=1)
    with pytest.raises(ValidationError, match="ended_at"):
        _new_run(started_at=start, ended_at=end)


# --- Node ------------------------------------------------------------------


def _new_node(**overrides: object) -> Node:
    defaults = {
        "id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "step_index": 0,
        "node_name": "plan",
        "kind": NodeKind.LLM,
    }
    defaults.update(overrides)
    return Node(**defaults)  # type: ignore[arg-type]


def test_node_defaults() -> None:
    node = _new_node()
    assert node.parent_node_id is None
    assert node.state_after == {}
    assert node.usage is None
    assert node.cost_usd_cents is None


def test_node_step_index_non_negative() -> None:
    with pytest.raises(ValidationError):
        _new_node(step_index=-1)


def test_node_name_must_be_non_empty() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        _new_node(node_name="")
    with pytest.raises(ValidationError, match="non-empty"):
        _new_node(node_name="   ")


def test_node_kind_is_string_enum() -> None:
    assert NodeKind.LLM.value == "llm"
    assert NodeKind("tool") is NodeKind.TOOL
    # All kinds match the CHECK constraint in 001_init.sql
    assert {k.value for k in NodeKind} == {
        "llm",
        "tool",
        "fn",
        "router",
        "fork",
        "end",
    }


def test_run_status_values_match_ddl() -> None:
    assert {s.value for s in RunStatus} == {
        "pending",
        "running",
        "completed",
        "failed",
        "forked",
    }


# --- Usage -----------------------------------------------------------------


def test_usage_total_tokens() -> None:
    u = Usage(prompt_tokens=100, completion_tokens=50, reasoning_tokens=10)
    assert u.total_tokens == 160


# --- Fork ------------------------------------------------------------------


def _new_fork(**overrides: object) -> Fork:
    defaults = {
        "id": str(uuid.uuid4()),
        "parent_run_id": "run-A",
        "parent_node_id": "node-X",
        "child_run_id": "run-B",
    }
    defaults.update(overrides)
    return Fork(**defaults)  # type: ignore[arg-type]


def test_fork_requires_different_runs() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        _new_fork(parent_run_id="same", child_run_id="same")


def test_fork_edited_fields_default_empty() -> None:
    fork = _new_fork()
    assert fork.edited_fields == {}
    assert fork.reason is None
