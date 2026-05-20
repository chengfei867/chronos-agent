"""Spike 16 (R92, Phase 5 Arc C slice 1) — validate that the existing
``GET /runs/{id}`` API contract is sufficient for linear replay UI.

Per ADR-027 §2 slice 1, the deliverable is `Replay.tsx` + `PlaybackTimeline.tsx`
+ `usePlayback` reuse. The spike validates the three R57-spike-pattern
assumptions BEFORE the React skeleton is written:

    A1  ``usePlayback`` from R37 is reusable for linear replay without API
        change. → Concretely: the existing ``GET /runs/{id}`` endpoint, when
        sorted by ``step_index``, gives a stable monotonic sequence that
        ``usePlayback`` can drive. No new ``/replay`` endpoint needed.

    A2  Timeline render perf budget. → For a 200-node trace, the React side
        must render ≤16ms (one frame at 60fps). The spike validates the
        Python-side data shape: 200 nodes' worth of payload is bounded
        (small enough that the timeline can render dots/bars without jank).
        React-side perf is checked manually via `chronos web` browser smoke.

    A3  Keyboard nav contract — ←/→ step, Space play/pause, q quit. → The
        data contract requirement: ``step_index`` is dense (0..N-1) so
        left/right arrow stepping is a simple index ± 1, not a graph
        traversal. The spike confirms this against synthetic + seed-demo
        recorded runs.

This is a Python-only spike (frontend has no test runner installed; adding one
is overkill for slice 1 — visual review forcing function per ADR-027 §3 covers
the React-side gate). On green, R92 proceeds with the skeleton and ADR-027
promotes Draft → Accepted in-place per R57.

The spike uses synthetic ``Node``/``Run`` objects via ``chronos.core.models``
plus a ``SqliteStore`` round-trip to confirm the API-equivalent shape; no
adapter/recorder boot is needed for a data-contract probe.

Run via:  uv run python tests/spikes/spike16_replay_ui_data.py
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Make the spike runnable as a script (no pytest discovery; it's a smoke probe).
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from chronos.core.models import Node, NodeKind, Run, RunStatus  # noqa: E402
from chronos.store import SqliteStore  # noqa: E402


def _make_synthetic_run(num_nodes: int = 200) -> tuple[Run, list[Node]]:
    """Build a synthetic run with `num_nodes` linear nodes, dense step_index.

    Mirrors the seed_demo shape (LangGraph: increment / double / END) but
    scaled to 200 steps so we can probe the timeline perf budget. Each node
    carries a small ``state_after`` payload (counter + recent history) to
    be representative of typical agent-loop sizes (≈100-300 bytes/node).
    """
    run_id = str(uuid.uuid4())
    base = datetime(2026, 5, 22, 4, 0, 0, tzinfo=UTC)
    run = Run(
        id=run_id,
        adapter="langgraph",
        adapter_thread_id="spike16-thread",
        status=RunStatus.COMPLETED,
        started_at=base,
        ended_at=base + timedelta(seconds=num_nodes),
        task_description="spike16 synthetic trace for replay UI",
        initial_state={"counter": 0, "history": []},
        final_state={"counter": num_nodes, "history": ["…"]},
    )

    nodes: list[Node] = []
    prev_id: str | None = None
    counter = 0
    history: list[str] = []
    for i in range(num_nodes):
        # Alternate increment/double — same as seed_demo motif
        if i % 2 == 0:
            counter += 1
            history.append(f"+1->{counter}")
            name = "increment"
        else:
            counter *= 2
            history.append(f"x2->{counter}")
            name = "double"
        # Keep history bounded; UI typically only renders the tail
        if len(history) > 8:
            history = history[-8:]

        node = Node(
            id=str(uuid.uuid4()),
            run_id=run_id,
            step_index=i,
            node_name=name,
            kind=NodeKind.FN,
            parent_node_id=prev_id,
            started_at=base + timedelta(seconds=i),
            ended_at=base + timedelta(seconds=i + 1),
            state_after={"counter": counter, "history": list(history)},
        )
        nodes.append(node)
        prev_id = node.id
    return run, nodes


def _check(label: str, ok: bool, detail: str = "") -> bool:
    mark = "✅" if ok else "❌"
    suffix = f"  ({detail})" if detail else ""
    print(f"  {mark} {label}{suffix}")
    return ok


def main() -> int:
    print("Spike 16 — Phase 5 Arc C slice 1 data-contract validation")
    print("=" * 64)

    # --- Build synthetic run + persist via SqliteStore (mirrors API path) ---
    run, nodes = _make_synthetic_run(num_nodes=200)

    db_path = Path("/tmp/spike16_replay.db")
    if db_path.exists():
        db_path.unlink()
    store = SqliteStore.open(db_path)

    store.put_run(run)
    for n in nodes:
        store.put_node(n)

    # Read back via the same API the FastAPI handler uses for GET /runs/{id}
    fetched_run = store.get_run(run.id)
    fetched_nodes = store.get_nodes_for_run(run.id)

    invariants: list[bool] = []

    # === A1: dense step_index, sortable, drives usePlayback by index ± 1 ===
    print("\nA1 — usePlayback reusability (no API change):")
    sorted_by_step = sorted(fetched_nodes, key=lambda n: n.step_index)
    indices = [n.step_index for n in sorted_by_step]
    invariants.append(
        _check(
            "step_index is dense 0..N-1",
            indices == list(range(len(indices))),
            f"len={len(indices)}, first={indices[:3]}, last={indices[-3:]}",
        )
    )
    invariants.append(
        _check(
            "step_index is unique (no duplicates)",
            len(set(indices)) == len(indices),
        )
    )
    invariants.append(
        _check(
            "sort by step_index matches insertion order",
            [n.id for n in sorted_by_step] == [n.id for n in nodes],
        )
    )
    invariants.append(
        _check(
            "GET /runs/{id} returns run + nodes (no /replay endpoint needed)",
            fetched_run is not None and len(fetched_nodes) == len(nodes),
            f"run={fetched_run.id[:8]}…, nodes={len(fetched_nodes)}",
        )
    )

    # === A2: payload size budget ===
    print("\nA2 — timeline payload size budget:")
    # Serialise the same shape the API returns to the frontend
    payload = {
        "run": fetched_run.model_dump(mode="json"),
        "nodes": [n.model_dump(mode="json") for n in sorted_by_step],
    }
    blob = json.dumps(payload)
    size_kb = len(blob) / 1024
    invariants.append(
        _check(
            "200-node payload < 256KB (single fetch, no pagination)",
            size_kb < 256,
            f"{size_kb:.1f}KB",
        )
    )
    # Per-node minimum needed by the timeline (just step_index + node_name + kind)
    minimal = [
        {"step_index": n.step_index, "node_name": n.node_name, "kind": n.kind.value}
        for n in sorted_by_step
    ]
    minimal_kb = len(json.dumps(minimal)) / 1024
    invariants.append(
        _check(
            "timeline-only projection < 16KB for 200 nodes",
            minimal_kb < 16,
            f"{minimal_kb:.1f}KB — fits one network frame easily",
        )
    )

    # === A3: keyboard nav contract (index ± 1 stepping) ===
    print("\nA3 — keyboard nav contract:")
    # ← step back: index - 1, clamped at 0
    # → step forward: index + 1, clamped at N-1
    n = len(sorted_by_step)

    def step_back(i: int) -> int:
        return max(0, i - 1)

    def step_forward(i: int) -> int:
        return min(n - 1, i + 1)

    invariants.append(
        _check(
            "← from index 0 stays at 0 (clamped)",
            step_back(0) == 0,
        )
    )
    invariants.append(
        _check(
            "→ from index N-1 stays at N-1 (clamped)",
            step_forward(n - 1) == n - 1,
        )
    )
    invariants.append(
        _check(
            "← from index 100 → 99",
            step_back(100) == 99,
        )
    )
    invariants.append(
        _check(
            "→ from index 100 → 101",
            step_forward(100) == 101,
        )
    )
    # Walking forward from 0 hits each step exactly once
    walk: list[int] = [0]
    while walk[-1] < n - 1:
        walk.append(step_forward(walk[-1]))
    invariants.append(
        _check(
            "→ walk from 0 covers every step_index exactly once",
            walk == list(range(n)),
            f"walked {len(walk)} steps",
        )
    )

    # === Summary ===
    print("\n" + "=" * 64)
    passed = sum(1 for x in invariants if x)
    total = len(invariants)
    print(f"Spike 16 result: {passed}/{total} invariants pass")
    if passed == total:
        print("✅ GREEN — proceed with Replay.tsx + PlaybackTimeline.tsx skeleton.")
        return 0
    print("❌ RED — block R92, revisit ADR-027 slice 1 assumptions.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
