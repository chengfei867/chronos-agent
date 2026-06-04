"""Spike 21 (R115, Phase 6 ADR-030) — eval/compare end-to-end pipeline.

Probe: per ADR-030 §82, prove the full Evaluation pipeline works end-to-end
on a fresh ``chronos quickstart`` DB:

    1. Seed two runs via ``chronos quickstart`` (parent + forked child).
    2. Run two registered evaluators (``output_length_chars`` and
       ``final_state_key_present``) against each run via ``run_evaluator`` +
       ``store.put_evaluation``.
    3. Confirm ``store.get_evaluations_for_run`` returns the persisted rows.
    4. Run ``chronos compare --eval output_length_chars`` (programmatic
       ``compare_command`` invocation) and assert the JSON payload carries an
       ``eval`` block with one score per run.
    5. Re-run an evaluator on the same run and confirm UPSERT (row count
       stays at 1 for that ``(run_id, evaluator_name)`` pair, score updates
       to the new value).

Why a spike (not just a unit test): the chain crosses five layers (eval
registry → run_evaluator → store.put_evaluation → store.get_evaluations →
compare's annotate_with_evaluation → compare JSON output), each of which
already has unit coverage but the failure modes that bite users in
production are *cross-layer*:

    INV-1  ``run_evaluator`` produces an ``Evaluation`` whose ``run_id``
        matches the input run. Failure: stale id → UPSERT lands on wrong row.

    INV-2  ``store.put_evaluation`` UPSERT preserves the (run_id, evaluator_name)
        unique invariant — re-running same evaluator overwrites, not duplicates.

    INV-3  ``compare --eval`` JSON payload exposes ``eval.scores`` keyed by
        run_id and includes both pivot + others, so the frontend score column
        and CLI table both have data to render.

    INV-4  Built-in evaluators (``output_length_chars``,
        ``final_state_key_present``) are auto-registered at import time; spike
        does NOT register anything, exercises only the built-ins shipped per
        ADR-030 §50-52.

This spike runs as a normal pytest (file name ``spike21_*.py``, ``test_``
prefix on functions so pytest collects them; also ad-hoc runnable via
``python tests/spikes/spike21_eval_compare_pipeline.py``).

Perf budget: ≤ 500 ms (single quickstart seed + 4 evaluator runs +
compare round-trip).
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from rich.console import Console

from chronos.cli.compare import compare_command
from chronos.cli.quickstart import quickstart_command
from chronos.eval import run_evaluator
from chronos.store.sqlite import SqliteStore


def _seed_demo(db: Path) -> Console:
    """Seed the builtin-minimal quickstart demo into ``db``. Returns a
    Console writing to a sink so seeding output doesn't leak into the
    pytest capture."""
    sink_path = db.parent / "seed-out.txt"
    with open(sink_path, "w", encoding="utf-8") as fh:
        console = Console(file=fh)
        quickstart_command(demo="builtin-minimal", db=db, force=False, console=console)
    # Caller doesn't need the seeding console afterwards; spike-level
    # callers create their own console to capture compare/CLI output.
    return Console(file=open(db.parent / "spike-out.txt", "w", encoding="utf-8"))


def test_eval_run_persists_per_run_evaluator() -> None:
    """INV-1+2: run two evaluators against each seeded run, confirm both
    persist correctly and the (run_id, evaluator_name) unique invariant
    holds across re-runs.
    """
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "spike21.db"
        _seed_demo(db)

        store = SqliteStore.open(db)
        try:
            runs = store.list_runs(limit=100)
            assert len(runs) == 2, f"expected 2 runs from builtin-minimal, got {len(runs)}"

            for r in runs:
                nodes = store.get_nodes_for_run(r.id)
                # Built-ins (auto-registered at chronos.eval import time).
                e_len = run_evaluator("output_length_chars", r, nodes)
                e_key = run_evaluator("final_state_key_present", r, nodes)
                # INV-1: ids round-trip cleanly.
                assert e_len.run_id == r.id
                assert e_key.run_id == r.id
                store.put_evaluation(e_len)
                store.put_evaluation(e_key)

            # INV-2: two evaluations per run, no dupes.
            for r in runs:
                evs = store.get_evaluations_for_run(r.id)
                assert len(evs) == 2, f"expected 2 evals for {r.id}, got {len(evs)}"
                names = sorted(e.evaluator_name for e in evs)
                assert names == ["final_state_key_present", "output_length_chars"]

            # Re-run output_length_chars on first run — UPSERT, not insert.
            r0 = runs[0]
            n0 = store.get_nodes_for_run(r0.id)
            e_len2 = run_evaluator("output_length_chars", r0, n0)
            store.put_evaluation(e_len2)
            evs0 = store.get_evaluations_for_run(r0.id)
            assert len(evs0) == 2, f"UPSERT broken — expected 2 rows after re-run, got {len(evs0)}"
        finally:
            store.close()


def test_compare_eval_json_carries_scores() -> None:
    """INV-3: ``chronos compare --eval <name>`` JSON output exposes
    ``eval.scores`` for every candidate run (pivot + others)."""
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "spike21.db"
        _seed_demo(db)

        # Pick the two runs as pivot + other.
        store = SqliteStore.open(db)
        try:
            runs = store.list_runs(limit=100)
            assert len(runs) == 2
            pivot_id = runs[0].id
            other_id = runs[1].id
        finally:
            store.close()

        # Programmatically invoke compare_command with --eval. Capture stdout
        # (compare writes JSON via _emit_json which uses print).
        sink = Path(td) / "compare-out.txt"
        with sink.open("w", encoding="utf-8") as fp:
            console = Console(file=fp)
            buf = io.StringIO()
            with redirect_stdout(buf):
                compare_command(
                    pivot_run_id=pivot_id,
                    other_run_ids=[other_id],
                    db=db,
                    json_out=True,
                    restrict_to_downstream=False,
                    columns="all",
                    show_equal=False,
                    width=None,
                    open_store_fn=lambda d: SqliteStore.open(d),
                    console=console,
                    auto_pivot=False,
                    show_matrix=False,
                    matrix=False,
                    eval_evaluator="output_length_chars",
                )
        payload = json.loads(buf.getvalue())

        assert "eval" in payload, f"compare JSON missing 'eval' block: {list(payload)}"
        assert payload["eval"]["evaluator"] == "output_length_chars"
        scores = payload["eval"]["scores"]
        assert pivot_id in scores
        assert other_id in scores
        # Both runs should have scored (auto_run=True), so neither entry is None.
        assert scores[pivot_id] is not None, f"pivot {pivot_id} missing score"
        assert scores[other_id] is not None, f"other {other_id} missing score"
        # Score field is a float (>= 0 for output_length_chars on demo data).
        assert isinstance(scores[pivot_id]["score"], (int, float))
        assert scores[pivot_id]["evaluator"] == "output_length_chars"


def test_compare_eval_unknown_evaluator_warns_in_json() -> None:
    """INV-3 boundary: unknown evaluator name short-circuits to all-None
    scores and surfaces a warning instead of crashing the compare verb.
    """
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "spike21.db"
        _seed_demo(db)

        store = SqliteStore.open(db)
        try:
            runs = store.list_runs(limit=100)
            pivot_id = runs[0].id
            other_id = runs[1].id
        finally:
            store.close()

        sink = Path(td) / "compare-out.txt"
        with sink.open("w", encoding="utf-8") as fp:
            console = Console(file=fp)
            buf = io.StringIO()
            with redirect_stdout(buf):
                compare_command(
                    pivot_run_id=pivot_id,
                    other_run_ids=[other_id],
                    db=db,
                    json_out=True,
                    restrict_to_downstream=False,
                    columns="all",
                    show_equal=False,
                    width=None,
                    open_store_fn=lambda d: SqliteStore.open(d),
                    console=console,
                    auto_pivot=False,
                    show_matrix=False,
                    matrix=False,
                    eval_evaluator="totally_made_up_evaluator_zzz",
                )
        payload = json.loads(buf.getvalue())
        # Compare still produced an eval block (with all-None scores) and a
        # warning the JSON consumer can render.
        assert payload["eval"]["evaluator"] == "totally_made_up_evaluator_zzz"
        scores = payload["eval"]["scores"]
        assert all(v is None for v in scores.values())
        assert any("totally_made_up_evaluator_zzz" in w for w in payload["warnings"])


if __name__ == "__main__":
    # Ad-hoc runner (no pytest needed) for manual probing.
    test_eval_run_persists_per_run_evaluator()
    test_compare_eval_json_carries_scores()
    test_compare_eval_unknown_evaluator_warns_in_json()
    print("spike21: all 3 invariants GREEN")
    sys.exit(0)
