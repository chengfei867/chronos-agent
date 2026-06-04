"""Chronos evaluation/scoring layer (ADR-030, R115).

A minimal-but-honest evaluator surface: a hookable scoring function applied to
one or more recorded runs, results stored alongside the run in the
``evaluations`` table, surfaced in CLI ``compare --eval`` and the frontend
fork-tree / RunList. Explicitly *not* a full eval framework — that's a v2.0+
direction (see ADR-030 §Out of scope).

Evaluator API
=============

A user-supplied evaluator is any callable matching::

    def evaluator(run: Run, nodes: list[Node]) -> EvaluationResult: ...

Evaluators are **registered, not auto-discovered** — register via
:func:`register` (programmatic) or via the ``chronos.evaluators`` entry-point
group (plugin packaging). No magic glob of the user's CWD.

Built-in evaluators
===================

This module ships two evaluators, registered at import time, to anchor the
surface (ADR-030 §50-52):

- ``output_length_chars`` — emits ``score = len(final_state.get("output", ""))``.
  Trivial, always works, useful for "did my fork actually produce more text?"
  comparisons.
- ``final_state_key_present`` — emits ``passed = key in final_state``.
  The key name is configurable via metadata at registration time (default
  ``"output"``). Demonstrates the boolean-evaluator path.

LLM-judge evaluators are **explicitly out of scope for v1.0** (ADR-030 §53)
and live in v1.1+.

Re-running an evaluator on the same run overwrites the prior result via
``INSERT … ON CONFLICT(run_id, evaluator_name) DO UPDATE`` in the store layer
— see :meth:`chronos.store.sqlite.SqliteStore.put_evaluation`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from chronos.core.models import Evaluation, EvaluationResult, Node, Run

# Evaluator callable type.
Evaluator = Callable[[Run, list[Node]], EvaluationResult]

# Module-level registry. Keyed by evaluator name. Built-ins are registered
# below at import time; users add their own via ``register()``.
_REGISTRY: dict[str, Evaluator] = {}


def register(name: str, fn: Evaluator) -> None:
    """Register an evaluator under ``name``.

    Idempotent: re-registering the same ``(name, fn)`` pair is a no-op.
    Re-registering a different ``fn`` under an existing ``name`` overwrites.
    Per ADR-030 §97, evaluator versioning is the user's responsibility —
    rename the evaluator if you change behaviour and want to preserve old
    results separately.

    Args:
        name: Stable identifier used by the CLI (`--evaluator <name>`),
            stored in `evaluations.evaluator_name`. Non-empty string.
        fn: Callable of signature ``(run: Run, nodes: list[Node]) ->
            EvaluationResult``.

    Raises:
        ValueError: If ``name`` is empty.
    """
    if not name or not name.strip():
        raise ValueError("evaluator name must be non-empty")
    _REGISTRY[name] = fn


def get(name: str) -> Evaluator:
    """Resolve an evaluator by name.

    Raises:
        KeyError: If ``name`` is not registered. The exception message
            includes the list of currently-registered names so the CLI
            can surface an actionable hint.
    """
    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(
            f"unknown evaluator: {name!r}. Registered evaluators: {known}. "
            "Use chronos.eval.register() or the 'chronos.evaluators' "
            "entry-point group to add one."
        )
    return _REGISTRY[name]


def list_registered() -> list[str]:
    """Return the sorted list of registered evaluator names."""
    return sorted(_REGISTRY)


def run_evaluator(
    name: str,
    run: Run,
    nodes: list[Node],
) -> Evaluation:
    """Resolve ``name``, invoke the evaluator, and wrap the result in an
    :class:`Evaluation` ready for ``store.put_evaluation``.

    The returned ``Evaluation`` is *not* persisted — the caller (CLI or API)
    decides whether to commit. This split keeps the evaluator API pure
    (no DB) and makes unit-testing trivial.

    Raises:
        KeyError: If ``name`` is not registered.
        Exception: Whatever the evaluator itself raises is propagated. The
            CLI catches and renders an error row; programmatic callers can
            choose to skip or fail.
    """
    fn = get(name)
    result = fn(run, nodes)
    return Evaluation(
        id=str(uuid.uuid4()),
        run_id=run.id,
        evaluator_name=name,
        score=result.score,
        passed=result.passed,
        rationale=result.rationale,
        metadata=result.metadata,
    )


# ---------------------------------------------------------------------------
# Built-in evaluators (ADR-030 §50-52). Registered at import time.
# ---------------------------------------------------------------------------


def _output_length_chars(run: Run, nodes: list[Node]) -> EvaluationResult:
    """Built-in: ``score = len(final_state.get("output", ""))``.

    Always returns a numeric score (zero if the run has no final_state or no
    "output" key). Useful for "did my fork actually produce more text?"
    comparisons and as a smoke-test that the eval pipeline is wired up.

    Rationale string includes the resolved length and the run id for
    debuggability when a compare table is dense.
    """
    _ = nodes  # not used; keeps the signature consistent with other evaluators
    final_state = run.final_state or {}
    output_value = final_state.get("output", "")
    if not isinstance(output_value, str):
        # Coerce non-string outputs to their str() representation rather than
        # erroring — evaluators are best-effort scoring and a TypeError here
        # would just break the CLI table for one row.
        output_value = str(output_value)
    score = float(len(output_value))
    return EvaluationResult(
        score=score,
        rationale=f"len(final_state['output']) = {int(score)}",
        metadata={"key": "output"},
    )


def _final_state_key_present_factory(key: str = "output") -> Evaluator:
    """Build a ``final_state_key_present`` evaluator bound to a specific key.

    The default key is ``"output"`` — matches the ``output_length_chars``
    convention. To probe a different key, register a fresh instance::

        from chronos.eval import register, _final_state_key_present_factory
        register("has_summary", _final_state_key_present_factory("summary"))

    The single registered ``final_state_key_present`` entry uses the default
    ``"output"`` key — sufficient for built-in demos and docs.
    """

    def evaluator(run: Run, nodes: list[Node]) -> EvaluationResult:
        _ = nodes  # not used
        final_state = run.final_state or {}
        is_present = key in final_state
        return EvaluationResult(
            passed=is_present,
            rationale=(
                f"key {key!r} {'present in' if is_present else 'absent from'} "
                f"final_state (keys: {sorted(final_state.keys())[:5]}…)"
                if final_state
                else f"final_state is None or empty; key {key!r} cannot be present"
            ),
            metadata={"key": key},
        )

    return evaluator


# Register the two built-ins exactly once, at import time.
register("output_length_chars", _output_length_chars)
register("final_state_key_present", _final_state_key_present_factory("output"))


# ---------------------------------------------------------------------------
# Entry-point loader — discovers third-party evaluators packaged as
# ``[project.entry-points."chronos.evaluators"]`` in their pyproject.toml.
# ---------------------------------------------------------------------------


_ENTRY_POINTS_LOADED = False


def load_entry_points() -> int:
    """Discover and register evaluators advertised via the ``chronos.evaluators``
    entry-point group.

    A plugin package declares::

        [project.entry-points."chronos.evaluators"]
        my_evaluator = "my_pkg.my_module:my_evaluator"

    On first call, this function scans installed packages, imports each entry,
    and calls :func:`register` on the resolved callable. Idempotent across
    repeated calls — entries already loaded are not re-registered. Failures
    on individual entries log a warning and are skipped (one bad plugin must
    not break the CLI).

    Returns:
        Number of new evaluators registered on this call. Zero on subsequent
        calls (entry-point set is cached).
    """
    global _ENTRY_POINTS_LOADED
    if _ENTRY_POINTS_LOADED:
        return 0
    _ENTRY_POINTS_LOADED = True

    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover — Python 3.11+ guaranteed
        return 0

    count = 0
    eps: Any
    try:
        eps = entry_points(group="chronos.evaluators")
    except TypeError:
        # importlib_metadata <5 fallback; project pins Python 3.11 so this
        # branch is defensive only.
        eps = entry_points().get("chronos.evaluators", [])  # type: ignore[union-attr,attr-defined,unused-ignore]

    for ep in eps:
        try:
            fn = ep.load()
            register(ep.name, fn)
            count += 1
        except Exception:
            # Don't let a misbehaving plugin take down the CLI.
            import logging

            logging.getLogger("chronos.eval").warning(
                "skipped malformed evaluator entry-point %r", ep.name, exc_info=True
            )
    return count


__all__ = [
    "Evaluator",
    "get",
    "list_registered",
    "load_entry_points",
    "register",
    "run_evaluator",
]
