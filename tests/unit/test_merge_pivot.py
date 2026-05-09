"""Unit tests for ``chronos.core.diff.merge_pivot_reports`` (Phase 4 Arc A, R58).

Design reference: ``docs/design/n-run-compare.md`` §4.1, §5.1, §7.1.

Covered (≥ 10 cases per CONTEXT §6 Option A):

1.  N=2 → summary matches today's ``DiffReport.summary`` exactly (regression guard).
2.  N=3 all-equals → every cell is ``tag=equal``, no insert rows.
3.  N=3 B changed at pivot step 2 + C changed at pivot step 3 → per-column tags correct.
4.  N=3 B adds a step + C adds at the same position with same name → merged insert row.
5.  N=3 B removes pivot step 2, C identical → B cell tag=removed, C cell tag=equal.
6.  Adapter mismatch (pivot=langgraph, other=crewai) → ``warnings[]`` populated.
7.  Duplicate ids in ``other_run_ids`` → ``ValueError``.
8.  Empty ``other_run_ids`` → ``ValueError``.
9.  ``len(other_run_ids) != len(reports)`` → ``ValueError``.
10. ``other_run_ids`` contains the pivot id → ``ValueError``.
11. Report ``run_a.id`` doesn't match ``pivot_run_id`` → ``ValueError``.
12. Report ``run_b.id`` doesn't match ``other_run_ids[i]`` → ``ValueError``.
13. N=5 all-equals → 5 alignment rows, each with 4 per-run cells tagged equal.
14. ``to_dict`` serialisation shape matches design doc §5.1 keys.
15. Alignment ``pivot_step`` ordering is strictly ascending across the anchored rows.
"""

from __future__ import annotations

import pytest

from chronos.core.diff import MergedPivotAlignment, merge_pivot_reports
from tests.unit.fixtures.three_run_pivot import (
    n_run_all_equal,
    three_run_adapter_mismatch,
    three_run_all_equal,
    three_run_b_and_c_both_insert_same_position,
    three_run_b_changed_step2_c_changed_step3,
    three_run_b_removed_step2,
    two_run_wrap,
)

# ---------------------------------------------------------------------------
# 1. N=2 summary matches today's DiffReport.summary verbatim
# ---------------------------------------------------------------------------


def test_n2_summary_matches_diffreport_summary_equal_case() -> None:
    pivot, others, reports = two_run_wrap(three_run_all_equal)
    merged = merge_pivot_reports(pivot.id, [o.id for o in others], reports)

    # The canonical N=2 regression guarantee: for each other, summary
    # counts must be identical to the upstream DiffReport.summary counts.
    assert merged.summary[others[0].id] == reports[0].summary


def test_n2_summary_matches_diffreport_summary_changed_case() -> None:
    pivot, others, reports = two_run_wrap(three_run_b_changed_step2_c_changed_step3)
    merged = merge_pivot_reports(pivot.id, [o.id for o in others], reports)
    assert merged.summary[others[0].id] == reports[0].summary
    # Sanity: expected counts from the fixture (B: 3 equal, 1 changed).
    assert merged.summary[others[0].id] == {"equal": 3, "changed": 1, "added": 0, "removed": 0}


# ---------------------------------------------------------------------------
# 2. N=3 all-equals
# ---------------------------------------------------------------------------


def test_n3_all_equal_every_cell_equal() -> None:
    pivot, others, reports = three_run_all_equal()
    merged = merge_pivot_reports(pivot.id, [o.id for o in others], reports)

    # 3 pivot rows, no insert rows.
    assert len(merged.alignment) == 3
    for row in merged.alignment:
        assert row["pivot_step"] is not None
        for oid in [o.id for o in others]:
            assert row["per_run"][oid]["tag"] == "equal"
    assert merged.warnings == []
    for oid in [o.id for o in others]:
        assert merged.summary[oid] == {"equal": 3, "changed": 0, "added": 0, "removed": 0}


# ---------------------------------------------------------------------------
# 3. N=3 per-column tags — B changed at step 2, C changed at step 3
# ---------------------------------------------------------------------------


def test_n3_per_column_tags_reflect_per_pair_changes() -> None:
    pivot, others, reports = three_run_b_changed_step2_c_changed_step3()
    b_id, c_id = others[0].id, others[1].id
    merged = merge_pivot_reports(pivot.id, [b_id, c_id], reports)

    # 4 pivot rows, ascending step 0..3.
    steps = [row["pivot_step"] for row in merged.alignment]
    assert steps == [0, 1, 2, 3]

    row_step2 = merged.alignment[2]
    assert row_step2["per_run"][b_id]["tag"] == "changed"
    assert row_step2["per_run"][c_id]["tag"] == "equal"

    row_step3 = merged.alignment[3]
    assert row_step3["per_run"][b_id]["tag"] == "equal"
    assert row_step3["per_run"][c_id]["tag"] == "changed"

    assert merged.summary[b_id]["changed"] == 1
    assert merged.summary[c_id]["changed"] == 1


# ---------------------------------------------------------------------------
# 4. Inserts at same position with same name merge into one row
# ---------------------------------------------------------------------------


def test_inserts_at_same_position_same_name_merge() -> None:
    pivot, others, reports = three_run_b_and_c_both_insert_same_position()
    b_id, c_id = others[0].id, others[1].id
    merged = merge_pivot_reports(pivot.id, [b_id, c_id], reports)

    # 3 pivot rows + 1 merged insert row = 4 alignment rows total.
    assert len(merged.alignment) == 4
    # Find the insert row — it's the one with pivot_step is None.
    insert_rows = [r for r in merged.alignment if r["pivot_step"] is None]
    assert len(insert_rows) == 1

    ir = insert_rows[0]
    assert ir["inserted_after_pivot_step"] == 1  # anchored after pivot step 1
    assert ir["inserted_node_name"] == "refine"
    assert ir["per_run"][b_id]["tag"] == "added"
    assert ir["per_run"][c_id]["tag"] == "added"

    for oid in (b_id, c_id):
        assert merged.summary[oid]["added"] == 1


# ---------------------------------------------------------------------------
# 5. Removal in one other leaves "equal" in the other column
# ---------------------------------------------------------------------------


def test_removal_leaves_other_column_equal() -> None:
    pivot, others, reports = three_run_b_removed_step2()
    b_id, c_id = others[0].id, others[1].id
    merged = merge_pivot_reports(pivot.id, [b_id, c_id], reports)

    # 3 pivot rows expected.
    steps = [row["pivot_step"] for row in merged.alignment if row["pivot_step"] is not None]
    assert steps == [0, 1, 2]

    # Row at pivot step 1 ("plan"): B removed, C equal.
    row = next(r for r in merged.alignment if r["pivot_step"] == 1)
    assert row["per_run"][b_id]["tag"] == "removed"
    assert row["per_run"][c_id]["tag"] == "equal"

    assert merged.summary[b_id]["removed"] == 1
    assert merged.summary[c_id]["removed"] == 0


# ---------------------------------------------------------------------------
# 6. Adapter mismatch warning
# ---------------------------------------------------------------------------


def test_adapter_mismatch_produces_warning() -> None:
    pivot, others, reports = three_run_adapter_mismatch()
    b_id, c_id = others[0].id, others[1].id
    merged = merge_pivot_reports(pivot.id, [b_id, c_id], reports)

    # Exactly one warning for the crewai-vs-langgraph pair. B matches, so
    # it should not trigger a warning.
    assert len(merged.warnings) == 1
    w = merged.warnings[0]
    assert "adapter-mismatch" in w
    assert c_id in w
    assert "crewai" in w
    assert "langgraph" in w


# ---------------------------------------------------------------------------
# 7-12. Input validation
# ---------------------------------------------------------------------------


def test_duplicate_other_run_ids_raises() -> None:
    pivot, others, reports = three_run_all_equal()
    with pytest.raises(ValueError, match="duplicate"):
        # Same id twice in other_run_ids.
        merge_pivot_reports(pivot.id, [others[0].id, others[0].id], [reports[0], reports[0]])


def test_empty_other_run_ids_raises() -> None:
    pivot, _others, _reports = three_run_all_equal()
    with pytest.raises(ValueError, match="at least one"):
        merge_pivot_reports(pivot.id, [], [])


def test_length_mismatch_raises() -> None:
    pivot, others, reports = three_run_all_equal()
    with pytest.raises(ValueError, match="same length"):
        merge_pivot_reports(pivot.id, [others[0].id], reports)  # 1 id vs 2 reports


def test_pivot_id_in_other_run_ids_raises() -> None:
    pivot, others, reports = three_run_all_equal()
    with pytest.raises(ValueError, match="must not contain the pivot"):
        merge_pivot_reports(pivot.id, [pivot.id, others[1].id], reports)


def test_report_run_a_mismatch_raises() -> None:
    _pivot, others, reports = three_run_all_equal()
    # Swap the reports so report[0].run_a is actually the pivot but we
    # pass a fake pivot id.
    with pytest.raises(ValueError, match=r"run_a\.id"):
        merge_pivot_reports("bogus_pivot_id", [others[0].id, others[1].id], reports)


def test_report_run_b_mismatch_raises() -> None:
    pivot, others, reports = three_run_all_equal()
    # other_run_ids in wrong order relative to reports.
    with pytest.raises(ValueError, match=r"run_b\.id"):
        merge_pivot_reports(pivot.id, [others[1].id, others[0].id], reports)


# ---------------------------------------------------------------------------
# 13. N=5 all-equals
# ---------------------------------------------------------------------------


def test_n5_all_equals_produces_5_rows_with_4_per_run_cells() -> None:
    pivot, others, reports = n_run_all_equal(5)
    other_ids = [o.id for o in others]
    merged = merge_pivot_reports(pivot.id, other_ids, reports)

    # 5 pivot steps, no inserts.
    assert len(merged.alignment) == 5
    for row in merged.alignment:
        assert row["pivot_step"] is not None
        assert set(row["per_run"].keys()) == set(other_ids)
        for oid in other_ids:
            assert row["per_run"][oid]["tag"] == "equal"


# ---------------------------------------------------------------------------
# 14. to_dict() shape matches design doc §5.1 keys
# ---------------------------------------------------------------------------


def test_to_dict_shape_matches_design_doc() -> None:
    pivot, others, reports = three_run_b_changed_step2_c_changed_step3()
    merged = merge_pivot_reports(pivot.id, [o.id for o in others], reports)
    d = merged.to_dict()

    # Design doc §5.1 top-level keys for the merged alignment (subset the
    # CLI / API will embed). The API adds ``runs``, ``trees``, ``diffs``
    # — those are wrapper responsibilities, not this function's.
    assert set(d.keys()) == {"pivot_id", "other_ids", "alignment", "summary", "warnings"}
    assert d["pivot_id"] == pivot.id
    assert d["other_ids"] == [o.id for o in others]
    for row in d["alignment"]:
        assert "per_run" in row
        for oid in [o.id for o in others]:
            assert oid in row["per_run"]
            assert "tag" in row["per_run"][oid]


# ---------------------------------------------------------------------------
# 15. Alignment row ordering is ascending by pivot_step (anchored rows)
# ---------------------------------------------------------------------------


def test_alignment_rows_ordered_by_ascending_pivot_step() -> None:
    pivot, others, reports = three_run_b_and_c_both_insert_same_position()
    merged = merge_pivot_reports(pivot.id, [o.id for o in others], reports)

    anchored_steps = [
        row["pivot_step"] for row in merged.alignment if row["pivot_step"] is not None
    ]
    assert anchored_steps == sorted(anchored_steps)
    # And the insert row is spliced in between its anchor (step 1) and
    # the following pivot step (step 2).
    idx_step1 = next(i for i, r in enumerate(merged.alignment) if r["pivot_step"] == 1)
    idx_step2 = next(i for i, r in enumerate(merged.alignment) if r["pivot_step"] == 2)
    # Insert row should live strictly between them.
    assert idx_step2 == idx_step1 + 2
    assert merged.alignment[idx_step1 + 1]["pivot_step"] is None


# ---------------------------------------------------------------------------
# 16. Return type is MergedPivotAlignment dataclass
# ---------------------------------------------------------------------------


def test_return_type_is_dataclass() -> None:
    pivot, others, reports = three_run_all_equal()
    merged = merge_pivot_reports(pivot.id, [o.id for o in others], reports)
    assert isinstance(merged, MergedPivotAlignment)
    # other_run_ids is a copy, not the same list (caller mutation safety).
    input_ids = [o.id for o in others]
    merged2 = merge_pivot_reports(pivot.id, input_ids, reports)
    input_ids.append("mutation")
    assert "mutation" not in merged2.other_run_ids
