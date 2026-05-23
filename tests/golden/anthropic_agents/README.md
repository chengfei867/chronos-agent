# tests/golden/anthropic_agents/

Per-recorder golden trace fixtures for the Anthropic Agents adapter.

## Status (R101)

**Empty.** Fixtures are not yet captured. This directory is a placeholder
established by R101 alongside `scripts/capture/capture_anthropic_agents.py`,
the offline driver that materialises golden traces from a recorded SQLite
run. No paid live capture has been authorised; populating real subdirs
(`hello/`, `tool_use/`, `mcp/`, `error/`) is planned for R102+ and
gated on the user-funded credit window described in CONTEXT §6.

The fixture **schema** is fully exercised by:

- `tests/golden/_skeleton/` — synthetic 2-node fixture used by the
  schema-only invariants in `tests/spikes/spike19_golden_trace_invariants.py`.
- `tests/unit/test_capture_anthropic_agents.py` — drives the capture
  script end-to-end against an in-memory SqliteStore with synthetic Run +
  Node rows; asserts envelope shape, sanitiser belt, golden_dumps byte
  stability, and parity with the spike 19 reference projection.

## Scenarios (target list — R102+)

| dir          | scenario                              | nodes | tools         |
|--------------|---------------------------------------|------:|---------------|
| `hello/`     | single-turn text completion           | ~2    | none          |
| `tool_use/`  | one tool round-trip (`get_weather`)   | ~5    | local stub    |
| `mcp/`       | one MCP tool call (`fetch_pr_diff`)   | ~6    | mcp__github__ |
| `error/`     | mid-turn API 429 → adapter records F  | ~3    | none          |

Each subdirectory will contain exactly two files (per ADR-028 §2):

```
tests/golden/anthropic_agents/<scenario>/
  ├── envelopes.jsonl     # one StreamEvent envelope per node, in step order
  └── expected_run.json   # canonical projection produced by golden_dumps()
```

## Capture procedure

The full procedure lives in `scripts/capture/README.md`. Quick summary:

```bash
# 1. Record a real run (requires CHRONOS_LIVE=1 + ANTHROPIC_API_KEY).
export CHRONOS_LIVE=1
chronos run \
  --adapter anthropic-agents \
  --task "Say hello in five words." \
  --db /tmp/capture.db
# → prints RUN_ID

# 2. Materialise golden trace from the recorded run.
uv run python scripts/capture/capture_anthropic_agents.py \
  --db /tmp/capture.db \
  --run-id <RUN_ID> \
  --out-dir tests/golden/anthropic_agents/hello

# 3. Hand-audit envelopes.jsonl for residual secrets, then commit.
grep -iE 'sk-ant|api[_-]?key|bearer' \
  tests/golden/anthropic_agents/hello/envelopes.jsonl  # MUST be empty
```

## Sanitiser belt

The capture driver invokes `sanitise_capture()` on every envelope's
JSON-serialised form before write (ADR-028 §3, R101). Patterns redacted:

- `sk-ant-…` Anthropic keys
- `Bearer …` headers
- `api_key=…` query/body params
- `password=…`, `secret=…`, `token=…` form fields
- AWS access/secret keys (`AKIA…`, 40-char b64)

A unit test (`test_capture_belt_redacts_anthropic_secret`) plants a
canonical `sk-ant-` key in `model_call.response_text` and asserts it is
absent from the on-disk JSONL. Hand-audit step 3 above is **belt + braces**.

## Why empty in R101

R101 closed Phase 5 Arc-D **slot 1** (driver + tests + skeleton). The
live capture step (slot 2) requires a real Anthropic API key and pays
real money — that is the only Arc-D blocker the agent cannot self-clear.
See `progress/2026-05-24-round-101.md` and CONTEXT §6 for handoff.
