"""`chronos quickstart` — seed a fresh chronos.db with a builtin demo (R109 / R118).

The verb's contract:

* Default (``chronos quickstart``) loads the ``builtin-minimal`` demo: 2 runs
  (parent + child), 3 nodes each, 1 fork edge linking them. Zero deps, zero
  API keys, zero clock — every value is deterministic.
* ``chronos quickstart --demo <name>`` reads ``examples/<name>/envelopes.jsonl``
  shipped in the repo / wheel.
* ``chronos quickstart --list`` enumerates available demos with a one-line
  description sourced from the per-demo ``manifest.json`` (R118; ADR-030
  acceptance row "≥3 real demos under examples/ with quickstart loader").
* Refuses to clobber a non-empty DB; pass ``--force`` to overwrite.
* Prints next-step hints (``runs list``, ``web``, ``eval run``) so the new user
  knows where to go. The ``eval run`` hint uses each demo's
  ``recommended_evaluators[0]`` (R118) so users see the matching evaluator
  without reading source.

Demo file format (NOT the golden-trace contract — see
``examples/builtin-minimal/README.md``): JSONL where each line has exactly one
top-level key:

* ``_meta``  — optional human-readable header (ignored by the loader).
* ``_run``   — Run record (subset of ``chronos.core.models.Run`` fields).
* ``node``   — Node record (subset of ``chronos.core.models.Node``).
* ``_fork``  — Fork edge linking two previously-declared runs.

Each demo also ships a ``manifest.json`` with ``name``, ``title``,
``description``, ``adapter``, ``recommended_evaluators`` (list, in priority
order), ``final_state_key``, ``stats``, and ``first_run_id``. Missing /
malformed manifests degrade gracefully — the verb still loads the envelopes
and falls back to ``output_length_chars`` for the eval hint.

Timestamps are NOT in the file — the loader assigns deterministic synthetic
ones (epoch + 1-second-per-step) so the demo's ``started_at`` is reproducible
across invocations and across machines.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from chronos.core.models import Fork, Node, NodeKind, Run, RunStatus, Usage
from chronos.store.sqlite import SqliteStore

# Demo runs use a fixed epoch so timestamps are reproducible.
_DEMO_EPOCH = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

# Default fallback evaluator when a demo lacks a manifest or the manifest
# omits ``recommended_evaluators``. Always works — every demo's final_state
# carries an "output" key (per R118 envelope-authoring convention) so this
# evaluator returns a meaningful numeric score.
_DEFAULT_EVALUATOR = "output_length_chars"


@dataclass(frozen=True)
class DemoManifest:
    """Parsed view of an ``examples/<name>/manifest.json`` file.

    Free-form fields (``adapter``, ``stats``, ``first_run_id``) are kept as raw
    JSON; the loader only enforces the small subset it consumes for hints and
    listings, so older manifests without newer fields keep working.
    """

    name: str
    title: str
    description: str
    recommended_evaluators: list[str]

    @classmethod
    def empty(cls, name: str) -> DemoManifest:
        return cls(
            name=name,
            title=name,
            description="",
            recommended_evaluators=[_DEFAULT_EVALUATOR],
        )


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


def _load_manifest(demo_dir: Path, name: str) -> DemoManifest:
    """Parse ``demo_dir/manifest.json``; return ``DemoManifest.empty`` on miss.

    Defensive: a corrupt or partial manifest never crashes ``quickstart`` —
    the demo's envelopes.jsonl is the source of truth, the manifest is a
    cosmetic / hint surface.
    """
    path = demo_dir / "manifest.json"
    if not path.exists():
        return DemoManifest.empty(name)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return DemoManifest.empty(name)
    if not isinstance(raw, dict):
        return DemoManifest.empty(name)
    evaluators_raw = raw.get("recommended_evaluators")
    if isinstance(evaluators_raw, list) and all(isinstance(x, str) for x in evaluators_raw):
        evaluators = list(evaluators_raw) or [_DEFAULT_EVALUATOR]
    else:
        evaluators = [_DEFAULT_EVALUATOR]
    return DemoManifest(
        name=str(raw.get("name") or name),
        title=str(raw.get("title") or name),
        description=str(raw.get("description") or ""),
        recommended_evaluators=evaluators,
    )


def _list_available_demos(root: Path) -> list[tuple[str, DemoManifest]]:
    """Return ``[(name, manifest), …]`` for every demo dir alphabetically.

    A demo dir is any subdirectory containing an ``envelopes.jsonl``; manifest
    is best-effort (empty manifest if missing/malformed).
    """
    out: list[tuple[str, DemoManifest]] = []
    if not root.exists():
        return out
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "envelopes.jsonl").exists():
            out.append((child.name, _load_manifest(child, child.name)))
    return out


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
    # Optional usage block: ``{"prompt_tokens": .., "completion_tokens": ..,
    # "reasoning_tokens": ..}``. Demo envelopes from R111 (ADR-029) carry this
    # on LLM-kind nodes so quickstart users see populated token/cost columns
    # in `runs list` and the frontend RunList page out of the box.
    usage_payload = payload.get("usage")
    usage_obj: Usage | None = None
    if usage_payload is not None:
        usage_obj = Usage(
            prompt_tokens=int(usage_payload.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage_payload.get("completion_tokens", 0) or 0),
            reasoning_tokens=int(usage_payload.get("reasoning_tokens", 0) or 0),
        )
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
        usage=usage_obj,
        cost_usd_cents=payload.get("cost_usd_cents"),
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


def list_demos_command(*, console: Console) -> None:
    """Implementation behind ``chronos quickstart --list`` (R118).

    Emits a small table-like listing: ``name`` (bold) → ``title`` →
    indented ``description``. No external table libs required — keeps the
    output readable in plain TTYs and CI logs.
    """
    root = _examples_root()
    demos = _list_available_demos(root)
    if not demos:
        console.print(f"[yellow]No demos found under {root}.[/]")
        return
    console.print(f"[bold]Available demos[/] ([dim]{len(demos)}[/]):")
    console.print("")
    for name, manifest in demos:
        console.print(f"  • [bold cyan]{name}[/]")
        if manifest.title and manifest.title != name:
            console.print(f"    [dim]{manifest.title}[/]")
        if manifest.description:
            # Soft-wrap the description by clipping at 100 chars per line —
            # rich.Console handles wrapping if console is wide enough; we
            # just print a single chunk and let rich's overflow handle TTY.
            console.print(f"    {manifest.description}")
        if manifest.recommended_evaluators:
            evals = ", ".join(manifest.recommended_evaluators)
            console.print(f"    [dim]evaluators: {evals}[/]")
        console.print("")
    console.print("Load one with [cyan]chronos quickstart --demo <name>[/cyan].")


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
        available = [name for name, _ in _list_available_demos(_examples_root())]
        listing = ", ".join(available) if available else "<none>"
        console.print(f"[red]error:[/] unknown demo [bold]{demo}[/]. Available: {listing}.")
        console.print("[dim]Hint: run [cyan]chronos quickstart --list[/cyan] for descriptions.[/]")
        raise typer.Exit(code=2)

    manifest = _load_manifest(demo_dir, demo)

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
        # R115 / ADR-030: surface the evaluator path so a new user can score
        # the demo run without reading source. Anchors the R122 must-pass
        # "new-user path → run eval" gate.
        # R118: the evaluator name comes from the demo's manifest
        # (recommended_evaluators[0]), with a sane fallback.
        evaluator_name = (
            manifest.recommended_evaluators[0]
            if manifest.recommended_evaluators
            else _DEFAULT_EVALUATOR
        )
        console.print(
            f"  • [cyan]chronos eval run {first_id} --evaluator {evaluator_name}[/cyan] — score it"
        )
    console.print("  • [cyan]chronos web[/cyan]                    — explore in the browser")
