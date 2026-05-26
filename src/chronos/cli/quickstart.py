"""`chronos quickstart` — seed a fresh chronos.db with a builtin demo (R109).

The verb's contract:

* Default (``chronos quickstart``) loads the ``builtin-minimal`` demo: 2 runs
  (parent + child), 3 nodes each, 1 fork edge linking them. Zero deps, zero
  API keys, zero clock — every value is deterministic.
* ``chronos quickstart --demo <name>`` reads ``examples/<name>/envelopes.jsonl``
  shipped in the repo / wheel.
* Refuses to clobber a non-empty DB; pass ``--force`` to overwrite.
* Prints next-step hints (`runs list`, `web`) so the new user knows where to go.

Demo file format (NOT the golden-trace contract — see
``examples/builtin-minimal/README.md``): JSONL where each line has exactly one
top-level key:

* ``_meta``  — optional human-readable header (ignored by the loader).
* ``_run``   — Run record (subset of ``chronos.core.models.Run`` fields).
* ``node``   — Node record (subset of ``chronos.core.models.Node``).
* ``_fork``  — Fork edge linking two previously-declared runs.

Timestamps are NOT in the file — the loader assigns deterministic synthetic
ones (epoch + 1-second-per-step) so the demo's ``started_at`` is reproducible
across invocations and across machines.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from chronos.core.models import Fork, Node, NodeKind, Run, RunStatus
from chronos.store.sqlite import SqliteStore

# Demo runs use a fixed epoch so timestamps are reproducible.
_DEMO_EPOCH = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _examples_root() -> Path:
    """Locate the shipped ``examples/`` directory.

    In a source checkout this is ``<repo>/examples/``. In a wheel install it
    sits next to the package — but R109 ships demos as repo-only resources
    (the wheel install path is a R115-R117 docs concern). For now we walk up
    from this file's location to find ``examples/`` alongside ``src/``.
    """
    # …/src/chronos/cli/quickstart.py → up 4 = repo root.
    here = Path(__file__).resolve()
    candidate = here.parents[3] / "examples"
    return candidate


def _load_envelopes(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:  # pragma: no cover — defensive
                raise ValueError(f"{path}:{lineno}: invalid JSON ({exc.msg})") from exc
            if not isinstance(obj, dict):  # pragma: no cover — defensive
                raise ValueError(f"{path}:{lineno}: expected JSON object")
            out.append(obj)
    return out


def _build_run(payload: dict[str, Any], started_at: datetime) -> Run:
    status = RunStatus(payload.get("status", "completed"))
    ended = started_at + timedelta(seconds=10)
    return Run(
        id=payload["id"],
        adapter=payload["adapter"],
        adapter_thread_id=payload.get("adapter_thread_id") or payload["id"],
        status=status,
        started_at=started_at,
        ended_at=ended
        if status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.FORKED)
        else None,
        task_description=payload.get("task_description"),
        tags=payload.get("tags") or [],
        metadata=payload.get("metadata") or {},
        initial_state=payload.get("initial_state") or {},
        final_state=payload.get("final_state"),
    )


def _build_node(payload: dict[str, Any], run_started_at: datetime) -> Node:
    step = int(payload["step_index"])
    started = run_started_at + timedelta(seconds=step)
    ended = started + timedelta(milliseconds=500)
    return Node(
        id=payload["id"],
        run_id=payload["run_id"],
        step_index=step,
        node_name=payload["node_name"],
        kind=NodeKind(payload["kind"]),
        parent_node_id=payload.get("parent_node_id"),
        started_at=started,
        ended_at=ended,
        state_after=payload.get("state_after") or {},
        model_name=payload.get("model_name"),
        tool_name=payload.get("tool_name"),
        error_message=payload.get("error_message"),
        metadata=payload.get("metadata") or {},
    )


def _build_fork(payload: dict[str, Any], created_at: datetime) -> Fork:
    return Fork(
        id=payload["id"],
        parent_run_id=payload["parent_run_id"],
        parent_node_id=payload["parent_node_id"],
        child_run_id=payload["child_run_id"],
        created_at=created_at,
        edited_fields=payload.get("edited_fields") or {},
        reason=payload.get("reason"),
    )


def quickstart_command(
    *,
    demo: str,
    db: Path | None,
    force: bool,
    console: Console,
) -> None:
    """Implementation behind the ``@app.command("quickstart")`` Typer wrapper.

    Kept as a free function (not a Typer-decorated entry point) so it stays
    unit-testable and so the entry point in ``chronos.cli.__init__`` mirrors
    the existing ``replay_command`` / ``web_command`` factoring pattern.
    """
    target = db if db is not None else Path("chronos.db")

    # Resolve demo source.
    demo_dir = _examples_root() / demo
    envelopes_path = demo_dir / "envelopes.jsonl"
    if not envelopes_path.exists():
        # Enumerate available demos for the hint (alphabetical, only dirs with envelopes.jsonl).
        root = _examples_root()
        available: list[str] = []
        if root.exists():
            for child in sorted(root.iterdir()):
                if child.is_dir() and (child / "envelopes.jsonl").exists():
                    available.append(child.name)
        listing = ", ".join(available) if available else "<none>"
        console.print(f"[red]error:[/] unknown demo [bold]{demo}[/]. Available: {listing}.")
        raise typer.Exit(code=2)

    # Refuse to clobber an existing non-empty DB.
    if target.exists() and not force:
        try:
            store = SqliteStore.open(target)
            try:
                existing = store.list_runs(limit=1)
            finally:
                store.close()
        except Exception:
            existing = []  # unreadable → treat as empty for safety; --force still required
        if existing:
            console.print(
                f"[red]error:[/] [bold]{target}[/] already contains runs. "
                "Pass [bold]--force[/] to overwrite, or point [bold]--db[/] at a fresh path."
            )
            raise typer.Exit(code=1)

    # If --force on an existing file, drop it so we re-seed cleanly.
    if force and target.exists():
        target.unlink()

    # Parse envelopes.
    try:
        envelopes = _load_envelopes(envelopes_path)
    except ValueError as exc:
        console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(code=2) from exc

    # Group by kind, preserving order.
    runs_payload: list[dict[str, Any]] = []
    nodes_payload: list[dict[str, Any]] = []
    forks_payload: list[dict[str, Any]] = []
    for env in envelopes:
        if "_meta" in env:
            continue
        if "_run" in env:
            runs_payload.append(env["_run"])
        elif "node" in env:
            nodes_payload.append(env["node"])
        elif "_fork" in env:
            forks_payload.append(env["_fork"])
        # Unknown keys silently ignored (forward-compat).

    # Persist.
    target.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteStore.open(target)
    try:
        # Stagger run start times so list ordering is deterministic.
        for idx, rp in enumerate(runs_payload):
            run = _build_run(rp, started_at=_DEMO_EPOCH + timedelta(minutes=idx))
            store.put_run(run)

        # Build a run_id -> started_at map for node timestamping.
        run_starts = {
            rp["id"]: _DEMO_EPOCH + timedelta(minutes=idx) for idx, rp in enumerate(runs_payload)
        }
        for np in nodes_payload:
            run_started = run_starts.get(np["run_id"], _DEMO_EPOCH)
            store.put_node(_build_node(np, run_started_at=run_started))

        for fp in forks_payload:
            # Place fork creation slightly after its parent run start.
            base = run_starts.get(fp["parent_run_id"], _DEMO_EPOCH)
            store.put_fork(_build_fork(fp, created_at=base + timedelta(seconds=30)))
    finally:
        store.close()

    # Friendly recap + next-step hints.
    console.print(
        f"[green]✓[/] seeded [bold]{target}[/] with demo "
        f"[bold]{demo}[/] "
        f"({len(runs_payload)} runs, {len(nodes_payload)} nodes, "
        f"{len(forks_payload)} fork{'s' if len(forks_payload) != 1 else ''})."
    )
    console.print("")
    console.print("Next steps:")
    console.print("  • [cyan]chronos runs list[/cyan]              — see the seeded runs")
    if runs_payload:
        first_id = runs_payload[0]["id"]
        console.print(f"  • [cyan]chronos runs show {first_id}[/cyan]   — inspect the parent run")
    console.print("  • [cyan]chronos web[/cyan]                    — explore in the browser")
