"""Structural diff between two Chronos ``Run``s.

Implements the algorithm frozen in ``docs/decisions/ADR-006-diff-alignment.md``:
align by ``node_name`` sequence using ``difflib.SequenceMatcher``, then
compare ``state_after`` deep-equality for paired nodes.

Public surface::

    from chronos.core.diff import diff_runs, DiffReport, DiffEntry

    report = diff_runs(store, run_a_id, run_b_id)
    for entry in report.entries:
        ...

The report is serialisable via ``to_dict()`` for the CLI ``--json`` flag.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from chronos.core.models import Fork, Node, Run

DiffTag = Literal["equal", "changed", "added", "removed"]


# ---------------------------------------------------------------------------
# Minimal store protocol — keeps diff_runs testable without pulling in
# the full SqliteStore in unit tests.
# ---------------------------------------------------------------------------


class _DiffStore(Protocol):  # pragma: no cover - typing only
    def get_run(self, run_id: str) -> Run | None: ...
    def get_nodes_for_run(self, run_id: str) -> list[Node]: ...
    def get_fork_for_child(self, child_run_id: str) -> Fork | None: ...


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass
class StateDiff:
    """Shallow key-level diff between two ``state_after`` dicts."""

    added_keys: list[str] = field(default_factory=list)
    removed_keys: list[str] = field(default_factory=list)
    changed_keys: dict[str, dict[str, Any]] = field(default_factory=dict)
    # changed_keys[key] = {"a": <value in A>, "b": <value in B>}

    @property
    def is_empty(self) -> bool:
        return not (self.added_keys or self.removed_keys or self.changed_keys)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added_keys": list(self.added_keys),
            "removed_keys": list(self.removed_keys),
            "changed_keys": dict(self.changed_keys),
        }


@dataclass
class DiffEntry:
    """One aligned slot in the diff — may hold 0, 1, or 2 nodes."""

    tag: DiffTag
    node_name: str
    a: Node | None
    b: Node | None
    state_diff: StateDiff | None = None

    def to_dict(self) -> dict[str, Any]:
        def _node_brief(n: Node | None) -> dict[str, Any] | None:
            if n is None:
                return None
            return {
                "id": n.id,
                "run_id": n.run_id,
                "step_index": n.step_index,
                "node_name": n.node_name,
                "kind": n.kind.value,
                "state_after": n.state_after,
            }

        return {
            "tag": self.tag,
            "node_name": self.node_name,
            "a": _node_brief(self.a),
            "b": _node_brief(self.b),
            "state_diff": self.state_diff.to_dict() if self.state_diff else None,
        }


@dataclass
class DiffReport:
    """Full diff result: per-entry alignment plus summary counters."""

    run_a: Run
    run_b: Run
    entries: list[DiffEntry] = field(default_factory=list)
    fork: Fork | None = None  # if B is a forked child of A
    fork_point_node_name: str | None = None
    # True when the a-side was sliced to post-fork-point nodes only
    restricted_to_downstream: bool = False

    @property
    def summary(self) -> dict[str, int]:
        out = {"equal": 0, "changed": 0, "added": 0, "removed": 0}
        for e in self.entries:
            out[e.tag] += 1
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_a": {
                "id": self.run_a.id,
                "adapter": self.run_a.adapter,
                "status": self.run_a.status.value,
                "task_description": self.run_a.task_description,
            },
            "run_b": {
                "id": self.run_b.id,
                "adapter": self.run_b.adapter,
                "status": self.run_b.status.value,
                "task_description": self.run_b.task_description,
            },
            "fork_of": (
                {
                    "id": self.fork.id,
                    "parent_run_id": self.fork.parent_run_id,
                    "parent_node_id": self.fork.parent_node_id,
                    "parent_node_name": self.fork_point_node_name,
                    "edited_fields": self.fork.edited_fields,
                    "reason": self.fork.reason,
                }
                if self.fork
                else None
            ),
            "restricted_to_downstream": self.restricted_to_downstream,
            "entries": [e.to_dict() for e in self.entries],
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DiffRunNotFoundError(LookupError):
    """Raised when one of the diff targets isn't in the store."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"run not found: {run_id}")
        self.run_id = run_id


# ---------------------------------------------------------------------------
# Alignment primitives (pure, no I/O)
# ---------------------------------------------------------------------------


def _state_diff(a: dict[str, Any], b: dict[str, Any]) -> StateDiff:
    """Shallow key-level diff of two state_after dicts."""
    a_keys = set(a.keys())
    b_keys = set(b.keys())
    added = sorted(b_keys - a_keys)
    removed = sorted(a_keys - b_keys)
    changed: dict[str, dict[str, Any]] = {}
    for k in sorted(a_keys & b_keys):
        if a[k] != b[k]:
            changed[k] = {"a": a[k], "b": b[k]}
    return StateDiff(added_keys=added, removed_keys=removed, changed_keys=changed)


def align_nodes(a: list[Node], b: list[Node]) -> list[DiffEntry]:
    """Align two ordered node sequences by ``node_name`` (ADR-006).

    This is the pure alignment function — no store access, no fork
    awareness. Called by ``diff_runs`` after it's done its I/O.
    """
    names_a = [n.node_name for n in a]
    names_b = [n.node_name for n in b]
    sm = difflib.SequenceMatcher(a=names_a, b=names_b, autojunk=False)
    entries: list[DiffEntry] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                na = a[i1 + k]
                nb = b[j1 + k]
                sd = _state_diff(na.state_after, nb.state_after)
                tag: DiffTag = "equal" if sd.is_empty else "changed"
                entries.append(
                    DiffEntry(
                        tag=tag,
                        node_name=na.node_name,
                        a=na,
                        b=nb,
                        state_diff=sd if tag == "changed" else None,
                    )
                )
        elif op == "replace":
            # ADR-006 §Decision 3: linearise replace as removes then adds
            for k in range(i1, i2):
                entries.append(DiffEntry(tag="removed", node_name=a[k].node_name, a=a[k], b=None))
            for k in range(j1, j2):
                entries.append(DiffEntry(tag="added", node_name=b[k].node_name, a=None, b=b[k]))
        elif op == "delete":
            for k in range(i1, i2):
                entries.append(DiffEntry(tag="removed", node_name=a[k].node_name, a=a[k], b=None))
        elif op == "insert":
            for k in range(j1, j2):
                entries.append(DiffEntry(tag="added", node_name=b[k].node_name, a=None, b=b[k]))
    return entries


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def diff_runs(
    store: _DiffStore,
    run_a_id: str,
    run_b_id: str,
    *,
    restrict_to_downstream: bool = True,
) -> DiffReport:
    """Diff two recorded runs.

    If ``run_b`` is the child of a fork of ``run_a`` and
    ``restrict_to_downstream`` is True (default), the diff ignores
    ``run_a``'s upstream-of-fork-point nodes — they are definitionally
    identical. Pass ``restrict_to_downstream=False`` for an apples-to-
    apples full-run comparison.

    Raises ``DiffRunNotFoundError`` if either run id is absent.
    """
    run_a = store.get_run(run_a_id)
    if run_a is None:
        raise DiffRunNotFoundError(run_a_id)
    run_b = store.get_run(run_b_id)
    if run_b is None:
        raise DiffRunNotFoundError(run_b_id)

    nodes_a = store.get_nodes_for_run(run_a_id)
    nodes_b = store.get_nodes_for_run(run_b_id)

    fork = store.get_fork_for_child(run_b_id)
    fork_of_a = fork if (fork and fork.parent_run_id == run_a_id) else None

    fork_point_name: str | None = None
    restricted = False
    if fork_of_a is not None and restrict_to_downstream:
        # Find the fork-point node on A, slice to nodes whose step_index
        # is strictly greater (ADR-005: the fork point itself exists on
        # the parent, child re-executes starting from the NEXT node).
        fp_node = next(
            (n for n in nodes_a if n.id == fork_of_a.parent_node_id),
            None,
        )
        if fp_node is not None:
            fork_point_name = fp_node.node_name
            nodes_a = [n for n in nodes_a if n.step_index > fp_node.step_index]
            restricted = True

    entries = align_nodes(nodes_a, nodes_b)

    return DiffReport(
        run_a=run_a,
        run_b=run_b,
        entries=entries,
        fork=fork_of_a,
        fork_point_node_name=fork_point_name,
        restricted_to_downstream=restricted,
    )


__all__ = [
    "DiffEntry",
    "DiffReport",
    "DiffRunNotFoundError",
    "DiffTag",
    "StateDiff",
    "align_nodes",
    "diff_runs",
]
