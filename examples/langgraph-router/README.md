# langgraph-router demo

A LangGraph-shaped **conditional-edge routing** demo, designed to exercise
Chronos's fork machinery on a real branching pattern (not just a linear
pipeline like `builtin-minimal`).

## Shape

```
                 ┌──────────────┐
                 │   classify   │  ← LLM, sets state["category"]
                 └──────┬───────┘
                        │
                 ┌──────▼───────┐
                 │    route     │  ← fn, picks next based on category
                 └──┬────────┬──┘
        general_answer    technical_answer
              │                 │
              └────────┬────────┘
                 ┌─────▼────────┐
                 │   finalize   │  ← end
                 └──────────────┘
```

* **Parent run** `aaaaaaaa-…-aaa1`: question = *"What's the capital of France?"*,
  classified as `general`, routed to `general_answer`, output is a one-line answer.
* **Child run** `aaaaaaaa-…-aaa2`: forked at the `classify` node with
  `category="technical"`, re-routes to `technical_answer`, output is a richer
  answer with coordinates and historical context.
* **Fork edge** `aaaaaaaa-…-ff01` links the two with
  `edited_fields={"category": "technical"}`.

## Why this demo exists

`builtin-minimal` is intentionally trivial (3 linear nodes, 1 LLM kind).
`langgraph-router` is the next step up: it shows that fork-then-rerun changes
not just a value but the **branch the graph takes** — the kind of debugging
question (*"what would have happened if the classifier said X instead?"*)
that Chronos was built to answer.

## Try it

```bash
chronos quickstart --demo langgraph-router --force
chronos runs list
chronos diff aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1 aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2
chronos eval run aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1 --evaluator output_length_chars
chronos eval run aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2 --evaluator output_length_chars
chronos compare aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1 aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2 --eval output_length_chars
chronos web
```

`compare --eval output_length_chars` should rank the technical-branch child
above the general-branch parent — the longer answer scores higher on the
length-chars evaluator, which is the simplest "did the fork actually change
something measurable?" signal.

## Notes

* All token/cost numbers are **synthetic illustrative** — no real LLM call
  happens at quickstart time (per ADR-029).
* This is the second demo to ship; see `builtin-minimal/` for the format
  reference and `crewai-research-team/` + `anthropic-agent-tools/` for the
  other two demos under the R118 acceptance gate.
