"""Golden-trace projection helpers (R103, ADR-028 §4 slot-2 Option A).

Hoisted **verbatim** from ``tests/spikes/spike19_golden_trace_invariants.py``
(R100) — function bodies, docstrings, and the closed-key tuple are
byte-identical to the spike's reference implementation. The R102 pin tests
in ``tests/unit/test_capture_anthropic_agents.py`` (#4 ``project_to_golden``,
#5 ``_canonicalise``) had been guarding against drift while the helpers
lived in two places; R103 collapses both copies and deletes the pin tests
since drift is no longer possible.

Determinism rules (re-enforced by INV-1 / INV-2 in spike 19):
- ``run_id``, ``started_at``, ``ended_at``, per-node ``id`` /
  ``started_at`` / ``ended_at`` are STRIPPED — they leak machine state.
- ``node_kinds`` + ``node_names`` are emitted in ``step_index`` order
  (matches ``store.get_nodes_for_run`` ordering).
- ``states_after`` is per-node, JSON-canonicalised separately so dict
  iteration order can never sneak through (we use ``sort_keys=True`` at
  serialise time, but re-emit here as ordered dicts of canonical primitives).
- Top-level keys are CLOSED to :data:`_RUN_SUMMARY_KEYS`. Any kwargs sneak
  is caught by INV-2's closed-set assertion.
"""

from __future__ import annotations

import json
from typing import Any

from chronos.core.models import Node, Run

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
