"""Shared CLI helpers — DB resolution, store opening, serialisation, JSON emit.

Extracted from ``chronos.cli.__init__`` in R14 so subcommand modules
(``runs``, ``forks``, ``diff``, ``replay``, ``fork``) can reuse them without
importing the entry-point module.

All symbols keep their original leading underscore: they are CLI-internal and
not part of the public library API.

The ``console`` re-export is deliberate — subcommand modules accept a
``console`` parameter so tests can inject a captured Rich ``Console``, but the
default instance lives here so helper functions like :func:`_open_store` can
emit consistent error styling without plumbing ``console`` through every call.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from chronos.core.models import Fork, Node, Run
from chronos.store.sqlite import SqliteStore

console = Console()

_DEFAULT_DB = "chronos.db"


def _resolve_db_path(db: Path | None) -> Path:
    """Resolve DB path: CLI flag > env var > cwd default."""
    if db is not None:
        return db
    env = os.environ.get("CHRONOS_DB")
    if env:
        return Path(env)
    return Path(_DEFAULT_DB)


def _open_store(db: Path | None) -> SqliteStore:
    """Open store, exiting with a friendly error if the file is missing.

    We deliberately do NOT auto-create the file for read commands — creating
    an empty DB on ``runs list`` in the wrong directory is a silent footgun.
    Writers (adapters) are the only callers allowed to initialise a DB.
    """
    path = _resolve_db_path(db)
    if not path.exists():
        console.print(
            f"[red]error:[/] chronos DB not found at [bold]{path}[/]. "
            "Set --db or CHRONOS_DB, or record a run first."
        )
        raise typer.Exit(code=2)
    try:
        return SqliteStore.open(path)
    except Exception as exc:  # pragma: no cover — defensive
        console.print(f"[red]error:[/] failed to open {path}: {exc}")
        raise typer.Exit(code=2) from exc


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _run_to_dict(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "adapter": run.adapter,
        "adapter_thread_id": run.adapter_thread_id,
        "status": run.status.value,
        "started_at": run.started_at.isoformat(),
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "task_description": run.task_description,
        "tags": run.tags,
        "metadata": run.metadata,
        "initial_state": run.initial_state,
        "final_state": run.final_state,
    }


def _node_to_dict(node: Node) -> dict[str, Any]:
    return {
        "id": node.id,
        "run_id": node.run_id,
        "step_index": node.step_index,
        "node_name": node.node_name,
        "kind": node.kind.value,
        "parent_node_id": node.parent_node_id,
        "started_at": node.started_at.isoformat(),
        "ended_at": node.ended_at.isoformat() if node.ended_at else None,
        "state_after": node.state_after,
        "model_name": node.model_name,
        "tool_name": node.tool_name,
        "error_message": node.error_message,
        "usage": (
            {
                "prompt_tokens": node.usage.prompt_tokens,
                "completion_tokens": node.usage.completion_tokens,
                "reasoning_tokens": node.usage.reasoning_tokens,
            }
            if node.usage is not None
            else None
        ),
        "cost_usd_cents": node.cost_usd_cents,
        "metadata": node.metadata,
    }


def _fork_to_dict(fork: Fork) -> dict[str, Any]:
    return {
        "id": fork.id,
        "parent_run_id": fork.parent_run_id,
        "parent_node_id": fork.parent_node_id,
        "child_run_id": fork.child_run_id,
        "created_at": fork.created_at.isoformat(),
        "edited_fields": fork.edited_fields,
        "reason": fork.reason,
    }


def _emit_json(payload: Any) -> None:
    # Use plain ``print`` (not the Rich console) so the output is a clean JSON
    # document consumable by jq / scripts. Rich would otherwise wrap at the
    # terminal width.
    print(json.dumps(payload, indent=2, default=str))
