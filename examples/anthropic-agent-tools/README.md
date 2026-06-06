# anthropic-agent-tools demo

An **Anthropic-Agents-style tool-using research agent**, designed to
exercise Chronos's `tool` NodeKind on a realistic
plan → search → fetch → synthesize loop.

## Shape

```
   ┌──────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────┐
   │ plan │ →  │  web_search  │ →  │  fetch_page  │ →  │  synthesize  │ →  │ finalize │
   │ (LLM)│    │   (tool)     │    │   (tool)     │    │   (LLM)      │    │  (end)   │
   └──────┘    └──────────────┘    └──────────────┘    └──────────────┘    └──────────┘
```

* **Parent run** `cccccccc-…-ccc1`: task = *"Find the population of Tokyo as of 2024"*,
  no citation required, output is a one-line answer.
* **Child run** `cccccccc-…-ccc2`: forked at the `synthesize` node with
  `citation_required=true`, output is the same fact + a source URL.
* **Fork edge** `cccccccc-…-ff01` with `edited_fields={"citation_required": true}`.

## Why this demo exists

`builtin-minimal` and `langgraph-router` are LLM-only. `crewai-research-team`
is multi-agent but still LLM-only. `anthropic-agent-tools` is the demo
that exercises the **`tool` NodeKind path** end-to-end — both the
Chronos UI and the evaluator infrastructure need to handle tool-shaped
nodes with `tool_name` set, no `usage`, and tool-flavoured `state_after`.

The fork is interesting on a second axis too: the model's *answer* is
the same in both branches; what changes is the *form*. A perfect demo
for the `output_length_chars` evaluator showing that "longer ≠ better"
in the absence of further context — exactly the pedagogical point of
shipping multiple built-in evaluators (ADR-030).

## Try it

```bash
chronos quickstart --demo anthropic-agent-tools --force
chronos runs list
chronos diff cccccccc-cccc-4ccc-8ccc-ccccccccccc1 cccccccc-cccc-4ccc-8ccc-ccccccccccc2
chronos eval run cccccccc-cccc-4ccc-8ccc-ccccccccccc1 --evaluator final_state_key_present
chronos eval run cccccccc-cccc-4ccc-8ccc-ccccccccccc2 --evaluator final_state_key_present
chronos compare cccccccc-cccc-4ccc-8ccc-ccccccccccc1 cccccccc-cccc-4ccc-8ccc-ccccccccccc2 --eval output_length_chars
chronos web
```

In the web UI's **TreeView**, both `web_search` and `fetch_page` should
render as tool-kind nodes (distinct from the `plan` / `synthesize` LLM
nodes). The fork-tree should show the child branching from `synthesize`,
not from any of the upstream tool steps.

## Notes

* All token/cost/HTTP responses are **synthetic illustrative** — no real
  LLM call or web request happens at quickstart time.
* Adapter is labelled `anthropic_agents`; quickstart treats adapter
  strings as opaque labels — no SDK install required.
