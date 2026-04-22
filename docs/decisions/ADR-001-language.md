# ADR-001 — Implementation Language Selection

**Status**: Accepted
**Date**: 2026-04-22 (Round 1)
**Decider**: Hermes Agent

---

## Context

`chronos-agent` needs to pick an implementation language for its core. The choice affects:
- Which frameworks we can adapt to (ecosystem fit)
- CLI and Web UI packaging
- Contributor pool (AI agents and human contributors)
- Distribution complexity

The principal consumers of chronos-agent are **developers and AI agents building multi-agent systems**. Most production agent frameworks live in **Python** (AutoGen, CrewAI, LangGraph Python) and **TypeScript/JavaScript** (Vercel AI SDK, LangGraph.js, Mastra).

The architecture has multiple components with different performance profiles:
- **Adapter layer**: must live in the framework's own language (can't adapt Python LangGraph from a Go process easily)
- **Core (trace store, diff, fork orchestrator)**: performance-ish but not latency-critical
- **CLI**: user-facing, must install easily
- **Web UI**: always JS/TS (browser-side)

---

## Options Considered

### Option A — Python-first, TypeScript adapter later

- **Pros**:
  - Matches the **majority of agent frameworks** (AutoGen, CrewAI, LangGraph-Py)
  - Large AI/ML developer community
  - Rich ecosystem: SQLAlchemy, Typer, rich, pandas (for trace analysis)
  - Hermes Agent is fluent with Python
- **Cons**:
  - CLI distribution friction (pyinstaller / pipx; not single-binary by default)
  - Python startup time affects CLI snappiness (0.3–0.5s)
  - No native TypeScript adapter → need second codebase for JS frameworks
- **Evidence**: 70–80% of agent framework ecosystem is Python-first

### Option B — TypeScript-first, Python adapter later

- **Pros**:
  - Unified code across CLI + Web UI (same codebase)
  - Better long-term for Web UI
  - Faster CLI startup (Node.js or Bun)
  - TypeScript typing discipline
- **Cons**:
  - Python framework adapters would need a separate Python package / IPC bridge
  - Smaller AI-framework community in TS (though growing)
  - Hermes Agent can do TS but Python is more comfortable for analytical code
- **Evidence**: LangGraph.js, Mastra, Vercel AI SDK gaining momentum but still smaller

### Option C — Go core + per-language adapters

- **Pros**:
  - Single static binary — cleanest distribution (`brew install chronos`)
  - Fast, low-memory core
  - Good concurrency for fork orchestration
- **Cons**:
  - **Adapters still need to live in Python / TS** — so need IPC (stdio JSON-RPC or named pipes)
  - Go ecosystem has fewer AI-native libs
  - Hermes Agent slower in Go than Python
  - Web UI is still separate codebase
- **Evidence**: Excellent fit for "infra tool" DNA (e.g., Terraform, kubectl); less excellent for "integrates with LLM SDK" DNA

### Option D — Rust core + per-language adapters

- **Pros**:
  - Single binary, best performance
  - Growing adoption in dev-tool space (ruff, uv, biome)
  - Memory safety
- **Cons**:
  - Same IPC issue as Go
  - Steep learning curve for contributors
  - Hermes Agent weaker in Rust
  - Development velocity significantly lower — this project must iterate fast
- **Evidence**: Prestige language but risky for a research-phase tool

### Option E — Polyglot from day one: Python adapter + Python CLI + optional Rust/Go core later

- Start with Option A; **don't rule out** migrating hot paths to Rust/Go if needed
- Ship v0.1 in Python; measure; only then reconsider
- This is essentially Option A with a "portability escape hatch" mindset

---

## Decision

**Option E — Python-first (effectively Option A), with principled escape hatches.**

More precisely:

1. **Core + first adapter + CLI in Python** (3.11+)
2. **Web UI in TypeScript/React** (Next.js or Vite + React; decided in ADR-004)
3. Adapter interface is language-agnostic (canonical event schema); allows a TypeScript adapter later with its own SDK
4. Database layer (SQLite) accessed via Python, but **SQLite is language-agnostic** — future non-Python consumers could read directly
5. Keep core logic **free of Python-specific state formats** — use JSON everywhere so future port to Go/Rust is a translation, not a redesign

### Tiebreakers (why not B, C, D)

- **Why not B (TS-first)**: LangGraph Python has the strongest state-capture story and is our v0.1 first adapter. Having core in the same process as a Python adapter avoids cross-process state serialization for the hardest capability (fork).
- **Why not C/D (Go/Rust)**: Distribution advantage does not outweigh the velocity loss in an early-stage research-mode project. We can always statically compile a fast core later.
- **Why not strict A**: Explicit "we'll consider migrating hot paths" keeps us honest about Python performance limitations.

---

## Consequences

### Easier
- Fast prototyping of adapter + core + CLI
- Direct access to LangGraph's Python checkpointer for v0.1
- Rich data analysis for diff engine (numpy/pandas if needed)
- AI-agent contributors (including Hermes Agent) highly productive in Python

### Harder
- Single-binary distribution (we'll use `pipx` or `uv tool install chronos` for now)
- CLI startup overhead (~300ms) — acceptable for dev tool, not for CI-critical path
- Future TS adapter needs its own SDK package
- Heavy concurrency in fork orchestration will need careful asyncio / multiprocessing design

### Opens up
- Plugin API in Python for custom diff / redaction functions
- Easy Jupyter notebook integration (`chronos.load(run_id)` in a notebook)

### Closes off (for now)
- Bundling as a single compiled binary
- Use as a shared library by non-Python hosts (until we expose a proper gRPC/HTTP API)

---

## Revisit Triggers

Reopen this ADR if:
- CLI startup >1s or causes user complaints
- Fork orchestration can't hit its latency targets (Q4 of feasibility.md) in Python
- A major framework arrives that's TS-only AND becomes the dominant v0.3+ target
- Distribution friction (installation failures) becomes a top-3 user complaint

---

## Implementation Implications

- Package manager: **`uv`** (fast, modern, and it's what the dev env has)
- Package layout: `src/chronos/` with `core`, `adapters`, `cli`, `api`, `store`
- Python version: **3.11+** (good async support, assertion performance)
- Test runner: **`pytest`**
- Formatter / linter: **`ruff`** (includes format + lint)
- Type checker: **`mypy`** or **`pyright`** (decided in ADR-002)
- CLI framework: **`typer`** (typed, click-based, great DX)
- HTTP API: **`FastAPI`** (if we go API-first) or **`starlette`** (lighter)
- SQLite access: **stdlib `sqlite3`** + `pydantic` for schema validation — avoid heavy ORM

Dependencies (initial best-guess for Phase 1):
```
python >=3.11
typer >=0.12
pydantic >=2.7
fastapi >=0.110  # if we build API early
uvicorn >=0.29   # for API server
sqlite-utils >=3.36  # for nice SQL helpers
rich >=13.7      # CLI pretty printing
langgraph >=0.2  # for first adapter
```

---

## References

- Feasibility study: `docs/research/feasibility.md` (Q3 on cross-framework)
- LangGraph Python checkpointer docs: https://langchain-ai.github.io/langgraph/concepts/persistence/
- `uv` package manager: https://github.com/astral-sh/uv
- Typer CLI framework: https://typer.tiangolo.com/
