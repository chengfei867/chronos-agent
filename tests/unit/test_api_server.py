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
