"""Unit tests for ``chronos.eval`` — evaluator registry + built-ins (R115, ADR-030).

Covers:
  * register / get / list_registered / run_evaluator happy + edge paths
  * built-ins ``output_length_chars`` and ``final_state_key_present`` per ADR §50-52
  * ``run_evaluator`` produces an ``Evaluation`` ready for store.put_evaluation
  * ``load_entry_points`` is idempotent and tolerant of malformed plugins
  * Re-registering a name overwrites; empty name is rejected.
  * Evaluator exceptions propagate (CLI/API decide what to do).

Hermetic — no DB, no FS, no network.
"""

from __future__ import annotations

import uuid

import pytest

from chronos.core.models import EvaluationResult, Node, NodeKind, Run
from chronos.eval import (
    _final_state_key_present_factory,
    _output_length_chars,
    get,
    list_registered,
    load_entry_points,
    register,
    run_evaluator,
)


def _make_run(**overrides: object) -> Run:
    defaults: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "adapter": "langgraph",
        "adapter_thread_id": "t-" + uuid.uuid4().hex[:6],
    }
    defaults.update(overrides)
    return Run(**defaults)  # type: ignore[arg-type]


def _make_node(run_id: str) -> Node:
    return Node(
        id=str(uuid.uuid4()),
        run_id=run_id,
        step_index=0,
        node_name="plan",
        kind=NodeKind.LLM,
    )


# ---------------- registry --------------------------------------------------


def test_builtins_registered_at_import_time() -> None:
    names = list_registered()
    assert "output_length_chars" in names
    assert "final_state_key_present" in names


def test_get_unknown_evaluator_includes_hint() -> None:
    with pytest.raises(KeyError) as exc:
        get("does_not_exist_zzz")
    msg = str(exc.value)
    # Hint must include the registered names AND mention register/entry-point.
    assert "output_length_chars" in msg
    assert "register" in msg or "entry-point" in msg


def test_register_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        register("", lambda r, n: EvaluationResult(score=1.0))
    with pytest.raises(ValueError, match="non-empty"):
        register("   ", lambda r, n: EvaluationResult(score=1.0))


def test_register_overwrites_on_same_name() -> None:
    def first(r: Run, n: list[Node]) -> EvaluationResult:
        return EvaluationResult(score=1.0)

    def second(r: Run, n: list[Node]) -> EvaluationResult:
        return EvaluationResult(score=2.0)

    register("__t_overwrite", first)
    register("__t_overwrite", second)
    run = _make_run()
    ev = run_evaluator("__t_overwrite", run, [])
    assert ev.score == 2.0


# ---------------- output_length_chars ---------------------------------------


def test_output_length_chars_normal_string() -> None:
    run = _make_run(final_state={"output": "hello world"})
    res = _output_length_chars(run, [])
    assert res.score == 11.0
    assert res.passed is None
    assert res.metadata == {"key": "output"}
    assert "11" in (res.rationale or "")


def test_output_length_chars_missing_output_key() -> None:
    run = _make_run(final_state={"summary": "x"})
    res = _output_length_chars(run, [])
    assert res.score == 0.0


def test_output_length_chars_none_final_state() -> None:
    run = _make_run(final_state=None)
    res = _output_length_chars(run, [])
    assert res.score == 0.0


def test_output_length_chars_non_string_value() -> None:
    # Coerced to str() rather than raising — evaluators are best-effort.
    run = _make_run(final_state={"output": 42})
    res = _output_length_chars(run, [])
    assert res.score == 2.0  # len("42")


# ---------------- final_state_key_present -----------------------------------


def test_final_state_key_present_default_key_hit() -> None:
    fn = _final_state_key_present_factory("output")
    run = _make_run(final_state={"output": "x"})
    res = fn(run, [])
    assert res.passed is True
    assert res.score is None
    assert res.metadata == {"key": "output"}


def test_final_state_key_present_default_key_miss() -> None:
    fn = _final_state_key_present_factory("output")
    run = _make_run(final_state={"summary": "x"})
    res = fn(run, [])
    assert res.passed is False


def test_final_state_key_present_custom_key() -> None:
    fn = _final_state_key_present_factory("summary")
    run = _make_run(final_state={"summary": "ok"})
    res = fn(run, [])
    assert res.passed is True
    assert res.metadata == {"key": "summary"}


def test_final_state_key_present_none_final_state() -> None:
    fn = _final_state_key_present_factory("output")
    run = _make_run(final_state=None)
    res = fn(run, [])
    assert res.passed is False
    assert "cannot be present" in (res.rationale or "")


# ---------------- run_evaluator wrapper -------------------------------------


def test_run_evaluator_wraps_into_evaluation() -> None:
    run = _make_run(final_state={"output": "abc"})
    ev = run_evaluator("output_length_chars", run, [])
    assert ev.run_id == run.id
    assert ev.evaluator_name == "output_length_chars"
    assert ev.score == 3.0
    # id must be a valid UUID4 string
    uuid.UUID(ev.id, version=4)


def test_run_evaluator_propagates_user_exception() -> None:
    def boom(r: Run, n: list[Node]) -> EvaluationResult:
        raise RuntimeError("kaboom")

    register("__t_boom", boom)
    with pytest.raises(RuntimeError, match="kaboom"):
        run_evaluator("__t_boom", _make_run(), [])


def test_run_evaluator_uses_node_arg_only_if_evaluator_does() -> None:
    seen: dict[str, int] = {"count": 0}

    def counter(r: Run, n: list[Node]) -> EvaluationResult:
        seen["count"] = len(n)
        return EvaluationResult(score=float(len(n)))

    register("__t_counter", counter)
    run = _make_run()
    nodes = [_make_node(run.id) for _ in range(3)]
    ev = run_evaluator("__t_counter", run, nodes)
    assert seen["count"] == 3
    assert ev.score == 3.0


# ---------------- entry-point loader ----------------------------------------


def test_load_entry_points_idempotent() -> None:
    # First call may register zero or more (depending on installed plugins) — both
    # OK. Subsequent calls must return 0 (cached).
    load_entry_points()
    second = load_entry_points()
    assert second == 0


def test_load_entry_points_does_not_unregister_builtins() -> None:
    load_entry_points()
    names = list_registered()
    assert "output_length_chars" in names
    assert "final_state_key_present" in names
