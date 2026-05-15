"""Tool-linkage orphan-detection helpers (ADR-026 §5.1 / §5.1.1).

Slice 3a of Phase 4 Arc B (Anthropic Agents SDK adapter) introduced two
binding contracts on ``Node.state_after`` for tool round-trip linkage:

- **§5.1 (R76, single-block):** ``state_after['tool_use_id']`` is a
  scalar string set on every assistant message carrying exactly one
  ``ToolUseBlock`` and on every user message carrying exactly one
  ``ToolResultBlock``. This is the 1:1 cross-Node JOIN anchor.
- **§5.1.1 (R77, multi-block):** ``state_after['tool_use_ids']`` is an
  ordered list set on every multi-block (>1) message — both sides
  symmetrically. This is the 1:N JOIN keyset.

§5.1's fourth contract clause explicitly tolerates **orphan** result
Nodes: a ``ToolResultBlock`` whose ``tool_use_id`` does not match any
prior ``ToolUseBlock`` in the same run is allowed (it can happen when
the recorder picks up a resumed / forked session mid-conversation).
``record()`` must NOT raise for orphans — observability tooling detects
them at query time via a ``LEFT JOIN ... WHERE ... IS NULL`` shape
(see the SQL recipes in ADR-026 §5.1.1).

The helpers in this module are the in-Python equivalent of those
``LEFT JOIN`` queries. They:

- Walk every Node in the run via :meth:`SqliteStore.get_nodes_for_run`.
- Build the keyset of tool-use ids declared by *use*-side Nodes
  (``AssistantMessage*`` carrying ``ToolUseBlock``).
- Build the keyset declared by *result*-side Nodes (``UserMessage``
  carrying ``ToolResultBlock``).
- Return the Nodes whose declared ids are absent from the
  complementary keyset.

Both single-block and multi-block keysets are honored: the helper
COALESCEs ``state_after['tool_use_id']`` and
``json_each(state_after['tool_use_ids'])`` in one Python set per side.
The mutual-exclusivity invariant pinned by §5.1.1 (``len == 1 →
singular only``, ``len > 1 → plural only``) means a Node contributes
to exactly one branch of the COALESCE.

These helpers are **internal** (``chronos.queries`` is not exposed via
HTTP/CLI/adapter-interface contracts) and may evolve freely between
minor versions. They land in R78 as a slice-3a-P2 closeout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chronos.core.models import Node
    from chronos.store.sqlite import SqliteStore


__all__ = [
    "unmatched_tool_results",
    "unmatched_tool_uses",
]


def _ids_from_state_after(node: Node) -> list[str]:
    """Extract every tool-use id declared by a Node's ``state_after``.

    Honors both ``tool_use_id`` (singular, R76 §5.1) and
    ``tool_use_ids`` (plural, R77 §5.1.1). The ADR-026 §5.1.1
    mutual-exclusivity invariant means at most one of the two keys is
    present on any given Node; we tolerate both being present
    defensively (returning the union) since the contract is binding on
    writers, not readers.

    Returns an empty list for Nodes that declare no tool linkage.
    """
    state = node.state_after or {}
    out: list[str] = []
    singular = state.get("tool_use_id")
    if isinstance(singular, str) and singular:
        out.append(singular)
    plural = state.get("tool_use_ids")
    if isinstance(plural, list):
        out.extend(v for v in plural if isinstance(v, str) and v)
    return out


def _is_use_side(node: Node) -> bool:
    """``AssistantMessage`` (optionally with ``:tool_name`` postfix) is the
    use side. ``node_name`` is the canonical key per ADR-016 / ADR-020."""
    return node.node_name.startswith("AssistantMessage")


def _is_result_side(node: Node) -> bool:
    """``UserMessage`` is the result side. The recorder never appends a
    postfix to ``UserMessage`` Nodes, so equality is sufficient."""
    return node.node_name == "UserMessage"


def unmatched_tool_results(store: SqliteStore, run_id: str) -> list[Node]:
    """Nodes whose declared tool-result anchor has no matching tool-use.

    A ``UserMessage`` Node with a ``ToolResultBlock`` whose
    ``tool_use_id`` (or any element of ``tool_use_ids``) does NOT
    appear in the union of tool-use ids declared by any
    ``AssistantMessage*`` Node in the same run. This is the canonical
    "orphan tool result" signal — typically caused by a recorder
    starting from a resumed / forked session mid-conversation, per
    ADR-026 §5.1's fourth contract clause.

    Returns Nodes in stream order (``step_index`` ASC), matching the
    ordering guarantee of :meth:`SqliteStore.get_nodes_for_run`.
    Empty list if the run is fully linked or has no tool traffic.

    The complementary helper is :func:`unmatched_tool_uses`.
    """
    nodes = store.get_nodes_for_run(run_id)

    # Use-side keyset: every tool-use id any AssistantMessage Node ever
    # declared in this run.
    use_ids: set[str] = set()
    for n in nodes:
        if _is_use_side(n):
            use_ids.update(_ids_from_state_after(n))

    # A result-side Node is orphan iff at least one of its declared ids
    # is absent from use_ids. (We surface the Node, not the missing id —
    # consumers can re-extract via ``state_after`` if they need the id.)
    out: list[Node] = []
    for n in nodes:
        if not _is_result_side(n):
            continue
        ids = _ids_from_state_after(n)
        if not ids:
            continue  # No declared linkage — not an orphan, just unrelated.
        if any(tu_id not in use_ids for tu_id in ids):
            out.append(n)
    return out


def unmatched_tool_uses(store: SqliteStore, run_id: str) -> list[Node]:
    """Nodes whose declared tool-use id has no matching tool-result.

    Symmetric mirror of :func:`unmatched_tool_results`. An
    ``AssistantMessage*`` Node with a ``ToolUseBlock`` whose
    ``tool_use_id`` (or any element of ``tool_use_ids``) does NOT
    appear in the union of tool-result ids declared by any
    ``UserMessage`` Node in the same run.

    This is rarer in practice than result-side orphans (a typical
    Anthropic Agents trace records the result before the run ends) but
    matters when:

    - The recorder cuts off mid-tool-loop (failed/timeout run).
    - A fork rewinds **before** the matching ToolResultBlock arrived
      (a deliberate slice-3b time-travel scenario where the consumer
      *wants* to see which tool calls have no replies yet).

    Returns Nodes in stream order. Empty list if every tool use was
    answered or the run has no tool traffic.
    """
    nodes = store.get_nodes_for_run(run_id)

    # Result-side keyset.
    result_ids: set[str] = set()
    for n in nodes:
        if _is_result_side(n):
            result_ids.update(_ids_from_state_after(n))

    out: list[Node] = []
    for n in nodes:
        if not _is_use_side(n):
            continue
        ids = _ids_from_state_after(n)
        if not ids:
            continue
        if any(tu_id not in result_ids for tu_id in ids):
            out.append(n)
    return out
