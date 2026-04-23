"""Unit + CLI tests for `chronos fork plan` (ADR-008).

Split:
* Pure-helper tests (override parsing, node resolution, validation) — no DB.
* CliRunner-driven tests — full end-to-end with a seeded SQLite DB.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chronos.cli import app
from chronos.cli.fork import (
    ForkCLIError,
    build_plan,
    default_child_thread_id,
    merge_overrides,
    parse_override_token,
    resolve_parent_node,
    validate_overrides_against_state,
)
from chronos.core.models import Node, NodeKind, Run, RunStatus
from chronos.fork_plan import FORK_PLAN_VERSION, load_plan
from chronos.store.sqlite import SqliteStore

runner = CliRunner()


# ---------------------------------------------------------------------------
# parse_override_token
# ---------------------------------------------------------------------------


def test_parse_override_json_number() -> None:
    assert parse_override_token("n=3") == ("n", 3)


def test_parse_override_json_bool() -> None:
    assert parse_override_token("enabled=true") == ("enabled", True)
    assert parse_override_token("enabled=false") == ("enabled", False)


def test_parse_override_json_null() -> None:
    assert parse_override_token("x=null") == ("x", None)


def test_parse_override_json_array() -> None:
    assert parse_override_token("xs=[1,2,3]") == ("xs", [1, 2, 3])


def test_parse_override_falls_back_to_raw_string() -> None:
    k, v = parse_override_token("note=hello world")
    assert (k, v) == ("note", "hello world")


def test_parse_override_empty_value_is_empty_string() -> None:
    # "k=" parses as "" via the fallback (JSON parse of empty string fails).
    assert parse_override_token("k=") == ("k", "")


def test_parse_override_value_with_equals_sign() -> None:
    # The first `=` is the separator; later ones are part of the value.
    assert parse_override_token("eq=a=b=c") == ("eq", "a=b=c")


def test_parse_override_rejects_no_equals() -> None:
    with pytest.raises(ForkCLIError, match="key=value"):
        parse_override_token("oops")


def test_parse_override_rejects_empty_key() -> None:
    with pytest.raises(ForkCLIError, match="empty key"):
        parse_override_token("=value")


# ---------------------------------------------------------------------------
# merge_overrides
# ---------------------------------------------------------------------------


def test_merge_overrides_json_blob_wins_over_kv() -> None:
    result = merge_overrides(
        ["a=1", "b=2"],
        ['{"b": 99, "c": 3}'],
    )
    assert result == {"a": 1, "b": 99, "c": 3}


def test_merge_overrides_later_kv_wins() -> None:
    result = merge_overrides(["x=1", "x=2"], [])
    assert result == {"x": 2}


def test_merge_overrides_rejects_non_object_json() -> None:
    with pytest.raises(ForkCLIError, match="JSON object"):
        merge_overrides([], ["[1,2]"])


def test_merge_overrides_rejects_bad_json() -> None:
    with pytest.raises(ForkCLIError, match="valid JSON"):
        merge_overrides([], ["{not json}"])


# ---------------------------------------------------------------------------
# resolve_parent_node
# ---------------------------------------------------------------------------


def _mk_node(nid: str, step: int, name: str) -> Node:
    t = datetime(2026, 4, 23, tzinfo=UTC)
    return Node(
        id=nid,
        run_id="run-1",
        step_index=step,
        node_name=name,
        kind=NodeKind.FN,
        started_at=t,
        ended_at=t,
        state_after={"step": step},
        metadata={},
    )


def test_resolve_by_node_id() -> None:
    nodes = [_mk_node("n-0", 0, "plan"), _mk_node("n-1", 1, "research")]
    picked = resolve_parent_node(nodes, at_node=None, at_index=None, at_node_id="n-1")
    assert picked.id == "n-1"


def test_resolve_by_index() -> None:
    nodes = [_mk_node("n-0", 0, "plan"), _mk_node("n-1", 1, "research")]
    picked = resolve_parent_node(nodes, at_node=None, at_index=1, at_node_id=None)
    assert picked.node_name == "research"


def test_resolve_by_name_unique() -> None:
    nodes = [_mk_node("n-0", 0, "plan"), _mk_node("n-1", 1, "research")]
    picked = resolve_parent_node(nodes, at_node="research", at_index=None, at_node_id=None)
    assert picked.step_index == 1


def test_resolve_requires_at_least_one_selector() -> None:
    with pytest.raises(ForkCLIError, match="selector required"):
        resolve_parent_node(
            [_mk_node("n-0", 0, "plan")],
            at_node=None,
            at_index=None,
            at_node_id=None,
        )


def test_resolve_rejects_multiple_selectors() -> None:
    with pytest.raises(ForkCLIError, match="exclusive"):
        resolve_parent_node(
            [_mk_node("n-0", 0, "plan")],
            at_node="plan",
            at_index=0,
            at_node_id=None,
        )


def test_resolve_unknown_node_id() -> None:
    with pytest.raises(ForkCLIError, match="not found"):
        resolve_parent_node(
            [_mk_node("n-0", 0, "plan")],
            at_node=None,
            at_index=None,
            at_node_id="nope",
        )


def test_resolve_unknown_index_lists_available() -> None:
    with pytest.raises(ForkCLIError, match=r"available: \[0\]"):
        resolve_parent_node(
            [_mk_node("n-0", 0, "plan")],
            at_node=None,
            at_index=5,
            at_node_id=None,
        )


def test_resolve_unknown_name_lists_available() -> None:
    with pytest.raises(ForkCLIError, match=r"available names: \['plan'\]"):
        resolve_parent_node(
            [_mk_node("n-0", 0, "plan")],
            at_node="missing",
            at_index=None,
            at_node_id=None,
        )


def test_resolve_ambiguous_name_points_to_indices() -> None:
    # Router/loop graph: `step` node appears twice.
    nodes = [
        _mk_node("n-0", 0, "plan"),
        _mk_node("n-1", 1, "step"),
        _mk_node("n-2", 2, "step"),
    ]
    with pytest.raises(ForkCLIError, match=r"ambiguous.*step indices \[1, 2\]"):
        resolve_parent_node(nodes, at_node="step", at_index=None, at_node_id=None)


# ---------------------------------------------------------------------------
# validate_overrides_against_state
# ---------------------------------------------------------------------------


def test_validate_overrides_all_known_no_warnings() -> None:
    warnings = validate_overrides_against_state(
        {"a": 1},
        {"a": 0, "b": 0},
        allow_new_keys=False,
    )
    assert warnings == []


def test_validate_overrides_unknown_keys_rejected() -> None:
    with pytest.raises(ForkCLIError, match="not present"):
        validate_overrides_against_state(
            {"new_key": 1},
            {"a": 0},
            allow_new_keys=False,
        )


def test_validate_overrides_allow_new_keys_emits_warning() -> None:
    warnings = validate_overrides_against_state(
        {"new_key": 1},
        {"a": 0},
        allow_new_keys=True,
    )
    assert any("new_key" in w for w in warnings)


def test_validate_overrides_type_swap_warning() -> None:
    warnings = validate_overrides_against_state(
        {"a": "now a string"},
        {"a": 0},
        allow_new_keys=False,
    )
    assert any("int" in w and "str" in w for w in warnings)


def test_validate_overrides_none_is_fine() -> None:
    # None → X and X → None should not trigger type warnings.
    warnings = validate_overrides_against_state(
        {"a": None, "b": "x"},
        {"a": "old", "b": None},
        allow_new_keys=False,
    )
    assert warnings == []


def test_validate_overrides_no_state_after_rejects_with_overrides() -> None:
    with pytest.raises(ForkCLIError, match="no state_after"):
        validate_overrides_against_state(
            {"a": 1},
            None,
            allow_new_keys=False,
        )


def test_validate_overrides_no_state_after_allow_new_keys() -> None:
    warnings = validate_overrides_against_state(
        {"a": 1},
        None,
        allow_new_keys=True,
    )
    assert warnings == []


# ---------------------------------------------------------------------------
# build_plan + default_child_thread_id
# ---------------------------------------------------------------------------


def _mk_run(run_id: str = "run-1", thread: str = "t-main") -> Run:
    t = datetime(2026, 4, 23, tzinfo=UTC)
    return Run(
        id=run_id,
        adapter="langgraph",
        adapter_thread_id=thread,
        status=RunStatus.COMPLETED,
        started_at=t,
        ended_at=t,
        task_description="demo",
        initial_state={},
        final_state={},
        tags=[],
        metadata={},
    )


def test_default_child_thread_id_uses_parent_thread() -> None:
    run = _mk_run(thread="my-thread")
    tid = default_child_thread_id(run)
    assert tid.startswith("my-thread-fork-")
    assert len(tid.split("-fork-")[-1]) == 8


def test_build_plan_uses_default_child_thread_id_when_missing() -> None:
    run = _mk_run(thread="abc")
    node = _mk_node("n-1", 1, "research")
    plan = build_plan(
        parent_run=run,
        parent_node=node,
        overrides={"x": 1},
        child_thread_id=None,
        reason=None,
        tags=[],
    )
    assert plan.child_thread_id.startswith("abc-fork-")
    assert plan.parent_node_index == 1
    assert plan.parent_node_name == "research"


# ---------------------------------------------------------------------------
# End-to-end CLI tests via CliRunner
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    """DB with one run (3 nodes: plan, research, draft) — research has state_after."""
    db_path = tmp_path / "chronos.db"
    t = datetime(2026, 4, 23, tzinfo=UTC)
    store = SqliteStore.open(db_path)
    try:
        store.put_run(
            Run(
                id="r1",
                adapter="langgraph",
                adapter_thread_id="t-main",
                status=RunStatus.COMPLETED,
                started_at=t,
                ended_at=t,
                task_description="demo",
                initial_state={"task": "demo"},
                final_state={"final": "ok"},
                tags=[],
                metadata={},
            )
        )
        names_and_state = [
            ("plan", {"plan": "do it"}),
            ("research", {"plan": "do it", "research": "original"}),
            ("draft", {"plan": "do it", "research": "original", "draft": "v1"}),
        ]
        for i, (name, state) in enumerate(names_and_state):
            store.put_node(
                Node(
                    id=f"n{i}",
                    run_id="r1",
                    step_index=i,
                    node_name=name,
                    kind=NodeKind.FN,
                    parent_node_id=(f"n{i - 1}" if i > 0 else None),
                    started_at=t,
                    ended_at=t,
                    state_after=state,
                    metadata={},
                )
            )
    finally:
        store.close()
    return db_path


def test_cli_fork_plan_writes_default_file(seeded_db: Path, tmp_path: Path) -> None:
    out = tmp_path / "fork_plan.json"
    result = runner.invoke(
        app,
        [
            "--",
            "fork",
            "plan",
            "r1",
            "--at-node",
            "research",
            "--override",
            'research="v2"',
            "--reason",
            "swap prompt",
            "--out",
            str(out),
            "--db",
            str(seeded_db),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert out.exists()
    loaded = load_plan(out)
    assert loaded.parent_run_id == "r1"
    assert loaded.parent_node_name == "research"
    assert loaded.parent_node_index == 1
    assert loaded.overrides == {"research": "v2"}
    assert loaded.reason == "swap prompt"
    assert loaded.plan_version == FORK_PLAN_VERSION
    # Preview mentions both the parent run and fork point.
    assert "r1" in result.stdout
    assert "research" in result.stdout


def test_cli_fork_plan_json_to_stdout(seeded_db: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--",
            "fork",
            "plan",
            "r1",
            "--at-index",
            "1",
            "--override",
            'research="v2"',
            "--json",
            "--db",
            str(seeded_db),
        ],
    )
    assert result.exit_code == 0
    # --json mode: stdout is valid JSON (modulo rich's pretty printer).
    # print_json produces real JSON; parse it.
    parsed = json.loads(result.stdout)
    assert parsed["parent_run_id"] == "r1"
    assert parsed["overrides"] == {"research": "v2"}


def test_cli_fork_plan_unknown_run(seeded_db: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--",
            "fork",
            "plan",
            "nope",
            "--at-index",
            "0",
            "--db",
            str(seeded_db),
        ],
    )
    assert result.exit_code == 1
    assert "no such run" in result.stdout


def test_cli_fork_plan_unknown_override_key_rejected(seeded_db: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--",
            "fork",
            "plan",
            "r1",
            "--at-node",
            "research",
            "--override",
            "brand_new_key=42",
            "--out",
            str(tmp_path / "plan.json"),
            "--db",
            str(seeded_db),
        ],
    )
    assert result.exit_code == 1
    assert "not present in parent state_after" in result.stdout
    assert not (tmp_path / "plan.json").exists()


def test_cli_fork_plan_allow_new_keys(seeded_db: Path, tmp_path: Path) -> None:
    out = tmp_path / "plan.json"
    result = runner.invoke(
        app,
        [
            "--",
            "fork",
            "plan",
            "r1",
            "--at-node",
            "research",
            "--override",
            "brand_new_key=42",
            "--allow-new-keys",
            "--out",
            str(out),
            "--db",
            str(seeded_db),
        ],
    )
    assert result.exit_code == 0, result.stdout
    loaded = load_plan(out)
    assert loaded.overrides == {"brand_new_key": 42}


def test_cli_fork_plan_requires_selector(seeded_db: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--",
            "fork",
            "plan",
            "r1",
            "--db",
            str(seeded_db),
        ],
    )
    assert result.exit_code == 1
    assert "selector required" in result.stdout


def test_cli_fork_plan_conflicting_selectors(seeded_db: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--",
            "fork",
            "plan",
            "r1",
            "--at-node",
            "research",
            "--at-index",
            "1",
            "--db",
            str(seeded_db),
        ],
    )
    assert result.exit_code == 1
    assert "exclusive" in result.stdout


def test_cli_fork_plan_override_json_blob(seeded_db: Path, tmp_path: Path) -> None:
    out = tmp_path / "plan.json"
    result = runner.invoke(
        app,
        [
            "--",
            "fork",
            "plan",
            "r1",
            "--at-index",
            "1",
            "--override-json",
            '{"research": "from-blob"}',
            "--out",
            str(out),
            "--db",
            str(seeded_db),
        ],
    )
    assert result.exit_code == 0, result.stdout
    loaded = load_plan(out)
    assert loaded.overrides == {"research": "from-blob"}


def test_cli_fork_plan_roundtrip_feeds_recorder_kwargs(seeded_db: Path, tmp_path: Path) -> None:
    out = tmp_path / "plan.json"
    res = runner.invoke(
        app,
        [
            "--",
            "fork",
            "plan",
            "r1",
            "--at-node",
            "research",
            "--override",
            'research="v2"',
            "--reason",
            "r",
            "--tag",
            "demo",
            "--child-thread-id",
            "custom-thread",
            "--out",
            str(out),
            "--db",
            str(seeded_db),
        ],
    )
    assert res.exit_code == 0, res.stdout
    plan = load_plan(out)
    kwargs = plan.recorder_kwargs()
    # Exactly the keys LangGraphRecorder.fork accepts (none extra).
    assert set(kwargs.keys()) == {
        "parent_run_id",
        "at_node_id",
        "overrides",
        "child_thread_id",
        "reason",
        "tags",
    }
    assert kwargs["child_thread_id"] == "custom-thread"
    assert kwargs["overrides"] == {"research": "v2"}


# ---------------------------------------------------------------------------
# --emit python (R22 / ADR-013 alt C)
# ---------------------------------------------------------------------------


def test_cli_fork_plan_emit_python_writes_valid_stub(seeded_db: Path, tmp_path: Path) -> None:
    """--emit python writes a fork_stub.py that compiles."""
    out = tmp_path / "fork_stub.py"
    result = runner.invoke(
        app,
        [
            "--",
            "fork",
            "plan",
            "r1",
            "--at-node",
            "research",
            "--override",
            "research=override-value",
            "--emit",
            "python",
            "--out",
            str(out),
            "--db",
            str(seeded_db),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert out.exists()
    src = out.read_text(encoding="utf-8")
    # Must compile under Python 3.11+.
    compile(src, str(out), "exec")
    # Must include the fork kwargs inline, not reference a JSON file.
    assert "parent_run_id=" in src
    assert "at_node_id=" in src
    assert "TODO(user)" in src
    # Preview should confirm stub was written + hint how to run it.
    assert str(out) in result.stdout or out.name in result.stdout
    assert "fill the two TODO(user) blocks" in result.stdout


def test_cli_fork_plan_emit_python_default_filename(seeded_db: Path, tmp_path: Path) -> None:
    """Without --out, --emit python defaults to ./fork_stub.py (cwd-relative)."""
    import os

    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = runner.invoke(
            app,
            [
                "--",
                "fork",
                "plan",
                "r1",
                "--at-node",
                "research",
                "--emit",
                "python",
                "--db",
                str(seeded_db),
            ],
        )
    finally:
        os.chdir(cwd)
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "fork_stub.py").exists()


def test_cli_fork_plan_emit_invalid_format_errors(seeded_db: Path, tmp_path: Path) -> None:
    """--emit with an unknown value must exit with a clear error."""
    result = runner.invoke(
        app,
        [
            "--",
            "fork",
            "plan",
            "r1",
            "--at-node",
            "research",
            "--emit",
            "yaml",
            "--out",
            str(tmp_path / "out"),
            "--db",
            str(seeded_db),
        ],
    )
    assert result.exit_code == 1
    assert "unknown --emit value" in result.stdout
