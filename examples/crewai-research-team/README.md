# crewai-research-team demo

A CrewAI-style **multi-agent research pipeline** showing how Chronos
lets you A/B-test the *persona* of one agent in a team without
re-running the upstream agent.

## Shape

```
   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
   │  researcher  │ →  │   analyst    │ →  │   reporter   │ →  │   finalize   │
   │  (LLM)       │    │  (LLM)       │    │  (LLM)       │    │  (end)       │
   └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

* **Parent run** `bbbbbbbb-…-bbb1`: topic = *"remote work productivity"*,
  analyst's `stance="neutral"`, reporter writes a balanced, moderately
  positive summary.
* **Child run** `bbbbbbbb-…-bbb2`: forked at the **analyst** node with
  `stance="critical"`. The reporter now produces a measurably longer and
  more skeptical report (and uses more tokens/cost — visible in
  `chronos runs list`).
* **Fork edge** `bbbbbbbb-…-ff01` with `edited_fields={"stance": "critical"}`.

## Why this demo exists

This is the multi-agent counterpart to `langgraph-router`. Where
`langgraph-router` shows fork = different *branch*, `crewai-research-team`
shows fork = different *persona on a fixed topology*. The interesting
debugging question it lets you answer is: *"how much of my final report's
character is the topic, vs. how much is the analyst's stance?"*

## Try it

```bash
chronos quickstart --demo crewai-research-team --force
chronos runs list                     # cost column shows fork-child > parent
chronos diff bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1 bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2
chronos eval run bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1 --evaluator final_state_key_present
chronos eval run bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2 --evaluator final_state_key_present
chronos compare bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1 bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2 --eval output_length_chars
chronos web
```

Both runs should pass `final_state_key_present` (the built-in is bound to
key=`output`, which both branches produce in `final_state`) — and
`compare --eval output_length_chars` should rank the critical-stance
fork-child higher (longer report).

## Notes

* All token/cost numbers are **synthetic illustrative** — no real LLM call
  happens at quickstart time (per ADR-029).
* Adapter is labelled `crewai`, but quickstart treats adapter strings as
  opaque labels — no CrewAI install required to load this demo.
