"""R67 dogfood — ``chronos tree`` CLI on a real 4-run fork graph.

Purpose
-------
Validate the Arc A item 2 surface (``chronos tree`` CLI + ``/runs/{id}/tree``
HTTP, shipping in v0.6.0) on a real LangGraph trace with a *non-trivial* fork
topology:

    pivot ──fork(identity)──> twin
    pivot ──fork(early)─────> early
    early ──fork(extra)─────> extra

``extra`` is a *grandchild* of the pivot (forked from the early-exit child),
which is the case the ``--descendants`` BFS traversal was built for.

This dogfood exercises:
  * ``chronos tree <pivot> --db ...``               (text, single-run)
  * ``chronos tree <pivot> --db ... --json``        (JSON, single-run)
  * ``chronos tree <pivot> --descendants --db ...`` (text, family tree)
  * ``chronos tree <pivot> --descendants --db ... --json``  (JSON, family tree)

And asserts *byte-equality* between the CLI ``--json`` output and the HTTP
``GET /runs/{id}/tree`` response — the ADR-025 invariant that protects us
from one surface quietly drifting from the other.

Run
---
    source .venv/bin/activate
    python scripts/dogfood_fork_tree.py

Emits
-----
- /tmp/chronos_r67_dogfood.db
- /tmp/chronos_r67_dogfood_tree_text.txt
- /tmp/chronos_r67_dogfood_tree.json
- /tmp/chronos_r67_dogfood_desc_text.txt
- /tmp/chronos_r67_dogfood_desc.json
- prints all four runs' ids, tree output, and parity assertion results.
"""

from __future__ import annotations

import json
import os
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
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from chronos.adapters import LangGraphRecorder
from chronos.api.server import build_app
from chronos.store import SqliteStore

DB_PATH = Path("/tmp/chronos_r67_dogfood.db")
TREE_TEXT_OUT = Path("/tmp/chronos_r67_dogfood_tree_text.txt")
TREE_JSON_OUT = Path("/tmp/chronos_r67_dogfood_tree.json")
DESC_TEXT_OUT = Path("/tmp/chronos_r67_dogfood_desc_text.txt")
DESC_JSON_OUT = Path("/tmp/chronos_r67_dogfood_desc.json")


def _banner(msg: str) -> None:
    print()
    print("=" * 72)
    print(msg)
    print("=" * 72)


def _run_initial() -> dict[str, object]:
    return {
        "task": "Explain time-travel debugging in three sentences.",
        "rounds": 0,
        "notes": [],
        "decision": "",
        "answer": "",
    }


def _record_pivot(recorder: LangGraphRecorder, graph) -> str:
    with recorder.record(
        graph,
        thread_id="r67-pivot",
        task_description="R67 pivot — 3-round research loop",
        tags=["r67-dogfood", "pivot"],
    ) as ref:
        graph.invoke(_run_initial(), {"configurable": {"thread_id": "r67-pivot"}})
    assert ref.run_id is not None
    return ref.run_id


def _fork(
    store: SqliteStore,
    recorder: LangGraphRecorder,
    graph,
    *,
    parent_run_id: str,
    at_node_name: str,
    overrides: dict[str, object],
    reason: str,
    thread_id: str,
    tag: str,
) -> str:
    nodes = store.get_nodes_for_run(parent_run_id)
    at_node = next(n for n in nodes if n.node_name == at_node_name)
    with recorder.fork(
        graph,
        parent_run_id=parent_run_id,
        at_node_id=at_node.id,
        overrides=overrides,
        child_thread_id=thread_id,
        reason=reason,
        tags=["r67-dogfood", "fork", tag],
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
        pivot = _record_pivot(recorder, graph)

        twin = _fork(
            store,
            recorder,
            graph,
            parent_run_id=pivot,
            at_node_name="research",
            overrides={},  # identity — produces a "twin" downstream
            reason="identity fork — twin of pivot",
            thread_id="r67-fork-twin",
            tag="twin",
        )

        early = _fork(
            store,
            recorder,
            graph,
            parent_run_id=pivot,
            at_node_name="research",
            overrides={
                "rounds": MAX_ROUNDS,  # router short-circuits to finalize
                "decision": "",
                "answer": "",
            },
            reason="early-exit — skip remaining research rounds",
            thread_id="r67-fork-early",
            tag="early-exit",
        )

        # Grandchild: fork from the early-exit child to stress --descendants BFS
        extra = _fork(
            store,
            recorder,
            graph,
            parent_run_id=early,
            at_node_name="finalize",
            overrides={"decision": "extra polish", "answer": ""},
            reason="extra polish on top of early-exit child",
            thread_id="r67-fork-extra",
            tag="extra-on-early",
        )

    return pivot, twin, early, extra


def _run_chronos_tree(run_id: str, *, descendants: bool, json_mode: bool) -> str:
    chronos_bin = shutil.which("chronos")
    if chronos_bin is None:
        raise RuntimeError("chronos entry point not on PATH — activate the venv first")
    cmd = [chronos_bin, "tree", run_id, "--db", str(DB_PATH)]
    if descendants:
        cmd.append("--descendants")
    if json_mode:
        cmd.append("--json")
    proc = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "COLUMNS": "140"},
    )
    return proc.stdout


def _http_tree(run_id: str, *, descendants: bool) -> dict:
    """Hit the HTTP endpoint against the same DB, for parity assertions."""
    with SqliteStore.open(DB_PATH) as store:
        client = TestClient(build_app(store))
        resp = client.get(
            f"/runs/{run_id}/tree",
            params={"include_descendants": descendants},
        )
        resp.raise_for_status()
        return resp.json()


def main() -> None:
    _banner("R67 dogfood — chronos tree on a real fork graph")
    pivot, twin, early, extra = _seed_runs()
    print(f"pivot : {pivot}")
    print(f"twin  : {twin}   (direct child — identity fork)")
    print(f"early : {early}   (direct child — early-exit)")
    print(f"extra : {extra}   (grandchild — forked from `early`)")
    print(f"db    : {DB_PATH}")

    # ---- single-run mode -------------------------------------------------
    _banner("chronos tree <pivot> — text, single-run")
    text_single = _run_chronos_tree(pivot, descendants=False, json_mode=False)
    TREE_TEXT_OUT.write_text(text_single)
    print(text_single)
    print(f"(saved to {TREE_TEXT_OUT})")

    _banner("chronos tree <pivot> --json — single-run")
    json_single_raw = _run_chronos_tree(pivot, descendants=False, json_mode=True)
    TREE_JSON_OUT.write_text(json_single_raw)
    cli_single = json.loads(json_single_raw)
    print(f"run_id       : {cli_single['run_id']}")
    print(f"nodes        : {len(cli_single['nodes'])}")
    print(f"edges        : {len(cli_single['edges'])} (sequential+fork)")
    print(f"child_runs   : {len(cli_single['child_runs'])}")
    assert "descendant_run_ids" not in cli_single, (
        "single-run JSON must NOT carry descendant_run_ids (ADR-025 §Interface)"
    )
    assert "run_summaries" not in cli_single, (
        "single-run JSON must NOT carry run_summaries (ADR-025 §Interface)"
    )
    # 2 direct forks originate from pivot
    assert len(cli_single["child_runs"]) == 2, cli_single["child_runs"]
    print(f"(saved to {TREE_JSON_OUT})")

    # HTTP parity guard — single-run
    http_single = _http_tree(pivot, descendants=False)
    assert cli_single == http_single, (
        "CLI --json and HTTP response diverged for single-run tree — "
        "ADR-025 byte-equivalence invariant violated"
    )
    print("✓ CLI --json matches HTTP GET /runs/{id}/tree byte-for-byte")

    # ---- descendants mode -------------------------------------------------
    _banner("chronos tree <pivot> --descendants — text, family tree")
    text_desc = _run_chronos_tree(pivot, descendants=True, json_mode=False)
    DESC_TEXT_OUT.write_text(text_desc)
    print(text_desc)
    print(f"(saved to {DESC_TEXT_OUT})")

    _banner("chronos tree <pivot> --descendants --json — family tree")
    json_desc_raw = _run_chronos_tree(pivot, descendants=True, json_mode=True)
    DESC_JSON_OUT.write_text(json_desc_raw)
    cli_desc = json.loads(json_desc_raw)

    assert "descendant_run_ids" in cli_desc
    assert "run_summaries" in cli_desc
    desc_ids = cli_desc["descendant_run_ids"]
    print(f"descendant_run_ids ({len(desc_ids)}):")
    for rid in desc_ids:
        summary = cli_desc["run_summaries"][rid]
        print(f"  - {rid}   task={summary['task_description']!r}")

    # Topology invariants
    expected = {pivot, twin, early, extra}
    assert set(desc_ids) == expected, (
        f"descendant_run_ids mismatch: expected {expected}, got {set(desc_ids)}"
    )
    # BFS — root first, grandchild after its direct parent
    assert desc_ids[0] == pivot, f"pivot should be first: {desc_ids}"
    assert desc_ids.index(early) < desc_ids.index(extra), (
        f"early (parent) must come before extra (grandchild): {desc_ids}"
    )
    # 3 cross-run forks total
    fork_edges = [e for e in cli_desc["edges"] if e["kind"] == "fork"]
    assert len(fork_edges) == 3, f"expected 3 fork edges, got {len(fork_edges)}"
    print("✓ BFS order, 3 fork edges, 4 connected runs — topology OK")
    print(f"(saved to {DESC_JSON_OUT})")

    # HTTP parity guard — descendants
    http_desc = _http_tree(pivot, descendants=True)
    assert cli_desc == http_desc, (
        "CLI --json --descendants and HTTP response diverged — "
        "ADR-025 byte-equivalence invariant violated"
    )
    print("✓ CLI --json --descendants matches HTTP byte-for-byte")

    _banner("R67 Arc A item 2 validated on real LangGraph trace ✅")


if __name__ == "__main__":
    main()
