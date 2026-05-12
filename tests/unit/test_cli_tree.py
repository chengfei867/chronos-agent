"""Tests for ``chronos tree`` (R67, Arc A item 2 CLI closeout — ADR-025).

Seeded fork graph shared across tests:

    root ──fork(temp-swap)──> child_a ──fork(model-swap)──> grandchild
    root ──fork(seed-swap)──> child_b
    orphan_root  (unrelated, NOT in root's tree)

Tests cover:
* single-run text (default, no --descendants)
* single-run JSON shape (byte-for-byte HTTP contract)
* --descendants text (family tree with all 4 runs)
* --descendants JSON shape (adds descendant_run_ids + run_summaries)
* missing run → exit 1
* orphan run not in tree (sibling boundary)
* empty run (run with no nodes)
* CLI JSON ↔ HTTP parity (cross-layer byte-equality guard)
* descendants BFS ordering (root first, then breadth)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from chronos.api.server import build_app
from chronos.cli import app
from chronos.core.models import Fork, Node, NodeKind, Run, RunStatus
from chronos.store.sqlite import SqliteStore

runner = CliRunner()


@pytest.fixture
def seeded_tree_db(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Fork graph with 4 connected runs + 1 orphan + 1 empty."""
    db_path = tmp_path / "tree.db"
    t0 = datetime(2026, 5, 12, 7, 0, 0, tzinfo=UTC)
    ids: dict[str, str] = {}

    store = SqliteStore.open(db_path)
    try:

        def put_run(rid: str, task: str, adapter: str = "langgraph") -> None:
            store.put_run(
                Run(
                    id=rid,
                    adapter=adapter,
                    adapter_thread_id=f"t-{rid}",
                    status=RunStatus.COMPLETED,
                    started_at=t0,
                    ended_at=t0,
                    task_description=task,
                    initial_state={"task": task},
                    final_state={"final": rid},
                    tags=[],
                    metadata={},
                )
            )

        def put_node(
            nid: str,
            run_id: str,
            step: int,
            name: str,
            parent: str | None = None,
        ) -> None:
            store.put_node(
                Node(
                    id=nid,
                    run_id=run_id,
                    step_index=step,
                    node_name=name,
                    kind=NodeKind.FN,
                    parent_node_id=parent,
                    started_at=t0,
                    ended_at=t0,
                    state_after={},
                    metadata={},
                )
            )

        # root: plan → draft → polish
        put_run("run-root", "write haiku")
        put_node("n-root-0", "run-root", 0, "plan", None)
        put_node("n-root-1", "run-root", 1, "draft", "n-root-0")
        put_node("n-root-2", "run-root", 2, "polish", "n-root-1")

        # child_a: fork from root at draft, with own draft + polish
        put_run("run-child-a", "write haiku (temp=0.2)")
        put_node("n-a-0", "run-child-a", 0, "draft", None)
        put_node("n-a-1", "run-child-a", 1, "polish", "n-a-0")

        # child_b: fork from root at polish, with only final
        put_run("run-child-b", "write haiku (seed=42)")
        put_node("n-b-0", "run-child-b", 0, "polish", None)

        # grandchild: fork from child_a at polish
        put_run("run-grandchild", "write haiku (temp=0.2, model=haiku)")
        put_node("n-g-0", "run-grandchild", 0, "polish", None)
        put_node("n-g-1", "run-grandchild", 1, "end", "n-g-0")

        # Forks linking them
        store.put_fork(
            Fork(
                id="fork-root-a",
                parent_run_id="run-root",
                parent_node_id="n-root-1",
                child_run_id="run-child-a",
                reason="temp-swap",
                edited_fields={"temperature": 0.2},
            )
        )
        store.put_fork(
            Fork(
                id="fork-root-b",
                parent_run_id="run-root",
                parent_node_id="n-root-2",
                child_run_id="run-child-b",
                reason="seed-swap",
                edited_fields={"seed": 42},
            )
        )
        store.put_fork(
            Fork(
                id="fork-a-g",
                parent_run_id="run-child-a",
                parent_node_id="n-a-1",
                child_run_id="run-grandchild",
                reason="model-swap",
                edited_fields={"model": "haiku"},
            )
        )

        # orphan root — unrelated, should never appear in root's tree
        put_run("run-orphan", "unrelated")
        put_node("n-orphan-0", "run-orphan", 0, "solo", None)

        # empty run — no nodes, no forks
        put_run("run-empty", "nothing happened", adapter="linear")

        ids = {
            "root": "run-root",
            "child_a": "run-child-a",
            "child_b": "run-child-b",
            "grandchild": "run-grandchild",
            "orphan": "run-orphan",
            "empty": "run-empty",
        }
    finally:
        store.close()

    return db_path, ids


# ---------------------------------------------------------------------------
# Single-run (no --descendants) tests
# ---------------------------------------------------------------------------


def test_tree_single_run_text_happy_path(
    seeded_tree_db: tuple[Path, dict[str, str]],
) -> None:
    db_path, ids = seeded_tree_db
    result = runner.invoke(app, ["tree", ids["root"], "--db", str(db_path)])
    assert result.exit_code == 0, result.stdout
    # All three root nodes visible
    assert "plan" in result.stdout
    assert "draft" in result.stdout
    assert "polish" in result.stdout
    # Fork hints visible (summary footer in single-run mode)
    assert "temp-swap" in result.stdout or "seed-swap" in result.stdout


def test_tree_single_run_json_shape(
    seeded_tree_db: tuple[Path, dict[str, str]],
) -> None:
    db_path, ids = seeded_tree_db
    result = runner.invoke(app, ["tree", ids["root"], "--db", str(db_path), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["run_id"] == ids["root"]
    assert len(payload["nodes"]) == 3
    # Two forks originate from root
    assert len(payload["child_runs"]) == 2
    # Default (no descendants) → these keys ABSENT per ADR-025 contract
    assert "descendant_run_ids" not in payload
    assert "run_summaries" not in payload
    # Sequential edges inside root
    seq = [e for e in payload["edges"] if e["kind"] == "sequential"]
    assert len(seq) == 2  # n0→n1, n1→n2
    # Fork edges: 2 out
    fork_edges = [e for e in payload["edges"] if e["kind"] == "fork"]
    assert len(fork_edges) == 2


# ---------------------------------------------------------------------------
# --descendants tests
# ---------------------------------------------------------------------------


def test_tree_descendants_text_shows_all_runs(
    seeded_tree_db: tuple[Path, dict[str, str]],
) -> None:
    db_path, ids = seeded_tree_db
    result = runner.invoke(app, ["tree", ids["root"], "--descendants", "--db", str(db_path)])
    assert result.exit_code == 0, result.stdout
    # Header announces 4 runs
    assert "4 run(s)" in result.stdout
    # All four adapters' short ids rendered (8-char prefix)
    for key in ("root", "child_a", "child_b", "grandchild"):
        assert ids[key][:8] in result.stdout
    # Orphan must NOT appear in a root-rooted tree
    assert ids["orphan"][:8] not in result.stdout


def test_tree_descendants_json_adds_contract_fields(
    seeded_tree_db: tuple[Path, dict[str, str]],
) -> None:
    db_path, ids = seeded_tree_db
    result = runner.invoke(
        app,
        ["tree", ids["root"], "--descendants", "--db", str(db_path), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    # ADR-025 §Interface: include_descendants=True adds these two keys
    assert "descendant_run_ids" in payload
    assert "run_summaries" in payload
    # BFS order: root first
    assert payload["descendant_run_ids"][0] == ids["root"]
    # All four connected runs appear, orphan does not
    connected = {ids["root"], ids["child_a"], ids["child_b"], ids["grandchild"]}
    assert set(payload["descendant_run_ids"]) == connected
    assert ids["orphan"] not in payload["descendant_run_ids"]
    # run_summaries keyed by run_id with all four ADR-025 keys
    for rid in connected:
        summary = payload["run_summaries"][rid]
        assert set(summary.keys()) >= {
            "task_description",
            "status",
            "started_at",
            "adapter",
        }
    # 3 cross-run forks total
    fork_edges = [e for e in payload["edges"] if e["kind"] == "fork"]
    assert len(fork_edges) == 3
    # Total nodes across all four runs (3+2+1+2 = 8)
    assert len(payload["nodes"]) == 8


def test_tree_descendants_bfs_order_root_first_then_breadth(
    seeded_tree_db: tuple[Path, dict[str, str]],
) -> None:
    """descendant_run_ids is BFS-ish per ADR-025: root first, direct children
    before grandchildren."""
    db_path, ids = seeded_tree_db
    result = runner.invoke(
        app,
        ["tree", ids["root"], "--descendants", "--db", str(db_path), "--json"],
    )
    assert result.exit_code == 0
    order = json.loads(result.stdout)["descendant_run_ids"]
    # Root position 0
    assert order[0] == ids["root"]
    # Both direct children must appear before the grandchild
    idx_a = order.index(ids["child_a"])
    idx_b = order.index(ids["child_b"])
    idx_g = order.index(ids["grandchild"])
    assert idx_a < idx_g, f"child_a should come before grandchild: {order}"
    assert idx_b < idx_g, f"child_b should come before grandchild: {order}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_tree_missing_run_exit_1(
    seeded_tree_db: tuple[Path, dict[str, str]],
) -> None:
    db_path, _ = seeded_tree_db
    result = runner.invoke(app, ["tree", "run-does-not-exist", "--db", str(db_path)])
    assert result.exit_code == 1
    assert "no such run" in result.stdout or "no such run" in (result.stderr or "")


def test_tree_missing_run_json_mode_exit_1(
    seeded_tree_db: tuple[Path, dict[str, str]],
) -> None:
    db_path, _ = seeded_tree_db
    result = runner.invoke(app, ["tree", "run-nope", "--db", str(db_path), "--json"])
    assert result.exit_code == 1


def test_tree_empty_run_descendants_returns_just_root(
    seeded_tree_db: tuple[Path, dict[str, str]],
) -> None:
    """Run with no nodes + no forks → descendants payload has only that
    one run_id, empty nodes/edges."""
    db_path, ids = seeded_tree_db
    result = runner.invoke(
        app,
        ["tree", ids["empty"], "--descendants", "--db", str(db_path), "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["descendant_run_ids"] == [ids["empty"]]
    assert payload["nodes"] == []
    assert payload["edges"] == []
    # run_summaries still has one entry
    assert set(payload["run_summaries"].keys()) == {ids["empty"]}


# ---------------------------------------------------------------------------
# Cross-layer parity — the CLI+HTTP byte-equivalence guard (ADR-025 pent-layer)
# ---------------------------------------------------------------------------


def test_tree_cli_json_matches_http_single_run(
    seeded_tree_db: tuple[Path, dict[str, str]],
) -> None:
    """CLI ``--json`` output == HTTP response JSON for include_descendants=False.

    Locks ADR-025 §Interface contract across both surfaces. Drift in either
    wrapper trips this test."""
    db_path, ids = seeded_tree_db
    cli_result = runner.invoke(app, ["tree", ids["root"], "--db", str(db_path), "--json"])
    assert cli_result.exit_code == 0
    cli_payload = json.loads(cli_result.stdout)

    store = SqliteStore.open(db_path)
    try:
        app_ = build_app(store)
        client = TestClient(app_)
        http_payload = client.get(
            f"/runs/{ids['root']}/tree", params={"include_descendants": False}
        ).json()
    finally:
        store.close()

    assert cli_payload == http_payload


def test_tree_cli_json_matches_http_descendants(
    seeded_tree_db: tuple[Path, dict[str, str]],
) -> None:
    """Same byte-parity guard but for include_descendants=True."""
    db_path, ids = seeded_tree_db
    cli_result = runner.invoke(
        app,
        ["tree", ids["root"], "--descendants", "--db", str(db_path), "--json"],
    )
    assert cli_result.exit_code == 0
    cli_payload = json.loads(cli_result.stdout)

    store = SqliteStore.open(db_path)
    try:
        app_ = build_app(store)
        client = TestClient(app_)
        http_payload = client.get(
            f"/runs/{ids['root']}/tree", params={"include_descendants": True}
        ).json()
    finally:
        store.close()

    assert cli_payload == http_payload
