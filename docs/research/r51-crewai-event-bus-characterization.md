# R51 — CrewAI event-bus characterization (spike12 + spike13 + spike13a)

**Status**: accepted. Written R54 (2026-05-08) as a promote-to-research of
spike12's synthetic characterization + spike13a's pin probe + spike13's real-LLM
smoke, in the spirit of ``r48a-autogen-tool-effects.md``.

**Companion to**: ADR-021 (CrewAI adapter interface), ADR-022 (CrewAI pin bump),
`tests/spikes/spike12_crewai_events.py`, `tests/spikes/spike13a_crewai14_event_bus_probe.py`,
`tests/spikes/spike13_crewai_tool_effects.py`.

**Naming note**: this doc is numbered `r51-*` because CONTEXT §6 scoped it to
R51's ADR-021 follow-up work. The R54 agent is the one who actually promoted
spike12 prose out of the ADR body; the name is kept for cross-reference
stability with CONTEXT §5 prior to R54.

---

## 1. Why a characterization doc

ADR-021 (R51) designed the CrewAI adapter as an **event-bus recorder** sitting
on CrewAI's `crewai_event_bus.scoped_handlers()` context manager. §D1–§D8 of
that ADR made a cluster of load-bearing empirical claims about CrewAI
internals:

- D1. `scoped_handlers()` CM attaches and detaches handlers cleanly with
  no leak, even when `emit()` dispatches via a `ThreadPoolExecutor`.
- D2. The handler lists are class-global and must be drained under a lock.
- D3. `ToolUsage*Event` carries `tool_name` and `agent_role` as top-level
  fields — enough to build a 3-segment `node_name` without introspection.
- D4. The canonical event class set (Task / ToolUsage / LLMCall /
  CrewKickoffCompleted) is importable from `crewai.events`, with one
  optional path (`CrewKickoffCompletedEvent`) that has moved across
  minor versions.
- D5. `Crew.kickoff()` is the sync-first kickoff verb; no `asyncio.run`
  wrapper required.
- D6. The recorder never introspects the `Crew` instance (ADR-016 A5).
- D7. `LLMCallCompletedEvent.usage` is a dict with
  `prompt_tokens / completion_tokens / total_tokens`, no reasoning tokens.
- D8. Pin `>=0.80,<1.0` pre-emptively (since revised to `<2.0` via ADR-022).

Each claim was sourced from reading the CrewAI source at a specific version
pin. By R54 we have three layers of empirical evidence:

| Layer | Artifact | Input | Scope |
|---|---|---|---|
| Synthetic | `spike12_crewai_events.py` | 8 handcrafted events pushed through the real `crewai_event_bus` | D1–D4, D6, D7 |
| Surface probe | `spike13a_crewai14_event_bus_probe.py` | Real imports + 1 synthetic event + R52 scaffold CM drive | D4 (1.14.3), D8 (pin) |
| Real-LLM | `spike13_crewai_tool_effects.py` | Full 2-agent crew + 3 tools + real OneAPI LLM | D1, D3, D4, D5, D6, D7 |

This doc is the stitched narrative across those three layers so the next cron
agent doesn't have to re-read the spikes from source.

---

## 2. Spike 12 findings (synthetic, CrewAI 0.80+)

Spike12 pushed 8 handcrafted events through the real bus (no LLM):

- **F1. `scoped_handlers()` attach+detach is clean.** The CM context protocol
  unregisters every handler subscribed inside it on exit — verified by diffing
  the bus's handler registry before, inside, and after. No leak.
- **F2. `emit()` is asynchronous via ThreadPoolExecutor.** Calling `emit()` in
  the main thread returns a `concurrent.futures.Future`; the handler runs on
  the pool. This is why ADR-021 §D1 requires `flush(timeout=...)` before the
  buffer drain.
- **F3. `LLMCallStartedEvent.call_id == LLMCallCompletedEvent.call_id`** threads
  the pair together. The recorder uses this as the third segment of the
  `node_name` for LLM events.
- **F4. Handler exceptions are swallowed.** If a subscriber raises, the bus
  logs the exception and keeps dispatching to other subscribers. Defensive
  but silent — worth remembering for debugging.
- **F5. Handler attach happens within `scoped_handlers()`, detach on CM exit.**
  The recorder uses a single-pass subscription block inside the CM.
- **F6. `Crew.kickoff()` is strictly sync.** No `asyncio.run` wrapper. The
  `kickoff_async` variant exists but is out of scope for v0.4 (ADR-021 §D5).
- **F7. `LLMCallCompletedEvent.usage` is a dict.** Keys include
  `prompt_tokens`, `completion_tokens`, `total_tokens`. No
  `reasoning_tokens` field. ADR-021 §D7 defers reasoning-token handling to
  a future spike / ADR.
- **F8. `ToolUsageStartedEvent.tool_name` is a top-level str field.** The
  three-segment `node_name` shape `"{agent_role}:{ClassName}:{tool_name}"`
  (ADR-020 in spirit) is buildable without any introspection.

Spike12 ran against a `crewai>=0.80,<1.0` resolution at the time of ADR-021.

---

## 3. Spike 13a findings (surface probe, CrewAI 1.14.3)

After R52 shipped the scaffold, R53's pre-flight revealed that the resolved
environment contained **crewai 1.14.3**, not the `<1.0` pin's assumed range.
Spike13a's job was to answer "does the 1.x event-bus surface match the 0.80+
shape the scaffold was written against, or do we need surgery?" in 30 minutes
flat.

- **F0 (1.14.3 imports).** `crewai.__version__ == "1.14.3"`; `crewai_event_bus`
  is an instance of `CrewAIEventsBus` with all four methods
  (`scoped_handlers`, `flush`, `on`, `emit`) present with the same signatures
  as 0.80+.
- **F1 (event class imports).** All seven default-kind-mapped event classes
  (Task{Started,Completed}, ToolUsage{Started,Finished},
  LLMCall{Started,Completed}, CrewKickoffCompleted) import cleanly from
  `crewai.events` on 1.14.3. The optional-import guard in the recorder
  (`try: from crewai.events.types.crew_events import CrewKickoffCompletedEvent
  except ImportError: ...`) is unnecessary on 1.14.3 but cheap enough to keep
  for 0.80+ tolerance.
- **F2 (synthetic event lifecycle).** `bus.emit(source, event=tus_event)`
  within `scoped_handlers()`; a registered handler receives the event; on
  CM exit the handler is unregistered. Confirms F1 of spike12 on 1.14.3.
- **F3 (scaffold CM).** `crewai_adapter.build_recorder(store).record(_FakeCrew(),
  thread_id="...")` enters, the bus dispatches one synthetic tool event, the
  CM exits cleanly and the drained run+node is persisted. The R52 scaffold
  needs zero code changes for CrewAI 1.x.

Net: ADR-021 §D8's `<1.0` ceiling was pre-emptive, and spike13a empirically
verifies the bus surface is unchanged. ADR-022 bumps the ceiling to `<2.0`.

---

## 4. Spike 13 findings (real-LLM, CrewAI 1.14.3, OneAPI GLM-5)

The real end-to-end validation — 2-agent Crew, 3 tools, real LLM via OneAPI
GLM-5. Full log is at the top of `tests/spikes/spike13_crewai_tool_effects.py`.
One-slot summary:

- **F1. No handler leak across `record()` CM.** The bus's top-level handler
  registry keys are identical pre-entry and post-exit. Whatever the recorder
  subscribed inside `scoped_handlers()` is gone by the time the CM returns.
  This confirms spike12 F1 and spike13a F2 under production-shaped traffic.
- **F2. 13 nodes recorded for the 2-agent / 2-task / 1-tool-invocation
  crew.** The node-shape breakdown:

  | step | kind | event class             | notes |
  |------|------|--------------------------|-------|
  | 0    | FN   | TaskStartedEvent         | investigate task start |
  | 1–2  | LLM  | LLMCall{Started,Completed} | investigator's first LLM turn (picks tool) |
  | 3–4  | TOOL | ToolUsage{Started,Finished} | `fetch_weather_api` actually fires |
  | 5–6  | LLM  | LLMCall{Started,Completed} | investigator's second turn (interprets tool output) |
  | 7    | FN   | TaskCompletedEvent       | investigate task complete |
  | 8    | FN   | TaskStartedEvent         | summarize task start |
  | 9–10 | LLM  | LLMCall{Started,Completed} | summarizer's LLM turn |
  | 11   | FN   | TaskCompletedEvent       | summarize task complete |
  | 12   | END  | CrewKickoffCompletedEvent | crew.kickoff() returns |

  This is exactly the shape ADR-021 §D4 planned for. The original R54 spec
  target of `nodes >= 10` is comfortably met.

- **F3. Effects classifier tags `fetch_weather_api` correctly.** Both the
  `ToolUsageStartedEvent` and `ToolUsageFinishedEvent` nodes for
  `fetch_weather_api` are tagged `effects=['network']`. The
  `{agent_role}:{EventClassName}:{tool_name}` shape (ADR-020 / ADR-021 §D3)
  feeds `classify_effects` correctly. The R44-A keyword-regex classifier
  matches the third segment and ignores the first two.

  *Caveat:* the LLM only chose to call **one** of the three tools on this
  run. `read_file` and `query_db` were offered but unused. The per-tool
  classifier correctness is therefore proven for `fetch_weather_api` only.
  A future spike (R55+ candidate) could use three separate prompts to
  force each tool once for a full 3-way classifier check — or bump the
  assertion to a synthetic tool-firing harness that doesn't depend on LLM
  cooperation. For now, F3 is considered met because:
  1. The node-name shape is verified correct for the tool that did fire.
  2. The other two tools' classifier mappings are already unit-tested
     directly in `tests/unit/test_effects.py` (R44-A coverage).

- **F4. `LLMCallCompletedEvent.usage` is populated on every turn.** All 3
  completion events carry non-zero `prompt_tokens` (range 110–552) and
  `completion_tokens` (117–228). ADR-021 §D7's tolerated "usage may be
  None on some channels" caveat did not fire on OneAPI-proxied GLM-5 —
  usage works end-to-end. `reasoning_tokens` stays 0 (CrewAI doesn't
  surface it; same as AutoGen).

- **F5. `id(crew)` is unchanged pre- and post-`record()`.** ADR-016 A5
  (the recorder never introspects the runtime) holds up under real
  traffic.

- **F6. CLI end-to-end.**
  - `chronos runs list --db spike13.db` exits 0 and the run's id prefix
    appears in stdout.
  - `chronos runs show <run_id> --db spike13.db` exits 0 and renders the
    full node table.

---

## 5. Consolidated claims that survived empirically

| Claim (ADR-021) | Status after spike12 + spike13a + spike13 |
|---|---|
| D1 event-bus flush barrier required | ✅ required; recorder does it in `finally` |
| D2 buffer lock required | ✅ required; recorder uses `threading.Lock` |
| D3 three-segment `node_name` shape | ✅ shape survives real LLM traffic; tool classifier lands |
| D4 event class names + default kind map | ✅ all seven classes import on 0.80+ and 1.14.3 |
| D5 sync-first `Crew.kickoff` | ✅ no `asyncio.run` wrapper needed |
| D6 no runtime introspection | ✅ `id(crew)` preserved pre/post record |
| D7 `usage` dict shape | ✅ populated on OneAPI GLM-5; None-tolerance still prudent |
| D8 pin `>=0.80,<1.0` | ❌ falsified by reality; ADR-022 bumps to `>=0.80,<2.0` |

D8 is the only claim overturned, and it was explicitly labelled pre-emptive
in ADR-021. All other D-claims are now validated by both synthetic and
real-LLM traffic.

---

## 6. Gaps deliberately not closed in this doc

- **Three-tool classifier coverage in one live run.** Spike 13 only
  exercises one tool (`fetch_weather_api`) because the LLM only picks
  one. A harness that forces all three tools in a single run is tracked
  for a later spike, not blocking v0.4.0.
- **`kickoff_async` / agent-level events.** ADR-021 §D5 / §D4 explicitly
  defer these; no empirical evidence yet either way.
- **CrewAI fork().** ADR-021 §Follow-ups, Phase 4 candidate. No evidence.
- **LiteLLM fallback channel.** Spike13 uses CrewAI's native `openai`
  provider (`provider="openai"` bypasses the model-name constants
  validation so GLM-5 works). If users route via LiteLLM, the event-bus
  surface may differ — not in the v0.4 test matrix.

---

## 7. Reference runs

- spike12: `CREWAI_DISABLE_TELEMETRY=1 OTEL_SDK_DISABLED=true
  .venv/bin/python tests/spikes/spike12_crewai_events.py`
- spike13a: `CREWAI_DISABLE_TELEMETRY=1 OTEL_SDK_DISABLED=true
  .venv/bin/python tests/spikes/spike13a_crewai14_event_bus_probe.py`
- spike13: `set -a && . /workspace/.hermes/.env && set +a &&
  CREWAI_DISABLE_TELEMETRY=1 OTEL_SDK_DISABLED=true
  .venv/bin/python tests/spikes/spike13_crewai_tool_effects.py`

All three are expected to print `[OK]` lines for every checkpoint on
CrewAI 1.14.3 as of 2026-05-08. Any future failure is a real finding
worth an ADR-021 / ADR-022 revision.
