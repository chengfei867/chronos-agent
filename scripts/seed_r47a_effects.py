"""R47-A dogfood seed — build a DB with effect-annotated nodes so the
Web UI fork modal (PH3-04, shipped in R46-A) has real warning + success
cases to render.

Three runs:

1. ``run_effects_warn`` — a 6-step LangGraph-style run where steps 1-4
   carry ``metadata.effects`` with dangerous tags (db, network, fs,
   external). Forking from step 0 must surface a ``warning`` Alert
   with 4 downstream dangerous nodes.
2. ``run_effects_safe`` — a 4-step run that only carries pure-LLM
   nodes. Forking from step 0 must surface a ``success`` Alert
   (pure-LLM case).
3. ``run_effects_lastnode`` — same warnings as #1 but we fork from
   the *last* node, so there are no downstream nodes → ``success``
   Alert (last-node case).

Usage:
    uv run python scripts/seed_r47a_effects.py --db dogfood.db
"""

from __future__ import annotations

import argparse
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from chronos.core.models import Node, NodeKind, Run, RunStatus, Usage
from chronos.store.sqlite import SqliteStore


def _now(offset_sec: float = 0.0) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=offset_sec)


def _make_node(
    run_id: str,
    step_index: int,
    name: str,
    kind: NodeKind,
    parent_id: str | None,
    *,
    effects: list[str] | None = None,
    model: str | None = None,
    tool_name: str | None = None,
) -> Node:
    nid = f"node_{uuid.uuid4().hex[:12]}"
    metadata: dict[str, object] = {}
    if effects is not None:
        metadata["effects"] = effects
    return Node(
        id=nid,
        run_id=run_id,
        step_index=step_index,
        node_name=name,
        kind=kind,
        parent_node_id=parent_id,
        started_at=_now(-600 + step_index * 30),
        ended_at=_now(-600 + step_index * 30 + 15),
        state_after={"step": step_index, "last": name},
        model_name=model,
        usage=(Usage(prompt_tokens=100, completion_tokens=60, total_tokens=160) if model else None),
        cost_usd_cents=5 if model else None,
        tool_name=tool_name,
        tool_input={"q": "x"} if tool_name else None,
        tool_output={"r": "y"} if tool_name else None,
        error_message=None,
        metadata=metadata,
    )


def seed(db_path: Path) -> list[str]:
    """Seed 3 runs and return their run_ids for reference."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteStore.open(db_path)
    run_ids: list[str] = []

    # ---------- Run 1: warn — 4 dangerous downstream nodes ----------
    run1 = Run(
        id=f"run_{uuid.uuid4().hex[:12]}",
        adapter="langgraph",
        adapter_thread_id="thread_r47a_warn",
        status=RunStatus.COMPLETED,
        started_at=_now(-800),
        ended_at=_now(-400),
        task_description="R47-A: dangerous downstream (db/network/fs/external)",
        initial_state={"task": "fetch and persist"},
        final_state={"ok": True},
        tags=["r47a", "effects", "warn"],
        metadata={},
    )
    store.put_run(run1)
    run_ids.append(run1.id)

    specs_warn: list[tuple[str, NodeKind, list[str] | None, str | None, str | None]] = [
        ("plan_agent", NodeKind.LLM, None, "gpt-4o", None),
        ("db_write", NodeKind.TOOL, ["db"], None, "sqlite_write"),
        ("http_fetch", NodeKind.TOOL, ["network"], None, "http_get"),
        ("write_file", NodeKind.TOOL, ["fs"], None, "write_file"),
        ("send_email", NodeKind.TOOL, ["external"], None, "smtp_send"),
        ("summarize", NodeKind.LLM, None, "gpt-4o", None),
    ]
    parent_id: str | None = None
    for i, (name, kind, effects, model, tool) in enumerate(specs_warn):
        node = _make_node(
            run1.id, i, name, kind, parent_id, effects=effects, model=model, tool_name=tool
        )
        store.put_node(node)
        parent_id = node.id

    # ---------- Run 2: pure LLM — success alert ----------
    run2 = Run(
        id=f"run_{uuid.uuid4().hex[:12]}",
        adapter="langgraph",
        adapter_thread_id="thread_r47a_safe",
        status=RunStatus.COMPLETED,
        started_at=_now(-600),
        ended_at=_now(-300),
        task_description="R47-A: pure-LLM chain (safe to fork)",
        initial_state={"task": "draft a poem"},
        final_state={"ok": True},
        tags=["r47a", "effects", "safe"],
        metadata={},
    )
    store.put_run(run2)
    run_ids.append(run2.id)

    specs_safe: list[tuple[str, NodeKind, str | None]] = [
        ("plan", NodeKind.LLM, "gpt-4o"),
        ("draft", NodeKind.LLM, "gpt-4o"),
        ("critique", NodeKind.LLM, "gpt-4o"),
        ("finalize", NodeKind.END, None),
    ]
    parent_id = None
    for i, (name, kind, model) in enumerate(specs_safe):
        node = _make_node(run2.id, i, name, kind, parent_id, model=model)
        store.put_node(node)
        parent_id = node.id

    # ---------- Run 3: same as Run1 but fork from last node ----------
    # (reuse run1 structure, users will fork from the last LLM summarize
    # node to exercise the "no downstream" success alert.)
    run3 = Run(
        id=f"run_{uuid.uuid4().hex[:12]}",
        adapter="langgraph",
        adapter_thread_id="thread_r47a_lastnode",
        status=RunStatus.COMPLETED,
        started_at=_now(-200),
        ended_at=_now(-100),
        task_description="R47-A: fork from last node (empty downstream)",
        initial_state={"task": "one-shot summary"},
        final_state={"ok": True},
        tags=["r47a", "effects", "lastnode"],
        metadata={},
    )
    store.put_run(run3)
    run_ids.append(run3.id)

    specs_last: list[tuple[str, NodeKind, list[str] | None, str | None]] = [
        ("load", NodeKind.TOOL, ["fs"], None),
        ("answer", NodeKind.LLM, None, "gpt-4o"),
    ]
    parent_id = None
    for i, (name, kind, effects, model) in enumerate(specs_last):
        node = _make_node(run3.id, i, name, kind, parent_id, effects=effects, model=model)
        store.put_node(node)
        parent_id = node.id

    return run_ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="dogfood.db", type=Path)
    args = parser.parse_args()

    # Start clean so the demo is deterministic.
    if args.db.exists():
        args.db.unlink()

    ids = seed(args.db)
    print(f"Seeded {args.db} with {len(ids)} runs:")
    for rid in ids:
        print(f"  {rid}")
    print("\nNext steps:")
    print(f"  chronos web --db {args.db}")
    print("  → open browser, click a run, click a non-last node,")
    print("    click the 'Fork from here' danger button in the drawer.")


if __name__ == "__main__":
    main()
