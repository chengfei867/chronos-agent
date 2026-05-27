"""Spike 20 (R111, Phase 6 ADR-029) — quickstart demo carries node.usage.

Probe: per ADR-029 §Quickstart-demo, the ``builtin-minimal`` envelopes that
``chronos quickstart`` seeds into a fresh ``chronos.db`` MUST populate
``Node.usage`` and ``Node.cost_usd_cents`` on at least one LLM-kind node per
run. This is the round trip from on-disk JSONL fixture → Pydantic ``Node`` →
SqliteStore → ``store.get_nodes_for_run()`` — the exact same code path the
``runs list`` and frontend RunList ultimately depend on.

Why a spike (not just a unit test): the chain crosses three layers (JSONL
parser, Pydantic validation, SQLite serialise/deserialise of the ``usage``
nested model) and three failure modes hit different layers:

    INV-1  Loader threads ``usage`` payload into ``Node.usage``.
        Failure: ``_build_node`` ignores the field → ``node.usage is None``.

    INV-2  Loader threads ``cost_usd_cents`` into ``Node.cost_usd_cents``.
        Failure: ``_build_node`` ignores the field → ``cost is None``.

    INV-3  Round-trip via SqliteStore preserves both fields byte-equally.
        Failure: store JSON-round-trip drops or mangles the embedded usage
        sub-document. (We trust the existing store contract here, but the
        round-trip is in the assertion path so any regression surfaces.)

This spike runs as a normal pytest (file name ``spike20_*.py``, no
``test_`` prefix is required for ``pytest -q``-collection — pytest collects
``test_`` prefix functions; we use ``test_`` prefix here so the spike is
opted into the regular suite *and* invokable directly via
``python tests/spikes/spike20_quickstart_demo_has_usage.py`` for ad-hoc runs).

Perf budget: ≤ 200 ms (single quickstart seed + read-back).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from rich.console import Console

from chronos.cli.quickstart import quickstart_command
from chronos.store.sqlite import SqliteStore


def _run_spike() -> tuple[int, int, int]:
    """Run the quickstart loader against a tmp DB and return counts.

    Returns:
        ``(runs, nodes_with_usage, nodes_with_cost)``.
    """
    with (
        tempfile.TemporaryDirectory() as td,
        open(Path(td) / "out.txt", "w", encoding="utf-8") as fh,
    ):
        db = Path(td) / "spike20.db"
        console = Console(file=fh)
        quickstart_command(demo="builtin-minimal", db=db, force=False, console=console)

        store = SqliteStore.open(db)
        try:
            runs = store.list_runs(limit=100)
            nodes_with_usage = 0
            nodes_with_cost = 0
            for r in runs:
                for n in store.get_nodes_for_run(r.id):
                    if n.usage is not None:
                        nodes_with_usage += 1
                    if n.cost_usd_cents is not None:
                        nodes_with_cost += 1
        finally:
            store.close()
        return (len(runs), nodes_with_usage, nodes_with_cost)


def test_quickstart_demo_node_usage_populated() -> None:
    """INV-1+2+3: ≥1 node per run carries ``Node.usage`` and ``cost_usd_cents``
    after the JSONL → Pydantic → SqliteStore round-trip."""
    runs, with_usage, with_cost = _run_spike()
    # The builtin-minimal demo ships 2 runs (parent + forked child).
    assert runs == 2, f"expected 2 runs from builtin-minimal demo, got {runs}"
    # At least 2 nodes (one per run, the LLM-kind ``draft`` node) carry usage.
    assert with_usage >= 2, f"expected ≥2 nodes with usage, got {with_usage}"
    # And matching cost_usd_cents.
    assert with_cost >= 2, f"expected ≥2 nodes with cost_usd_cents, got {with_cost}"


def test_quickstart_demo_summarise_usage_nonzero() -> None:
    """The ``_summarise_usage`` helper that ``runs list`` uses returns nonzero
    aggregate tokens for the parent run, proving the default-on column logic
    will render a real number (not ``—``) on a fresh ``chronos quickstart`` DB.
    """
    from chronos.cli._usage import _summarise_usage

    with (
        tempfile.TemporaryDirectory() as td,
        open(Path(td) / "out.txt", "w", encoding="utf-8") as fh,
    ):
        db = Path(td) / "spike20.db"
        console = Console(file=fh)
        quickstart_command(demo="builtin-minimal", db=db, force=False, console=console)
        store = SqliteStore.open(db)
        try:
            runs = store.list_runs(limit=100)
            assert runs, "no runs recorded"
            for r in runs:
                nodes = store.get_nodes_for_run(r.id)
                summ = _summarise_usage(nodes)
                assert summ.nodes_with_usage >= 1, (
                    f"run {r.id} has no nodes with usage — column would render '—'"
                )
                assert summ.total_tokens > 0
                assert summ.any_cost is True
        finally:
            store.close()


if __name__ == "__main__":
    # Ad-hoc runner (no pytest needed) for manual probing during development.
    runs, with_usage, with_cost = _run_spike()
    print(f"runs={runs}  nodes_with_usage={with_usage}  nodes_with_cost={with_cost}")
    sys.exit(0 if (runs == 2 and with_usage >= 2 and with_cost >= 2) else 1)
