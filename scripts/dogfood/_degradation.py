"""Shared dogfood-degradation classifier (R86).

When a Chronos dogfood script drives a real LLM relay end-to-end and the
relay misbehaves, the script needs to distinguish three outcomes:

- **exit 0 (green)** — relay healthy, all invariants pass.
- **exit 2 (relay degraded)** — relay returned a recognisable failure
  envelope (synthetic-auth-failed, masked-error-result, etc.) that is
  *known* to be a relay-side issue, not an adapter regression. Caller
  should *skip*, not fail.
- **exit 3 (hard regression)** — anything else; treat as adapter bug
  and bisect.

Relay failure envelopes evolve with SDK versions. R69 spike #3.4 first
documented the OneAPI relay's "synthetic-auth-failed" mode (relay
returns ``model='<synthetic>'`` + ``error='authentication_failed'`` +
text ``'Not logged in · Please run /login'``). R71 first hit it in
production. R73 worked around it with the spaced-PascalCase model id
``'Claude Sonnet 4.6'``. R85 dogfood encoded the heuristic as substring
match on ``"authentication"`` / ``"synthetic"``.

R86 hit the **same root cause** with a **different surface**: the
current ``claude-agent-sdk`` (≥ R85's pin) wraps a relay-side
``is_error=True ResultMessage(subtype='success')`` into the misleading
exception ``Exception('Claude Code returned an error result: success')``.
That string contains *neither* ``"authentication"`` nor ``"synthetic"``,
so the R85 heuristic mis-classified the failure as exit 3 (hard).

This module is the canonical home of the heuristic so all dogfoods
share the same classifier and unit tests. Keep matching **lower-cased
substrings** in :data:`_RELAY_DEGRADED_MARKERS`. Add new markers as
SDK versions evolve. Do NOT match on exception *type* — relay
degradations come through as plain ``Exception`` from the SDK's
stream-receiver and are indistinguishable by type.
"""

from __future__ import annotations

# Lowercase substrings that, when present in an exception's str(), strongly
# suggest the failure is relay-side and not an adapter regression.
#
# Keep this tight: false-negatives (treating a real bug as a relay flake)
# only delay diagnosis by one round; false-positives (treating a real bug
# as a flake) hide regressions and break the GA-ratchet semantics.
_RELAY_DEGRADED_MARKERS: tuple[str, ...] = (
    # R69 / R71 era — synthetic auth-failure pattern surfaced via
    # AssistantMessage.model='<synthetic>' or error='authentication_failed'.
    "authentication",
    "synthetic",
    "not logged in",
    # R86 era — claude-agent-sdk wraps the relay's is_error=True
    # ResultMessage(subtype='success') into this misleading text.
    # Match without trailing colon so future variants ("returned an
    # error result: degraded", etc.) still classify correctly.
    "claude code returned an error result",
)


def is_relay_degraded_exception(exc: BaseException) -> bool:
    """Return True iff ``exc`` matches a known relay-degradation envelope.

    The check is a case-insensitive substring scan over ``str(exc)``
    using :data:`_RELAY_DEGRADED_MARKERS`. We deliberately do NOT inspect
    ``type(exc)`` because the SDK surfaces relay-side issues as plain
    ``Exception`` from inside the message-stream coroutine, and adapter
    bugs (``AdapterError`` etc.) wrap those plain exceptions.

    The function is intentionally cheap and side-effect-free so it can
    run inside an ``except`` block without risk.
    """
    msg = str(exc).lower()
    return any(marker in msg for marker in _RELAY_DEGRADED_MARKERS)


__all__ = ["is_relay_degraded_exception"]
