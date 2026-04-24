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

from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

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
           "lanes": [
               {"agent_id": str, "node_count": int, "first_step_index": int},
               ...
           ],
       }

    Edge kinds:

    * ``sequential`` — same-run ``parent_node_id`` chain.
    * ``fork`` — cross-run link from the parent's ``parent_node_id`` to the
      first node of the child run. If the child run has no nodes yet
      (e.g. still running), the edge's ``to`` is ``None`` and the frontend
      shows the fork as an unresolved branch.

    Lanes (R37 — multi-agent concurrent lanes):

    Derived from ``node.metadata["agent_id"]``. Single-agent adapters emit
    ``"main"`` so single-lane runs still get ``[{"agent_id": "main", ...}]``
    and the frontend can render lane decorations uniformly. Order is by
    first appearance (smallest ``step_index``) — stable and deterministic.
    Missing ``agent_id`` defaults to ``"main"`` so legacy DBs recorded before
    the field existed render as single-lane without breaking.

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

    # Lanes — derive from node.metadata.agent_id, preserving first-appearance
    # order so the frontend can render lanes deterministically.
    lanes: list[dict[str, Any]] = []
    seen_agents: dict[str, dict[str, Any]] = {}
    for node in sorted(nodes, key=lambda n: n.step_index):
        agent_id = str(node.metadata.get("agent_id") or "main")
        if agent_id not in seen_agents:
            lane_entry = {
                "agent_id": agent_id,
                "node_count": 0,
                "first_step_index": node.step_index,
            }
            seen_agents[agent_id] = lane_entry
            lanes.append(lane_entry)
        seen_agents[agent_id]["node_count"] += 1

    return {
        "run_id": run_id,
        "nodes": [_node_to_dict(n) for n in nodes],
        "edges": edges,
        "child_runs": [_fork_to_dict(f) for f in forks],
        "lanes": lanes,
    }


# ---------------------------------------------------------------------------
# Landing page HTML
# ---------------------------------------------------------------------------

# Static HTML served at ``/`` — kept as a module constant rather than a
# template file so the whole API is one self-contained ``server.py`` and
# packaging stays trivial (no ``package_data`` wiring needed). When R34-C
# adds a real React/Vue viewer we'll mount it under a separate prefix and
# leave this landing page as a fallback for people who hit the root.
_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Chronos Agent — Local</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root { color-scheme: dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0d1117; color: #c9d1d9;
    max-width: 720px; margin: 4rem auto; padding: 0 1.5rem;
    line-height: 1.6;
  }
  h1 { color: #f0f6fc; font-weight: 600; letter-spacing: -0.02em; }
  code, kbd { background: #161b22; padding: 2px 6px; border-radius: 4px;
              font-size: 0.9em; color: #79c0ff; }
  a { color: #58a6ff; text-decoration: none; }
  a:hover { text-decoration: underline; }
  ul { padding-left: 1.2rem; }
  li { margin: 0.4rem 0; }
  .muted { color: #8b949e; font-size: 0.9em; }
  .pill { display: inline-block; background: #1f6feb33; color: #79c0ff;
          padding: 2px 10px; border-radius: 999px; font-size: 0.8em;
          margin-left: 0.5rem; vertical-align: middle; }
  .cta {
    display: inline-block; margin: 0.5rem 0 1.5rem;
    background: linear-gradient(135deg, #1f6feb 0%, #0969da 100%);
    color: #fff; padding: 0.7rem 1.4rem; border-radius: 8px;
    font-weight: 600; text-decoration: none;
    box-shadow: 0 4px 14px #1f6feb40;
    transition: transform 0.1s ease, box-shadow 0.1s ease;
  }
  .cta:hover { transform: translateY(-1px); text-decoration: none;
               box-shadow: 0 6px 20px #1f6feb66; }
  .cta-row { display: flex; gap: 0.75rem; flex-wrap: wrap; }
  .cta.secondary {
    background: #161b22; color: #c9d1d9; box-shadow: none;
    border: 1px solid #30363d;
  }
  .cta.secondary:hover { background: #1c2128; box-shadow: none; }
</style>
</head>
<body>
  <h1>Chronos Agent <span class="pill">local api</span></h1>
  <p class="muted">
    Read-only HTTP surface over your recorded runs.
    Open the visual tree viewer below, or poke the API directly.
  </p>

  <div class="cta-row">
    <a class="cta" href="/app/">🌲 Open Tree Viewer</a>
    <a class="cta secondary" href="/docs">API Docs</a>
  </div>

  <h2>Endpoints</h2>
  <ul>
    <li><a href="/runs"><code>GET /runs</code></a> — list recorded runs (most recent first)</li>
    <li><code>GET /runs/{run_id}</code> — one run + its nodes</li>
    <li><code>GET /runs/{run_id}/nodes</code> — nodes only</li>
    <li><code>GET /runs/{run_id}/forks</code> — forks where this run is the parent</li>
    <li><code>GET /runs/{run_id}/tree</code> — neutral reasoning tree (nodes + edges + child runs)</li>
    <li><a href="/healthz"><code>GET /healthz</code></a> — liveness + schema version</li>
  </ul>

  <h2>Interactive docs</h2>
  <ul>
    <li><a href="/docs">Swagger UI</a> — try endpoints in-browser</li>
    <li><a href="/redoc">ReDoc</a> — reference-style docs</li>
  </ul>

  <h2>CLI</h2>
  <p>All HTTP endpoints have a CLI equivalent:</p>
  <ul>
    <li><code>chronos runs list</code></li>
    <li><code>chronos runs show &lt;run_id&gt;</code></li>
    <li><code>chronos replay &lt;run_id&gt;</code> — interactive TUI walker</li>
    <li><code>chronos diff &lt;run_a&gt; &lt;run_b&gt;</code></li>
  </ul>

  <p class="muted">
    Stop the server with <kbd>Ctrl-C</kbd>. Source:
    <a href="https://github.com/chengfei867/chronos-agent">chengfei867/chronos-agent</a>.
  </p>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _find_frontend_dist() -> Path | None:
    """Resolve the frontend/dist bundle directory, or None if missing.

    Search order:

    1. ``CHRONOS_FRONTEND_DIST`` env var (explicit override, dev use).
    2. ``<repo_root>/frontend/dist`` — for editable installs / dev checkouts.

    We do NOT walk up arbitrarily; the repo-root lookup is based on this
    file's location, so moving the package into site-packages without
    packaging the dist would correctly return None (and trigger the 503
    fallback in :func:`build_app`).
    """
    import os

    override = os.environ.get("CHRONOS_FRONTEND_DIST")
    if override:
        p = Path(override)
        return p if (p / "index.html").exists() else None

    # src/chronos/api/server.py → src/chronos/api → src/chronos → src → <root>
    repo_root = Path(__file__).resolve().parents[3]
    candidate = repo_root / "frontend" / "dist"
    return candidate if (candidate / "index.html").exists() else None


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

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        """Minimal landing page — a 'you are here' map until R34-C ships a real UI.

        Intentionally single-file HTML with no external assets and no JS build
        step. The goal is: when someone runs ``chronos web`` and a browser
        tab pops open, they see SOMETHING immediately that explains how to
        poke at the API (``/runs``, ``/docs``) and confirms the server is
        bound to the right database. Dark palette matches the README so
        screenshots look cohesive.
        """
        return _INDEX_HTML

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

    # ------------------------------------------------------------------
    # /app/* — ReactFlow viewer (R34-C). Served from the frontend/dist
    # bundle that ships with the wheel. If the bundle is missing (dev
    # checkout pre-build, or unusual packaging), /app returns a 503 with
    # instructions rather than silently 404'ing — so the failure mode is
    # explicit. The mount is best-effort: a missing dist does NOT break
    # the REST API, healthz, or the landing page.
    # ------------------------------------------------------------------
    dist_dir = _find_frontend_dist()
    if dist_dir is not None:
        app.mount(
            "/app",
            StaticFiles(directory=str(dist_dir), html=True),
            name="viewer",
        )
    else:

        @app.get("/app", include_in_schema=False)
        @app.get("/app/{_rest:path}", include_in_schema=False)
        def viewer_missing(_rest: str = "") -> JSONResponse:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "viewer_bundle_missing",
                    "detail": (
                        "frontend/dist/ not found — rebuild with "
                        "`cd frontend && npm install && npm run build`, "
                        "or reinstall the chronos-agent package."
                    ),
                },
            )

    return app


__all__ = ["build_app"]
