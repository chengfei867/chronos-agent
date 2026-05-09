"""Tests for the Local HTTP API (:mod:`chronos.api.server`).

R34-A scope
-----------

Six endpoints, each covered on two axes:

1. **Happy path** — store has matching data, response is well-formed JSON
   with the expected fields / counts / ordering.
2. **404** — every ``/runs/{id}/...`` path returns 404 for a missing run,
   never 200 with ``null`` or ``[]``. This matters because a frontend needs
   to distinguish "no such run" from "empty run".

The ``tree`` endpoint gets extra coverage because its JSON shape is the
contract between this API and whatever viewer the community builds on top.
We assert on edge kinds, cross-run fork edges, and the ``child_runs``
summary explicitly — if any of these drift, a frontend would silently
render the wrong graph.

Fixtures
--------

We build a tiny end-to-end scenario via ``put_run`` / ``put_node`` /
``put_fork`` (the only write surface the store exposes) rather than mocking
the store. Mocks would lie: the real value of this test suite is proving
that the server's SELECT-shaped reads map correctly back to pydantic
models via the actual SQLite driver. A two-run fork scenario gives us
enough structure to exercise every endpoint.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chronos.api import build_app
from chronos.core.models import Fork, Node, NodeKind, Run, RunStatus, Usage
from chronos.store import SqliteStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def scenario(tmp_path: Path) -> Iterator[tuple[SqliteStore, dict[str, str]]]:
    """Build a two-run scenario: parent with 3 nodes, fork, child with 2 nodes.

    Topology::

        parent_run (completed)
          └── n1 (llm) ──► n2 (tool) ──► n3 (end)
                              │
                              └─fork──► child_run (completed)
                                         └── c1 (llm) ──► c2 (end)

    Returns the open store and a dict of IDs for assertions.
    """
    db_path = tmp_path / "scenario.db"
    with SqliteStore.open(db_path) as store:
        parent_run_id = _uuid()
        child_run_id = _uuid()
        n1_id, n2_id, n3_id = _uuid(), _uuid(), _uuid()
        c1_id, c2_id = _uuid(), _uuid()
        fork_id = _uuid()

        parent = Run(
            id=parent_run_id,
            adapter="langgraph",
            adapter_thread_id="thread-parent",
            status=RunStatus.COMPLETED,
            started_at=_now(),
            ended_at=_now(),
            task_description="Parent run for API tests",
            tags=["api-test", "parent"],
        )
        child = Run(
            id=child_run_id,
            adapter="langgraph",
            adapter_thread_id="thread-child",
            status=RunStatus.COMPLETED,
            started_at=_now(),
            ended_at=_now(),
            task_description="Child run for API tests",
            tags=["api-test", "child"],
        )
        store.put_run(parent)
        store.put_run(child)

        # Parent nodes — sequential chain via parent_node_id
        n1 = Node(
            id=n1_id,
            run_id=parent_run_id,
            step_index=0,
            node_name="research",
            kind=NodeKind.LLM,
            parent_node_id=None,
            model_name="gpt-4o",
            usage=Usage(prompt_tokens=100, completion_tokens=50),
        )
        n2 = Node(
            id=n2_id,
            run_id=parent_run_id,
            step_index=1,
            node_name="search_tool",
            kind=NodeKind.TOOL,
            parent_node_id=n1_id,
            tool_name="web_search",
            tool_input={"q": "chronos"},
            tool_output={"hits": 3},
        )
        n3 = Node(
            id=n3_id,
            run_id=parent_run_id,
            step_index=2,
            node_name="done",
            kind=NodeKind.END,
            parent_node_id=n2_id,
        )
        for node in (n1, n2, n3):
            store.put_node(node)

        # Child nodes — note parent_node_id of c1 points across runs to n2
        # (the fork source), per ADR-003 §3.5.
        c1 = Node(
            id=c1_id,
            run_id=child_run_id,
            step_index=0,
            node_name="research_v2",
            kind=NodeKind.LLM,
            parent_node_id=n2_id,
            model_name="gpt-4o",
            usage=Usage(prompt_tokens=120, completion_tokens=60),
        )
        c2 = Node(
            id=c2_id,
            run_id=child_run_id,
            step_index=1,
            node_name="done",
            kind=NodeKind.END,
            parent_node_id=c1_id,
        )
        for node in (c1, c2):
            store.put_node(node)

        fork = Fork(
            id=fork_id,
            parent_run_id=parent_run_id,
            parent_node_id=n2_id,
            child_run_id=child_run_id,
            created_at=_now(),
            edited_fields={"q": "chronos-agent"},
            reason="Broader search query",
        )
        store.put_fork(fork)

        ids = {
            "parent_run": parent_run_id,
            "child_run": child_run_id,
            "n1": n1_id,
            "n2": n2_id,
            "n3": n3_id,
            "c1": c1_id,
            "c2": c2_id,
            "fork": fork_id,
        }
        yield store, ids


@pytest.fixture
def client(scenario: tuple[SqliteStore, dict[str, str]]) -> TestClient:
    store, _ = scenario
    app = build_app(store)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_healthz_returns_ok_and_schema_version(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # schema_version is not the bare int from core.models; it's whatever that
    # constant stringifies to. Assert the key exists and is non-empty.
    assert body["schema_version"]


# ---------------------------------------------------------------------------
# /runs
# ---------------------------------------------------------------------------


def test_list_runs_returns_both_runs(
    client: TestClient, scenario: tuple[SqliteStore, dict[str, str]]
) -> None:
    _, ids = scenario
    resp = client.get("/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    run_ids = {r["id"] for r in body["runs"]}
    assert run_ids == {ids["parent_run"], ids["child_run"]}


def test_list_runs_respects_limit(client: TestClient) -> None:
    resp = client.get("/runs", params={"limit": 1})
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_list_runs_rejects_invalid_limit(client: TestClient) -> None:
    # FastAPI's Query validation returns 422 for out-of-range limits.
    resp = client.get("/runs", params={"limit": 0})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /runs/{id}
# ---------------------------------------------------------------------------


def test_get_run_returns_run_and_nodes_in_order(
    client: TestClient, scenario: tuple[SqliteStore, dict[str, str]]
) -> None:
    _, ids = scenario
    resp = client.get(f"/runs/{ids['parent_run']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run"]["id"] == ids["parent_run"]
    assert body["run"]["adapter"] == "langgraph"
    assert body["run"]["tags"] == ["api-test", "parent"]

    node_ids = [n["id"] for n in body["nodes"]]
    assert node_ids == [ids["n1"], ids["n2"], ids["n3"]]  # step_index ASC

    # Spot-check LLM-specific field propagation.
    assert body["nodes"][0]["model_name"] == "gpt-4o"
    assert body["nodes"][0]["usage"]["prompt_tokens"] == 100


def test_get_run_404_for_unknown_id(client: TestClient) -> None:
    resp = client.get(f"/runs/{_uuid()}")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# /runs/{id}/nodes
# ---------------------------------------------------------------------------


def test_get_run_nodes_returns_only_nodes(
    client: TestClient, scenario: tuple[SqliteStore, dict[str, str]]
) -> None:
    _, ids = scenario
    resp = client.get(f"/runs/{ids['child_run']}/nodes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert [n["id"] for n in body["nodes"]] == [ids["c1"], ids["c2"]]


def test_get_run_nodes_404_for_unknown_run(client: TestClient) -> None:
    resp = client.get(f"/runs/{_uuid()}/nodes")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /runs/{id}/forks
# ---------------------------------------------------------------------------


def test_get_run_forks_returns_forks_from_this_parent(
    client: TestClient, scenario: tuple[SqliteStore, dict[str, str]]
) -> None:
    _, ids = scenario
    resp = client.get(f"/runs/{ids['parent_run']}/forks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    fork = body["forks"][0]
    assert fork["id"] == ids["fork"]
    assert fork["child_run_id"] == ids["child_run"]
    assert fork["edited_fields"] == {"q": "chronos-agent"}


def test_get_run_forks_empty_for_leaf_run(
    client: TestClient, scenario: tuple[SqliteStore, dict[str, str]]
) -> None:
    # Child run is nobody's parent — should return 200 with count=0, not 404.
    _, ids = scenario
    resp = client.get(f"/runs/{ids['child_run']}/forks")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_get_run_forks_404_for_unknown_run(client: TestClient) -> None:
    resp = client.get(f"/runs/{_uuid()}/forks")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /runs/{id}/tree — the contract endpoint
# ---------------------------------------------------------------------------


def test_tree_has_sequential_edges_for_parent_run(
    client: TestClient, scenario: tuple[SqliteStore, dict[str, str]]
) -> None:
    _, ids = scenario
    resp = client.get(f"/runs/{ids['parent_run']}/tree")
    assert resp.status_code == 200
    tree = resp.json()

    assert tree["run_id"] == ids["parent_run"]
    assert [n["id"] for n in tree["nodes"]] == [ids["n1"], ids["n2"], ids["n3"]]

    sequential = [e for e in tree["edges"] if e["kind"] == "sequential"]
    # n1 has no parent (root); n2 → n3 follow chain, so expect 2 sequential edges.
    assert len(sequential) == 2
    seq_pairs = {(e["from"], e["to"]) for e in sequential}
    assert seq_pairs == {
        (ids["n1"], ids["n2"]),
        (ids["n2"], ids["n3"]),
    }


def test_tree_has_fork_edge_crossing_runs(
    client: TestClient, scenario: tuple[SqliteStore, dict[str, str]]
) -> None:
    _, ids = scenario
    resp = client.get(f"/runs/{ids['parent_run']}/tree")
    tree = resp.json()

    fork_edges = [e for e in tree["edges"] if e["kind"] == "fork"]
    assert len(fork_edges) == 1
    fe = fork_edges[0]
    assert fe["from"] == ids["n2"]  # fork source node in parent run
    assert fe["to"] == ids["c1"]  # first node of child run
    assert fe["child_run_id"] == ids["child_run"]
    assert fe["fork_id"] == ids["fork"]
    assert fe["edited_fields"] == {"q": "chronos-agent"}


def test_tree_child_runs_summary_lists_forks_out(
    client: TestClient, scenario: tuple[SqliteStore, dict[str, str]]
) -> None:
    _, ids = scenario
    resp = client.get(f"/runs/{ids['parent_run']}/tree")
    tree = resp.json()
    assert len(tree["child_runs"]) == 1
    assert tree["child_runs"][0]["child_run_id"] == ids["child_run"]


def test_tree_for_leaf_run_has_no_fork_edges(
    client: TestClient, scenario: tuple[SqliteStore, dict[str, str]]
) -> None:
    _, ids = scenario
    resp = client.get(f"/runs/{ids['child_run']}/tree")
    tree = resp.json()
    assert tree["child_runs"] == []
    assert all(e["kind"] != "fork" for e in tree["edges"])


def test_tree_404_for_unknown_run(client: TestClient) -> None:
    resp = client.get(f"/runs/{_uuid()}/tree")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# build_app is a factory (no shared state across apps)
# ---------------------------------------------------------------------------


def test_build_app_binds_distinct_stores(tmp_path: Path) -> None:
    """Two separately-built apps see their own stores — guards against
    accidental module-level state creeping in."""
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"
    with SqliteStore.open(db_a) as store_a, SqliteStore.open(db_b) as store_b:
        run_a = Run(
            id=_uuid(),
            adapter="langgraph",
            adapter_thread_id="t-a",
            status=RunStatus.COMPLETED,
            started_at=_now(),
            ended_at=_now(),
        )
        store_a.put_run(run_a)
        # store_b stays empty

        client_a = TestClient(build_app(store_a))
        client_b = TestClient(build_app(store_b))

        assert client_a.get("/runs").json()["count"] == 1
        assert client_b.get("/runs").json()["count"] == 0


# ---------------------------------------------------------------------------
# /app — ReactFlow viewer mount (R34-C)
# ---------------------------------------------------------------------------


def test_app_mount_serves_index_when_dist_present(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a valid dist directory (via CHRONOS_FRONTEND_DIST env override)
    ``GET /app/`` returns ``index.html`` and ``GET /app/assets/<file>`` serves
    static bundle assets.

    We build a FRESH app inside the test so the override applies — the top-level
    ``client`` fixture was built before the monkeypatch took effect.
    """
    from chronos.api import build_app

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><body>stub viewer</body></html>",
        encoding="utf-8",
    )
    (dist / "assets" / "index.js").write_text("console.log('hi')", encoding="utf-8")

    monkeypatch.setenv("CHRONOS_FRONTEND_DIST", str(dist))

    # Build a fresh app/client so the mount sees the override.
    with SqliteStore.open(":memory:") as store:
        fresh = TestClient(build_app(store))

        r_index = fresh.get("/app/")
        assert r_index.status_code == 200
        assert "stub viewer" in r_index.text
        assert r_index.headers["content-type"].startswith("text/html")

        r_asset = fresh.get("/app/assets/index.js")
        assert r_asset.status_code == 200
        assert "console.log" in r_asset.text


def test_app_mount_returns_503_when_dist_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no dist is found, ``/app`` and ``/app/<anything>`` return 503 with
    a structured ``viewer_bundle_missing`` error — the REST API continues to
    work regardless.
    """
    from chronos.api import build_app

    # Point the override at an empty path so repo-root fallback is bypassed.
    monkeypatch.setenv("CHRONOS_FRONTEND_DIST", str(tmp_path / "does-not-exist"))

    with SqliteStore.open(":memory:") as store:
        client_ = TestClient(build_app(store))

        for path in ("/app", "/app/", "/app/index.html", "/app/deep/nested"):
            r = client_.get(path)
            assert r.status_code == 503, f"expected 503 for {path}, got {r.status_code}"
            body = r.json()
            assert body["error"] == "viewer_bundle_missing"
            assert "frontend/dist" in body["detail"]

        # REST API still works.
        assert client_.get("/healthz").status_code == 200
        assert client_.get("/runs").status_code == 200


def test_find_frontend_dist_resolver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit-test the resolver itself: override wins when valid, falls through
    when the override is missing an ``index.html``.
    """
    from chronos.api.server import _find_frontend_dist

    # 1. Valid override with index.html → returns that path.
    good = tmp_path / "good"
    good.mkdir()
    (good / "index.html").write_text("ok")
    monkeypatch.setenv("CHRONOS_FRONTEND_DIST", str(good))
    assert _find_frontend_dist() == good

    # 2. Override set but missing index.html → returns None (explicit fail).
    bad = tmp_path / "bad"
    bad.mkdir()  # exists but no index.html
    monkeypatch.setenv("CHRONOS_FRONTEND_DIST", str(bad))
    assert _find_frontend_dist() is None

    # 3. Override pointing at a nonexistent path → None.
    monkeypatch.setenv("CHRONOS_FRONTEND_DIST", str(tmp_path / "nope"))
    assert _find_frontend_dist() is None


def test_landing_page_advertises_viewer(client: TestClient) -> None:
    """The landing page includes a visible CTA pointing at ``/app/`` so users
    discover the tree viewer without reading docs.
    """
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/app/"' in r.text
    assert "Tree Viewer" in r.text


# ---------------------------------------------------------------------------
# /runs/{id}/tree?include_descendants=true — R37.5-B
# ---------------------------------------------------------------------------


def test_tree_include_descendants_merges_parent_and_child(
    client: TestClient, scenario: tuple[SqliteStore, dict[str, str]]
) -> None:
    """With ``include_descendants=true``, the tree of the parent run includes
    every node from the child run plus the fork edge.
    """
    _, ids = scenario
    r = client.get(f"/runs/{ids['parent_run']}/tree", params={"include_descendants": "true"})
    assert r.status_code == 200
    body = r.json()

    # All 5 nodes from both runs should be present.
    node_ids = {n["id"] for n in body["nodes"]}
    assert node_ids == {ids["n1"], ids["n2"], ids["n3"], ids["c1"], ids["c2"]}

    # Every node carries its run_id tag — essential for frontend lane grouping.
    by_id = {n["id"]: n for n in body["nodes"]}
    assert by_id[ids["n1"]]["run_id"] == ids["parent_run"]
    assert by_id[ids["c1"]]["run_id"] == ids["child_run"]

    # descendant_run_ids lists root first, then children in DFS order.
    assert body["descendant_run_ids"] == [ids["parent_run"], ids["child_run"]]

    # run_summaries indexable by run_id with the expected keys.
    summaries = body["run_summaries"]
    assert set(summaries.keys()) == {ids["parent_run"], ids["child_run"]}
    assert summaries[ids["parent_run"]]["task_description"] == "Parent run for API tests"
    assert summaries[ids["child_run"]]["adapter"] == "langgraph"
    assert summaries[ids["parent_run"]]["status"] == "completed"

    # Fork edge has the child's first node as concrete target (not None).
    fork_edges = [e for e in body["edges"] if e["kind"] == "fork"]
    assert len(fork_edges) == 1
    assert fork_edges[0]["to"] == ids["c1"]
    assert fork_edges[0]["child_run_id"] == ids["child_run"]


def test_tree_include_descendants_default_false_preserves_original_shape(
    client: TestClient, scenario: tuple[SqliteStore, dict[str, str]]
) -> None:
    """Default behavior (no query param) must not include descendant nodes —
    preserves backward compatibility with v0.1 / v0.2 clients.
    """
    _, ids = scenario
    r = client.get(f"/runs/{ids['parent_run']}/tree")
    assert r.status_code == 200
    body = r.json()

    node_ids = {n["id"] for n in body["nodes"]}
    assert node_ids == {ids["n1"], ids["n2"], ids["n3"]}
    assert "descendant_run_ids" not in body
    assert "run_summaries" not in body


def test_tree_include_descendants_for_leaf_run_returns_only_itself(
    client: TestClient, scenario: tuple[SqliteStore, dict[str, str]]
) -> None:
    """A leaf run (no outgoing forks) + include_descendants=true returns a
    tree containing only its own nodes, and descendant_run_ids=[leaf].
    """
    _, ids = scenario
    r = client.get(f"/runs/{ids['child_run']}/tree", params={"include_descendants": "true"})
    assert r.status_code == 200
    body = r.json()

    assert body["descendant_run_ids"] == [ids["child_run"]]
    node_ids = {n["id"] for n in body["nodes"]}
    assert node_ids == {ids["c1"], ids["c2"]}


def test_tree_include_descendants_two_level_chain(tmp_path: Path) -> None:
    """Three-generation chain (grandparent → parent → child) with
    include_descendants=true must return all three runs' nodes.
    """
    db_path = tmp_path / "three_gen.db"
    with SqliteStore.open(db_path) as store:
        gp_id, p_id, c_id = _uuid(), _uuid(), _uuid()
        gn, pn, cn = _uuid(), _uuid(), _uuid()

        for rid, desc in ((gp_id, "grandparent"), (p_id, "parent"), (c_id, "child")):
            store.put_run(
                Run(
                    id=rid,
                    adapter="langgraph",
                    adapter_thread_id=f"t-{desc}",
                    status=RunStatus.COMPLETED,
                    started_at=_now(),
                    ended_at=_now(),
                    task_description=desc,
                )
            )
        store.put_node(Node(id=gn, run_id=gp_id, step_index=0, node_name="gp", kind=NodeKind.LLM))
        store.put_node(
            Node(
                id=pn,
                run_id=p_id,
                step_index=0,
                node_name="p",
                kind=NodeKind.LLM,
                parent_node_id=gn,
            )
        )
        store.put_node(
            Node(
                id=cn,
                run_id=c_id,
                step_index=0,
                node_name="c",
                kind=NodeKind.LLM,
                parent_node_id=pn,
            )
        )
        store.put_fork(
            Fork(
                id=_uuid(),
                parent_run_id=gp_id,
                parent_node_id=gn,
                child_run_id=p_id,
                created_at=_now(),
                edited_fields={},
                reason="",
            )
        )
        store.put_fork(
            Fork(
                id=_uuid(),
                parent_run_id=p_id,
                parent_node_id=pn,
                child_run_id=c_id,
                created_at=_now(),
                edited_fields={},
                reason="",
            )
        )

        client = TestClient(build_app(store))
        r = client.get(f"/runs/{gp_id}/tree", params={"include_descendants": "true"})
        assert r.status_code == 200
        body = r.json()

        assert body["descendant_run_ids"] == [gp_id, p_id, c_id]
        node_ids = {n["id"] for n in body["nodes"]}
        assert node_ids == {gn, pn, cn}
        # Two fork edges, one per generation.
        fork_edges = [e for e in body["edges"] if e["kind"] == "fork"]
        assert len(fork_edges) == 2


def test_tree_include_descendants_cycle_protection(tmp_path: Path) -> None:
    """Defensive: if a descendant set's BFS revisits a node, we must not
    infinite-loop. We simulate this with a direct call to the internal
    helper since schema rejects fork.parent == fork.child.
    """
    from chronos.api.server import _assemble_tree_with_descendants

    db_path = tmp_path / "cycle.db"
    with SqliteStore.open(db_path) as store:
        a_id, b_id = _uuid(), _uuid()
        an, bn = _uuid(), _uuid()

        for rid, desc in ((a_id, "A"), (b_id, "B")):
            store.put_run(
                Run(
                    id=rid,
                    adapter="langgraph",
                    adapter_thread_id=f"t-{desc}",
                    status=RunStatus.COMPLETED,
                    started_at=_now(),
                    ended_at=_now(),
                    task_description=desc,
                )
            )
        store.put_node(Node(id=an, run_id=a_id, step_index=0, node_name="a", kind=NodeKind.LLM))
        store.put_node(
            Node(
                id=bn,
                run_id=b_id,
                step_index=0,
                node_name="b",
                kind=NodeKind.LLM,
                parent_node_id=an,
            )
        )
        # A → B
        store.put_fork(
            Fork(
                id=_uuid(),
                parent_run_id=a_id,
                parent_node_id=an,
                child_run_id=b_id,
                created_at=_now(),
                edited_fields={},
                reason="",
            )
        )
        # B → A (would cycle; schema permits since parent_run != child_run)
        store.put_fork(
            Fork(
                id=_uuid(),
                parent_run_id=b_id,
                parent_node_id=bn,
                child_run_id=a_id,
                created_at=_now(),
                edited_fields={},
                reason="",
            )
        )

        # Must terminate (no hang) and visit each run exactly once.
        tree = _assemble_tree_with_descendants(store, a_id)
        assert set(tree["descendant_run_ids"]) == {a_id, b_id}
        assert len(tree["descendant_run_ids"]) == 2  # no duplicates


# ---------------------------------------------------------------------------
# /runs/compare?a=...&b=... — R39-A diff endpoint
#
# Shape: wraps chronos.core.diff.DiffReport.to_dict() and bundles both runs'
# reasoning trees (same shape as /runs/{id}/tree) so a frontend can render
# side-by-side ReactFlow graphs without a second round-trip per run.
# ---------------------------------------------------------------------------


def test_compare_happy_path_returns_diff_report_and_both_trees(
    scenario: tuple[SqliteStore, dict[str, str]],
    client: TestClient,
) -> None:
    _, ids = scenario
    resp = client.get(
        "/runs/compare",
        params={"a": ids["parent_run"], "b": ids["child_run"]},
    )
    assert resp.status_code == 200
    body = resp.json()

    # Diff block (from DiffReport.to_dict)
    assert "diff" in body
    diff = body["diff"]
    assert diff["run_a"]["id"] == ids["parent_run"]
    assert diff["run_b"]["id"] == ids["child_run"]
    assert "entries" in diff and isinstance(diff["entries"], list)
    assert "summary" in diff
    # parent→child is a fork relationship in this scenario → fork_of populated
    assert diff["fork_of"] is not None
    assert diff["fork_of"]["parent_run_id"] == ids["parent_run"]
    assert diff["restricted_to_downstream"] is True

    # Both trees included so frontend renders without extra requests.
    assert "tree_a" in body and body["tree_a"]["run_id"] == ids["parent_run"]
    assert "tree_b" in body and body["tree_b"]["run_id"] == ids["child_run"]
    # Tree shape mirrors /runs/{id}/tree — same keys.
    for tree in (body["tree_a"], body["tree_b"]):
        assert set(tree.keys()) >= {"run_id", "nodes", "edges", "child_runs"}


def test_compare_supports_restrict_to_downstream_false(
    scenario: tuple[SqliteStore, dict[str, str]],
    client: TestClient,
) -> None:
    _, ids = scenario
    resp = client.get(
        "/runs/compare",
        params={
            "a": ids["parent_run"],
            "b": ids["child_run"],
            "restrict_to_downstream": "false",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["diff"]["restricted_to_downstream"] is False


def test_compare_404_when_a_missing(client: TestClient) -> None:
    resp = client.get("/runs/compare", params={"a": _uuid(), "b": _uuid()})
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_compare_404_when_b_missing(
    scenario: tuple[SqliteStore, dict[str, str]],
    client: TestClient,
) -> None:
    _, ids = scenario
    resp = client.get("/runs/compare", params={"a": ids["parent_run"], "b": _uuid()})
    assert resp.status_code == 404


def test_compare_400_when_a_equals_b(
    scenario: tuple[SqliteStore, dict[str, str]],
    client: TestClient,
) -> None:
    _, ids = scenario
    resp = client.get(
        "/runs/compare",
        params={"a": ids["parent_run"], "b": ids["parent_run"]},
    )
    assert resp.status_code == 400


def test_compare_missing_query_params_422(client: TestClient) -> None:
    # FastAPI's Query() required default → 422 on missing params
    resp = client.get("/runs/compare")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /runs/{id}/nodes/{node_id}/fork-plan  (R46-A)
# ---------------------------------------------------------------------------


def test_fork_plan_preview_happy_path(
    scenario: tuple[SqliteStore, dict[str, str]],
    client: TestClient,
) -> None:
    """GET the preview for a real run + real node returns plan + summary."""
    _, ids = scenario
    resp = client.get(f"/runs/{ids['parent_run']}/nodes/{ids['n2']}/fork-plan")
    assert resp.status_code == 200
    body = resp.json()
    assert "plan" in body
    assert "effects_summary" in body

    plan = body["plan"]
    # Plan fields must match what build_plan wired up.
    assert plan["parent_run_id"] == ids["parent_run"]
    assert plan["parent_node_id"] == ids["n2"]
    assert plan["overrides"] == {}
    assert plan["reason"] is None or plan["reason"] == ""
    # ForkPlan schema marker.
    assert plan.get("chronos_fork_plan_version") == 1

    summary = body["effects_summary"]
    # Summary shape (regardless of whether this scenario has effects).
    assert set(summary.keys()) == {
        "total",
        "dangerous_count",
        "tag_counts",
        "dangerous_samples",
    }
    assert isinstance(summary["total"], int)
    assert isinstance(summary["dangerous_count"], int)
    assert isinstance(summary["tag_counts"], dict)
    assert isinstance(summary["dangerous_samples"], list)
    # n2 is step_index=1 in the scenario, n3 is step_index=2 → total == 1.
    assert summary["total"] == 1


def test_fork_plan_preview_404_for_unknown_run(client: TestClient) -> None:
    resp = client.get(f"/runs/{_uuid()}/nodes/{_uuid()}/fork-plan")
    assert resp.status_code == 404
    assert "Run not found" in resp.json()["detail"]


def test_fork_plan_preview_404_for_unknown_node(
    scenario: tuple[SqliteStore, dict[str, str]],
    client: TestClient,
) -> None:
    _, ids = scenario
    resp = client.get(f"/runs/{ids['parent_run']}/nodes/{_uuid()}/fork-plan")
    assert resp.status_code == 404
    assert "Node not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# /runs/compare/n  (R59 — Phase 4 Arc A slice 2 — N-run pivot-anchored compare)
# ---------------------------------------------------------------------------
# Shape: pivot_id + other_ids, bundled runs/trees/diffs + merged alignment.
# N=2 is numerically identical to /runs/compare on the summary row (R58 guard).
# ---------------------------------------------------------------------------


@pytest.fixture
def compare_n_scenario(
    tmp_path: Path,
) -> Iterator[tuple[SqliteStore, dict[str, str]]]:
    """Seed a DB with pivot + two other runs for N-run compare tests.

    ``pivot`` has 3 nodes (plan → draft → polish). ``twin`` has identical
    3 nodes (expect all-equal column). ``variant`` forks off pivot's
    second node with a diverged polish step (expect changed column).
    """
    db_path = tmp_path / "compare_n.db"
    with SqliteStore.open(db_path) as store:
        pivot_id, twin_id, variant_id = "run-pivot-n", "run-twin-n", "run-variant-n"
        for rid, tag in (
            (pivot_id, "pivot"),
            (twin_id, "twin"),
            (variant_id, "variant"),
        ):
            store.put_run(
                Run(
                    id=rid,
                    adapter="langgraph",
                    adapter_thread_id=f"thread-{tag}",
                    status=RunStatus.COMPLETED,
                    started_at=_now(),
                    ended_at=_now(),
                    task_description=f"Run {tag}",
                    tags=["compare-n", tag],
                )
            )

        def _seed_three_nodes(run_id: str, prefix: str, polish_state: str) -> tuple[str, str, str]:
            p, d, po = f"{prefix}-plan", f"{prefix}-draft", f"{prefix}-polish"
            store.put_node(
                Node(
                    id=p,
                    run_id=run_id,
                    step_index=0,
                    node_name="plan",
                    kind=NodeKind.LLM,
                    parent_node_id=None,
                    model_name="gpt-4o",
                    output_state={"phase": "plan"},
                )
            )
            store.put_node(
                Node(
                    id=d,
                    run_id=run_id,
                    step_index=1,
                    node_name="draft",
                    kind=NodeKind.LLM,
                    parent_node_id=p,
                    model_name="gpt-4o",
                    output_state={"phase": "draft"},
                )
            )
            store.put_node(
                Node(
                    id=po,
                    run_id=run_id,
                    step_index=2,
                    node_name="polish",
                    kind=NodeKind.LLM,
                    parent_node_id=d,
                    model_name="gpt-4o",
                    output_state={"phase": polish_state},
                )
            )
            return p, d, po

        pivot_p, pivot_d, _pivot_po = _seed_three_nodes(pivot_id, "pivot", "polish")
        _seed_three_nodes(twin_id, "twin", "polish")
        _seed_three_nodes(variant_id, "variant", "polish-v2")

        # Register variant as a fork of pivot so restrict_to_downstream
        # semantics exercise the same code path as /runs/compare.
        store.put_fork(
            Fork(
                id="fork-variant",
                parent_run_id=pivot_id,
                parent_node_id=pivot_d,
                child_run_id=variant_id,
                created_at=_now(),
                edited_fields={"polish_prompt": "be more concise"},
                reason="variant polish",
            )
        )
        _ = pivot_p  # silence unused-var; kept for readability above.

        ids = {"pivot": pivot_id, "twin": twin_id, "variant": variant_id}
        yield store, ids


@pytest.fixture
def compare_n_client(
    compare_n_scenario: tuple[SqliteStore, dict[str, str]],
) -> TestClient:
    store, _ = compare_n_scenario
    app = build_app(store)
    return TestClient(app)


def test_compare_n_happy_path_returns_merged_alignment(
    compare_n_scenario: tuple[SqliteStore, dict[str, str]],
    compare_n_client: TestClient,
) -> None:
    _, ids = compare_n_scenario
    resp = compare_n_client.get(
        "/runs/compare/n",
        params={"ids": f"{ids['pivot']},{ids['twin']},{ids['variant']}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pivot_id"] == ids["pivot"]
    assert body["other_ids"] == [ids["twin"], ids["variant"]]
    assert set(body["runs"].keys()) == {ids["pivot"], ids["twin"], ids["variant"]}
    assert set(body["trees"].keys()) == {ids["pivot"], ids["twin"], ids["variant"]}
    assert set(body["diffs"].keys()) == {ids["twin"], ids["variant"]}
    # Alignment rows carry per_run tags for each other_id.
    assert isinstance(body["alignment"], list)
    assert len(body["alignment"]) >= 1
    for row in body["alignment"]:
        assert set(row["per_run"].keys()) == {ids["twin"], ids["variant"]}
        for cell in row["per_run"].values():
            assert cell["tag"] in {"equal", "changed", "added", "removed", "absent"}
    # Summary keyed by other_id.
    assert set(body["summary"].keys()) == {ids["twin"], ids["variant"]}
    # Tree shape matches /runs/{id}/tree (same keys).
    for tree in body["trees"].values():
        assert set(tree.keys()) >= {"run_id", "nodes", "edges", "child_runs"}


def test_compare_n_n2_matches_compare_2run_summary(
    compare_n_scenario: tuple[SqliteStore, dict[str, str]],
    compare_n_client: TestClient,
) -> None:
    """N=2 via /runs/compare/n agrees with /runs/compare on the summary row.

    This is the R58 frozen-contract regression guard at the HTTP layer.
    """
    _, ids = compare_n_scenario
    resp_n = compare_n_client.get(
        "/runs/compare/n",
        params={"ids": f"{ids['pivot']},{ids['variant']}"},
    )
    resp_2 = compare_n_client.get(
        "/runs/compare",
        params={"a": ids["pivot"], "b": ids["variant"]},
    )
    assert resp_n.status_code == 200
    assert resp_2.status_code == 200
    n_summary = resp_n.json()["summary"][ids["variant"]]
    two_summary = resp_2.json()["diff"]["summary"]
    for key in ("equal", "changed", "added", "removed"):
        assert n_summary[key] == two_summary[key], (
            f"N=2 compare-n summary[{key}] diverged from /runs/compare: "
            f"n={n_summary[key]} vs 2={two_summary[key]}"
        )


def test_compare_n_404_when_pivot_missing(compare_n_client: TestClient) -> None:
    resp = compare_n_client.get(
        "/runs/compare/n",
        params={"ids": f"ghost-pivot,{_uuid()}"},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_compare_n_400_when_duplicate_ids(
    compare_n_scenario: tuple[SqliteStore, dict[str, str]],
    compare_n_client: TestClient,
) -> None:
    _, ids = compare_n_scenario
    resp = compare_n_client.get(
        "/runs/compare/n",
        params={"ids": f"{ids['pivot']},{ids['twin']},{ids['twin']}"},
    )
    assert resp.status_code == 400
    assert "duplicate" in resp.json()["detail"].lower()


def test_compare_n_400_when_fewer_than_two_ids(
    compare_n_client: TestClient,
) -> None:
    resp = compare_n_client.get("/runs/compare/n", params={"ids": "solo-run"})
    assert resp.status_code == 400
    assert "at least 2" in resp.json()["detail"].lower()
