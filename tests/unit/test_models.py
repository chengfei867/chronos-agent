"""Smoke tests for core data model."""

from __future__ import annotations

from datetime import datetime

from chronos import __version__
from chronos.core import Node, NodeKind, Run, RunStatus, Usage


def test_version_is_set() -> None:
    assert __version__
    assert isinstance(__version__, str)


def test_run_defaults() -> None:
    run = Run(run_id="run_001")
    assert run.run_id == "run_001"
    assert run.status == RunStatus.RUNNING
    assert isinstance(run.started_at, datetime)
    assert run.ended_at is None
    assert run.schema_version == 0


def test_node_requires_run_id() -> None:
    node = Node(
        node_id="n1",
        run_id="run_001",
        step_index=0,
        kind=NodeKind.LLM_CALL,
        payload={"model": "claude-opus-4.7", "messages": []},
    )
    assert node.kind is NodeKind.LLM_CALL
    assert node.parent_node_id is None
    assert node.usage == Usage()


def test_node_kind_is_string_enum() -> None:
    assert NodeKind.LLM_CALL.value == "llm_call"
    assert NodeKind("tool_call") is NodeKind.TOOL_CALL
