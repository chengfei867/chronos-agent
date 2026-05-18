"""R85 — live MCP smoke for the Anthropic Agents adapter (AC-2 release gate).

Why this lives here (not in ``tests/unit``)
-------------------------------------------
The ARC-B GA matrix (ADR-026 §6) requires AC-2 to demonstrate end-to-end
recording of an **MCP tool call** through the Claude Agent SDK against the
live OneAPI relay (baidu-int / `Claude Sonnet 4.6`). Unit tests already
cover the offline / fake-runtime contracts (R76 ``test_queries_tool_linkage``
etc.); the only thing those can NOT prove is that the relay actually
surfaces ``ToolUseBlock`` + ``ToolResultBlock`` to the SDK and that the
recorder stamps both with a matching ``tool_use_id`` end-to-end.

This test is a thin pytest wrapper around
``scripts/dogfood/arc_b_slice_3_mcp.py`` so the same logic gates both the
dogfood script (which the cron runner executes for AC-2) and the GA test
matrix.

Skip semantics
--------------
- Skips if ``ANTHROPIC_API_KEY`` env var is unset (no relay → no live test).
- Skips if the dogfood script is missing (defensive, shouldn't happen).
- Network-bound: this is a *live* test. CI runs it only in jobs that have
  the relay key wired up.

Cost guard
----------
Default ``CHRONOS_LIVE_MCP_TIMEOUT_S=120`` keeps a single failed call from
running away. The dogfood script enforces the same timeout internally.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOGFOOD = _REPO_ROOT / "scripts" / "dogfood" / "arc_b_slice_3_mcp.py"


@pytest.mark.live
def test_arc_b_slice_3_mcp_live_smoke() -> None:
    """Run the AC-2 dogfood; ratchet on its exit code.

    The dogfood prints a structured report and exits 0 iff all five
    invariants (run.status=COMPLETED, ToolUseBlock surfaced, ToolResultBlock
    surfaced, matching tool_use_id, final TextBlock contains expected sum)
    are satisfied.
    """
    if os.environ.get("CHRONOS_LIVE") != "1":
        pytest.skip("CHRONOS_LIVE != 1 — live tests opt-in only")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY unset — live MCP smoke requires relay")
    if not _DOGFOOD.is_file():
        pytest.skip(f"dogfood script not found at {_DOGFOOD}")

    proc = subprocess.run(
        [sys.executable, str(_DOGFOOD)],
        capture_output=True,
        text=True,
        timeout=240,  # outer guard; dogfood has its own 120s inner guard
        cwd=str(_REPO_ROOT),
    )

    # Dump output regardless of outcome so CI logs are diagnosable.
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)

    assert proc.returncode == 0, (
        f"AC-2 MCP live-smoke dogfood failed (rc={proc.returncode}). "
        f"See captured stdout/stderr above."
    )

    # Belt-and-suspenders: dogfood prints this exact line on success.
    assert "AC-2 release-gate INVARIANTS GREEN" in proc.stdout, (
        "Dogfood exited 0 but did not print the AC-2 success marker; "
        "either the success criterion drifted or the script was edited "
        "without updating this test."
    )
