"""R60 dogfood — 4-run fork-sweep + `chronos compare` showcase.

Purpose
-------
Validate the Phase 4 Arc A surface (`chronos compare` CLI + `/runs/compare/n`
HTTP) on a real LangGraph trace. Produces a pivot run and three forked
children, each with a different override, then drives `chronos compare`
against all four and captures both text + JSON output.

Run
---
    uv run python scripts/dogfood_compare_n.py

Emits
-----
- /tmp/chronos_r60_dogfood.db
- /tmp/chronos_r60_dogfood_text.txt
- /tmp/chronos_r60_dogfood.json
- prints the four run ids, the compare output, and summary counts.

Why this flavour of fork sweep
------------------------------
We reuse ``examples.router_loop.build_graph`` (deterministic FakeLLM,
3-round research loop) as the pivot, then produce three forks that each
take a different override strategy:

1. ``fork_identity`` — re-run the loop with no overrides. Should produce
   a byte-identical trace (all ``equal`` tags). Tests the "twin" case.
2. ``fork_early_exit`` — bump ``rounds`` to MAX_ROUNDS so the router
   immediately routes to ``finalize``. The downstream has fewer research
   iterations. Tests ``removed`` + ``changed`` tags.
3. ``fork_extra_round`` — bump ``rounds`` to MAX_ROUNDS - 2 so the router
   adds an extra round instead. The downstream has more research
   iterations. Tests ``added`` + ``changed`` tags.

Together they form the pivot-anchored N=4 compare that design doc
§3.1 / §5.1 targets.
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

DB_PATH = Path("/tmp/chronos_r60_dogfood.db")
TEXT_OUT = Path("/tmp/chronos_r60_dogfood_text.txt")
JSON_OUT = Path("/tmp/chronos_r60_dogfood.json")


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


def _record_pivot(store: SqliteStore, recorder: LangGraphRecorder, graph) -> str:
    with recorder.record(
        graph,
        thread_id="pivot",
        task_description="pivot baseline — 3 research rounds",
        tags=["r60-dogfood", "pivot"],
    ) as ref:
        graph.invoke(_run_initial(), {"configurable": {"thread_id": "pivot"}})
    assert ref.run_id is not None
    return ref.run_id


def _fork_with_overrides(
    store: SqliteStore,
    recorder: LangGraphRecorder,
    graph,
    *,
    pivot_run_id: str,
    overrides: dict[str, object],
    reason: str,
    thread_id: str,
    tag: str,
) -> str:
    nodes = store.get_nodes_for_run(pivot_run_id)
    first_research = next(n for n in nodes if n.node_name == "research")
    with recorder.fork(
        graph,
        parent_run_id=pivot_run_id,
        at_node_id=first_research.id,
        overrides=overrides,
        child_thread_id=thread_id,
        reason=reason,
        tags=["r60-dogfood", "fork", tag],
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
        pivot = _record_pivot(store, recorder, graph)

        twin = _fork_with_overrides(
            store,
            recorder,
            graph,
            pivot_run_id=pivot,
            overrides={},  # no-op override ⇒ byte-identical downstream
            reason="identity fork — twin of pivot",
            thread_id="fork-twin",
            tag="twin",
        )

        early = _fork_with_overrides(
            store,
            recorder,
            graph,
            pivot_run_id=pivot,
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
            pivot_run_id=pivot,
            overrides={
                # pretend we've done 1 round (instead of the 1 we just did),
                # so the router keeps looping — 1 more research round than
                # the pivot.
                "rounds": MAX_ROUNDS - 3,
                "decision": "",
                "answer": "",
            },
            reason="extra-round — add an additional research iteration",
            thread_id="fork-extra",
            tag="extra-round",
        )

    return pivot, twin, early, extra


def _run_compare(pivot: str, others: list[str], *, json_mode: bool) -> str:
    chronos_bin = shutil.which("chronos")
    if chronos_bin is None:
        raise RuntimeError("chronos entry point not on PATH — activate the venv first")
    cmd = [
        chronos_bin,
        "compare",
        pivot,
        *others,
        "--db",
        str(DB_PATH),
    ]
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
    _banner("R60 dogfood — 4-run fork-sweep")
    pivot, twin, early, extra = _seed_runs()
    print(f"pivot       : {pivot}")
    print(f"twin        : {twin}   (identity fork — expected all equal)")
    print(f"early-exit  : {early}   (fewer research rounds)")
    print(f"extra-round : {extra}   (extra research round)")
    print(f"db          : {DB_PATH}")

    _banner("chronos compare — text mode (changed-or-added columns)")
    text_out = _run_compare(pivot, [twin, early, extra], json_mode=False)
    TEXT_OUT.write_text(text_out)
    print(text_out)
    print(f"(saved to {TEXT_OUT})")

    _banner("chronos compare --json — stable contract")
    json_out = _run_compare(pivot, [twin, early, extra], json_mode=True)
    JSON_OUT.write_text(json_out)
    parsed = json.loads(json_out)
    summary = parsed["summary"]
    print(f"summary   : {summary}")
    print(f"alignment : {len(parsed['alignment'])} rows")
    print(f"other_ids : {parsed['other_ids']}")
    print(f"warnings  : {parsed.get('warnings', [])}")
    print(f"(saved to {JSON_OUT})")

    _banner("Done — Arc A surface validated on real LangGraph trace ✅")


if __name__ == "__main__":
    main()
