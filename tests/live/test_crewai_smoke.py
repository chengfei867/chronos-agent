"""Live smoke test — real LLM CrewAI record path.

Wraps the F1-F6 checks from ``tests/spikes/spike13_crewai_tool_effects.py``
into a ``@pytest.mark.live`` assertion harness so v0.4.0+ CI (when
opted in with ``CHRONOS_LIVE=1``) carries a persistent guard that the
CrewAI adapter (ADR-021, R52 scaffold) still drains real events end
to end.

Opt-in::

    set -a && . /workspace/.hermes/.env && set +a
    CHRONOS_LIVE=1 CREWAI_DISABLE_TELEMETRY=1 OTEL_SDK_DISABLED=true \\
      .venv/bin/pytest tests/live/test_crewai_smoke.py -m live -v

Wall-clock: ~30-60s (1 real LLM crew kickoff via OneAPI ``GLM-5``).
Skipped by default and in CI; see ``pyproject.toml::pytest.markers``
for the ``live`` marker.

Scope (mirrors R54 spike13 F1-F6):

  - **F1** — ``crewai_event_bus._handlers`` registry identical pre
    vs post ``record()`` CM (no handler leak, per ADR-021 §D1).
  - **F2** — Recorded Run has ≥ 4 nodes (Task* + ToolUsage* +
    LLMCall* in some combination; ≥ 4 is a safe floor; 13 observed
    in R54).
  - **F3** — Every ``ToolUsage*`` node whose ``tool_name`` is in
    ``{fetch_weather_api, read_file, query_db}`` carries the
    expected effect group tag (``network`` / ``fs`` / ``db``).
  - **F4** — Soft: every ``LLMCallCompletedEvent`` node with
    non-None usage carries ``prompt_tokens >= 0`` and
    ``completion_tokens >= 0``. If all usages are None, skip
    (ADR-021 §D7 explicitly tolerates this on some channels).
  - **F5** — ``id(crew)`` preserved pre/post record (ADR-016 A5 /
    ADR-021 §D6, recorder does not wrap/mutate the crew).
  - **F6** — ``chronos runs list --db <path>`` and
    ``chronos runs show <id>`` both exit 0 against the live DB.

Environment requirements:

  - ``CHRONOS_LIVE=1`` (set by the opt-in command above).
  - ``$OPENAI_API_KEY`` pointing at OneAPI (the shared ``.env``).
  - ``crewai`` importable (R53 pin: ``>=0.80,<2.0``).
  - Optional: ``$CHRONOS_LIVE_MODEL`` (default ``GLM-5``),
    ``$CHRONOS_LIVE_BASE_URL`` (default OneAPI).

This test is intentionally one-shot (one kickoff) — we rely on a
single crew run to exercise the recorder path, not on exhaustive
tool coverage. Unit-level effect-classifier coverage lives in
``tests/unit/test_effects.py`` (R44-A).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_LIVE_ENABLED = os.getenv("CHRONOS_LIVE") == "1"
_API_KEY = os.getenv("OPENAI_API_KEY")
_BASE_URL = os.getenv("CHRONOS_LIVE_BASE_URL", "https://oneapi-comate.baidu-int.com/v1")
_MODEL = os.getenv("CHRONOS_LIVE_MODEL", "GLM-5")

# Defensive: telemetry off *before* any crewai import anywhere in this
# process. conftest + other live tests may have triggered the import
# already; this is idempotent.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "1")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")


def _crewai_importable() -> bool:
    try:
        import crewai  # noqa: F401
    except Exception:
        return False
    return True


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
    pytest.mark.skipif(
        not _crewai_importable(),
        reason="crewai not installed in this environment.",
    ),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_store(tmp_path: Path):
    """Isolated SQLite store — never touches a shared DB."""
    from chronos.store.sqlite import SqliteStore

    return SqliteStore.open(tmp_path / "crewai_smoke.db")


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_crewai_tool_effects_smoke(sqlite_store, tmp_path: Path) -> None:
    """Real CrewAI crew + real LLM + CrewAIRecorder -- F1-F6 from spike13.

    See module docstring for the per-assertion contract. This is a
    direct port of ``tests/spikes/spike13_crewai_tool_effects.py::main``
    with ``print`` output replaced by ``assert``/``pytest.skip``.
    """
    from crewai import LLM, Agent, Crew, Process, Task
    from crewai.events import crewai_event_bus
    from crewai.tools import tool

    from chronos.adapters.crewai import crewai_adapter

    # -----------------------------------------------------------------
    # Tools — names are load-bearing (effects classifier regexes).
    # -----------------------------------------------------------------
    @tool("fetch_weather_api")
    def fetch_weather_api(city: str) -> str:
        """Network-effect tool (stubbed)."""
        return f"sunny 22C in {city}"

    @tool("read_file")
    def read_file(path: str) -> str:
        """FS-effect tool (stubbed)."""
        return f"(stub) contents of {path}: weather records from last week."

    @tool("query_db")
    def query_db(sql: str) -> str:
        """DB-effect tool (stubbed)."""
        return f"(stub) rows for: {sql}"

    # -----------------------------------------------------------------
    # LLM — native `openai` provider (bypasses CrewAI's model-constants
    # validator; GLM-5 isn't in the OpenAI constants table, so without
    # provider="openai" explicitly, CrewAI would fall through to
    # LiteLLM). See R54 CONTEXT §5 "OneAPI + CrewAI" recipe.
    # -----------------------------------------------------------------
    llm = LLM(
        model=_MODEL,
        provider="openai",
        api_key=_API_KEY,
        base_url=_BASE_URL,
    )

    investigator = Agent(
        role="investigator",
        goal=(
            "Answer the user question by calling exactly one tool, then report the result tersely."
        ),
        backstory=(
            "You are a pragmatic investigator. You call exactly one "
            "tool per task, then report the raw result in one sentence. "
            "No commentary."
        ),
        tools=[fetch_weather_api, read_file, query_db],
        llm=llm,
        allow_delegation=False,
        verbose=False,
        max_iter=3,
    )
    summarizer = Agent(
        role="summarizer",
        goal="Summarize the investigator's finding in one sentence.",
        backstory=("You read what the investigator said and restate it in one short sentence."),
        llm=llm,
        allow_delegation=False,
        verbose=False,
        max_iter=2,
    )

    investigate_task = Task(
        description=(
            "What is the weather in Beijing right now? Call the most "
            "appropriate tool from your toolbox exactly once, then "
            "state the tool's raw output verbatim."
        ),
        expected_output="The raw string returned by the tool.",
        agent=investigator,
    )
    summarize_task = Task(
        description=("Restate what the investigator reported in one short sentence."),
        expected_output="One short English sentence.",
        agent=summarizer,
    )

    crew = Crew(
        agents=[investigator, summarizer],
        tasks=[investigate_task, summarize_task],
        process=Process.sequential,
        verbose=False,
    )
    crew_id_before = id(crew)

    # -----------------------------------------------------------------
    # F1 pre-snapshot of the event-bus handler registry.
    # -----------------------------------------------------------------
    raw_pre = getattr(crewai_event_bus, "_handlers", None)
    pre_registry_keys = list(raw_pre) if raw_pre is not None else None

    # -----------------------------------------------------------------
    # Record!
    # -----------------------------------------------------------------
    rec = crewai_adapter.build_recorder(sqlite_store)
    with rec.record(
        crew,
        thread_id="live-smoke-crewai-1",
        task_description="live smoke: CrewAI + real LLM",
        tags=["live", "smoke", "crewai"],
    ) as ref:
        result = crew.kickoff(inputs={})
        ref.submit_result(result)  # type: ignore[attr-defined]

    # -----------------------------------------------------------------
    # F1 post-snapshot — registry keys unchanged.
    # -----------------------------------------------------------------
    raw_post = getattr(crewai_event_bus, "_handlers", None)
    post_registry_keys = list(raw_post) if raw_post is not None else None

    # If the private attr is accessible on both sides, assert structural
    # equality. If either side is None (future CrewAI rename), fall
    # back to the indirect signal: the CM exited without raising, which
    # is itself a signal that `scoped_handlers()` tore down cleanly.
    if pre_registry_keys is not None and post_registry_keys is not None:
        assert pre_registry_keys == post_registry_keys, (
            f"F1 handler leak: registry keys differ pre vs post record() "
            f"CM. pre={pre_registry_keys}, post={post_registry_keys}"
        )

    # -----------------------------------------------------------------
    # F5 — crew identity preserved (no wrap/replace by recorder).
    # -----------------------------------------------------------------
    assert id(crew) == crew_id_before, (
        f"F5: crew identity changed across record() CM (before={crew_id_before}, after={id(crew)})"
    )

    # -----------------------------------------------------------------
    # F2 — node floor.
    # -----------------------------------------------------------------
    run_id = ref.run_id
    assert run_id is not None, "Recorder did not persist a run"
    nodes = sqlite_store.get_nodes_for_run(run_id)
    assert len(nodes) >= 4, (
        f"F2: expected ≥ 4 nodes from the real crew run, got {len(nodes)}. "
        f"Node names: {[n.node_name for n in nodes]}"
    )

    # -----------------------------------------------------------------
    # F3 — every ToolUsage* node whose tool_name is one we ship must
    # carry the expected effect tag.
    # -----------------------------------------------------------------
    expected_effect_for = {
        "fetch_weather_api": "network",
        "read_file": "fs",
        "query_db": "db",
    }
    tool_nodes = [
        n
        for n in nodes
        if "ToolUsageStartedEvent" in n.node_name or "ToolUsageFinishedEvent" in n.node_name
    ]
    assert tool_nodes, (
        "F3: no ToolUsage* nodes at all — the LLM did not call a tool, "
        "or the recorder is not subscribed to ToolUsage* events. "
        f"Node names seen: {[n.node_name for n in nodes]}"
    )

    f3_failures: list[str] = []
    for n in tool_nodes:
        tool_name = n.metadata.get("tool_name")
        if tool_name not in expected_effect_for:
            # Unexpected tool name — skip silently; this is not a
            # classifier contract violation (R54 found LLMs pick only
            # 1/3 of the tools in a single kickoff).
            continue
        effects = n.metadata.get("effects", []) or []
        want = expected_effect_for[tool_name]
        if want not in effects:
            f3_failures.append(
                f"{n.node_name!r} (tool_name={tool_name!r}) expected "
                f"{want!r} in effects, got {effects}"
            )
    assert not f3_failures, "F3 effect-tag mismatches:\n  " + "\n  ".join(f3_failures)

    # -----------------------------------------------------------------
    # F4 — LLMCallCompletedEvent usage: soft assertion. Skip if usage
    # is uniformly None on this channel (ADR-021 §D7 tolerance).
    # -----------------------------------------------------------------
    llm_completed = [n for n in nodes if "LLMCallCompletedEvent" in n.node_name]
    if not llm_completed:
        pytest.skip(
            "F4: no LLMCallCompletedEvent nodes observed — tolerated "
            "per ADR-021 §D7 caveat (some provider paths don't emit "
            "this event)."
        )
    llm_with_usage = [n for n in llm_completed if n.usage is not None]
    if not llm_with_usage:
        pytest.skip(
            f"F4: all {len(llm_completed)} LLMCallCompletedEvent nodes "
            "had usage=None — tolerated per ADR-021 §D7 (OneAPI channel "
            "may not populate usage on some routes)."
        )
    for n in llm_with_usage:
        u = n.usage
        assert u is not None  # narrow for mypy
        assert (u.prompt_tokens or 0) >= 0, (
            f"F4: {n.node_name!r} has negative prompt_tokens={u.prompt_tokens}"
        )
        assert (u.completion_tokens or 0) >= 0, (
            f"F4: {n.node_name!r} has negative completion_tokens={u.completion_tokens}"
        )

    # -----------------------------------------------------------------
    # F6 — CLI `runs list` + `runs show` against the live-recorded DB.
    # We must first close the SqliteStore so the file is fully flushed
    # before the subprocess reads it (matches spike13's ordering).
    # -----------------------------------------------------------------
    sqlite_store.close()

    db_path = tmp_path / "crewai_smoke.db"
    assert db_path.exists(), f"F6: expected DB at {db_path} to exist for CLI subprocess"

    def _cli(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [".venv/bin/chronos", *args],
            capture_output=True,
            text=True,
            cwd=os.getcwd(),
            check=False,
            timeout=30,
        )

    list_proc = _cli("runs", "list", "--db", str(db_path))
    assert list_proc.returncode == 0, (
        f"F6a: `chronos runs list` exited {list_proc.returncode}\n"
        f"  stdout: {list_proc.stdout[:500]}\n"
        f"  stderr: {list_proc.stderr[:500]}"
    )
    assert run_id[:8] in list_proc.stdout, (
        f"F6a: `chronos runs list` stdout did not mention run_id prefix "
        f"{run_id[:8]!r}. stdout:\n{list_proc.stdout[:500]}"
    )

    show_proc = _cli("runs", "show", run_id, "--db", str(db_path))
    assert show_proc.returncode == 0, (
        f"F6b: `chronos runs show {run_id}` exited {show_proc.returncode}\n"
        f"  stdout: {show_proc.stdout[:500]}\n"
        f"  stderr: {show_proc.stderr[:500]}"
    )
