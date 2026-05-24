"""Golden-trace data contract helpers (R103, ADR-028 §4 slot-2 Option A).

Hoisted verbatim from ``tests/spikes/spike19_golden_trace_invariants.py``
(R100) and ``scripts/capture/capture_anthropic_agents.py`` (R101) to give
the data-contract reference implementation a single home on the production
``sys.path``. Byte-parity preservation was the entire point of R103 — both
prior copies were checked-in word-for-word identical at the source level,
and R103's hoist preserved that exactly. ``tests/spikes/spike19_*`` and
``scripts/capture/capture_*`` continue to work; they now import from here
instead of inlining.

Public surface (the symbols R102+ ``chronos verify-golden`` CLI verb +
sibling capture drivers depend on):

    project_to_golden  — (Run, [Node]) -> canonical RunSummary dict
    golden_dumps       — RunSummary dict -> canonical JSON bytes
    sanitise_capture   — JSONL str -> sanitised JSONL str (idempotent)
    _SECRET_PATTERNS   — secret-pattern table (exposed for sibling drivers)
    _canonicalise      — recursive dict/list canonicaliser (used by callers
                         that need to canonicalise pieces independently;
                         also re-exported so the spike pin tests pre-R103
                         had a stable handle)

Closed top-level RunSummary key set:

    _RUN_SUMMARY_KEYS = (schema, adapter, status, task_description,
                          node_count, node_kinds, node_names, states_after)

Adding a key requires an explicit ADR-028 amendment + ``chronos.golden/v0
→ v1`` schema bump per ``docs/contracts/golden-trace-format.md`` §5.
"""

from chronos.golden.projection import (
    _GOLDEN_SCHEMA,
    _RUN_SUMMARY_KEYS,
    _canonicalise,
    golden_dumps,
    project_to_golden,
)
from chronos.golden.sanitise import _SECRET_PATTERNS, sanitise_capture

__all__ = [
    "_GOLDEN_SCHEMA",
    "_RUN_SUMMARY_KEYS",
    "_SECRET_PATTERNS",
    "_canonicalise",
    "golden_dumps",
    "project_to_golden",
    "sanitise_capture",
]
