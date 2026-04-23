# ADR-015: Extractor Contract v2 — Framework-Agnostic Consolidation

- **Status:** Accepted
- **Date:** 2026-04-23
- **Round:** R25
- **Consolidates:** ADR-009 (hook), ADR-010 (native extractors),
  ADR-011 (serialization boundary), ADR-012 (multi-LLM-per-node)
- **Related:** ADR-014 (Phase 2 entry criteria, R2), ADR-003 (schema)
- **Supersedes:** — (ADR-009/010/011/012 remain historical record; this ADR
  is the single source of truth for future adapter authors)

---

## Context

Four ADRs have shaped the `UsageExtractor` contract by evolution:

| ADR | Round | Contribution |
|-----|-------|--------------|
| ADR-009 | R12 | Introduced the hook, the `UsageContext` / `UsageResult` dataclasses, and the "extractor may never abort a recording" invariant. |
| ADR-010 | R15 | Added `anthropic_usage_extractor` / `openai_usage_extractor` siblings and pinned cache-token / reasoning-token field mapping. |
| ADR-011 | R17 | Added recursive pydantic→dict coercion at the serialization boundary; forced extractors to be dict-shape-aware via `_msg_field`. |
| ADR-012 | R18 | Activated `pre_values`: extractors now sum usage across **all new AIMessages** between pre- and post-snapshot, not just the last one. |

ADR-014 R2 (R24) called this out as the #2 Phase-2 entry blocker: the
contract is real and works, but it is implicit — scattered across four
ADRs, three convenience extractor implementations, and `langgraph_usage.py`
docstrings. An AutoGen adapter author in R26+ would have to reverse-
engineer the contract from the LangGraph implementation, which is exactly
the drift ADR-014 warns about: **"the second implementation becomes the
de-facto spec and drift compounds."**

This ADR consolidates the four predecessors into one contract, generalizes
the vocabulary from LangGraph-specific to framework-agnostic, and calls
out the parts AutoGen adapters are expected to re-use as-is versus the
parts they are expected to specialize.

### Why now, not at R26

Writing the adapter interface (R1, planned R26) against a drifted extractor
contract would bake that drift into the interface. The order is forced:
extractor contract v2 first (this ADR), adapter interface ADR second
(R26), then implementation.

### What this ADR is *not*

- Not a code change. The three existing extractors already implement
  everything below. ADR-015 is *documentation debt paydown*, nothing else.
- Not an AutoGen adapter design. That's ADR-TBD in R26, which will *cite*
  this ADR for the extractor-shaped portion of the interface.
- Not a pricing / cost-table proposal. Pricing remains user turf
  (ADR-009 §Decision #4 stays in force).

---

## Decision

The `UsageExtractor` contract consists of **five layers**. Layers 1-3 are
framework-agnostic and every future adapter MUST honor them verbatim.
Layers 4-5 are framework-specific: each adapter provides its own concrete
realization.

### Layer 1 — Data shape (framework-agnostic, invariant)

```python
@dataclass(frozen=True)
class UsageContext:
    node_name: str                     # identifier of the node being recorded
    pre_snapshot:  Any                 # adapter-native pre-execution state object
    post_snapshot: Any                 # adapter-native post-execution state object
    pre_values:    dict[str, Any]      # coerced (Layer 3) pre-state as JSON-safe dict
    post_values:   dict[str, Any]      # coerced (Layer 3) post-state as JSON-safe dict
    task:          Any                 # adapter-native task / step handle (best-effort)

@dataclass(frozen=True)
class UsageResult:
    prompt_tokens:     int = 0
    completion_tokens: int = 0
    reasoning_tokens:  int = 0
    cost_usd_cents:    int | None = None
    model_name:        str | None = None
```

**Invariants:**

- Both classes are `frozen=True` dataclasses. Extractors get read-only input
  and return a pure value — zero side effects are permitted on the types.
- `pre_values` / `post_values` are ALWAYS JSON-safe dicts (Layer 3
  guarantee). Extractors MUST NOT assume object-shape on these fields.
- `pre_snapshot` / `post_snapshot` are the adapter's native objects
  (LangGraph `StateSnapshot`, AutoGen `GroupChatManager` state, CrewAI
  `CrewState`, …). Extractors that need framework-specific metadata
  read from these; extractors that only need token usage do not.
- `task` is optional — some frameworks may pass `None`. Extractors MUST
  tolerate this.

### Layer 2 — Protocol & lifecycle (framework-agnostic, invariant)

```python
class UsageExtractor(Protocol):
    def __call__(self, ctx: UsageContext) -> UsageResult | None: ...
```

**Lifecycle invariants (every adapter MUST honor):**

1. **Optional kwarg.** The extractor is passed to the recorder constructor
   (e.g., `LangGraphRecorder(..., usage_extractor=...)`). Default `None`
   means "do not call any extractor; leave `Node.usage` = `None`."
   **Fully backwards compatible** is an adapter-level promise.
2. **One call per recorded node.** Called exactly once per `Node` the
   adapter is about to append — never zero times (would lose LLM nodes),
   never twice (would double-count).
3. **Called AFTER state coercion, BEFORE node append.** This ordering is
   non-negotiable: coercion guarantees Layer 3, and being pre-append lets
   the extractor's return value populate `Node.usage` / `Node.model_name`
   / `Node.cost_usd_cents` in the same transaction.
4. **`None` return = non-LLM node.** Leaves `Node.usage = None`,
   `Node.cost_usd_cents = None`. Expected for routers, tools, state-only
   nodes. The recorder MUST NOT treat `None` as an error.
5. **Raised exception = warning + skip.** The recorder MUST catch all
   exceptions, log one warning record at `WARNING` level to the logger
   `chronos.adapters.<adapter_name>.usage` with `exc_info=True`, and
   continue recording the node with `usage = None`. **A buggy extractor
   must NEVER abort a recording.** This is the single most important
   invariant in the entire contract.
6. **Field mapping.** The recorder MUST map returned fields exactly:
   - `prompt_tokens` + `completion_tokens` + `reasoning_tokens`
     → `Node.usage = Usage(...)`
   - `cost_usd_cents` → `Node.cost_usd_cents`
   - `model_name` → `Node.model_name`

   Any field left at its default (0 / `None`) is written as-is. The
   recorder does NOT synthesize values (e.g., does NOT compute cost
   from tokens — pricing is user turf).

### Layer 3 — Serialization boundary (framework-agnostic, invariant)

Before an extractor is called, the adapter MUST coerce its native state
values to a JSON-safe shape. ADR-011's `_jsonable` algorithm is the
reference implementation; any adapter MUST produce output
**observationally equivalent** to:

1. Primitives (`None`, `str`, `int`, `float`, `bool`) pass through.
2. Objects with `.model_dump()` (pydantic v1/v2, LangChain `BaseMessage`,
   AutoGen `Message`, …) are dumped, then recursed.
3. Generic objects with `__dict__` fall back to `dict(obj.__dict__)`,
   then recursed.
4. Containers (`dict` / `list` / `tuple` / `set` / `frozenset`) are
   recursed element-wise (tuples/sets become lists).
5. Exotic objects (datetime, UUID, Enum, bytes, …) surviving steps 2-4
   fall back to `repr(obj)` — **never raise**. Recording completeness
   beats type round-tripping.

**Why this is framework-agnostic:** every adapter's storage layer
(ADR-003's SQLite `state_after_json`) demands JSON-serializability. The
coercion rule has nothing to do with LangGraph; it's an invariant of the
adapter→store boundary. Putting it in the extractor contract (rather
than letting each adapter reinvent it) removes one class of drift.

**Extractor-author consequence:** extractors MUST read message fields
through a dict/object-bimodal helper (reference: `_msg_field` in
`chronos.adapters.langgraph_usage`). Writing `getattr(msg, "x", None)`
alone is insufficient — it will silently return `None` on the
dict-shaped inputs that Layer 3 produces.

### Layer 4 — Multi-call-per-node accumulation (framework-specific SHAPE, invariant POLICY)

**Policy (invariant):** when one super-step of the graph makes N≥1 LLM
calls between pre- and post-snapshot, the extractor MUST sum usage
across ALL N calls. "Last message wins" is forbidden — it silently
undercounts swarm / react_agent / evaluator-loop patterns by 30-70 %
(ADR-012 §Context).

**Shape (framework-specific):** how the extractor *finds* the N calls
depends on the framework. For LangGraph:

```python
delta_msgs = post_values["messages"][len(pre_values.get("messages", [])):]
for msg in delta_msgs:
    if _msg_is_ai(msg):
        accumulate(_msg_field(msg, "usage_metadata"))
```

For AutoGen (future R26), the analog would walk whatever list the
manager appends to — likely `post_values["chat_messages"]` sliced
against pre. For CrewAI, `post_values["tasks_output"]`. The slicing
policy is invariant; the field name is not.

**Invariant restated, framework-free:** `delta = post_stream − pre_stream`,
where `pre_stream` is possibly empty (first super-step). Extractors
MUST treat missing-pre as empty-pre.

### Layer 5 — Convenience extractors & model-specific field mapping (framework-specific IMPLEMENTATIONS)

Each adapter SHOULD ship convenience extractors for its common LLM
backends, following these naming and mapping conventions:

**Naming:** `<provider>_usage_extractor` — e.g.,
`anthropic_usage_extractor`, `openai_usage_extractor`. A generic fallback
named `<framework>_native_usage_extractor` (e.g.,
`aimessage_usage_extractor` for LangChain's standardised
`usage_metadata`) covers the provider-agnostic path when one exists.

**Field mapping (provider-invariant, see ADR-010 for LangGraph):**

| Provider | Source field | Maps to | Notes |
|----------|--------------|---------|-------|
| **Anthropic** | `usage.input_tokens` | `prompt_tokens` | base |
| | `usage.output_tokens` | `completion_tokens` | — |
| | `usage.cache_creation_input_tokens` | `prompt_tokens` (+=) | cost surcharge = user concern |
| | `usage.cache_read_input_tokens` | `prompt_tokens` (+=) | cost discount = user concern |
| | *(none)* | `reasoning_tokens = 0` | extended thinking not in basic usage block |
| **OpenAI** | `usage.prompt_tokens` | `prompt_tokens` | already includes cached |
| | `usage.completion_tokens` | `completion_tokens` | already includes reasoning |
| | `usage.completion_tokens_details.reasoning_tokens` | `reasoning_tokens` | o1/o3; NOT subtracted from completion |
| **LangChain std** | `AIMessage.usage_metadata.input_tokens` | `prompt_tokens` | LC 0.3+ |
| | `AIMessage.usage_metadata.output_tokens` | `completion_tokens` | — |

**Duck typing is mandatory.** Extractors MUST NOT `import anthropic`
or `import openai` — users without those packages still need the
extractors. Read by field name; tolerate missing fields via
`int(value or 0)`.

**`cost_usd_cents` default = `None`.** Convenience extractors MUST NOT
compute cost. Users compose pricing as a post-processing wrapper.

**Composed multi-provider fallback (documented pattern):**

```python
def mixed(ctx):
    return (anthropic_usage_extractor(ctx)
            or openai_usage_extractor(ctx)
            or aimessage_usage_extractor(ctx))
```

This one-liner is the ONLY supported way to combine extractors. Chronos
does NOT ship an auto-cascading "smart" extractor — that would hide
double-counting bugs when a message carries both metadata shapes.

---

## Framework portability matrix

| Layer | LangGraph (shipped) | AutoGen (R26+) | CrewAI (TBD) |
|-------|---------------------|----------------|--------------|
| **1 — data shape** | `UsageContext` / `UsageResult` verbatim | verbatim | verbatim |
| **2 — lifecycle** | verbatim (see `LangGraphRecorder._extract_usage`) | verbatim | verbatim |
| **3 — coercion** | `_jsonable` in `langgraph.py` | adapter owns its `_jsonable` (same algorithm) | ditto |
| **4 — delta policy** | invariant | invariant | invariant |
| **4 — delta SHAPE** | `post_values["messages"]` diff | `post_values["chat_messages"]` diff (or equivalent) | `post_values["tasks_output"]` diff (or equivalent) |
| **5 — convenience extractors** | `anthropic` / `openai` / `aimessage` | new module `autogen_usage.py` with mirror names | `crewai_usage.py` ditto |

**Cross-adapter reuse of provider extractors:** the Anthropic / OpenAI
field mappings in Layer 5 are *provider-specific*, not
framework-specific. A future AutoGen adapter SHOULD import the field-
mapping logic (not the whole extractor — the message-walking loop differs)
from a shared module. We will refactor when the second adapter lands;
until then, code duplication is acceptable (ADR-010 rationale stands).

---

## Consequences

### Positive

- **Single source of truth.** Future AutoGen / CrewAI adapter authors
  read one ADR, not four. R2 (ADR-014) is unblocked.
- **No code change.** ADR-015 only codifies what already exists. Zero
  risk of regression, zero test churn.
- **Adapter-author checklist.** Layers 1-3 are invariants → new
  adapter's CI can test them directly via a shared `UsageContext`
  fixture. Layers 4-5 are framework-specific → each adapter writes
  its own tests.
- **ADR-014 R2 ✅.** Phase 2 entry scorecard moves from 0/4 to 1/4
  required (assuming R26 tackles R1 next).
- **Discoverable.** `docs/decisions/ADR-015-extractor-contract-v2.md`
  is where someone searching "how do I write a new adapter?" lands.
  ADR-009 / 010 / 011 / 012 now bear "Consolidated into ADR-015"
  breadcrumbs (cross-linking round, same commit).

### Negative

- **One more ADR to maintain.** Mitigated: predecessors become
  historical; future edits go to ADR-015 only.
- **Risk of spec-code drift.** If the LangGraph extractor implementation
  changes but ADR-015 doesn't, the next adapter author reads the wrong
  contract. Mitigated: dogfood rounds test the contract; any contract
  change is itself an ADR.

### Neutral

- No version bump (R25 is a documentation round, same pattern as R24).
  CHANGELOG `[Unreleased]` accumulates R24 + R25 until next feature
  substance lands.

---

## Alternatives Considered

### (A) Leave the contract implicit, rely on ADR-009/010/011/012 + the LangGraph code as the spec

Rejected. ADR-014 R2 explicitly flags this as a Phase-2 blocker: "the
second implementation becomes the de-facto spec and drift compounds."
Doing the AutoGen adapter first and then writing this ADR retroactively
would lock in whatever drift happened during that adapter's
development.

### (B) Collapse ADR-009/010/011/012 into this one and delete them

Rejected. The predecessor ADRs document the **decision context** —
why cache tokens fold into `prompt_tokens`, why R18 forced the delta
rule, why pydantic coercion happens at the adapter boundary. Losing
that history makes future "why did we decide this?" questions harder
to answer. Cross-link breadcrumbs preserve both reachability and
history.

### (C) Push Layers 4-5 into framework-specific ADRs (one per adapter)

Rejected. The *policy* in Layer 4 (delta semantics) and the *shape* of
Layer 5 (naming, duck typing, `cost_usd_cents = None`) are
framework-agnostic. Only the concrete field names vary. Splitting would
create N copies of the same policy prose.

### (D) Define `UsageContext` as a `Protocol` instead of a frozen dataclass, so each adapter can add framework-specific fields

Rejected (for now). Simpler to keep `UsageContext` a single concrete
dataclass across all adapters — extractors that need framework-
specific metadata reach into `pre_snapshot` / `post_snapshot` (both
typed `Any`). If a future adapter *really* needs typed per-adapter
fields (e.g., AutoGen-specific `turn_id`), we revisit in the adapter's
own ADR; the Protocol migration is mechanical.

---

## Implementation Notes

**No code changes in R25.** The ADR is the deliverable. What already
exists is already compliant:

- `src/chronos/adapters/langgraph_usage.py` — Layers 1, 2, 5 shipped.
- `src/chronos/adapters/langgraph.py::_jsonable` — Layer 3 shipped.
- Layer 4 delta rule — R18 refactor in the three convenience extractors.
- All 264 tests green as of R24 HEAD (`5a8e844`).

**Cross-link work (this commit):**

- ADR-009 gets "**Consolidated into:** ADR-015" line.
- ADR-010 ditto.
- ADR-011 ditto.
- ADR-012 ditto.

**Where new adapters start reading in R26+:**

1. ADR-005 (adapter interface — to be written in R26 per R1).
2. ADR-015 (this ADR).
3. `src/chronos/adapters/langgraph_usage.py` as the reference
   implementation.

---

## Verification Gates

Because R25 is documentation-only, verification is lighter than a code
round:

- **ruff/format/mypy/pytest** all stay green (264/264).
- `grep -rn "UsageExtractor\|UsageContext\|UsageResult" docs/decisions/`
  shows all five ADRs (009, 010, 011, 012, 015) as the authoritative
  cluster; no stale docs elsewhere.
- ADR-009 / 010 / 011 / 012 each carry a "Consolidated into ADR-015"
  breadcrumb (verified by grep).
- `docs/CONTEXT.md` §5 references ADR-015 as the extractor contract
  citation (instead of pointing at 009/010/011/012 individually).

---

## Phase 2 entry impact

**Before R25:** R1 ❌, R2 ❌, R3 ❌, R4 ❌ (0/4 required)
**After R25:**  R1 ❌, R2 ✅, R3 ❌, R4 ❌ (1/4 required)

R26 candidate: **R1 — adapter interface ADR**. With Layer 1-3 of this
ADR as invariant foundation, R1 can cite ADR-015 rather than rederive
the extractor surface.
