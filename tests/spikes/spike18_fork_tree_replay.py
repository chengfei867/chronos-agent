"""Spike 18 (R95, Phase 5 Arc C slice 4) — fork-tree replay data-contract probe.

Per ADR-027 §2 slice 4 + R94 progress doc §"Next-round TODO", R95 ships
``ForkTimeline.tsx`` + a ``#/runs/<id>/forks`` route. Slice 4 introduces a
NEW data-contract assumption — the fork-tree projection — which we must
disprove BEFORE any UI lands (per ADR-027 §3 disprover-first / R57 spike-
first / R69 / R92-R94 lesson).

Three invariants to validate:

    A1  Fork-tree round-trip — given a 3-level fork tree (root → A,
        root → B, A → C) persisted via ``SqliteStore.put_run/put_fork``,
        ``assemble_tree_with_descendants(store, root)`` must return:
          - ``descendant_run_ids`` containing all 4 runs in deterministic
            BFS order ([root, A, B, C]).
          - ``run_summaries`` keyed by every run_id with adapter +
            task_description + status + started_at populated.
          - ``child_runs`` (cross-run fork edges) covering all 3 forks
            with intact ``parent_run_id`` + ``parent_node_id`` +
            ``child_run_id`` linkage.
          - Every child fork's ``parent_node_id`` resolves to a real
            ``Node`` in the parent run's ``nodes`` list.

    A2  Projection determinism — given the descendant tree dict, the
        client-side projection ``project_fork_tree(tree)`` must return a
        stable, depth-first ordered list of ``ForkTreeNode`` records with
          - root at depth 0.
          - each child placed at parent.depth + 1.
          - per-node ``branch_at_step`` resolved from the parent_node's
            ``step_index`` (the step at which the fork branched).
          - ``step_count`` matching the run's ``len(nodes)``.
        Same input → identical output (no nondeterminism from set
        iteration etc.).

    A3  Perf / size budget — worst-case fork tree of 50 nodes total
        (1 root + 5 forks x ~10 nodes each) projects in ≤16ms (single-
        digit ms expected) and serialises to JSON ≤16KB. This is the
        client-side render budget per ADR-027 §3 A2 / R93 spike 17 A3
        sibling rule.

A spike is a Python-only data-contract probe; the React-side perf
assertion (panel re-render ≤16ms) is gated by the slot-2 (R96)
``chronos web`` browser_vision checkpoint, per ADR-027 §3.

The projection algorithm under test is mirrored in
``frontend/src/format/forkTree.ts`` (R95 slot-1). Keeping the Python
reference here lets future rounds catch projection drift quickly.

Run via:  uv run python tests/spikes/spike18_fork_tree_replay.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Make the spike runnable as a script (no pytest discovery; it's a smoke probe).
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from chronos.core.models import Fork, Node, NodeKind, Run, RunStatus  # noqa: E402
from chronos.core.tree import assemble_tree_with_descendants  # noqa: E402
from chronos.store import SqliteStore  # noqa: E402

# ---------------------------------------------------------------------------
# Builders (mirror spike 16/17 patterns — datetime-typed Pydantic v2 models).
# ---------------------------------------------------------------------------


def _make_run(adapter: str, *, label: str) -> Run:
    return Run(
        id=str(uuid.uuid4()),
        adapter=adapter,
        framework_version="0.0.0-spike18",
        adapter_thread_id=f"spike18_{label}",
        status=RunStatus.COMPLETED,
        started_at=datetime(2026, 5, 22, 10, 0, 0, tzinfo=UTC),
        ended_at=datetime(2026, 5, 22, 10, 5, 0, tzinfo=UTC),
        task_description=f"spike18 — fork-tree probe ({label})",
        initial_state={},
        final_state={"done": True},
        tags=[],
        metadata={"spike18_label": label},
    )


def _make_node(run_id: str, step: int, name: str | None = None) -> Node:
    started = datetime(2026, 5, 22, 10, 0, step, tzinfo=UTC)
    return Node(
        id=str(uuid.uuid4()),
        run_id=run_id,
        step_index=step,
        node_name=name or f"step_{step}",
        kind=NodeKind.LLM,
        parent_node_id=None,
        started_at=started,
        ended_at=started + timedelta(seconds=1),
        state_after={"step": step},
        metadata={},
    )


def _make_fork(parent: Run, parent_node: Node, child: Run) -> Fork:
    return Fork(
        id=str(uuid.uuid4()),
        parent_run_id=parent.id,
        parent_node_id=parent_node.id,
        child_run_id=child.id,
        created_at=datetime(2026, 5, 22, 10, 1, 0, tzinfo=UTC),
        edited_fields={"prompt": "ablated"},
        reason="spike18 fork tree probe",
    )


# ---------------------------------------------------------------------------
# Projection (Python reference — frontend mirrors this in TS).
# ---------------------------------------------------------------------------


@dataclass
class ForkTreeNode:
    run_id: str
    parent_run_id: str | None
    depth: int
    branch_at_step: int | None  # step_index in parent at which this child branched
    step_count: int
    adapter: str
    task_description: str | None


def project_fork_tree(tree: dict[str, Any]) -> list[ForkTreeNode]:
    """Project a ``descendants`` tree dict into a deterministic
    depth-first ordered list of ``ForkTreeNode`` records.

    Mirrors the algorithm shipped in ``frontend/src/format/forkTree.ts``;
    keeping a Python reference catches drift via spike re-run.
    """
    nodes_by_run: dict[str, list[dict[str, Any]]] = {}
    for n in tree["nodes"]:
        nodes_by_run.setdefault(n["run_id"], []).append(n)
    # Stable per-run step ordering.
    for _rid, ns in nodes_by_run.items():
        ns.sort(key=lambda d: d["step_index"])

    summaries: dict[str, dict[str, Any]] = tree.get("run_summaries") or {}
    forks: list[dict[str, Any]] = tree.get("child_runs") or []

    # Build parent_run_id + branch_at_step lookup per child run.
    parent_by_child: dict[str, str] = {}
    branch_by_child: dict[str, int] = {}
    for fork in forks:
        cid = fork["child_run_id"]
        pid = fork["parent_run_id"]
        parent_node_id = fork["parent_node_id"]
        parent_by_child[cid] = pid
        # Resolve parent_node_id → step_index in parent run.
        parent_nodes = nodes_by_run.get(pid, [])
        for pn in parent_nodes:
            if pn["id"] == parent_node_id:
                branch_by_child[cid] = pn["step_index"]
                break

    root_id = tree["run_id"]

    # DFS with deterministic iteration order. Children of a run are
    # visited in (branch_at_step, child_run_id) order.
    children_by_parent: dict[str, list[str]] = {}
    for fork in forks:
        children_by_parent.setdefault(fork["parent_run_id"], []).append(fork["child_run_id"])
    for _pid, kids in children_by_parent.items():
        kids.sort(key=lambda cid: (branch_by_child.get(cid, -1), cid))

    out: list[ForkTreeNode] = []
    visited: set[str] = set()

    def _summary(rid: str) -> dict[str, Any]:
        return summaries.get(rid) or {}

    def _step_count(rid: str) -> int:
        return len(nodes_by_run.get(rid, []))

    def _walk(rid: str, depth: int) -> None:
        if rid in visited:
            return
        visited.add(rid)
        s = _summary(rid)
        out.append(
            ForkTreeNode(
                run_id=rid,
                parent_run_id=parent_by_child.get(rid),
                depth=depth,
                branch_at_step=branch_by_child.get(rid),
                step_count=_step_count(rid),
                adapter=s.get("adapter", ""),
                task_description=s.get("task_description"),
            )
        )
        for cid in children_by_parent.get(rid, []):
            _walk(cid, depth + 1)

    _walk(root_id, 0)

    # Catch orphaned descendants (defensive — shouldn't happen given the
    # API contract, but guard against future bulk imports / bad data).
    for rid in tree.get("descendant_run_ids", []):
        if rid not in visited:
            s = _summary(rid)
            out.append(
                ForkTreeNode(
                    run_id=rid,
                    parent_run_id=parent_by_child.get(rid),
                    depth=0,
                    branch_at_step=branch_by_child.get(rid),
                    step_count=_step_count(rid),
                    adapter=s.get("adapter", ""),
                    task_description=s.get("task_description"),
                )
            )

    return out


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def main() -> int:
    invariants_pass = 0
    invariants_total = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal invariants_pass, invariants_total
        invariants_total += 1
        marker = "[OK]" if ok else "[FAIL]"
        status = "GREEN" if ok else "RED"
        print(f"{marker} {label} -> {status}{(' :: ' + detail) if detail else ''}")
        if ok:
            invariants_pass += 1

    print("Spike 18 — fork-tree replay data-contract probe (R95 / Phase 5 Arc C slice 4)")
    print("=" * 78)

    # =====================================================================
    # A1 — Fork-tree round-trip through SqliteStore.
    # =====================================================================
    print()
    print("A1 — Fork-tree round-trip via assemble_tree_with_descendants")
    print("-" * 78)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "spike18.db"

        with SqliteStore.open(db_path) as store:
            # Build a 4-run fork tree:
            #   root (3 nodes) → A (3 nodes, branched at root.step_1)
            #                  → B (2 nodes, branched at root.step_2)
            #   A             → C (2 nodes, branched at A.step_0)
            root = _make_run("langgraph", label="root")
            run_a = _make_run("langgraph", label="A")
            run_b = _make_run("langgraph", label="B")
            run_c = _make_run("langgraph", label="C")
            store.put_run(root)
            store.put_run(run_a)
            store.put_run(run_b)
            store.put_run(run_c)

            root_nodes = [_make_node(root.id, i) for i in range(3)]
            a_nodes = [_make_node(run_a.id, i) for i in range(3)]
            b_nodes = [_make_node(run_b.id, i) for i in range(2)]
            c_nodes = [_make_node(run_c.id, i) for i in range(2)]
            for n in (*root_nodes, *a_nodes, *b_nodes, *c_nodes):
                store.put_node(n)

            fork_a = _make_fork(root, root_nodes[1], run_a)
            fork_b = _make_fork(root, root_nodes[2], run_b)
            fork_c = _make_fork(run_a, a_nodes[0], run_c)
            store.put_fork(fork_a)
            store.put_fork(fork_b)
            store.put_fork(fork_c)

            tree = assemble_tree_with_descendants(store, root.id)

        # I1.1 — descendant_run_ids contains all 4 runs.
        desc = tree.get("descendant_run_ids") or []
        check(
            "I1.1 descendant_run_ids covers all 4 runs",
            set(desc) == {root.id, run_a.id, run_b.id, run_c.id},
            f"got {len(desc)} runs",
        )

        # I1.2 — root is first (BFS / DFS-discovery).
        check(
            "I1.2 descendant_run_ids root-first",
            len(desc) > 0 and desc[0] == root.id,
            f"first={desc[0][:8] if desc else 'EMPTY'}",
        )

        # I1.3 — run_summaries keyed by every run_id.
        summaries = tree.get("run_summaries") or {}
        check(
            "I1.3 run_summaries keyed by every run_id",
            set(summaries.keys()) == {root.id, run_a.id, run_b.id, run_c.id},
            f"{len(summaries)} entries",
        )

        # I1.4 — every summary has adapter + task_description + status + started_at.
        all_keys_ok = all(
            {"adapter", "task_description", "status", "started_at"}.issubset(s.keys())
            for s in summaries.values()
        )
        check("I1.4 run_summaries fields complete", all_keys_ok)

        # I1.5 — child_runs covers all 3 forks with intact linkage.
        child_runs = tree.get("child_runs") or []
        fork_ids = {f["id"] for f in child_runs}
        check(
            "I1.5 child_runs covers all 3 forks",
            fork_ids == {fork_a.id, fork_b.id, fork_c.id},
            f"{len(child_runs)} forks",
        )

        # I1.6 — every fork's parent_node_id resolves to a real Node in the
        # parent's nodes list.
        nodes_by_id = {n["id"]: n for n in tree["nodes"]}
        all_resolve = all(f["parent_node_id"] in nodes_by_id for f in child_runs)
        check("I1.6 every fork.parent_node_id resolves to a real node", all_resolve)

    # =====================================================================
    # A2 — Projection determinism + correctness.
    # =====================================================================
    print()
    print("A2 — Projection determinism + correctness")
    print("-" * 78)

    # Recompute on a fresh store to keep this section independent (and to
    # exercise the projection algo against the same shape twice for
    # determinism).
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "spike18b.db"
        with SqliteStore.open(db_path) as store:
            root = _make_run("langgraph", label="root")
            run_a = _make_run("anthropic_agents", label="A")
            run_b = _make_run("langgraph", label="B")
            run_c = _make_run("langgraph", label="C")
            for r in (root, run_a, run_b, run_c):
                store.put_run(r)
            root_nodes = [_make_node(root.id, i) for i in range(3)]
            a_nodes = [_make_node(run_a.id, i) for i in range(3)]
            b_nodes = [_make_node(run_b.id, i) for i in range(2)]
            c_nodes = [_make_node(run_c.id, i) for i in range(2)]
            for n in (*root_nodes, *a_nodes, *b_nodes, *c_nodes):
                store.put_node(n)
            store.put_fork(_make_fork(root, root_nodes[1], run_a))
            store.put_fork(_make_fork(root, root_nodes[2], run_b))
            store.put_fork(_make_fork(run_a, a_nodes[0], run_c))
            tree = assemble_tree_with_descendants(store, root.id)

        proj1 = project_fork_tree(tree)
        proj2 = project_fork_tree(tree)

        # I2.1 — Same input → identical output (determinism).
        check(
            "I2.1 projection is deterministic",
            [n.run_id for n in proj1] == [n.run_id for n in proj2],
            f"{len(proj1)} nodes",
        )

        # I2.2 — Root at depth 0.
        check(
            "I2.2 root at depth 0",
            proj1[0].depth == 0 and proj1[0].run_id == root.id,
            f"depth={proj1[0].depth}",
        )

        # I2.3 — Every non-root has parent + depth = parent.depth + 1.
        depth_by_run: dict[str, int] = {n.run_id: n.depth for n in proj1}
        bad = [
            n.run_id
            for n in proj1
            if n.parent_run_id is not None and depth_by_run.get(n.parent_run_id, -99) + 1 != n.depth
        ]
        check("I2.3 child.depth == parent.depth + 1", not bad, f"violations: {len(bad)}")

        # I2.4 — branch_at_step resolved correctly for all forks.
        # A branched at root.step_1, B branched at root.step_2, C branched at A.step_0.
        by_run = {n.run_id: n for n in proj1}
        check(
            "I2.4 branch_at_step matches parent step_index",
            by_run[run_a.id].branch_at_step == 1
            and by_run[run_b.id].branch_at_step == 2
            and by_run[run_c.id].branch_at_step == 0,
            f"A={by_run[run_a.id].branch_at_step} B={by_run[run_b.id].branch_at_step} C={by_run[run_c.id].branch_at_step}",
        )

        # I2.5 — step_count matches len(nodes) per run.
        check(
            "I2.5 step_count matches len(nodes)",
            by_run[root.id].step_count == 3
            and by_run[run_a.id].step_count == 3
            and by_run[run_b.id].step_count == 2
            and by_run[run_c.id].step_count == 2,
            f"counts={by_run[root.id].step_count}/{by_run[run_a.id].step_count}/{by_run[run_b.id].step_count}/{by_run[run_c.id].step_count}",
        )

        # I2.6 — adapter carried through from run_summaries.
        check(
            "I2.6 adapter carried through projection",
            by_run[root.id].adapter == "langgraph"
            and by_run[run_a.id].adapter == "anthropic_agents",
            f"root={by_run[root.id].adapter} A={by_run[run_a.id].adapter}",
        )

    # =====================================================================
    # A3 — Perf / size budget (50 nodes total, projection ≤16ms, JSON ≤16KB).
    # =====================================================================
    print()
    print("A3 — Perf / size budget (worst-case fork tree)")
    print("-" * 78)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "spike18c.db"
        with SqliteStore.open(db_path) as store:
            root = _make_run("langgraph", label="root")
            store.put_run(root)
            root_nodes = [_make_node(root.id, i) for i in range(10)]
            for n in root_nodes:
                store.put_node(n)
            child_runs: list[Run] = []
            # 5 forks x 8 nodes each = 40 nodes; +10 root = 50 nodes total.
            for k in range(5):
                child = _make_run("langgraph", label=f"fork_{k}")
                store.put_run(child)
                child_runs.append(child)
                for i in range(8):
                    store.put_node(_make_node(child.id, i))
                # Branch at varying root steps to exercise sort-order.
                store.put_fork(_make_fork(root, root_nodes[k], child))
            tree = assemble_tree_with_descendants(store, root.id)

        # I3.1 — total node count ≈ 50 (10 + 5x8 = 50).
        total_nodes = len(tree["nodes"])
        check(
            "I3.1 total node count == 50 (1 root + 5 forks x 8 nodes)",
            total_nodes == 50,
            f"got {total_nodes}",
        )

        # I3.2 — projection runs in ≤16ms.
        t0 = time.perf_counter()
        proj = project_fork_tree(tree)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        check(
            "I3.2 projection ≤16ms (single React frame budget)",
            elapsed_ms <= 16.0,
            f"{elapsed_ms:.2f}ms",
        )

        # I3.3 — projected output ≤16KB serialised JSON.
        proj_json = json.dumps(
            [
                {
                    "run_id": n.run_id,
                    "parent_run_id": n.parent_run_id,
                    "depth": n.depth,
                    "branch_at_step": n.branch_at_step,
                    "step_count": n.step_count,
                    "adapter": n.adapter,
                    "task_description": n.task_description,
                }
                for n in proj
            ]
        )
        size_bytes = len(proj_json.encode("utf-8"))
        check(
            "I3.3 projected output ≤16KB JSON",
            size_bytes <= 16 * 1024,
            f"{size_bytes} bytes ({len(proj)} nodes)",
        )

        # I3.4 — projected node count = 1 + 5 = 6.
        check(
            "I3.4 projection produces 1 + 5 = 6 ForkTreeNodes",
            len(proj) == 6,
            f"got {len(proj)}",
        )

    # =====================================================================
    # Summary
    # =====================================================================
    print()
    print("=" * 78)
    print(f"Spike 18 result: {invariants_pass}/{invariants_total} invariants GREEN")
    if invariants_pass == invariants_total:
        print("[OVERALL] GREEN — fork-tree projection contract validated; UI ship clear.")
        return 0
    print("[OVERALL] RED — fork-tree contract violated; do NOT ship UI until fixed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
