"""Unit tests for :mod:`chronos.fork_plan` — the portable artifact format."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chronos import __version__
from chronos.fork_plan import (
    FORK_PLAN_VERSION,
    ForkPlan,
    ForkPlanError,
    load_plan,
    plan_from_dict,
)

# ---------------------------------------------------------------------------
# ForkPlan.recorder_kwargs — the fields handed off to recorder.fork()
# ---------------------------------------------------------------------------


def test_recorder_kwargs_minimal() -> None:
    plan = ForkPlan(
        parent_run_id="run-1",
        parent_node_id="node-1",
        parent_node_name="research",
        parent_node_index=2,
        child_thread_id="t1-fork-abc",
        overrides={"research": "v2"},
    )
    kwargs = plan.recorder_kwargs()
    assert kwargs == {
        "parent_run_id": "run-1",
        "at_node_id": "node-1",
        "overrides": {"research": "v2"},
        "child_thread_id": "t1-fork-abc",
    }


def test_recorder_kwargs_includes_optional_only_when_set() -> None:
    plan = ForkPlan(
        parent_run_id="r",
        parent_node_id="n",
        parent_node_name="x",
        parent_node_index=0,
        child_thread_id="t-fork",
        overrides={},
        reason="swap model",
        tags=["alt"],
        task_description="fork: alt model",
    )
    kwargs = plan.recorder_kwargs()
    assert kwargs["reason"] == "swap model"
    assert kwargs["tags"] == ["alt"]
    assert kwargs["task_description"] == "fork: alt model"


def test_recorder_kwargs_copies_mutables() -> None:
    overrides = {"a": [1, 2, 3]}
    plan = ForkPlan(
        parent_run_id="r",
        parent_node_id="n",
        parent_node_name="x",
        parent_node_index=0,
        child_thread_id="t-fork",
        overrides=overrides,
        tags=["x"],
    )
    kwargs = plan.recorder_kwargs()
    kwargs["overrides"]["a"].append(4)
    kwargs["tags"].append("y")
    assert plan.overrides == {"a": [1, 2, 3]}
    assert plan.tags == ["x"]


# ---------------------------------------------------------------------------
# to_dict / to_json / dump
# ---------------------------------------------------------------------------


def _minimal_plan() -> ForkPlan:
    return ForkPlan(
        parent_run_id="run-1",
        parent_node_id="node-2",
        parent_node_name="research",
        parent_node_index=2,
        child_thread_id="t-fork-01",
        overrides={"research": "alt"},
        reason="swap prompt",
        tags=["demo"],
    )


def test_to_dict_has_stable_key_order() -> None:
    plan = _minimal_plan()
    d = plan.to_dict()
    keys = list(d.keys())
    # Version key comes first so readers can bail early on unknown versions.
    assert keys[0] == "chronos_fork_plan_version"
    # parent_* identifiers come before child_thread_id/overrides.
    assert keys.index("parent_run_id") < keys.index("child_thread_id")
    assert keys.index("child_thread_id") < keys.index("overrides")


def test_to_dict_records_provenance() -> None:
    plan = _minimal_plan()
    d = plan.to_dict()
    assert d["chronos_fork_plan_version"] == FORK_PLAN_VERSION
    assert d["chronos_version"] == __version__
    assert isinstance(d["generated_at"], str) and "T" in d["generated_at"]


def test_to_json_round_trips_unicode() -> None:
    plan = ForkPlan(
        parent_run_id="r",
        parent_node_id="n",
        parent_node_name="研究",
        parent_node_index=0,
        child_thread_id="t-fork",
        overrides={"note": "你好"},
    )
    parsed = json.loads(plan.to_json())
    assert parsed["parent_node_name"] == "研究"
    assert parsed["overrides"]["note"] == "你好"


def test_dump_creates_parent_dirs_and_adds_trailing_newline(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "plan.json"
    plan = _minimal_plan()
    written = plan.dump(target)
    assert written == target
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    reloaded = load_plan(target)
    assert reloaded.parent_run_id == plan.parent_run_id
    assert reloaded.overrides == plan.overrides


# ---------------------------------------------------------------------------
# load_plan / plan_from_dict — validation
# ---------------------------------------------------------------------------


def test_load_plan_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_plan(tmp_path / "nope.json")


def test_load_plan_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json ", encoding="utf-8")
    with pytest.raises(ForkPlanError, match="invalid JSON"):
        load_plan(bad)


def test_plan_from_dict_rejects_non_object() -> None:
    with pytest.raises(ForkPlanError, match="JSON object"):
        plan_from_dict([1, 2])  # type: ignore[arg-type]


def test_plan_from_dict_rejects_missing_version() -> None:
    with pytest.raises(ForkPlanError, match="chronos_fork_plan_version"):
        plan_from_dict({"parent_run_id": "x"})


def test_plan_from_dict_rejects_future_version() -> None:
    with pytest.raises(ForkPlanError, match="unsupported fork plan version"):
        plan_from_dict(
            {
                "chronos_fork_plan_version": 99,
                "parent_run_id": "r",
                "parent_node_id": "n",
                "parent_node_name": "x",
                "parent_node_index": 0,
                "child_thread_id": "t",
                "overrides": {},
            }
        )


def test_plan_from_dict_reports_missing_required() -> None:
    with pytest.raises(ForkPlanError, match="missing required fields"):
        plan_from_dict(
            {
                "chronos_fork_plan_version": FORK_PLAN_VERSION,
                "parent_run_id": "r",
                # missing parent_node_id, parent_node_name, etc.
            }
        )


def test_plan_from_dict_rejects_non_dict_overrides() -> None:
    with pytest.raises(ForkPlanError, match="overrides"):
        plan_from_dict(
            {
                "chronos_fork_plan_version": FORK_PLAN_VERSION,
                "parent_run_id": "r",
                "parent_node_id": "n",
                "parent_node_name": "x",
                "parent_node_index": 0,
                "child_thread_id": "t",
                "overrides": [("a", 1)],
            }
        )


def test_plan_from_dict_rejects_bad_tags() -> None:
    with pytest.raises(ForkPlanError, match="tags"):
        plan_from_dict(
            {
                "chronos_fork_plan_version": FORK_PLAN_VERSION,
                "parent_run_id": "r",
                "parent_node_id": "n",
                "parent_node_name": "x",
                "parent_node_index": 0,
                "child_thread_id": "t",
                "overrides": {},
                "tags": ["ok", 42],
            }
        )
