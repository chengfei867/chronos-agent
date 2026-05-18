"""Unit tests for ``scripts/dogfood/_degradation.is_relay_degraded_exception``.

The classifier is the gating heuristic between exit 2 (relay-degraded skip)
and exit 3 (hard regression) for live dogfood scripts. False-positives hide
regressions and break the GA-ratchet semantics; false-negatives only delay
diagnosis by one round. The tests below pin both directions:

- **Positive cases** — exception strings observed against the OneAPI relay
  in R69, R71, R73, R85, and R86 (this round). New markers should land
  here first.
- **Negative cases** — adapter / chronos / generic Python exceptions that
  must NOT be classified as relay flakes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# The dogfood directory is intentionally NOT a Python package (no
# ``__init__.py``) so its scripts can be invoked directly as
# ``python scripts/dogfood/<name>.py``. To exercise its private helper
# from pytest we load it through ``importlib.util`` instead of leaking
# ``scripts/dogfood`` onto ``sys.path`` permanently.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELPER_PATH = _REPO_ROOT / "scripts" / "dogfood" / "_degradation.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "chronos_dogfood_degradation",
        _HELPER_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_helper = _load_helper()
is_relay_degraded_exception = _helper.is_relay_degraded_exception
_MARKERS: tuple[str, ...] = _helper._RELAY_DEGRADED_MARKERS


# ---------------------------------------------------------------------------
# Positive cases — must classify as relay-degraded (exit 2).
# ---------------------------------------------------------------------------

# Exception strings observed in the wild against the OneAPI relay.
RELAY_DEGRADED_FIXTURES: tuple[tuple[str, str], ...] = (
    # R69 spike #3.4 — synthetic-auth-failed envelope leaked into adapter
    # via AssistantMessage.model='<synthetic>'.
    ("R69 synthetic model", "AssistantMessage model='<synthetic>' subtype='authentication_failed'"),
    # R71 production hit — relay returned authentication_failed verbatim.
    ("R71 auth failed", "RelayError: authentication_failed: token rejected"),
    # R73 surfaced this human-readable variant in the SDK error path.
    ("R73 not logged in", "Not logged in · Please run /login"),
    # R86 — claude-agent-sdk masks ResultMessage(is_error=True, subtype='success')
    # into a misleading exception text.
    ("R86 masked success", "Claude Code returned an error result: success"),
    # Future-proof: trailing variant from same SDK code path.
    (
        "future SDK variant",
        "Claude Code returned an error result: degraded_no_session",
    ),
    # Case-insensitivity guard — markers are matched lowercased.
    ("uppercase variant", "CLAUDE CODE RETURNED AN ERROR RESULT: SUCCESS"),
)


@pytest.mark.parametrize(
    ("label", "msg"),
    RELAY_DEGRADED_FIXTURES,
    ids=[f[0] for f in RELAY_DEGRADED_FIXTURES],
)
def test_classifies_known_relay_envelopes_as_degraded(label: str, msg: str) -> None:
    """Each known relay-failure envelope must classify as exit-2 degraded."""
    assert is_relay_degraded_exception(Exception(msg)) is True, label


def test_works_with_non_exception_subclass() -> None:
    """Helper must accept BaseException subclasses, not just Exception."""

    class CustomBaseException(BaseException):
        pass

    exc = CustomBaseException("Claude Code returned an error result: success")
    assert is_relay_degraded_exception(exc) is True


def test_works_with_chained_exception_str() -> None:
    """If a wrapping exception's str includes the marker, it still classifies."""
    inner = Exception("Claude Code returned an error result: success")
    outer = RuntimeError(f"adapter wrapped: {inner}")
    assert is_relay_degraded_exception(outer) is True


# ---------------------------------------------------------------------------
# Negative cases — must NOT classify as relay-degraded.
# ---------------------------------------------------------------------------

NON_DEGRADED_FIXTURES: tuple[tuple[str, str], ...] = (
    ("plain math bug", "ZeroDivisionError: division by zero"),
    ("adapter contract bug", "AdapterError: ForkRef.child_run_id missing"),
    ("chronos store bug", "RunNotFoundError: no run with id='abc-123'"),
    ("network timeout (caller already handled separately)", "TimeoutError: timed out after 90.0s"),
    ("empty exception", ""),
    # Sneaky: substring 'auth' alone must NOT match — only full 'authentication'.
    ("substring trap 'auth'", "OAuth flow init failed: token store empty"),
)


@pytest.mark.parametrize(
    ("label", "msg"),
    NON_DEGRADED_FIXTURES,
    ids=[f[0] for f in NON_DEGRADED_FIXTURES],
)
def test_does_not_classify_real_bugs_as_degraded(label: str, msg: str) -> None:
    """Random / real-bug exception strings must classify as exit-3 hard."""
    assert is_relay_degraded_exception(Exception(msg)) is False, label


# ---------------------------------------------------------------------------
# Marker-table invariants (catch accidental edits).
# ---------------------------------------------------------------------------


def test_markers_are_all_lowercase() -> None:
    """Markers are matched against lowercased str(exc); guard the contract."""
    for marker in _MARKERS:
        assert marker == marker.lower(), f"marker not lowercase: {marker!r}"


def test_markers_are_unique() -> None:
    """No duplicate markers (cheap drift check)."""
    assert len(set(_MARKERS)) == len(_MARKERS)


def test_markers_table_is_non_empty() -> None:
    """A nuked marker list would silently turn every relay flake into exit 3."""
    assert len(_MARKERS) >= 4
