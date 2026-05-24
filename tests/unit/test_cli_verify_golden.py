"""Unit tests for ``chronos verify-golden`` (R104, Phase 5 Arc D slice 3).

The verb's contract is a 4-way exit-code matrix (R104 progress doc + the
``docs/contracts/golden-trace-format.md`` §6 verifier-contract amendment):

  0 — happy path: recorded run projects byte-equal to expected_run.json
       AND envelopes.jsonl is sanitiser-clean.
  1 — projection mismatch: print unified diff, return 1.
  2 — missing fixture (or unknown run id): point operator at capture driver.
  3 — sanitiser audit hit: envelopes.jsonl contains a known-secret shape;
       refuse to "verify" — re-record required.

The four tests below pin one row each. They invoke
:func:`chronos.cli.verify_golden.verify_golden_command` directly (the CLI
function under test) so we don't depend on Typer's CliRunner, mirroring the
in-place style of ``test_capture_anthropic_agents.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from rich.console import Console

from chronos.cli.verify_golden import (
    EXIT_MISMATCH,
    EXIT_MISSING_FIXTURE,
    EXIT_OK,
    EXIT_SANITISER_HIT,
    verify_golden_command,
)
from chronos.core.models import Node, NodeKind, Run, RunStatus
from chronos.golden import golden_dumps, project_to_golden
from chronos.store import SqliteStore

# ---------------------------------------------------------------------------
# Shared fixtures — synthetic 3-node Run, populated SqliteStore, golden dir
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_run_and_nodes() -> tuple[Run, list[Node]]:
    """A 3-node anthropic_agents-shaped Run mirroring the skeleton fixture."""
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    run = Run(
        id="00000000-0000-0000-0000-0000000000a4",
        adapter="anthropic_agents",
        adapter_thread_id="t-r104-test",
        status=RunStatus.COMPLETED,
        started_at=base,
        ended_at=base + timedelta(seconds=3),
        task_description="r104 verify-golden round-trip",
        initial_state={"input": "hi"},
        final_state={"output": "hello world"},
        tags=["r104"],
        metadata={"source": "r104-unit-test"},
    )
    nodes = [
        Node(
            id="aaaaaaaa-aaaa-aaaa-aaaa-000000000000",
            run_id=run.id,
            step_index=0,
            node_name="agent_start",
            kind=NodeKind.FN,
            started_at=base,
            ended_at=base + timedelta(milliseconds=10),
            state_after={"input": "hi", "tools_loaded": ["search", "lookup"]},
        ),
        Node(
            id="aaaaaaaa-aaaa-aaaa-aaaa-000000000001",
            run_id=run.id,
            step_index=1,
            node_name="chat_call",
            kind=NodeKind.LLM,
            started_at=base + timedelta(seconds=1),
            ended_at=base + timedelta(seconds=2),
            state_after={"messages": [{"role": "assistant", "content": "hello world"}]},
            model_name="claude-opus-4-7",
        ),
        Node(
            id="aaaaaaaa-aaaa-aaaa-aaaa-000000000002",
            run_id=run.id,
            step_index=2,
            node_name="agent_end",
            kind=NodeKind.END,
            started_at=base + timedelta(seconds=2, milliseconds=500),
            ended_at=base + timedelta(seconds=3),
            state_after={"output": "hello world"},
        ),
    ]
    return run, nodes


@pytest.fixture
def populated_store(tmp_path, synthetic_run_and_nodes) -> tuple[Path, str]:
    """Open a SqliteStore in tmp_path with the synthetic Run + Nodes written.

    Returns (db_path, run_id). The store is closed before returning so the
    verify_golden_command's own ``open_store_fn`` re-opens it (matching
    real-CLI behaviour where the DB is opened from a path, not a handle).
    """
    run, nodes = synthetic_run_and_nodes
    db_path = tmp_path / "chronos.db"
    store = SqliteStore.open(db_path)
    try:
        with store.transaction():
            store.put_run(run)
            for node in nodes:
                store.put_node(node)
    finally:
        store.close()
    return db_path, run.id


@pytest.fixture
def golden_dir_with_matching_fixture(tmp_path, synthetic_run_and_nodes) -> Path:
    """Build a tmp golden dir whose expected_run.json matches the run.

    Strategy: project the synthetic Run+Nodes through the *same* helpers
    the verifier uses, then write the result to disk. That guarantees a
    happy-path baseline without copying skeleton bytes around. Tampered
    / missing / leaky variants are derived from this baseline by the
    individual tests.
    """
    run, nodes = synthetic_run_and_nodes
    gdir = tmp_path / "golden_fixture"
    gdir.mkdir()
    expected = golden_dumps(project_to_golden(run, nodes))
    (gdir / "expected_run.json").write_text(expected, encoding="utf-8")
    (gdir / "envelopes.jsonl").write_text(
        # Realistic-ish 3-line envelopes shape (see tests/golden/_skeleton/);
        # content is irrelevant to the byte-compare — only INV-3 / sanitiser
        # audit reads it. A clean baseline must NOT match any pattern.
        '{"envelope": "agent_start", "node_name": "agent_start"}\n'
        '{"envelope": "llm_call", "node_name": "chat_call"}\n'
        '{"envelope": "agent_end", "node_name": "agent_end"}\n',
        encoding="utf-8",
    )
    return gdir


def _open_store_fn(db: Path | None) -> SqliteStore:
    """Mirror chronos.cli._common._open_store but without typer.Exit on miss."""
    assert db is not None, "tests always pass an explicit --db"
    return SqliteStore.open(db)


# ---------------------------------------------------------------------------
# Test 1: happy path — exit 0
# ---------------------------------------------------------------------------


def test_verify_golden_happy_path_returns_0(
    populated_store, golden_dir_with_matching_fixture
) -> None:
    db_path, run_id = populated_store
    console = Console(record=True)

    code = verify_golden_command(
        db=db_path,
        run_id=run_id,
        golden_dir=golden_dir_with_matching_fixture,
        open_store_fn=_open_store_fn,
        console=console,
    )

    assert code == EXIT_OK
    output = console.export_text()
    assert "ok:" in output
    assert run_id in output


# ---------------------------------------------------------------------------
# Test 2: mismatch path — tamper expected_run.json, expect exit 1 + diff
# ---------------------------------------------------------------------------


def test_verify_golden_mismatch_returns_1(
    populated_store, golden_dir_with_matching_fixture, capsys
) -> None:
    db_path, run_id = populated_store
    expected_path = golden_dir_with_matching_fixture / "expected_run.json"

    # Tamper: flip task_description to something that can't possibly match
    # what the recorded Run holds. (The Run.task_description is
    # "r104 verify-golden round-trip"; we substitute "tampered" here.)
    bad = expected_path.read_text(encoding="utf-8").replace(
        "r104 verify-golden round-trip", "tampered-by-test"
    )
    assert "tampered-by-test" in bad, "tamper sanity check"
    expected_path.write_text(bad, encoding="utf-8")

    console = Console(record=True)
    code = verify_golden_command(
        db=db_path,
        run_id=run_id,
        golden_dir=golden_dir_with_matching_fixture,
        open_store_fn=_open_store_fn,
        console=console,
    )

    assert code == EXIT_MISMATCH
    rich_output = console.export_text()
    assert "mismatch:" in rich_output
    # The unified diff goes to plain stdout (not Rich), so capsys catches it.
    captured = capsys.readouterr()
    assert "tampered-by-test" in captured.out
    assert "r104 verify-golden round-trip" in captured.out


# ---------------------------------------------------------------------------
# Test 3: missing fixture — exit 2 + "re-record" hint
# ---------------------------------------------------------------------------


def test_verify_golden_missing_fixture_returns_2(populated_store, tmp_path) -> None:
    db_path, run_id = populated_store
    # Point at a directory that doesn't exist at all. The verifier must
    # exit 2 BEFORE it tries to open the SqliteStore — the missing-fixture
    # gate runs first.
    nonexistent_dir = tmp_path / "no_such_golden_dir"
    assert not nonexistent_dir.exists()

    console = Console(record=True)
    code = verify_golden_command(
        db=db_path,
        run_id=run_id,
        golden_dir=nonexistent_dir,
        open_store_fn=_open_store_fn,
        console=console,
    )

    assert code == EXIT_MISSING_FIXTURE
    output = console.export_text()
    assert "golden-dir not found" in output
    assert "scripts/capture/" in output


# ---------------------------------------------------------------------------
# Test 4: sanitiser hit at load-time — exit 3 ("suspenders" gate)
# ---------------------------------------------------------------------------


def test_verify_golden_sanitiser_hit_returns_3(
    populated_store, golden_dir_with_matching_fixture
) -> None:
    """Inject a synthetic ``sk-ant-...`` token *post-capture* into the on-disk
    envelopes.jsonl. The capture driver's belt-layer would have caught this
    on write, but our test simulates a leaked or hand-edited fixture: the
    suspenders layer (this verb's load-time audit) must refuse to verify.
    """
    db_path, run_id = populated_store
    envelopes_path = golden_dir_with_matching_fixture / "envelopes.jsonl"

    # Craft a synthetic Anthropic-key shape (matches _SECRET_PATTERNS[0]:
    # ``sk-ant-[A-Za-z0-9_-]{20,}``). Use deliberately fake characters so
    # nothing real ever pings — just regex-equivalent.
    leaky = (
        envelopes_path.read_text(encoding="utf-8")
        + '{"envelope": "tool_use", "headers": '
        + '{"x-api-key": "sk-ant-api03-FAKE0000fakeFAKE0000fakeFAKE0000fake"}}\n'
    )
    envelopes_path.write_text(leaky, encoding="utf-8")

    console = Console(record=True)
    code = verify_golden_command(
        db=db_path,
        run_id=run_id,
        golden_dir=golden_dir_with_matching_fixture,
        open_store_fn=_open_store_fn,
        console=console,
    )

    assert code == EXIT_SANITISER_HIT
    output = console.export_text()
    # The error message names the matched pattern so the operator knows
    # which capture-time rule failed and what to look for.
    assert "ANTHROPIC_KEY" in output
    assert "re-record" in output
