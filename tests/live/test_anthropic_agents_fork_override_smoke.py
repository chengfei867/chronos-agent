"""R86 — live override-fork smoke for the Anthropic Agents adapter (AC-3 release gate).

Why this lives here (not in ``tests/unit``)
-------------------------------------------
The ARC-B GA matrix (ADR-026 §6) requires AC-3 to demonstrate that the
adapter's ``fork(..., tool_input_overrides=...)`` primitive works
end-to-end against the live OneAPI relay (baidu-int / `Claude Sonnet
4.6`) — not just against the offline fake-SDK fixture. R80 closed the
unit-test contract, R86 closes the live-relay contract.

Unit tests (``tests/unit/test_anthropic_agents_fork_tool_override.py``)
already cover the offline contracts: validation of override keys, fork
delegation to ``fork_session()``, ``state_after['tool_input']`` stamping
on id-match. The only thing those can NOT prove is that the *real*
``claude_agent_sdk.fork_session()`` succeeds against the relay, that the
recorder catches the resumed child stream, and that the child run reaches
``RunStatus.COMPLETED`` with a fresh ToolUseBlock+ToolResultBlock pair
(R76 §5.1 linkage holding across the fork).

This test is a thin pytest wrapper around
``scripts/dogfood/arc_b_slice_3_fork_override.py`` so the same logic
gates both the dogfood script (which the cron runner executes for AC-3)
and the GA test matrix.

Skip semantics
--------------
- Skips unless ``CHRONOS_LIVE=1`` (live tests are opt-in only).
- Skips if ``ANTHROPIC_API_KEY`` env var is unset (no relay → no live test).
- Skips if the dogfood script is missing (defensive, shouldn't happen).
- Network-bound: this is a *live* test. CI runs it only in jobs that
  have the relay key wired up.

Cost guard
----------
Default ``CHRONOS_DOGFOOD_TIMEOUT_S=120`` keeps a single failed call
from running away (parent + child each get the budget). The dogfood
script enforces this internally; the outer pytest guard is 300s
(parent + child + jitter).

Three-tier ratchet semantics
----------------------------
The dogfood exits with three distinct codes:

- **0** — green; all five AC-3 invariants passed; we assert this.
- **2** — relay degraded (synthetic auth failure, model outage,
  parent run didn't reach COMPLETED, etc); we ``pytest.skip`` so the
  GA gate doesn't trip on transient relay flake.
- **3** — hard regression (unexpected exception type, fork pipeline
  broken, child run failed an invariant); we fail the test with the
  captured stdout/stderr.

Treat exit 2 as "you can re-run; not our bug" and exit 3 as "the
adapter regressed; bisect required."
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOGFOOD = _REPO_ROOT / "scripts" / "dogfood" / "arc_b_slice_3_fork_override.py"


@pytest.mark.live
def test_arc_b_slice_3_fork_override_live_smoke() -> None:
    """Run the AC-3 dogfood; ratchet on its exit code.

    The dogfood prints a structured report and exits:

    - **0** iff all five AC-3 invariants pass (parent COMPLETED with
      anchor; ``recorder.fork(tool_input_overrides=...)`` returns
      child_run_id+fork_id; store has Fork row linking parent↔child;
      child COMPLETED with matching ToolUseBlock+ToolResultBlock; child
      tu_id differs from parent — the documented R86 contract finding).
    - **2** if the relay is degraded (skip, don't fail).
    - **3** on hard regression (fail with full output).
    """
    if os.environ.get("CHRONOS_LIVE") != "1":
        pytest.skip("CHRONOS_LIVE != 1 — live tests opt-in only")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY unset — live override-fork smoke requires relay")
    if not _DOGFOOD.is_file():
        pytest.skip(f"dogfood script not found at {_DOGFOOD}")

    proc = subprocess.run(
        [sys.executable, str(_DOGFOOD)],
        capture_output=True,
        text=True,
        timeout=300,  # outer guard; dogfood has its own 120s inner guard per phase
        cwd=str(_REPO_ROOT),
    )

    # Dump output regardless of outcome so CI logs are diagnosable.
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)

    if proc.returncode == 2:
        pytest.skip(
            "AC-3 override-fork live-smoke degraded (rc=2). "
            "Relay flake — not a regression. See captured output above."
        )

    assert proc.returncode == 0, (
        f"AC-3 override-fork live-smoke dogfood failed (rc={proc.returncode}). "
        f"See captured stdout/stderr above."
    )

    # Belt-and-suspenders: dogfood prints this exact line on success.
    assert "AC-3 release-gate INVARIANTS GREEN" in proc.stdout, (
        "Dogfood exited 0 but did not print the AC-3 success marker; "
        "either the success criterion drifted or the script was edited "
        "without updating this test."
    )
