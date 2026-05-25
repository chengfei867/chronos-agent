"""Parametrised CI shim for ``chronos verify-golden`` (R106, ADR-028 §4 close).

Phase 5 Arc D slice 4 — the parametrised pytest module that loops every
committed golden fixture under ``tests/golden/`` and runs the
``chronos verify-golden`` CLI verb against it via ``subprocess.run``,
asserting exit 0. Pairs with ``.github/workflows/golden-verify.yml`` so
every push / PR to ``main`` gates on this file.

Discovery rules (see R106 progress doc D-decisions):

* Glob ``tests/golden/*/expected_run.json``.
* A directory qualifies iff it contains BOTH ``expected_run.json`` AND
  ``envelopes.jsonl``. (Asymmetric directories — exactly one of the two —
  fail loudly. Placeholder dirs with neither are silently skipped.)
* If zero qualifying dirs are found, the test is marked
  ``pytest.skip(...)`` rather than collected with zero parameters
  (defensive: R94 empty-fixture trap).
* Each qualifying dir is parametrised by directory name (``_skeleton``,
  ``anthropic_agents/<scenario>``, …).

Per-fixture flow:

1. Read ``expected_run.json`` (the source of truth for ``adapter`` /
   ``status`` / ``task_description`` / ``node_kinds`` / ``node_names`` /
   ``states_after``).
2. Read ``envelopes.jsonl`` line-by-line (the source of truth for
   ``step_index`` ordering, plus optional ``model_name`` for LLM nodes).
3. Materialise a ``Run`` + ``[Node]`` whose projection
   (``project_to_golden`` + ``golden_dumps``) byte-equals the on-disk
   ``expected_run.json``. The ``run_id`` is a deterministic synthetic
   UUID — projection strips it (per ``_RUN_SUMMARY_KEYS``), so any
   stable value works (D-106-1).
4. Insert into a fresh ``SqliteStore`` at ``tmp_path / "verify.db"``.
5. ``subprocess.run([sys.executable, "-m", "chronos.cli", "verify-golden",
   run_id, "--db", db_path, "--golden-dir", dir])`` — assert exit 0.

Subprocess (NOT ``CliRunner``) is per the R106 hand-off invariant: we
exercise the full Typer-wrapped CLI exit-code surface end-to-end so a
regression in the wrapper itself, the entrypoint, or process exit-code
propagation surfaces in CI rather than at first user-report.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from chronos.core.models import Node, NodeKind, Run, RunStatus
from chronos.store import SqliteStore

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

_GOLDEN_ROOT = Path(__file__).resolve().parent / "golden"
# A deterministic synthetic run-id; projection strips run_id so the value
# is irrelevant to the byte-compare. Pinned to a constant for log clarity.
_SYNTHETIC_RUN_ID = "00000000-0000-0000-0000-00000000a106"


def _discover_fixtures() -> list[Path]:
    """Return every directory under ``tests/golden/`` that has BOTH files.

    Asymmetric directories (exactly one of the two) are NOT included here;
    they're caught by :func:`_assert_no_asymmetric_fixtures` as a separate
    sentinel test so a botched record fails loudly instead of silently
    dropping out of CI.
    """
    if not _GOLDEN_ROOT.is_dir():
        return []
    qualifying: list[Path] = []
    # Recurse one level deep so both ``tests/golden/_skeleton/`` and
    # ``tests/golden/<adapter>/<scenario>/`` patterns are picked up.
    for expected in sorted(_GOLDEN_ROOT.rglob("expected_run.json")):
        if (expected.parent / "envelopes.jsonl").is_file():
            qualifying.append(expected.parent)
    return qualifying


def _fixture_id(p: Path) -> str:
    """Pretty parametrize-id: relative path under ``tests/golden/``."""
    return str(p.relative_to(_GOLDEN_ROOT))


_FIXTURES = _discover_fixtures()


# ---------------------------------------------------------------------------
# Materialiser — envelopes.jsonl + expected_run.json -> Run + Nodes
# ---------------------------------------------------------------------------


def _build_run_and_nodes_from_fixture(
    fixture_dir: Path,
) -> tuple[Run, list[Node]]:
    """Reconstruct a ``Run`` + ``[Node]`` whose projection byte-equals
    ``<fixture_dir>/expected_run.json``.

    Strategy: ``expected_run.json`` is the canonical truth for projection
    output (closed-set ``_RUN_SUMMARY_KEYS``); ``envelopes.jsonl`` carries
    per-node provenance the projection drops (notably ``model_name`` for
    LLM nodes — relevant for adapter-level regression coverage but stripped
    at projection time, so its value doesn't gate the byte-compare).

    We trust ``expected_run.json`` for the projection-keyed fields and pull
    ``model_name`` out of ``envelopes.jsonl`` for its row, where present.
    A cross-check asserts the two files agree on ``node_count``,
    ``node_names``, ``node_kinds``, and ``states_after`` — divergence here
    means the fixture is internally inconsistent (the capture driver got
    interrupted, or the JSON files were hand-edited apart). Refuse to
    proceed in that case so the operator re-records.
    """
    expected_path = fixture_dir / "expected_run.json"
    envelopes_path = fixture_dir / "envelopes.jsonl"

    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    envelopes_lines = [
        ln for ln in envelopes_path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    envelopes = [json.loads(ln) for ln in envelopes_lines]
    envelopes.sort(key=lambda e: int(e["step_index"]))

    # Cross-check the two files agree on the projection-keyed fields.
    env_node_kinds = [str(e["kind"]) for e in envelopes]
    env_node_names = [str(e["node_name"]) for e in envelopes]
    env_states = [e.get("state_after", {}) for e in envelopes]
    assert env_node_kinds == expected["node_kinds"], (
        f"fixture {fixture_dir.name}: envelopes.jsonl node_kinds "
        f"{env_node_kinds!r} disagree with expected_run.json "
        f"{expected['node_kinds']!r} — re-record."
    )
    assert env_node_names == expected["node_names"], (
        f"fixture {fixture_dir.name}: envelopes.jsonl node_names "
        f"disagree with expected_run.json — re-record."
    )
    assert len(envelopes) == int(expected["node_count"]), (
        f"fixture {fixture_dir.name}: envelopes count {len(envelopes)} "
        f"disagrees with expected_run.json node_count "
        f"{expected['node_count']} — re-record."
    )
    # states_after is canonicalised at projection time (sort_keys); compare
    # by re-canonicalising both sides through json.dumps(sort_keys=True).
    for i, (es, xs) in enumerate(zip(env_states, expected["states_after"], strict=True)):
        assert json.dumps(es, sort_keys=True) == json.dumps(xs, sort_keys=True), (
            f"fixture {fixture_dir.name}: state_after diverged at "
            f"step_index={i} between envelopes.jsonl and expected_run.json"
        )

    # Materialise. Times are arbitrary — projection strips them. Use a
    # deterministic base so regression diffs (if the projection ever leaks
    # a time-derived field) are reproducible.
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    run = Run(
        id=_SYNTHETIC_RUN_ID,
        adapter=str(expected["adapter"]),
        adapter_thread_id=f"t-r106-{fixture_dir.name}",
        status=RunStatus(str(expected["status"])),
        started_at=base,
        ended_at=base + timedelta(seconds=int(expected["node_count"]) + 1),
        task_description=expected.get("task_description"),
        initial_state={},
        final_state=None,
        tags=["r106", "golden-verify"],
        metadata={"source": "r106-test-shim", "fixture": fixture_dir.name},
    )
    nodes: list[Node] = []
    for envelope in envelopes:
        kind = NodeKind(str(envelope["kind"]))
        step_index = int(envelope["step_index"])
        node_kwargs = {
            "id": f"aaaaaaaa-aaaa-aaaa-aaaa-{step_index:012d}",
            "run_id": run.id,
            "step_index": step_index,
            "node_name": str(envelope["node_name"]),
            "kind": kind,
            "started_at": base + timedelta(seconds=step_index),
            "ended_at": base + timedelta(seconds=step_index, milliseconds=500),
            "state_after": envelope.get("state_after", {}),
        }
        if envelope.get("model_name"):
            node_kwargs["model_name"] = str(envelope["model_name"])
        nodes.append(Node(**node_kwargs))
    return run, nodes


# ---------------------------------------------------------------------------
# Sentinel: asymmetric fixture directories must fail loudly
# ---------------------------------------------------------------------------


def test_no_asymmetric_golden_fixtures() -> None:
    """A directory with ONLY one of (expected_run.json, envelopes.jsonl)
    is a botched record — refuse silently passing CI on it.

    Placeholder dirs (neither file) are fine — they're documented capture
    targets awaiting their first run (e.g. ``anthropic_agents/`` pre-R101
    live capture).
    """
    if not _GOLDEN_ROOT.is_dir():
        pytest.skip("tests/golden/ does not exist yet")
    asymmetric: list[str] = []
    for child in _GOLDEN_ROOT.rglob("*"):
        if not child.is_dir():
            continue
        has_expected = (child / "expected_run.json").is_file()
        has_envelopes = (child / "envelopes.jsonl").is_file()
        if has_expected ^ has_envelopes:
            missing = "envelopes.jsonl" if has_expected else "expected_run.json"
            asymmetric.append(f"{child.relative_to(_GOLDEN_ROOT)} (missing {missing})")
    assert not asymmetric, (
        "Asymmetric golden-fixture directories detected — each must carry "
        "BOTH expected_run.json and envelopes.jsonl, or NEITHER (placeholder). "
        f"Offenders: {asymmetric!r}. Re-record via "
        "scripts/capture/capture_<adapter>.py or remove the stray file."
    )


# ---------------------------------------------------------------------------
# Parametrised CLI exit-code shim
# ---------------------------------------------------------------------------


@pytest.mark.golden
@pytest.mark.skipif(
    not _FIXTURES,
    reason="no golden fixtures committed yet (tests/golden/ has no qualifying dir)",
)
@pytest.mark.parametrize(
    "fixture_dir",
    _FIXTURES,
    ids=[_fixture_id(p) for p in _FIXTURES] if _FIXTURES else None,
)
def test_chronos_verify_golden_exits_zero_for_committed_fixture(
    fixture_dir: Path, tmp_path: Path
) -> None:
    """End-to-end: build a run, run the CLI, expect exit 0.

    This is the regression net for the *contract* (projection determinism +
    sanitiser-clean fixtures), not for the verifier itself — that has its
    own 4-row unit test suite at ``tests/unit/test_cli_verify_golden.py``.
    The two layers compose: unit tests pin the exit-code matrix; this
    parametrised shim asserts every committed fixture is in the happy-path
    row.
    """
    run, nodes = _build_run_and_nodes_from_fixture(fixture_dir)

    db_path = tmp_path / "verify.db"
    store = SqliteStore.open(db_path)
    try:
        with store.transaction():
            store.put_run(run)
            for node in nodes:
                store.put_node(node)
    finally:
        store.close()

    # Subprocess (NOT typer.testing.CliRunner) — full CLI exit-code surface.
    # Prefer the installed ``chronos`` console script (project.scripts entry
    # point); fall back to ``python -c "from chronos.cli import app; app()"``
    # if it's not on PATH (e.g. when a test runner invokes pytest from a
    # raw interpreter without the venv's bin/ on PATH).
    chronos_exe = shutil.which("chronos")
    if chronos_exe is not None:
        cmd = [chronos_exe]
    else:
        cmd = [
            sys.executable,
            "-c",
            "import sys; from chronos.cli import app; sys.exit(app() or 0)",
        ]
    cmd += [
        "verify-golden",
        run.id,
        "--db",
        str(db_path),
        "--golden-dir",
        str(fixture_dir),
    ]
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"chronos verify-golden exit={result.returncode} for "
        f"{fixture_dir.name}\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
