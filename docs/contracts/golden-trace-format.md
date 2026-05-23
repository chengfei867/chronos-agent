# golden-trace format v0 (ADR-028 / R100)

Status: **v0 / Draft (data contract frozen at R100; CLI surface lands R102)**

This document specifies the on-disk shape of chronos golden traces — the
deterministic regression net that lets contributors prove an adapter
behaves the same way after a refactor without spending API tokens.

Companion: [ADR-028](../decisions/ADR-028-phase-5-arc-d-golden-traces.md).

## 1 Two artefacts per fixture

A golden-trace fixture is a directory containing two files:

```
tests/golden/<adapter>/<scenario>/
    envelopes.jsonl       # human-authored capture (input)
    expected_run.json     # canonical RunSummary projection (target)
```

`envelopes.jsonl` is the *capture-side* artefact — what the recording layer
emits as the agent runs, line-delimited JSON, one envelope per node /
side-effect / fork point.

`expected_run.json` is the *replay-side* target — the canonical projection
of the Run+Nodes that ``capture-replay envelopes.jsonl`` MUST produce.
Byte-equality of `golden_dumps(project_to_golden(run, nodes))` against this
file is the regression check.

Skeleton lives at `tests/golden/_skeleton/`; spike 19 round-trips it.

## 2 RunSummary projection (closed schema)

`project_to_golden(Run, list[Node]) -> dict` emits exactly these top-level
keys, in any order (canonicalised by `golden_dumps`):

| key                | type         | notes                                                         |
|--------------------|--------------|---------------------------------------------------------------|
| `schema`           | `str`        | constant `"chronos.golden/v0"`                                |
| `adapter`          | `str`        | `Run.adapter` (e.g. `langgraph`, `linear`)                    |
| `status`           | `str`        | `Run.status.value` — one of pending/running/completed/failed/forked |
| `task_description` | `str \| null`| `Run.task_description`                                        |
| `node_count`       | `int`        | `len(nodes)`                                                  |
| `node_kinds`       | `list[str]`  | `Node.kind.value` per node, ordered by `step_index`           |
| `node_names`       | `list[str]`  | `Node.node_name` per node, same order                         |
| `states_after`     | `list[obj]`  | each node's `state_after`, dict keys recursively sorted       |

This list is **closed**. Adding a key requires an ADR-028 amendment AND a
v-bump on `schema` (e.g. `chronos.golden/v1`). Spike 19 INV-2(b)/(c) gates
this.

### Stripped fields (intentional)

The projection deliberately omits:

- `Run.id`, `Node.id` (machine-minted UUIDs — non-deterministic)
- All timestamps (`started_at`, `ended_at` on Run and Node) — wall-clock
- `Node.usage` (token counts; meaningful only at live-replay time)
- `Node.cost_usd_cents`
- `Node.tool_input` / `tool_output` (TODO at v1: capture these via a
  separate canonical projection — deferred per ADR-028 §8 risk register)
- `Run.adapter_thread_id`, `Run.tags`, `Run.metadata`

Anything stripped is by design: it would couple the golden net to the
machine the test runs on, the API token budget, or transient UUID minting.

## 3 Canonical serialisation (`golden_dumps`)

```python
json.dumps(payload, sort_keys=True, indent=2) + "\n"
```

- `sort_keys=True`: belt-and-suspenders against dict-iteration drift.
- `indent=2`: matches on-disk fixture style; lets humans `git diff`
  fixture changes without a parser round-trip.
- Trailing newline: POSIX text-file convention.

`_canonicalise()` recursively rebuilds dicts with sorted keys before
serialisation, so even nested `state_after` dicts are stable across
Python versions where `dict.__iter__` semantics could in theory change.

## 4 Sanitiser

Externally contributed fixtures land via PRs. `sanitise_capture(jsonl_str)`
runs at fixture-LOAD (not record) and redacts five secret shapes:

| pattern                                            | replacement                       |
|----------------------------------------------------|-----------------------------------|
| `sk-ant-[A-Za-z0-9_-]{20,}`                        | `<REDACTED:ANTHROPIC_KEY>`        |
| `\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{20,}`        | `<REDACTED:OPENAI_KEY>`           |
| `\bBearer\s+[A-Za-z0-9._\-]{20,}`                  | `Bearer <REDACTED:BEARER_TOKEN>`  |
| `\bAKIA[0-9A-Z]{16}\b`                             | `<REDACTED:AWS_AKID>`             |
| `[?&](token\|secret\|api_key\|key)=...{16,}`       | preserves param name, redacts value |

Properties (spike 19 INV-3):

- **Idempotent**: running twice == running once (markers don't self-match).
- **Low false-positive rate**: ten benign tokens (UUID-shaped node ids,
  short strings, `claude-opus-4-7`, `Beijing`, etc.) survive intact.
- **Audit-on-load** is non-negotiable: recording hooks may evolve, but
  the load-time gate provides a single chokepoint for every fixture, no
  matter who or what produced it.

## 5 v0 → v1 evolution rules

Until `chronos.golden/v0` is deprecated:

1. ANY new top-level key in the projection requires:
   - an ADR-028 amendment listing the key, type, and rationale;
   - a `schema` field bump to `chronos.golden/v1`;
   - regen of every committed `expected_run.json`;
   - spike 19 INV-2(b) updated to the new closed set.

2. A new `NodeKind` value does NOT bump the schema — it surfaces only
   inside the existing `node_kinds` list. The closed-set property is
   about top-level keys, not enum cardinality. (Spike 19 INV-2(c).)

3. The sanitiser pattern set MAY grow without a v-bump, as long as no
   existing committed fixture's load output changes. New patterns must
   ship with a spike-19-style assertion that ten representative benign
   tokens survive.

## 6 Pointers

- Reference projection: `tests/spikes/spike19_golden_trace_invariants.py`
  (R100; hoisted to `src/chronos/golden/projection.py` at R102).
- Reference sanitiser: same file (hoisted to `src/chronos/golden/sanitise.py` at R102).
- Capture-replay CLI: `chronos verify-golden` — slice 3 (R102+) per ADR-028 §4.
- Skeleton fixture: `tests/golden/_skeleton/`.
