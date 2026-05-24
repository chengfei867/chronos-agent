"""Chronos verify-golden — fixture-side regression net for golden traces.

Phase 5 Arc D slice 3 (R104, ADR-028 §4 close). The CLI verb takes a
recorded ``Run`` (in a ``chronos.db`` SQLite store) and a directory of
golden-trace fixtures (``tests/golden/<adapter>/<scenario>/``) and asserts:

1. Project the recorded ``Run`` to its canonical ``RunSummary`` via
   :func:`chronos.golden.project_to_golden` + :func:`chronos.golden.golden_dumps`,
   and byte-compare against the on-disk ``expected_run.json``.
2. **Suspenders layer (load-time sanitiser audit)**: pass the on-disk
   ``envelopes.jsonl`` content through :func:`chronos.golden.sanitise_capture`'s
   pattern set BEFORE the byte-compare. If any pattern matches, fail loudly
   so the operator goes and re-records — fixtures with leaked secrets must
   never become a regression-net "OK". This is the defence-in-depth gate
   ADR-028 §4 promised: belt = capture-time redaction (R101 driver),
   suspenders = load-time audit (this verb).

Exit-code contract (stable, documented at ``docs/contracts/golden-trace-format.md`` §6):

  0 — happy path. The recorded run matches the on-disk expected_run.json
       byte-for-byte AND envelopes.jsonl carries no detectable secret.
  1 — projection mismatch. The recorded run does NOT match
       expected_run.json. A unified diff of the canonical-JSON serialisation
       is printed to stderr/console for the operator.
  2 — missing fixture. The directory or one of the two required files
       (``expected_run.json``, ``envelopes.jsonl``) is absent. Points the
       operator at the capture driver (``scripts/capture/capture_*.py``).
  3 — sanitiser audit failure. ``envelopes.jsonl`` contains a pattern from
       :data:`chronos.golden._SECRET_PATTERNS`. The matched pattern name
       (e.g. ``ANTHROPIC_KEY``) is reported. The operator must re-record
       (capture-time sanitiser should have caught it; this layer is the
       belt-and-suspenders second gate).

R104 ships the standalone command function. The thin Typer wrapper that
registers it under the ``chronos`` CLI tree lives in :mod:`chronos.cli.__init__`,
mirroring the shape of ``chronos replay``.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from rich.console import Console

from chronos.golden import (
    _SECRET_PATTERNS,
    golden_dumps,
    project_to_golden,
)

# Public exit-code constants (kept here so tests can pin them by name).
EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_MISSING_FIXTURE = 2
EXIT_SANITISER_HIT = 3


def _scan_for_secrets(envelopes_text: str) -> str | None:
    """Return the first matching pattern name, or None if clean.

    We do NOT redact and compare — we run each pattern's ``search()``
    against the raw envelopes text and surface the pattern's name. The
    redaction codepath (:func:`chronos.golden.sanitise_capture`) belongs
    at *capture* time; at *load* time we want to detect and refuse, not
    silently fix-up.
    """
    for kind, rx, _repl in _SECRET_PATTERNS:
        if rx.search(envelopes_text):
            return kind
    return None


def verify_golden_command(
    db: Path | None,
    run_id: str,
    golden_dir: Path,
    open_store_fn: Any,
    console: Console,
) -> int:
    """Implementation shared between Typer wiring and tests.

    ``open_store_fn`` is injected so tests can hand in a fake store factory.
    Returns the integer exit code (the Typer wrapper translates this into
    ``typer.Exit(code=...)``); tests assert on the return value directly.
    """
    expected_path = golden_dir / "expected_run.json"
    envelopes_path = golden_dir / "envelopes.jsonl"

    # ---- Missing-fixture gate (exit 2) ------------------------------------
    if not golden_dir.exists() or not golden_dir.is_dir():
        console.print(
            f"[red]error:[/] golden-dir not found: [bold]{golden_dir}[/]. "
            "Re-record via [cyan]scripts/capture/capture_<adapter>.py[/] "
            "(e.g. [cyan]scripts/capture/capture_anthropic_agents.py[/])."
        )
        return EXIT_MISSING_FIXTURE
    if not expected_path.exists():
        console.print(
            f"[red]error:[/] missing expected_run.json under [bold]{golden_dir}[/]. "
            "Re-record via [cyan]scripts/capture/capture_<adapter>.py[/]."
        )
        return EXIT_MISSING_FIXTURE
    if not envelopes_path.exists():
        console.print(
            f"[red]error:[/] missing envelopes.jsonl under [bold]{golden_dir}[/]. "
            "Re-record via [cyan]scripts/capture/capture_<adapter>.py[/]."
        )
        return EXIT_MISSING_FIXTURE

    # ---- Suspenders: load-time sanitiser audit (exit 3) -------------------
    # Run BEFORE the byte-compare so a fixture that leaked a secret + happens
    # to project byte-equal still fails loudly. The capture driver should
    # already have redacted on write (R101), but two independent gates >
    # one. Per ADR-028 §4: belt + suspenders.
    envelopes_text = envelopes_path.read_text(encoding="utf-8")
    leaked = _scan_for_secrets(envelopes_text)
    if leaked is not None:
        console.print(
            f"[red]error:[/] secret in fixture, please re-record. "
            f"Pattern matched: [bold]{leaked}[/] in [bold]{envelopes_path}[/]. "
            "The capture driver's belt-layer sanitiser should have caught "
            "this — re-run capture or report a sanitiser-pattern miss."
        )
        return EXIT_SANITISER_HIT

    # ---- Project recorded run + byte-compare (exit 0 / 1) -----------------
    store = open_store_fn(db)
    try:
        run = store.get_run(run_id)
        if run is None:
            console.print(f"[red]error:[/] no such run: [bold]{run_id}[/]")
            # Run-missing reuses exit 2 — same operator action
            # (re-record / pick a real run id), same family of failure.
            return EXIT_MISSING_FIXTURE
        nodes = store.get_nodes_for_run(run_id)
    finally:
        store.close()

    projected = project_to_golden(run, nodes)
    actual_serialised = golden_dumps(projected)
    expected_serialised = expected_path.read_text(encoding="utf-8")

    if actual_serialised == expected_serialised:
        console.print(
            f"[green]ok:[/] run [bold]{run_id}[/] projects byte-equal to "
            f"[bold]{expected_path}[/] (and envelopes.jsonl is sanitiser-clean)."
        )
        return EXIT_OK

    diff = "".join(
        difflib.unified_diff(
            expected_serialised.splitlines(keepends=True),
            actual_serialised.splitlines(keepends=True),
            fromfile=str(expected_path),
            tofile=f"<recorded run {run_id}>",
            n=3,
        )
    )
    console.print(
        f"[red]mismatch:[/] recorded run [bold]{run_id}[/] does NOT match [bold]{expected_path}[/]."
    )
    # Use plain print for the diff so it's pipe-friendly (no Rich wrapping).
    print(diff)
    return EXIT_MISMATCH
