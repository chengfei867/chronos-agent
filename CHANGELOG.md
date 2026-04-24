# Changelog

All notable changes to Chronos Agent are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

_Nothing yet — R35 will decide._

## [0.2.0b0] — 2026-04-24 (Round 31 + Round 32 + Round 33 + Round 34-A + Round 34-B + Round 34-C)

### Added (Round 34-C)

- **ReactFlow viewer bundle — `frontend/`** (~500 LOC TSX + CSS, 108KB gzipped after build). New self-contained Vite + React 19 + TypeScript 5 + `@xyflow/react` v12 SPA under `frontend/` with two routes: `#/` lists recorded runs in a clickable table (ID, adapter, status tag, relative-time, task description), and `#/runs/<run_id>` renders the reasoning tree as a ReactFlow DAG (sequential edges solid, cross-run fork edges dashed with a `child_run_id` label), plus a side drawer `NodeDetails` that reveals identity / tool_input / tool_output / usage + cost / error / state_after / metadata / timestamps when a node is clicked. Hash-routing (not HTML5 history) so no server-side rewrite is needed — the FastAPI mount is pure static serving. Custom node renderer per `NodeKind` (`llm`, `tool`, `fn`, `router`, `fork`, `end`) with colored kind-badge + derived `previewOf(node)` that hunts through `tool_output → tool_input → state_after → metadata` for the first conventional string key (`text` / `answer` / `output` / `result` / `content`) so a useful 36-char preview shows on the canvas without demanding a dedicated `content_preview` field on the API contract (neutral tree stays minimal). Dark palette matches the R34-B landing page and the README (`#0d1117` background, `#58a6ff` accents) so screenshots look cohesive across surfaces.
- **`frontend/dist/` committed to git via whitelist** — `.gitignore` rewrite adds `!frontend/dist/` + `!frontend/dist/**` as the **last** pattern so it wins over the earlier generic `dist/` glob (git's last-match-wins ordering — verified with `git check-ignore -v` and `git add --dry-run`). Rationale: the Node toolchain is only needed to *build* the viewer, not to *use* it. Users installing via `uv pip install chronos-agent[web]` get a working `/app` tree viewer with zero npm dependencies, which is non-negotiable for the "GitHub-virality 5-minute quickstart" thesis (R33). The `frontend/.gitignore` whitelists only `dist/` — `node_modules/`, `.vite/`, `.tsbuildinfo` stay ignored.
- **`/app/*` StaticFiles mount on the FastAPI app** (`src/chronos/api/server.py`). `build_app(store)` now resolves `frontend/dist/` via `_find_frontend_dist()` — honors `CHRONOS_FRONTEND_DIST` env override first (for dev or alternate bundle paths), else falls back to `<repo_root>/frontend/dist` computed from `__file__.parents[3]`. Found → `app.mount("/app", StaticFiles(directory=..., html=True), name="viewer")` so `/app/` serves `index.html` and `/app/assets/<hash>.{js,css}` serves the bundle chunks. Missing → a `/app` + `/app/{rest:path}` handler returns **503 with `{error: "viewer_bundle_missing", detail: ...}`** including a `cd frontend && npm install && npm run build` remediation hint, rather than 404'ing silently. Failure mode is explicit by design: REST API, `/healthz`, and the landing page keep working regardless of bundle presence.
- **Landing page CTA to the viewer** (`src/chronos/api/server.py:_INDEX_HTML`) — prominent blue-gradient "🌲 Open Tree Viewer" button (`/app/`) alongside a secondary "API Docs" button (`/docs`). First-time users now see the tree viewer as the obvious next click after `chronos web` opens their browser; the endpoint list stays below for API consumers.

### Design (Round 34-C)

- **`@xyflow/react` v12, not `reactflow` v11** — the `reactflow` npm package was frozen in 11.11.4 and officially rebranded to `@xyflow/react` v12 (same team, same API surface, active development). Pinning to v12 keeps us on the supported branch; the import path `import { ReactFlow, Background, Controls, MiniMap } from "@xyflow/react"` plus `import "@xyflow/react/dist/style.css"` is the current canonical form. No compatibility shims needed.
- **Frontend types.ts mirrors `model_dump(mode="json")` output verbatim** — earlier drafts used shorter names (`framework`, `thread_id`, `finished_at`, `name`, `content_preview`, `extracted`) that diverged from the pydantic `Run` / `Node` / `Fork` models. R34-C rewrites `frontend/src/types.ts` to match the backend contract field-for-field (`adapter`, `adapter_thread_id`, `ended_at`, `node_name`, `tool_name`/`tool_input`/`tool_output`, `error_message`, `cost_usd_cents`, `metadata`, etc.) so the frontend stays truthful about what the API actually returns. Source-of-truth comment at the top of the file points readers back to `src/chronos/core/models.py` when drift is suspected.
- **Layout is a frontend concern, not baked into `/tree`** — `frontend/src/layout.ts` computes ReactFlow `position: {x, y}` from the sequential + fork graph with a simple topological level-by-level layout (BFS from root, 220px horizontal per level, 140px vertical per sibling). The API contract stays position-free — a different viewer (d3, Cytoscape, Graphviz, plain SVG) can render the same `/tree` JSON without our layout choices leaking in.
- **Hash routing, not HTML5 history** — the server-side mount is dumb StaticFiles; it doesn't rewrite unknown paths back to `index.html`. Hash routing (`#/`, `#/runs/<id>`) keeps everything client-side and side-steps the need for a catch-all server rewrite rule, which would otherwise collide with the 503-on-missing-dist fallback semantics.
- **Why `CHRONOS_FRONTEND_DIST` env override exists** — two concrete use cases: (1) dev iteration with a live `vite dev` server where the override points at an out-of-tree dist dir, and (2) distribution packaging that ships `dist/` under `site-packages/chronos/frontend/dist` instead of the repo-relative path. The `parents[3]` fallback is intentional about NOT walking up arbitrarily, so site-packages installs without a bundled `dist/` correctly return `None` → 503, rather than silently finding a stale bundle on the dev's machine.

### Tests (Round 34-C)

- `tests/unit/test_api_server.py` (+4 tests, total **375/375 pass**; api/server.py coverage **100%**). New cases: `test_app_mount_serves_index_when_dist_present` builds a fake `dist/` with a stub `index.html` + `assets/index.js` in a tmp_path, sets `CHRONOS_FRONTEND_DIST` via `monkeypatch.setenv`, builds a FRESH app (the top-level `client` fixture was built before the monkeypatch), and confirms `/app/` returns the stub HTML with `text/html` content-type and `/app/assets/index.js` returns the asset body; `test_app_mount_returns_503_when_dist_missing` points the override at a nonexistent path, builds a fresh client, and verifies `/app`, `/app/`, `/app/index.html`, `/app/deep/nested` all return 503 with `{error: "viewer_bundle_missing"}` and that `/healthz` + `/runs` still return 200 (REST API unaffected); `test_find_frontend_dist_resolver` unit-tests the resolver in isolation — valid override with index.html wins, override missing index.html returns None (explicit fail, not silent repo-root fallback), nonexistent override path returns None; `test_landing_page_advertises_viewer` asserts `href="/app/"` + "Tree Viewer" text appear in the landing HTML so the CTA never regresses silently. Lint/type: ruff clean after `ruff format src/chronos/api/server.py tests/unit/test_api_server.py`, mypy strict on 26 source files (unchanged count).
- **Live end-to-end smoke against real built bundle** (ad-hoc, not in suite) — seeded `/tmp/chr-smoke/s.db` with 2 runs (5 nodes, one with tool_input/tool_output, one with state_after text) via real `put_run`/`put_node` calls on a `SqliteStore`. Started `chronos web --db /tmp/chr-smoke/s.db --port 18766 --no-browser` as a background process. Curl'd 9 paths: `/` → 200, `/app/` → 200 + real `index.html` referencing the current asset hashes, `/app/index.html` → 200, `/app/assets/index-yV9Orvf-.js` → 200, `/runs` → 200 JSON with both runs, `/runs/demo-run-1` → 200, `/runs/demo-run-1/tree` → 200 JSON with 3 nodes + 2 sequential edges, `/healthz` → 200, `/docs` → 200. Confirms the full stack wires end-to-end: Vite build → committed `dist/` → `_find_frontend_dist()` → `StaticFiles` mount → real HTTP → correct asset-hash references in served HTML.

### Added (Round 34-A)

- **Local HTTP API — `chronos.api.server`** (`src/chronos/api/server.py`, ~230 LOC including module docstring). FastAPI app factory `build_app(store: SqliteStore) -> FastAPI` that mounts **six** read-only endpoints over a Chronos store: `GET /healthz` (trivial liveness probe + `schema_version` echo, no store touch); `GET /runs?limit=N` (list runs, most-recent-first, matching `SqliteStore.list_runs` 1:1; `limit` validated by FastAPI `Query(ge=1, le=1000)` → 422 on out-of-range); `GET /runs/{id}` (single Run + ordered Nodes with 404-if-missing); `GET /runs/{id}/nodes` (ordered Nodes only, same order — for UIs that paginate or diff-compare without round-tripping the Run); `GET /runs/{id}/forks` (forks where this run is the parent — 200 with `count=0` for leaf runs, 404 only if the run itself is missing); `GET /runs/{id}/tree` (the contract endpoint — neutral reasoning-tree shape, see §Design). Every `/runs/{id}/...` path is 404-strict on the run (not 200-with-`null`), so a viewer can distinguish "no such run" from "run exists but has no nodes/forks". Response bodies use pydantic's own `model_dump(mode="json")` so `datetime` → ISO-8601 and `StrEnum` → its string value come for free. Store is captured in each route's closure via `build_app(store)` — **no module-level global, no side-effect lifecycle**; callers (tests, `chronos web` in R34-B) own open/close. `pyproject.toml` new `[project.optional-dependencies].web` group (`fastapi>=0.110`, `uvicorn>=0.30`, `httpx>=0.27`). Top-level `chronos.api` package re-exports `build_app`.
- **`SqliteStore.get_forks_for_parent(parent_run_id) -> list[Fork]`** (`src/chronos/store/sqlite.py`) — mirrors `get_fork_for_child` on the other side of the fork relation, ordered by `created_at ASC`. Added for `/runs/{id}/tree` and `/runs/{id}/forks` endpoints; cleaner than ad-hoc SQL in the server layer.

### Design (Round 34-A)

- **Neutral reasoning-tree shape, not ReactFlow-specific** — `/runs/{id}/tree` returns `{run_id, nodes: [<full Node dict>], edges: [...], child_runs: [<full Fork dict>]}` where edges come in two flavors: `{"from": <parent_node_id>, "to": <node_id>, "kind": "sequential"}` for within-run parent-child chains, and `{"from": <parent_node_id>, "to": <child_first_node_id>, "kind": "fork", "fork_id", "child_run_id", "edited_fields"}` for cross-run fork edges. The shape is a strict superset of what ReactFlow needs (frontend computes `position` / `type` locally) and is framework-neutral — nothing about the viewer is baked into the API contract. A fork edge to a child run with no nodes yet (e.g. still running) has `to: null` so the frontend can render "unresolved branch" instead of mis-pointing. `child_runs` is a parallel summary for UIs that want to lazy-load children without re-fetching the full tree.
- **`SqliteStore.open()` now opens the connection with `check_same_thread=False`** — FastAPI dispatches sync endpoints onto a worker thread-pool, so the `TestClient`-or-`uvicorn`-driven reads happen off the thread that opened the store. SQLite itself is thread-safe in its default "serialized" mode; the `sqlite3` module's `check_same_thread` is a Python-layer guard, not an engine-layer one. We hold a single shared connection in autocommit + explicit `transaction()` CM, so flipping the Python guard is safe and matches how every local-server SQLite project on PyPI configures connections. Inline comment at the `sqlite3.connect()` call documents this for anyone auditing the change. No other code path was affected.
- **Route handlers are sync `def`** (not `async def`) — FastAPI runs sync handlers in a worker thread-pool, which is the correct fit for blocking SQLite I/O (doesn't block the event loop). With `check_same_thread=False` set above, this combination is idiomatic FastAPI + SQLite.
- **`build_app(store)` factory, one app per store, no singleton** — each call returns a fresh `FastAPI` instance closed over the given store. Tests exercise this explicitly (`test_build_app_binds_distinct_stores`): two apps bound to two stores don't cross-talk. Prevents the classic "module-level `app = FastAPI()` + global state" trap that makes production bindings hard to test.

### Tests (Round 34-A)

- `tests/unit/test_api_server.py` (17 tests). A two-run fork scenario (parent with 3 nodes → fork → child with 2 nodes) is built via real `put_run` / `put_node` / `put_fork` calls on a temp-file `SqliteStore` (no mocks — the real value of this suite is proving SELECT-shaped reads round-trip correctly through pydantic). Coverage: `/healthz` (1); `/runs` — both runs returned, `limit` respected, `limit=0` → 422 (3); `/runs/{id}` — run + ordered nodes + 404 (2); `/runs/{id}/nodes` — ordered by `step_index` ASC + 404 (2); `/runs/{id}/forks` — parent returns its fork with `edited_fields` intact, leaf run returns `count=0` with 200 not 404, unknown run 404 (3); `/runs/{id}/tree` — sequential edges match parent_node_id chain exactly (2 edges for 3-node chain), cross-run fork edge has `{from: n2, to: c1_first, kind: "fork", fork_id, child_run_id, edited_fields}`, `child_runs` summary lists forks-out, leaf run has no fork edges, 404 (5); `build_app` factory isolation — two apps against two stores don't share state (1). Total suite **363/363 pass** (+17 from R33's 346); ruff clean, mypy strict on 26 src files.
- **Live uvicorn smoke-test** (ad-hoc, not in suite) — `uvicorn.Server` bound to 127.0.0.1:18734 serves `/healthz` + `/runs` over real HTTP in a daemon thread. Confirmed the `check_same_thread=False` fix works end-to-end, not just under `TestClient`.

### Added (Round 34-B)

- **`chronos web` CLI command** (`src/chronos/cli/web.py`, ~180 LOC). One-command on-ramp that turns a recorded `chronos.db` into a browseable surface — prints a banner, starts the R34-A FastAPI app via uvicorn against the resolved DB, and opens a browser tab at the landing page. Signature: `chronos web [--host HOST] [-p PORT] [--db PATH] [--no-browser]`; defaults `127.0.0.1:8765`. Reuses `_open_store` / `_resolve_db_path` from `cli._common` so DB resolution (flag > `$CHRONOS_DB` > `./chronos.db`) matches every other subcommand verbatim. **Lazy uvicorn import** inside `web_command` so a base install without the `[web]` extra still runs `chronos --help` and every non-web subcommand without ImportError; hitting `chronos web` without the extra produces a friendly install hint instead of a traceback. **Browser auto-open via `threading.Timer(1.0, ...)`** on a daemon thread — uvicorn's public API has no caller-side "after startup" hook, so we schedule the `webbrowser.open` call ~1s after `uvicorn.run()` starts, which is empirically enough for loopback bind. `webbrowser.open` returning `False` (headless platforms) emits a rich notice and falls through to serving normally. `--no-browser` flag short-circuits the Timer entirely. **`reload=True` intentionally NOT supported** — uvicorn's reloader spawns a subprocess that re-imports the module path, which would lose our closure-bound store; `chronos web` is an inspection tool, not a dev server for editing `server.py`. Store lifecycle bound to the request to serve: `open → build_app(store) → uvicorn.run → store.close()` in a `finally` so a uvicorn startup crash still releases the SQLite handle.
- **`/` landing page on the FastAPI app** (`src/chronos/api/server.py`) — dark-themed single-file HTML served at the API root (not `include_in_schema`, so `/docs` stays clean). Zero external assets, zero JS build step: the whole page is a module-level `_INDEX_HTML` constant so packaging stays trivial (no `package_data` wiring). Palette matches the README (`#0d1117` background, GitHub-dark blue links) so future screenshots look cohesive. Links to every read endpoint (`/runs`, `/runs/{id}/nodes`, `/runs/{id}/forks`, `/runs/{id}/tree`, `/healthz`), the Swagger UI (`/docs`) and ReDoc (`/redoc`), plus CLI-equivalent commands for users who prefer the terminal. This is a fallback viewer that R34-C's real frontend will mount over a separate prefix and leave in place for `/` requests.
- **Bilingual README quickstart + `docs/cli-reference.md` entry** — English + 中文 quickstart sections both add a third step showing `uv pip install 'chronos-agent[web]'` then `chronos web --db ...`. CLI reference doc gains a full `chronos web` section with the flag table, endpoint links, landing page description, and an SSH port-forward recipe for remote hosts.

### Design (Round 34-B)

- **Why `chronos web` instead of asking users to run uvicorn themselves** — `uvicorn chronos.api.server:app` can't work as-is because `build_app(store)` is a factory that needs a store, not a module-level `app`. Exposing a module-level `app` would force an implicit default DB path and bake "one store per process" into the contract, which conflicts with the R34-A isolation invariant (two apps against two stores don't cross-talk). A dedicated subcommand owns DB resolution + browser-open + banner + uvicorn invocation as one unit, reusing the same helpers as every other `chronos` subcommand, which is the minimum-friction path to "runs recorded → browser open".
- **Dependency injection for uvicorn.run and webbrowser.open** — `web_command` accepts optional `run_server_fn` / `open_browser_fn` parameters defaulting to module-level `_default_run_server` / `_default_open_browser` wrappers. Unit tests inject spies that record call args without binding a port or spawning a browser process. This matches the DI pattern every other CLI module in `chronos.cli.*` already uses (`open_store_fn`, `console`) — no new mocking strategy, no patching via `unittest.mock`. The typer-wired CliRunner tests monkey-patch the module-level defaults instead (demonstrates both seams).
- **Path resolved for the banner, not store-attribute-read** — the banner prints the DB path that was actually opened. We call `_resolve_db_path(db)` ourselves (rather than reading e.g. `store._path`, which doesn't exist on `SqliteStore`) so the banner truthfully shows what `$CHRONOS_DB` or the default-cwd fallback resolved to. Users debugging a "wrong DB" confusion would otherwise see `None` in the banner and have no visible signal of what was actually opened.

### Tests (Round 34-B)

- `tests/unit/test_cli_web.py` (8 tests). Split into `TestWebCommand` (direct `web_command(...)` calls with spy `run_server_fn` + `open_browser_fn` injected — no typer wiring, no socket bind) and `TestWebCLI` (via `typer.testing.CliRunner` with `monkeypatch.setattr` on the module-level defaults — exercises the registration + option parsing layer). Coverage: uvicorn invoked with default host/port and a FastAPI `app` carrying the 6 R34-A routes; custom `--host 0.0.0.0` + `--port 9001` propagate; browser opens with correct URL after Timer fires (pytest sleeps 1.2s to wait out the 1.0s Timer); `--no-browser` suppresses the open even after Timer delay; `webbrowser.open` returning `False` is non-fatal (emits notice, doesn't raise); missing `--db` path causes `typer.Exit` before uvicorn is ever called; `chronos web --help` works without requiring `[web]` extras at import time (pins the lazy-import design); end-to-end typer-wired invocation reaches the spy uvicorn with the right port. Total suite **371/371 pass** (+8 from R34-A's 363); ruff clean, ruff format clean, mypy strict on 26 src files (unchanged count — new module didn't widen the src surface because it imports cleanly under strict).
- **Live smoke-test against a real empty DB** (ad-hoc, not in suite) — started `chronos web --db /tmp/smoke.db --port 18766 --no-browser` as a background process, curl'd `/healthz` (→ `{"status":"ok","schema_version":"0.1.0"}`), `/` (→ 200, 2525 bytes of landing HTML), `/runs` (→ `{"runs":[],"count":0}`). Confirmed end-to-end wiring: CLI flag → `_open_store` → `build_app(store)` → uvicorn bind → HTTP response matches R34-A TestClient contracts.

### Added (Round 33)

- **AutoGen adapter (record-only)** — `src/chronos/adapters/autogen/__init__.py` + `recorder.py` ship `AutoGenRecorder` (implements `RecorderProtocol`) and `autogen_adapter = _AutoGenAdapter()` module-level singleton satisfying `AdapterProtocol` (verified by `isinstance()` via `@runtime_checkable`). `name="autogen"`, `version_constraint=">=0.7,<0.8"`. **Strategy**: users write `with recorder.record(team, thread_id=...) as ref: asyncio.run(team.run(task=...))` — the sync `RecorderProtocol` context manager wraps AutoGen's async-first API via `asyncio.run()` at the user call-site, walking `TaskResult.messages` on CM exit to build the Node tree. Two channels accepted for delivering the result to the recorder: primary `ref.submit_result(result)` (explicit) or fallback `runtime.messages` attribute (if the user forgets). Message→NodeKind map covers `TextMessage` (source-aware: user→FN, assistant→LLM), `ToolCall*` events→TOOL, `HandoffMessage`→ROUTER, `StopMessage`→END, with merge-over-default user overrides via `kind_map`. Usage extracted from AutoGen's per-message `models_usage.RequestUsage` (bypasses ADR-015 callback path — `build_recorder(usage_extractor=...)` raises `AdapterError` to make this loud). Each Node's `state_after = {"messages": [...cumulative serialized messages...]}` since AutoGen's state IS its message history. `fork()` structurally conforms but raises `AdapterError("...See ADR-017 §Decision")` (Phase 3 candidate). `pyproject.toml` new `[project.optional-dependencies].autogen` group (`autogen-agentchat>=0.7.5`, `autogen-ext>=0.7.5`). Top-level `chronos.adapters` package re-exports `AutoGenRecorder` + `autogen_adapter`. **First adapter implementing ADR-017 sync-wrap strategy; third adapter shipping under ADR-016 — AutoGen was the highest-risk entry in R27's multi-framework risks doc (R-4 async mismatch) and it landed without mutating the sync Protocol family.**

### Added (Round 33) — ADR

- **ADR-017 — AutoGen Adapter Sync Wrap Strategy** (`docs/decisions/ADR-017-autogen-adapter-sync-wrap.md`, ~9.6 KB, Accepted). Decides Path A (users call `asyncio.run()` at the Chronos boundary; `RecorderProtocol` stays sync) over Path B (introduce a parallel `AsyncRecorderProtocol` family). Four-reason rationale ordered for a GitHub-breakout OSS project: DX first (one idiom users already know), single Protocol family = single audit surface, 3-min spike proved `TaskResult.messages` is post-hoc sufficient (streaming is Phase 3+ UI work), Path B remains available as a strict superset if later needed. Rollback plan: if Phase 2 dogfood reveals `asyncio.run()` too painful (FastAPI/Jupyter loop-already-running), add `AsyncRecorderProtocol` in v0.3 as a superset without breaking sync callers. **Resolves risks-doc R-4 (async vs sync) without mutating ADR-016.**

### Tests (Round 33)

- `tests/unit/test_adapter_autogen.py` (10 tests): duck-typed `_StubMessage` / `_StubTaskResult` / `_StubTeam` — **does NOT import `autogen_agentchat`** so the core test suite doesn't need the optional dep. Covers: happy-path `submit_result` with multi-message TaskResult producing the right NodeKind chain; `runtime.messages` fallback when `submit_result` is omitted; usage extraction from `models_usage.RequestUsage`; exception during recorded block → failed-shell Run persistence + re-raise; `fork()` raises `AdapterError` citing ADR-017; structural `isinstance(autogen_adapter, AdapterProtocol)` + `isinstance(rec, RecorderProtocol)` conformance; factory `build_recorder(usage_extractor=...)` raises `AdapterError` with the right channel hint; unknown `**adapter_specific` kwarg rejection (R32 Linear pattern); custom `kind_map` overrides merge over defaults; zero-message TaskResult produces Run with 0 nodes (visibility over silent success). Total suite **346/346 pass** (+10 from R32's 336); mypy strict + ruff clean on 24 src files.

### Fixed (Round 33)

- **`SqliteStore.put_run()` + `ON DELETE CASCADE` pitfall documented in adapter code** — discovered while implementing AutoGen recorder: `put_run()` uses `INSERT OR REPLACE`, which at the SQLite level is "DELETE then INSERT"; `nodes.run_id REFERENCES runs(id) ON DELETE CASCADE` means a second `put_run()` in the same transaction cascade-deletes every Node we just inserted. Fix in `autogen/recorder.py::_persist_run_and_nodes`: compute final state + serialized message list BEFORE opening the transaction, then write the Run exactly once as `COMPLETED` with `ended_at` + `final_state` set up front, then insert Nodes. Long inline comment documents the trap for future adapters. **Lesson (now in CONTEXT.md §5 "old facts"): never call `put_run()` twice in the same transaction; if mid-flight status updates are needed later, add an `update_run_status()` store method that doesn't cascade.**

### Added (Round 32)

- **Module-level `AdapterProtocol` instances** — `langgraph_adapter` (`src/chronos/adapters/langgraph.py`) and `linear_adapter` (`src/chronos/adapters/linear/__init__.py`) now ship as importable singletons satisfying `chronos.adapters.protocols.AdapterProtocol` structurally (verified by `isinstance()` via `@runtime_checkable`). Each carries canonical `name` (`"langgraph"` / `"linear"`), `version_constraint` (`">=1.1,<2"` / `""` — empty string per ADR-016 P2 for zero-dep adapters), and a uniform `build_recorder(store, *, kind_map=None, usage_extractor=None, **adapter_specific)` factory. LangGraph routes both `kind_map` and `usage_extractor` to the recorder constructor and raises `AdapterError` on any unknown `**adapter_specific` kwarg. Linear raises `AdapterError` on `kind_map` (lives on `LinearRuntime`, not the recorder) or `usage_extractor` (Linear uses the `__chronos_usage__` state-key hint, not an extractor callback) with a helpful message directing the caller to the right channel; accepts `adapter_name` as the one documented `**adapter_specific` kwarg. Top-level `chronos.adapters` package re-exports both instances + adds them to `__all__`. **First concrete implementations of ADR-016 P2 `AdapterProtocol` — upgrades the Protocol from "contract with no live instance" to "contract with two shipping impls". Prep for future adapter registry / CLI `chronos adapters list` commands; also templates the shape AutoGen's `autogen_adapter` will follow.**

### Tests (Round 32)

- `tests/unit/test_adapter_instances.py` (21 tests, 5 test classes): **TestMetadata** — `name` / `version_constraint` documented values for both adapters. **TestAdapterProtocolConformance** — `isinstance(langgraph_adapter, AdapterProtocol)` + `isinstance(linear_adapter, AdapterProtocol)` + both `build_recorder()` outputs pass `isinstance(rec, RecorderProtocol)`. **TestLangGraphBuildRecorder** — `kind_map` / `usage_extractor` forwarding, default-kwargs path, `AdapterError` on unknown `**adapter_specific`. **TestLinearBuildRecorder** — default adapter_name, custom adapter_name via `**adapter_specific`, three `AdapterError` paths (kind_map non-None, usage_extractor non-None, unknown kwarg). **TestTopLevelExports** — top-level `ca.langgraph_adapter is langgraph_adapter` identity, both in `ca.__all__`, enumerable-roster smoke test. Total suite 336/336 (+21 from R31's 315); 93% coverage; mypy strict + ruff clean.

### Changed (Round 31)

- **`src/chronos/adapters/protocols.py` introduced** (ADR-016 rollout step 2) — single canonical home for `RunRef` / `ForkRef` / `AdapterError` dataclasses and the three documented ADR-016 Protocols (`RecorderProtocol`, `AdapterProtocol`, `NodeIdentityResolver`). All three Protocols carry `@runtime_checkable` for cheap `isinstance()` smoke tests; real signature-level conformance is still verified by the existing `inspect.signature` tests in `tests/unit/test_adapter_linear.py`. **Strictly additive / backward-compatible**: `chronos.adapters.langgraph` and `chronos.adapters.linear.recorder` now re-import `RunRef` / `ForkRef` / `AdapterError` from the new module and re-export them unchanged; any existing import path (`from chronos.adapters.langgraph import RunRef`, `from chronos.adapters.linear import AdapterError`, etc.) keeps working. The top-level `chronos.adapters` package now also exposes the three Protocols + the shared dataclasses/error for direct import. Eliminates the R28 L4 pre-existing tech-debt ticket (two parallel `RunRef` / `ForkRef` / `AdapterError` class hierarchies) before the AutoGen adapter lands and adds a third.

### Added (Round 31)

- **`tests/unit/test_adapter_protocols.py`** (~220 LOC, 22 tests). Four test classes covering: (1) **canonical-identity** — `lg_mod.RunRef is RunRef`, `lin_mod.ForkRef is ForkRef`, `lg_mod.AdapterError is AdapterError` and `lin_mod.AdapterError is AdapterError` via literal `is` identity assertions, plus cross-adapter `isinstance` compatibility; (2) **dataclass-shape** — default field values, `node_ids` list is not shared between instances (`default_factory` correctness), `ForkRef` requires positional args; (3) **Protocol conformance** — `LangGraphRecorder` / `LinearRecorder` pass `isinstance(x, RecorderProtocol)` via `@runtime_checkable`, duck-typed stubs satisfy `AdapterProtocol` and `NodeIdentityResolver`, `cast(RecorderProtocol, rec)` smoke test exercises ADR-016 rollout step 2's type-safety claim on both adapters; (4) **public-surface** — `protocols.__all__` is exhaustive, `chronos.adapters` package-level `__all__` advertises all seven public names (3 Protocols + 2 dataclasses + `AdapterError` + `LangGraphRecorder`).

## [0.2.0a0] — 2026-04-24 (Round 24 + Round 25 + Round 26 + Round 27 + Round 28 + Round 29 + Round 30)

**Theme**: Phase 2 entry bundle. Six rounds of contract formalisation + one dogfood + one reference adapter + one release cut. ADR-014 scorecard: **R1 ✅ / R2 ✅ / R3 ✅ / R4 ✅ — 4/4 green, Phase 2 formally unblocked.** Adapter interface (ADR-016) + extractor contract v2 (ADR-015) are now the stable v0.2.x public contracts for framework authors; first reference adapter (Linear pipeline, zero-dep) ships as the concrete R1 impl; multi-framework risks catalog (R27) stands as the Phase-2 gotchas reader; dual-adapter CI dogfood (R29) enforces the interface by running two implementations through it. Zero new features beyond what R24-R29 already landed — R30 is a pure packaging cut.

### Release (Round 30)

- `__version__` / `pyproject.toml::version` / CLI status line bumped `0.1.6` → `0.2.0a0`. CLI status string updated to reference Phase 2 entry: "Phase 2 entry — adapter interface stable (ADR-016), reference Linear adapter, dual-adapter CI dogfood (ADR-014 4/4 green), v0.2.0a0". No feature code changed in R30 — all the substance was landed R24-R29 and sat in `[Unreleased]` until this cut.

### Added (Round 29)

- **Dual-adapter CI dogfood** (`tests/integration/test_dual_adapter_dogfood.py`, ~540 LOC, 4 tests). Three scenarios run symmetrically against both `LangGraphRecorder` and `LinearRecorder` via a deterministic `FakeLLM`, asserting equivalence at the persisted `Run` / `Node` / `Fork` row level (not in-memory adapter state): **Scenario A** — record 4-step research→draft→critique→polish pipeline, both adapters produce equivalent `Run + 4×Node` with sequential `parent_node_id` chain (targets risks-doc R-1 event-model drift); **Scenario B** — fork at the `research` node with `{"research": "HIJACKED-research"}` override, asserts both adapters (LangGraph via `update_state(as_node=...) + invoke(None, …)` checkpointer resume; Linear via re-execution from the override point) produce child runs whose first node carries the override through to `state_after`, validating ADR-016's **postcondition-only** fork contract (targets R-2 fork portability); **Scenario C** — usage metering with matching sha256-derived fake tokens wired via `UsageExtractor` callback on LangGraph side and `__chronos_usage__` state-key hint on Linear side, asserts identical `Node.usage` rows across both adapters (targets R-3 usage gaps). Plus one trivial sanity marker test. **Resolves ADR-014 R3 ✅ — the 4th and final Phase-2 entry criterion is now green. ADR-014 scorecard: R1 ✅ / R2 ✅ / R3 ✅ / R4 ✅ — Phase 2 formally unblocked at R30.**

### Changed (Round 29)

- **`LinearRecorder` usage-hint API generalized** (`src/chronos/adapters/linear/recorder.py`). The `__chronos_usage__` state-dict key now accepts three shapes for parity with the LangGraph adapter's ADR-015 `UsageResult` contract: `dict` (unpacked into `Usage(**hint)`); `Usage` instance (used as-is); or any duck-typed object exposing `prompt_tokens` / `completion_tokens` / `reasoning_tokens` / `cost_usd_cents` / `model_name` attrs (e.g. the adapter-layer `UsageResult` dataclass — imported via duck typing to avoid a hard dep from this zero-dep adapter onto `langgraph_usage.py`). Previous behavior (dict-only) is preserved as one of the three branches; all existing tests unchanged. **This gap was surfaced by the Round 29 dogfood test (Scenario C) — a concrete secondary win of ADR-014 R3's "test the interface by running two implementations through it" mandate; exactly the kind of asymmetry unit tests on either adapter in isolation could not catch.** Docstring §"Usage metering" updated to enumerate all three accepted shapes and explain the duck-typing rationale.

### Docs (Round 29)

- **R29 verdict section appended to `docs/research/multi-framework-risks.md`** (~80 LOC). Each risk updated with post-dogfood verdict: **R-1** ⚠️ partially confirmed (persisted-shape equivalence proven but Linear is a LangGraph simplification by construction — true event-model divergence requires AutoGen; severity unchanged at Medium); **R-2** ✅ confirmed sufficient (postcondition-only fork contract is the correct abstraction; severity lowered High → Medium-Low, effectively resolved for Phase 2); **R-3** ⚠️ API parity achieved + Linear adapter gap fixed as above, real-LLM provider parity testing still future work (severity unchanged at Medium); **R-4** / **R-5** / **R-6** unchanged (not exercised by R29); **no new risks (R-7) surfaced** — all failures encountered during R29 were test-author typos (field name `parent_node_id` vs. `parent_id`) or the R-3 API gap, not architectural surprises. Final ADR-014 checklist delta section recording all 4/4 criteria green.

### Added (Round 28)

- **Linear-pipeline reference adapter** (`src/chronos/adapters/linear/`, ~385 LOC across `__init__.py` + `recorder.py`, zero external dependencies). Implements ADR-016 `RecorderProtocol` with the same public shape as `LangGraphRecorder`: `record(runtime, *, thread_id, …)` and `fork(runtime, *, parent_run_id, at_node_id, overrides, child_thread_id, …)` context managers, populating `RunRef` / `ForkRef` dataclasses on exit. `LinearRuntime` is a plain ordered list of `(node_name, step_fn: dict → dict)` pairs with duplicate-name detection; `LinearRecorder` iterates steps inline, captures `state_before / state_after` per step into `Node` rows, persists `Run + Nodes + Fork` in a single `store.transaction()`. Fork semantics mirror the Protocol postcondition (parent `state_after` + `overrides` → seeded state → re-execute `runtime.steps[fork_index+1:]`); no checkpointer involved, validating R27 risks-doc R-2 mitigation (fork-by-re-execution is a legal mechanism). Optional usage metering via a `__chronos_usage__` dict key in a step's return value — extracted into `Node.usage` and popped from `state_after` to keep diffs clean (matches ADR-015 Layer 1 `UsageResult MAY be None` semantics). Failed step functions persist a zero-node `status=FAILED` Run shell for visibility then re-raise; contract violations (non-dict return, mismatched parent run/node, same-thread-id fork, duplicate node names) raise `AdapterError`. **Resolves the *implementation* half of ADR-014 R1** — the contract (R26) + impl (R28) are both green. **ADR-014 scorecard: R1 ✅ / R2 ✅ / R3 ❌ / R4 ✅ — 3/4 green, R29 closes R3.**

### Tests (Round 28)

- `tests/unit/test_adapter_linear.py` (25 tests, 99% coverage on the new module): `TestLinearRuntime` (4: duplicate-name rejection, `step_index_of` lookups, kind_map default); `TestRecordHappy` (7: single-step persistence, multi-step parent-id chain, default empty initial_state, kind_map application, usage-hint extraction+pop, task/tags propagation, num_steps metadata); `TestRecordErrors` (2: non-dict return → `AdapterError`, exception → failed shell Run); `TestFork` (8: middle-node tail resume, last-node empty child, unknown parent/node validation, cross-parent at_node_id, same-thread-id rejection, non-linear parent rejection, fork-time step exception → failed child); `TestProtocolConformance` (4: `inspect.signature` shared-kwargs check vs. `LangGraphRecorder` for both `record()` and `fork()`, plus `RunRef`/`ForkRef` lifecycle shape). Total suite **289/289 pass, 94% coverage** (up from 264/264, 93%).

### Added (Round 27)

- **Research note — Multi-Framework Portability Risks** (`docs/research/multi-framework-risks.md`, ~14 KB). First document in a new `docs/research/` tree, distinct from ADRs because the content is a living risk register (with review cadence appending verdicts as adapters land), not a single Accepted decision. Catalogs **six risks** the adapter interface (ADR-016) contract alone cannot answer: **R-1** event-model drift (Medium; LangGraph checkpoint snapshots vs. AutoGen message stream vs. CrewAI task DAG — owner ADR-016, mitigated by `NodeIdentityResolver` + explicit \"no cross-framework diff invariant\" non-promise); **R-2** fork primitive fundamentally non-portable (**High**; ADR-016 `fork()` Protocol intentionally specifies *postcondition only* — child run starts from parent `state_after` + overrides — not mechanism; Phase 2 red line: no `chronos.core.*` may call LangGraph checkpointer methods; adapters without fork support must raise `AdapterError(\"fork not supported\")` at call time, citing R23-A `InMemorySaver` empirical trap); **R-3** usage metering gaps (Medium; ADR-015 Layer 1 already permits `UsageResult=None`, Layer 4 accumulation policy invariant — CI double-dogfood at R28-R29 will assert non-zero usage for real-LLM runs, citing R18 multi-LLM-per-node undercount that inspired ADR-012); **R-4** async vs sync execution (Medium; Deferred ADR-017 triggered by the first AutoGen adapter PR — parallel `AsyncRecorderProtocol` hierarchy, not a mutation of the sync Protocol); **R-5** deterministic replay not cross-framework (Low, Phase 3; `chronos replay` gains an `--adapter langgraph` guard at R28-R29, defaulting to error-with-helpful-message on non-LangGraph runs); **R-6** side-effect strategy (Low, Phase 3; status quo of `fork plan --emit python` stub with explicit TODO blocks is the correct UX, defers `@chronos.pure` taxonomy to a speculative ADR-019). Includes summary table, Phase 2 entry checklist delta (**3/4 contract+doc criteria now green** after R27; R1 impl + R3 remain as R28-R29), and review-cadence clause committing to append pass/fail verdicts when the reference adapter lands. **Resolves ADR-014 R4** — the final contract/doc-side Phase 2 entry criterion. No code changes.

### Added (Round 26)

- **ADR-016 — Adapter Interface (Protocol-Based Contract for Framework Recorders)** (`docs/decisions/ADR-016-adapter-interface.md`, ~15 KB, Accepted). Defines three `typing.Protocol` classes in a future `src/chronos/adapters/protocols.py`: **`RecorderProtocol`** (framework-agnostic `record()` / `fork()` context-manager contract with five lifecycle invariants — atomicity, idempotency, `AdapterError` as the only legal framework-leak, silent-noop on empty runs, failed-run persistence + re-raise); **`AdapterProtocol`** (module-level plugin shape: `build_recorder()` + `name` + `version_constraint` + `**adapter_specific` pressure-release kwargs); **`NodeIdentityResolver`** (Phase-2-facing hook for per-framework `(node_name, node_kind)` derivation). Includes a framework-portability table (LangGraph / AutoGen / CrewAI) across six axes (execution model, node identity, state, fork primitive, usage origin, determinism), five rejected alternatives (`abc.ABC` base class, single merged Protocol, drop `NodeIdentityResolver`, fold `UsageExtractor` into Recorder, typed `Runtime` Protocol), and a five-step rollout ending in ADR-014 gate check. Parameter rename `graph=` → `runtime=` at the contract level; `LangGraphRecorder` keeps `graph=` as a positional-compatible alias so no user call sites break. **Resolves the *contract* half of ADR-014 R1** (4/4 Phase 2 entry criteria: R1 contract ✅ / impl ❌, R2 ✅, R3 ❌, R4 ❌). No code changes in this round — contract precedes implementation deliberately.

### Changed (Round 26) — roadmap alignment

- `docs/roadmap.md` large refresh correcting ~18 rounds of checkbox drift. **Phase 1** header now reads "✅ COMPLETE (shipped through R25; current tag `v0.1.6`)" with a retrospective note on the 25+-round actual duration vs. 6-10-round estimate, attributing the overrun to (a) pulling forward usage extraction (ADR-009 → ADR-015), (b) three dogfood rounds, (c) fork-CLI reshape (ADR-008, ADR-013), (d) R24-R26 contract formalisation. **M1.1 / M1.2 / M1.3** checkboxes updated from `[ ]` to `[x]` with round attribution (spike outcomes merged into per-round progress docs, not a standalone `spikes-result.md`; `make`/`just` explicitly de-scoped as `uv run` covers the gap). **M1.4** usage-extraction sub-bullet added (originally deferred to M2, delivered ahead in Phase 1 via ADR-009 → ADR-015). **M1.7** (Replay) and **M1.8** (Diff + fork CLI) and **M1.9** (Documentation + Release) all updated to ✅ DONE with ADR-008 / ADR-013 / ADR-006 / ADR-007 cross-references and a note that the shipped `fork plan` interface supersedes the original `--set-state k=v` design. **Phase 2** key-milestones section rewritten: replaced the stale "AutoGen adapter (ADR-005 on adapter interface)" bullet (ADR-005 is fork semantics; never was the adapter interface) with an ADR-014 criteria status table (R1/R2/R3/R4 with per-gate target rounds) and an updated top-of-phase bullet referencing ADR-016 and explicitly allowing a minimal linear-pipeline adapter as the R1 impl reference. **Footer** gains a "drift detected mid-phase → refresh immediately" rule (lesson learned: 18 rounds elapsed between last refresh and this one).

### Added (Round 25)

- **ADR-015 — Extractor Contract v2 (Framework-Agnostic Consolidation)** (`docs/decisions/ADR-015-extractor-contract-v2.md`, ~17 KB, Accepted). Consolidates ADR-009 (R12 hook), ADR-010 (R15 native extractors), ADR-011 (R17 serialization boundary), ADR-012 (R18 multi-LLM-per-node) into a single five-layer contract: **Layer 1** data shape (`UsageContext` / `UsageResult` frozen dataclasses, framework-agnostic invariant); **Layer 2** protocol & lifecycle (six lifecycle invariants including "a buggy extractor must NEVER abort a recording"); **Layer 3** serialization boundary (recursive pydantic→dict `_jsonable` algorithm, invariant across all adapters); **Layer 4** multi-call-per-node delta-accumulation policy (invariant; slicing SHAPE is framework-specific); **Layer 5** convenience extractor naming + provider field-mapping tables (Anthropic / OpenAI / LangChain std) + duck-typing rule + `cost_usd_cents = None` default. Includes a framework-portability matrix showing exactly which layers AutoGen / CrewAI adapters must honor verbatim vs. specialize. Resolves ADR-014 R2 ✅ (1/4 Phase 2 entry criteria now green).

### Changed (Round 25) — ADR breadcrumbs

- `ADR-009-usage-extractor-hook.md`, `ADR-010-native-usage-extractors.md`, `ADR-011-state-serialization-boundary.md`, `ADR-012-multi-llm-per-node-usage.md` each gain a `Consolidated into: ADR-015 (R25)` header line pointing future readers at the authoritative spec while preserving the original decision context. No content changes to the predecessor ADRs beyond the breadcrumb — they remain the historical record for *why* each layer of the contract was adopted.

---

### Added (Round 24)

- **ADR-014 — Phase 2 Entry Criteria** (`docs/decisions/ADR-014-phase-2-entry-criteria.md`). Formalises when Phase 2 (AutoGen adapter, Web UI, multi-agent lanes) is allowed to begin. Four **required** criteria: R1 adapter interface frozen (with ADR + one non-trivial change implementable without touching `chronos.core.*`), R2 extractor contract v2 consolidated into a single ADR, R3 one *adversarial* LangGraph dogfood (candidate: `.astream_events` streaming, explicitly flagged untested in R17 case study), R4 `docs/CONTEXT.md` §4 refreshed for Phase-2 operational red lines. Three **optional** confidence-raisers: O1 second LLM backend exercised, O2 external user signal, O3 performance baseline. All four required are ❌ as of R24 — non-binding work breakdown puts Phase 2 opening around R29. Ties back to R10 near-miss (agent caught itself mid-`uv add autogen-agentchat` under "自由发挥") by replacing vibe-based discipline with a falsifiable checklist.

### Fixed (Round 24) — test harness color-env pollution

- `tests/conftest.py` (new file) adds a top-level autouse fixture that neutralises five shell color env vars (`FORCE_COLOR`, `NO_COLOR`, `CLICOLOR`, `CLICOLOR_FORCE`, `PY_COLORS`), sets `TERM=dumb`/`COLUMNS=80`, and monkeypatches the module-level `chronos.cli._common.console` **and** `chronos.cli.console` to a fresh no-color `Console(force_terminal=False, no_color=True, color_system=None, width=80, highlight=False)`. Restores automatically per pytest `monkeypatch` semantics. Fixes v0.1.6 demo-report Finding #1: five CLI tests (`test_{diff,runs,replay}_help_surfaces`, `test_cli_fork_plan_json_to_stdout`, `test_cli_fork_plan_emit_python_writes_valid_stub`) failed when developers ran `pytest` with `FORCE_COLOR=1` exported (common for terminal-capture workflows), because `rich` emitted ANSI sequences that broke `substring in result.stdout` assertions across line wraps. The fix is test-harness-only; user CLI invocations retain colors as before. Verified: **264/264 pass with `FORCE_COLOR=1` set**.

---

## [0.1.6] — 2026-04-23 (Round 23-A + Round 23-B + Round 23-C)

**Theme**: R22's `fork plan --emit python` survives first real use. Dogfood of the feature against the R17 supervisor baseline (parent run `69932676-5b33...`) surfaced three bugs the R22 tests missed (they only `compile()`-checked, never `exec`-ed), plus one DX pitfall worth documenting. All four addressed before cut.

### Fixed (Round 23-A) — `fork plan --emit python` stub executability

Three bugs in the generated stub template, caught by real end-to-end use:

- Stub used `ref.run_id`, but `ForkRef` exposes `child_run_id` (plus `fork_id`, `node_ids`). Any real execution of the stub would `AttributeError` at the final print line. Now correctly uses `ref.child_run_id`.
- Final `print(...)` was placed *inside* the `with recorder.fork(...)` block, but `ForkRef` fields are populated on context-manager **exit** — so the print always fired before population and printed `None`. Print moved below the `with` block with a comment explaining the lifecycle.
- Example import/construction comments suggested `from chronos.store.sqlite import SqliteStore` + `SqliteStore("..."); store.open()`, neither of which is the public API. Corrected to `from chronos.store import SqliteStore` + `SqliteStore.open(path)` context-manager idiom.
- CLI `render_plan_preview` previously printed the same `consume in code with from chronos.fork_plan import load_plan` hint for both `--emit json` and `--emit python`. Now emit-aware: the python path tells users to fill the two `TODO(user)` blocks and `python <stub>`.

### Added (Round 23-C) — checkpointer-persistence warning in the stub

The stub's graph `TODO(user)` block now includes an `IMPORTANT:` note explaining that child runs only step through graph nodes if the parent and the fork share a persistent or cross-call-live LangGraph checkpointer. An `InMemorySaver` rebuilt per factory call registers the fork record but produces `node_ids=[]`. Note recommends `SqliteSaver.from_conn_string(...)` and points at the case study.

### Documentation (Round 23-B)

- New case study: `docs/case-studies/fork-via-emit-python.md` walks through the full use-in-anger path — generate → fill → run → inspect — with the three R22 bugs and the checkpointer-persistence pitfall explained in detail. Also revisits why ADR-008 / ADR-013 chose the stub-emission path over execute-fork automation.

### Tests

- `test_fork_plan.py` gained 4 regression tests (22 → 26): one actually `exec`s the stub with a mocked recorder + graph and asserts the print line reaches stdout with the correct value; three assert text-level invariants (correct imports, correct `ref` field, checkpointer warning present).
- `test_fork_cli.py` assertion for the stale "paste-ready Python stub written to" message replaced with the new preview-based hint check.
- Full suite: **264 / 264 pass, 93% coverage**, ruff/format/mypy all green.

### Evidence

End-to-end verified: `chronos fork plan 69932676-5b33... --emit python --out fork_stub.py --db dogfood.db` → fill 2 TODO blocks → `python fork_stub_filled.py` → new child run `16ca0fa5-cbec-418b-bd47-7a9546048b01` + fork `f6b36f40-82c3-45d8-9386-5b8a4e7b393c` land in the DB alongside the parent.

---

## [0.1.5] — 2026-04-23 (Round 21 + Round 22)

**Theme**: ADR-013 landed + ADR-013 deferred alt C shipped. After three rounds of dogfood weak-consistent evidence (R17/R18/R20), Chronos formally freezes `fork=JSON-only` (ADR-013), then ships the middle-ground path the evidence suggested: `chronos fork plan --emit python` generates a self-contained, pastable stub that inlines fork kwargs as Python literals. No execute-fork crossed.

### Added (Round 22) — `fork plan --emit python`
- New CLI option: `chronos fork plan <run_id> ... --emit python` writes a paste-ready Python stub (default `./fork_stub.py`, override with `--out`). Default `--emit json` unchanged.
- New public API: `ForkPlan.to_python(*, recorder_var="recorder", graph_var="graph") -> str` renders the plan as valid Python 3.11+ source. Callable from user code without going through the CLI.
- Stub includes: provenance docstring (parent_run_id, parent_node, chronos_version, generated_at); two `TODO(user)` markers for Recorder + graph construction; fork kwargs inlined as Python literals (no JSON file dependency at runtime); `graph.invoke(None, {"configurable": {"thread_id": ...}})` call sample; final `print(f"fork child run: {ref.run_id}")`.
- 10 new tests: 7 unit (valid Python, inlined kwargs, TODO markers, provenance, custom variable names, no-reason placeholder, trailing-newline contract) + 3 CLI (end-to-end stub file, default filename, invalid format error).
- Implements ADR-013 deferred alternative C: middle ground between raw JSON (too bare) and execute-fork (ADR-008 rejected, ADR-013 frozen).

### Added (Round 21) — `Node.model` convenience property
- New read-only property `Node.model` returns `self.model_name`. Shorter, canonical form. Prefer `node.model` in user code.
- Docstring cross-refs added to `Usage` class and `Node.usage` field, explicitly calling out that `model_name` is **not** a `Usage` field — it lives on `Node`. Addresses R20 Finding #2 (three independent dogfood scripts wrote `node.usage.model_name` and got `None`).
- 3 new tests guard the property + enforce the guardrail that `Usage.model_name` stays rejected (ADR-013 affirmation).

### Documentation (Round 21) — ADR-013 (fork auto-execution: stay frozen)
- ADR-013 formalizes the stop-thinking-about-it decision on execute-fork, based on R17+R18+R20 three-round weak-consistent dogfood evidence (zero execute-fork demand across supervisor / swarm / bigtool topologies).
- Affirms ADR-008 "fork=JSON-only" boundary; documents explicit trigger conditions for reopening.
- Third-party case study: `docs/case-studies/langgraph-bigtool.md` (R20 dogfood #3).

### Tests
- 250 → 260 (+10).
- Coverage: 93% (unchanged).
- `src/chronos/fork_plan.py` coverage: 99% (was 99%).

---

## [0.1.4] — 2026-04-23 (Round 17 + Round 18)

**Theme**: Real-world dogfood finds silent token undercount. Two consecutive rounds of using Chronos on real 1000+ ★ LangGraph ecosystem libraries (`langgraph-supervisor-py`, `langgraph-swarm-py`) surfaced bugs that 242 green unit tests had not caught. Numbers that looked valid were wrong by up to ~50%. Now fixed.

### Fixed (Round 18) — multi-LLM-per-node token accumulation (ADR-012)
- All three LangGraph usage extractors (`aimessage_usage_extractor`, `anthropic_usage_extractor`, `openai_usage_extractor`) previously used "last AIMessage wins" semantics, which silently under-counted tokens by 30-70% on graphs where a single super-step issues multiple LLM calls. Swarm-style graphs (`create_react_agent` sub-graphs embedded in a parent swarm) are the most common trigger.
- Concrete evidence: on `langgraph-swarm-py`, Bob-node usage was reported as `1222 prompt + 99 completion` when the true usage was `2275 + 211` (46% of prompt tokens, 53% of completion tokens silently dropped).
- **Fix**: extractors now diff `UsageContext.post_values["messages"]` against `UsageContext.pre_values["messages"]` and sum usage across **all** new `AIMessage` objects, not just the last one. `UsageContext.pre_values` was exposed in R15 (ADR-011) but had never been used — R18 makes it earn its keep.
- No public API change. No data-model change. Preserves all prior semantics (cache tokens fold into `prompt_tokens`; `reasoning_tokens` sub-field of `completion_tokens`; `None` for non-LLM nodes).
- ADR-012 — multi-LLM-per-node usage accumulation (extends ADR-009 contract without signature change).
- 5 regression tests added: swarm Bob-node scenario, pre-history protection, OpenAI path, non-LLM node `None` return, initial-step fallback.
- R17 supervisor dogfood re-run confirms no regression; `research_expert` now reports `1957+283` (was `1755+271` — a previously-unnoticed ~10% undercount in the old code path, also now accurate).
- Case study published: `docs/case-studies/langgraph-swarm.md`.

### Fixed (Round 17) — state serialization + JSON-to-pydantic coercion (ADR-011)
- First real-world dogfood target: `langgraph-supervisor-py`. Three showstopper bugs surfaced on the very first run, all of them invisible to the unit suite.
- `LangGraphRecorder` now recursively coerces pydantic models to `dict` before SQLite write-back (`TypeError: Object of type HumanMessage is not JSON serializable`). Extractors now accept both `AIMessage` pydantic objects and dict-coerced messages (ADR-011).
- Case study published: `docs/case-studies/langgraph-supervisor.md`.

### Numbers
- Tests: 236 → **247 pass** (+5 R17 regression, +6 R18 regression; 2 R18 tests renamed in-place since semantics changed from "last wins" to "sum all new"). Coverage **93%**. Ruff + format clean.
- Version bumped `0.1.3` → `0.1.4` in `src/chronos/__init__.py` and `pyproject.toml`.
- CLI status line updated: `"Phase 1 M1.11 — usage extractor hook + native Anthropic/OpenAI adapters + multi-LLM-per-node accumulation, v0.1.4"`.
- Git tag `v0.1.4` pushed to `origin` (private repo, gh-proxy.com mirror).

### Notes
- No schema changes. `UsageExtractor` Protocol signature from ADR-009 unchanged — R18 only extends the documented accumulation semantics.
- M1.11 milestone kept (R17 + R18 fix latent bugs in the same capability; not a new milestone).
- ADR-008 (execute-fork boundary): 2 consecutive dogfood rounds produced **zero** demand for auto-executing forked plans. Boundary stays frozen — evidence now based on real usage, not speculation.
- **Core lesson (now project DNA)**: N green unit tests + M showstopper bugs can coexist; unit tests do not replace dogfood. R18 re-validated this even *after* R17 had sharpened the tests.

---

## [0.1.3] — 2026-04-23 (Round 14 + Round 15 + Round 16)

**Theme**: Three-extractor family + Anthropic prompt caching fidelity. The `usage_extractor` hook shipped in v0.1.2 now has first-class convenience implementations for the two most common LLM SDKs alongside the LangChain-standard one — and the interior CLI was split up so further growth stays tractable.

### Added (Round 15) — native Anthropic / OpenAI usage extractors (ADR-010)
- `chronos.adapters.langgraph_usage.anthropic_usage_extractor` — reads `AIMessage.response_metadata["usage"]` (the shape Anthropic's SDK produces); folds `cache_creation_input_tokens` + `cache_read_input_tokens` into `prompt_tokens`. (Anthropic's API reports cache tokens **separately** from `input_tokens`; forgetting to sum them under-reports prompt usage by 10-100× when prompt caching is on.)
- `chronos.adapters.langgraph_usage.openai_usage_extractor` — reads `AIMessage.response_metadata["token_usage"]` (OpenAI Chat Completions shape); captures `completion_tokens_details.reasoning_tokens` as a sub-detail so `prompt_tokens + completion_tokens == total_tokens` stays invariant (o1 / o3 models).
- Both new extractors implement the existing `UsageExtractor` Protocol from ADR-009 — **zero** protocol change, pure additive feature. Cross-provider composition via the documented `anthropic or openai or aimessage` short-circuit pattern.
- Duck-typed: no hard dependency on the `anthropic` or `openai` SDK packages (users without them can still use the extractors).
- ADR-010 — native usage extractors design (chose sibling extractors over extending `aimessage_usage_extractor` / automatic cascade / hard-dep typed responses).
- 21 new unit tests: 8 anthropic + 7 openai + 3 composition pattern. Totals: **236/236 pass, 94% coverage**; `langgraph_usage.py` at 100%.
- Docs: `docs/getting-started.md` §4b rewritten with three-extractor family; `docs/cli-reference.md` token-usage section gets an extractor comparison table.

### Refactored (Round 14) — CLI file split
- `src/chronos/cli/__init__.py`: **848 → 348 lines (-59%)**, command groups split into sibling modules.
- New shared helpers: `cli/_common.py` (DB open + serialise + shared `console`) and `cli/_usage.py` (usage summary dataclass).
- Per-command impl modules: `cli/runs.py`, `cli/forks.py`, `cli/diff.py`; joining the already-split `cli/replay.py` and `cli/fork.py`. All expose `*_command(console, open_store_fn, ...)` with DI — pattern frozen for future commands.
- `__init__.py` now only does typer app registration + thin wrappers. **Zero** test changes required — the refactor is validated by the existing suite staying green.
- No new ADR (pure refactor). No version bump at the time (bundled into v0.1.3).

### Added (Round 16) — v0.1.3 release cut
- Version bumped `0.1.2` → `0.1.3` in `src/chronos/__init__.py` and `pyproject.toml`.
- CLI status line updated: `"Phase 1 M1.11 — usage extractor hook + native Anthropic/OpenAI adapters, v0.1.3"`.
- Git tag `v0.1.3` pushed to `origin` (private repo, gh-proxy.com mirror).
- No code changes this round — pure release packaging for R14 + R15 work.

### Notes
- No schema changes. `UsageExtractor` Protocol from ADR-009 unchanged — this release proves the protocol accommodates multiple implementations cleanly.
- M1.11 milestone kept (R15 is extension of the same capability, not a new milestone).

---

## [0.1.2] — 2026-04-23 (Round 12 + Round 13)

**Theme**: Token usage & cost visibility. The four-verb loop (record/replay/fork/diff) gains a sibling capability — **know what each run cost**.

### Added (Round 12) — M1.11 usage extractor hook + CLI token/cost surfaces
- `usage_extractor: UsageExtractor | None` kwarg on `LangGraphRecorder.__init__` — callable protocol `(UsageContext) -> UsageResult | None` invoked per node to populate the previously-dormant `Node.usage` and `Node.cost_usd_cents` schema fields (added in M1.1, zero references until now).
- New module `chronos.adapters.langgraph_usage` — `UsageContext` / `UsageResult` frozen dataclasses, `UsageExtractor` Protocol, plus `aimessage_usage_extractor` convenience implementation that reads LangChain `AIMessage.usage_metadata` / `response_metadata`.
- Failure tolerance: extractor raises are logged at WARNING and stored as `usage=None` — capture never breaks (tested).
- `chronos runs show <id>` — total-usage summary line + per-node inline token counts when data is present.
- `chronos runs list --with-usage` — opt-in flag adds `tokens` and `cost¢` columns (per-run SUM). Opt-in because it costs one extra node-fetch per row.
- `chronos diff A B --show-usage` — side-by-side A vs B vs Δ token/cost table, colorized (green = savings, red = regression). JSON mode gains a `usage` subtree with deltas.
- `_node_to_dict` (JSON output) always exposes `usage` and `cost_usd_cents` when populated — machine readers get it free.
- Examples updated: both `examples/linear_pipeline.py` and `examples/router_loop.py` wire a demo extractor and print `--with-usage` / `--show-usage` in their "Try these commands" block (dogfood auto-picks them up).
- ADR-009 — usage-extractor hook design (chose callable protocol over global callback / adapter subclass / middleware chain / runtime LLM-call interception).
- 21 new unit tests (`test_usage_extractor.py`): dataclass frozen semantics, `aimessage_usage_extractor` happy-path + edge cases, hook null/None/success/raise paths, CLI rendering. Totals: **216/216 pass, 94% coverage**.

### Notes
- No schema changes — pure fill of existing-but-unused fields, fully backward compatible (runs without an extractor keep recording identically).

### Added (Round 13) — v0.1.2 release cut
- Version bumped `0.1.1` → `0.1.2` in `src/chronos/__init__.py` and `pyproject.toml`.
- Git tag `v0.1.2` pushed to `origin` (private repo, gh-proxy.com mirror).
- No code changes this round — pure release packaging per R12 plan.

---

## [0.1.1] — 2026-04-23 (Round 10 + Round 11)

Phase 1 follow-up: the **record / replay / fork / diff four-verb loop** is now end-to-end in CLI (not just library). Shipped in two rounds:

### Added (Round 11) — M1.10 `chronos fork` CLI + fork plan artifact
- `chronos fork plan <run_id>` — emit a portable **fork plan** JSON artifact describing a proposed fork (parent run, fork-point node, overrides, child thread id, reason, tags). CLI never executes user code; plans are consumed via `chronos.fork_plan.load_plan()` in the user's script, which then calls `recorder.fork(graph, **plan.recorder_kwargs())`. Fork-point selectable via `--at-node <name>` (unique-name check), `--at-index <k>` (step index, always unambiguous), or `--at-node-id <uid>`.
- Override ergonomics: repeatable `--override k=v` (JSON-parsed first, falls back to raw string), `--override-json '{...}'` for bulk merges, `--allow-new-keys` to opt out of the default "reject unknown keys" typo guard.
- `--out <path>` (default `./fork_plan.json`) for file output with Rich preview; `--json` for stdout streaming (pipe-friendly).
- New `chronos.fork_plan` module: `ForkPlan` dataclass, `load_plan()`/`dump_plan()` helpers with schema version + `recorder_kwargs()` adapter that returns exactly the kwargs accepted by `LangGraphRecorder.fork()`. Deep-copies overrides to prevent plan mutation.
- ADR-008 — `chronos fork` CLI plan-artifact design (chose plan-file over inspection-only, over `--script` dynamic import).
- 55 new unit tests (`test_fork_plan.py` + `test_fork_cli.py`). Totals: **195/195 pass, 93% coverage**. Dogfood: **14/14 green** (2 new fork-plan commands auto-picked up from examples).

### Added (Round 10) — M1.7 replay TUI + dogfood CI
- `chronos replay <run_id>` — interactive step-through of any recorded run. Uses `rich.live` for the TUI; keyboard controls: `space`/`→` next, `←` prev, `home`/`end` jump, `q` quit. Falls back to static node-by-node rendering when stdin/stdout isn't a TTY (CI, pipes, `tee`). `--no-interactive` forces static mode.
- `scripts/dogfood.sh` — end-to-end dogfood: runs every `examples/*.py`, extracts the "Try these commands:" block, re-executes each suggested command, and scans for `chronos --db` docstring drift (the R9 bug class). Wired into GitHub Actions CI on Python 3.11.
- ADR-007 — replay TUI framework selection (`rich.live` chosen; `textual`, `prompt_toolkit`, `curses`, pager-only rejected with rationale).
- 26 new unit tests for the replay module (pure render + cursor logic + Typer CLI).

### Notes
- With M1.7 + M1.10 shipped, the record/replay/fork/diff "four-verb loop" is now end-to-end **in CLI** (not just library). Candidate tag: **v0.1.1**.

---

## [0.1.0] — 2026-04-23 (Round 9)

First tagged release. Phase 1 MVP complete: record → fork → diff across a LangGraph agent, all inspectable from the CLI.

### Added (Round 8/9) — M1.9 examples, docs, release polish
- `examples/linear_pipeline.py` — runnable LangGraph 5-node agent demoing record → fork → diff with a deterministic fake LLM (no API key required).
- `examples/router_loop.py` — runnable LangGraph agent with a conditional edge loop, demoing fork-forced early exit and how the diff aligner handles repeated node names.
- `examples/_fake_llm.py` — pure-function FakeLLM for deterministic demos.
- `docs/getting-started.md` — 5-minute onboarding walkthrough from install to `chronos diff`.
- `docs/cli-reference.md` — every CLI command, flag, exit code, and environment variable documented.
- Rewrite of `README.md` with real install instructions, quickstart, current milestone table, and development commands.
- `.gitignore` now excludes `examples/chronos.db` and `*.db-journal` so demo DB churn isn't committed.

### Fixed (Round 9)
- Docstring drift: `chronos --db X cmd` → `chronos cmd --db X` in three example docstrings (R8 missed these; dogfood script in R10 now catches this class of bug).

---

## [0.0.x] — Internal pre-release (Rounds 1–7)

### Added (Round 7) — M1.8 structural diff
- `chronos.core.diff` module (`DiffEntry`, `DiffReport`, `align_nodes`, `diff_runs`).
- `chronos diff <run_a> <run_b>` CLI command with `--json`, `--verbose`, `--full`, and fork-aware default slicing.
- ADR-006 — diff alignment algorithm (`difflib.SequenceMatcher` over `node_name` sequence) + frozen JSON schema.
- 30 new tests (21 diff unit + 9 CLI integration). Total: 112/112 pass, 92% coverage.

### Added (Round 6) — M1.6 CLI read-side
- `chronos runs list` / `chronos runs show` / `chronos forks show` with rich tables and `--json` machine-readable output.
- `CHRONOS_DB` env var for default DB path.

### Added (Round 5) — M1.5 fork primitive
- `LangGraphRecorder.fork(...)` context manager — seeded child thread via `graph.update_state(as_node=...)`, parent→child lineage recorded in `forks` table and cross-run `parent_node_id`.
- ADR-005 — fork semantics.

### Added (Round 4) — M1.4 LangGraph adapter
- `chronos.adapters.langgraph.LangGraphRecorder` — checkpointer-based state capture via `graph.get_state_history()` on context-manager exit.
- ADR-004 — snapshot → node mapping algorithm.

### Added (Round 3) — M1.3 SQLite canonical store
- Pydantic models for `Run`, `Node`, `Fork`, `Tag`.
- SQLite schema (`chronos.store.sqlite`) with upsert semantics for Runs/Nodes, append-only for Forks.
- ADR-003 — canonical event schema; ADR-002 — trace schema versioning.

### Added (Round 2) — M1.2 scaffolding
- `pyproject.toml` + `uv`-based dev environment.
- Ruff + pytest + mypy wired; GitHub Actions CI.

### Added (Round 1) — Phase 0 research
- Competitor landscape (20+ tools across 4 tiers).
- Feasibility research (determinism, checkpoint capture, diff semantics, multi-framework risk).
- Architecture doc, user stories, risk register.
- ADR-001 — Python chosen over TypeScript for Phase 1 (LangGraph alignment, Pydantic ecosystem).
