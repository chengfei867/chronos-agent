"""`chronos doctor` — environment health check (R110).

Triage helper for the new-user / support path. Walks a fixed set of checks
covering the runtime, the on-disk DB, the shipped demos, and optional extras,
prints a row per check (``✅`` / ``⚠️`` / ``❌``), then a one-line summary and
returns:

* ``0`` — no hard failures (any number of warnings is still happy).
* ``1`` — one or more ❌ rows: the install or DB needs attention.

Design notes (R110):

* This verb is read-only. It NEVER mutates ``chronos.db`` or installs
  packages. If a check finds something off (e.g. a missing optional extra),
  the row's hint tells the operator what command to run.
* Optional dependencies are reported as ⚠️ when missing (they're optional by
  definition) — **only** the runtime essentials (Python version, sqlite3
  module, schema-major compat when a DB exists) can produce ❌.
* The verb mirrors ``replay_command`` / ``verify_golden_command`` factoring:
  a free function that takes its console + path-resolution dependencies as
  kwargs, so unit tests can hand it a captured ``Console`` and a tmp path
  without spinning up the Typer app.
"""

from __future__ import annotations

import importlib
import importlib.metadata as importlib_metadata
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from chronos import __version__ as _chronos_version
from chronos.cli._common import _resolve_db_path
from chronos.core.models import SCHEMA_VERSION
from chronos.store.sqlite import SqliteStore

_OK = "ok"
_WARN = "warn"
_FAIL = "fail"

_REQUIRED_PYTHON = (3, 11)

# Optional extras and the import probes that prove they're installed.
# Keep this table aligned with `[project.optional-dependencies]` in
# ``pyproject.toml`` — drift here just means the doctor row says "missing"
# when actually it's there under a different name. Don't include `dev` (it's
# a developer-only extra; users don't need it).
_OPTIONAL_EXTRAS: tuple[tuple[str, str, str], ...] = (
    # (extra-name as user types `pip install 'chronos-agent[<X>]'`, probe import, friendly purpose)
    ("web", "fastapi", "browser viewer (`chronos web`)"),
    ("langgraph", "langgraph", "LangGraph adapter"),
    ("anthropic_agents", "claude_agent_sdk", "Anthropic Agents SDK adapter"),
    ("autogen", "autogen_agentchat", "AutoGen adapter"),
    ("crewai", "crewai", "CrewAI adapter"),
)


@dataclass(frozen=True)
class CheckRow:
    """One health check's outcome (presentation-layer struct)."""

    status: str  # _OK / _WARN / _FAIL
    label: str
    detail: str
    hint: str | None = None


def _glyph(status: str) -> str:
    return {_OK: "[green]✅[/green]", _WARN: "[yellow]⚠️[/yellow]", _FAIL: "[red]❌[/red]"}[status]


def _escape_markup(text: str) -> str:
    r"""Escape Rich markup ``[`` so e.g. ``Extra: [web]`` or hint
    ``chronos-agent[web]`` renders literally instead of being parsed as
    a (potentially unknown / silently-eaten) markup tag.

    Used for both labels (``Extra: [web]``) and hints
    (``\`uv pip install 'chronos-agent[web]'\```) — anywhere user-facing
    text contains ``[`` that should be displayed verbatim. R121 F14 fix:
    before this widening, hints were emitted into ``console.print`` raw,
    so ``[web]`` / ``[langgraph]`` / etc. were silently consumed as
    unknown markup tags and the install command rendered as
    ``\`uv pip install 'chronos-agent'\``` — which is wrong (no extras
    selected). Escaping ``[`` fixes the bug without changing the public
    ``hint`` field on ``CheckRow``.
    """
    return text.replace("[", r"\[")


# Backwards-compatible alias — older tests / contributors may import the
# narrower-named helper. ``_escape_label`` is the original name from R110.
_escape_label = _escape_markup


def _check_python_version() -> CheckRow:
    v = sys.version_info
    pretty = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= _REQUIRED_PYTHON:
        return CheckRow(_OK, "Python version", f"{pretty} (≥ 3.11 required)")
    return CheckRow(
        _FAIL,
        "Python version",
        f"{pretty} (≥ 3.11 required)",
        hint="Upgrade to Python 3.11+ — chronos uses `from __future__ import annotations` plus PEP-604 unions natively.",
    )


def _check_chronos_version() -> CheckRow:
    return CheckRow(_OK, "chronos package", f"v{_chronos_version}")


def _check_sqlite() -> CheckRow:
    # sqlite3 ships with CPython, but pin a soft floor for JSON1 + UPSERT confidence.
    runtime = sqlite3.sqlite_version
    parts = runtime.split(".")
    try:
        major, minor = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):  # pragma: no cover — defensive
        return CheckRow(_WARN, "SQLite library", f"{runtime} (could not parse version)")
    if (major, minor) >= (3, 38):
        return CheckRow(_OK, "SQLite library", f"{runtime}")
    return CheckRow(
        _WARN,
        "SQLite library",
        f"{runtime} (older than 3.38)",
        hint="Some JSON1 helpers may behave inconsistently; upgrading the host's libsqlite3 is recommended.",
    )


def _check_database(
    db: Path | None, *, open_store_fn: Callable[[Path], SqliteStore]
) -> list[CheckRow]:
    target = _resolve_db_path(db)
    rows: list[CheckRow] = []
    if not target.exists():
        rows.append(
            CheckRow(
                _WARN,
                "chronos.db",
                f"not found at {target}",
                hint="Run `chronos quickstart` to seed a demo DB, or set --db / $CHRONOS_DB.",
            )
        )
        return rows

    # Exists — try to open it.
    try:
        store = open_store_fn(target)
    except Exception as exc:  # pragma: no cover — message-only, can't easily synthesise
        rows.append(
            CheckRow(
                _FAIL,
                "chronos.db",
                f"failed to open {target}: {exc}",
                hint="The file may be corrupt or written by a future schema. Re-record or pick a different --db.",
            )
        )
        return rows

    try:
        # Schema version row.
        cur = store._conn.execute("SELECT schema_version FROM schema_info LIMIT 1")
        row = cur.fetchone()
        on_disk = row["schema_version"] if row is not None else "<unknown>"
        lib_major = SCHEMA_VERSION.split(".", 1)[0]
        disk_major = on_disk.split(".", 1)[0] if on_disk != "<unknown>" else None
        if disk_major == lib_major:
            rows.append(
                CheckRow(
                    _OK,
                    "DB schema",
                    f"{on_disk} (library expects {SCHEMA_VERSION})",
                )
            )
        else:
            rows.append(
                CheckRow(
                    _FAIL,
                    "DB schema",
                    f"{on_disk} (library expects {SCHEMA_VERSION} — major mismatch)",
                    hint="Migrate or re-record: this DB was written by an incompatible chronos version.",
                )
            )

        # Counts (informational — never ❌; emitted as a single info row).
        runs = store.list_runs(limit=1_000_000)
        run_count = len(runs)
        node_count = 0
        fork_count = 0
        try:
            cur = store._conn.execute("SELECT COUNT(*) AS n FROM nodes")
            r = cur.fetchone()
            node_count = int(r["n"]) if r is not None else 0
            cur = store._conn.execute("SELECT COUNT(*) AS n FROM forks")
            r = cur.fetchone()
            fork_count = int(r["n"]) if r is not None else 0
        except sqlite3.Error:  # pragma: no cover — defensive
            pass
        rows.append(
            CheckRow(
                _OK,
                "DB contents",
                f"{run_count} runs, {node_count} nodes, {fork_count} forks at {target}",
            )
        )
    finally:
        store.close()

    return rows


def _check_examples(examples_root: Path | None = None) -> CheckRow:
    if examples_root is None:
        # Mirror chronos.cli.quickstart._examples_root() — repo-root walk.
        here = Path(__file__).resolve()
        examples_root = here.parents[3] / "examples"
    if not examples_root.exists():
        return CheckRow(
            _WARN,
            "Examples directory",
            f"{examples_root} (not found)",
            hint="Shipped demos are repo-only at R110. Re-clone, or use `--db` to point at your own data.",
        )
    demos = sorted(
        d.name for d in examples_root.iterdir() if d.is_dir() and (d / "envelopes.jsonl").exists()
    )
    if not demos:
        return CheckRow(
            _WARN,
            "Examples directory",
            f"{examples_root} (no demos with envelopes.jsonl)",
            hint="`chronos quickstart` expects at least one demo subdir; re-clone if this is unexpected.",
        )
    listing = ", ".join(demos)
    return CheckRow(_OK, "Examples directory", f"{len(demos)} demo(s): {listing}")


def _check_optional_extras() -> list[CheckRow]:
    rows: list[CheckRow] = []
    for extra, probe, purpose in _OPTIONAL_EXTRAS:
        try:
            mod = importlib.import_module(probe)
        except ImportError:
            rows.append(
                CheckRow(
                    _WARN,
                    f"Extra: [{extra}]",
                    f"not installed — {purpose}",
                    hint=f"`uv pip install 'chronos-agent[{extra}]'`",
                )
            )
            continue
        # Get the version: try the probe module's __version__, then the importlib metadata.
        version = getattr(mod, "__version__", None)
        if version is None:
            try:
                version = importlib_metadata.version(probe.replace("_", "-"))
            except importlib_metadata.PackageNotFoundError:  # pragma: no cover — defensive
                version = "?"
        rows.append(
            CheckRow(
                _OK,
                f"Extra: [{extra}]",
                f"installed (v{version}) — {purpose}",
            )
        )
    return rows


def doctor_command(
    *,
    db: Path | None,
    console: Console,
    open_store_fn: Callable[[Path], SqliteStore] | None = None,
    examples_root: Path | None = None,
) -> int:
    """Run all health checks and print a summary. Returns the desired exit code.

    Parameters mirror the established CLI module pattern:

    * ``db``               — explicit DB path override (defaults via $CHRONOS_DB or ./chronos.db).
    * ``console``          — Rich Console (tests inject a captured one).
    * ``open_store_fn``    — DB opener (tests inject a fake to surface I/O errors deterministically).
    * ``examples_root``    — override the shipped-demos lookup root (test only).
    """
    if open_store_fn is None:
        open_store_fn = SqliteStore.open

    rows: list[CheckRow] = []
    rows.append(_check_python_version())
    rows.append(_check_chronos_version())
    rows.append(_check_sqlite())
    rows.extend(_check_database(db, open_store_fn=open_store_fn))
    rows.append(_check_examples(examples_root))
    rows.extend(_check_optional_extras())

    # Render rows.
    console.print("[bold]chronos doctor[/bold] — environment health check")
    console.print("")
    label_width = max(len(r.label) for r in rows) + 2
    for row in rows:
        glyph = _glyph(row.status)
        label = _escape_markup(row.label)
        # padding is computed on raw width, then markup-escaped output is appended,
        # so column alignment matches the un-escaped logical label width.
        pad = " " * max(0, label_width - len(row.label))
        # Escape ``[`` in detail + hint as well — without this, hints like
        # ``\`uv pip install 'chronos-agent[web]'\``` had ``[web]`` consumed
        # as unknown Rich markup (R121 F14). Detail strings are ours today,
        # but defensive escape keeps future versions/paths from regressing.
        detail = _escape_markup(row.detail)
        console.print(f"  {glyph}  [bold]{label}[/bold]{pad}{detail}")
        if row.hint:
            hint = _escape_markup(row.hint)
            console.print(f"      [dim]Hint:[/dim] [dim]{hint}[/dim]")

    # Summary.
    console.print("")
    fail_count = sum(1 for r in rows if r.status == _FAIL)
    warn_count = sum(1 for r in rows if r.status == _WARN)
    ok_count = sum(1 for r in rows if r.status == _OK)
    if fail_count:
        console.print(
            f"[red]✗ {fail_count} failure(s)[/red], "
            f"[yellow]{warn_count} warning(s)[/yellow], "
            f"[green]{ok_count} ok[/green] — fix the ❌ rows above."
        )
        return 1
    if warn_count:
        console.print(
            f"[green]✓ no failures[/green], "
            f"[yellow]{warn_count} warning(s)[/yellow], "
            f"[green]{ok_count} ok[/green] — warnings are non-fatal."
        )
        return 0
    console.print(f"[green]✓ all {ok_count} checks passed[/green] — chronos is healthy.")
    return 0
