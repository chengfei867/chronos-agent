"""Fork plan — portable, commit-able JSON artifact describing a proposed fork.

See :doc:`docs/decisions/ADR-008-fork-cli-plan-artifact` for the motivation.

Typical flow::

    # 1. Generate plan from the CLI:
    #    chronos fork plan <parent_run_id> --at-node research --override research=...

    # 2. User code loads and hands it to the adapter's fork():
    from chronos.fork_plan import load_plan

    plan = load_plan("fork_plan.json")
    with recorder.fork(graph, **plan.recorder_kwargs()) as ref:
        graph.invoke(None, {"configurable": {"thread_id": plan.child_thread_id}})
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chronos import __version__

#: Schema version for the persisted JSON artifact. Bump on breaking changes.
FORK_PLAN_VERSION = 1


class ForkPlanError(ValueError):
    """Raised when a fork plan is malformed, unsupported, or inconsistent."""


@dataclass
class ForkPlan:
    """A validated, ready-to-consume fork plan.

    Serialize via :meth:`to_json` or :meth:`dump` and reconstruct with
    :func:`load_plan`. Consumer code gets the exact kwargs for
    ``recorder.fork()`` from :meth:`recorder_kwargs`.
    """

    parent_run_id: str
    parent_node_id: str
    parent_node_name: str
    parent_node_index: int
    child_thread_id: str
    overrides: dict[str, Any]
    reason: str | None = None
    tags: list[str] = field(default_factory=list)
    task_description: str | None = None
    # Provenance (informational only — not passed to recorder.fork)
    generated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    chronos_version: str = __version__
    plan_version: int = FORK_PLAN_VERSION

    # ------------------------------------------------------------------
    # Consumer API
    # ------------------------------------------------------------------

    def recorder_kwargs(self) -> dict[str, Any]:
        """Return the exact kwargs ``LangGraphRecorder.fork()`` accepts.

        Drops provenance fields (``generated_at``, ``chronos_version``,
        ``plan_version``) and convenience fields (``parent_node_name``,
        ``parent_node_index``) that the adapter does not take.
        """
        kwargs: dict[str, Any] = {
            "parent_run_id": self.parent_run_id,
            "at_node_id": self.parent_node_id,
            "overrides": copy.deepcopy(self.overrides),
            "child_thread_id": self.child_thread_id,
        }
        if self.reason is not None:
            kwargs["reason"] = self.reason
        if self.tags:
            kwargs["tags"] = list(self.tags)
        if self.task_description is not None:
            kwargs["task_description"] = self.task_description
        return kwargs

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a stable, key-ordered dict."""
        # Ordered explicitly so the JSON file is diff-friendly.
        return {
            "chronos_fork_plan_version": self.plan_version,
            "parent_run_id": self.parent_run_id,
            "parent_node_id": self.parent_node_id,
            "parent_node_name": self.parent_node_name,
            "parent_node_index": self.parent_node_index,
            "child_thread_id": self.child_thread_id,
            "overrides": self.overrides,
            "reason": self.reason,
            "tags": list(self.tags),
            "task_description": self.task_description,
            "generated_at": self.generated_at,
            "chronos_version": self.chronos_version,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_python(self, *, recorder_var: str = "recorder", graph_var: str = "graph") -> str:
        """Render the plan as a self-contained, pastable Python stub.

        The output is ADR-013 deferred alternative C: a middle ground between
        raw JSON (too bare) and execute-fork (ADR-008 rejected). Chronos
        generates glue code; the user pastes it into their own graph setup.

        The generated code does NOT read the JSON plan at runtime -- it
        inlines the fork kwargs as Python literals, so it is a standalone
        artifact. Two ``TODO(user)`` markers show where to wire the real
        ``recorder`` and ``graph`` objects.

        Args:
            recorder_var: Name of the Recorder variable in the stub.
                Defaults to ``"recorder"``.
            graph_var: Name of the graph variable in the stub.
                Defaults to ``"graph"``.

        Returns:
            A UTF-8 string of valid Python 3.11+ source. Always ends with a
            single trailing newline so it is safe to pipe to a file.
        """
        kwargs = self.recorder_kwargs()

        # Pretty-print kwargs as Python literals. We deliberately use
        # ``repr`` for each value -- it produces valid Python for strings,
        # ints, bools, None, lists, and dicts of those, which covers every
        # ForkPlan field. Custom objects in overrides would already have
        # broken ``to_json``, so ``repr`` is not a new failure surface.
        kwargs_lines = []
        for key, value in kwargs.items():
            kwargs_lines.append(f"    {key}={value!r},")
        kwargs_block = "\n".join(kwargs_lines)

        # Child thread id for the graph.invoke config dict.
        child_thread_repr = repr(self.child_thread_id)

        header_reason = self.reason if self.reason is not None else "(no reason provided)"

        return f'''"""Fork stub generated by Chronos Agent.

Plan provenance:
    parent_run_id    = {self.parent_run_id!r}
    parent_node      = {self.parent_node_name!r} (index {self.parent_node_index})
    child_thread_id  = {self.child_thread_id!r}
    reason           = {header_reason!r}
    chronos_version  = {self.chronos_version!r}
    generated_at     = {self.generated_at!r}

This file is ADR-013 deferred alternative C: glue code you paste into your
own graph setup. Chronos does NOT execute your graph for you; wiring the
two TODO(user) blocks below is your step.
"""

# TODO(user): import your Recorder and construct it against your SqliteStore.
# Example (LangGraph adapter):
#
#     from chronos.store.sqlite import SqliteStore
#     from chronos.adapters.langgraph import LangGraphRecorder
#
#     store = SqliteStore("chronos.db")
#     store.open()
#     {recorder_var} = LangGraphRecorder(store=store)

# TODO(user): build or import your compiled LangGraph ``{graph_var}`` here.
# It must be the same graph (same nodes, same edges) as the parent run.

# Fork kwargs are inlined below as Python literals -- no JSON file needed.
with {recorder_var}.fork(
    {graph_var},
{kwargs_block}
) as ref:
    {graph_var}.invoke(
        None,
        {{"configurable": {{"thread_id": {child_thread_repr}}}}},
    )
    print(f"fork child run: {{ref.run_id}}")
'''

    def dump(self, path: str | Path, *, indent: int = 2) -> Path:
        """Write the plan as JSON to ``path``. Returns the resolved path."""
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(indent=indent) + "\n", encoding="utf-8")
        return target

    # Compat helper — asdict() on dataclass loses key ordering control,
    # but is useful for tests / debugging.
    def as_plain_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_plan(path: str | Path) -> ForkPlan:
    """Load a fork plan from a JSON file.

    Raises :class:`ForkPlanError` for missing/unknown/mismatched schema versions
    and :class:`FileNotFoundError` if the file is absent.
    """
    src = Path(path).expanduser()
    if not src.exists():
        raise FileNotFoundError(f"fork plan not found: {src}")
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ForkPlanError(f"invalid JSON in {src}: {exc}") from exc
    return plan_from_dict(raw)


def plan_from_dict(raw: dict[str, Any]) -> ForkPlan:
    """Construct a ForkPlan from a parsed JSON dict, validating the schema."""
    if not isinstance(raw, dict):
        raise ForkPlanError(f"fork plan must be a JSON object, got {type(raw).__name__}")

    version = raw.get("chronos_fork_plan_version")
    if version is None:
        raise ForkPlanError(
            "missing required field 'chronos_fork_plan_version' — "
            "is this file actually a chronos fork plan?"
        )
    if version != FORK_PLAN_VERSION:
        raise ForkPlanError(
            f"unsupported fork plan version {version!r} "
            f"(this chronos supports v{FORK_PLAN_VERSION})"
        )

    required = (
        "parent_run_id",
        "parent_node_id",
        "parent_node_name",
        "parent_node_index",
        "child_thread_id",
        "overrides",
    )
    missing = [k for k in required if k not in raw]
    if missing:
        raise ForkPlanError(f"fork plan missing required fields: {missing}")

    overrides = raw["overrides"]
    if not isinstance(overrides, dict):
        raise ForkPlanError("'overrides' must be a JSON object")

    tags_raw = raw.get("tags") or []
    if not isinstance(tags_raw, list) or not all(isinstance(t, str) for t in tags_raw):
        raise ForkPlanError("'tags' must be a list of strings")

    return ForkPlan(
        parent_run_id=str(raw["parent_run_id"]),
        parent_node_id=str(raw["parent_node_id"]),
        parent_node_name=str(raw["parent_node_name"]),
        parent_node_index=int(raw["parent_node_index"]),
        child_thread_id=str(raw["child_thread_id"]),
        overrides=dict(overrides),
        reason=raw.get("reason"),
        tags=list(tags_raw),
        task_description=raw.get("task_description"),
        generated_at=str(raw.get("generated_at", "")),
        chronos_version=str(raw.get("chronos_version", "")),
        plan_version=int(version),
    )


__all__ = [
    "FORK_PLAN_VERSION",
    "ForkPlan",
    "ForkPlanError",
    "load_plan",
    "plan_from_dict",
]
