"""Auto-pivot N-run compare (Phase 4 Arc A slice 4, R62).

When the caller supplies a list of runs but **no designated pivot**, we need
to pick one. This module implements Option C of ADR-024 — the "star schema /
auto-centroid" approach — on top of the pivot-anchored ``merge_pivot_reports``
primitive shipped in v0.5.0 (R58).

Design summary (full spec: ``docs/decisions/ADR-024-multi-pivot-compare.md``):

1. Compute pairwise structural distance for every ``(i, j)`` run pair, ``i < j``,
   using :func:`compute_distance` over :class:`DiffReport`\\ s.
2. Select the **centroid** = ``argmin_i  mean_j≠i d(i, j)``, with deterministic
   tie-break by lexicographically smallest ``run_id`` (:func:`select_centroid`).
3. Delegate the actual merge to the v0.5.0 frozen primitive
   ``merge_pivot_reports(pivot=centroid, others=N-1)``.

Public surface (R62 core phase — CLI / HTTP wrappers land in R63)::

    from chronos.core.auto_pivot import (
        compute_distance,
        pairwise_distances,
        select_centroid,
        auto_pivot_compare,
        AutoPivotReport,
        METRIC_VERSION,
    )

The ``metric_version`` field on every :class:`AutoPivotReport` is the **public
contract** for the distance metric (ADR-024 §Consequences, ADR-025 candidate
for any future v2 metric).

Deviation note on module placement (R62): ADR-024 §Decision sketched the file
path as ``src/chronos/core/diff/auto_pivot.py`` (a diff package). The current
repository layout has ``src/chronos/core/diff.py`` as a single module and no
diff package. Splitting ``diff.py`` into a package is a separate refactor
with its own test / import-graph ripple; R62 keeps the auto-pivot logic in a
sibling module ``chronos.core.auto_pivot`` to preserve the one-module one-PR
discipline. This does not change the public contract or the algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from chronos.core.diff import (
    DiffReport,
    MergedPivotAlignment,
    diff_runs,
    merge_pivot_reports,
)
from chronos.core.models import Fork, Node, Run

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Distance-metric version. Any change to :func:`compute_distance`'s formula
#: or its tag-classification must bump this integer **and** be documented in
#: CHANGELOG + an ADR (ADR-025 candidate). R62 ships v1.
METRIC_VERSION: int = 1


# ---------------------------------------------------------------------------
# Store protocol (narrow, matches ``diff_runs`` signature)
# ---------------------------------------------------------------------------


class _AutoPivotStore(Protocol):  # pragma: no cover - typing only
    """Narrow store protocol — must support the same surface as ``_DiffStore``.

    ``auto_pivot_compare`` calls ``diff_runs(store, a, b)`` under the hood for
    each unordered pair; any store satisfying the ``diff_runs`` contract works.
    """

    def get_run(self, run_id: str) -> Run | None: ...
    def get_nodes_for_run(self, run_id: str) -> list[Node]: ...
    def get_fork_for_child(self, child_run_id: str) -> Fork | None: ...


# ---------------------------------------------------------------------------
# Value object
# ---------------------------------------------------------------------------


@dataclass
class AutoPivotReport:
    """Output of :func:`auto_pivot_compare`.

    Wraps the v0.5.0 :class:`MergedPivotAlignment` with the auto-pivot
    metadata the caller needs to understand *why* the centroid was picked
    and to reproduce the selection.

    Attributes:
        centroid_run_id: The run id selected as the pivot.
        distance_matrix: Symmetric pairwise distance map keyed by unordered
            pair ``(min_id, max_id)`` to distance ``∈ [0, 1]``. Self-distances
            are not included.
        pivot_selection: Always the literal string ``"auto-centroid"`` for
            this code path (field name mirrors the ADR-024 §Decision shape so
            downstream consumers can dispatch on it).
        metric_version: Mirror of :data:`METRIC_VERSION` at the time the
            report was computed. Pinned on the report so a stored report
            remains interpretable after the module's version bumps.
        merged: The actual pivot-anchored merge produced by delegating to
            :func:`chronos.core.diff.merge_pivot_reports`.
        input_run_ids: The run ids the caller passed, in original order.
            (``merged.pivot_run_id`` + ``merged.other_run_ids`` may be in a
            different order because we rotate the centroid to the front.)
    """

    centroid_run_id: str
    distance_matrix: dict[tuple[str, str], float]
    pivot_selection: str
    metric_version: int
    merged: MergedPivotAlignment
    input_run_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise for CLI ``--json`` / HTTP responses.

        Distance-matrix tuple keys are flattened to ``"a|b"`` strings because
        JSON doesn't have tuple keys. The ``|`` separator is chosen because
        run ids in this codebase are UUID-shaped and never contain pipes.
        """
        flat_matrix: dict[str, float] = {
            f"{a}|{b}": d for (a, b), d in self.distance_matrix.items()
        }
        return {
            "centroid_run_id": self.centroid_run_id,
            "distance_matrix": flat_matrix,
            "pivot_selection": self.pivot_selection,
            "metric_version": self.metric_version,
            "input_run_ids": list(self.input_run_ids),
            "merged": self.merged.to_dict(),
        }


# ---------------------------------------------------------------------------
# Pure building blocks
# ---------------------------------------------------------------------------


def compute_distance(report: DiffReport) -> float:
    """Structural pairwise distance derived from a two-run :class:`DiffReport`.

    **Metric v1 (ADR-024 §Decision)**::

        d(a, b) = disagreeing_positions / max(1, total_positions)

    where ``total_positions = len(report.entries)`` and
    ``disagreeing_positions`` is the count of entries with tag in
    ``{"changed", "added", "removed"}`` (everything that is *not* ``"equal"``).

    Properties (enforced by tests):

    * ``d(a, a) = 0`` when the report is all-equal.
    * ``d(a, b) = 1`` when the two runs have no equal-tagged positions.
    * ``d ∈ [0, 1]`` — bounded, deterministic.
    * ``d`` is **symmetric under report-flip**: if the caller swaps ``run_a``
      and ``run_b`` and re-runs alignment, the resulting report has the same
      count of non-equal entries (``added`` and ``removed`` are exchanged).
      Tests verify this via ``pairwise_distances``.
    * Empty reports return ``0.0`` (the ``max(1, ...)`` guard) — treated as
      "no information to disagree on" rather than raising; this matches the
      N=2 contract where ``merge_pivot_reports`` already accepts empty
      alignment gracefully.

    Args:
        report: A :class:`DiffReport` produced by :func:`diff_runs` or an
            equivalent synthetic fixture.

    Returns:
        A float in ``[0.0, 1.0]``.
    """
    total = len(report.entries)
    if total == 0:
        return 0.0
    disagreeing = sum(1 for entry in report.entries if entry.tag != "equal")
    return disagreeing / total


def pairwise_distances(
    run_ids: list[str],
    store: _AutoPivotStore,
    *,
    restrict_to_downstream: bool = True,
) -> dict[tuple[str, str], float]:
    """Compute symmetric pairwise distances for every ``(i, j)`` run pair.

    Iterates unordered pairs ``(a, b)`` with ``a < b`` lexicographically and
    calls :func:`diff_runs` + :func:`compute_distance` for each. The returned
    mapping has exactly ``N * (N - 1) / 2`` keys.

    The key convention ``(min_id, max_id)`` is intentional — it makes the
    mapping symmetric without duplicating entries, matches the standard
    upper-triangular convention, and gives a canonical lookup shape for
    :func:`select_centroid`.

    Args:
        run_ids: Run ids to compare. Must have at least 2 entries; duplicates
            raise ``ValueError``.
        store: Any store implementing ``_AutoPivotStore``.
        restrict_to_downstream: Forwarded to :func:`diff_runs`. Defaults to
            ``True`` to match the CLI ``--restrict-to-downstream`` default
            shipped in R59.

    Returns:
        ``{(min_id, max_id): distance}``. Distances are in ``[0.0, 1.0]``.

    Raises:
        ValueError: fewer than 2 ids, or duplicate ids.
        DiffRunNotFoundError: any id missing from the store (propagated from
            :func:`diff_runs`).
    """
    if len(run_ids) < 2:
        raise ValueError(f"pairwise_distances needs at least 2 run_ids, got {len(run_ids)}")
    seen: set[str] = set()
    for rid in run_ids:
        if rid in seen:
            raise ValueError(f"duplicate run_id in pairwise_distances: {rid!r}")
        seen.add(rid)

    distances: dict[tuple[str, str], float] = {}
    n = len(run_ids)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = run_ids[i], run_ids[j]
            key = (a, b) if a < b else (b, a)
            report = diff_runs(store, key[0], key[1], restrict_to_downstream=restrict_to_downstream)
            distances[key] = compute_distance(report)
    return distances


def select_centroid(
    run_ids: list[str],
    distances: dict[tuple[str, str], float],
) -> str:
    """Pick the centroid run = argmin over runs of mean distance to all others.

    Tie-break: when two or more runs share the minimum mean distance, the
    **lexicographically smallest** run_id wins. This makes the selection
    fully deterministic and replayable, which matters for regression testing
    and for CI runs across machines.

    Args:
        run_ids: The same list that was passed to :func:`pairwise_distances`.
            Must have at least 2 entries and no duplicates.
        distances: The output of :func:`pairwise_distances` (unordered-pair
            keyed with ``min_id`` first). Missing pairs raise ``KeyError``.

    Returns:
        The centroid run_id (a member of ``run_ids``).

    Raises:
        ValueError: fewer than 2 run_ids, or duplicates.
        KeyError: when a needed pair is missing from ``distances`` — indicates
            the caller built the matrix incorrectly.
    """
    if len(run_ids) < 2:
        raise ValueError(f"select_centroid needs at least 2 run_ids, got {len(run_ids)}")
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("select_centroid: duplicate run_ids not allowed")

    def _pair_key(a: str, b: str) -> tuple[str, str]:
        return (a, b) if a < b else (b, a)

    # Mean distance from each rid to all others.
    means: dict[str, float] = {}
    n = len(run_ids)
    for rid in run_ids:
        total = 0.0
        for other in run_ids:
            if other == rid:
                continue
            total += distances[_pair_key(rid, other)]
        means[rid] = total / (n - 1)

    min_mean = min(means.values())
    # Tie-break: lexicographically smallest run_id.
    candidates = sorted(rid for rid, m in means.items() if m == min_mean)
    return candidates[0]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def auto_pivot_compare(
    run_ids: list[str],
    store: _AutoPivotStore,
    *,
    restrict_to_downstream: bool = True,
) -> AutoPivotReport:
    """Full auto-pivot N-run compare (ADR-024 Option C).

    Pipeline:

    1. Validate input (≥ 2 ids, no duplicates).
    2. Compute all pairwise distances (:func:`pairwise_distances`).
    3. Select the centroid (:func:`select_centroid`).
    4. Fetch the ``DiffReport(centroid, other)`` for every other id by
       re-using the cached pair from step 2 (either the stored orientation
       or by re-calling ``diff_runs`` with the centroid first).
    5. Delegate to :func:`merge_pivot_reports` to build the alignment.
    6. Wrap the result in :class:`AutoPivotReport`.

    For step 4 we **re-call** ``diff_runs(store, centroid, other)`` rather
    than reuse the pair from step 2 because step 2 stored pairs in
    ``(min_id, max_id)`` orientation — half of them will have ``other`` as
    ``run_a`` instead of the centroid. Re-calling with the centroid in the
    ``a`` slot gives us the exact reports the pivot-anchored merge expects
    (``run_a == centroid`` for every report). The cost is N-1 extra diff
    calls; the total remains ``O(N²)`` which is dominated by step 2.

    N=2 degenerate case:

    With only two runs, the centroid is whichever id sorts first lexically
    (the distance-matrix has one entry so both means equal that distance →
    tie → lex tie-break wins). The resulting :class:`AutoPivotReport` is
    equivalent to calling ``merge_pivot_reports(pivot=sorted(run_ids)[0],
    others=[sorted(run_ids)[1]])`` directly. This preserves the v0.5.0
    contract (ADR-024 §Decision, ADR-024 §Why Option C tiebreaker).

    Args:
        run_ids: Run ids to compare, in any order. Must have at least 2 and
            no duplicates.
        store: Any store implementing ``_AutoPivotStore``.
        restrict_to_downstream: Forwarded to :func:`diff_runs` for every
            pair, matching the R59 CLI / HTTP default.

    Returns:
        An :class:`AutoPivotReport` with the centroid selection, the full
        distance matrix, the pivot-anchored merge, and the metric version.

    Raises:
        ValueError: fewer than 2 ids or duplicates.
        DiffRunNotFoundError: any id missing from the store.
    """
    if len(run_ids) < 2:
        raise ValueError(f"auto_pivot_compare needs at least 2 run_ids, got {len(run_ids)}")
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("auto_pivot_compare: duplicate run_ids not allowed")

    distances = pairwise_distances(run_ids, store, restrict_to_downstream=restrict_to_downstream)
    centroid = select_centroid(run_ids, distances)
    others = [rid for rid in run_ids if rid != centroid]

    reports = [
        diff_runs(store, centroid, oid, restrict_to_downstream=restrict_to_downstream)
        for oid in others
    ]
    merged = merge_pivot_reports(
        pivot_run_id=centroid,
        other_run_ids=others,
        reports=reports,
    )

    return AutoPivotReport(
        centroid_run_id=centroid,
        distance_matrix=distances,
        pivot_selection="auto-centroid",
        metric_version=METRIC_VERSION,
        merged=merged,
        input_run_ids=list(run_ids),
    )


__all__ = [
    "METRIC_VERSION",
    "AutoPivotReport",
    "auto_pivot_compare",
    "compute_distance",
    "pairwise_distances",
    "select_centroid",
]
