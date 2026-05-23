"""Capture driver — anthropic_agents adapter (R101, ADR-028 §4 slice 2).

Reads a recorded :class:`chronos.store.SqliteStore` row for the given
``--run-id`` and writes the canonical golden-trace fixture pair under
``--out-dir``::

    <out-dir>/envelopes.jsonl    # human-authored capture (one Node per line)
    <out-dir>/expected_run.json  # canonical RunSummary projection

Both files are **sanitised on write** (belt) — known-secret patterns are
redacted before bytes hit disk. The load-time gate (spike 19 INV-3, R102 CLI
verb) remains the suspenders. ADR-028 §4 mandates both layers hold at v0.

Cron policy
-----------
This driver is intended to be invoked by a *human-led local round* with a
real ``CHRONOS_LIVE=1`` recording session that has already populated
``chronos.db``. Cron rounds DO NOT run this driver against a live recorder
(no API key, ``CHRONOS_LIVE`` must remain unset per CONTEXT.md §3 disciplines).
The unit test ``tests/unit/test_capture_anthropic_agents.py`` exercises the
driver against an in-memory ``SqliteStore`` with synthetic Nodes — no live
API needed for CI.

Usage (live capture)
--------------------
1. Record a real anthropic_agents Run::

       export CHRONOS_LIVE=1
       export ANTHROPIC_API_KEY=...
       uv run --no-sync python scripts/dogfood/arc_b_slice_1_smoke.py
       # produces a Run row in chronos.db with adapter='anthropic_agents'

2. Get the run id::

       uv run --no-sync chronos runs list | head -3
       # copy the id

3. Capture the fixture::

       uv run --no-sync python scripts/capture/capture_anthropic_agents.py \\
           --db chronos.db \\
           --run-id <run-id> \\
           --out-dir tests/golden/anthropic_agents/<scenario>/

4. Verify byte-equality::

       uv run --no-sync python tests/spikes/spike19_golden_trace_invariants.py
       # should remain 3/3 GREEN; expected_run.json freshly written is canonical

Design notes
------------
- Reference impls (``project_to_golden``, ``_canonicalise``, ``golden_dumps``,
  ``sanitise_capture``) are inlined here to avoid importing from
  ``tests/spikes/`` (which isn't a package). The unit test pins byte-identity
  between this file's helpers and spike 19's, so slot-2 Option A (hoist to
  ``src/chronos/golden/`` at R102) is a mechanical follow-up — drift can't go
  undetected.
- Envelope shape mirrors ``tests/golden/_skeleton/envelopes.jsonl``: one JSON
  object per Node with keys ``envelope`` (synthetic kind label),
  ``node_name``, ``kind``, ``step_index``, ``state_after``, plus an optional
  ``model_name`` for LLM nodes.
- Hook level = adapter-level (per ADR-028 §4 preference). The driver reads
  whatever the recorder already wrote into the store; it does NOT widen the
  envelopes schema beyond v0.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Ensure the in-tree chronos package resolves without an editable install
# when this script is invoked directly from a clone.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from chronos.core.models import Node, Run
from chronos.store import SqliteStore

# ---------------------------------------------------------------------------
# Reference projection (R101 inline; hoisted to chronos.golden.projection in R102)
# Kept byte-identical to tests/spikes/spike19_golden_trace_invariants.py via the
# unit test in tests/unit/test_capture_anthropic_agents.py.
# ---------------------------------------------------------------------------

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

    Mirrors spike 19's reference projection: drops machine-state fields
    (run_id, timestamps, usage, cost), emits node_kinds + node_names in
    step_index order, canonicalises per-node state_after via :func:`_canonicalise`.
    Top-level field set is closed to :data:`_RUN_SUMMARY_KEYS`.
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
    """Canonical golden serialisation: sort_keys + 2-space indent + trailing nl."""
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Sanitiser (R101 inline; hoisted to chronos.golden.sanitise in R102)
# Pinned byte-identical to spike 19 via the unit test.
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    # Anthropic API keys: sk-ant-{api03,test}-...{20+ chars}
    ("ANTHROPIC_KEY", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "<REDACTED:ANTHROPIC_KEY>"),
    # OpenAI / project keys: sk-proj-..., sk-... (must NOT eat sk-ant- substrings)
    (
        "OPENAI_KEY",
        re.compile(r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{20,}"),
        "<REDACTED:OPENAI_KEY>",
    ),
    # Bearer tokens (JWT-shaped or opaque)
    (
        "BEARER_TOKEN",
        re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}"),
        "Bearer <REDACTED:BEARER_TOKEN>",
    ),
    # AWS access key id
    ("AWS_AKID", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<REDACTED:AWS_AKID>"),
    # Generic secret-shaped URL token query param
    (
        "URL_TOKEN",
        re.compile(r"([?&](?:token|secret|api_key|key)=)[A-Za-z0-9._\-]{16,}"),
        r"\1<REDACTED:URL_TOKEN>",
    ),
)


def sanitise_capture(jsonl_str: str) -> str:
    """Redact known-secret patterns in a JSONL capture string. Idempotent."""
    out = jsonl_str
    for _kind, rx, repl in _SECRET_PATTERNS:
        out = rx.sub(repl, out)
    return out


# ---------------------------------------------------------------------------
# Envelope projection (Node -> envelope dict)
# ---------------------------------------------------------------------------

# Map NodeKind enum value -> envelope semantic label. Mirrors the skeleton:
# kind=fn  -> envelope=agent_start (or generic 'fn' for non-start fn nodes)
# kind=llm -> envelope=llm_call
# kind=end -> envelope=agent_end
# Other kinds (tool, router, fork) keep their kind value as the envelope label.
_ENVELOPE_LABELS: dict[str, str] = {
    "fn": "fn_call",
    "llm": "llm_call",
    "tool": "tool_call",
    "router": "router_decision",
    "fork": "fork_event",
    "end": "agent_end",
}


def _envelope_label(node: Node) -> str:
    """Pick a semantic envelope label for a node.

    First node with kind=fn becomes ``agent_start`` (skeleton convention);
    others use the kind-derived label. This matches ``tests/golden/_skeleton/
    envelopes.jsonl`` shape so contributors can hand-edit by analogy.
    """
    if node.step_index == 0 and node.kind.value == "fn":
        return "agent_start"
    return _ENVELOPE_LABELS.get(node.kind.value, node.kind.value)


def node_to_envelope(node: Node) -> dict[str, Any]:
    """Project a Node into a single capture-side envelope dict.

    Output shape (v0):
        {
          "envelope": <label>,
          "node_name": <Node.node_name>,
          "kind": <Node.kind.value>,
          "step_index": <int>,
          "state_after": <canonicalised dict>,
          "model_name": <Node.model_name> (only if non-null),
        }
    """
    env: dict[str, Any] = {
        "envelope": _envelope_label(node),
        "node_name": node.node_name,
        "kind": node.kind.value,
        "step_index": node.step_index,
        "state_after": _canonicalise(node.state_after) if node.state_after else {},
    }
    if node.model_name:
        env["model_name"] = node.model_name
    return env


def envelopes_dumps(envelopes: list[dict[str, Any]]) -> str:
    """Serialise envelopes to JSONL (one canonical JSON object per line)."""
    lines = [json.dumps(e, sort_keys=True) for e in envelopes]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Driver entrypoint
# ---------------------------------------------------------------------------


def capture_run(
    *,
    store: SqliteStore,
    run_id: str,
    out_dir: Path,
) -> tuple[Path, Path]:
    """Capture a recorded run into a golden-trace fixture pair.

    Returns ``(envelopes_path, expected_run_path)``. Both files are
    sanitised before write (sanitiser belt; load-time gate at R102 verify-golden
    is the suspenders).

    Raises:
        ValueError: if the run id isn't in the store, or if the run's adapter
                    isn't ``anthropic_agents`` (this driver is per-adapter
                    explicit per ADR-028 §4 — capturing langgraph would need
                    a sibling driver in v0.10.0+).
    """
    run = store.get_run(run_id)
    if run is None:
        raise ValueError(f"run not found in store: run_id={run_id!r}")
    if run.adapter != "anthropic_agents":
        raise ValueError(
            f"capture_anthropic_agents.py is per-adapter explicit; "
            f"got run.adapter={run.adapter!r}, expected 'anthropic_agents'. "
            f"Add a sibling driver under scripts/capture/ for other adapters."
        )

    nodes = store.get_nodes_for_run(run_id)
    if not nodes:
        raise ValueError(
            f"run {run_id!r} has zero nodes — refuse to write empty fixture "
            f"(would defeat the regression net)."
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    # Emit envelopes.jsonl (sanitised on write)
    envelopes = [node_to_envelope(n) for n in sorted(nodes, key=lambda n: n.step_index)]
    envelopes_jsonl = envelopes_dumps(envelopes)
    envelopes_jsonl_sanitised = sanitise_capture(envelopes_jsonl)
    envelopes_path = out_dir / "envelopes.jsonl"
    envelopes_path.write_text(envelopes_jsonl_sanitised, encoding="utf-8")

    # Emit expected_run.json (also sanitise-belt — projected JSON could in
    # principle carry a secret in task_description / state_after).
    expected = project_to_golden(run, nodes)
    expected_json = golden_dumps(expected)
    expected_json_sanitised = sanitise_capture(expected_json)
    expected_path = out_dir / "expected_run.json"
    expected_path.write_text(expected_json_sanitised, encoding="utf-8")

    return envelopes_path, expected_path


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="capture_anthropic_agents",
        description=(
            "Capture a recorded anthropic_agents Run into a golden-trace fixture "
            "pair (envelopes.jsonl + expected_run.json). ADR-028 / R101."
        ),
    )
    p.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Path to a SqliteStore-formatted chronos DB containing the run.",
    )
    p.add_argument(
        "--run-id",
        required=True,
        help="The Run.id to capture (UUID4 string).",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help=(
            "Output directory for envelopes.jsonl + expected_run.json. "
            "Will be created if absent. Convention: "
            "tests/golden/anthropic_agents/<scenario>/"
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if not args.db.is_file():
        print(f"error: --db file not found: {args.db}", file=sys.stderr)
        return 2
    store = SqliteStore.open(args.db)
    try:
        envelopes_path, expected_path = capture_run(
            store=store,
            run_id=args.run_id,
            out_dir=args.out_dir,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"wrote {envelopes_path}")
    print(f"wrote {expected_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
