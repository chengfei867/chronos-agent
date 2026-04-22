# Technical Feasibility Study

**Last updated**: 2026-04-22 (Round 1)
**Status**: Initial — assumptions to be verified with PoC in later rounds

> Purpose: Before committing to a language, architecture, or framework priority, prove (or falsify) the hardest technical bets of `chronos-agent`.

---

## The Four Hard Questions

1. **Can we capture agent state with enough fidelity to meaningfully fork?**
2. **Can we re-execute a fork deterministically enough for diffs to be meaningful?**
3. **Can we do this across multiple agent frameworks (not just one)?**
4. **Can we scale to reasoning trees with 100s of nodes without breaking UX?**

Each question is tackled below.

---

## Q1. State Capture Fidelity

### What needs to be captured per node?

| Layer | What | How to capture |
|---|---|---|
| **LLM call** | model, system prompt, messages[], tools[], temperature, seed, response, reasoning tokens, usage | Intercept at LLM SDK boundary |
| **Tool call** | tool name, arguments, return value, side-effects hint | Intercept at tool dispatch |
| **Agent state** | scratchpad, memory, local vars relevant to reasoning | Framework-specific hooks |
| **Time/resource** | timestamp, latency, cost | Derived |
| **Graph edge** | what node triggered this node | Framework-specific or OTel parent span |

### What's the standard landscape (2026)?

- **OpenTelemetry GenAI Semantic Conventions** (GA as of mid-2025): defines `gen_ai.*` attributes for LLM calls — request model, messages, usage, response. Widely adopted.
- **OpenTelemetry Agent Semantic Conventions** (experimental through 2025-26): extending to cover agent loops, tool calls, multi-step workflows. Not yet stable but direction is clear.
- **MCP (Model Context Protocol)** (stabilized late 2024): standardized tool call schema. Agents using MCP expose a clean interception point at the protocol level.

**Feasibility verdict**: **Capture is solved for LLM calls and MCP-based tool calls**. The remaining gap is **agent-internal state** (what's in scratchpad? what does the plan look like?) which is framework-specific.

### Framework-specific hooks survey

| Framework | State capture story |
|---|---|
| **LangChain/LangGraph** | `callbacks` + `LangGraph checkpointer` — BEST native support. Checkpointer literally serializes/deserializes state. |
| **AutoGen** (Microsoft) | `event handlers` + message history — capturable but no built-in snapshot |
| **CrewAI** | `callbacks` — basic tracing only |
| **Vercel AI SDK** | middleware pattern — interceptable |
| **OpenAI Agents SDK / Assistants API** | OpenAI-hosted state — we can only capture what we send/receive, not "agent internal state" |
| **Anthropic Claude Agent SDK** | similar to OpenAI — hosted state is opaque |
| **Custom / no framework** | pure instrumentation — user must annotate |

**Implication**: v0.1 should target **one framework with strong state semantics**. LangGraph is the obvious first choice (its checkpointer does half the work). Second framework could be AutoGen.

### What about closed-agent-SDK state (OpenAI/Anthropic hosted agents)?

These expose only I/O. Can still do R1/R2/R4 but R3 (fork) degrades to "rerun from scratch with modified input" — acceptable for v0.1 as a known limitation.

---

## Q2. Replay / Re-execution Determinism

### The naïve assumption

"Record LLM response X at step N; on replay just play back X." — This works for pure replay (R2).

### The fork challenge

Fork says "change prompt at step 5 to X'; re-run downstream steps 6, 7, 8". But step 6 calls the LLM. How do we re-run it?

### Options

**A. Recall mode (replay exactly, no fork possible past edit point)**
   - For the edited node and everything downstream: **call LLM fresh**
   - Problem: non-determinism even at temperature=0 (numerical drift, model updates, tool output changes)

**B. Seed + temp=0 + pinned model**
   - Use `seed` parameter (supported by OpenAI/Anthropic) + temp=0 + snapshot model version
   - Gives "best-effort determinism" for identical inputs
   - **For forked nodes (modified input), determinism isn't the goal** — we just want a stable comparison run

**C. Hybrid "fresh downstream"**
   - Pre-fork steps: replay recorded outputs
   - Post-fork steps: execute fresh, record new trace, flag as "live" vs. "replayed"

### Best approach for chronos-agent

**Use Option C (hybrid).** Practically:
- Everything upstream of fork point uses recorded data
- Everything downstream is freshly executed with (a) snapshot model + (b) seed + (c) temp=0 for "stability mode", OR (d) natural temperature for "exploration mode"
- The UX is: `agent-fork --mode=stable` vs. `--mode=explore`

### Tool call re-execution gotcha

When we re-run a tool call in a fork, side effects might happen twice (e.g., "send email" tool). We need:

1. **Dry-run mode**: tools declared as `side-effectful` return cached result or stub during replay
2. **Side-effect registry**: user declares which tools are pure vs. effectful
3. **Sandbox mode**: run forks in isolated sandbox (E2B / Modal)

**Decision**: v0.1 starts with **conservative default — side-effectful tools return cached on fork unless user opts in**. ADR-003 (future) will formalize.

---

## Q3. Cross-Framework Support

### The adapter pattern

```
┌────────────────────────────────────┐
│   Framework Adapter (per fw)       │
│   - wrap framework's trace API     │
│   - emit canonical chronos events  │
│   - expose snapshot/restore        │
└──────────────┬─────────────────────┘
               ↓  canonical format
┌──────────────────────────────────┐
│   chronos-core                   │
│   - store trace                   │
│   - compute diffs                 │
│   - orchestrate forks             │
└──────────────────────────────────┘
```

### Canonical event format (draft)

```jsonc
{
  "run_id": "run_abc123",
  "node_id": "node_005",
  "parent_node_id": "node_004",
  "kind": "llm_call" | "tool_call" | "agent_state" | "error",
  "ts": "2026-04-22T10:00:00Z",
  "framework": "langgraph",
  "payload": { /* kind-specific */ },
  "usage": { "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.002 },
  "fingerprint": "sha256(...)" // for dedup / comparison
}
```

This mirrors OTel GenAI + adds `fingerprint` (for diff) and `run_id/node_id/parent_node_id` (for tree reconstruction).

### Adapter priority for v0.1 → v0.2

1. **v0.1**: LangGraph (best state support)
2. **v0.1.5**: Generic OTel GenAI receiver (ingest any OTel-instrumented agent, but without fork — read-only R1+R2+R4)
3. **v0.2**: AutoGen (second real adapter with state)
4. **v0.3**: Add MCP-level adapter (works across any MCP-using agent, partial support)

### Interop strategy

**Do not fight the standards**. Build on top of:
- OTel GenAI semconv for trace schema (extend, don't replace)
- MCP for tool call semantics
- OpenInference conventions where they apply

**Feasibility verdict**: Adapter pattern is standard engineering. Hard part is **state extraction API** per framework, which varies. Plan 2-3 weeks per adapter.

---

## Q4. Scale — How big can reasoning trees get?

### Realistic sizes

- Simple ReAct agent: 5-20 nodes per run
- Deep research agent (Perplexity Deep Research, Claude Research): 50-200 nodes
- Multi-agent orchestration (CrewAI with 5 agents × 10 steps each): 50-500 nodes
- Autonomous coding agent (Devin-like, many subgoals): 500-5000 nodes

### Storage

Each node: ~1-5 KB typical (more if messages are long). Worst case: 500 × 10KB = 5MB per run.

For local-first storage:
- **SQLite** handles 5MB trivially, can scale to millions of rows
- **DuckDB** — if analytical queries (diff, aggregation) matter, this is a better fit
- **LanceDB** — vector + metadata, useful if we want semantic search in trace

**Decision**: Start with **SQLite** for v0.1 (zero-config, universal). Later possibly migrate to DuckDB or offer both.

### UI rendering

- 500-node tree renders fine with virtualization (any modern tree library)
- 5000-node tree needs progressive disclosure / lazy loading
- For v0.1 targeting small-to-medium agents, no scale issue

### Fork re-execution cost

- 100 LLM calls × $0.01 per call = $1 per fork (reasonable)
- 5000 LLM calls × $0.01 = $50 per fork (expensive; need "partial fork" = only re-run affected subtree)
- **Must implement "dependency-aware fork"**: only re-execute nodes whose inputs changed due to the fork edit

**Feasibility verdict**: Manageable with right storage + lazy UI + partial fork. Not a PoC-stage concern.

---

## Supporting Technology Stack Survey

### Trace DB / Storage
- **SQLite** — universal, zero-config ✅ v0.1 choice
- **DuckDB** — columnar analytics on traces ⚠️ evaluate for v0.2
- **PostgreSQL** — if we go server-mode ⚠️ v0.3+
- **Parquet files** — for export / archive

### OTel Integration
- **opentelemetry-instrumentation-*** (Python) and `@opentelemetry/*` (JS) — production-ready
- OTel Collector as optional receiver if users want centralized ingest

### CLI
- **Typer** (Python) or **Commander** / **oclif** (TS) — mature
- **Ratatui** (Rust) or **Bubble Tea** (Go) — for rich TUI if we go that way

### Web UI
- **Next.js + React + Tailwind + shadcn/ui** — industry default, fast to ship
- **SvelteKit** — lighter, less mindshare
- **Reagraph / Cytoscape.js / ReactFlow** — for tree visualization

### Diff Engine
- **jsondiffpatch** (JS) / **deepdiff** (Python) — structural JSON diff exists
- Custom LLM-semantic diff (different embeddings, different intents) — novel component, v0.2+

### Snapshot / Sandbox
- **Docker**, **E2B**, **Modal**, **Daytona** — multiple options for sandboxing fork re-execution
- v0.1 punts on sandboxing (user's own runtime)

---

## Experimental PoC Plan (for Phase 0 closeout / Phase 1 entry)

Before writing any v0.1 code, validate these three bets with minimum spikes:

### Spike 1: LangGraph state capture & replay (1-2 hours)
- Write a 5-node LangGraph agent
- Hook checkpointer to persist state
- Restore and re-run from a mid-node checkpoint
- ✅ If this works smoothly, R1+R2 for LangGraph are proven

### Spike 2: Fork with modified prompt (2-3 hours)
- Take Spike 1's checkpoint
- Modify the system prompt for node-3
- Restore from node-2's state, continue with modified prompt for node-3, re-execute through end
- Compare final output
- ✅ If this works, R3 is proven for LangGraph

### Spike 3: Structured diff of two runs (2-3 hours)
- Take two runs of the same agent (original + forked)
- Compute per-node diff (prompt text diff, tool arg diff, LLM response diff, cost delta)
- ✅ If this renders meaningfully, R4 is proven

**Total spike budget: 1 day.** Do this in Phase 0 → Phase 1 transition round.

---

## Conclusion — Feasibility Verdict

| Question | Verdict | Confidence |
|---|---|---|
| Q1. State capture | **Feasible** for LangGraph/AutoGen; **limited** for hosted agents | High |
| Q2. Re-execution | **Feasible** with hybrid replay + fresh-downstream; side-effects need care | Medium-High |
| Q3. Cross-framework | **Feasible** via adapter pattern; 2-3 weeks per adapter | High |
| Q4. Scale | **Feasible** for typical runs; partial-fork needed for very large agents | High |

**Bottom line: The core technical bet is viable. Hardest work is (a) the fork semantics for edge cases (side-effectful tools) and (b) the cross-framework state abstraction. Both are engineering problems, not research problems.**

---

## Open Technical Questions for Next Rounds

1. [ ] How do we handle **streaming LLM responses** in replay? (Record full response vs. record deltas?)
2. [ ] How do we handle **tool outputs that include timestamps / random IDs** in diff? (Diff normalizer needed)
3. [ ] How do we handle **async / parallel agent calls** in the tree representation?
4. [ ] Should chronos-agent's trace format be **strict OTel compliance** or **OTel-compatible but extended**?
5. [ ] For the UI, do we build **web-first** or **TUI-first**? (TUI fits the AI-dev audience better and ships faster)
6. [ ] **Storage backend**: SQLite universally, or offer pluggable (SQLite / DuckDB / Postgres)?
7. [ ] **Deterministic mode**: do we enforce model pinning + seed, or just recommend?

---

*Document owner: Hermes Agent. Next review: Round 2 cron cycle.*
