# ADR-028: Phase 5 Arc D — Cross-framework golden-trace test fixtures

**Status**: Accepted (R100, 2026-05-24 — promoted in-place per R57 rule; spike 19 GREEN 3/3, total 1.12 s, well under the 5 s budget)
**Date**: 2026-05-23 (Beijing, in-window cron R99); promoted R100 2026-05-24
**Spike-19 evidence**: `tests/spikes/spike19_golden_trace_invariants.py` (3/3 GREEN at HEAD), `tests/golden/_skeleton/expected_run.json` (595-byte canonical projection), `docs/contracts/golden-trace-format.md` (v0 spec)
**Supersedes**: nothing
**Depends on**: [ADR-016][ADR-016] (adapter `RecorderProtocol` — read-only impact), [ADR-027][ADR-027] (Phase 5 charter — Arc D was pre-authorised hot-backup, now promoted to second-arc primary), [ADR-001][ADR-001] (Python 3.11+ pin)
**Related**: [ADR-026][ADR-026] (Arc B Anthropic Agents adapter — primary seed-adapter candidate after AC-3 relay-flake history), [docs/contracts/adapter-protocol.md][contract] (Arc D builds on this contract — recorder-side regression net)
**Feeds**: [docs/research/r90-phase-5-arc-survey.md][research] §1.2 (Arc D pitch), [docs/roadmap.md][roadmap] §"Phase 5 — second arc"

---

## Context

Phase 5 first arc (Arc C — Replay UI) shipped end-to-end as **v0.8.0 GA at R98** (slices 1–5 across R92→R97, release-engineering at R98). With Arc C now closed, Phase 5 needs its **second arc**. ADR-027 §6 names Arc D as the pre-authorised hot-backup; with Arc C succeeding rather than failing, Arc D no longer activates *via the fallback clause* — instead it becomes the **natural second-arc primary** for the remainder of Phase 5, targeting **v0.9.0**.

R98 F-1 (the `uv run --no-sync` post-bump trap) was already codified into the `chronos-release-pattern` skill at R98 close-out — the operational lesson is captured; what remains is *strategic* pre-Arc-D scoping work, which this ADR is.

The R90 research survey ([r90-phase-5-arc-survey.md][research] §1.2) sketched Arc D's pitch:

> Build a deterministic regression layer: capture canonical recorded JSONL traces from each of the 4 first-class adapters (langgraph, autogen, crewai, anthropic_agents) and assert the recorder + fork primitive correctness against fakes that replay the captured envelopes. Result: every CI run verifies all 4 adapters' end-to-end behaviour without `CHRONOS_LIVE=1` or any LLM relay.

R86 demonstrated the *cost* of NOT having Arc D: a relay-degradation-driven regression in `anthropic_agents` had no CI signal because that adapter is `CHRONOS_LIVE=1`-gated, so the failure surfaced in the dogfood round and consumed a full slot of confusion + recovery. Arc D's **leverage story** is preventing repeats of R86 across all live-gated adapters.

This ADR commits Phase 5 second-arc scope, picks the seed adapter, fixes the fixture layout, and decides between two competing tooling shapes (CLI verb vs. pytest plugin).

### What's different from ADR-027

ADR-027 is a hero-feature arc — user-visible, frontend-heavy, single-arc release (v0.8.0). ADR-028 is a **foundation arc** — test-only, no user-visible surface, designed to grow incrementally over multiple minor releases (v0.9.0 seeds the structure, v0.10.0+ ratchets coverage). Arc D's slot budget (per R90 survey) is 6–8 slots; ADR-028 commits to **only the first 3 slots** (capture infra + first seed adapter end-to-end + tooling shape) under v0.9.0, with explicit re-scoping at the v0.9.0 cut for whether to extend coverage to the remaining 3 adapters under v0.9.1 or treat it as a slow-grow corpus.

---

## Decision

**Phase 5 second-arc target: Arc D — Cross-framework golden-trace test fixtures.** Three-slice rollout R100→R102 (v0.9.0 seed), with `langgraph` as the seed adapter and a **dedicated CLI verb** (`chronos verify-golden`) as the tooling shape. v0.10.0+ ratchets coverage to the remaining 3 first-class adapters.

### 1. Primary binding

- **Arc**: Arc D — golden-trace fixtures.
- **Seed adapter**: **`langgraph`** — picked as seed despite `anthropic_agents` having the higher *operational* leverage (relay-flake mitigation per R86 lesson), because:
  1. **Lowest variance per round**: langgraph already runs deterministically in CI under `chronos-langgraph-test` matrix; its envelope shape (checkpointer events) is the most stable across SDK versions and the recorder integration is the most-tested.
  2. **R52→R98 zero-regression streak (46 rounds)** means there's no live ambiguity about what "correct recorded behaviour" looks like for langgraph — making golden-trace authoring a pure data-capture round, not a behaviour-debate round.
  3. **Anthropic Agents seed deferred to slice 4+**: per R90 survey §1.2 R-3 risk note, the per-adapter capture infra cost differs by adapter; `anthropic_agents` is the highest-payoff *target* but also the trickiest *capture* (live SDK + sanitisation + sub-iterator framing). Tackling it second-or-later, after the langgraph-shaped pattern is proven, reduces the round budget needed.
  4. **Path-of-least-surprise alignment**: Arc C's spike 16/17/18 (R92/R93/R95) all used langgraph as the primary fixture seed. Arc D continuing this convention keeps the test corpus mentally coherent.
- **Backend impact**: ZERO new HTTP endpoints. Arc D operates against existing storage (`SqliteStore`) via in-process replay; no `chronos web` surface change.
- **Adapter impact**: ZERO production-code change to `src/chronos/adapters/*`. Adapter zero-regression streak preservation is an explicit ADR-028 invariant. (Test-only adapter shims under `tests/fakes/<adapter>/` are NOT adapter code.)
- **Schema impact**: ZERO. SqliteStore round-trip is read-only against existing tables; no new tables, no migrations.
- **Distribution impact**: minimal — fixtures (`tests/fixtures/golden_traces/...`) ship inside the repo; no PyPI distribution change. The new `chronos verify-golden` CLI verb is a developer/CI tool, not a user-facing feature (excluded from `chronos --help` short-form per ADR-028 §3).

### 2. Definitions — what is a "golden trace"?

A **golden trace** for chronos-agent has two layers, recorded as a tuple:

1. **Capture layer** (input): a JSONL file at `tests/fixtures/golden_traces/<adapter>/<scenario>/envelopes.jsonl`, each line a sanitised SDK-level event (e.g. for langgraph: a checkpointer event; for anthropic_agents: a `ClaudeSDKClient.query()`-yielded message). The capture is what a `FakeRuntime` will replay back into the adapter under test.
2. **Expected-output layer** (oracle): a JSON file at `tests/fixtures/golden_traces/<adapter>/<scenario>/expected_run.json`, containing the canonical `Run` projection (run id stripped + replaced with `__GOLDEN__`, timestamps normalised to `T0/T0+1/...`, node count / node kinds / node names / per-node `state_after` shape). Plus an `assertions.yaml` companion file declaring which fields are *strict-equal*, which are *shape-only*, and which are *ignored* (typically `run_id`, real timestamps, hardware-dependent payload sizes).

A golden trace is **passing** iff: replaying the capture layer through the recorder via the per-adapter `FakeRuntime` produces a `Run` that, when compared to the expected-output layer under `assertions.yaml`, has zero strict-equal mismatches and zero shape mismatches.

This two-layer split is what distinguishes *recorded behaviour* (what the adapter does given an SDK event stream) from *captured input* (what the SDK would have emitted in some past CI run). A drift in either layer surfaces as a test failure with a clear diagnostic, not a single opaque "diff".

### 3. Tooling shape — `chronos verify-golden` CLI verb (vs. pytest plugin)

ADR-028 picks **CLI verb** over pytest plugin, after the trade-off analysis below. Decision rationale:

| Axis | CLI verb (`chronos verify-golden`) | pytest plugin (`@chronos.golden`) |
|---|---|---|
| **Discoverability** | `chronos --help` lists it; greppable from `pyproject.toml` | Hidden inside pytest config; discovery requires reading `conftest.py` |
| **CI integration** | One-line invocation in any CI; `chronos verify-golden --adapter langgraph` | pytest already in CI but golden tests live alongside other unit tests, hard to filter |
| **Fixture authoring** | `chronos verify-golden --record --adapter langgraph --scenario simple_chat` writes a new fixture pair | pytest plugin needs custom `--save-golden` flag; gets buried in pytest's plugin matrix |
| **Diagnostic output** | Custom rich-text diff renderer (chronos owns the format) | pytest's `assert` diff (less control) |
| **Coverage with existing pytest** | `chronos verify-golden` *can be wrapped* by a `tests/golden/test_<adapter>_golden.py` shim (one-line `subprocess.run`) for pytest matrix integration | Native — no shim needed, but you can't easily run goldens *without* pytest |
| **Auth boundary for `--record` mode** | Explicit `CHRONOS_LIVE=1` env opt-in, audit trail in `chronos --version` log | Requires custom `pytest.mark.skipif` boilerplate in every fixture |
| **Reusable for non-CI use** | Yes — devs run `chronos verify-golden` locally during fixture authoring | Awkward — requires `pytest tests/golden/...` invocation with implicit env |
| **R57 in-place ADR promotion** | CLI verb is a *new sub-command*, additive — easier to ship under Draft→Accepted promotion | pytest plugin is invasive (modifies `conftest.py` discovery); harder to ship as Draft |

**Decision: CLI verb wins** on 6 of 8 axes. The pytest plugin's only advantage (no shim needed) is offset by losing flexibility everywhere else. Slice 3 (R102) ships a thin `tests/golden/test_<adapter>_golden.py` pytest shim that calls `chronos verify-golden` via `subprocess.run`, giving us the best of both worlds: a chronos-native CLI tool + pytest matrix integration.

A separate research doc (`docs/research/r99-arc-d-tooling-survey.md`) is **not** authored at R99 — the table above and the R90 survey §1.2 sketch are sufficient. If a tooling-shape pivot is forced later (e.g. CLI verb proves brittle), R102 progress doc records the pivot via ADR-028 amendment.

### 4. Slice plan

Three slices, R100→R102, each one slot pre-budget (matching ADR-027 §2 single-slot rows). Slot-2 fallback per `cron-slot-handoff-recovery` skill if any slice caps before close-out.

| Slice | Round(s) | Goal | Deliverable | Slot budget |
|---|---|---|---|---|
| 1 | R100 | Spike 19 + capture-infra spike + fixture layout commit | `tests/spikes/spike19_golden_trace_roundtrip.py` (3 invariants), `tests/fixtures/golden_traces/.gitkeep`, `scripts/capture/.gitkeep`, `docs/contracts/golden-trace-format.md` (NEW — fixture file format spec, replaces `assertions.yaml` schema lookup) | 1 (spike-first) |
| 2 | R101 | First seed fixture: `langgraph/simple_chat/` end-to-end | `scripts/capture/capture_langgraph.py` (~80 LOC), `tests/fakes/langgraph/replay.py` (~120 LOC), 1 envelope JSONL + 1 `expected_run.json` + 1 `assertions.yaml` for `simple_chat` scenario | 1 |
| 3 | R102 | `chronos verify-golden` CLI verb + pytest shim + v0.9.0 cut | `src/chronos/cli/verify_golden.py` (~140 LOC), `tests/golden/test_langgraph_golden.py` shim (~30 LOC), CHANGELOG entry, version bump 0.8.0→0.9.0, tag + Release | 1 |

Total: 3 impl rounds + 1 release-engineering round (R102 bundles release-cut). Per ADR-027 lesson, A2 close-out fallback applies if any single slot caps.

**Coverage extension to remaining adapters (autogen, crewai, anthropic_agents)** is OUT OF SCOPE for v0.9.0 / Arc D first three slices. Per R90 survey §1.2 R-3, each additional adapter is a sub-round of Slice 2 + Slice 3 pattern; budget for those is 4–6 additional slots and explicitly re-scoped at v0.9.0 cut (probably v0.10.0 milestone).

### 5. Acceptance criteria

For Arc D first three slices as a whole (gates v0.9.0 cut):

- **AC-1**: `chronos verify-golden --adapter langgraph` exits 0 against the `simple_chat` golden trace fixture pair shipped in slice 2.
- **AC-2**: `chronos verify-golden --adapter langgraph --record --scenario new_scenario` produces a *new* fixture pair under `tests/fixtures/golden_traces/langgraph/new_scenario/` containing JSONL capture + `expected_run.json` + `assertions.yaml`. The recorded fixture roundtrips green on a subsequent `verify-golden` run (idempotency).
- **AC-3**: Captured JSONL contains zero secrets — sanitiser test in spike 19 demonstrates `ANTHROPIC_API_KEY=...`, `OPENAI_API_KEY=...`, real tool docstrings get redacted before the JSONL writes. (Even though slice 2 ships only `langgraph` which doesn't use those keys directly, the sanitiser hook is wired in slice 1 to be ready for slice 4+ adapters.)
- **AC-4**: `tests/golden/test_langgraph_golden.py` runs in pytest matrix as a green test on a fresh CI environment with no `CHRONOS_LIVE=1` env. Adds ≤2 seconds to total pytest runtime.
- **AC-5**: `pytest -q --no-cov` baseline 648/9/0/0 (post-R98) extends to **649+/9/0/0** (one new green test in `tests/golden/`), with no skipped goldens.
- **AC-6**: Adapter zero-regression streak R52→R102 = **50 rounds** preserved. (No `src/chronos/adapters/*` files modified across slices 1–3.)

### 6. Out of scope (explicit non-goals for Arc D first three slices)

- **No new adapter** — Arc E (5th adapter) remains Phase 6+.
- **No SDK version-pin bumps** — capture format is allowed to break across major SDK upgrades; recapture procedure documented in `chronos-release-pattern` skill addition (slice 3 close-out follow-up). No v0.9.0 commitment to back-compat across `langgraph` major bumps.
- **No semantic-diff golden assertions** — `assertions.yaml` is shape + strict-equal only. LLM-as-judge stays Phase 6+.
- **No cross-adapter golden** (e.g. "same scenario across two adapters should produce shape-equivalent run") — Arc D sticks to per-adapter goldens.
- **No fork-trace goldens** — slice 2 covers linear scenarios only. Fork-replay goldens deferred to v0.10.0+ once linear fixtures prove stable.
- **No public capture corpus** — fixtures ship inside the private repo; no separate CDN/storage. Per R90 hard-constraint "private repo only".
- **No GUI fixture browser** — `chronos web` does NOT gain a "browse goldens" page in v0.9.0. Pure CLI + pytest workflow.

### 7. Risks and mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| **Spike 19 reveals SqliteStore round-trip is non-deterministic** (e.g. dict iteration order in serialised state, timestamp precision drift) | medium | Spike 19 invariant 2 explicitly tests determinism; `assertions.yaml` ignore-list absorbs known non-determinisms; if spike 19 blows up, defer to ADR-028 amendment with concrete failure mode rather than press on |
| **`FakeRuntime` for langgraph turns out to be more invasive than 120 LOC** | medium | Slice 2 has 1-slot pre-budget; if cap hits, A2 close-out per `cron-slot-handoff-recovery` skill. Hard escalation: if slice 2 takes >2 slots, ADR-028 amends to defer langgraph and pivot seed-adapter to `linear` (toy adapter from R28, simplest possible recorder integration) |
| **CLI verb overlaps with existing `chronos replay` semantics** | low | `verify-golden` is a separate verb with `--record` and `--adapter <name>` flags; collision avoided by naming + namespace |
| **Sanitiser regex incomplete** (e.g. misses a new SDK secret format) | medium | Spike 19 invariant 3 is sanitiser regex audit; add manual review checklist to slice 2 close-out; capture commits get explicit `git diff` review per R90 R-2 mitigation |
| **Adapter regression from test-only fakes** | very low | `tests/fakes/<adapter>/replay.py` is test-only; no import path crosses into `src/chronos/adapters/*`. Adapter zero-regression streak preserved by ADR-028 §1 invariant |
| **CHANGELOG bloat from many goldens** | low | Each adapter+scenario pair gets ONE bullet line in `[Unreleased]` Added section; if corpus grows past 20 fixtures, switch to summary-only entries |

### 8. Fallback clause

If R100 spike 19 fails any of its 3 invariants (round-trip determinism, projection stability, sanitiser audit), ADR-028 amends in-place per R57 rule:

- **Spike 19 invariant 1 fail (round-trip)**: defer Arc D entirely; pivot R101+ to a simpler "envelope-shape" goldens that don't require full Run reconstruction. Arc D becomes a v0.10.0 candidate, and v0.9.0 ships from a fallback small-arc (TBD at amendment time — likely the deferred ADR-016 ↔ contracts doc reorg from R90+).
- **Spike 19 invariant 2 fail (determinism)**: ignore-list expansion in `assertions.yaml` schema; possible 1-slot delay; not arc-killing.
- **Spike 19 invariant 3 fail (sanitiser)**: spike 19 itself absorbs the fix; mitigation cost is within slice 1 budget.

The amendment criterion is non-binary (unlike ADR-027 §6) — soft-fail invariants 2/3 don't kill the arc, only invariant 1 does.

### 9. Process invariants for R100–R102

Inherited from Phase 4 + Arc C (binding):

- Pre-flight remote-state check (R88, every round since).
- Aspirational-release-doc trap detector (R88, `cron-slot-handoff-recovery` skill).
- Disprover-first / spike-first (R73 + Arc C R92/R93/R95). **R100 = spike 19 round; no implementation until spike GREEN.**
- Strict-xfail forcing function (R76→R80) — applies to slice 2 if `expected_run.json` fields are added before fake replay produces them.
- 1-slot pre-budget per slice (matches ADR-027 single-slot slices 4/5).
- Tool-call iteration budget — commit early per-spike + per-fixture (R69/R71).
- Pre-commit lockfile-trap check (`git status` for `M uv.lock`).
- `uv run --no-sync` for any post-bump smoke gate (R98 F-1, codified in `chronos-release-pattern` skill).

New for Arc D (R100+):

- **Sanitiser-first capture invariant**: every capture script writes through a sanitiser hook BEFORE the JSONL is committed. The sanitiser hook is part of slice 1 spike 19 invariant 3; no fixture commits until sanitiser is green.
- **Adapter zero-change invariant** (extra strictness): R100–R102 do NOT touch `src/chronos/adapters/*` even by accident. `git diff src/chronos/adapters/` must be empty at every commit. Streak target: **50 rounds** at R102 close (R52 → R102).
- **Fixture commit-message convention**: `golden(<adapter>): <scenario> v1` for first capture, `golden(<adapter>): <scenario> v2 (sdk bump)` for recapture. Lets `git log --grep='^golden('` scan the corpus history.
- **CLI verb `--help` test**: slice 3 ships a `chronos verify-golden --help` snapshot test alongside the runtime test (catches accidental help-text regressions).
- **R57 in-place promotion at slice 1 spike GREEN**: ADR-028 stays Draft until spike 19 lands GREEN at R100; same commit promotes Status: Draft → Accepted.

---

## Spike 19 plan (executed at R100, NOT in R99)

`tests/spikes/spike19_golden_trace_roundtrip.py` — three invariants, run via `uv run --no-sync python tests/spikes/spike19_golden_trace_roundtrip.py`:

### Invariant 1 — Round-trip a synthetic golden trace through SqliteStore

- **Setup**: hand-build a 5-node `Run` object in memory (no adapter involved) with the canonical shape that langgraph's recorder would produce — `node_kind` ∈ {agent_start, llm_call, tool_use, llm_response, agent_end}, `state_after` is a small JSON dict per node.
- **Action**: `store.save_run(run)` → fresh `SqliteStore` → `store.get_run(run.id)`.
- **Assertion**: deserialised Run matches in-memory Run on (node count, node kinds in order, node names in order, per-node `state_after` deep-equal). Tolerance for: `run_id` (always-different), `created_at` (assertions.yaml ignored), `step_index` arithmetic if storage normalises it.
- **Pass criterion**: 5-node round-trip is byte-stable across 3 consecutive `save→get` cycles on the same data.

### Invariant 2 — Projection stability (golden compare with tolerance)

- **Setup**: take the round-tripped Run from invariant 1; run a candidate `project_to_golden(run)` function that emits the `expected_run.json` shape (canonical: stripped run_id, normalised timestamps, node count, kinds, names, state_after shape).
- **Action**: project twice with different `now()` clocks; assert byte-equal output.
- **Assertion**: projection is deterministic given a fixed Run (no hidden time/random dependency in the projection function itself).
- **Pass criterion**: hash of `project_to_golden(run)` JSON serialisation equals across two invocations 1 second apart.

### Invariant 3 — Sanitiser regex audit on a synthetic dirty capture

- **Setup**: hand-build a JSONL string containing 5 known-secret patterns: `sk-ant-...` (Anthropic API key), `sk-proj-...` (OpenAI), `Bearer eyJhbGc...` (JWT), `https://relay.example.com/secret-token-XYZ` (proprietary URL), and `internal_tool_xyz_v3` (proprietary tool name from a synthetic tools list).
- **Action**: pass through candidate `sanitise_capture(jsonl_str)` function from slice 1 design.
- **Assertion**: each of the 5 patterns is replaced with `<REDACTED:KIND>` markers; whitelist patterns (e.g. `node_id="abc-def"`, `state.counter=42`) are untouched.
- **Pass criterion**: 5/5 redactions successful + 0/N whitelist false-positives (where N is at least 10 benign strings in the same JSONL).

### Spike 19 perf budget

- Whole spike (3 invariants) completes in ≤ 5 seconds on a clean uv venv.
- Round-trip of a 50-node Run (stretch case) completes in ≤ 50 ms (1ms/node ceiling — generous).

If perf blows budget by >10×, slice 1 close-out adds an "AC-2 perf clause" to ADR-028; not arc-killing.

### Spike 19 → ADR-028 promotion gate

ADR-028 stays **Draft** until spike 19 commit lands with all 3 invariants GREEN. Same R100 close-out commit promotes Status: Draft → Accepted in-place per R57 rule. No separate ADR-028.1 amendment doc.

---

## Consequences

### Positive

- Project gets a **deterministic regression net** for adapter-end-to-end behaviour — the missing layer between unit tests (mocked SDK) and `CHRONOS_LIVE=1` smoke (relay-dependent, not in CI). R86-class incidents become CI-detectable, not dogfood-surface-only.
- Foundation work for Phase 6+ ambitions (Arc E 5th-adapter onboarding, recorder refactor under ADR-016 evolution) — both get a regression baseline they can develop against.
- Adapter zero-regression streak extends from R52→R98 (46) through Phase 5 second arc (≥R102, target 50).
- v0.9.0 ships a developer-facing CLI tool (`chronos verify-golden`) that doubles as fixture-authoring tooling — modest but real DX win.
- Fixture corpus grows organically — every `--record` invocation that produces a clean fixture is a CI-coverage delta.

### Negative

- 3-slot v0.9.0 budget defers Arc E (5th adapter) to Phase 6+. Acceptable tradeoff per R90 survey §3.3 diminishing-returns analysis.
- Test-only feature; no marketing/demo surface from Arc D itself. Mitigated by treating Arc D as foundation for Arc C+ user-facing demos (e.g. "look how stable our recorder is — here's the golden corpus").
- Capture-version drift (R90 R-1 risk) introduces a recurring cost: every SDK major-bump round needs a recapture pre-flight step. Mitigation lives in `chronos-release-pattern` skill (slice 3 close-out adds a sub-step).
- Single-adapter v0.9.0 corpus is *partial coverage* — only langgraph guards against R86-class regressions; anthropic_agents (the actual R86 victim) doesn't get coverage until v0.10.0+. Acceptable because v0.9.0 ships the *infrastructure* + *one validated example*, and v0.10.0 onward ratchets coverage one adapter at a time.

### Neutral / unchanged

- ADR-016 contract unchanged.
- `src/chronos/adapters/*` unchanged (zero-regression streak invariant).
- SqliteStore schema unchanged.
- Frontend (Replay UI) unchanged — Arc D is backend/CLI-only.
- v0.8.x patch line remains open for Arc C polish if needed.

---

## Outcome of slice 1 spike (to be recorded at R100)

R100 will land spike 19 + slice 1 deliverables in either a single A2 round (if budget holds) or a slot-1+slot-2 pair per `cron-slot-handoff-recovery` skill default for spike-first rounds.

Status will promote from **Draft** to **Accepted** in-place per R57 rule in the same commit as the spike-green proof + slice 1 fixture-layout commit. R100 progress doc records the spike outcome + the `Status:` line edit in the same diff.

---

[ADR-001]: ./ADR-001-language.md
[ADR-016]: ./ADR-016-adapter-interface.md
[ADR-026]: ./ADR-026-arc-b-scope.md
[ADR-027]: ./ADR-027-phase-5-arc-selection.md
[research]: ../research/r90-phase-5-arc-survey.md
[roadmap]: ../roadmap.md
[contract]: ../contracts/adapter-protocol.md

— Hermes Agent, R99 cron, 2026-05-23 ~11:55 CST
