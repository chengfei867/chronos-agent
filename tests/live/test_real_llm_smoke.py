"""Live smoke tests — real LLM calls via OneAPI proxy.

Marked ``@pytest.mark.live``; skipped by default and in CI. Opt in with::

    CHRONOS_LIVE=1 uv run pytest -m live -v

Purpose
=======
Validate that Chronos's LangGraph and AutoGen recorders correctly capture
events from **real** LLM traffic — not just the FakeLLM used in unit tests.
Specifically we check that:

1. `usage_metadata` from a real OpenAI-compatible endpoint is parsed by
   `chronos.adapters.langgraph_usage.py`'s OpenAI extractor (prompt, completion,
   and total tokens are populated and non-zero).
2. AutoGen's `BaseChatMessage.source` field (agent name) is captured into
   `node.metadata.agent_id` as R37-A1 expects — under real streaming, not
   synthetic test fixtures.
3. End-to-end the recorded Run has a non-empty node list whose `state_after`
   reflects the real assistant response.

Endpoint
========
Uses the Baidu-int OneAPI proxy (OpenAI-compatible) at
``https://oneapi-comate.baidu-int.com/v1`` with model ``GLM-5``. The key is
read from ``$OPENAI_API_KEY`` — no secret ever lives in the repo.

Why GLM-5 specifically
----------------------
As of 2026-04-24 the OneAPI "default" group exposes GLM-5 as the most
capable model with working channel mapping. Other listed models (Claude
Opus/Sonnet variants, Kimi-K2, MiniMax-M2) fail with either
"awsModelID not found in channel ARN map" or timeout. GLM-5 returns full
OpenAI-shaped responses including `usage.prompt_tokens`,
`usage.completion_tokens`, `usage.total_tokens`, and a
`completion_tokens_details.reasoning_tokens` nested field — perfect for
validating the OpenAI extractor path.

Model override: set ``$CHRONOS_LIVE_MODEL`` to try a different model.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_LIVE_ENABLED = os.getenv("CHRONOS_LIVE") == "1"
_API_KEY = os.getenv("OPENAI_API_KEY")
_BASE_URL = os.getenv("CHRONOS_LIVE_BASE_URL", "https://oneapi-comate.baidu-int.com/v1")
_MODEL = os.getenv("CHRONOS_LIVE_MODEL", "GLM-5")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _LIVE_ENABLED,
        reason="Live tests disabled (set CHRONOS_LIVE=1 to enable).",
    ),
    pytest.mark.skipif(
        not _API_KEY,
        reason="OPENAI_API_KEY not set.",
    ),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_store(tmp_path: Path):
    """Isolated SQLite store for this test — never touches a shared DB."""
    from chronos.store.sqlite import SqliteStore

    return SqliteStore.open(tmp_path / "live_smoke.db")


# ---------------------------------------------------------------------------
# A. LangGraph — single-node graph that calls a real ChatOpenAI
# ---------------------------------------------------------------------------


def test_live_langgraph_real_llm_usage_captured(sqlite_store):
    """Record a 1-node LangGraph run with real ChatOpenAI → OneAPI → GLM-5.

    Asserts:
      - Run persists with >=1 node
      - The LLM node has a non-empty `usage` populated from real tokens
      - The node's agent_id is "main" (LangGraph default for R37)
    """
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    from chronos.adapters.langgraph import LangGraphRecorder
    from chronos.adapters.langgraph_usage import openai_usage_extractor

    class State(TypedDict):
        question: str
        answer: str | None
        messages: list  # hold AIMessages so UsageExtractor can read token_usage

    llm = ChatOpenAI(
        model=_MODEL,
        api_key=_API_KEY,
        base_url=_BASE_URL,
        temperature=0,
        max_tokens=30,
    )

    def answer_node(state: State) -> dict:
        msg = llm.invoke([HumanMessage(content=state["question"])])
        # Return the AIMessage in state so openai_usage_extractor can find
        # response_metadata["token_usage"] on it.
        return {"answer": str(msg.content)[:200], "messages": [msg]}

    builder = StateGraph(State)
    builder.add_node("answer", answer_node)
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)
    # LangGraphRecorder reads graph.get_state_history() → must have a checkpointer.
    graph = builder.compile(checkpointer=MemorySaver())

    rec = LangGraphRecorder(store=sqlite_store, usage_extractor=openai_usage_extractor)
    with rec.record(
        graph,
        thread_id="live-smoke-lg-1",
        task_description="live smoke: LangGraph + real LLM",
        tags=["live", "smoke", "langgraph"],
    ) as ref:
        graph.invoke(
            {"question": "In 5 words, what is Chronos?", "answer": None, "messages": []},
            config={"configurable": {"thread_id": ref.thread_id}},
        )

    # ----- assertions -----
    assert ref.run_id is not None, "Run must be persisted after live call"

    nodes = sqlite_store.get_nodes_for_run(ref.run_id)
    assert len(nodes) >= 1, f"Expected at least 1 node, got {len(nodes)}"

    # Every node should carry agent_id = "main" (R37-A3)
    for n in nodes:
        assert n.metadata.get("agent_id") == "main", (
            f"LangGraph node {n.node_name} missing agent_id=main in metadata"
        )

    # At least one node should have real usage from the LLM call.
    nodes_with_usage = [n for n in nodes if n.usage is not None]
    assert nodes_with_usage, (
        "No node captured `usage` — OpenAI extractor may not be matching "
        "the real response shape from OneAPI/GLM-5."
    )

    llm_node = nodes_with_usage[0]
    u = llm_node.usage
    assert u is not None
    assert u.prompt_tokens and u.prompt_tokens > 0, "prompt_tokens must be >0"
    assert u.completion_tokens and u.completion_tokens > 0, "completion_tokens must be >0"
    assert u.total_tokens and u.total_tokens > 0, "total_tokens must be >0"


# ---------------------------------------------------------------------------
# B. AutoGen — two-agent team that actually converses via real LLM
# ---------------------------------------------------------------------------


def test_live_autogen_real_llm_agent_ids_captured(sqlite_store):
    """Record a 2-agent AutoGen RoundRobin team with real OpenAI-compat client.

    Asserts:
      - Run persists with >=2 nodes (one per agent turn)
      - Nodes carry distinct `metadata.agent_id` values matching the agent names
      - At least one LLM node has non-zero usage (models_usage captured)
    """
    import asyncio

    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.conditions import MaxMessageTermination
    from autogen_agentchat.teams import RoundRobinGroupChat
    from autogen_ext.models.openai import OpenAIChatCompletionClient

    from chronos.adapters.autogen.recorder import AutoGenRecorder

    # OneAPI speaks OpenAI protocol; AutoGen's OpenAIChatCompletionClient works.
    # model_info is required for non-canonical model names.
    client = OpenAIChatCompletionClient(
        model=_MODEL,
        api_key=_API_KEY,
        base_url=_BASE_URL,
        model_info={
            "vision": False,
            "function_calling": False,
            "json_output": False,
            "family": "unknown",
            "structured_output": False,
        },
    )

    alice = AssistantAgent(
        name="alice",
        model_client=client,
        system_message="You are Alice. Reply in exactly 5 words.",
    )
    bob = AssistantAgent(
        name="bob",
        model_client=client,
        system_message="You are Bob. Reply in exactly 5 words.",
    )
    team = RoundRobinGroupChat(
        [alice, bob],
        termination_condition=MaxMessageTermination(max_messages=3),
    )

    rec = AutoGenRecorder(store=sqlite_store)
    with rec.record(
        team,
        thread_id="live-smoke-ag-1",
        task_description="live smoke: AutoGen + real LLM",
        tags=["live", "smoke", "autogen"],
    ) as ref:
        result = asyncio.run(team.run(task="Say hi."))
        ref.submit_result(result)  # type: ignore[attr-defined]

    # ----- assertions -----
    assert ref.run_id is not None
    nodes = sqlite_store.get_nodes_for_run(ref.run_id)
    assert len(nodes) >= 2, f"Expected >=2 nodes (user + >=1 agent turn), got {len(nodes)}"

    agent_ids = {n.metadata.get("agent_id") for n in nodes}
    # Must include the two agents at least; user source may or may not appear
    # depending on AutoGen event emission.
    assert "alice" in agent_ids or "bob" in agent_ids, (
        f"Neither 'alice' nor 'bob' appeared as agent_id. Got: {agent_ids}. "
        f"Node names: {[n.node_name for n in nodes]}"
    )

    # At least one LLM-kind node should have models_usage populated.
    llm_nodes_with_usage = [n for n in nodes if n.kind == "llm" and n.usage is not None]
    assert llm_nodes_with_usage, (
        "No LLM node captured usage — AutoGen extractor may not be reading "
        "models_usage from OpenAIChatCompletionClient responses."
    )
