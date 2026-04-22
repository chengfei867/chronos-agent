# Architecture Design

**Last updated**: 2026-04-22 (Round 1)
**Status**: Initial architecture — subject to revision after Phase 1 PoC

---

## Design Philosophy

1. **Local-first** — everything runs on the user's machine; no required cloud
2. **Framework-agnostic core** — adapters isolate framework specifics
3. **Schema-first** — canonical event format is the contract
4. **Standards-compatible** — build on OpenTelemetry GenAI semconv and MCP
5. **Progressive disclosure** — CLI before Web UI; SQLite before distributed storage; one framework before many

---

## System Overview (Level-0)

```mermaid
flowchart LR
    Agent["User's Agent Program<br/>(any framework)"] -->|runtime hooks| Adapter["Framework Adapter"]
    Adapter -->|canonical events| Core["Chronos Core<br/>(trace store + fork engine)"]
    Core --> SQLite[("SQLite<br/>trace DB")]
    Core <-->|query/mutate| CLI["Chronos CLI"]
    Core <-->|query/mutate| Web["Web UI<br/>(local)"]
    CLI --> User["User / AI Dev"]
    Web --> User
```

---

## Layered Architecture (Level-1)

```mermaid
flowchart TB
    subgraph L1["Layer 1: Agent Code"]
        Agent["User agent code<br/>(LangGraph / AutoGen / custom)"]
    end

    subgraph L2["Layer 2: Instrumentation"]
        Hook["Framework Adapter<br/>- capture LLM calls<br/>- capture tool calls<br/>- capture state snapshots"]
        OTel["OTel GenAI<br/>(opt-in generic)"]
    end

    subgraph L3["Layer 3: Core Services"]
        Ingest["Ingest Pipeline<br/>(normalize to canonical)"]
        Store["Trace Store<br/>(SQLite)"]
        Tree["Tree Builder<br/>(reconstruct reasoning tree)"]
        Diff["Diff Engine<br/>(structural + semantic)"]
        Fork["Fork Orchestrator<br/>(replay + re-execute)"]
    end

    subgraph L4["Layer 4: Interfaces"]
        CLI["CLI<br/>(record / list / inspect / diff / fork)"]
        API["Local HTTP API<br/>(JSON-RPC or REST)"]
        WebUI["Web UI<br/>(tree viewer / diff viewer)"]
    end

    subgraph L5["Layer 5: Users"]
        Human["Human developer"]
        AI["AI agent<br/>(dogfood)"]
    end

    Agent --> Hook
    Agent -.OTel.-> OTel
    Hook --> Ingest
    OTel --> Ingest
    Ingest --> Store
    Store --> Tree
    Tree --> Diff
    Tree --> Fork
    Fork -->|re-execute| Agent

    Store --> API
    Tree --> API
    Diff --> API
    Fork --> API

    API --> CLI
    API --> WebUI
    CLI --> Human
    CLI --> AI
    WebUI --> Human
```

---

## Data Model (Canonical)

### Core entities

```mermaid
erDiagram
    RUN ||--o{ NODE : contains
    RUN {
        string run_id PK
        string name
        timestamp started_at
        timestamp ended_at
        string framework
        string agent_signature
        json metadata
        string status
        float cost_usd
        int total_tokens
    }
    NODE ||--o{ NODE : parents
    NODE {
        string node_id PK
        string run_id FK
        string parent_node_id FK
        int step_index
        string kind "llm_call|tool_call|agent_state|error|branch"
        timestamp ts
        int duration_ms
        json payload
        json usage
        string fingerprint "SHA256 of payload"
    }
    RUN ||--o{ FORK : branched_by
    FORK {
        string fork_id PK
        string source_run_id FK
        string source_node_id FK
        string forked_run_id FK
        json edits
        string strategy "stable|explore"
        timestamp created_at
    }
    RUN ||--o{ TAG : tagged_by
    TAG {
        string run_id FK
        string tag
    }
```

### Node `kind` variants

| `kind` | `payload` schema |
|---|---|
| `llm_call` | `{model, system, messages[], tools[], temperature, seed, response_message, finish_reason}` |
| `tool_call` | `{tool_name, args, result, error?}` |
| `agent_state` | `{framework, state_blob (serialized), schema_version}` |
| `error` | `{exception_type, message, traceback}` |
| `branch` | `{condition, chosen, alternatives[]}` (for explicit agent decisions) |

### Reasoning tree reconstruction

Given rows in `NODE`:
- Build DAG from `parent_node_id`
- Multi-agent: multiple roots under the same `run_id` = parallel actors
- Sub-tree = sub-agent call

---

## Component Deep Dives

### C1. Framework Adapter (per-framework)

**Responsibilities**:
- Subscribe to framework events (callbacks / middleware)
- Capture LLM call I/O, tool call I/O, agent state checkpoints
- Emit canonical events to Core Ingest

**Interface** (per adapter, language-agnostic):
```
start_recording(run_name, metadata) → run_id
emit_event(run_id, event: CanonicalEvent)
end_recording(run_id, status)
```

**Spot the variation per framework**:

| Framework | Hook mechanism | State capture API |
|---|---|---|
| LangGraph | `with_config(callbacks=[ChronosCallback()])` | `graph.get_state(config)` via checkpointer |
| AutoGen | `@agent.event_handler` | custom message_history serialization |
| Generic OTel | OTel GenAI receiver | none (R1+R2+R4 only, no R3) |

### C2. Ingest Pipeline

**Pipeline**:
```
raw_event → validate schema → normalize (tokens, cost) → dedupe by fingerprint → persist to SQLite
```

Fingerprint allows dedup across identical retries and stable references across forks.

### C3. Trace Store (SQLite)

**Schema** (simplified):
```sql
CREATE TABLE runs (
  run_id        TEXT PRIMARY KEY,
  name          TEXT,
  started_at    INTEGER,
  ended_at      INTEGER,
  framework     TEXT,
  status        TEXT,
  cost_usd      REAL,
  total_tokens  INTEGER,
  metadata      JSON
);

CREATE TABLE nodes (
  node_id          TEXT PRIMARY KEY,
  run_id           TEXT REFERENCES runs(run_id),
  parent_node_id   TEXT REFERENCES nodes(node_id),
  step_index       INTEGER,
  kind             TEXT,
  ts               INTEGER,
  duration_ms      INTEGER,
  payload          JSON,
  usage            JSON,
  fingerprint      TEXT
);

CREATE INDEX nodes_run ON nodes(run_id, step_index);
CREATE INDEX nodes_parent ON nodes(parent_node_id);
CREATE INDEX nodes_fingerprint ON nodes(fingerprint);

CREATE TABLE forks (
  fork_id         TEXT PRIMARY KEY,
  source_run_id   TEXT REFERENCES runs(run_id),
  source_node_id  TEXT REFERENCES nodes(node_id),
  forked_run_id   TEXT REFERENCES runs(run_id),
  edits           JSON,
  strategy        TEXT,
  created_at      INTEGER
);

CREATE TABLE tags (
  run_id   TEXT REFERENCES runs(run_id),
  tag      TEXT,
  PRIMARY KEY (run_id, tag)
);
```

### C4. Tree Builder

In-memory reconstruction of reasoning tree from flat rows. Cached per-run with invalidation on mutation.

### C5. Diff Engine

**Two levels of diff**:

1. **Structural**: compare node-by-node using fingerprint equality, position alignment, type match
2. **Semantic**: for text payloads (prompts, responses), use:
   - Text diff (word-level)
   - Optional: LLM-as-judge for intent-level diff ("are these two responses saying the same thing?")

**Alignment algorithm** (when trees diverge in shape):
- Anchor on shared ancestry up to fork point
- After fork, align by step_index within same agent lane
- Unmatched nodes marked as "only in A" / "only in B"

### C6. Fork Orchestrator

**Algorithm**:
```
fork(source_run, source_node, edits, strategy):
  new_run_id = generate_id()
  copy nodes from source_run up to source_node (with new run_id, preserving step_index)
  apply edits to source_node's payload → emit as first new node
  replay_context = restore agent state at source_node's parent
  re-execute agent from source_node using replay_context
    for each step:
      if strategy == 'stable': use seed, pinned model, temp=0
      if strategy == 'explore': use user-default LLM params
    emit new events → Ingest
  mark fork row
  return new_run_id
```

**Side-effect handling** (see feasibility doc R-T for details):
- Default: tools with `side_effect_level >= "effectful"` return cached result from source_run
- Override: `--re-execute-tools=<list>` to force re-execution
- Future: sandboxed re-execution via E2B/Modal

### C7. CLI

Entry point for most interactions. Commands map to API calls over Local HTTP API or direct in-process if running bundled.

### C8. Local HTTP API

Decouples CLI/Web UI from core. JSON-RPC over HTTP:
- `chronos.run.list`
- `chronos.run.get`
- `chronos.run.tree`
- `chronos.diff.compute`
- `chronos.fork.create`
- `chronos.fork.status` (for streaming progress)

Local by default (bind 127.0.0.1:<port>), not exposed externally.

### C9. Web UI

Rendered as local static bundle, talks to API at localhost. Uses ReactFlow / Cytoscape.js for tree rendering. Deferred to v0.2+ — CLI first.

---

## Sequence Diagrams

### S1. Recording a run

```mermaid
sequenceDiagram
    participant User
    participant CLI as chronos CLI
    participant Agent as User Agent
    participant Adapter as Framework Adapter
    participant Core as Chronos Core
    participant DB as SQLite

    User->>CLI: chronos record -- python agent.py
    CLI->>Agent: exec child process, inject adapter
    Agent->>Adapter: import + register hooks
    Adapter->>Core: start_recording() → run_id

    loop for each agent step
        Agent->>Adapter: LLM call / tool call
        Adapter->>Core: emit_event(llm_call, payload)
        Core->>DB: INSERT node
    end

    Agent->>Adapter: end
    Adapter->>Core: end_recording()
    Core->>DB: UPDATE run status
    Core-->>CLI: run_id, summary
    CLI-->>User: print summary
```

### S2. Forking a run

```mermaid
sequenceDiagram
    participant User
    participant CLI as chronos CLI
    participant Core as Chronos Core
    participant DB as SQLite
    participant Agent as Agent (re-exec)

    User->>CLI: chronos fork <run> --at <node> --set-prompt X
    CLI->>Core: fork_request(run, node, edits)
    Core->>DB: SELECT nodes up to <node>
    DB-->>Core: nodes[]
    Core->>DB: INSERT new run + cloned nodes
    Core->>Agent: restore state, re-exec from <node> with edits

    loop for each new step
        Agent->>Core: emit_event
        Core->>DB: INSERT node
    end

    Core-->>CLI: forked run_id, summary
    CLI->>User: print summary + suggest diff
```

### S3. Diffing two runs

```mermaid
sequenceDiagram
    participant User
    participant CLI
    participant Core
    participant DB

    User->>CLI: chronos diff run_A run_B
    CLI->>Core: diff_compute(A, B)
    Core->>DB: load trees for A and B
    Core->>Core: align trees, compute structural diff
    Core->>Core: optionally LLM-semantic diff for divergent nodes
    Core-->>CLI: diff result (json)
    CLI-->>User: render pretty diff
```

---

## Deployment Topologies

### T1. Local-only (v0.1 default)
Everything runs on one machine. SQLite file in `~/.chronos/`. CLI invokes bundled core.

### T2. Local + LAN sharing (v0.2 nice-to-have)
CLI can bind API to LAN port; teammates can view each other's traces read-only.

### T3. Cloud-hosted (v1.0+ possible future)
Optional trace upload to hosted chronos cloud. Out of scope for Phase 0–3.

---

## Security Model

- Trace DB is **local-only by default**; filesystem permissions protect it
- LLM API keys are **never stored by chronos**; user provides via environment as always
- **Redaction hooks** — users can register regex / function to scrub PII before storage
- Fork re-execution uses user's own API keys
- No network calls from chronos core except to user-configured LLM provider during fork re-execution

---

## Extension Points (designed-for-future)

1. **Custom diff plugins** — users can register domain-specific diff functions (e.g., "for my RAG app, diff retrieved docs by semantic similarity not text")
2. **Custom adapters** — adapter interface is public; any framework can be added
3. **Trace exporters** — Parquet, OTLP, JSON Lines
4. **Pre-fork hooks** — user code runs before fork (to mutate sandbox env, etc.)

---

## Open Architecture Questions

1. [ ] Should the core be a library (embedded in CLI) or a daemon (shared across CLI / Web)?
2. [ ] Should we ship a single binary (Go/Rust build) or a package (Python/TS install)?
3. [ ] How to handle very long-running agents (>1h) — streaming ingest vs. batch?
4. [ ] Web UI framework: Next.js (heavy but popular) vs. Vite+React (light) vs. Svelte?
5. [ ] Should diff UI support 3-way diff (base, A, B) like git mergetool?

---

*Document owner: Hermes Agent. Major architecture changes require an ADR.*
