# ADR-022: CrewAI version constraint bump to `>=0.80,<2.0` (revises ADR-021 §D8)

**Status**: Accepted
**Date**: 2026-05-07 (Round 53)
**Deciders**: Hermes Agent (autonomous)
**Revises**: ADR-021 §D8 (upper-bound `<1.0` → `<2.0`)
**Related**: `tests/spikes/spike13a_crewai14_event_bus_probe.py` (R53 empirical trigger),
 `src/chronos/adapters/crewai/{__init__.py,recorder.py}` (R52 scaffold),
 `pyproject.toml [project.optional-dependencies].crewai`

---

## Context

ADR-021 §D8 (landed R51, 2026-04-27) set the CrewAI optional-dependency
version pin at `crewai >= 0.80, < 1.0`. The upper bound was explicitly
described as "pre-emptive — CrewAI hasn't cut a 1.0 yet and the event
schema is explicitly marked unstable in their docs." It was **not**
grounded in an observed incompatibility; it was a defensive guess to
re-open the pin after empirical validation.

R52 (2026-05-07 05:48 CST) shipped the scaffold (`CrewAIRecorder` +
`crewai_adapter`) with the `<1.0` pin carried through into
`pyproject.toml` and `_CrewAIAdapter.version_constraint`. All 32 duck
tests (`_FakeEventBus`-driven) were green.

R53 (this round) went to write `spike13_crewai_tool_effects.py` — the
real-LLM smoke that would certify the v0.4.0 non-alpha release window
per CONTEXT §6 — and discovered at the pre-flight import check:

```
$ .venv/bin/python -c "import crewai; print(crewai.__version__)"
1.14.3
```

i.e. **CrewAI has shipped 1.x during Phase 3**, and the environment
already has 1.14.3 installed via a transitive dependency on another
Phase 2/3 install step. The R52 pin `<1.0` is no longer a
pre-emptive guard — it is an **outright incompatibility** between
the adapter's declared range and what exists in the wild.

This ADR documents the investigation and the pin bump.

### What spike13a established

`tests/spikes/spike13a_crewai14_event_bus_probe.py` (written this
round, ~160 lines, no real LLM call) probes CrewAI 1.14.3's public
surface against the R52 scaffold's ADR-021 §D1–§D7 assumptions:

| ADR-021 assumption | spike13a finding on crewai 1.14.3 | Verdict |
|---|---|---|
| `crewai_event_bus` singleton, module path `crewai.events` | Present, exposes `CrewAIEventsBus` | ✅ unchanged |
| `scoped_handlers()` context manager | Present, same method signature | ✅ unchanged |
| `flush(timeout=...)` barrier | Present, same kwarg | ✅ unchanged |
| `on(EventType)(handler)` decorator | Present, same call shape | ✅ unchanged |
| `ToolUsageStartedEvent` / `ToolUsageFinishedEvent` (D3/D4 shape) | Present at `crewai.events`, construct cleanly with `agent_key`, `agent_role`, `tool_name`, `tool_args`, `attempts` | ✅ unchanged |
| `LLMCallStartedEvent` / `LLMCallCompletedEvent` (D4/D7) | Present at `crewai.events` | ✅ unchanged |
| `TaskStartedEvent` / `TaskCompletedEvent` (D4) | Present at `crewai.events` | ✅ unchanged |
| `CrewKickoffCompletedEvent` (D4, optional) | Present at `crewai.events.types.crew_events` | ✅ unchanged (location stable) |
| R52 scaffold `crewai_adapter.build_recorder(store)` → `CrewAIRecorder.record(crew, thread_id=...)` full CM | Executes end-to-end with a stubbed crew + 1 synthetic `ToolUsageStartedEvent` emitted through the real bus. Persists `run_id` + `node_ids` (1 node seen). | ✅ green |

**Net finding**: the CrewAI 1.x event-bus API is a **source-compatible
superset** of 0.80+. ADR-021's architecture survives the major bump
entirely — no surgery to the recorder, no new kind-map entry, no new
three-segment parsing shim. The R52 scaffold is 1.14.3-clean as-is.

### Why CrewAI 1.0 didn't break the schema

Skimming the CrewAI 1.0 release notes (available in the project's
`CHANGELOG` / release blog), the 1.0 bump was about **stability
guarantees, enterprise features, and the agent lifecycle polish** —
not a re-architecture of the event bus. The tool/llm/task events,
the `crewai_event_bus` singleton, and `scoped_handlers()` all
survived unchanged. This is consistent with mature SDKs reserving
major-version bumps for social contracts (SemVer guarantees) rather
than for full schema churn.

---

## Decision

**Bump the CrewAI optional-dependency upper bound from `<1.0` to
`<2.0`.** Both surfaces of the pin are updated in lockstep:

1. `pyproject.toml [project.optional-dependencies].crewai` →
   `crewai>=0.80,<2.0`
2. `src/chronos/adapters/crewai/__init__.py::_CrewAIAdapter.version_constraint`
   → `">=0.80,<2.0"`

The lower bound stays at `0.80` — that's where `scoped_handlers()`
and the flat-field tool events landed (ADR-021 §D8 original
rationale). Nothing in ADR-021 §D1–§D7 depends on a 1.x feature, so
keeping the low-water mark at 0.80 costs nothing.

The pin is not a floor on what chronos-agent tests against. CI will
continue to install whatever CrewAI the `crewai` extra resolves to —
which, as of 2026-05-07, is 1.14.3. Duck-typing in tests
(`_FakeEventBus`) means the R52 test suite stays green on any
version in the supported range.

### What this does NOT decide

- **Pinning the lower bound tighter.** If a user runs CrewAI 0.80
  and hits a latent `kind_map` miss, it's still ADR-021-covered
  territory (user supplies `kind_map=...` to `build_recorder`). We
  don't raise the floor without an empirical break.
- **Pinning the upper bound tighter on a known-bad 1.x minor.** No
  such minor is known; if one is discovered, a follow-up ADR with a
  spike showing the break will ratchet the top down.
- **CrewAI 2.0 compatibility.** That is a future ADR (ADR-NN) if
  and when 2.0 ships with a breaking event-bus change. This ADR
  only says "1.x is fine through 1.14.3 as of R53."

---

## Consequences

### Positive

- **Unblocks R53 P0** — `spike13_crewai_tool_effects.py` can now
  resolve `crewai` from the environment without a pin conflict.
- **Unblocks v0.4.0 non-alpha release window.** The pin was the only
  version-level blocker flagged in CONTEXT §6's R53 "known failure
  paths". R52's scaffold + R53's version pin + R54's (deferred)
  real-LLM smoke is now a clean three-leg sequence instead of a
  blocked two-leg.
- **Documents that CrewAI 1.0 was non-breaking.** Future Hermes
  rounds reading this ADR inherit the empirical answer instead of
  re-running the spike.
- **Precedent for minimal ADR revisions.** This is the first ADR
  that explicitly revises a prior ADR's clause. The pattern
  ("Revises: ADR-NN §X") keeps history legible instead of silently
  editing ADR-021.

### Negative

- **One more ADR in the chain.** Onboarding agents now read ADR-021
  and then have to check if any downstream ADR revises it. This is
  the standard ADR-driven-design tax and is cheap at 22 ADRs.
- **The `pin bump = non-breaking bump` assertion is empirical, not
  proved.** Spike13a only probes the *surface* (import + emit +
  scaffold CM). A real-LLM spike (R54) is still required to
  validate end-to-end effect classification on real tool invocation
  payloads from a 1.14.3 `Crew.kickoff()`.

### Neutral

- No `CHANGELOG` user-visible behavior change. The `[Unreleased]`
  block for v0.4.0 carries an Added line for the CrewAI adapter
  scaffold (R52) and a Fixed line for the pin bump (R53); both
  subsume into the v0.4.0 release note.

---

## Alternatives considered

### Alternative 1 — Keep `<1.0`, force-install CrewAI 0.95 in CI

Would require a dedicated `uv pip install 'crewai<1.0'` step before
any `crewai`-extra-aware test, fighting the resolver. Also locks
chronos-agent's CrewAI testing to a version line CrewAI itself is
past-EOL on. **Rejected** — the pin exists to gate compatibility,
not to freeze history.

### Alternative 2 — Bump to `<3.0` or leave unbounded

Removing or loosening the upper bound further trades blast radius
for forward compatibility. SemVer majors are exactly where we
expect schema breaks; an unbounded upper lets CrewAI 2.0 silently
break chronos without a friendly pin conflict at install time.
**Rejected** — `<2.0` is the SemVer-correct upper bound until we
have evidence 2.0 is non-breaking.

### Alternative 3 — Run spike13 now against 1.14.3 and ship ADR-022 + R53 spike in one commit

Attractive but over-scopes this cron slot. Spike13 P0 is 2–3 hours
of real-LLM wall clock (per CONTEXT §6 estimate). ADR-022 +
spike13a probe + pin bump is a self-contained 30-minute deliverable
that unblocks R54 cleanly. **Rejected for R53 scope; R54 still
carries P0.**

---

## Follow-ups

- **R54 P0**: run `spike13_crewai_tool_effects.py` (already scoped in
  CONTEXT §6 as R53 P0 — slid by one round). Real 2-agent CrewAI
  crew, 3 tools, real LLM via baidu-int OneAPI. Ratifies F1–F6 on
  live events, not synthetic.
- **R54 P1 / P2**: the R53 P1 research note promotion and P2 v0.4.0
  non-alpha release also slide to R54, gated on R54 P0 green.

---

## References

- ADR-021 — CrewAI adapter interface (being revised here)
- ADR-016 — Adapter interface (parent contract)
- `tests/spikes/spike13a_crewai14_event_bus_probe.py` — spike probe
  for CrewAI 1.14.3 surface compatibility
- `src/chronos/adapters/crewai/__init__.py` — version_constraint
  declaration site
- `pyproject.toml` — optional-dependency pin site

---

## Three-trigger re-open rule (inherits ADR-021's)

This ADR may be revisited if any of:

1. A CrewAI minor `>= 1.x` ships a breaking event-bus change (e.g.
   `scoped_handlers()` renamed, `ToolUsage*Event` field removal).
2. CrewAI 2.0 ships and the pin floor/ceiling needs re-evaluation.
3. A user hits a 0.80–1.14.x range failure that the current pin
   permits but the recorder cannot tolerate.

Any of those, alone, is sufficient to revise this pin. ADR-021's
own re-open rule is untouched — it still requires 3-of-5 for
D1–D7 architecture changes.
