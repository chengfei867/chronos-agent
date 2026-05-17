"""Shared stub helpers for ``anthropic_agents`` adapter tests + dogfoods (R84).

R84 (Round 84, 2026-05-18) extracts the duck-typed ``StubBlock`` /
``StubMessage`` / ``aiter_messages`` pattern that R75-R83 had replicated across
6 sites (4 unit-test files + 2 dogfood scripts). Per the R58 fixture-module
convention (threshold = 3 duplications), this extraction was deferred 4 times
during the slice-3 TDD/impl chain (R79-R82) to keep diffs small; R83's
slice-3 closing retro explicitly listed it as the R84 first-choice cleanup
slot.

## Design

The pattern across the 5 homogeneous sites was identical:

* A ``_StubBlock`` ``@dataclass`` with optional ``text`` / ``name`` / ``input``
  / ``id`` / ``tool_use_id`` / ``content`` slots, sub-classed by
  ``TextBlock`` / ``ToolUseBlock`` / ``ToolResultBlock`` static subclasses.
  The recorder dispatches on ``type(block).__name__`` (mirrors CrewAI
  ADR-021), so subclass *names* drive kind detection, not isinstance.
* A ``_StubMessage`` ``@dataclass`` with optional ``content`` / ``usage`` /
  ``model`` / ``stop_reason`` / ``total_cost_usd`` / ``duration_ms`` /
  ``uuid`` / ``session_id`` / ``extra`` slots, sub-classed by
  ``UserMessage`` / ``AssistantMessage``.
* An ``_aiter`` helper that wraps a ``list[Any]`` into an ``AsyncIterator``
  using a generator function (so the iterator can be re-created if a test
  reuses the same list — though most don't).

This module exports those names without the leading underscore (since they
are now a deliberate shared API rather than per-file privates) plus a few
convenience helpers:

* ``aiter_messages(messages)`` — drop-in for the previous ``_aiter``.
* ``make_block(cls_name, **kw)`` / ``make_message(cls_name, **kw)`` — runtime
  subclass factories for tests that need additional block kinds (e.g.
  ``ThinkingBlock``) without growing the static taxonomy. Mirrors the
  pattern used in ``test_adapter_anthropic_agents.py`` (which is NOT
  refactored to use this module yet — see R84 progress doc for rationale).

## Non-goals

* This module does NOT replace ``test_adapter_anthropic_agents.py``'s
  ``_StubBlockBase`` / ``_StubMsgBase`` factory pattern. That file uses
  richer fields (``is_error``, ``thinking``, ``signature``) and an
  intentionally different idiom (``_blk(cls_name, **kw)`` runtime subclass
  factory only — no static subclasses). Merging would either bloat this
  module's static surface or lose the named-subclass ergonomics 5 of the
  6 sites depend on. R85+ may reconcile if a forcing function appears.
* This module does NOT export ``_FakeClient`` (each call site has slightly
  different needs around ``connect()`` / ``disconnect()`` / awaitables).
* ``StubBlock.is_error`` / ``thinking`` / ``signature`` slots are NOT
  added pre-emptively; per the R64 anti-pattern, "future-proof" extra
  slots are falsification targets. If a future test needs them, this
  module gets the fields then, not now.

## Stability

This is a TEST-ONLY module under ``tests/unit/fixtures/``. It is NOT part
of the chronos public API. Internal callers may evolve it freely (e.g. add
a slot, reorder defaults) as long as the 5 (or N+) consumers update in
lockstep. There is no SemVer commitment.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Block stubs (mirror anthropic_agents content blocks)
# ---------------------------------------------------------------------------


@dataclass
class StubBlock:
    """Duck-typed stand-in for SDK content blocks.

    The recorder reads attributes via ``getattr`` (R70 ADR-026 §4) and
    dispatches kind on ``type(block).__name__``, so subclass names matter
    but isinstance does not.

    * ``text`` — TextBlock payload.
    * ``name`` / ``input`` — ToolUseBlock fields.
    * ``id`` — ToolUseBlock anchor (R76 ADR-026 §5.1).
    * ``tool_use_id`` — ToolResultBlock back-reference (R76 ADR-026 §5.1).
    * ``content`` — ToolResultBlock payload.
    """

    text: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None
    id: str | None = None
    tool_use_id: str | None = None
    content: Any = None


class TextBlock(StubBlock):
    """Class name drives recorder TextBlock dispatch."""


class ToolUseBlock(StubBlock):
    """Class name drives recorder ToolUseBlock dispatch."""


class ToolResultBlock(StubBlock):
    """Class name drives recorder ToolResultBlock dispatch."""


# ---------------------------------------------------------------------------
# Message stubs (mirror anthropic_agents SDK Messages)
# ---------------------------------------------------------------------------


@dataclass
class StubMessage:
    """Duck-typed stand-in for SDK ``UserMessage`` / ``AssistantMessage``.

    The recorder dispatches kind on ``type(msg).__name__``. ``extra``
    captures any additional metadata fields the tests want to attach
    without growing this dataclass; it is not read by the recorder.
    """

    content: Any = None
    usage: Any = None
    model: str | None = None
    stop_reason: str | None = None
    total_cost_usd: float | None = None
    duration_ms: int | None = None
    uuid: str | None = None
    session_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class UserMessage(StubMessage):
    """Class name drives recorder UserMessage dispatch."""


class AssistantMessage(StubMessage):
    """Class name drives recorder AssistantMessage dispatch."""


# ---------------------------------------------------------------------------
# Async-iterator helper (mirror SDK ``receive_messages()`` shape)
# ---------------------------------------------------------------------------


def aiter_messages(messages: list[Any]) -> AsyncIterator[Any]:
    """Wrap a synchronous list into an async iterator.

    Returns a fresh generator each call (closure over ``messages``), so
    callers may invoke this multiple times if the underlying list is
    mutated between yields. Most callers consume once.
    """

    async def _gen() -> AsyncIterator[Any]:
        for m in messages:
            yield m

    return _gen()


# ---------------------------------------------------------------------------
# Runtime-subclass factories (parity with test_adapter_anthropic_agents.py
# style — useful for ad-hoc block kinds that don't warrant a named subclass)
# ---------------------------------------------------------------------------


def make_block(cls_name: str, **kwargs: Any) -> StubBlock:
    """Create a one-off ``StubBlock`` subclass with the given class name.

    Example:
        thinking = make_block("ThinkingBlock", text="…")

    The recorder reads the class name via ``type(block).__name__``, so this
    is sufficient to drive ad-hoc kind dispatch without polluting this
    module's static taxonomy with every block variant.
    """

    subclass = type(cls_name, (StubBlock,), {})
    return subclass(**kwargs)  # type: ignore[return-value]


def make_message(cls_name: str, **kwargs: Any) -> StubMessage:
    """Create a one-off ``StubMessage`` subclass with the given class name.

    Companion to :func:`make_block` for message-level stubs.
    """

    subclass = type(cls_name, (StubMessage,), {})
    return subclass(**kwargs)  # type: ignore[return-value]


__all__ = [
    "AssistantMessage",
    "StubBlock",
    "StubMessage",
    "TextBlock",
    "ToolResultBlock",
    "ToolUseBlock",
    "UserMessage",
    "aiter_messages",
    "make_block",
    "make_message",
]
