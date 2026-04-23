"""Usage summary helpers for CLI token/cost rendering (ADR-009).

Extracted from ``chronos.cli.__init__`` in R14 to allow ``runs``, ``diff`` and
other subcommand modules to share the same aggregation / formatting logic
without pulling the entire CLI entry-point module.

Public symbols (consumed by peer CLI modules only — not part of the public
library API):

- :class:`_RunUsageSummary` — aggregated token + cost summary
- :func:`_summarise_usage` — reduce a node list to a summary
- :func:`_sum_usage` — convenience wrapper returning ``None`` when empty
- :func:`_fmt_usage_inline` — one-line rendering for tree labels
- :func:`_fmt_node_usage` — per-node rendering for ``runs show`` tree

The leading underscore is preserved from the original location: these are
considered internal to the CLI package and may change without notice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from chronos.core.models import Node


@dataclass
class _RunUsageSummary:
    """Aggregated usage across a run's nodes for table rendering."""

    nodes_with_usage: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd_cents: int = 0
    any_cost: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens + self.reasoning_tokens

    def tokens_cell(self) -> str:
        if self.nodes_with_usage == 0:
            return "[dim]—[/]"
        return str(self.total_tokens)

    def cost_cell(self) -> str:
        if not self.any_cost:
            return "[dim]—[/]"
        return str(self.cost_usd_cents)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes_with_usage": self.nodes_with_usage,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd_cents": self.cost_usd_cents if self.any_cost else None,
        }


def _summarise_usage(nodes: list[Node]) -> _RunUsageSummary:
    summ = _RunUsageSummary()
    for n in nodes:
        if n.usage is None:
            continue
        summ.nodes_with_usage += 1
        summ.prompt_tokens += n.usage.prompt_tokens
        summ.completion_tokens += n.usage.completion_tokens
        summ.reasoning_tokens += n.usage.reasoning_tokens
        if n.cost_usd_cents is not None:
            summ.any_cost = True
            summ.cost_usd_cents += n.cost_usd_cents
    return summ


def _sum_usage(nodes: list[Node]) -> _RunUsageSummary | None:
    summ = _summarise_usage(nodes)
    return summ if summ.nodes_with_usage > 0 else None


def _fmt_usage_inline(summ: _RunUsageSummary) -> str:
    parts = [
        f"{summ.prompt_tokens} prompt",
        f"{summ.completion_tokens} completion",
    ]
    if summ.reasoning_tokens:
        parts.append(f"{summ.reasoning_tokens} reasoning")
    parts.append(f"= [bold]{summ.total_tokens}[/] tokens")
    if summ.any_cost:
        parts.append(f"[bold]{summ.cost_usd_cents}¢[/]")
    parts.append(f"across {summ.nodes_with_usage} node(s)")
    return ", ".join(parts)


def _fmt_node_usage(node: Node) -> str:
    assert node.usage is not None
    u = node.usage
    parts = [f"{u.prompt_tokens}+{u.completion_tokens}"]
    if u.reasoning_tokens:
        parts.append(f"(+{u.reasoning_tokens} reasoning)")
    parts.append(f"= {u.prompt_tokens + u.completion_tokens + u.reasoning_tokens} tokens")
    if node.cost_usd_cents is not None:
        parts.append(f"{node.cost_usd_cents}¢")
    if node.model_name:
        parts.append(f"[dim]{node.model_name}[/]")
    return " ".join(parts)
