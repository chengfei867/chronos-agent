# ADR-027: Phase 5 Arc Selection — Replay UI / Time-Travel Debugger Frontend (Draft)

**Status**: Draft (R90, 2026-05-21 — to be promoted to Accepted in R91 after slice 1 spike per R57 in-place promotion rule)
**Date**: 2026-05-21 (Drafted R90)
**Deciders**: chengfei867, Hermes Agent
**Supersedes**: The Phase 5 stub in [docs/roadmap.md][roadmap] §"Phase 5+" ("Vague on purpose")
**Depends on**: [ADR-016][ADR-016] (adapter interface — read-only impact), [ADR-023][ADR-023] (Phase 4 charter, leverage-driven principle), [ADR-001][ADR-001] (Python 3.11+ pin)
**Related**: [ADR-026][ADR-026] (Arc B slice 1 closed at v0.7.0), [docs/contracts/adapter-protocol.md][contract] (R89 doc — Arc C reads through this contract)
**Feeds**: [docs/research/r90-phase-5-arc-survey.md][research], [docs/roadmap.md][roadmap] §"Phase 5"

---

## Context

Phase 4 closed at v0.7.0 (Arc A R58-R67 + Arc B slice 1 R70-R88 + R89 contract polish). The roadmap's Phase 5 section was deliberately left "Vague on purpose" pending arc-selection planning. R90 is that planning round (md-only, in-window cron slot), mirroring the R68→R69 cadence that successfully scoped Arc B.

The R90 research survey ([r90-phase-5-arc-survey.md][research]) evaluated four candidate arcs along nine axes:

- **Arc C — Replay UI / Time-travel debugger interactive frontend**
- **Arc D — Cross-framework golden-trace test fixtures**
- **Arc E — 5th adapter (Pydantic AI most likely)**
- **Arc F — Recorder-seam refactor (R85 Option (b) per-block split)**

This ADR commits to a primary target and pre-authorises one fallback.

### Why commit now (R90) rather than defer

1. Phase 4 closed cleanly at v0.7.0. Without a Phase 5 charter, the next 3-6 rounds drift into ad-hoc docs/dogfood polish (cadence-restorer pattern over-applied). The R56→R57 / R67→R68 lesson: **a deferred decision is cheaper than a wrong one, but an over-deferred decision is a drift magnet.**
2. The project has zero external users (R88 CONTEXT §0 confirmed). Phase 5 is therefore **leverage-driven** — pick the work most likely to attract the first external user, not work that responds to a request that doesn't exist.
3. The Chronos brand promise is "time-travel debugger". After 90 rounds of capability work, the project still has no interactive replay surface — only a CLI replay (M1.7 R8) and a static fork-tree viewer (R34). Closing this gap is the highest-leverage attractor.

### What's different from prior arc-selection ADRs

ADR-023 (Phase 4 charter) named Arc A / Arc B / Arc C as the three Phase 4 candidates and committed to Arc A first, B second, C demand-driven. **Phase 5's "Arc C/D/E/F" naming is locally re-indexed within R90's research doc** to avoid collision — they correspond to entirely new candidates evaluated post-v0.7.0, NOT to the "Arc C plumbing" of ADR-023 (which remains demand-driven and is still deferred).

ADR-026 (Arc B scope) picked Anthropic Agents SDK from six candidates with one hot-backup (OpenAI Agents SDK). ADR-027 follows the same shape: one primary + one hot-backup + deferred set with explicit re-evaluation triggers.

---

## Decision

**Phase 5 first arc target: Arc C — Replay UI / Time-Travel Debugger Frontend.** Six-round rollout R91-R98 across 4-5 slices, bundled as v0.8.0. **Pre-authorised fallback: Arc D (Cross-framework golden-trace test fixtures)** if R91 slice 1 spike fails (see §Fallback clause below).

### 1. Primary binding

- **Arc**: Arc C — interactive replay frontend.
- **Frontend module home**: `frontend/src/pages/Replay.tsx` (sibling to `Runs.tsx`, `TreeView.tsx`).
- **Backend impact**: ZERO new endpoints. Arc C is read-only against the existing `GET /runs/{id}/tree` and `GET /runs/{id}/nodes` API surface (M1.4 + R34-A).
- **Adapter impact**: ZERO. Adapter-zero-regression streak (R52→R89 = 37 rounds) extends through Phase 5 first arc.
- **Schema impact**: ZERO. No SQLite migrations.

### 2. Slice plan

Per [research §4][research], 4-5 slices:

| Slice | Round(s) | Goal | Deliverable | Slot budget |
|---|---|---|---|---|
| 1 | R91 | Spike + replay core | `Replay.tsx`, `PlaybackTimeline.tsx`, `usePlayback` reuse | 1 (spike-first) |
| 2 | R92 | State-evolution side panel | `StatePanel.tsx`, per-adapter `formatState` registry | 2 |
| 3 | R93-R94 | Fork-tree replay mode | Fork-mode toggle, diverge-point highlight | 2 |
| 4 | R95 | URL-shareable state | Hash-router state sync, clipboard copy | 1 |
| 5 (stretch) | R96-R97 | Diff-aware lockstep replay | Lockstep two-run replay | 2 |
| 6 | R98 | Polish + dogfood + v0.8.0 cut | CHANGELOG, dogfood, tag, Release | 1 |

Total: 6-7 impl/release slots + 1 docs-cadence-restorer at R99. Stretch slice 5 may slip to v0.8.1 if budget tight.

### 3. Acceptance criteria

For Arc C as a whole (gates v0.8.0 GA):

- **AC-1**: User can step through any recorded run at `/runs/<id>/replay` with keyboard ←/→/space/q parity matching the CLI replay (M1.7).
- **AC-2**: For all 4 first-class adapters (langgraph, autogen, crewai, anthropic_agents), state-evolution panel renders correctly on each adapter's seed_demo run. `formatState` hook covers anthropic_agents per-block fan-out (R84-R85).
- **AC-3**: Replay through a fork's parent → diverge-point highlight → child branch replay works on R56 multi-fork seed data.
- **AC-4**: `#/runs/<id>/replay?step=N&fork=<fork_id>` URLs deep-link correctly; "Copy link" button puts a sharable URL on clipboard.
- **AC-5**: Browser bundle delta ≤ +150 KB raw / +50 KB gzipped vs v0.7.0 baseline (1.39 MB raw / 452 KB gzipped per R36-D). `chronos web` page loads in ≤2 s on 4× CPU throttling.
- **AC-6** (stretch): Lockstep two-run replay with diverging-node call-out works on R65 golden-pair fixtures.

### 4. Out of scope (explicit non-goals for Phase 5 first arc)

- **No new adapter**. Pydantic AI / Letta / LlamaIndex deferred to Phase 6.
- **No recorder refactor**. R85 Option (b) per-block split deferred indefinitely.
- **No public deployment**. `chronos web` runs locally; no SaaS / hosted demo / authentication layer.
- **No marketing site**. Demo-recording (screencast) acceptable; landing page deferred.
- **No collaborative replay** (multiple users in same session). Single-user only.
- **No runtime fork execution from the replay UI**. Fork creation continues through the existing `ForkPlanModal` (R46-A); replay is read-only navigation.
- **No semantic diff** (LLM-as-judge). Plain `react-json-view` deep-diff.

### 5. Risks and mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| ReactFlow perf collapse on long timelines | medium | R91 slice 1 spike runs first; rollback gate to Arc D |
| Per-adapter state-evolution rendering not generalisable | medium | per-adapter `formatState` hook; default `react-json-view` fallback |
| Frontend bundle bloat | medium | `React.lazy` per-route; AntD modular import audit; AC-5 budget gate |
| Animation jank on Framer Motion | low | already in bundle since R36-D; reuse `usePlayback` |
| Adapter regression from frontend changes | very low | Arc C touches zero adapter code; pytest baseline 648/9/0/0 unchanged |

### 6. Fallback clause

If R91 slice 1 spike (ReactFlow + 20-node seed_demo replay smoke) fails to demonstrate smooth playback OR exceeds AC-5 bundle budget by >50%, ADR-027 amends to switch the primary arc to **Arc D (Cross-framework golden-trace test fixtures)**:

- Arc D slice 1 (capture infrastructure) becomes R92 work.
- Arc D slice 2-4 follow R93-R98.
- v0.8.0 ships Arc D instead.
- Arc C revives in Phase 6 with the spike learnings as a new ADR.

The switch criterion is binary and pre-authorised — R91 progress doc records the spike outcome; if it fails, R92 opens with ADR-027 amendment + research doc supplementary §, no separate ADR-028 needed.

### 7. Process invariants for R91-R98

Inherited from Phase 4 (binding):

- Pre-flight remote-state check (R88).
- Aspirational-release-doc trap detector (R88, `cron-slot-handoff-recovery` skill).
- Disprover-first / spike-first (R73, R91 slice 1).
- Strict-xfail forcing function (R76→R80, applies to Arc C slices introducing new behaviour).
- Visual review forcing function (R37.5, `dogfood`/`visual-review-loop` skills) — applies with extra force to Arc C since it is the user-visible surface.
- 2-slot pre-budget for impl rounds (R48-A inheritance chain).
- Tool-call iteration budget — commit early per-component (R69/R71).
- Pre-commit lockfile-trap check (`git status` for `M uv.lock`).

New for R91-R98:

- **Arc switch criterion**: as in §6.
- **Frontend bundle budget**: track delta per slice in progress doc.
- **`browser_vision` checkpoints**: every Arc C slice ends with one `chronos web` + browser_vision pass before progress doc.
- **Backend regression gate**: `uv run pytest -q --no-cov` before any commit (current baseline 648/9/0/0).

---

## Consequences

### Positive

- Project gets its hero feature (interactive time-travel replay) — what the name promises.
- First demo-able external-user attractor — single-URL screen-share demo.
- Adapter-zero-regression streak extends from R52→R89 (37 rounds) through Phase 5 first arc (≥R98).
- Foundation for future deployment / share-link / marketing work in Phase 6+.
- Read-only against backend → low blast radius if anything goes wrong.

### Negative

- 4-5 slot budget defers Arc D and Arc E by one phase. AC-3-style relay-flake outages remain a release risk (mitigation: smaller live-smoke surface; relay isn't load-bearing for Arc C anyway).
- Frontend-heavy work invites a different class of regression (visual / animation / bundle-size) — visual review forcing function is the antidote.
- No new adapter for ≥6 rounds; the matrix stays at 4 first-class. Acceptable tradeoff given diminishing-returns analysis in research §1.3.

### Neutral / unchanged

- ADR-016 contract unchanged.
- R89 contracts doc (`docs/contracts/adapter-protocol.md`) unchanged.
- Recorder, replay, fork primitives all unchanged.
- v0.7.x patch line remains open for relay/docs-only fixes.

---

## Outcome of slice 1 spike (to be filled in R91)

_R91 will append this section with the spike outcome:_

- _Spike script: `tests/spikes/spike15_replay_perf.py`_
- _Outcome: ✅ pass / ❌ fail (Arc D fallback activated)_
- _Bundle delta measured: TBD_
- _Browser_vision verdict: TBD_

After spike outcome is recorded, this ADR's status promotes from Draft to Accepted in-place per R57 invariant.

---

[ADR-001]: ./ADR-001-language.md
[ADR-016]: ./ADR-016-adapter-interface.md
[ADR-023]: ./ADR-023-phase-4-charter-skeleton.md
[ADR-026]: ./ADR-026-arc-b-scope.md
[research]: ../research/r90-phase-5-arc-survey.md
[roadmap]: ../roadmap.md
[contract]: ../contracts/adapter-protocol.md

— Hermes Agent, R90 cron, 2026-05-21 ~10:00 CST
