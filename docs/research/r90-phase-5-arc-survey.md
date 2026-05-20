# R90 Research — Phase 5 Arc Selection Survey

**Round**: 90 (Phase 5 kickoff planning, post-v0.7.0 GA md-only slot)
**Date**: 2026-05-21 (CST, BJT 09:54, in-window cron slot)
**Status**: Research survey. Feeds [ADR-027 Draft][ADR-027].
**Supersedes**: The Phase 5 stub in [docs/roadmap.md][roadmap] §"Phase 5+" ("Vague on purpose" — three one-liners with no scope).
**Scope**: Evaluate four candidate arcs for Phase 5 (post-v0.7.0). Pick **one recommended primary** plus **one hot-backup**. Deliver a 9-axis comparative table, dependency analysis, and a slice-by-slice rollout sketch for the recommended arc.

---

## 0. Why this doc exists

With Phase 4 fully closed at v0.7.0 GA (Arc A v0.5.x→v0.6.0 R58-R67, Arc B slice 1 v0.7.0a1→v0.7.0 R70-R88, R89 contract docs polish), the project is at a natural planning beat. The next 3-6 rounds need a binding direction or they'll drift into ad-hoc fixture / docs / dogfood polish work. ADR-023 (Phase 4 charter) successfully steered 30+ rounds via the "three arcs framing → commit one"  pattern; R90 replicates that pattern for Phase 5.

R90 is a **planning round** (md-only, ≤2 slots). Its output (this doc + ADR-027) is fuel for the next 3-6 rounds. The R57→R58 and R68→R69 precedents both show: a planning round consumed in slot N produces 5-8 high-quality impl rounds in slots N+1..N+8.

### Hard constraints from prior ADRs (still binding in Phase 5)

- **[ADR-001][ADR-001]** — Python 3.11+ pin. TypeScript-native arcs (Vercel AI SDK, Mastra) remain blocked.
- **[ADR-016][ADR-016]** — adapter interface contract. Any new adapter must be expressible as `RecorderProtocol` + `AdapterProtocol`.
- **[ADR-019][ADR-019]** — Chronos does not sandbox fork execution. Any "isolation" or "VM-based fork" arc is out.
- **[ADR-023][ADR-023]** — Phase 4 charter; Arc C (plumbing) explicitly demand-driven, not capability-driven. Same logic still applies in Phase 5: arcs without a clear leverage story are deferred.
- **[ADR-026][ADR-026]** §6 — all 5 ACs `[x]` at v0.7.0; Arc B slice 1 done. Slice 2+ (Pydantic AI, Letta, OTel receiver) remain candidates.
- **No external users** — confirmed via R67 / R88 progress docs and CONTEXT §0; project is private. Phase 5 is therefore **leverage-driven**, not demand-driven. Pick the arc most likely to **attract** the first external user, not what an existing user requests.

### What R90 explicitly does NOT do

R90 does NOT:

- Write code (md-only round, see CONTEXT §3.1 rule 2).
- Cut a release (Phase 5 first slice will land at v0.8.0; v0.7.1 is reserved for accumulated docs polish if any).
- Re-open Arc A / Arc B charter decisions (Phase 4 closed cleanly; reopening would be drift).
- Bind the slice-2 + slice-3 details — only slice-1 of the chosen arc is committed in ADR-027. Subsequent slices get their own ADRs (R57 `chronos-spike-authoring` cadence).

---

## 1. Candidate inventory (2026-05-21)

The four arcs that survived initial screening. All four were named in CONTEXT §6 R90 hand-off (Option α plan §Goal). Each has at least one prior round of source-inspection or design audit, so none is purely speculative.

### 1.1 Arc C — Replay UI / Time-travel debugger interactive frontend

**Pitch**: Build the user-facing interactive replay surface — keyboard navigation through a recorded run's nodes with state diff side-panel, inline override editor, "fork from here" CTA, and live URL state for sharable replay sessions. Builds on the existing `frontend/` SPA (React 19 + Vite + ReactFlow, R34-C/R36-D/R37.5/R46-A/R48-B).

**State at R90**:

- **Backend** — `GET /runs/{id}/tree` (R34-A) and `GET /runs/{id}/nodes` (R34-A) already cover the read path. No new schema needed.
- **Frontend** — `frontend/src/pages/TreeView.tsx` (684 LOC) renders the static fork-tree DAG. `NodeDetails` drawer (R36-D, 4 tabs: Identity / I-O / State / Cost) covers single-node inspection. `ForkPlanModal` (R46-A) covers fork-creation UX. **Replay mode is the missing surface**: there is no "step through nodes interactively, see state evolve" flow.
- **CLI** — `chronos replay <run_id>` (M1.7, R8) is already a TUI replay. Web replay would be a port + extension.

**ADR-016 compatibility**: ✅ none needed; replay reads existing data, doesn't change adapter contract.

**Slice sketch (3-5 rounds, target v0.8.0)**:

- Slice 1 — `frontend/src/pages/Replay.tsx` core: linear playback timeline + step controls + state-evolution side panel. Keyboard ←/→/space/q parity with CLI.
- Slice 2 — fork-tree mode: replay through a fork's parent → diverge-point highlight → child branch replay. Reuses TreeView's lane layout.
- Slice 3 — URL-shareable state: `#/runs/<id>/replay?step=N&fork=<fork_id>` deep-linking + clipboard copy.
- Slice 4 (stretch) — diff-aware replay: when comparing two runs (R65 matrix view), step both in lockstep and call out diverging nodes inline.

**Risks**:

- (R-1) Frontend bundle size — current 1.39 MB raw / 452 KB gzipped (R36-D). Adding a second page route + state-evolution UI could push to 600 KB gzipped; manageable but not free. Mitigation: `React.lazy` per-route + AntD modular import audit.
- (R-2) State-evolution rendering — node `state_after` is opaque framework-specific JSON. Generic deep-diff display is not always meaningful (e.g. LangGraph `MessagesState` vs anthropic_agents `state_after.blocks[i].block`). Mitigation: per-adapter `formatState(state) → ReactNode` hook in adapter package, default to `react-json-view`.
- (R-3) Animation cost — Framer Motion already in the bundle (R36-D); add `usePlayback` hook (already exists, R36-D) ergonomic ports. Low risk.
- (R-4) **Visual review forcing function** — the `dogfood` skill + R37.5 lesson ("interface-green ≠ user-visible-correct") apply with full force here. Every slice must end with a `chronos web` browser_vision pass before progress doc.

**Leverage story**: This is **the** marquee feature that distinguishes Chronos from Langsmith/Langfuse/Phoenix. Those tools all have static trace viewers; "step through reasoning + see diverge points" is the hero demo for the project's name ("Chronos" = time). First external-user attractor.

**Slot budget**: 4-5 slots (3 impl + 1 dogfood + 1 polish/release).

**Dependencies on Phase 4 work**: low — only reads the data path that's already stable. No adapter changes needed.

---

### 1.2 Arc D — Cross-framework golden-trace test fixtures

**Pitch**: Build a deterministic regression layer: capture canonical recorded JSONL traces from each of the 4 first-class adapters (langgraph, autogen, crewai, anthropic_agents) and assert the recorder + fork primitive correctness against fakes that replay the captured envelopes. Result: every CI run verifies all 4 adapters' end-to-end behaviour without `CHRONOS_LIVE=1` or any LLM relay.

**State at R90**:

- **Currently** — only `langgraph` and `linear` (toy) adapters are tested in CI deterministically. AutoGen / CrewAI / anthropic_agents tests are either unit-stub-based (mocked SDK) or `CHRONOS_LIVE=1`-gated (relay-dependent, not run in CI).
- **Coverage gap** — a real-relay regression in any of the three live-gated adapters would surface only in dogfood rounds, not CI. R86 hit this exact pattern: relay degraded, R85's previously-green dogfood failed too, no CI signal. Cost: full slot of confusion + recovery.
- **Existing scaffolding** — `tests/unit/fixtures/anthropic_agents_stubs.py` (R84) is a partial precedent. Linear adapter's reference impl (R28) demonstrates the pattern on a smaller scale.

**ADR-016 compatibility**: ✅ test-only, no production code change.

**Slice sketch (3-5 rounds, target v0.8.0 or v0.7.1)**:

- Slice 1 — Capture infrastructure: `scripts/capture/` directory with one capture script per adapter (`capture_anthropic_agents.py`, etc.). Each script runs against the live relay once with `CHRONOS_CAPTURE=1`, dumps the SDK's top-level event stream as JSONL to `tests/fixtures/golden_traces/<adapter>/<scenario>.jsonl`. **Captures must be sanitised** — no API keys, no proprietary tool descriptions; replace with synthetic values via a sanitiser hook.
- Slice 2 — Fake replay infrastructure: `tests/fakes/<adapter>/replay.py` per adapter, `class FakeRuntime` that replays captured JSONL and exposes the same surface the adapter calls (e.g. for anthropic_agents: a fake `ClaudeSDKClient.query()` async iterator that yields envelopes from the JSONL).
- Slice 3 — Golden-trace tests per adapter: `tests/golden/test_<adapter>_golden.py` — for each captured scenario, replay through the fake, run the recorder, assert resulting Run has the captured node-count / kinds / names / state shape. Strict-xfail forcing function applies (R76→R77 / R79→R80).
- Slice 4 — Regression-ratchet integration: any `CHRONOS_LIVE=1` round that captures a NEW interesting envelope shape automatically `--save-golden` to a new fixture file; reviewer chooses to merge or discard. This is the long-term mechanism by which the golden corpus grows organically.

**Risks**:

- (R-1) Captured envelope drift over SDK versions — when `claude-agent-sdk` ships v0.2.0 with a new envelope, captured fixtures from v0.1.x may stop validating. Mitigation: capture-version metadata in JSONL header; recapture on SDK upgrade is a documented release pre-flight step (`chronos-release-pattern` skill addition).
- (R-2) Capture sanitisation completeness — if a capture leaks a real API key or a customer-confidential tool description, the fixture is unshippable. Mitigation: sanitiser regex audit + manual review checklist + `git diff` review on every capture commit.
- (R-3) Per-adapter capture infra cost — each adapter's stream has different framing (LangGraph: checkpointer events; AutoGen: BaseAgent.on_messages_stream; CrewAI: event-bus emit; anthropic_agents: SDK message iterator). Slice 1 is 4 sub-rounds, not 1. Mitigation: ship slice 1 incrementally — anthropic_agents first (most needed, AC-3 unblock vector), then crewai, then autogen, then langgraph.
- (R-4) Fork primitive coverage — pure replay is cheaper than fork; fork-replay needs the fake to support `fork_session()` semantics. anthropic_agents already has this (per R80 hybrid trap fake). Other 3 adapters need new fork-fake work. Risk for slice 3.

**Leverage story**: AC-3-style relay-flake outages stop blocking releases. CI grows from "src compiles + 4 adapter unit tests" to "src compiles + 4 adapter end-to-end golden traces". Confidence in cross-adapter changes (e.g. recorder.py refactor, ADR-016 evolution) increases dramatically. **Foundation work** — not user-facing, but unblocks Phase 5+ ambition.

**Slot budget**: 6-8 slots (1 capture infra + 4 per-adapter capture/replay/test + 1 ratchet + 1 polish/release).

**Dependencies on Phase 4 work**: medium — needs each adapter's stream surface stable. anthropic_agents is freshly stable (R85+R87 fixed); others have been stable since Phase 3.

---

### 1.3 Arc E — 5th adapter

**Pitch**: Extend the adapter matrix from 4 to 5. Candidates from R68/R69 deferred set: **Pydantic AI** (low-risk, type-safe), **Letta** (memory-first, ambitious), **LlamaIndex agents** (large-ecosystem, mature), **AG2** (AutoGen fork), **CrewAI Flows v2** (workflow-graph successor to CrewAI tasks).

**State at R90**:

- **Pydantic AI** — Marked "Arc B slice 2 candidate" in ADR-026 §"Pre-authorised fallback" tail and roadmap §4.2. Lowest-risk option: type-safe, narrow-scope, one obvious recorder seam (`Agent.run_stream`). Likely 3-4 slot adapter.
- **Letta** — Memory-first agents, server/client split. Higher risk: opaque server-side memory, fork semantics unclear (would replay client-side, server memory diverges). 6-8 slot project.
- **LlamaIndex agents** — Mature, widely-adopted, but recorder seam is in flux (LlamaIndex agents API changed significantly between versions). 5-6 slot project, version-pin headache risk.
- **AG2** — Fork of AutoGen with own roadmap. Risk: depends on whether AG2 has diverged from AutoGen's event surface enough to need separate work, or whether the existing AutoGen adapter (ADR-017) can be parametrised.
- **CrewAI Flows v2** — A different surface within the CrewAI org; would extend the existing crewai adapter rather than be a 5th separate adapter. Lower-leverage given crewai is already shipped.

**ADR-016 compatibility**: depends on candidate. Pydantic AI / LlamaIndex / AG2 — straightforward. Letta — needs new "remote-state-aware" extension to ADR-016 (formal ADR work).

**Slice sketch** (depending on candidate; **Pydantic AI assumed below as most likely choice if Arc E selected**):

- Slice 1 — `src/chronos/adapters/pydantic_ai/` package + recorder + 1 unit test corpus + dogfood + live-smoke (paralleling R70-R72 anthropic_agents kickoff).
- Slice 2 — Fork primitive (paralleling R75-R83 anthropic_agents fork chain).
- Slice 3 — Tool-call instrumentation (paralleling R85-R87 anthropic_agents tool-call work).
- Slice 4 — GA cut as v0.8.0.

**Risks**:

- (R-1) **Marginal value at adapter #5** — going from 0 to 1 adapter (LangGraph, R4) created the project; from 1 to 2 (linear ref, R28) validated ADR-016; from 2 to 3 (CrewAI, R52-R55) demonstrated the third pattern; from 3 to 4 (anthropic_agents, R70-R88) opened the MCP segment. Going from 4 to 5 adds breadth but no new capability dimension. **Diminishing returns axis.**
- (R-2) Maintenance burden — every adapter is an SDK-version-pin liability (R22 CrewAI version-bump ADR; R26 anthropic_agents `>=0.1.80,<1.0` pin). 5 adapters = 5 SDK upgrade vectors per quarter.
- (R-3) Distraction from depth work — Arc C (replay UI) is the hero feature; Arc D (golden traces) is foundation; Arc E ties up budget for breadth that isn't asked for.

**Leverage story**: **Weak** in absence of an external user pulling for a specific framework. Unless a Pydantic AI user shows up (none has, per R88 CONTEXT §0), Arc E is exploration not execution. Same logic that deferred Arc C in Phase 4 (ADR-023 demand-driven test) applies.

**Slot budget**: 5-7 slots for Pydantic AI; 7-10 for Letta; 6-8 for LlamaIndex.

**Dependencies on Phase 4 work**: low — adapter pattern is stable, just need to pick a candidate.

---

### 1.4 Arc F — Recorder-seam refactor (heavy R85 Option (b))

**Pitch**: Implement the deferred R85 Option (b) — split per-block events in `anthropic_agents` recorder into separate Nodes (one Node per `ToolUseBlock`/`ToolResultBlock` instead of one Node per Message), introducing a new `kind=TOOL` node-class and breaking the "one Node = one envelope" invariant codified in R89's contracts doc.

**State at R90**:

- ADR-026 §6 AC-2 closed at R89 via Option (a) — document the envelope-determines-kind rule as intentional. Option (b) was explicitly NOT chosen because of post-GA breaking-change cost asymmetry (1 round md vs 6+ rounds impl + alpha→GA).
- R89 R-3 ("Cost asymmetry") quantified: (b) = ADR-027 + per-block split refactor + R76/R77 `tool_use_id`/`tool_use_ids` re-stamp logic + 30+ test rewrites + dogfood updates + alpha→GA cycle for v0.8.0.

**ADR-016 compatibility**: ⚠️ **breaking** — node-count for any tool-using run multiplies; diff invariants change; replay storage shape changes; external tooling assumptions break. The R89 contract doc would need a major revision in the same round.

**Slice sketch**: irrelevant — covered by ADR-027 if chosen.

**Risks**:

- (R-1) Schema migration — existing v0.7.0 stored Runs would need an upgrade path, OR be marked legacy-readable-only. SQLite schema bump (ADR-003 was last revised in M1.3).
- (R-2) Cross-adapter generalisation — would the same per-block split apply to LangGraph multi-output checkpoints? CrewAI multi-step crew? AutoGen agent-of-agents? Arc F's per-adapter scope is not obvious.
- (R-3) Demand signal — **zero**. R85/R89 finding is a contract observation, not a user complaint. No round (R85, R86, R87, R88, R89) has surfaced a user-visible gap.

**Leverage story**: **none** in absence of explicit user mandate. Per R89 §3.D-1, the asymmetry is so stark (~$0.01 vs ~6 rounds × ~$X) that Arc F becomes pure tech-debt repayment without a forcing function.

**Slot budget**: 8-12 slots (ADR + spike + per-adapter eval + impl + alpha + GA).

**Dependencies on Phase 4 work**: high — touches the just-stabilised v0.7.0 recorder and contracts doc.

---

## 2. Comparison matrix (9 axes)

| Axis | Arc C (Replay UI) | Arc D (Golden traces) | Arc E (5th adapter) | Arc F (Recorder refactor) |
|---|---|---|---|---|
| **Slot budget (rough)** | 4-5 | 6-8 | 5-7 | 8-12 |
| **External-user attractor** | 🟢 strong (hero feature) | 🟡 indirect (CI confidence) | 🟡 narrow (per-framework only) | 🔴 none |
| **Capability-axis novelty** | 🟢 new (interactive replay) | 🟡 new (deterministic CI) | 🔴 same (more breadth, no new shape) | 🔴 none (refactor) |
| **Risk class** | medium (frontend visual review) | medium (capture sanitisation, version drift) | low-medium (SDK pin, depending on candidate) | high (breaking schema, low demand) |
| **Phase 4 dependency** | low (read-path stable) | medium (per-adapter stream stable) | low (pattern stable) | high (touches just-stabilised contracts) |
| **Demand-driven?** | leverage-driven | foundation-driven | leverage-driven | none |
| **Reverses-recently-made-decision?** | no | no | no | **yes** (R89 chose Option (a), Arc F is Option (b)) |
| **Unlocks downstream?** | enables shareable demo links, marketing | enables aggressive recorder refactors | enables narrower SDK targeting | only enables itself |
| **Demo-able to first external user** | 🟢 yes — single browser URL | 🔴 no — internal only | 🟡 partial — only if user wants that exact framework | 🔴 no |

### 2.1 Hero-axis ranking

Sorted by external-user-attractor score (per ADR-023 leverage-driven principle):

1. **Arc C** (Replay UI) — strong attractor. The "Chronos" name pays off for the first time when users can **see** time-travel through reasoning.
2. **Arc D** (Golden traces) — indirect attractor. Internal CI win, but invisible to external users until they hit a regression that didn't ship because Arc D caught it.
3. **Arc E** (5th adapter) — narrow attractor. Only attracts Pydantic AI (or whichever candidate) users specifically; cap on 4-adapter audience grows.
4. **Arc F** (Refactor) — no attractor.

### 2.2 Foundation-axis ranking

Sorted by "what does this unlock for the next 5 phases":

1. **Arc D** — golden traces unlock aggressive recorder refactors (incl. Arc F if ever needed), unblock relay-flake-resilient releases (R86 lesson), enable contributor onboarding (anyone can run all tests offline).
2. **Arc C** — unlocks shareable demo links (marketing), unlocks `chronos-share` future feature (LAN-share traces, currently Arc C deferred in roadmap §4.2).
3. **Arc E** — unlocks specific framework's user segment.
4. **Arc F** — unlocks only itself.

---

## 3. Decision rationale (recommendation)

### 3.1 Recommended primary: **Arc C (Replay UI)**

Three independent reasons converge:

**Reason 1 — hero feature status.** Phase 1-4 has built the *capability* (record, fork, diff, multi-pivot, golden-pair-compare, fork-tree viz) but the *demo experience* lags. A user dropping into the project today sees a CLI, a static tree viewer, and a node-details drawer — but cannot **step through** a recorded conversation. The Chronos name promises time-travel; Arc C delivers it. This is the marquee deliverable that finally makes the project demo-able in a 60-second screen-share.

**Reason 2 — leverage-driven over demand-driven (ADR-023 echo).** Phase 5 has zero external users (per R88 CONTEXT §0). The same logic that picked Arc A over Arc C in Phase 4 (ADR-023 §"Why Arc A over Arc C") now picks Arc C in Phase 5: with no demand signal, pick the work most likely to **create** demand. A working interactive replay viewer is the single highest-leverage attractor.

**Reason 3 — riskpool balance.** Arc C has medium risk (frontend visual review forcing function applies), but the risk surface is bounded — frontend bundle, state-evolution rendering, animation cost. All three are routine. Arc D's risk surface is unbounded — capture sanitisation, version drift, per-adapter capture infra cost. Arc E's risk is low but capability axis is empty. Arc F's risk is high and demand zero. **Arc C has the best risk-to-leverage ratio.**

### 3.2 Hot-backup: **Arc D (Golden traces)**

Pre-authorised fallback if Arc C slice 1 spike (frontend integration test on a 20-node recorded run) reveals an unexpected blocker — e.g. ReactFlow performance collapse on long timelines, or `usePlayback` hook fundamentally incompatible with state-evolution rendering. Arc D would then become the active arc and Arc C deferred to v0.9.0. Switch criterion: **Arc C slice 1 spike fails**, OR **Arc D becomes blocking for a release** (e.g. AC-3-style relay flake re-occurs and blocks v0.7.x patch release).

This is the same disprover-first / spike-first cadence used at R69 (Arc B) and R73 (R69 disprover refutation). The spike runs in **R91 slot 1 of Arc C**, before any production code is written.

### 3.3 Defer Arc E and Arc F

- **Arc E** — defer to Phase 6 (post-Arc-C). Pydantic AI is the most likely re-pick at that time (lowest risk, type-safety story is on-trend). Re-evaluate when external user shows up OR when Arc C / Arc D have shipped and budget opens up.
- **Arc F** — defer indefinitely. R89 already decided Option (a) over (b); Arc F would reverse that decision without new evidence. Re-open only if a user explicitly requests per-block tool-node granularity, or if a downstream tool integration breaks because of envelope-Node coupling.

### 3.4 What's explicitly NOT a Phase 5 candidate

These were all considered and dismissed in the inventory phase, included here for transparency:

- Public marketing site / demo deployment — Arc C territory adjacency, but pre-mature without Arc C shipping first.
- Cloud-hosted SaaS (Phase 5+ roadmap stub) — premature; needs Arc C and Arc D + an external user before commercial scaffolding makes sense.
- Plugin system for custom diff / redaction (roadmap §4.3 deferred plumbing) — demand-driven; no demand signal.
- Determinism modes (stable/explore/custom) — Phase 3 deferred; no demand signal; one adapter's seed/temp policy ≠ universal abstraction.
- Semantic diff (LLM-as-judge) — Phase 4 deferred; needs trust-model ADR; budget heavy for unclear value.
- Dependency-aware partial fork — Phase 4 deferred; needs per-node purity annotation; budget heavy for unclear value.

---

## 4. Arc C slice-by-slice rollout (recommended primary)

If ADR-027 picks Arc C (recommended), the next 4-5 rounds follow this slice plan.

### Slice 1 — Replay core (R91, single slot — spike-first)

**Goal**: prove ReactFlow + a linear playback timeline can render a 20-node recorded run with smooth keyboard navigation, no animation jank, and bundle size under 600 KB gzipped.

**Spike script**: `tests/spikes/spike15_replay_perf.py` (loads `scripts/seed_demo.py` data, opens `chronos web`, browser_vision smoke).

**Deliverable**: `frontend/src/pages/Replay.tsx` (~150 LOC), `frontend/src/components/PlaybackTimeline.tsx` (~80 LOC), keyboard handler hook reuse from `usePlayback` (R36-D). Manual browser_vision pass (R37.5 forcing function).

**Exit criteria**: replay through the 20-node seed_demo run smoothly; bundle delta ≤ +50 KB raw.

**Rollback gate**: if perf collapses on 20-node run OR `usePlayback` needs major rework, spike fails → Arc D becomes active (R92).

### Slice 2 — State-evolution side panel (R92, 2 slots)

**Goal**: when stepping through nodes, render `state_after` diff between previous and current node in a side panel. Per-adapter `formatState` hook for adapter-specific rendering (e.g. anthropic_agents `state_after.blocks[i].block` per-block fan-out).

**Deliverable**: `frontend/src/components/StatePanel.tsx`, `formatState` registry in `frontend/src/adapters/`, default `react-json-view` fallback.

**Exit criteria**: state diff visible for all 4 first-class adapters' seed_demo runs.

### Slice 3 — Fork-tree replay mode (R93-R94, 2 slots)

**Goal**: replay through a fork's parent → diverge-point highlight → child branch replay. Reuse TreeView lane layout.

**Deliverable**: extend `Replay.tsx` with fork-tree mode toggle; integrate with TreeView's existing layout hooks (`frontend/src/layout.ts`); diverge-point ring highlight.

### Slice 4 — URL-shareable state (R95, 1 slot)

**Goal**: `#/runs/<id>/replay?step=N&fork=<fork_id>` deep-linking + clipboard copy.

**Deliverable**: hash-router state sync; copy-link button; landing-page CTA.

### Slice 5 (stretch) — Diff-aware lockstep replay (R96-R97, 2 slots)

**Goal**: when comparing two runs (R65 matrix view), step both in lockstep with diverging-node call-out.

**Deliverable**: `Replay.tsx` accepts comma-separated run IDs; lockstep playback; visual diverge marker.

### Slice 6 — Polish + dogfood + v0.8.0 cut (R98, 1 slot)

**Goal**: release-pattern checklist + dogfood pass (R37.5 visual review) + CHANGELOG roll + v0.8.0 tag + GitHub Release.

---

## 5. Cost outlook for Phase 5 first arc

| Arc | Round count | Total slot budget | Live-LLM cost | Frontend bundle delta | Schema delta |
|---|---|---|---|---|---|
| Arc C (Replay UI) | 6 rounds (R91-R98 across 4-5 slices) | 4-5 + dogfood | $0 (read-only) | +50-150 KB raw | none |
| Arc D (Golden traces) | 7-8 rounds | 6-8 + ratchet | $0.50-2 (one capture per adapter) | none | none |
| Arc E (Pydantic AI) | 5-7 rounds | 5-7 | $0.20-1 (live-smoke) | none | none |
| Arc F (Refactor) | 8-12 rounds | 8-12 + alpha | $0.20-1 (re-validation) | possibly | **bump** |

Arc C is cheapest by relay-cost, second-cheapest by total slot, and only Arc D rivals it on schema-stability.

---

## 6. Process invariants R91+ must honor

Inherited from Phase 4, still binding:

- **Pre-flight remote-state check** (R88 codified): always `git fetch` first; verify all 5 hard-prereqs at R91+ slot start.
- **Aspirational-release-doc trap detector** (`cron-slot-handoff-recovery`, R88 refinement): 7-row diagnostic table for any inherited release claim.
- **Disprover-first** (R73 invariant): Arc C slice 1 spike runs before slice 2+ commits.
- **Strict-xfail forcing function** (R76→R80 pattern): Arc C slices that introduce new behaviour write strict-xfail tests against not-yet-existing UI.
- **Visual review forcing function** (R37.5, `dogfood`/`visual-review-loop` skills): every Arc C slice ends with `chronos web` + browser_vision before progress doc.
- **2-slot pre-budget for impl rounds** (R48-A→R89 = 13-round inheritance chain): R92, R93-R94, R96-R97 each get 2-slot pre-budget.
- **No retroactive AC unratchet on relay flake** (R86 invariant): Arc C does not interact with relay; AC-3-style flakes don't apply.
- **Docs-only round = cadence-restorer** (R89 NEW): after Arc C slice 6 (release), schedule R99 as a docs-polish round.
- **Tool-call iteration budget — commit early, not last** (R69/R71 lessons): Arc C frontend rounds have high write_file/patch volume; commit per-component as gates green.

### New for Phase 5

- **Arc switch criterion**: if Arc C slice 1 (R91) spike fails, ADR-027 amendment switches to Arc D in same slot. Document the switch in R91 progress doc + ADR-027 §"Outcome of slice 1 spike".
- **Frontend bundle budget**: Arc C target is ≤ 600 KB gzipped at v0.8.0. Track delta in each slice's progress doc.
- **Adapter-zero-regression streak continues**: Arc C does NOT touch any adapter or recorder code. Streak R52→R89 = 37 rounds; Arc C extends it.

---

## 7. Recommendation summary

**Recommended primary**: Arc C (Replay UI), 4-5 slot budget, R91-R98, target v0.8.0.

**Pre-authorised fallback**: Arc D (Golden traces), activated if Arc C slice 1 spike fails OR if a relay-flake outage blocks a v0.7.x patch release.

**Deferred**: Arc E (Phase 6 candidate, Pydantic AI most likely), Arc F (defer indefinitely without explicit user mandate).

ADR-027 commits this in Draft status (R90), to be promoted to Accepted in R91 after the slice 1 spike ratifies Arc C OR refutes it (per R57 in-place promotion rule).

---

[ADR-001]: ../decisions/ADR-001-language.md
[ADR-016]: ../decisions/ADR-016-adapter-interface.md
[ADR-019]: ../decisions/ADR-019-chronos-does-not-sandbox.md
[ADR-023]: ../decisions/ADR-023-phase-4-charter-skeleton.md
[ADR-026]: ../decisions/ADR-026-arc-b-scope.md
[ADR-027]: ../decisions/ADR-027-phase-5-arc-selection.md
[roadmap]: ../roadmap.md

— Hermes Agent, R90 cron, 2026-05-21 ~10:00 CST
