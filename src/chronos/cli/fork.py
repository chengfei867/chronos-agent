"""Chronos fork CLI — emits portable fork plan JSON artifacts.

See ``docs/decisions/ADR-008-fork-cli-plan-artifact.md`` for the design.

The CLI never executes user graph code. It validates overrides against a
parent node's ``state_after`` and writes a ``fork_plan.json`` that the
user's code loads and hands to ``recorder.fork()``.

Public entry point: the ``fork`` subcommand registered via
:func:`register` in ``chronos.cli.__init__``.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from chronos.adapters.effects import DANGEROUS_EFFECTS_DEFAULT
from chronos.core.models import Node, Run
from chronos.fork_plan import ForkPlan

# ---------------------------------------------------------------------------
# Pure helpers (unit-testable without a filesystem)
# ---------------------------------------------------------------------------


class ForkCLIError(Exception):
    """User-facing errors from the fork CLI (printed, exit code 1)."""


def parse_override_token(token: str) -> tuple[str, Any]:
    """Parse ``key=value`` into ``(key, parsed_value)``.

    ``value`` is parsed as JSON first (so ``123``, ``true``, ``[1,2]``,
    ``"quoted"`` all work), falling back to the raw string when JSON
    parsing fails. Keys are everything left of the first ``=``.

    >>> parse_override_token("n=3")
    ('n', 3)
    >>> parse_override_token("enabled=true")
    ('enabled', True)
    >>> parse_override_token("note=hello world")
    ('note', 'hello world')
    """
    if "=" not in token:
        raise ForkCLIError(
            f"--override must be key=value, got {token!r} (use --override-json for complex values)"
        )
    key, _, raw = token.partition("=")
    key = key.strip()
    if not key:
        raise ForkCLIError(f"--override has empty key in {token!r}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw  # fall back to raw string
    return key, value


def merge_overrides(
    kv_tokens: list[str],
    json_blobs: list[str],
) -> dict[str, Any]:
    """Merge ``--override k=v`` tokens with ``--override-json`` blobs.

    Later values win on collision, and all ``--override`` tokens apply
    before ``--override-json`` blobs so a JSON blob can always override.
    """
    merged: dict[str, Any] = {}
    for token in kv_tokens:
        k, v = parse_override_token(token)
        merged[k] = v
    for raw in json_blobs:
        try:
            blob = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ForkCLIError(f"--override-json is not valid JSON: {exc}") from exc
        if not isinstance(blob, dict):
            raise ForkCLIError(f"--override-json must be a JSON object, got {type(blob).__name__}")
        merged.update(blob)
    return merged


def resolve_parent_node(
    nodes: list[Node],
    *,
    at_node: str | None,
    at_index: int | None,
    at_node_id: str | None,
) -> Node:
    """Pick the parent node using exactly one selector.

    Raises :class:`ForkCLIError` with a helpful message on ambiguity,
    missing node, or conflicting selectors.
    """
    provided = [
        name
        for name, val in (
            ("--at-node", at_node),
            ("--at-index", at_index),
            ("--at-node-id", at_node_id),
        )
        if val is not None
    ]
    if len(provided) == 0:
        raise ForkCLIError(
            "fork point selector required: pass one of --at-node / --at-index / --at-node-id"
        )
    if len(provided) > 1:
        raise ForkCLIError(
            f"fork point selectors are exclusive: got {', '.join(provided)} — pick one"
        )

    if at_node_id is not None:
        match = next((n for n in nodes if n.id == at_node_id), None)
        if match is None:
            raise ForkCLIError(f"--at-node-id {at_node_id!r} not found in this run")
        return match

    if at_index is not None:
        match = next((n for n in nodes if n.step_index == at_index), None)
        if match is None:
            idxs = sorted({n.step_index for n in nodes})
            raise ForkCLIError(f"--at-index {at_index} not found in this run (available: {idxs})")
        return match

    # at_node: match by node_name. Ambiguity is common in loops/routers.
    assert at_node is not None
    matches = [n for n in nodes if n.node_name == at_node]
    if not matches:
        names = sorted({n.node_name for n in nodes})
        raise ForkCLIError(f"--at-node {at_node!r} not found (available names: {names})")
    if len(matches) > 1:
        indices = [n.step_index for n in matches]
        raise ForkCLIError(
            f"--at-node {at_node!r} is ambiguous — appears at step indices {indices}. "
            "Use --at-index or --at-node-id to disambiguate."
        )
    return matches[0]


def validate_overrides_against_state(
    overrides: dict[str, Any],
    state_after: dict[str, Any] | None,
    *,
    allow_new_keys: bool,
) -> list[str]:
    """Return a list of warnings (empty if allow_new_keys=True).

    Raises :class:`ForkCLIError` if unknown keys appear without
    ``allow_new_keys=True``.
    """
    warnings: list[str] = []
    if state_after is None:
        # Parent node has no captured state_after (rare — adapter bug?).
        # If the user wants to fork with no overrides, that's fine.
        if overrides and not allow_new_keys:
            raise ForkCLIError(
                "parent node has no state_after, cannot validate overrides. "
                "Pass --allow-new-keys to force."
            )
        return warnings

    unknown = sorted(k for k in overrides if k not in state_after)
    if unknown:
        if not allow_new_keys:
            available = sorted(state_after.keys())
            raise ForkCLIError(
                f"override keys not present in parent state_after: {unknown}. "
                f"Available keys: {available}. "
                "Pass --allow-new-keys to add them anyway."
            )
        warnings.append(f"adding new state keys (allow-new-keys): {unknown}")

    # Type warnings (non-fatal).
    for k, v in overrides.items():
        if k in state_after and state_after[k] is not None:
            old_t = type(state_after[k]).__name__
            new_t = type(v).__name__
            # Accept None→X, X→None, and widening; warn on complete type swap.
            if v is not None and state_after[k] is not None and old_t != new_t:
                warnings.append(f"override {k!r} changes type {old_t} → {new_t}")
    return warnings


def default_child_thread_id(parent_run: Run) -> str:
    """Compose a reasonable default ``child_thread_id``."""
    return f"{parent_run.adapter_thread_id}-fork-{uuid.uuid4().hex[:8]}"


def build_plan(
    *,
    parent_run: Run,
    parent_node: Node,
    overrides: dict[str, Any],
    child_thread_id: str | None,
    reason: str | None,
    tags: list[str],
) -> ForkPlan:
    """Assemble a :class:`ForkPlan` from validated inputs."""
    return ForkPlan(
        parent_run_id=parent_run.id,
        parent_node_id=parent_node.id,
        parent_node_name=parent_node.node_name,
        parent_node_index=parent_node.step_index,
        child_thread_id=child_thread_id or default_child_thread_id(parent_run),
        overrides=overrides,
        reason=reason,
        tags=list(tags),
    )


# ---------------------------------------------------------------------------
# Rendering (UI — not unit-tested directly)
# ---------------------------------------------------------------------------


def build_effects_summary(
    downstream_nodes: list[Node],
    *,
    dangerous: frozenset[str] = DANGEROUS_EFFECTS_DEFAULT,
) -> dict[str, Any]:
    """Aggregate effect tags across downstream nodes for fork preview.

    Returns a dict with:
      - ``total``: count of downstream nodes
      - ``dangerous_count``: nodes with ≥1 tag in ``dangerous``
      - ``tag_counts``: {tag: count} across all downstream nodes
      - ``dangerous_samples``: up to 3 (step_index, node_name, effects) for
        the first dangerous nodes — lets CLI show concrete examples, not
        just an abstract count.

    Pure helper. Unit-testable without a store or recorder.
    """
    total = len(downstream_nodes)
    tag_counts: dict[str, int] = {}
    dangerous_samples: list[tuple[int, str, list[str]]] = []
    dangerous_count = 0

    for node in downstream_nodes:
        raw = node.metadata.get("effects") if node.metadata else None
        effects: list[str] = raw if isinstance(raw, list) else []
        for tag in effects:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        if any(t in dangerous for t in effects):
            dangerous_count += 1
            if len(dangerous_samples) < 3:
                dangerous_samples.append((node.step_index, node.node_name, list(effects)))

    return {
        "total": total,
        "dangerous_count": dangerous_count,
        "tag_counts": tag_counts,
        "dangerous_samples": dangerous_samples,
    }


def render_effects_preview(
    summary: dict[str, Any],
    console: Console,
) -> None:
    """Render the downstream side-effects summary panel (PH3-03).

    Silent when ``summary['total'] == 0`` (forking at the last node) or
    when ``summary['dangerous_count'] == 0`` — no dangerous effects means
    no warning needed. ADR-019 stance: honest warning, not fake safety.
    """
    total = summary["total"]
    dangerous_count = summary["dangerous_count"]
    if total == 0 or dangerous_count == 0:
        return

    # Tag breakdown (only show dangerous ones in the count line to keep it
    # focused; llm is not dangerous per ADR-019 reasoning).
    tag_counts: dict[str, int] = summary["tag_counts"]
    dangerous_tag_bits = [
        f"{tag}={tag_counts[tag]}"
        for tag in sorted(tag_counts)
        if tag in DANGEROUS_EFFECTS_DEFAULT and tag_counts[tag] > 0
    ]
    tag_line = ", ".join(dangerous_tag_bits) if dangerous_tag_bits else "—"

    lines: list[str] = []
    lines.append(
        f"[bold red]⚠ side effects:[/] forking here may re-execute "
        f"[bold]{dangerous_count}[/] dangerous downstream node(s) "
        f"out of {total} total."
    )
    lines.append(f"  breakdown: {tag_line}")

    samples = summary["dangerous_samples"]
    if samples:
        lines.append("  examples:")
        for step, name, effects in samples:
            tag_str = ",".join(effects)
            lines.append(f"    • step {step}: [cyan]{name}[/] [yellow]({tag_str})[/]")
        if dangerous_count > len(samples):
            lines.append(f"    • … and {dangerous_count - len(samples)} more")

    lines.append(
        "  [dim]Chronos does not sandbox fork execution (ADR-019). "
        "If these effects touch the real world (HTTP, DB, email, filesystem), "
        "confirm duplicate invocations are safe before running the fork.[/]"
    )

    console.print(
        Panel(
            "\n".join(lines),
            border_style="yellow",
            title="[yellow]Downstream side-effects preview[/]",
            expand=False,
        )
    )


def _truncate(text: str, limit: int = 200) -> str:
    s = text if len(text) <= limit else text[:limit] + "…"
    # Collapse newlines for one-row display.
    return s.replace("\n", " ⏎ ")


def render_plan_preview(
    plan: ForkPlan,
    parent_run: Run,
    parent_node: Node,
    warnings: list[str],
    console: Console,
    *,
    out_path: Path | None,
    emit: str = "json",
    effects_summary: dict[str, Any] | None = None,
) -> None:
    """Print a human-readable preview of a plan before/after writing it.

    When ``effects_summary`` is provided (PH3-03), a dedicated yellow
    panel above the overrides table warns about dangerous downstream
    effects. Backwards-compatible: callers that don't pass the kwarg get
    the pre-R45-A behavior.
    """
    if effects_summary is not None:
        render_effects_preview(effects_summary, console)

    state_after = parent_node.state_after or {}

    tbl = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    tbl.add_column("field", style="cyan", no_wrap=True)
    tbl.add_column("before (parent state_after)", style="dim")
    tbl.add_column("after (override)", style="green")
    for key in sorted(plan.overrides.keys()):
        before = state_after.get(key, "<absent>")
        tbl.add_row(
            key,
            _truncate(json.dumps(before, ensure_ascii=False, default=str)),
            _truncate(json.dumps(plan.overrides[key], ensure_ascii=False, default=str)),
        )
    if not plan.overrides:
        tbl.add_row("—", "<no overrides>", "<pure replay>")

    header = (
        f"[bold magenta]Fork plan[/]  parent_run=[cyan]{parent_run.id}[/]  "
        f"at=[yellow]{parent_node.node_name}[/] (step {parent_node.step_index})"
    )
    child_line = f"  child_thread_id: [green]{plan.child_thread_id}[/]"
    reason_line = f"  reason: {plan.reason or '[dim]<none>[/]'}"
    tags_line = f"  tags: {plan.tags or '[dim]<none>[/]'}"
    console.print(Panel(tbl, title=header, border_style="magenta", expand=False))
    console.print(child_line)
    console.print(reason_line)
    console.print(tags_line)
    for w in warnings:
        console.print(f"  [yellow]warning:[/] {w}")
    if out_path is not None:
        console.print(f"\n  [dim]written to[/] [bold]{out_path}[/]")
        if emit == "python":
            console.print(
                f"  [dim]fill the two TODO(user) blocks, then[/] [cyan]python {out_path.name}[/]"
            )
        else:
            console.print(
                "  [dim]consume in code with[/] [cyan]from chronos.fork_plan import load_plan[/]"
            )


# ---------------------------------------------------------------------------
# Command body — called from the Typer wrapper in cli/__init__.py
# ---------------------------------------------------------------------------


def fork_plan_command(
    *,
    run_id: str,
    at_node: str | None,
    at_index: int | None,
    at_node_id: str | None,
    overrides: list[str],
    overrides_json: list[str],
    child_thread_id: str | None,
    reason: str | None,
    tags: list[str],
    out: Path | None,
    as_json: bool,
    emit: str,
    allow_new_keys: bool,
    db: Path | None,
    open_store_fn: Any,
    console: Console,
) -> None:
    """Entry point for ``chronos fork plan``.

    ``emit`` selects the output format:

    - ``"json"`` (default): write a JSON artifact via :meth:`ForkPlan.dump`.
    - ``"python"``: write a self-contained Python stub via
      :meth:`ForkPlan.to_python`. ADR-013 deferred alternative C.

    ``as_json`` (the ``--json`` flag) is the back-compat shortcut for
    ``emit="json"`` emitted to stdout instead of a file. When both are set,
    ``as_json`` wins for back-compat.
    """
    store = open_store_fn(db)
    try:
        parent_run = store.get_run(run_id)
        if parent_run is None:
            console.print(f"[red]error:[/] no such run: [bold]{run_id}[/]")
            raise typer.Exit(code=1)
        nodes = store.get_nodes_for_run(run_id)
        if not nodes:
            console.print(f"[red]error:[/] run {run_id!r} has no nodes to fork at")
            raise typer.Exit(code=1)
    finally:
        store.close()

    try:
        parent_node = resolve_parent_node(
            nodes,
            at_node=at_node,
            at_index=at_index,
            at_node_id=at_node_id,
        )
        merged = merge_overrides(overrides, overrides_json)
        warnings = validate_overrides_against_state(
            merged,
            parent_node.state_after,
            allow_new_keys=allow_new_keys,
        )
    except ForkCLIError as exc:
        console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(code=1) from exc

    plan = build_plan(
        parent_run=parent_run,
        parent_node=parent_node,
        overrides=merged,
        child_thread_id=child_thread_id,
        reason=reason,
        tags=tags,
    )

    # PH3-03: compute downstream dangerous-effect summary for preview.
    # Note: this is per-run linear downstream (step_index > parent's), not
    # DAG-topological. Good enough for preview — matches how replay/fork
    # consumers think about "what comes after".
    downstream_nodes = [n for n in nodes if n.step_index > parent_node.step_index]
    effects_summary = build_effects_summary(downstream_nodes)

    # --json: emit to stdout, no preview, no file (back-compat shortcut).
    if as_json:
        console.print_json(plan.to_json())
        return

    # Emit Python stub (ADR-013 alt C).
    if emit == "python":
        out_path = out if out is not None else Path("fork_stub.py")
        out_path = Path(out_path).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(plan.to_python(), encoding="utf-8")
        render_plan_preview(
            plan,
            parent_run,
            parent_node,
            warnings,
            console,
            out_path=out_path,
            emit="python",
            effects_summary=effects_summary,
        )
        return

    if emit != "json":
        console.print(
            f"[red]error:[/] unknown --emit value: {emit!r} (expected 'json' or 'python')"
        )
        raise typer.Exit(code=1)

    # Default: write JSON to file, then preview.
    out_path = out if out is not None else Path("fork_plan.json")
    written = plan.dump(out_path)
    render_plan_preview(
        plan,
        parent_run,
        parent_node,
        warnings,
        console,
        out_path=written,
        effects_summary=effects_summary,
    )


__all__ = [
    "ForkCLIError",
    "build_effects_summary",
    "build_plan",
    "default_child_thread_id",
    "fork_plan_command",
    "merge_overrides",
    "parse_override_token",
    "render_effects_preview",
    "render_plan_preview",
    "resolve_parent_node",
    "validate_overrides_against_state",
]
