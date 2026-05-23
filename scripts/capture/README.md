# scripts/capture/

Offline capture drivers — one per recorder — that materialise the
golden trace fixtures consumed by `tests/golden/<recorder>/<scenario>/`.

## Why a separate driver (vs. inline capture in `chronos run`)?

ADR-028 §3 keeps the recorder hot-path **fixture-agnostic**: the recorder
writes only to SqliteStore. Materialisation of golden artefacts
(`envelopes.jsonl` + `expected_run.json`) happens **out-of-band** from a
recorded DB. Benefits:

1. The recorder pays no perf tax for fixture I/O on production runs.
2. Fixtures can be re-materialised offline if the projection format
   evolves (golden_dumps is the source of truth).
3. The sanitiser belt runs at a single chokepoint — easy to audit.
4. Capture is replayable: re-running the driver on the same DB row is
   byte-deterministic (verified by `test_byte_stability_across_invocations`).

## Drivers

| script                              | recorder                               | status |
|-------------------------------------|----------------------------------------|--------|
| `capture_anthropic_agents.py`       | `chronos.adapters.anthropic_agents`    | R101   |
| `capture_langgraph.py`              | `chronos.adapters.langgraph`           | TODO   |
| `capture_crewai.py`                 | `chronos.adapters.crewai`              | TODO   |
| `capture_autogen.py`                | `chronos.adapters.autogen`             | TODO   |

## Usage

```bash
uv run python scripts/capture/capture_anthropic_agents.py \
  --db <recorded.db> \
  --run-id <UUID> \
  --out-dir tests/golden/anthropic_agents/<scenario>
```

Exit codes: `0` success, `1` usage error / runtime error, `2` DB / Run
not found.

## Sanitiser belt

The capture driver calls `sanitise_capture()` on each envelope's JSON
form before write (defence-in-depth — recorder also redacts at record
time). See `tests/golden/anthropic_agents/README.md` for the audit
checklist.

## R102 hoist plan

The driver currently in-lines small reference helpers
(`_canonicalise`, `golden_dumps`, `project_to_golden`,
`_SECRET_PATTERNS`, `sanitise_capture`) duplicated by-copy from
`tests/spikes/spike19_golden_trace_invariants.py`. A unit test
(`test_helpers_byte_match_spike_reference`) asserts byte-for-byte
parity, so the duplicates cannot silently drift. R102 will hoist
these into `src/chronos/golden/` (ADR-028 §4 slot-2 Option A) once
the live capture lands.
