"""R64 dogfood — 4-run fork-sweep + ``chronos compare --auto-pivot`` showcase.

Purpose
-------
Validate the Phase 4 Arc A **slice 4** surface (``chronos compare --auto-pivot``
CLI + ``GET /runs/compare/auto`` HTTP) on a real LangGraph trace. Produces
four sibling runs with no designated pivot and lets ``auto_pivot_compare()``
(R62 pure core) select the centroid by metric v1.

Run
---
    uv run python scripts/dogfood_auto_pivot.py

Emits
-----
- /tmp/chronos_r64_dogfood_auto_pivot.db
- /tmp/chronos_r64_dogfood_auto_pivot_text.txt
- /tmp/chronos_r64_dogfood_auto_pivot.json
- prints the four run ids, the auto-pivot output (text + JSON), and the
  selected centroid + distance matrix.

Why this flavour of fork sweep
------------------------------
Unlike R60's dogfood (which had a **designated** pivot + 3 named forks), the
auto-pivot feature assumes the caller does **not** know which run is the
centroid. We seed four candidate runs — a baseline + three variants — and
let ``auto_pivot_compare()`` pick the one closest (in mean pairwise distance)
to every other. With two identical-by-construction runs (baseline + twin),
the centroid is deterministic: lexicographically smaller of the two run_ids
(ADR-024 tie-break rule).

Topology
~~~~~~~~
1. ``baseline`` — router-loop example, 3 research rounds (full trace).
2. ``twin``     — identity fork of baseline (``overrides={}``), replays from the
   fork point. Distance to baseline is *small but non-zero* (R64 finding: the
   replay adds fresh node_ids past the fork point, which count as "added"
   rows in the diff). Still the closest sibling to baseline, so baseline and
   twin share the minimum mean-distance and tie on centroid selection.
3. ``early``    — fork with ``rounds = MAX_ROUNDS`` so the router skips the
   remaining research rounds. Shorter trace; distance > 0 to baseline / twin.
4. ``extra``    — fork with ``rounds = MAX_ROUNDS - 3`` so the router adds
   one extra research iteration. Longer trace; distance > 0 to baseline /
   twin.

Expected centroid = lex-min(baseline, twin) because both have mean-distance
= (0 + d_early + d_extra) / 3 which ties with the other's. (The early and
extra variants each have mean-distance = (d_early_baseline + d_early_twin +
d_early_extra) / 3 which is strictly larger since they are distant from two
"core" runs.)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from examples.router_loop import (
    MAX_ROUNDS,
    NODE_KIND_MAP,
    _demo_usage_extractor,
    build_graph,
)
from langgraph.checkpoint.memory import InMemorySaver

from chronos.adapters import LangGraphRecorder
from chronos.store import SqliteStore

DB_PATH = Path("/tmp/chronos_r64_dogfood_auto_pivot.db")
TEXT_OUT = Path("/tmp/chronos_r64_dogfood_auto_pivot_text.txt")
JSON_OUT = Path("/tmp/chronos_r64_dogfood_auto_pivot.json")


def _banner(msg: str) -> None:
    print()
    print("=" * 72)
    print(msg)
    print("=" * 72)


def _run_initial() -> dict[str, object]:
    return {
        "task": "Write a two-sentence summary of why time-travel debugging matters.",
        "rounds": 0,
        "notes": [],
        "decision": "",
        "answer": "",
    }


def _record_baseline(recorder: LangGraphRecorder, graph) -> str:
    with recorder.record(
        graph,
        thread_id="baseline",
        task_description="baseline candidate — 3 research rounds",
        tags=["r64-dogfood", "baseline"],
    ) as ref:
        graph.invoke(_run_initial(), {"configurable": {"thread_id": "baseline"}})
    assert ref.run_id is not None
    return ref.run_id


def _fork_with_overrides(
    store: SqliteStore,
    recorder: LangGraphRecorder,
    graph,
    *,
    parent_run_id: str,
    overrides: dict[str, object],
    reason: str,
    thread_id: str,
    tag: str,
) -> str:
    nodes = store.get_nodes_for_run(parent_run_id)
    first_research = next(n for n in nodes if n.node_name == "research")
    with recorder.fork(
        graph,
        parent_run_id=parent_run_id,
        at_node_id=first_research.id,
        overrides=overrides,
        child_thread_id=thread_id,
        reason=reason,
        tags=["r64-dogfood", "fork", tag],
    ) as fref:
        graph.invoke(None, {"configurable": {"thread_id": thread_id}})
    assert fref.child_run_id is not None
    return fref.child_run_id


def _seed_runs() -> tuple[str, str, str, str]:
    if DB_PATH.exists():
        DB_PATH.unlink()
    saver = InMemorySaver()
    graph = build_graph().compile(checkpointer=saver)
    with SqliteStore.open(DB_PATH) as store:
        recorder = LangGraphRecorder(
            store,
            kind_map=NODE_KIND_MAP,
            usage_extractor=_demo_usage_extractor,
        )
        baseline = _record_baseline(recorder, graph)

        twin = _fork_with_overrides(
            store,
            recorder,
            graph,
            parent_run_id=baseline,
            overrides={},  # byte-identical twin
            reason="identity fork — twin of baseline",
            thread_id="fork-twin",
            tag="twin",
        )

        early = _fork_with_overrides(
            store,
            recorder,
            graph,
            parent_run_id=baseline,
            overrides={
                "rounds": MAX_ROUNDS,  # force router to finalize immediately
                "decision": "",
                "answer": "",
            },
            reason="early-exit — skip remaining research rounds",
            thread_id="fork-early",
            tag="early-exit",
        )

        extra = _fork_with_overrides(
            store,
            recorder,
            graph,
            parent_run_id=baseline,
            overrides={
                "rounds": MAX_ROUNDS - 3,  # one extra research iteration
                "decision": "",
                "answer": "",
            },
            reason="extra-round — add an additional research iteration",
            thread_id="fork-extra",
            tag="extra-round",
        )

    return baseline, twin, early, extra


def _run_auto_pivot(
    run_ids: list[str], *, json_mode: bool, show_matrix: bool = False
) -> str:
    chronos_bin = shutil.which("chronos")
    if chronos_bin is None:
        raise RuntimeError("chronos entry point not on PATH — activate the venv first")
    cmd = [
        chronos_bin,
        "compare",
        "--auto-pivot",
        *run_ids,
        "--db",
        str(DB_PATH),
    ]
    if show_matrix:
        cmd.append("--show-matrix")
    if json_mode:
        cmd.append("--json")
    proc = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={
            **__import__("os").environ,
            # Widen terminal so the rich table doesn't truncate node columns.
            "COLUMNS": "160",
        },
    )
    return proc.stdout


def main() -> None:
    _banner("R64 dogfood — 4-run auto-pivot sweep (Arc A slice 4)")
    baseline, twin, early, extra = _seed_runs()
    print(f"baseline    : {baseline}  (3 research rounds — centroid candidate)")
    print(f"twin        : {twin}  (identity fork — centroid candidate)")
    print(f"early-exit  : {early}  (fewer rounds)")
    print(f"extra-round : {extra}  (extra round)")
    print(f"db          : {DB_PATH}")

    _banner("chronos compare --auto-pivot --show-matrix — text mode")
    text_out = _run_auto_pivot(
        [baseline, twin, early, extra], json_mode=False, show_matrix=True
    )
    TEXT_OUT.write_text(text_out)
    print(text_out)
    print(f"(saved to {TEXT_OUT})")

    _banner("chronos compare --auto-pivot --json — AutoPivotReport contract")
    json_out = _run_auto_pivot([baseline, twin, early, extra], json_mode=True)
    JSON_OUT.write_text(json_out)
    parsed = json.loads(json_out)

    centroid = parsed["centroid_run_id"]
    matrix = parsed["distance_matrix"]
    metric_version = parsed["metric_version"]
    input_ids = parsed["input_run_ids"]
    pivot_selection = parsed["pivot_selection"]
    merged = parsed["merged"]
    merged_summary = merged["summary"]
    merged_other_ids = merged["other_ids"]
    warnings = merged.get("warnings", [])

    print(f"centroid         : {centroid}")
    print(f"metric_version   : {metric_version}")
    print(f"input_run_ids    : {input_ids}")
    print(f"pivot_selection  : {pivot_selection}")
    print(f"distance_matrix  : {matrix}")
    print(f"merged.summary   : {merged_summary}")
    print(f"merged.alignment : {len(merged['alignment'])} rows")
    print(f"merged.other_ids : {merged_other_ids}")
    print(f"warnings         : {warnings}")
    print(f"(saved to {JSON_OUT})")

    # Lightweight structural assertions — the dogfood is a living regression
    # guard; any drift in the contract should trip here before release.
    assert metric_version == 1, f"metric_version drift: {metric_version!r}"
    assert pivot_selection == "auto-centroid", (
        f"pivot_selection drift: {pivot_selection!r}"
    )
    assert centroid in {baseline, twin}, (
        f"centroid must be one of the two identical candidates (baseline/twin), "
        f"got {centroid!r}"
    )
    assert centroid == min(baseline, twin), (
        f"lex tie-break expected centroid == min(baseline, twin)={min(baseline, twin)!r}, "
        f"got {centroid!r}"
    )
    # distance matrix uses flattened "a|b" keys with canonical min<max orientation
    for key in matrix:
        assert "|" in key, f"matrix key not flattened: {key!r}"
        a, b = key.split("|", 1)
        assert a < b, f"non-canonical matrix key orientation: {key!r}"
    # N=4 ⇒ C(4,2)=6 pairs
    assert len(matrix) == 6, f"expected 6 pairs for N=4, got {len(matrix)}"
    # twin<->baseline should be small (<= 0.5) — R64 empirical finding: an
    # "identity fork" (overrides={}) does not yield a byte-identical downstream
    # trace because the replay adds fresh node_ids/timestamps past the fork
    # point; those count as "added" rows in the diff. The distance stays
    # small-but-nonzero. The true invariant is: twin is still closest to
    # baseline among all other candidates, hence baseline & twin share the
    # minimum mean-distance and tie on centroid.
    tb_key = "|".join(sorted([baseline, twin]))
    assert matrix[tb_key] <= 0.5, (
        f"baseline<->twin distance should be small for identity fork, "
        f"got {matrix[tb_key]!r} for key {tb_key!r}"
    )
    # pairs involving early/extra should be strictly larger than baseline<->twin
    for key, dist in matrix.items():
        if key == tb_key:
            continue
        assert dist >= matrix[tb_key], (
            f"expected non-identity-pair distance >= identity-pair distance for "
            f"{key!r}, got {dist!r} < {matrix[tb_key]!r}"
        )
        assert dist > 0.0, f"expected positive distance for {key!r}, got {dist!r}"
    # input_run_ids should mirror the arg order
    assert input_ids == [baseline, twin, early, extra], (
        f"input_run_ids drift: {input_ids!r}"
    )
    # other_ids (inside `merged`) = input minus centroid
    expected_others = [r for r in [baseline, twin, early, extra] if r != centroid]
    assert set(merged_other_ids) == set(expected_others), (
        f"other_ids mismatch: got {merged_other_ids!r}, "
        f"expected set {set(expected_others)!r}"
    )

    _banner("Done — Arc A slice 4 surface validated on real LangGraph trace ✅")


if __name__ == "__main__":
    main()
