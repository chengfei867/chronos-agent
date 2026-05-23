"""Spike 19 (R100, Phase 5 Arc D slice 1) — golden-trace 3-invariant probe.

Per ADR-028 §"Spike 19 plan" (Draft at R99, promoted Accepted at R100 same
commit as this spike's GREEN proof per R57 in-place rule), Arc D introduces
a *deterministic regression net* for adapter end-to-end behaviour. The net
hinges on three invariants that MUST hold before any fixture authoring or
``chronos verify-golden`` CLI work proceeds (slice 2 / R101 + slice 3 / R102):

    INV-1  Round-trip byte-equality
        A synthetic envelope-ish trace projected to the canonical
        ``RunSummary`` shape (run_id stripped → ``__GOLDEN__``, timestamps
        normalised T0/T0+1/...) is byte-identical to a pre-committed
        ``expected_run.json`` after a SqliteStore round-trip.
        Failure mode: any non-determinism in projection (dict iteration,
        time field leakage, UUID re-mint) breaks this immediately.

    INV-2  Projection stability under closed field set
        ``project_to_golden(run, nodes)`` produces the same JSON byte-string
        across two invocations 1 second apart on the same Run, AND the
        top-level field set is closed — adding a new envelope (a new Node
        with a new kind value, say) MUST NOT silently introduce new top-
        level keys to the projected ``RunSummary``. Failure mode: latent
        ``**kwargs`` spread or ``model_dump()`` propagating SDK-specific
        fields into the golden contract.

    INV-3  Sanitiser audit at fixture-load
        ``sanitise_capture(jsonl_str)`` rejects/redacts known-secret patterns
        (``sk-ant-…``, ``sk-proj-…``, ``Bearer eyJ…`` JWTs, AWS-key shapes,
        proprietary URL tokens) and leaves benign tokens untouched. The
        sanitiser runs at fixture-LOAD (not record), so externally
        contributed fixtures must clear the gate.

This spike is data-contract only — no adapter code is touched. The
``project_to_golden`` reference implementation lives inline here; it will be
hoisted into ``src/chronos/golden/projection.py`` at R102 once the format
spec stabilises (per ADR-028 §4 Slice 3 / golden-trace-format.md v0).

Perf budget (ADR-028 §"Spike 19 perf budget"):
    - Whole spike (3 invariants) ≤ 5 s.
    - 50-node round-trip ≤ 50 ms (1 ms/node ceiling).

Run via:  uv run --no-sync python tests/spikes/spike19_golden_trace_invariants.py

Expected: 3/3 GREEN, perf well under budget. Any FAIL aborts ADR-028 §8
fallback clause — invariant 1 fail = arc kill (defer to v0.10.0+);
invariants 2/3 fail = soft-fail per ADR-028 §8 (1-slot fix in slice 1).
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Ensure the spike runs against the in-tree chronos package without
# requiring an editable install if the tree is already on PYTHONPATH.
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from chronos.core.models import Node, NodeKind, Run, RunStatus  # noqa: E402
from chronos.store import SqliteStore  # noqa: E402

# ---------------------------------------------------------------------------
# Reference projection (R100 inline; hoisted to chronos.golden.projection in R102)
# ---------------------------------------------------------------------------

# CLOSED field set for RunSummary projection. Adding a new envelope kind
# downstream MUST NOT change this list. Any new key requires an explicit
# ADR-028 amendment + golden-trace-format.md v-bump.
_RUN_SUMMARY_KEYS = (
    "schema",
    "adapter",
    "status",
    "task_description",
    "node_count",
    "node_kinds",
    "node_names",
    "states_after",
)
_GOLDEN_SCHEMA = "chronos.golden/v0"


def project_to_golden(run: Run, nodes: list[Node]) -> dict[str, Any]:
    """Project (Run, [Node]) -> canonical golden RunSummary dict.

    Determinism rules:
      * run_id, started_at, ended_at, node ids, per-node started_at/ended_at
        are STRIPPED (replaced with constants or omitted) — they leak machine
        state.
      * node_kinds + node_names are emitted in step_index order (same order
        as ``store.get_nodes_for_run`` returns).
      * states_after is per-node, JSON-canonicalised separately so dict
        iteration order can never sneak through (we use sort_keys=True at
        serialise time, but re-emit here as ordered dicts of canonical
        primitives).
      * Top-level keys are CLOSED to ``_RUN_SUMMARY_KEYS``. Any kwargs sneak
        is caught by the closed-set assertion in INV-2.
    """
    sorted_nodes = sorted(nodes, key=lambda n: n.step_index)
    return {
        "schema": _GOLDEN_SCHEMA,
        "adapter": run.adapter,
        "status": run.status.value,
        "task_description": run.task_description,
        "node_count": len(sorted_nodes),
        "node_kinds": [n.kind.value for n in sorted_nodes],
        "node_names": [n.node_name for n in sorted_nodes],
        # Each per-node dict is canonicalised at serialise time via
        # json.dumps(sort_keys=True).
        "states_after": [_canonicalise(n.state_after) for n in sorted_nodes],
    }


def _canonicalise(obj: Any) -> Any:
    """Recursively rebuild dicts with sorted keys; pass-through for scalars/lists."""
    if isinstance(obj, dict):
        return {k: _canonicalise(obj[k]) for k in sorted(obj.keys())}
    if isinstance(obj, list):
        return [_canonicalise(x) for x in obj]
    return obj


def golden_dumps(payload: dict[str, Any]) -> str:
    """Canonical golden serialisation: sort_keys + 2-space indent + trailing nl.

    Choice of indent=2: matches the on-disk ``expected_run.json`` format
    so the byte-equality assertion in INV-1 doesn't require a round-trip
    through a parser. ``sort_keys=True`` belt-and-suspenders against the
    in-memory canonicaliser; it enforces the contract at one more layer.
    """
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Sanitiser (R100 inline; hoisted to chronos.golden.sanitise in R102)
# ---------------------------------------------------------------------------

# Patterns chosen to match real-world secret shapes WITHOUT false-positiving
# on common benign tokens (UUID4 hex strings, langgraph node ids, etc.).
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    # Anthropic API keys: sk-ant-{api03,test}-...{40-200 chars}
    ("ANTHROPIC_KEY", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "<REDACTED:ANTHROPIC_KEY>"),
    # OpenAI / project keys: sk-proj-..., sk-... (be careful: must not eat sk-ant- substrings)
    ("OPENAI_KEY", re.compile(r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{20,}"), "<REDACTED:OPENAI_KEY>"),
    # Bearer tokens (JWT-shaped or opaque): "Bearer xxxxxxxxxxxxx..."
    ("BEARER_TOKEN", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}"), "Bearer <REDACTED:BEARER_TOKEN>"),
    # AWS access key id: AKIA + 16 uppercase alnum
    ("AWS_AKID", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<REDACTED:AWS_AKID>"),
    # Generic secret-shaped URL token query param: ?...token=<long>
    (
        "URL_TOKEN",
        re.compile(r"([?&](?:token|secret|api_key|key)=)[A-Za-z0-9._\-]{16,}"),
        r"\1<REDACTED:URL_TOKEN>",
    ),
)


def sanitise_capture(jsonl_str: str) -> str:
    """Redact known-secret patterns in a JSONL capture string.

    Idempotent: running twice produces identical output (regexes don't match
    the redaction markers themselves).
    """
    out = jsonl_str
    for _kind, rx, repl in _SECRET_PATTERNS:
        out = rx.sub(repl, out)
    return out


# ---------------------------------------------------------------------------
# Synthetic 3-envelope fixture (matches tests/golden/_skeleton/envelopes.jsonl)
# ---------------------------------------------------------------------------


def _build_synthetic_run() -> tuple[Run, list[Node]]:
    """Hand-built 3-envelope analogue: agent_start, llm, end.

    Maps to the chronos NodeKind enum (LLM/TOOL/FN/ROUTER/FORK/END):
      env0 -> kind=FN node_name='agent_start'
      env1 -> kind=LLM node_name='chat_call'
      env2 -> kind=END node_name='agent_end'
    """
    run_id = str(uuid.uuid4())
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    run = Run(
        id=run_id,
        adapter="langgraph",
        adapter_thread_id="t-spike19",
        status=RunStatus.COMPLETED,
        started_at=base,
        ended_at=base + timedelta(seconds=3),
        task_description="spike19 synthetic 3-envelope round-trip",
        initial_state={"input": "hi"},
        final_state={"output": "hello world"},
        tags=["spike19"],
        metadata={"source": "spike19"},
    )
    nodes = [
        Node(
            id=str(uuid.uuid4()),
            run_id=run_id,
            step_index=0,
            node_name="agent_start",
            kind=NodeKind.FN,
            started_at=base,
            ended_at=base + timedelta(milliseconds=10),
            state_after={"input": "hi", "tools_loaded": ["search", "lookup"]},
        ),
        Node(
            id=str(uuid.uuid4()),
            run_id=run_id,
            step_index=1,
            node_name="chat_call",
            kind=NodeKind.LLM,
            started_at=base + timedelta(seconds=1),
            ended_at=base + timedelta(seconds=2),
            state_after={"messages": [{"role": "assistant", "content": "hello world"}]},
            model_name="claude-opus-4-7",
        ),
        Node(
            id=str(uuid.uuid4()),
            run_id=run_id,
            step_index=2,
            node_name="agent_end",
            kind=NodeKind.END,
            started_at=base + timedelta(seconds=2, milliseconds=500),
            ended_at=base + timedelta(seconds=3),
            state_after={"output": "hello world"},
        ),
    ]
    return run, nodes


# ---------------------------------------------------------------------------
# Invariant 1 — round-trip byte-equality
# ---------------------------------------------------------------------------


def invariant_1_round_trip() -> None:
    """Round-trip a synthetic Run through SqliteStore → project → byte-check.

    Compare against pre-committed expected_run.json. ``__GOLDEN__`` markers
    in the expected file represent the run_id (stripped at projection time);
    the projection function never emits run_id at all, so they don't appear
    in the projected output — they're a contract reminder for human authors
    of the fixture.
    """
    run, nodes = _build_synthetic_run()
    skeleton_dir = Path(__file__).resolve().parents[1] / "golden" / "_skeleton"
    expected_path = skeleton_dir / "expected_run.json"
    assert expected_path.is_file(), (
        f"missing fixture skeleton: {expected_path} — slice 1 must commit it alongside spike 19"
    )
    expected = expected_path.read_text(encoding="utf-8")

    # Round-trip cycle 1
    with tempfile.TemporaryDirectory() as td:
        db1 = Path(td) / "rt1.db"
        with SqliteStore.open(db1) as store:
            store.put_run(run)
            for n in nodes:
                store.put_node(n)
        with SqliteStore.open(db1) as store:
            run_a = store.get_run(run.id)
            nodes_a = store.get_nodes_for_run(run.id)
        assert run_a is not None
        proj_a = project_to_golden(run_a, nodes_a)
        out_a = golden_dumps(proj_a)

    # Round-trip cycle 2 (different temp dir, same logical input)
    with tempfile.TemporaryDirectory() as td:
        db2 = Path(td) / "rt2.db"
        with SqliteStore.open(db2) as store:
            store.put_run(run)
            for n in nodes:
                store.put_node(n)
        with SqliteStore.open(db2) as store:
            run_b = store.get_run(run.id)
            nodes_b = store.get_nodes_for_run(run.id)
        assert run_b is not None
        proj_b = project_to_golden(run_b, nodes_b)
        out_b = golden_dumps(proj_b)

    assert out_a == out_b, "INV-1 sub-check: two round-trips should be byte-equal"
    assert out_a == expected, (
        "INV-1 main check: projection differs from expected_run.json — "
        f"len(out)={len(out_a)} len(expected)={len(expected)} — "
        "either fixture skeleton is stale or projection drifted"
    )


# ---------------------------------------------------------------------------
# Invariant 2 — projection stability + closed field set
# ---------------------------------------------------------------------------


def invariant_2_projection_stability() -> None:
    """(a) Two projections of the same Run, 1s apart, byte-equal.
    (b) Projected dict has EXACTLY ``_RUN_SUMMARY_KEYS`` at top level —
        no kwargs leak, no surprise SDK fields.
    (c) Adding a new Node (envelope-shape change) does NOT widen the
        top-level key set — only the existing list-shaped fields grow.
    """
    run, nodes = _build_synthetic_run()

    # (a) byte-stability across wall-clock gap
    proj_t0 = project_to_golden(run, nodes)
    out_t0 = golden_dumps(proj_t0)
    time.sleep(1.05)
    proj_t1 = project_to_golden(run, nodes)
    out_t1 = golden_dumps(proj_t1)
    assert out_t0 == out_t1, "INV-2(a): projection drifted across 1s gap (clock leakage?)"

    # (b) closed field set
    actual_keys = tuple(sorted(proj_t0.keys()))
    expected_keys = tuple(sorted(_RUN_SUMMARY_KEYS))
    assert actual_keys == expected_keys, (
        f"INV-2(b): top-level keys not closed — got {actual_keys}, want {expected_keys}"
    )

    # (c) widening with a new node does not introduce new top-level keys.
    extra_node = Node(
        id=str(uuid.uuid4()),
        run_id=run.id,
        step_index=3,
        node_name="tool_call",
        kind=NodeKind.TOOL,
        started_at=nodes[-1].started_at + timedelta(seconds=1),
        ended_at=nodes[-1].started_at + timedelta(seconds=2),
        state_after={"tool_result": "ok"},
        tool_name="search",
        tool_input={"q": "hi"},
        tool_output={"result": "ok"},
    )
    widened = project_to_golden(run, [*nodes, extra_node])
    widened_keys = tuple(sorted(widened.keys()))
    assert widened_keys == expected_keys, (
        f"INV-2(c): new envelope kind widened top-level keys to {widened_keys}"
    )
    assert widened["node_count"] == 4
    assert widened["node_kinds"] == ["fn", "llm", "end", "tool"]


# ---------------------------------------------------------------------------
# Invariant 3 — sanitiser audit at fixture-load
# ---------------------------------------------------------------------------


def invariant_3_sanitiser_audit() -> None:
    """Five known-bad patterns get redacted; ten benign tokens survive intact."""
    dirty = "\n".join(
        [
            json.dumps({"event": "auth", "key": "sk-ant-api03-" + "A" * 64}),
            json.dumps({"event": "auth", "key": "sk-proj-" + "B" * 48}),
            json.dumps({"event": "header", "value": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"}),
            json.dumps({"event": "aws", "id": "AKIAIOSFODNN7EXAMPLE"}),
            json.dumps({"event": "url", "u": "https://relay.example.com/?token=abcdefghijklmnop1234567890"}),
            # 10 benign tokens that MUST NOT trigger redaction:
            json.dumps({"node_id": "abc-def-1234", "step_index": 0, "counter": 42}),
            json.dumps({"adapter": "langgraph", "thread": "t1", "model": "claude-opus-4-7"}),
            json.dumps({"sk": "short", "key": "sk-too-short"}),  # below length threshold
            json.dumps({"random": "0123456789abcdef0123456789abcdef"}),  # hex but not key-shape
            json.dumps({"phrase": "Bearer with hi"}),  # too short post-Bearer
            json.dumps({"name": "AKIAonly3"}),  # too short for AKID
            json.dumps({"q": "search results for cats"}),
            json.dumps({"path": "/api/runs/list?limit=10"}),
            json.dumps({"prompt": "what's the weather?"}),
            json.dumps({"tool_input": {"city": "Beijing"}}),
        ]
    )
    cleaned = sanitise_capture(dirty)

    # Five redactions all present.
    assert "<REDACTED:ANTHROPIC_KEY>" in cleaned, "INV-3: sk-ant- not redacted"
    assert "<REDACTED:OPENAI_KEY>" in cleaned, "INV-3: sk-proj- not redacted"
    assert "<REDACTED:BEARER_TOKEN>" in cleaned, "INV-3: Bearer JWT not redacted"
    assert "<REDACTED:AWS_AKID>" in cleaned, "INV-3: AWS AKID not redacted"
    assert "<REDACTED:URL_TOKEN>" in cleaned, "INV-3: URL token not redacted"

    # No raw secrets survive in cleartext.
    assert "sk-ant-api03-AAA" not in cleaned, "INV-3: leaked anthropic key prefix"
    assert "AKIAIOSFODNN7EXAMPLE" not in cleaned, "INV-3: leaked AWS AKID"
    assert "abcdefghijklmnop1234567890" not in cleaned, "INV-3: leaked URL token"

    # Ten benign tokens untouched.
    benign_must_survive = [
        "abc-def-1234",
        '"step_index": 0',
        '"counter": 42',
        "langgraph",
        "claude-opus-4-7",
        '"sk": "short"',
        '"key": "sk-too-short"',
        "0123456789abcdef0123456789abcdef",
        "Bearer with hi",
        "AKIAonly3",
        "search results for cats",
        "/api/runs/list?limit=10",
        "what's the weather?",
        "Beijing",
    ]
    for b in benign_must_survive:
        assert b in cleaned, f"INV-3 false-positive: benign token {b!r} got eaten"

    # Idempotency.
    twice = sanitise_capture(cleaned)
    assert twice == cleaned, "INV-3 idempotency: re-sanitising changed output"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    invariants = [
        ("INV-1 round-trip byte-equality", invariant_1_round_trip),
        ("INV-2 projection stability + closed field set", invariant_2_projection_stability),
        ("INV-3 sanitiser audit", invariant_3_sanitiser_audit),
    ]
    failures: list[tuple[str, str]] = []
    t_total = time.perf_counter()
    for name, fn in invariants:
        t0 = time.perf_counter()
        try:
            fn()
            dt = (time.perf_counter() - t0) * 1000
            print(f"  GREEN  {name}  ({dt:.2f} ms)")
        except AssertionError as e:
            dt = (time.perf_counter() - t0) * 1000
            print(f"  FAIL   {name}  ({dt:.2f} ms): {e}")
            failures.append((name, str(e)))
        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000
            print(f"  ERROR  {name}  ({dt:.2f} ms): {type(e).__name__}: {e}")
            failures.append((name, f"{type(e).__name__}: {e}"))
    total_ms = (time.perf_counter() - t_total) * 1000
    print()
    if failures:
        print(f"spike 19: {len(failures)}/{len(invariants)} FAIL  total {total_ms:.2f} ms")
        for name, msg in failures:
            print(f"  - {name}: {msg}")
        return 1
    print(f"spike 19: {len(invariants)}/{len(invariants)} GREEN  total {total_ms:.2f} ms")
    # Perf budget assertion (≤ 5000 ms whole spike per ADR-028).
    assert total_ms <= 5000, f"perf budget blown: {total_ms:.2f} ms > 5000 ms"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
