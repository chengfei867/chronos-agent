"""Chronos Local HTTP API — FastAPI read-only server over a :class:`SqliteStore`.

Goal
----
A local read-only HTTP layer on top of the SQLite store so that the eventual
``chronos web`` command (R34-B) — and any external viewer the community builds
— can render reasoning trees without linking against ``chronos.store`` directly.

Scope (R34-A, intentionally minimal)
------------------------------------

* **Read-only.** No POST / PUT / DELETE. Mutations happen via adapters;
  this surface exists purely to render recorded runs.
* **Local-only.** No auth, no CORS, no pagination beyond a ``limit`` query
  param, no streaming, no websockets. This is a loopback tool.
* **Stable, framework-agnostic response shape.** The ``/tree`` endpoint emits
  a "neutral reasoning tree" (nodes + edges + child_runs) that a ReactFlow
  frontend can consume but that does NOT bake ReactFlow's ``position`` /
  ``type`` fields into the contract. Layout is a frontend concern.

Endpoints
---------

``GET /healthz`` — 200 + ``{"status": "ok", "schema_version": ...}``.
``GET /runs?limit=N`` — list most recent runs (default 100).
``GET /runs/{run_id}`` — full run row + all nodes (ordered by step_index).
``GET /runs/{run_id}/nodes`` — nodes only, same order. For UI that paginates or
    diff-compares without round-tripping the run itself.
``GET /runs/{run_id}/tree`` — neutral tree: nodes + sequential edges
    (parent_node_id links) + fork edges (cross-run) + child_runs summary.
``GET /runs/{run_id}/forks`` — forks where this run is the parent.

All endpoints return 404 (not 200 with ``null``) when the run doesn't exist,
so a viewer can distinguish "no such run" from "run exists but has no nodes".

Dependency injection
--------------------

The FastAPI app is built by :func:`build_app(store)` — callers inject a
:class:`SqliteStore` they own the lifecycle of. In production, ``chronos web``
opens the store in a context manager and binds the app to it. In tests, the
fixture pattern is identical. The app does NOT open or close the store.

Why not ``FastAPI.dependency_overrides`` for the store? Because a local tool
binds a single store for the app's entire lifetime — a per-request factory
would just re-import the same handle. A closure over ``build_app(store)`` is
simpler and makes the contract obvious at construction time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from chronos.core.models import SCHEMA_VERSION, Fork, Node, Run

if TYPE_CHECKING:
    from chronos.store import SqliteStore


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _run_to_dict(run: Run) -> dict[str, Any]:
    """Serialize a :class:`Run` to a JSON-safe dict.

    Uses pydantic's own ``model_dump(mode="json")`` so datetime → ISO-8601
    and StrEnum → its string value come for free.
    """
    return run.model_dump(mode="json")


def _node_to_dict(node: Node) -> dict[str, Any]:
    return node.model_dump(mode="json")


def _fork_to_dict(fork: Fork) -> dict[str, Any]:
    return fork.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Tree assembly
# ---------------------------------------------------------------------------


def _assemble_tree(
    store: SqliteStore, run_id: str, nodes: list[Node], forks: list[Fork]
) -> dict[str, Any]:
    """Build the neutral reasoning-tree shape for one run.

    Shape:

    .. code-block:: python

       {
           "run_id": str,
           "nodes": [<node dict>, ...],
           "edges": [
               {"from": <parent_node_id>, "to": <node_id>, "kind": "sequential"},
               {"from": <parent_node_id>, "to": <child_first_node_id>,
                "kind": "fork", "fork_id": str, "child_run_id": str,
                "edited_fields": dict},
               ...
           ],
           "child_runs": [<fork dict>, ...],
       }

    Edge kinds:

    * ``sequential`` — same-run ``parent_node_id`` chain.
    * ``fork`` — cross-run link from the parent's ``parent_node_id`` to the
      first node of the child run. If the child run has no nodes yet
      (e.g. still running), the edge's ``to`` is ``None`` and the frontend
      shows the fork as an unresolved branch.

    This shape is a strict superset of what ReactFlow needs (frontend adds
    ``position`` / ``type`` locally) and is framework-neutral — it doesn't
    bake any single viewer into the API contract.
    """
    edges: list[dict[str, Any]] = []

    # Sequential edges within this run — one per node with parent_node_id set.
    for node in nodes:
        if node.parent_node_id is not None:
            edges.append(
                {
                    "from": node.parent_node_id,
                    "to": node.id,
                    "kind": "sequential",
                }
            )

    # Fork edges out of this run (cross-run). For each fork, look up the
    # first node of the child run so the edge has a concrete target; if the
    # child has no nodes, target is None.
    for fork in forks:
        child_nodes = store.get_nodes_for_run(fork.child_run_id)
        child_first_id: str | None = child_nodes[0].id if child_nodes else None
        edges.append(
            {
                "from": fork.parent_node_id,
                "to": child_first_id,
                "kind": "fork",
                "fork_id": fork.id,
                "child_run_id": fork.child_run_id,
                "edited_fields": fork.edited_fields,
            }
        )

    return {
        "run_id": run_id,
        "nodes": [_node_to_dict(n) for n in nodes],
        "edges": edges,
        "child_runs": [_fork_to_dict(f) for f in forks],
    }


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def build_app(store: SqliteStore) -> FastAPI:
    """Build a FastAPI app bound to ``store``.

    The app closes over ``store``; it does NOT open or close it. Caller owns
    lifecycle (a context-manager pattern works: open store, build app, run
    uvicorn inside the ``with`` block).

    Returns a new :class:`FastAPI` instance each call, so tests can spin up
    independent apps against isolated SQLite files without cross-talk.
    """
    app = FastAPI(
        title="Chronos Local API",
        version="0.2.0a0",
        description=(
            "Read-only local HTTP surface over a Chronos SQLite store. "
            "Runs, nodes, forks, and reasoning trees — intended for the "
            "`chronos web` command and third-party viewers. No auth, "
            "loopback only."
        ),
    )

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "schema_version": SCHEMA_VERSION}

    @app.get("/runs")
    def list_runs(
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        runs = store.list_runs(limit=limit)
        return {"runs": [_run_to_dict(r) for r in runs], "count": len(runs)}

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        nodes = store.get_nodes_for_run(run_id)
        return {
            "run": _run_to_dict(run),
            "nodes": [_node_to_dict(n) for n in nodes],
        }

    @app.get("/runs/{run_id}/nodes")
    def get_run_nodes(run_id: str) -> dict[str, Any]:
        # 404 when the run itself is missing — not when it has zero nodes
        # (a FAILED run with no steps is a valid state we want to show).
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        nodes = store.get_nodes_for_run(run_id)
        return {"nodes": [_node_to_dict(n) for n in nodes], "count": len(nodes)}

    @app.get("/runs/{run_id}/forks")
    def get_run_forks(run_id: str) -> dict[str, Any]:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        forks = store.get_forks_for_parent(run_id)
        return {"forks": [_fork_to_dict(f) for f in forks], "count": len(forks)}

    @app.get("/runs/{run_id}/tree")
    def get_run_tree(run_id: str) -> JSONResponse:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        nodes = store.get_nodes_for_run(run_id)
        forks = store.get_forks_for_parent(run_id)
        tree = _assemble_tree(store, run_id, nodes, forks)
        return JSONResponse(content=tree)

    return app


__all__ = ["build_app"]
