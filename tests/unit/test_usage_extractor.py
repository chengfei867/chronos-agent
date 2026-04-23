"""Tests for ADR-009 usage_extractor hook and CLI surfacing.

Covers:
* ``UsageContext`` / ``UsageResult`` dataclasses are frozen & hashable-adjacent.
* ``aimessage_usage_extractor`` reads LangChain-shaped metadata.
* ``LangGraphRecorder._extract_usage`` semantics:
    - null hook → (None, None, None) fast path
    - hook returns None → (None, None, None)
    - hook returns UsageResult → tuple populated
    - hook raises → warning logged + (None, None, None)
* CLI rendering:
    - ``runs show`` JSON includes usage/cost fields
    - ``runs show`` rich tree shows "total usage:" when any node has usage
    - ``runs list --with-usage`` adds tokens/cost columns
    - ``diff --show-usage`` renders comparison table
"""

from __future__ import annotations

import json
import logging
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chronos.adapters.langgraph import LangGraphRecorder
from chronos.adapters.langgraph_usage import (
    UsageContext,
    UsageResult,
    aimessage_usage_extractor,
    anthropic_usage_extractor,
    openai_usage_extractor,
)
from chronos.cli import app
from chronos.core.models import Node, NodeKind, Run, RunStatus, Usage
from chronos.store.sqlite import SqliteStore

runner = CliRunner()


# ---------------------------------------------------------------------------
# UsageContext / UsageResult dataclass smoke
# ---------------------------------------------------------------------------


def test_usage_result_defaults() -> None:
    r = UsageResult()
    assert r.prompt_tokens == 0
    assert r.completion_tokens == 0
    assert r.reasoning_tokens == 0
    assert r.cost_usd_cents is None
    assert r.model_name is None


def test_usage_result_frozen() -> None:
    r = UsageResult(prompt_tokens=5)
    with pytest.raises(FrozenInstanceError):
        r.prompt_tokens = 9  # type: ignore[misc]


def test_usage_context_frozen() -> None:
    ctx = UsageContext(
        node_name="n",
        pre_snapshot=None,
        post_snapshot=None,
        pre_values={},
        post_values={},
        task=None,
    )
    with pytest.raises(FrozenInstanceError):
        ctx.node_name = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# aimessage_usage_extractor
# ---------------------------------------------------------------------------


class _FakeAIMessage:
    """Stand-in for langchain AIMessage — only the attributes we read."""

    def __init__(
        self,
        usage_metadata: dict | None = None,
        response_metadata: dict | None = None,
    ) -> None:
        self.usage_metadata = usage_metadata
        self.response_metadata = response_metadata


def _ctx(post_values: dict) -> UsageContext:
    return UsageContext(
        node_name="n",
        pre_snapshot=None,
        post_snapshot=None,
        pre_values={},
        post_values=post_values,
        task=None,
    )


def test_aimessage_extractor_happy_path() -> None:
    msg = _FakeAIMessage(
        usage_metadata={
            "input_tokens": 42,
            "output_tokens": 17,
            "output_token_details": {"reasoning": 3},
        },
        response_metadata={"model_name": "claude-3-5-sonnet"},
    )
    result = aimessage_usage_extractor(_ctx({"messages": [msg]}))
    assert result is not None
    assert result.prompt_tokens == 42
    assert result.completion_tokens == 17
    assert result.reasoning_tokens == 3
    assert result.model_name == "claude-3-5-sonnet"
    assert result.cost_usd_cents is None


def test_aimessage_extractor_no_messages_key() -> None:
    assert aimessage_usage_extractor(_ctx({})) is None
    assert aimessage_usage_extractor(_ctx({"messages": "not a list"})) is None


def test_aimessage_extractor_works_on_dict_coerced_messages() -> None:
    # ADR-011 regression guard: after _coerce_state dict-ifies pydantic
    # messages, aimessage_usage_extractor must still be able to read
    # usage_metadata from the dict shape. Prior to the fix this returned
    # None because getattr(dict, "usage_metadata") is always None.
    msg_dict = {
        "type": "ai",
        "content": "hello",
        "usage_metadata": {
            "input_tokens": 42,
            "output_tokens": 17,
            "output_token_details": {"reasoning": 3},
        },
        "response_metadata": {"model_name": "claude-3-5-sonnet"},
    }
    result = aimessage_usage_extractor(_ctx({"messages": [msg_dict]}))
    assert result is not None
    assert result.prompt_tokens == 42
    assert result.completion_tokens == 17
    assert result.reasoning_tokens == 3
    assert result.model_name == "claude-3-5-sonnet"


def test_aimessage_extractor_no_usage_metadata() -> None:
    msg = _FakeAIMessage(usage_metadata=None)
    assert aimessage_usage_extractor(_ctx({"messages": [msg]})) is None


def test_aimessage_extractor_picks_last_message_with_usage() -> None:
    m_old = _FakeAIMessage(usage_metadata={"input_tokens": 1, "output_tokens": 1})
    m_new = _FakeAIMessage(usage_metadata={"input_tokens": 99, "output_tokens": 100})
    result = aimessage_usage_extractor(_ctx({"messages": [m_old, m_new]}))
    assert result is not None
    assert result.prompt_tokens == 99
    assert result.completion_tokens == 100


def test_aimessage_extractor_missing_details_tolerated() -> None:
    msg = _FakeAIMessage(usage_metadata={"input_tokens": 5, "output_tokens": 7})
    result = aimessage_usage_extractor(_ctx({"messages": [msg]}))
    assert result is not None
    assert result.reasoning_tokens == 0


# ---------------------------------------------------------------------------
# anthropic_usage_extractor (ADR-010)
# ---------------------------------------------------------------------------


def test_anthropic_extractor_happy_path() -> None:
    msg = _FakeAIMessage(
        response_metadata={
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "model": "claude-3-5-sonnet-20241022",
        }
    )
    result = anthropic_usage_extractor(_ctx({"messages": [msg]}))
    assert result is not None
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 50
    assert result.reasoning_tokens == 0
    assert result.model_name == "claude-3-5-sonnet-20241022"
    assert result.cost_usd_cents is None


def test_anthropic_extractor_folds_cache_create_and_read_into_prompt() -> None:
    # Prompt caching: 100 fresh + 2000 cache-created + 500 cache-read = 2600 prompt.
    msg = _FakeAIMessage(
        response_metadata={
            "usage": {
                "input_tokens": 100,
                "output_tokens": 75,
                "cache_creation_input_tokens": 2000,
                "cache_read_input_tokens": 500,
            },
            "model": "claude-sonnet-4",
        }
    )
    result = anthropic_usage_extractor(_ctx({"messages": [msg]}))
    assert result is not None
    assert result.prompt_tokens == 2600
    assert result.completion_tokens == 75


def test_anthropic_extractor_no_messages() -> None:
    assert anthropic_usage_extractor(_ctx({})) is None
    assert anthropic_usage_extractor(_ctx({"messages": "not a list"})) is None


def test_anthropic_extractor_no_response_metadata() -> None:
    msg = _FakeAIMessage(response_metadata=None)
    assert anthropic_usage_extractor(_ctx({"messages": [msg]})) is None


def test_anthropic_extractor_no_usage_key_returns_none() -> None:
    # response_metadata present but no "usage" key — shouldn't match.
    msg = _FakeAIMessage(response_metadata={"model": "claude-3", "stop_reason": "end_turn"})
    assert anthropic_usage_extractor(_ctx({"messages": [msg]})) is None


def test_anthropic_extractor_usage_not_dict_returns_none() -> None:
    # Defensive: some adapters might stash a non-dict under usage.
    msg = _FakeAIMessage(response_metadata={"usage": "bogus"})
    assert anthropic_usage_extractor(_ctx({"messages": [msg]})) is None


def test_anthropic_extractor_malformed_values_coerced() -> None:
    # None values in the usage dict should be treated as 0, not raise.
    msg = _FakeAIMessage(
        response_metadata={
            "usage": {
                "input_tokens": None,
                "output_tokens": 42,
                "cache_creation_input_tokens": None,
            }
        }
    )
    result = anthropic_usage_extractor(_ctx({"messages": [msg]}))
    assert result is not None
    assert result.prompt_tokens == 0
    assert result.completion_tokens == 42


def test_anthropic_extractor_model_name_fallback_to_model_name_key() -> None:
    # Some wrappers surface "model_name" instead of "model".
    msg = _FakeAIMessage(
        response_metadata={
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "model_name": "claude-opus-4",
        }
    )
    result = anthropic_usage_extractor(_ctx({"messages": [msg]}))
    assert result is not None
    assert result.model_name == "claude-opus-4"


def test_anthropic_extractor_picks_newest_with_usage() -> None:
    m_old = _FakeAIMessage(response_metadata={"usage": {"input_tokens": 1, "output_tokens": 1}})
    m_new = _FakeAIMessage(response_metadata={"usage": {"input_tokens": 99, "output_tokens": 77}})
    result = anthropic_usage_extractor(_ctx({"messages": [m_old, m_new]}))
    assert result is not None
    assert result.prompt_tokens == 99
    assert result.completion_tokens == 77


# ---------------------------------------------------------------------------
# openai_usage_extractor (ADR-010)
# ---------------------------------------------------------------------------


def test_anthropic_extractor_works_on_dict_coerced_messages() -> None:
    # ADR-011 regression guard: dict form of response_metadata.
    msg_dict = {
        "type": "ai",
        "response_metadata": {
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 5,
            },
        },
    }
    result = anthropic_usage_extractor(_ctx({"messages": [msg_dict]}))
    assert result is not None
    assert result.prompt_tokens == 115  # 100 + 10 + 5
    assert result.completion_tokens == 50
    assert result.model_name == "claude-opus-4-7"


def test_openai_extractor_happy_path() -> None:
    msg = _FakeAIMessage(
        response_metadata={
            "token_usage": {
                "prompt_tokens": 120,
                "completion_tokens": 60,
                "total_tokens": 180,
            },
            "model_name": "gpt-4o-mini",
        }
    )
    result = openai_usage_extractor(_ctx({"messages": [msg]}))
    assert result is not None
    assert result.prompt_tokens == 120
    assert result.completion_tokens == 60
    assert result.reasoning_tokens == 0
    assert result.model_name == "gpt-4o-mini"
    assert result.cost_usd_cents is None


def test_openai_extractor_captures_reasoning_tokens() -> None:
    # o1/o3: reasoning_tokens is a sub-detail of completion (already folded in).
    msg = _FakeAIMessage(
        response_metadata={
            "token_usage": {
                "prompt_tokens": 50,
                "completion_tokens": 300,  # 300 already includes the 250 reasoning
                "total_tokens": 350,
                "completion_tokens_details": {"reasoning_tokens": 250},
            },
            "model_name": "o1-mini",
        }
    )
    result = openai_usage_extractor(_ctx({"messages": [msg]}))
    assert result is not None
    # Completion is NOT reduced — we preserve prompt + completion == total.
    assert result.prompt_tokens == 50
    assert result.completion_tokens == 300
    assert result.reasoning_tokens == 250


def test_openai_extractor_no_messages() -> None:
    assert openai_usage_extractor(_ctx({})) is None
    assert openai_usage_extractor(_ctx({"messages": "not a list"})) is None


def test_openai_extractor_no_response_metadata() -> None:
    msg = _FakeAIMessage(response_metadata=None)
    assert openai_usage_extractor(_ctx({"messages": [msg]})) is None


def test_openai_extractor_no_token_usage_key_returns_none() -> None:
    msg = _FakeAIMessage(response_metadata={"model_name": "gpt-4o", "finish_reason": "stop"})
    assert openai_usage_extractor(_ctx({"messages": [msg]})) is None


def test_openai_extractor_token_usage_not_dict_returns_none() -> None:
    msg = _FakeAIMessage(response_metadata={"token_usage": 42})
    assert openai_usage_extractor(_ctx({"messages": [msg]})) is None


def test_openai_extractor_malformed_completion_details_tolerated() -> None:
    # completion_tokens_details present but non-dict — don't crash.
    msg = _FakeAIMessage(
        response_metadata={
            "token_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "completion_tokens_details": "bogus",
            }
        }
    )
    result = openai_usage_extractor(_ctx({"messages": [msg]}))
    assert result is not None
    assert result.reasoning_tokens == 0


def test_openai_extractor_model_fallback_to_model_key() -> None:
    msg = _FakeAIMessage(
        response_metadata={
            "token_usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "model": "gpt-4.1",
        }
    )
    result = openai_usage_extractor(_ctx({"messages": [msg]}))
    assert result is not None
    assert result.model_name == "gpt-4.1"


# ---------------------------------------------------------------------------
# Composed fallback (Anthropic → OpenAI → AIMessage) — doc test for ADR-010
# ---------------------------------------------------------------------------


def test_composed_extractor_chain_anthropic_wins() -> None:
    """Users with mixed providers compose the three extractors."""

    def composed(ctx: UsageContext) -> UsageResult | None:
        return (
            anthropic_usage_extractor(ctx)
            or openai_usage_extractor(ctx)
            or aimessage_usage_extractor(ctx)
        )

    msg = _FakeAIMessage(response_metadata={"usage": {"input_tokens": 10, "output_tokens": 5}})
    result = composed(_ctx({"messages": [msg]}))
    assert result is not None
    assert result.prompt_tokens == 10


def test_composed_extractor_chain_openai_wins_when_no_anthropic() -> None:
    def composed(ctx: UsageContext) -> UsageResult | None:
        return (
            anthropic_usage_extractor(ctx)
            or openai_usage_extractor(ctx)
            or aimessage_usage_extractor(ctx)
        )

    msg = _FakeAIMessage(
        response_metadata={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}}
    )
    result = composed(_ctx({"messages": [msg]}))
    assert result is not None
    assert result.prompt_tokens == 7
    assert result.completion_tokens == 3


def test_composed_extractor_chain_aimessage_fallback() -> None:
    def composed(ctx: UsageContext) -> UsageResult | None:
        return (
            anthropic_usage_extractor(ctx)
            or openai_usage_extractor(ctx)
            or aimessage_usage_extractor(ctx)
        )

    msg = _FakeAIMessage(
        usage_metadata={"input_tokens": 11, "output_tokens": 22},
    )
    result = composed(_ctx({"messages": [msg]}))
    assert result is not None
    assert result.prompt_tokens == 11
    assert result.completion_tokens == 22


# ---------------------------------------------------------------------------
# LangGraphRecorder._extract_usage
# ---------------------------------------------------------------------------


class _FakeSnap:
    def __init__(self, values: dict | None = None) -> None:
        self.values = values if values is not None else {}


def _make_recorder(
    tmp_path: Path, extractor: object = None
) -> tuple[LangGraphRecorder, SqliteStore]:
    store = SqliteStore.open(tmp_path / "c.db")
    return LangGraphRecorder(store, usage_extractor=extractor), store  # type: ignore[arg-type]


def test_extract_usage_null_hook(tmp_path: Path) -> None:
    rec, store = _make_recorder(tmp_path, None)
    try:
        assert rec._extract_usage(
            node_name="n", pre=_FakeSnap(), post=_FakeSnap(), task=object()
        ) == (None, None, None)
    finally:
        store.close()


def test_extract_usage_hook_returns_none(tmp_path: Path) -> None:
    rec, store = _make_recorder(tmp_path, lambda ctx: None)
    try:
        assert rec._extract_usage(
            node_name="n", pre=_FakeSnap(), post=_FakeSnap(), task=object()
        ) == (None, None, None)
    finally:
        store.close()


def test_extract_usage_hook_success(tmp_path: Path) -> None:
    def hook(ctx: UsageContext) -> UsageResult:
        return UsageResult(
            prompt_tokens=10,
            completion_tokens=5,
            reasoning_tokens=2,
            cost_usd_cents=3,
            model_name="m",
        )

    rec, store = _make_recorder(tmp_path, hook)
    try:
        usage, cost, model = rec._extract_usage(
            node_name="n", pre=_FakeSnap(), post=_FakeSnap(), task=object()
        )
        assert usage == Usage(prompt_tokens=10, completion_tokens=5, reasoning_tokens=2)
        assert cost == 3
        assert model == "m"
    finally:
        store.close()


def test_extract_usage_hook_raise_is_swallowed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def bad_hook(ctx: UsageContext) -> UsageResult:
        raise ValueError("boom")

    rec, store = _make_recorder(tmp_path, bad_hook)
    try:
        with caplog.at_level(logging.WARNING, logger="chronos.adapters.langgraph.usage"):
            result = rec._extract_usage(
                node_name="my-node", pre=_FakeSnap(), post=_FakeSnap(), task=object()
            )
        assert result == (None, None, None)
        assert any("my-node" in rec_.message for rec_ in caplog.records)
        assert any("boom" in (rec_.exc_text or "") for rec_ in caplog.records)
    finally:
        store.close()


def test_recorder_receives_context_with_coerced_values(tmp_path: Path) -> None:
    """The extractor receives ``pre_values`` / ``post_values`` as dicts."""
    captured: dict = {}

    def hook(ctx: UsageContext) -> None:
        captured["post"] = ctx.post_values
        captured["node_name"] = ctx.node_name
        return None

    rec, store = _make_recorder(tmp_path, hook)
    try:
        rec._extract_usage(
            node_name="my-node",
            pre=_FakeSnap({"a": 1}),
            post=_FakeSnap({"b": 2}),
            task=object(),
        )
    finally:
        store.close()
    assert captured["node_name"] == "my-node"
    assert captured["post"] == {"b": 2}


# ---------------------------------------------------------------------------
# CLI rendering fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_with_usage(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A chronos.db with one run, 3 nodes (2 carry usage, 1 does not)."""
    db_path = tmp_path / "usage.db"
    t0 = datetime(2026, 4, 23, 6, 0, 0, tzinfo=UTC)
    run_id = "run-usage-1"
    store = SqliteStore.open(db_path)
    try:
        store.put_run(
            Run(
                id=run_id,
                adapter="langgraph",
                adapter_thread_id="t-u",
                status=RunStatus.COMPLETED,
                started_at=t0,
                ended_at=t0,
                task_description="usage test",
                initial_state={},
                final_state={"done": True},
                tags=[],
                metadata={},
            )
        )
        store.put_node(
            Node(
                id="n-0",
                run_id=run_id,
                step_index=0,
                node_name="llm_call_1",
                kind=NodeKind.LLM,
                parent_node_id=None,
                started_at=t0,
                ended_at=t0,
                state_after={"step": 0},
                model_name="claude-x",
                usage=Usage(prompt_tokens=100, completion_tokens=50, reasoning_tokens=10),
                cost_usd_cents=7,
                metadata={},
            )
        )
        store.put_node(
            Node(
                id="n-1",
                run_id=run_id,
                step_index=1,
                node_name="router",
                kind=NodeKind.FN,
                parent_node_id="n-0",
                started_at=t0,
                ended_at=t0,
                state_after={"step": 1},
                metadata={},
            )
        )
        store.put_node(
            Node(
                id="n-2",
                run_id=run_id,
                step_index=2,
                node_name="llm_call_2",
                kind=NodeKind.LLM,
                parent_node_id="n-1",
                started_at=t0,
                ended_at=t0,
                state_after={"step": 2},
                model_name="claude-x",
                usage=Usage(prompt_tokens=200, completion_tokens=80, reasoning_tokens=0),
                cost_usd_cents=11,
                metadata={},
            )
        )
    finally:
        store.close()
    return db_path, {"run": run_id}


@pytest.fixture
def db_with_usage_ab(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A DB with 2 runs A and B for diff --show-usage tests."""
    db_path = tmp_path / "usage_ab.db"
    t0 = datetime(2026, 4, 23, 6, 0, 0, tzinfo=UTC)
    store = SqliteStore.open(db_path)
    try:
        for run_id, final, tokens in [
            ("run-a", "expensive", (500, 200)),
            ("run-b", "cheaper", (300, 150)),
        ]:
            store.put_run(
                Run(
                    id=run_id,
                    adapter="langgraph",
                    adapter_thread_id=run_id,
                    status=RunStatus.COMPLETED,
                    started_at=t0,
                    ended_at=t0,
                    task_description="ab test",
                    initial_state={},
                    final_state={"text": final},
                    tags=[],
                    metadata={},
                )
            )
            store.put_node(
                Node(
                    id=f"{run_id}-n-0",
                    run_id=run_id,
                    step_index=0,
                    node_name="llm",
                    kind=NodeKind.LLM,
                    parent_node_id=None,
                    started_at=t0,
                    ended_at=t0,
                    state_after={"text": final},
                    model_name="x",
                    usage=Usage(
                        prompt_tokens=tokens[0],
                        completion_tokens=tokens[1],
                        reasoning_tokens=0,
                    ),
                    cost_usd_cents=tokens[0] // 100,
                    metadata={},
                )
            )
    finally:
        store.close()
    return db_path, {"a": "run-a", "b": "run-b"}


# ---------------------------------------------------------------------------
# CLI surface tests
# ---------------------------------------------------------------------------


def test_runs_show_json_includes_usage(db_with_usage: tuple[Path, dict[str, str]]) -> None:
    db, ids = db_with_usage
    result = runner.invoke(app, ["runs", "show", ids["run"], "--db", str(db), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert len(payload["nodes"]) == 3
    node_0 = payload["nodes"][0]
    assert node_0["usage"] == {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "reasoning_tokens": 10,
    }
    assert node_0["cost_usd_cents"] == 7
    assert payload["nodes"][1]["usage"] is None
    assert payload["nodes"][1]["cost_usd_cents"] is None


def test_runs_show_rich_has_total_usage(
    db_with_usage: tuple[Path, dict[str, str]],
) -> None:
    db, ids = db_with_usage
    result = runner.invoke(app, ["runs", "show", ids["run"], "--db", str(db)])
    assert result.exit_code == 0, result.stdout
    # 100+50+10 + 200+80+0 = 440 total
    assert "total usage" in result.stdout
    assert "440" in result.stdout
    # usage line for each LLM node (2 of them)
    assert result.stdout.count("usage:") >= 2


def test_runs_list_with_usage_flag(db_with_usage: tuple[Path, dict[str, str]]) -> None:
    db, _ = db_with_usage
    result = runner.invoke(app, ["runs", "list", "--with-usage", "--db", str(db)])
    assert result.exit_code == 0, result.stdout
    assert "tokens" in result.stdout
    assert "cost" in result.stdout
    assert "440" in result.stdout


def test_runs_list_with_usage_json(db_with_usage: tuple[Path, dict[str, str]]) -> None:
    db, _ = db_with_usage
    result = runner.invoke(app, ["runs", "list", "--with-usage", "--json", "--db", str(db)])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    summ = payload[0]["usage_summary"]
    assert summ["total_tokens"] == 440
    assert summ["cost_usd_cents"] == 18
    assert summ["nodes_with_usage"] == 2


def test_runs_list_without_flag_omits_usage_columns(
    db_with_usage: tuple[Path, dict[str, str]],
) -> None:
    db, _ = db_with_usage
    result = runner.invoke(app, ["runs", "list", "--db", str(db)])
    assert result.exit_code == 0
    # No 'tokens' or 'cost ¢' header present
    assert "tokens" not in result.stdout.lower().replace("thread", "")


def test_diff_show_usage_rich(db_with_usage_ab: tuple[Path, dict[str, str]]) -> None:
    db, ids = db_with_usage_ab
    result = runner.invoke(
        app, ["diff", ids["a"], ids["b"], "--show-usage", "--full", "--db", str(db)]
    )
    assert result.exit_code == 0, result.stdout
    assert "Usage comparison" in result.stdout
    # delta = 450 - 700 = -250
    assert "-250" in result.stdout  # plain hyphen-minus from str(int)


def test_diff_show_usage_json(db_with_usage_ab: tuple[Path, dict[str, str]]) -> None:
    db, ids = db_with_usage_ab
    result = runner.invoke(
        app,
        [
            "diff",
            ids["a"],
            ids["b"],
            "--show-usage",
            "--full",
            "--json",
            "--db",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert "usage" in payload
    # A: 500+200=700, B: 300+150=450, delta = -250
    assert payload["usage"]["a"]["total_tokens"] == 700
    assert payload["usage"]["b"]["total_tokens"] == 450
    assert payload["usage"]["delta_tokens"] == -250


def test_diff_without_flag_no_usage_block(
    db_with_usage_ab: tuple[Path, dict[str, str]],
) -> None:
    db, ids = db_with_usage_ab
    result = runner.invoke(
        app,
        ["diff", ids["a"], ids["b"], "--full", "--json", "--db", str(db)],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "usage" not in payload
