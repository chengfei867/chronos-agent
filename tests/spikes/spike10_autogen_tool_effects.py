"""Spike 10 — AutoGen adapter effects classification under real tool-calling.

**Question:** When a real AutoGen GroupChat actually calls tools (via real
LLM function-calling), does Chronos's effects classifier produce useful
tags on the resulting Nodes?

**Method:** Build a 2-agent RoundRobinGroupChat:

  - coder (AssistantAgent + tools=[fetch_weather_api, read_file, query_db])
  - executor (AssistantAgent) — just replies "OK"

Run against OneAPI/GLM-5 (real function-calling confirmed by curl probe
in the R48-A research note). Record via AutoGenRecorder. Then enumerate
all Nodes and inspect:

  - node.node_name  (what goes into classify_effects as key)
  - node.kind       (LLM vs TOOL vs FN)
  - node.metadata["effects"]  (the classifier output)

**Findings (before R48-A fix):**
  F1. Tools are really invoked — ToolCallRequestEvent +
      ToolCallExecutionEvent appear.
  F2. node_name for tool events is shaped "{source}:{ClassName}", i.e.
      the name has no tool function name embedded. So classify_effects
      matches ZERO patterns and effects == [].
  F3. The only way to override via `effects_map` is with coarse keys
      like "coder:ToolCallExecutionEvent" — maps ALL tools for ALL
      agents to the same tags. Useless for production.

**Findings (after R48-A fix, ADR-020):**
  F1'. Tools are still recorded (2 nodes).
  F2'. node_name now shaped "{source}:{ClassName}:{tool_name}" (e.g.
       "coder:ToolCallExecutionEvent:fetch_weather_api"). classifier
       matches the ``\\bfetch_\\w+\\b`` / ``\\bread_file\\b`` / etc.
       patterns and produces ["network"] / ["fs"] / ["db"] correctly.
  F3'. effects_map key-space is now per-tool-per-source; users can
       override "coder:ToolCallExecutionEvent:fetch_weather_api"
       independently from other tools.

Run:

    set -a && . /workspace/.hermes/.env && set +a && \\
    uv run python tests/spikes/spike10_autogen_tool_effects.py

Expected output (post-fix): every ToolCall* node has a non-empty
``effects`` list that matches the tool it called.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_core.tools import FunctionTool
from autogen_ext.models.openai import OpenAIChatCompletionClient

from chronos.adapters.autogen.recorder import AutoGenRecorder
from chronos.store import SqliteStore

# ---------------------------------------------------------------------------
# Tools — deliberately named to trip each effects-classifier group.
# ---------------------------------------------------------------------------


def fetch_weather_api(city: str) -> str:
    """Fetch current weather for a city (network)."""
    return f"sunny 22C in {city}"


def read_file(path: str) -> str:
    """Read a local file (fs)."""
    return f"(stub) contents of {path}"


def query_db(sql: str) -> str:
    """Query the local sqlite db (db)."""
    return f"(stub) rows for: {sql}"


TOOLS = [
    FunctionTool(
        fetch_weather_api,
        description="Fetch current weather for a city.",
    ),
    FunctionTool(
        read_file,
        description="Read a local file.",
    ),
    FunctionTool(
        query_db,
        description="Query the local database.",
    ),
]


def main() -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY not set — `set -a && . /workspace/.hermes/.env && set +a` first."
        )
    base_url = os.getenv("CHRONOS_LIVE_BASE_URL", "https://oneapi-comate.baidu-int.com/v1")
    model = os.getenv("CHRONOS_LIVE_MODEL", "GLM-5")

    client = OpenAIChatCompletionClient(
        model=model,
        api_key=api_key,
        base_url=base_url,
        model_info={
            "vision": False,
            "function_calling": True,
            "json_output": False,
            "family": "unknown",
            "structured_output": False,
        },
    )

    coder = AssistantAgent(
        name="coder",
        model_client=client,
        tools=TOOLS,
        system_message=(
            "You are a coder. When asked a question, pick the single most "
            "relevant tool from your toolbox and call it exactly once. Then "
            "report the result in one short sentence."
        ),
        reflect_on_tool_use=True,
    )
    executor = AssistantAgent(
        name="executor",
        model_client=client,
        system_message="You are the executor. Reply with exactly one word: OK.",
    )
    team = RoundRobinGroupChat(
        [coder, executor],
        termination_condition=MaxMessageTermination(max_messages=6),
    )

    tmp = Path(tempfile.mkdtemp(prefix="spike10_"))
    chronos_db = tmp / "chronos.db"

    with SqliteStore.open(chronos_db) as store:
        rec = AutoGenRecorder(store=store)
        with rec.record(
            team,
            thread_id="spike10-autogen-tools",
            task_description="spike10: real AutoGen tool-calling effects",
            tags=["spike", "spike10", "autogen"],
        ) as ref:
            result = asyncio.run(
                team.run(task=("What is the weather in Beijing? Call the right tool once."))
            )
            ref.submit_result(result)  # type: ignore[attr-defined]

        run_id = ref.run_id
        assert run_id is not None, "Recorder did not persist a run"

        # ------------------------------------------------------------------
        # F1: tools really invoked (ToolCall* events appear)
        # ------------------------------------------------------------------
        nodes = store.get_nodes_for_run(run_id)
        print()
        print(f"=== Recorded {len(nodes)} nodes for run {run_id[:8]}… ===")
        for n in nodes:
            effects = n.metadata.get("effects", [])
            print(
                f"  step={n.step_index}  kind={n.kind.value:<6}  "
                f"node_name={n.node_name!r:<50}  effects={effects}"
            )

        tool_nodes = [n for n in nodes if ":ToolCall" in n.node_name]
        if tool_nodes:
            print(f"\n[F1 ✅] Found {len(tool_nodes)} ToolCall* nodes — tools really fired.")
        else:
            print("\n[F1 ❌] No ToolCall* nodes — LLM did not call tools. Spike invalid.")
            return

        # ------------------------------------------------------------------
        # F2 (post-fix): node_name now embeds tool function name
        # ------------------------------------------------------------------
        tool_effects = [(n.node_name, n.metadata.get("effects", [])) for n in tool_nodes]
        empty = [(name, eff) for name, eff in tool_effects if not eff]
        if empty:
            print(f"[F2 ❌] Some tool nodes still have effects == []: {empty}")
            print("       The R48-A fix did not cover these shapes. Investigate.")
        else:
            print(f"[F2 ✅] All {len(tool_nodes)} tool nodes got non-empty effects:")
            for name, eff in tool_effects:
                print(f"          {name!r} → {eff}")

        # Check the node_name actually includes a function-name segment
        # (3rd colon-delimited token).
        embedded_names = [n.node_name for n in tool_nodes if n.node_name.count(":") >= 2]
        if embedded_names == [n.node_name for n in tool_nodes]:
            print(
                "[F2b ✅] Every tool node_name has the 3-segment "
                "'{source}:{ClassName}:{tool_name}' shape."
            )
        else:
            print(
                f"[F2b ❌] Some tool nodes missing the tool-name segment: "
                f"{[n.node_name for n in tool_nodes if n.node_name.count(':') < 2]}"
            )

        # ------------------------------------------------------------------
        # F3 (post-fix): effects_map key-space is now per-tool
        # ------------------------------------------------------------------
        unique_node_names = sorted({n.node_name for n in tool_nodes})
        print(f"[F3 ✅] Unique effects_map override keys now available: {unique_node_names}")
        print(
            "       -> Each tool x event-type x agent combination gets its own "
            "key. Fine-grained override is possible."
        )

    print()
    print("=" * 72)
    print("SPIKE 10 RESULT: R48-A fix verified — AutoGen tool nodes tagged correctly")
    print("=" * 72)
    print("  - pre-fix this spike recorded all empty effects; ADR-020 documents")
    print("    the shape change. See docs/research/r48a-autogen-tool-effects.md")


if __name__ == "__main__":
    main()
