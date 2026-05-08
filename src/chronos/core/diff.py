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
from collections import defaultdict
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


# ---------------------------------------------------------------------------
# N-run compare — pivot-anchored O(N) merge (Phase 4 Arc A, R58)
#
# See ``docs/design/n-run-compare.md`` §4.1 and §5.1 for the full spec.
# This implementation is the core pure function called by the CLI
# (``chronos compare``, R59) and the HTTP endpoint
# (``GET /runs/compare/n``, R59). R58 ships the function + tests only.
# ---------------------------------------------------------------------------


MergedCellTag = Literal["equal", "changed", "removed", "added", "absent"]


@dataclass
class MergedPivotAlignment:
    """Merged N-run alignment anchored on a pivot run (design doc §5.1).

    The merge is O(N): for each ``other_run_id`` we take the existing
    ``DiffReport(pivot, other)`` and fold its entries into a single
    alignment table keyed on the pivot's ``step_index``. "Added" entries
    (the other run inserted a node the pivot does not have) become
    separate rows with ``pivot_step=None`` and an ``inserted_after_pivot_step``
    hint so renderers can place them sensibly.

    Attributes:
        pivot_run_id: The "before" run id. All others are aligned against it.
        other_run_ids: The other run ids, in positional order. Must match
            ``reports`` one-to-one.
        alignment: The merged row list. Pivot-anchored rows appear in
            ascending pivot_step order; insert rows appear immediately
            after their ``inserted_after_pivot_step`` anchor (or at the
            start for ``inserted_after_pivot_step=-1``).
        summary: Per-other_run_id counts of tags. Each inner dict has
            keys ``equal``/``changed``/``added``/``removed`` and a value
            equal to the count of that tag in that run's column.
        warnings: Free-form warning strings (adapter-mismatch, large N, ...).
    """

    pivot_run_id: str
    other_run_ids: list[str]
    alignment: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, dict[str, int]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pivot_id": self.pivot_run_id,
            "other_ids": list(self.other_run_ids),
            "alignment": [dict(row) for row in self.alignment],
            "summary": {k: dict(v) for k, v in self.summary.items()},
            "warnings": list(self.warnings),
        }


def _cell_absent() -> dict[str, Any]:
    return {"tag": "absent"}


def merge_pivot_reports(
    pivot_run_id: str,
    other_run_ids: list[str],
    reports: list[DiffReport],
) -> MergedPivotAlignment:
    """Merge ``N-1`` ``DiffReport``s (pivot vs. each other) into a single
    pivot-anchored alignment table.

    This is the pure-function core of the N-run compare feature
    (see ``docs/design/n-run-compare.md`` §4.1). No store access, no IO,
    no new dependencies. The CLI/API wrappers (R59) are responsible for
    fetching runs and constructing the ``DiffReport``s via ``diff_runs``.

    Contract:

    * ``len(other_run_ids) == len(reports)`` and the i-th report must be
      ``diff_runs(store, pivot_run_id, other_run_ids[i])`` (or produce the
      same shape). Mismatches raise ``ValueError``; we do not try to
      recover because a mismatch implies the caller's indexing is wrong.
    * ``other_run_ids`` must be non-empty and contain no duplicates and
      must not contain ``pivot_run_id``. All three conditions raise
      ``ValueError`` — silent dedup is a footgun (design doc §7.1).
    * Each report's ``run_a`` must be the pivot. We do not assert it is
      the *same* ``Run`` instance — we check ``run_a.id == pivot_run_id``.

    When ``N == 2`` (one other), the resulting ``summary[other_id]`` is
    numerically identical to ``report.summary`` (regression guarantee;
    design doc §4.4). The ``alignment`` rows are the same per-step
    information rendered into the per-run-keyed cell shape.

    Warnings (non-fatal):

    * Adapter mismatch between pivot and any other run (``run_a.adapter
      != run_b.adapter``) adds one warning per mismatched other.
    """
    # --- input validation --------------------------------------------------
    if len(other_run_ids) == 0:
        raise ValueError("other_run_ids must contain at least one id")
    if len(other_run_ids) != len(reports):
        raise ValueError(
            "other_run_ids and reports must have the same length "
            f"(got {len(other_run_ids)} ids vs {len(reports)} reports)"
        )
    seen: set[str] = set()
    for oid in other_run_ids:
        if oid == pivot_run_id:
            raise ValueError(f"other_run_ids must not contain the pivot id: {pivot_run_id!r}")
        if oid in seen:
            raise ValueError(f"duplicate run id in other_run_ids: {oid!r}")
        seen.add(oid)

    for i, (oid, rep) in enumerate(zip(other_run_ids, reports, strict=True)):
        if rep.run_a.id != pivot_run_id:
            raise ValueError(
                f"reports[{i}].run_a.id ({rep.run_a.id!r}) does not match "
                f"pivot_run_id ({pivot_run_id!r})"
            )
        if rep.run_b.id != oid:
            raise ValueError(
                f"reports[{i}].run_b.id ({rep.run_b.id!r}) does not match "
                f"other_run_ids[{i}] ({oid!r})"
            )

    # --- per-pivot-step aggregation ---------------------------------------
    # Key: (pivot_node_id, pivot_step_index, pivot_node_name) → row dict.
    # We key on node_id rather than step_index alone to guard against the
    # (pathological but possible) case where two pivot entries share a
    # step_index; in practice step_index is unique per run.
    pivot_rows: dict[str, dict[str, Any]] = {}
    # Order of first insertion (by ascending pivot step in the pivot's
    # node list) — we'll discover pivot steps from any report that
    # references them, then sort at the end.
    # Insert rows: list of (anchor_step_index, other_run_id, entry)
    insert_rows: list[tuple[int, str, DiffEntry]] = []
    # Initialise per-run summary.
    summary: dict[str, dict[str, int]] = {
        oid: {"equal": 0, "changed": 0, "added": 0, "removed": 0} for oid in other_run_ids
    }
    warnings: list[str] = []

    for oid, rep in zip(other_run_ids, reports, strict=True):
        if rep.run_a.adapter != rep.run_b.adapter:
            warnings.append(
                f"adapter-mismatch: pivot={rep.run_a.adapter!r} vs "
                f"{oid}={rep.run_b.adapter!r}; structural alignment may be mostly removed/added"
            )

        # Track the last seen pivot step in this report so we can anchor
        # "added" entries (pivot has no node there) to the preceding pivot
        # step for rendering.
        last_pivot_step: int = -1

        for entry in rep.entries:
            tag = entry.tag
            summary[oid][tag] += 1

            if tag in ("equal", "changed"):
                # Both sides have nodes; key by pivot node.
                assert entry.a is not None and entry.b is not None
                pivot_node = entry.a
                key = pivot_node.id
                row = pivot_rows.setdefault(
                    key,
                    {
                        "pivot_step": pivot_node.step_index,
                        "pivot_node_name": pivot_node.node_name,
                        "pivot_node_id": pivot_node.id,
                        "per_run": {},
                    },
                )
                row["per_run"][oid] = {
                    "tag": tag,
                    "node_id": entry.b.id,
                    "node_name": entry.b.node_name,
                }
                last_pivot_step = pivot_node.step_index
            elif tag == "removed":
                # Pivot has node, other doesn't.
                assert entry.a is not None
                pivot_node = entry.a
                key = pivot_node.id
                row = pivot_rows.setdefault(
                    key,
                    {
                        "pivot_step": pivot_node.step_index,
                        "pivot_node_name": pivot_node.node_name,
                        "pivot_node_id": pivot_node.id,
                        "per_run": {},
                    },
                )
                row["per_run"][oid] = {"tag": "removed"}
                last_pivot_step = pivot_node.step_index
            elif tag == "added":
                # Other inserts a node pivot doesn't have.
                insert_rows.append((last_pivot_step, oid, entry))
            else:  # pragma: no cover - exhaustive guard
                raise AssertionError(f"unknown diff tag: {tag!r}")

    # --- fill "absent" for pivot-anchored rows where an other didn't speak --
    # This happens when report R covers pivot step X (equal/changed/removed)
    # but another report S also covers that same step via a different tag
    # — actually, every report's pivot side is the full pivot node list,
    # so every report should have an entry per pivot step. But if a
    # report is "restricted_to_downstream" it may start past a fork
    # point and therefore have fewer pivot steps. Fill those gaps with
    # "absent".
    for row in pivot_rows.values():
        for oid in other_run_ids:
            if oid not in row["per_run"]:
                row["per_run"][oid] = _cell_absent()

    # --- build final alignment in ascending pivot_step order ---------------
    sorted_pivot_rows = sorted(pivot_rows.values(), key=lambda r: r["pivot_step"])

    # Build a map from pivot_step → index in sorted_pivot_rows so we can
    # splice insert rows after their anchor.
    pivot_step_positions: dict[int, int] = {
        row["pivot_step"]: idx for idx, row in enumerate(sorted_pivot_rows)
    }

    # Group insert rows by anchor step and emit them after the anchor row.
    # Inserts with anchor=-1 (before any pivot step) go at the very start.
    inserts_by_anchor: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for anchor_step, oid, entry in insert_rows:
        assert entry.b is not None
        # Check if an existing insert row with the same (anchor, node_name,
        # node_id ~ positional) should merge across runs. Two different
        # others both inserting a node at the same anchor with the same
        # node_name are heuristically the "same" insert. This keeps the
        # table compact when, e.g., two forks both added a new "refine"
        # step at the same position.
        merged = False
        for ir in inserts_by_anchor[anchor_step]:
            # Merge when the existing insert row is at the same anchor
            # with the same node_name and this run hasn't yet contributed
            # (its cell is still the default "absent" placeholder).
            existing = ir["per_run"].get(oid)
            if (
                ir["inserted_node_name"] == entry.b.node_name
                and (existing is None or existing.get("tag") == "absent")
            ):
                ir["per_run"][oid] = {
                    "tag": "added",
                    "node_id": entry.b.id,
                    "node_name": entry.b.node_name,
                }
                merged = True
                break
        if not merged:
            inserts_by_anchor[anchor_step].append(
                {
                    "pivot_step": None,
                    "pivot_node_name": None,
                    "inserted_after_pivot_step": anchor_step,
                    "inserted_node_name": entry.b.node_name,
                    "per_run": {
                        o: ({
                            "tag": "added",
                            "node_id": entry.b.id,
                            "node_name": entry.b.node_name,
                        } if o == oid else _cell_absent())
                        for o in other_run_ids
                    },
                }
            )

    # Assemble: pivot rows interleaved with any inserts anchored at that row.
    alignment: list[dict[str, Any]] = []
    # Inserts before the first pivot step:
    for ir in inserts_by_anchor.get(-1, []):
        alignment.append(ir)
    for row in sorted_pivot_rows:
        # Strip the internal ``pivot_node_id`` helper key before emitting —
        # the response schema does not include it.
        clean = {
            "pivot_step": row["pivot_step"],
            "pivot_node_name": row["pivot_node_name"],
            "per_run": row["per_run"],
        }
        alignment.append(clean)
        for ir in inserts_by_anchor.get(row["pivot_step"], []):
            alignment.append(ir)
    # Inserts anchored after pivot steps that aren't in sorted_pivot_rows
    # (can happen if the report was fully "added") — splay them at the end
    # in ascending anchor order.
    orphan_anchors = sorted(
        a for a in inserts_by_anchor
        if a != -1 and a not in pivot_step_positions
    )
    for anchor in orphan_anchors:
        for ir in inserts_by_anchor[anchor]:
            alignment.append(ir)

    return MergedPivotAlignment(
        pivot_run_id=pivot_run_id,
        other_run_ids=list(other_run_ids),
        alignment=alignment,
        summary=summary,
        warnings=warnings,
    )


__all__ = [
    "DiffEntry",
    "DiffReport",
    "DiffRunNotFoundError",
    "DiffTag",
    "MergedCellTag",
    "MergedPivotAlignment",
    "StateDiff",
    "align_nodes",
    "diff_runs",
    "merge_pivot_reports",
]
