# R49 — LangGraph adapter ADR-020 audit (Follow-up closure)

**Date:** 2026-04-27 (Round 49, CST ~10:50 cron slot)
**Spike:** `tests/spikes/spike11_langgraph_tool_effects.py` (ran green
offline, no real LLM needed; 4 findings, all ✅)
**Closes:** ADR-020 §Follow-ups item "review LangGraph and CrewAI
adapters' tool-node naming".
**Scope note:** CrewAI audit is deferred — no CrewAI adapter exists yet
(R50+ candidate per CONTEXT.md §6). This note closes only the LangGraph
half of that follow-up.

---

## TL;DR

ADR-020 claimed LangGraph is "vacuously satisfied" by the three-segment
`{source}:{ClassName}:{tool_name}` `node_name` contract, because its
graph-level node name is **already** the tool function name. That claim
was made from code-reading in R48-A; Spike 11 confirms it empirically.

**Action items from the audit:**

1. **No adapter code change required.** `src/chronos/adapters/langgraph.py`
   is compliant as-is. `node_name = task.name` (langgraph.py:466) equals
   the string the user passed to `StateGraph.add_node(name, fn)`.
2. **One real gotcha was uncovered** that deserves documentation:
   `LangGraphRecorder(store, kind_map=...)` is **effectively required**
   for Phase 3 effect annotations to fire on LangGraph. Without
   `kind_map`, every node defaults to `NodeKind.FN`, and the classifier's
   `kind == NodeKind.TOOL` gate in `effects.py::classify_effects` (L146)
   short-circuits — so even the most suggestively-named node
   (`fetch_weather_api`, `read_file`, `query_db`) gets `effects = []`.
   → Docstring patch recommendation in §4 below.
3. **ADR-020 Follow-ups can be marked resolved for LangGraph.** CrewAI
   remains open (no adapter yet; to be addressed when ADR-021 is written).

---

## 1. What the spike verified

Four graph nodes, intentionally named to trip each
`src/chronos/adapters/effects.py` pattern group:

| LangGraph node name  | Matching pattern group | Expected tag |
|----------------------|------------------------|--------------|
| `plan`               | *(none — pure FN)*     | `[]`         |
| `fetch_weather_api`  | `NETWORK_PATTERNS`     | `["network"]`|
| `read_file`          | `FS_PATTERNS`          | `["fs"]`     |
| `query_db`           | `DB_PATTERNS`          | `["db"]`     |

Spike runs the same compiled graph twice: Run A without `kind_map`, Run
B with `kind_map` declaring the three tool-shaped nodes as
`NodeKind.TOOL`.

### Finding F1 — `node_name` shape (the ADR-020 claim)

LangGraph's `task.name` (used by the adapter at
`langgraph.py:466` as `node_name = getattr(task, "name", None)`) equals
exactly the string the user passed to `StateGraph.add_node(name, fn)`.
No prefix, no suffix, no colon separators. The set of distinct
`node_name` values from Run A matches `{"plan", "fetch_weather_api",
"read_file", "query_db"}` exactly, and none contain `":"`.

This is the empirical form of ADR-020's "LangGraph is exempt" carve-out
(ADR-020 §Decision / Shape rules #1 and §Graph-based adapters). The
classifier's keyword regex (`\bfetch_\w+\b`, `\bread_file\b`,
`\w*(read|write)_db\b`, etc.) sees the raw function name directly —
exactly what its word-boundary `\b` metacharacters were designed for.

### Finding F2 — the `kind_map` usage gotcha

Run A (no `kind_map`) produced `effects=[]` for every node, including
the three with obviously tool-shaped names:

```
step=1  kind=fn      node_name='fetch_weather_api'  effects=[]
step=2  kind=fn      node_name='read_file'          effects=[]
step=3  kind=fn      node_name='query_db'           effects=[]
```

Why: `classify_effects` gates the keyword-regex branch on
`kind == NodeKind.TOOL`. LangGraph has no framework-level concept of
"tool node vs function node" — the distinction is purely in how the
user thinks about the node body. So the adapter defaults everything to
`NodeKind.FN` (`langgraph.py:470`), and the classifier correctly but
unhelpfully refuses to guess.

**Consequence for real users:** anyone who builds a LangGraph agent and
expects the Phase 3 fork-modal "⚠️ 4 downstream dangerous nodes" warning
to fire will silently get zero warnings unless they declare their tool
nodes via `kind_map`. This is a documentation problem, not a code
problem.

### Finding F3 — classifier works end-to-end when `kind_map` is declared

Run B with
`kind_map={"fetch_weather_api": TOOL, "read_file": TOOL, "query_db": TOOL}`
produced the expected effect tags per-node:

```
step=1  kind=tool    node_name='fetch_weather_api'  effects=['network']
step=2  kind=tool    node_name='read_file'          effects=['fs']
step=3  kind=tool    node_name='query_db'           effects=['db']
```

`plan` correctly stayed `kind=fn effects=[]` (not in `kind_map`). This
confirms the classifier's LangGraph path is end-to-end correct when
used correctly.

### Finding F4 — ADR-020 "vacuously satisfied" is empirically true

ADR-020's actual invariant is
**"the classifier's input string contains the tool function name"**,
not "the string has three colon-separated segments" — see ADR-020
§Consequences: "Graph-based adapters… are exempt from the three-segment
convention. They may continue emitting single-segment function names."

LangGraph satisfies the invariant directly: `node_name` IS the tool
function name, no surgery needed. F1–F3 together demonstrate this.
Nothing in the LangGraph adapter needs to change.

---

## 2. What this means for Phase 3 UX

The fork-modal `ForkPlanModal` warning Alert reads `effects_summary`
off the run's nodes (R46-A / R47-A / R48-B pipeline). For LangGraph
users who don't pass `kind_map`, `effects_summary.dangerous_count` is
always 0, so the modal always shows the green-success "No dangerous
side effects downstream" Alert — a dangerous false-positive safety
signal.

This is why the **documentation remediation** in §4 matters more than
any code change: silent false-safety is worse than a loud false-alarm.

A good rule of thumb we can tell users: **if your LangGraph node body
makes an HTTP request, touches disk, or reads/writes a database, pass
it to `LangGraphRecorder(..., kind_map={"your_node_name":
NodeKind.TOOL})`**. The classifier will do the rest.

---

## 3. What we explicitly did NOT test

- **`langgraph.prebuilt.ToolNode` branches.** We did not build a graph
  that uses `ToolNode(tools=[...])` as its body, because R46-A / R47-A
  use cases (and the spike-9 / R44-A test suite) already exercise
  straightforward function-body nodes. If a future user reports that
  their `ToolNode` wrapper produces unexpected `task.name` values, a
  spike-12 can extend this audit — but it's not blocking R49.
- **Subgraphs / compiled-sub-graphs used as nodes.** LangGraph 1.1.9
  exposes these via `StateGraph.add_node(name, compiled_subgraph)`.
  We expect `task.name` to still equal the outer `name`, matching the
  same `node_name` contract. No current Chronos test exercises this;
  not in scope for R49.
- **CrewAI adapter.** Does not exist yet. ADR-021 (future) will codify
  the CrewAI-side `node_name` shape per the AutoGen precedent.

---

## 4. Recommendations

### 4.1 Documentation (do now — cheap, high impact)

Add a one-paragraph "Effect tagging on LangGraph: declare your TOOL
nodes" note to `LangGraphRecorder.__init__` docstring
(`src/chronos/adapters/langgraph.py:66-90`). Draft:

> **Effect tagging (Phase 3):** If you want the Phase 3 effect-classifier
> (`docs/guides/side-effects.md`) to tag your tool nodes with
> `["network"]` / `["fs"]` / `["db"]` / `["external"]`, declare them via
> `kind_map={"<name>": NodeKind.TOOL, ...}`. LangGraph has no
> framework-level tool/function distinction, so the adapter defaults
> every node to `NodeKind.FN` and the classifier cannot infer TOOL-ness
> from the name alone. See `docs/research/r49-langgraph-adr020-audit.md`.

This patch is R49 **candidate follow-up** — it's a two-line docstring
addition and a single-line cross-link. Worth landing in R50 together
with the screenshot refresh (the refreshed screenshots will expose the
fork-modal Alert prominently, so the doc link becomes more useful).

### 4.2 ADR-020 Follow-ups section — mark LangGraph resolved

ADR-020 §Follow-ups currently reads (paraphrased):

> review LangGraph and CrewAI adapters' tool-node naming

After this spike lands, the LangGraph half is resolved and can be
rewritten as:

> ~~LangGraph audit~~ — closed R49. `node_name` is single-segment and
> function-shaped; ADR-020 "vacuously satisfied" claim verified by
> Spike 11. CrewAI remains open and will be addressed when the CrewAI
> adapter is proposed (ADR-021 candidate).

This edit lands in the same commit as this note.

### 4.3 No test suite addition

Spike 11 is a one-off script, not a pytest. The behaviors it exercises
are already covered by:

- `tests/unit/test_effects_classify.py` (R44-A) — classifier keyword
  matrix. If this test breaks, the spike would also break.
- `tests/integration/test_dual_adapter_dogfood.py` (multi-round) — full
  LangGraph record + fork + effects path with real `kind_map`.

No need to promote the spike to a pytest; per
`chronos-spike-authoring` skill, spikes stay as-is for future
re-verification.

---

## 5. How to re-verify

```bash
cd /workspace/chronos-agent
uv run python tests/spikes/spike11_langgraph_tool_effects.py
```

Expected tail:

```
[F1 ✅] LangGraph node_name is single-segment and function-shaped: ...
[F2 ✅] Without kind_map, every node effects=[] — ... LangGraph usage gotcha.
[F3 ✅] With kind_map declaring TOOL on function-named nodes, classifier returns correct effect tags.
[F4 ✅] ADR-020 vacuously satisfied for LangGraph: ...
SPIKE 11 RESULT: LangGraph adapter is ADR-020-compliant (vacuous).
```

Runs in <2 s, no API keys, no network, no real LLM.

---

## 6. File inventory produced by R49

- `tests/spikes/spike11_langgraph_tool_effects.py` — 260 lines incl.
  docstring; the empirical verification script.
- `docs/research/r49-langgraph-adr020-audit.md` — this note.
- `docs/decisions/ADR-020-adapter-tool-node-name-shape.md` — Follow-ups
  section amended to mark LangGraph resolved (small edit, see commit
  diff).

Screenshot refresh + `scripts/capture_fork_modal.py` helper are
explicitly deferred to R50 — see this round's progress doc §3 for the
deferral rationale.
