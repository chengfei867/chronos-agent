"""Golden-trace secret sanitiser (R103, ADR-028 §4 slot-2 Option A).

Hoisted **verbatim** from ``tests/spikes/spike19_golden_trace_invariants.py``
(R100) — pattern table and ``sanitise_capture`` body are byte-identical to
the spike's reference implementation. R102 pin test
``test_sanitiser_byte_identical_to_spike`` had been guarding against drift
while the helper lived in two places; R103 collapses both copies and
deletes that pin test since drift is no longer possible.

Properties (re-enforced by INV-3 in spike 19):
- Idempotent: running twice produces identical output (the redaction
  markers themselves do not match any pattern).
- Low false-positive: regexes chosen to match real-world secret shapes
  WITHOUT capturing common benign tokens (UUID4 hex strings, langgraph
  node ids, etc.).
- Defence-in-depth: applied at fixture-LOAD by the v0.10.0+
  ``chronos verify-golden`` CLI verb AND at fixture-WRITE by the capture
  drivers under ``scripts/capture/``. Either layer alone is insufficient
  per ADR-028 §4.

Pattern set may grow without a v-bump (safety-valve for observed leakage
attempts during fixture authoring); shrinking or semantic-changing requires
ADR-028 amendment.
"""

from __future__ import annotations

import re

# Patterns chosen to match real-world secret shapes WITHOUT false-positiving
# on common benign tokens (UUID4 hex strings, langgraph node ids, etc.).
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    # Anthropic API keys: sk-ant-{api03,test}-...{40-200 chars}
    ("ANTHROPIC_KEY", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "<REDACTED:ANTHROPIC_KEY>"),
    # OpenAI / project keys: sk-proj-..., sk-... (be careful: must not eat sk-ant- substrings)
    (
        "OPENAI_KEY",
        re.compile(r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{20,}"),
        "<REDACTED:OPENAI_KEY>",
    ),
    # Bearer tokens (JWT-shaped or opaque): "Bearer xxxxxxxxxxxxx..."
    (
        "BEARER_TOKEN",
        re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}"),
        "Bearer <REDACTED:BEARER_TOKEN>",
    ),
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
