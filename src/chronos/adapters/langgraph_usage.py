"""Usage & cost extraction hook for the LangGraph adapter (ADR-009).

This module defines the :class:`UsageContext` / :class:`UsageResult` pair that
:class:`chronos.adapters.langgraph.LangGraphRecorder` passes through its optional
``usage_extractor`` callable, plus a convenience extractor for the common
case of LangChain ``AIMessage.usage_metadata``.

Why a hook?
-----------

LangGraph exposes LLM usage in several places depending on the LangChain
version, the provider, and the user's state shape (see ADR-009 §Context).
Hard-coding any single path would break half of our users. The hook lets the
user plug in their own pricing + accounting logic while Chronos stays
adapter/provider neutral.

Failure semantics
-----------------

If the user's extractor raises, the recorder logs a warning via the logger
``chronos.adapters.langgraph.usage`` and records the node with ``usage=None``.
A buggy extractor must **never** abort a recording — partial usage data is
far more useful than losing the entire run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class UsageContext:
    """Read-only payload passed to a user-supplied usage extractor.

    Fields mirror the snapshot pair that the adapter is currently turning into
    a :class:`chronos.core.models.Node`. ``pre_values`` / ``post_values`` are
    the coerced-to-dict state values (the same shape the user sees on
    ``Node.state_after``). ``pre_snapshot`` / ``post_snapshot`` expose the raw
    LangGraph ``StateSnapshot`` in case the extractor needs metadata.
    """

    node_name: str
    pre_snapshot: Any
    post_snapshot: Any
    pre_values: dict[str, Any]
    post_values: dict[str, Any]
    task: Any  # pre_snapshot.tasks[0] — exposed for message id / task.name


@dataclass(frozen=True)
class UsageResult:
    """Result of a usage extraction, merged into the Node being recorded.

    ``None`` return from the extractor means "no LLM activity on this node"
    and is the expected case for routers, tools, fallbacks, etc.

    ``cost_usd_cents`` is an integer to match the SQLite schema (ADR-003);
    user code should round accordingly (e.g. ``int(round(dollars * 100))``).
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd_cents: int | None = None
    model_name: str | None = None


class UsageExtractor(Protocol):
    """Protocol for pluggable usage extractors (ADR-009)."""

    def __call__(self, ctx: UsageContext) -> UsageResult | None:  # pragma: no cover
        ...


# ---------------------------------------------------------------------------
# Convenience: LangChain AIMessage.usage_metadata extractor
# ---------------------------------------------------------------------------


def aimessage_usage_extractor(ctx: UsageContext) -> UsageResult | None:
    """Best-effort extractor for LangChain ``AIMessage.usage_metadata``.

    Walks ``ctx.post_values["messages"]`` from the tail looking for the newest
    message with a ``usage_metadata`` attribute shaped like::

        {"input_tokens": int, "output_tokens": int,
         "output_token_details": {"reasoning": int}, ...}

    Returns ``None`` if no matching message is found. Does **not** compute
    cost — callers who want cost should wrap this extractor and add their
    own pricing table.

    Users with custom state shapes should write their own extractor; this
    one covers the stock ``MessagesState`` / ``add_messages`` pattern.
    """
    messages = ctx.post_values.get("messages")
    if not isinstance(messages, list):
        return None

    for msg in reversed(messages):
        meta = getattr(msg, "usage_metadata", None)
        if not isinstance(meta, dict):
            continue

        prompt = int(meta.get("input_tokens", 0) or 0)
        completion = int(meta.get("output_tokens", 0) or 0)

        reasoning = 0
        details = meta.get("output_token_details")
        if isinstance(details, dict):
            reasoning = int(details.get("reasoning", 0) or 0)

        model = getattr(msg, "response_metadata", None)
        model_name = None
        if isinstance(model, dict):
            model_name = model.get("model_name") or model.get("model")

        return UsageResult(
            prompt_tokens=prompt,
            completion_tokens=completion,
            reasoning_tokens=reasoning,
            cost_usd_cents=None,
            model_name=model_name,
        )

    return None


# ---------------------------------------------------------------------------
# Native Anthropic extractor (ADR-010)
# ---------------------------------------------------------------------------


def _latest_message_with_response_metadata_key(
    ctx: UsageContext, key: str
) -> tuple[Any, dict[str, Any]] | None:
    """Return the newest message whose ``response_metadata[key]`` is a dict.

    Common helper for the native Anthropic / OpenAI extractors — they only
    differ in which key they look for under ``response_metadata``.
    """
    messages = ctx.post_values.get("messages")
    if not isinstance(messages, list):
        return None

    for msg in reversed(messages):
        meta = getattr(msg, "response_metadata", None)
        if not isinstance(meta, dict):
            continue
        payload = meta.get(key)
        if isinstance(payload, dict):
            return msg, meta
    return None


def anthropic_usage_extractor(ctx: UsageContext) -> UsageResult | None:
    """Extractor for ``AIMessage.response_metadata["usage"]`` (Anthropic-shaped).

    Reads the token counts emitted by ``langchain_anthropic.ChatAnthropic``
    and, more generally, any message that carries an Anthropic-style usage
    block under ``response_metadata["usage"]``. Field names match
    ``anthropic.types.Usage``::

        {"input_tokens": int,
         "output_tokens": int,
         "cache_creation_input_tokens": int,   # optional, prompt caching
         "cache_read_input_tokens": int}       # optional, prompt caching

    Cache-creation and cache-read counts are **added into** ``prompt_tokens``
    because Anthropic reports them separately from ``input_tokens``. This
    gives a single number the user can multiply by price-per-prompt-token.
    (Cost differentials - cache-create is +25%, cache-read is -90% - are the
    user's pricing-table concern per ADR-009.)

    Returns ``None`` if no message carries a usage block — normal for
    non-LLM nodes.
    """
    found = _latest_message_with_response_metadata_key(ctx, "usage")
    if found is None:
        return None

    _msg, meta = found
    usage = meta["usage"]  # guaranteed dict by helper
    assert isinstance(usage, dict)

    base_input = int(usage.get("input_tokens", 0) or 0)
    cache_create = int(usage.get("cache_creation_input_tokens", 0) or 0)
    cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
    completion = int(usage.get("output_tokens", 0) or 0)

    model_name = meta.get("model") or meta.get("model_name")
    if not isinstance(model_name, str):
        model_name = None

    return UsageResult(
        prompt_tokens=base_input + cache_create + cache_read,
        completion_tokens=completion,
        reasoning_tokens=0,
        cost_usd_cents=None,
        model_name=model_name,
    )


# ---------------------------------------------------------------------------
# Native OpenAI extractor (ADR-010)
# ---------------------------------------------------------------------------


def openai_usage_extractor(ctx: UsageContext) -> UsageResult | None:
    """Extractor for ``AIMessage.response_metadata["token_usage"]`` (OpenAI-shaped).

    Reads the usage block emitted by ``langchain_openai.ChatOpenAI`` and,
    more generally, any message carrying an OpenAI-style usage block under
    ``response_metadata["token_usage"]``. Field names match
    ``openai.types.CompletionUsage``::

        {"prompt_tokens": int,
         "completion_tokens": int,
         "total_tokens": int,
         "completion_tokens_details": {"reasoning_tokens": int},  # o1/o3
         "prompt_tokens_details": {"cached_tokens": int}}         # discount

    Unlike Anthropic, OpenAI **already folds** cached prompt tokens into
    ``prompt_tokens`` and reasoning tokens into ``completion_tokens``. We
    therefore surface ``reasoning_tokens`` as a sub-detail alongside the
    completion count rather than subtracting it, so the invariant
    ``prompt_tokens + completion_tokens == total_tokens`` is preserved.

    Returns ``None`` if no message carries a token_usage block — normal for
    non-LLM nodes.
    """
    found = _latest_message_with_response_metadata_key(ctx, "token_usage")
    if found is None:
        return None

    _msg, meta = found
    token_usage = meta["token_usage"]  # guaranteed dict by helper
    assert isinstance(token_usage, dict)

    prompt = int(token_usage.get("prompt_tokens", 0) or 0)
    completion = int(token_usage.get("completion_tokens", 0) or 0)

    reasoning = 0
    details = token_usage.get("completion_tokens_details")
    if isinstance(details, dict):
        reasoning = int(details.get("reasoning_tokens", 0) or 0)

    model_name = meta.get("model_name") or meta.get("model")
    if not isinstance(model_name, str):
        model_name = None

    return UsageResult(
        prompt_tokens=prompt,
        completion_tokens=completion,
        reasoning_tokens=reasoning,
        cost_usd_cents=None,
        model_name=model_name,
    )


__all__ = [
    "UsageContext",
    "UsageExtractor",
    "UsageResult",
    "aimessage_usage_extractor",
    "anthropic_usage_extractor",
    "openai_usage_extractor",
]
