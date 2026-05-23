"""Unit tests for ``scripts/capture/capture_anthropic_agents.py`` (R101).

Exercises the capture driver against an in-memory SqliteStore populated with
synthetic Nodes — no live API call, no CHRONOS_LIVE needed in CI.

What this pins
--------------
1. ``capture_run()`` round-trips an in-memory ``Run`` + ``Nodes`` into the
   v0 fixture pair shape (envelopes.jsonl + expected_run.json) under a
   tmp_path.
2. The reference projection helpers in the capture driver (``project_to_golden``,
   ``_canonicalise``, ``golden_dumps``, ``sanitise_capture``) produce
   **byte-identical** output to spike 19's helpers on the spike's synthetic
   3-envelope fixture. This is the slot-2 Option A safety net: when R102
   hoists the helpers to ``src/chronos/golden/``, the consolidation must not
   change a single byte. If a future edit drifts either copy, this test
   fails immediately.
3. Adapter-mismatch + missing-run + zero-nodes error paths.
4. Sanitiser actually runs (a synthetic ``sk-ant-...`` token in
   ``state_after`` is redacted before bytes hit disk).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DRIVER_PATH = _REPO_ROOT / "scripts" / "capture" / "capture_anthropic_agents.py"
_SPIKE_PATH = _REPO_ROOT / "tests" / "spikes" / "spike19_golden_trace_invariants.py"


def _load_module(path: Path, name: str):
    """Load a non-package Python file as a module (for spike + driver imports)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def driver():
    return _load_module(_DRIVER_PATH, "_chronos_capture_anthropic_agents_under_test")


@pytest.fixture(scope="module")
def spike():
    return _load_module(_SPIKE_PATH, "_chronos_spike19_under_test")


@pytest.fixture
def synthetic_run_and_nodes():
    """A 3-node anthropic_agents Run mirroring the skeleton fixture shape."""
    from chronos.core.models import Node, NodeKind, Run, RunStatus

    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    run = Run(
        id="00000000-0000-0000-0000-000000000001",
        adapter="anthropic_agents",
        adapter_thread_id="t-r101-test",
        status=RunStatus.COMPLETED,
        started_at=base,
        ended_at=base + timedelta(seconds=3),
        task_description="r101 unit-test capture round-trip",
        initial_state={"input": "hi"},
        final_state={"output": "hello world"},
        tags=["r101"],
        metadata={"source": "r101-unit-test"},
    )
    nodes = [
        Node(
            id="11111111-1111-1111-1111-000000000000",
            run_id=run.id,
            step_index=0,
            node_name="agent_start",
            kind=NodeKind.FN,
            started_at=base,
            ended_at=base + timedelta(milliseconds=10),
            state_after={"input": "hi", "tools_loaded": ["search", "lookup"]},
        ),
        Node(
            id="11111111-1111-1111-1111-000000000001",
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
            id="11111111-1111-1111-1111-000000000002",
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
def populated_store(tmp_path, synthetic_run_and_nodes):
    """SqliteStore in tmp_path containing the synthetic Run+Nodes."""
    from chronos.store import SqliteStore

    run, nodes = synthetic_run_and_nodes
    db_path = tmp_path / "chronos.db"
    store = SqliteStore.open(db_path)
    with store.transaction():
        store.put_run(run)
        for node in nodes:
            store.put_node(node)
    return store, db_path, run


# ---------------------------------------------------------------------------
# Test 1: round-trip in-memory store -> envelopes.jsonl + expected_run.json
# ---------------------------------------------------------------------------


def test_capture_round_trip_writes_both_files(driver, populated_store, tmp_path):
    store, _db_path, run = populated_store
    out_dir = tmp_path / "fixture_out"
    envelopes_path, expected_path = driver.capture_run(
        store=store,
        run_id=run.id,
        out_dir=out_dir,
    )
    assert envelopes_path.is_file()
    assert expected_path.is_file()
    assert envelopes_path.parent == out_dir
    assert expected_path.parent == out_dir


def test_capture_envelopes_jsonl_shape(driver, populated_store, tmp_path):
    """envelopes.jsonl is one JSON object per line; carries v0 keys."""
    store, _db_path, run = populated_store
    out_dir = tmp_path / "fixture_env_shape"
    envelopes_path, _ = driver.capture_run(store=store, run_id=run.id, out_dir=out_dir)

    text = envelopes_path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    lines = text.rstrip("\n").split("\n")
    assert len(lines) == 3, f"expected 3 envelopes, got {len(lines)}"

    parsed = [json.loads(line) for line in lines]
    # Step 0 = agent_start (skeleton convention)
    assert parsed[0]["envelope"] == "agent_start"
    assert parsed[0]["node_name"] == "agent_start"
    assert parsed[0]["kind"] == "fn"
    assert parsed[0]["step_index"] == 0
    # Step 1 = llm_call with model_name
    assert parsed[1]["envelope"] == "llm_call"
    assert parsed[1]["node_name"] == "chat_call"
    assert parsed[1]["kind"] == "llm"
    assert parsed[1]["model_name"] == "claude-opus-4-7"
    # Step 2 = agent_end
    assert parsed[2]["envelope"] == "agent_end"
    assert parsed[2]["kind"] == "end"


def test_capture_expected_run_byte_equality_with_spike_projection(
    driver, spike, populated_store, tmp_path
):
    """The capture driver's expected_run.json must equal spike 19's projection."""
    store, _db_path, run = populated_store
    out_dir = tmp_path / "fixture_proj"
    _, expected_path = driver.capture_run(store=store, run_id=run.id, out_dir=out_dir)

    written = expected_path.read_text(encoding="utf-8")
    nodes = store.get_nodes_for_run(run.id)
    via_spike = spike.golden_dumps(spike.project_to_golden(run, nodes))
    assert written == via_spike, (
        "capture driver's expected_run.json drifted from spike 19 reference projection — "
        "would invalidate the slot-2 Option A hoist plan at R102"
    )


# ---------------------------------------------------------------------------
# Test 2: byte-identity between driver helpers and spike 19 helpers
# ---------------------------------------------------------------------------


def test_project_to_golden_byte_identical(driver, spike, synthetic_run_and_nodes):
    run, nodes = synthetic_run_and_nodes
    a = driver.golden_dumps(driver.project_to_golden(run, nodes))
    b = spike.golden_dumps(spike.project_to_golden(run, nodes))
    assert a == b


def test_canonicalise_byte_identical(driver, spike):
    sample = {
        "z": [{"b": 2, "a": 1}, {"d": 4, "c": 3}],
        "a": {"nested": {"y": 2, "x": 1}},
        "m": "scalar",
    }
    a = json.dumps(driver._canonicalise(sample), sort_keys=True)
    b = json.dumps(spike._canonicalise(sample), sort_keys=True)
    assert a == b


def test_sanitiser_redacts_known_secret_shapes(driver):
    """Each pattern in the table is redacted; benign tokens untouched."""
    raw = (
        "key=sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA "
        "openai=sk-proj-BBBBBBBBBBBBBBBBBBBBBBBB "
        "auth=Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 "
        "aws=AKIAIOSFODNN7EXAMPLE "
        "url=https://example.com/x?token=CCCCCCCCCCCCCCCCCC "
        "uuid=550e8400-e29b-41d4-a716-446655440000 "
        "harmless=hello-world-1234"
    )
    out = driver.sanitise_capture(raw)
    assert "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA" not in out
    assert "<REDACTED:ANTHROPIC_KEY>" in out
    assert "sk-proj-BBBBBBBBBBBBBBBBBBBBBBBB" not in out
    assert "<REDACTED:OPENAI_KEY>" in out
    assert "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in out
    assert "Bearer <REDACTED:BEARER_TOKEN>" in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "<REDACTED:AWS_AKID>" in out
    assert "token=CCCCCCCCCCCCCCCCCC" not in out
    assert "<REDACTED:URL_TOKEN>" in out
    # Benign tokens unchanged
    assert "550e8400-e29b-41d4-a716-446655440000" in out
    assert "hello-world-1234" in out


def test_sanitiser_idempotent(driver):
    raw = "key=sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA tail"
    once = driver.sanitise_capture(raw)
    twice = driver.sanitise_capture(once)
    assert once == twice


def test_sanitiser_byte_identical_to_spike(driver, spike):
    """Driver's sanitiser must equal spike 19's on a representative payload."""
    raw = (
        '{"key":"sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA","auth":"Bearer abc1234567'
        '8901234567890","url":"https://x.test?token=CCCCCCCCCCCCCCCCCC"}'
    )
    assert driver.sanitise_capture(raw) == spike.sanitise_capture(raw)


# ---------------------------------------------------------------------------
# Test 3: belt-on-write — secrets in state_after never reach disk
# ---------------------------------------------------------------------------


def test_capture_redacts_secret_in_state_after(driver, tmp_path):
    """If a synthetic Node carries a sk-ant-... in state_after, the bytes
    written to disk must be redacted (sanitiser belt working at write time)."""
    from chronos.core.models import Node, NodeKind, Run, RunStatus
    from chronos.store import SqliteStore

    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    run = Run(
        id="00000000-0000-0000-0000-00000000beef",
        adapter="anthropic_agents",
        adapter_thread_id="t-secret",
        status=RunStatus.COMPLETED,
        started_at=base,
        ended_at=base + timedelta(seconds=1),
        task_description="secret-leak guard",
    )
    nodes = [
        Node(
            id="22222222-2222-2222-2222-000000000000",
            run_id=run.id,
            step_index=0,
            node_name="agent_start",
            kind=NodeKind.FN,
            started_at=base,
            ended_at=base,
            state_after={"leaked_key": "sk-ant-api03-LEAKEDLEAKEDLEAKEDLEAKED"},
        ),
    ]
    db_path = tmp_path / "secret.db"
    store = SqliteStore.open(db_path)
    with store.transaction():
        store.put_run(run)
        for n in nodes:
            store.put_node(n)

    out_dir = tmp_path / "secret_out"
    envelopes_path, expected_path = driver.capture_run(store=store, run_id=run.id, out_dir=out_dir)
    env_text = envelopes_path.read_text(encoding="utf-8")
    exp_text = expected_path.read_text(encoding="utf-8")
    assert "sk-ant-api03-LEAKEDLEAKEDLEAKEDLEAKED" not in env_text
    assert "<REDACTED:ANTHROPIC_KEY>" in env_text
    assert "sk-ant-api03-LEAKEDLEAKEDLEAKEDLEAKED" not in exp_text
    assert "<REDACTED:ANTHROPIC_KEY>" in exp_text


# ---------------------------------------------------------------------------
# Test 4: error paths
# ---------------------------------------------------------------------------


def test_capture_run_missing_id_raises(driver, populated_store, tmp_path):
    store, _db_path, _run = populated_store
    with pytest.raises(ValueError, match="run not found"):
        driver.capture_run(
            store=store,
            run_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
            out_dir=tmp_path / "x",
        )


def test_capture_run_wrong_adapter_raises(driver, tmp_path):
    """A langgraph Run must be rejected — this driver is per-adapter explicit."""
    from chronos.core.models import Node, NodeKind, Run, RunStatus
    from chronos.store import SqliteStore

    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    run = Run(
        id="33333333-3333-3333-3333-000000000000",
        adapter="langgraph",
        adapter_thread_id="t-wrong",
        status=RunStatus.COMPLETED,
        started_at=base,
        ended_at=base,
        task_description="wrong adapter",
    )
    nodes = [
        Node(
            id="33333333-3333-3333-3333-000000000001",
            run_id=run.id,
            step_index=0,
            node_name="x",
            kind=NodeKind.FN,
            started_at=base,
            ended_at=base,
            state_after={},
        )
    ]
    db_path = tmp_path / "wrong.db"
    store = SqliteStore.open(db_path)
    with store.transaction():
        store.put_run(run)
        for n in nodes:
            store.put_node(n)
    with pytest.raises(ValueError, match="per-adapter explicit"):
        driver.capture_run(store=store, run_id=run.id, out_dir=tmp_path / "wrong_out")


def test_capture_run_zero_nodes_raises(driver, tmp_path):
    """A Run with no Nodes refuses to write empty fixture."""
    from chronos.core.models import Run, RunStatus
    from chronos.store import SqliteStore

    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    run = Run(
        id="44444444-4444-4444-4444-000000000000",
        adapter="anthropic_agents",
        adapter_thread_id="t-empty",
        status=RunStatus.COMPLETED,
        started_at=base,
        ended_at=base,
        task_description="empty run",
    )
    db_path = tmp_path / "empty.db"
    store = SqliteStore.open(db_path)
    with store.transaction():
        store.put_run(run)
    with pytest.raises(ValueError, match="zero nodes"):
        driver.capture_run(store=store, run_id=run.id, out_dir=tmp_path / "empty_out")


# ---------------------------------------------------------------------------
# Test 5: CLI smoke — main() returns 0 / 1 / 2
# ---------------------------------------------------------------------------


def test_main_db_missing_returns_2(driver, tmp_path):
    rc = driver.main(
        ["--db", str(tmp_path / "nope.db"), "--run-id", "x", "--out-dir", str(tmp_path / "o")]
    )
    assert rc == 2


def test_main_happy_path_returns_0(driver, populated_store, tmp_path):
    _store, db_path, run = populated_store
    out_dir = tmp_path / "happy"
    rc = driver.main(["--db", str(db_path), "--run-id", run.id, "--out-dir", str(out_dir)])
    assert rc == 0
    assert (out_dir / "envelopes.jsonl").is_file()
    assert (out_dir / "expected_run.json").is_file()


def test_main_unknown_run_returns_1(driver, populated_store, tmp_path):
    _store, db_path, _run = populated_store
    rc = driver.main(
        [
            "--db",
            str(db_path),
            "--run-id",
            "ffffffff-ffff-ffff-ffff-ffffffffffff",
            "--out-dir",
            str(tmp_path / "u"),
        ]
    )
    assert rc == 1
