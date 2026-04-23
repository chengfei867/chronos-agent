# ADR-013 — Fork Auto-Execution: Stay Frozen

- **Status:** Accepted
- **Date:** 2026-04-23
- **Round:** R21 (formalized after R17+R18+R20 three-dogfood evidence arc)
- **Relates to:** ADR-005 (fork semantics), ADR-008 (fork CLI plan artifact)
- **Supersedes:** none (this ADR does NOT change code — it formalizes a non-decision)

## Context

ADR-008 shipped the fork surface as **JSON-only**: `chronos fork` produces a
`ForkPlan` artifact and prints it; there is no built-in "execute this fork
now" button. The user is expected to read the plan and wire it into their
own graph invocation if they want counterfactual replay.

At the time (R7), we explicitly **froze** automatic fork execution with the
rationale "we don't yet have evidence about what safe auto-execution should
look like (sandbox? timeout? budget? idempotency keys?), and building it
without that evidence risks shipping the wrong abstraction."

Three rounds of real-world dogfood later, the question is ripe for a
decision.

## Evidence gathered

| Round | Target | Topology | Execute-fork demand |
|---|---|---|---|
| **R17** | `langgraph-supervisor-py` | Centralized routing | **0** |
| **R18** | `langgraph-swarm-py` | Decentralized handoff | **0** |
| **R20** | `langgraph-bigtool` | Single agent + meta-tool | **0** |

Across three dogfood rounds with three **orthogonal** LangGraph topologies
(covering the three dominant multi-agent patterns as of 2026 Q1), the user
(this agent, operating autonomously) **never once** wanted Chronos to
execute a fork directly. In every case the pattern was:

1. Run the graph, record to Chronos.
2. Inspect the trace (`chronos replay`, `chronos stats`, or direct SQL).
3. If a branching point was interesting, that interest was satisfied by
   **reading** the plan artifact — not by wanting Chronos to re-run.

## Decision

**Chronos will not ship automatic fork execution in Phase 1.** The ADR-008
"JSON-only" boundary is formally **affirmed** and will remain frozen until
one of the trigger conditions below fires.

This is not a soft "maybe later" — this is a decision to **stop wasting
bandwidth** thinking about it. Roadmap priorities for R22+ should be set
from other signal (see "Deferred alternatives" below).

## Evidence quality disclaimer

The evidence is **weak-but-consistent**, not statistically robust:

- **One user** (this autonomous agent, no external users yet)
- **One LLM backend** (Claude Opus 4.7 via baidu-int OneAPI)
- **One graph framework** (LangGraph 1.1.9)

What makes the evidence usable despite being thin:

- **Consistency across topologies.** The three dogfood targets are not
  variations of the same thing — supervisor/swarm/bigtool genuinely cover
  the three dominant patterns. If execute-fork were load-bearing for
  counterfactual exploration, it would have surfaced on at least one.
- **Bar appropriate to the decision.** We're not deciding "ship
  execute-fork forever" (which would need much stronger evidence). We're
  deciding "don't ship execute-fork **now**, prioritize other work." For
  the latter, weak-consistent is sufficient.
- **Open reversal conditions** (see below) — this is not a one-way door.

## Trigger conditions to revisit

Execute-fork becomes a live project when **any** of these fire:

1. **External user issue.** An outside user (not this agent) files a
   GitHub issue stating they need Chronos to execute a fork without them
   writing glue code.
2. **New topology uncovers hard limit.** A future dogfood round exposes a
   case where the JSON-only boundary is structurally insufficient (e.g.,
   a graph shape where "just wire the plan into your own invocation"
   demonstrably doesn't work).
3. **Phase 2 adapter requires it.** When AutoGen/CrewAI adapters are
   built (explicitly deferred until after ADR-013), if the non-LangGraph
   adapters force execute-fork to express basic counterfactual semantics,
   reopen.

None of these conditions are active as of R21.

## Consequences

### Positive

- **Focus dividend.** R22+ planning starts from a clean "what ships next"
  question instead of "should we finally build execute-fork?"
- **Extract DX polish instead.** R20 surfaced F2 (`Node.model_name`
  cognitive friction). Fixing that kind of wart is where marginal hours
  compound, because it reduces user (and self-as-agent) steering cost.
- **Smaller surface to maintain.** JSON-only fork means fewer moving
  parts in case-study reproducers; no sandbox, no timeout logic, no
  budget enforcement.

### Negative

- **Looks sparse on "feature list".** Chronos's one-liner is still "time-
  travel debugger" but the time-travel is read-only + BYO-execution.
  Honest framing wins over headline-feature chasing: it's a **recorder**
  first, a **replay inspector** second, and a **fork-planner** third.
- **Locks in a specific notion of "debugger".** Some users may expect
  time-travel debuggers to include re-execution (rr, pernosco). If a lot
  of users express this expectation, condition #1 above fires.

### Neutral

- Code is unchanged by this ADR. No version bump required.

## Deferred alternatives (explicitly not done)

These were considered and rejected or deferred:

### A. "Lift the freeze and build execute-fork now"
**Rejected.** Building without evidence of demand is how features rot into
"implemented but nobody uses this."

### B. "Build a minimal execute-fork behind a feature flag"
**Deferred.** Even minimal execute-fork requires sandbox/timeout/budget
decisions. Until at least one trigger condition fires, designing those
is premature.

### C. "Add a code template generator that emits the user-side glue"
**Deferred to R22+.** This is a **real** middle ground: instead of
Chronos executing forks, Chronos could emit a pastable Python snippet
that loads the ForkPlan and wires it into the user's graph. Low
complexity, useful. Not blocked by ADR-013 and worth considering.

## Related R21 work

R21-B (same round as this ADR) adds `Node.model` as a convenience property
alias for `Node.model_name`, addressing R20 Finding #2 — a DX polish that
exemplifies the "extract friction-fixes instead of headline features"
posture above.
