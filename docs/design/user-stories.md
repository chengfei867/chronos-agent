# User Stories & Scenarios

**Last updated**: 2026-04-22 (Round 1)

> The purpose of this document is to **ground the product in real use cases** before any architecture work. Each story walks through a concrete scenario with the exact CLI commands and Web UI interactions we envision.

---

## Personas

### P1. "Alex" — The Multi-Agent Developer
Working on a RAG pipeline with 3 specialized agents (retriever, reasoner, writer). Agent cost spiked from $0.02/run to $0.80/run last week. Needs to know: which agent's prompt got worse? Can I compare old-prompt-run to new-prompt-run?

### P2. "Sam" — The AI Researcher
Running experiments on different tool-calling strategies. Has 200 recorded runs. Wants to test a hypothesis: "What if agent had used tool X instead of tool Y at step 4?" Needs to fork 50 historical runs with the edit and compare outcomes.

### P3. "Jordan" — The Framework Explorer
Evaluating LangGraph vs. AutoGen for their team. Wants to run the same task on both, then structurally compare: which had fewer LLM calls? which had better final output? Needs cross-framework diff.

### P4. "Hermes Agent" (self) — The AI Developer
Building chronos-agent itself. Uses chronos-agent on its own coding runs to understand where it went off-track. This is the canonical dogfood.

---

## Story 1: "Why is my agent suddenly expensive?" (Primary MVP story)

**Persona**: Alex
**Journey**:

1. Alex has been running his agent with chronos-agent auto-recording enabled
2. Daily he sees cost per run. Yesterday: $0.02. Today: $0.80.
3. Alex opens terminal:

```bash
$ chronos list --last 20
┌──────────┬─────────────┬────────┬────────┐
│ run_id   │ time        │ cost   │ tokens │
├──────────┼─────────────┼────────┼────────┤
│ run_abc5 │ 5m ago      │ $0.82  │ 42,150 │
│ run_abc4 │ 1h ago      │ $0.78  │ 40,200 │
│ ...                                       │
│ run_xyz1 │ 2 days ago  │ $0.02  │ 2,150  │
└──────────┴─────────────┴────────┴────────┘

$ chronos diff run_abc5 run_xyz1
╔═════ DIFF: run_abc5 (today) vs run_xyz1 (baseline) ═════╗
║                                                          ║
║  Cost:     $0.82 → $0.02     (+4000%)                    ║
║  Nodes:    23   → 8          (+15 nodes)                 ║
║  Tokens:   42k  → 2.1k       (+20x)                      ║
║                                                          ║
║  Top cost divergence:                                    ║
║    node_5  retriever.search                              ║
║      today:  12 queries × 3k tokens context              ║
║      before: 1 query  × 1k tokens                        ║
║                                                          ║
║    node_12 reasoner.llm_call                             ║
║      today:  recursive call x8                           ║
║      before: single call                                 ║
║                                                          ║
║ Use: chronos inspect run_abc5 --node node_5              ║
╚══════════════════════════════════════════════════════════╝

$ chronos inspect run_abc5 --node node_5
  (prints full prompt, full tool args, full tool response)
  (shows: retriever prompt template changed — now uses "exhaustive mode")
```

4. Alex realizes: someone changed the retriever prompt last week. Easy fix: revert.
5. To verify the fix works: fork run_abc5 with old prompt re-inserted:

```bash
$ chronos fork run_abc5 --at node_5 --set-prompt file://old_prompt.txt --name cheap-again
  → executing forked run: fork_abc5_v1
  → node 5: LLM call (0.3s)
  → node 6: tool call (1.2s)
  → ... (progress bar)
  → fork complete. cost: $0.02

$ chronos diff run_abc5 fork_abc5_v1
  → shows old prompt restores cost/output parity
```

6. **Value delivered**: Alex found the regression in 5 minutes without a production incident.

---

## Story 2: "Counterfactual research" (Advanced story for v0.2+)

**Persona**: Sam

```bash
$ chronos list --tagged experiment-v12
$ chronos fork-batch --runs experiment-v12-* \
                    --at "tool:retriever" \
                    --swap-tool new_retriever \
                    --output experiment-v13

→ forking 200 runs... (parallel, 4 workers)
→ 200/200 complete

$ chronos compare --group experiment-v12 --against experiment-v13 \
                  --metric final_output_eval --metric total_cost

┌─────────────────────┬──────────┬──────────┬─────────┐
│ metric              │ v12 avg  │ v13 avg  │ delta   │
├─────────────────────┼──────────┼──────────┼─────────┤
│ final_output_eval*  │ 0.72     │ 0.81     │ +12.5%  │
│ total_cost ($)      │ 0.45     │ 0.38     │ -15.6%  │
│ latency_p50 (s)     │ 12.3     │ 10.1     │ -17.9%  │
└─────────────────────┴──────────┴──────────┴─────────┘
*LLM-as-judge evaluation

→ open web: chronos web --compare v12:v13
```

**Value delivered**: Sam proves a hypothesis scientifically on 200 historical runs without rerunning production.

---

## Story 3: "Framework bake-off" (v0.3+ stretch story)

**Persona**: Jordan

```bash
# Jordan has two adapters installed: langgraph, autogen
$ chronos record --adapter langgraph -- python agent_langgraph.py
$ chronos record --adapter autogen   -- python agent_autogen.py

$ chronos list --last 2
┌──────────────┬───────────┬────────┬───────┐
│ run_id       │ framework │ cost   │ nodes │
├──────────────┼───────────┼────────┼───────┤
│ run_lg_1     │ langgraph │ $0.18  │ 14    │
│ run_ag_1     │ autogen   │ $0.24  │ 11    │
└──────────────┴───────────┴────────┴───────┘

$ chronos diff run_lg_1 run_ag_1 --cross-framework
→ normalizes both to canonical form
→ reports semantic differences (not surface)
```

---

## Story 4: "The self-debugging AI" (Canonical dogfood)

**Persona**: Hermes Agent (autonomous AI developer)

When a cron-run produces a bad commit:
1. The next cron cycle reads `progress/last-round.md` and sees "tests failed on line X"
2. `chronos list --tagged hermes-round-N` finds the run where the bad commit was made
3. `chronos inspect <run> --node "file_edit:line:X"` shows the exact LLM reasoning that produced the bad edit
4. Hermes forks with a corrective system prompt, re-runs, verifies the fix, commits

**Value delivered**: Self-improving AI development pipeline. This is the ultimate dogfood.

---

## Web UI Scenarios

Complementing the CLI — the Web UI handles cases where visuals beat text:

### WV1. Reasoning Tree View
- Interactive tree (zoom, pan, collapse)
- Each node shows: prompt/tool-call preview, cost, latency, status
- Click node → right panel shows full details
- Highlight divergent nodes when comparing two runs

### WV2. Fork-and-Diff Side-by-Side
- Two trees side-by-side
- Aligned nodes colored by divergence severity
- Click aligned pair → inline diff of prompts/responses

### WV3. Timeline View
- Horizontal swim-lane: one lane per agent (multi-agent)
- Shows parallel execution, handoffs
- Click span → node details

### WV4. Cost Waterfall
- Stacked bar chart of cost per node
- Sort/filter by node type, agent, tool
- Helps answer "what was expensive?"

---

## CLI Design Principles

Based on the stories above:

1. **Subcommand structure** (`chronos <verb>`):
   - `record` — wrap an agent run, capture trace
   - `list` — browse recorded runs
   - `inspect` — zoom into one run (or one node)
   - `diff` — compare two runs (or a run and a fork)
   - `fork` — create a new run by branching an existing one
   - `fork-batch` — apply a fork template across multiple runs
   - `compare` — aggregate-level stats across groups of runs
   - `web` — launch local web UI
   - `export` — export traces (JSON, Parquet)
   - `prune` — delete old traces (retention management)

2. **Zero-config local mode**: `chronos record -- python agent.py` works out of the box; stores to `~/.chronos/`

3. **Human-readable output first, JSON on flag**: default pretty; `--json` for machine-readable

4. **Discoverable**: every command ends with a "Use: chronos ..." suggestion for likely next step

5. **Cost-aware**: every output shows cost where relevant — chronos-agent exists partly because cost surprises are a top use case

---

## Non-Goals (for now)

To keep scope tight, these are **explicit non-goals** for v0.1-v0.2:

- ❌ Production monitoring (Langfuse does this; we focus on dev-loop)
- ❌ LLM proxy mode (Helicone does this)
- ❌ Prompt management / versioning (Humanloop does this)
- ❌ Dataset-based evaluation (Braintrust does this)
- ❌ Real-time alerting / anomaly detection
- ❌ Team collaboration / sharing (post-v1.0 consideration)
- ❌ Hosted SaaS (local-first forever is a feature)

If users demand these, we evaluate case-by-case. Default answer: **focus on fork/replay/diff; let others do the rest**.

---

## Success Metrics per Story

| Story | Success measured by |
|---|---|
| S1. Cost regression | Time-to-root-cause < 5 min on 20-node agent |
| S2. Counterfactual | Batch fork 100 runs + compare < 15 min |
| S3. Framework diff | Cross-framework adapter shows semantic-level diff, not surface |
| S4. Self-debugging | Hermes Agent's own failed commits get auto-diagnosed in > 50% of cases |

---

## Open UX Questions for Design Phase

1. [ ] How do we represent a streaming LLM response visually? (span vs. point)
2. [ ] How do we show "dependency-aware partial fork" — which nodes re-executed, which stayed cached
3. [ ] TUI or web-first? (feasibility doc Q5)
4. [ ] How do we name runs / forks ergonomically? (random hash vs. semantic slugs like "fork-cheap-retriever")
5. [ ] How does a user correct a recorded run when the error was at step 1? (re-record-from-start vs. edit-root)

---

*Document owner: Hermes Agent. Source of truth for product scope until superseded.*
