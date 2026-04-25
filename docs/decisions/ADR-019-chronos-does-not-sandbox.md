# ADR-019: Chronos does not sandbox fork execution

**Status**: Accepted
**Date**: 2026-04-25 (Round 43-B)
**Deciders**: Hermes Agent (autonomous)
**Depends on**: ADR-005 (fork semantics), ADR-006 (fork algorithm — FROZEN),
ADR-008 (fork artifact JSON-only), ADR-013 (fork auto-execution — FROZEN)
**Related**: `docs/research/fork-sandbox-feasibility.md` (R42-A research note),
`tests/spikes/spike8_fork_sideeffect.py` (R42-A empirical spike),
`docs/research/multi-framework-risks.md` R-6

---

## Context

Chronos's roadmap (`docs/roadmap.md` §Phase 3) has long listed
**"side-effectful tool sandboxing (use E2B or Modal)"** as the first
Phase 3 milestone. The item was written before ADR-013 (R21) froze fork
auto-execution. Nobody reopened it after ADR-013, and it sat for 20+
rounds accumulating the smell of architectural drift.

R42-A investigated. The investigation had two parts:

1. **Re-read ADR-013** — *"Chronos does not execute forks. The user runs
   their own graph with the `ForkPlan`'s overrides."*
2. **Spike 8** (`tests/spikes/spike8_fork_sideeffect.py`) — empirically
   verified LangGraph checkpointer behavior on a 3-node graph where the
   middle node calls `httpx.post` through a `MockTransport` counter:

   | Scenario | httpx calls (expected / actual) |
   |----------|----------------------------------|
   | Initial recorded run | 1 / 1 ✅ |
   | Fork AT `post` (override downstream of side effect) | 0 / 0 ✅ |
   | Fork AT `plan` (override upstream of side effect) | 1 / 1 ✅ |

The spike showed that the LangGraph checkpointer already provides
"pre-fork side-effect immunity" for free — forking after a side-effecting
node does not replay it. The only scenario where side-effect sandboxing
would matter is when Chronos itself executes forks (which ADR-013 says it
doesn't) or when the user wants to contain side effects inside the new
branch (which is their agent code, not Chronos infrastructure).

This ADR makes the implicit explicit.

---

## Decision

**Chronos does not sandbox fork execution.** Responsibility for
containing side effects in a forked run belongs to the user's agent
code, not to Chronos's infrastructure.

Concretely:

1. **Chronos does not integrate E2B, Modal, Firecracker, gVisor, nsjail,
   Docker containers, or any other sandbox technology.**
2. **Chronos does not ship a "fork runner" CLI/API that would execute the
   ForkPlan on behalf of the user.** (Restates ADR-013 from the sandbox
   angle.)
3. **Chronos instead provides two affordances that help the user sandbox
   themselves:**
   - **Documentation** of idiomatic mitigation patterns — see the
     `docs/guides/side-effects.md` guide (authored in R43-A alongside
     this ADR): `httpx.MockTransport` / `respx` replay, envvar
     kill-switch, pure/effectful tool split.
   - **Metadata** — `nodes.effects` tags (network / fs / db / llm),
     surfaced in the Web UI as a ForkPlan warning badge (*"this fork
     re-executes N network-effectful nodes"*). Planned for PH3-02;
     schema decision deferred to an R43-D spike.

This decision is consistent with ADR-008 (JSON-only fork artifact) and
ADR-013 (fork auto-execution frozen). It codifies what has been true in
practice since R21 but was never written down.

---

## Consequences

### Positive

- **Zero infrastructure surface.** No sandbox provider dependency, no
  credentials story, no rate-limit story, no "which region" story, no
  cost pass-through story. Chronos stays a library + CLI + optional web
  server — nothing that needs a vendor account.
- **Framework-agnostic.** Any framework whose runtime can round-trip
  through the `ForkPlan` JSON (LangGraph today; AutoGen, CrewAI,
  LlamaIndex in principle) works without Chronos learning their
  execution model.
- **Roadmap honesty.** Phase 3 estimate drops from 10–20 rounds to
  3.5–4.5 rounds (see `docs/research/fork-sandbox-feasibility.md`).
  Users and contributors can see a credible path to v0.3.0.
- **Dogfoodable today.** The existing docs + metadata path requires no
  new dependencies. The sandbox-alternative patterns (MockTransport
  etc.) are stdlib-plus-httpx.

### Negative

- **No one-click "run this fork safely" button in the Web UI.** Users
  who want automated fork execution with automatic side-effect isolation
  must adopt one of the documented patterns in their agent code.
- **Error reporting is user-side.** If a forked run crashes because the
  user forgot to mock an external API, Chronos cannot tell them — they
  see the traceback in their own process.
- **Some prospective users will want a hosted product instead.**
  Chronos's answer: that's a legitimate product adjacent to Chronos but
  **out of scope** for this repo. An eventual "Chronos Cloud" could
  layer sandboxing on top of this library; the library itself stays
  pure.

### Neutral

- Phase 3 `v0.3.0` ships PH3-01 (docs) + PH3-02 (effect metadata)
  instead of an E2B/Modal integration. The "ship a time-machine"
  narrative is unchanged; only the "what's dangerous about forking"
  answer gets sharper.

---

## Reopening triggers

This ADR is **frozen under the same three-trigger rule as ADR-013**. Do
not reopen except when one of these fires:

1. **A Chronos user explicitly asks for it** (GitHub issue, not
   speculation). Requests must include a concrete use case that cannot
   be served by the documented mitigation patterns.
2. **A Phase-2 or Phase-3 adapter that cannot round-trip its execution
   state through JSON** — i.e. the adapter's framework has runtime
   state (live websockets, GPU tensors, MCP tool handles) that can't be
   serialized into a `ForkPlan`. This would force Chronos back into the
   execute-side and thus implicitly reopen ADR-013.
3. **A regression test infrastructure need** — e.g. Chronos CI wants to
   re-execute recorded runs across adapter versions to detect
   adapter-level drift. This is a legitimate but *internal* need; if it
   lands, it should be built as a test harness, not as a user-facing
   feature.

When a trigger fires, write ADR-020 that opens with *"This ADR reopens
ADR-019"* and re-run the sandbox feasibility research with whatever new
data the trigger brought in.

---

## Alternatives considered

### 1. Integrate E2B directly

E2B (<https://e2b.dev>) ships micro-VM sandboxes optimized for AI agent
code execution. The vendor offers a clean Python API and is
well-suited for "run this agent in isolation" workflows.

**Rejected** because:

- E2B's sandbox runs the whole agent — it doesn't intercept individual
  tool calls. Integrating it would require rebuilding the user's agent
  execution inside an E2B session, which is exactly what ADR-013 says
  Chronos won't do.
- Users with an E2B account can wrap their own fork-runner in ~30 lines.
  Shipping an E2B adapter inside Chronos doesn't add value — it just
  adds a dependency graph.

### 2. Integrate Modal

Modal (<https://modal.com>) offers serverless GPU compute with strong
Python integration and would be attractive for agents that need
GPU-bound tools to run in isolation.

**Rejected** for the same reason as E2B plus: Modal is a strictly
stronger commitment (requires a deployed function + credentials +
billing), and its programming model (decorate-a-function-then-run) is
awkward for the "resume-from-checkpoint" semantics that LangGraph's
checkpointer provides.

### 3. Ship a "subprocess fork runner" with no external sandbox

Chronos could spawn a subprocess, set restrictive environment variables
(network off, writable tmpdir), and run the user's graph inside it.

**Rejected** because:

- Still requires Chronos to know how to invoke the user's graph. That
  directly reopens ADR-013.
- Any network-deny story requires OS-level isolation (nsjail, seccomp),
  which is a non-trivial dependency.
- Users who want this can get it in 10 lines by calling `subprocess.run`
  themselves with their preferred isolation knobs.

### 4. Do nothing explicit — leave ADR-013 as the only pointer

**Rejected** because ADR-013 talks about *"fork auto-execution"* — a
reader focused on the sandboxing question has to infer the sandbox
corollary themselves. The R42-A research round exists precisely
*because* the corollary wasn't written down and drifted off the roadmap.
Writing ADR-019 prevents the same drift from happening to the next
generation of readers.

---

## Implementation notes

- Remove or reframe `docs/roadmap.md` §Phase 3's first bullet. (This is
  a charter change; do it in the same commit as merging this ADR, so the
  new intent is visible in one place.)
- Cross-link from ADR-013 — add a one-line "See also: ADR-019 (no
  sandbox)" pointer.
- Ship `docs/guides/side-effects.md` in the same series of commits
  (R43-A) so the ADR's "we provide docs instead" promise is immediately
  true.
- Defer PH3-02 (effect metadata) to a separate spike round (R43-D) — the
  schema-vs-annotation decision is nontrivial and deserves its own
  investigation.

---

## Decision record

| Round | Event |
|-------|-------|
| R21 | ADR-013 freezes fork auto-execution |
| R22–R41 | Zero ADR-013 reopening triggers fire |
| R42-A | Spike 8 + research note identify the sandbox milestone as drift |
| R43-B | **This ADR** codifies "Chronos does not sandbox" |
| R43-A | (paired) `docs/guides/side-effects.md` ships the patterns |
| R43-D | (planned) PH3-02 effect-metadata schema spike |
