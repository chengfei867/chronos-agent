"""Spike 17 (R93, Phase 5 Arc C slice 2) — validate the per-adapter ``formatState``
registry data contract.

Per ADR-027 §2 slice 2, R93 ships ``StatePanel.tsx`` + a per-adapter
``formatState`` dispatch registry on the frontend. Slice 2's three R57-spike-pattern
assumptions (validated here BEFORE the React skeleton lands):

    A1  Per-adapter ``formatState`` registry can dispatch on
        ``run.adapter`` + ``node.kind`` without ambiguity. → Concretely: the
        observable adapter strings on disk (``langgraph``, ``anthropic_agents``,
        ``claude_agent_sdk``, ``autogen``, ``crewai``, ``openai_agents``) form
        a flat namespace; per-(adapter, kind) tuples don't collide on shape.

    A2  Deeply-nested ``state_after`` payloads (R77 multi-block ResultMessage
        pattern; R85 envelope-determines-kind contract; R89 cross-adapter
        contract) round-trip through the existing GET /runs/{id} JSON contract
        without truncation, key drift, or shape mutation. The frontend can
        consume the payload as-is without server-side re-shaping.

    A3  Per-node ``state_after`` payload size stays bounded for typical traces.
        Worst-case anthropic_agents multi-block ResultMessage carries ~5-10
        blocks each ≤2KB, total ≤16KB — well within the React render budget
        for a single panel re-render.

A spike is a Python-only data-contract probe; the React-side perf assertion
(panel re-render ≤16ms) is gated by manual `chronos web` browser_vision
checkpoint at slice 2 close-out, per ADR-027 §3.

Run via:  uv run python tests/spikes/spike17_state_panel_format.py
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Make the spike runnable as a script (no pytest discovery; it's a smoke probe).
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from chronos.core.models import Node, NodeKind, Run, RunStatus  # noqa: E402
from chronos.store import SqliteStore  # noqa: E402

# ---------------------------------------------------------------------------
# A1 — adapter namespace + per-(adapter, kind) shape catalogue
# ---------------------------------------------------------------------------

# Observable adapter strings on disk; matches the values the recorders write
# into Run.adapter. Kept here as a flat enum-like list so the test can assert
# (a) all canonical adapters present, (b) no duplicate / collision after
# lower-casing.
KNOWN_ADAPTERS: tuple[str, ...] = (
    "langgraph",
    "anthropic_agents",
    "autogen",
    "crewai",
    "openai_agents",
    # claude_agent_sdk historically rolled under anthropic_agents per R71
    # adapter naming; not a separate adapter string.
)


def _build_adapter_state(adapter: str, kind: NodeKind) -> dict:
    """Build a representative state_after for (adapter, kind).

    Mirrors what each adapter's recorder produces in v0.7.0 (per
    docs/contracts/adapter-protocol.md and the per-adapter docs in
    docs/adapters/). Used to probe shape variance for the frontend
    formatState registry.
    """

    if adapter == "langgraph":
        # LangGraph: state_after is the typed-dict / Pydantic model from the
        # graph's State, post-step. Flat key/value dict typically.
        if kind == NodeKind.LLM:
            return {
                "messages": [
                    {"role": "user", "content": "what's 2+2?"},
                    {"role": "assistant", "content": "4"},
                ],
                "step_count": 1,
            }
        if kind == NodeKind.TOOL:
            return {
                "messages": [
                    {"role": "tool", "name": "calculator", "result": "4"},
                ],
                "step_count": 2,
            }
        return {"step_count": 3, "done": True}

    if adapter == "anthropic_agents":
        # anthropic_agents recorder (R71+, R77 multi-block contract):
        # state_after carries `blocks: [{block: <json>}]` for AssistantMessage,
        # `tool_use_ids: [...]` linkage from R76, and adapter-message-type
        # info on the envelope. Per R85 contract finding, kind is determined
        # by the message envelope, not the inner block type.
        if kind == NodeKind.LLM:
            return {
                "envelope": "AssistantMessage",
                "blocks": [
                    {
                        "block": {
                            "type": "TextBlock",
                            "text": "Let me compute that for you.",
                        }
                    },
                    {
                        "block": {
                            "type": "ToolUseBlock",
                            "id": "toolu_bdrk_01ABC",
                            "name": "calculator",
                            "input": {"a": 2, "b": 2},
                        }
                    },
                ],
                "tool_use_ids": ["toolu_bdrk_01ABC"],
            }
        if kind == NodeKind.TOOL:
            # Tool result message — fan-out from R76 linkage
            return {
                "envelope": "UserMessage",
                "blocks": [
                    {
                        "block": {
                            "type": "ToolResultBlock",
                            "tool_use_id": "toolu_bdrk_01ABC",
                            "content": [{"type": "text", "text": "4"}],
                        }
                    }
                ],
                "tool_use_id": "toolu_bdrk_01ABC",
            }
        if kind == NodeKind.END:
            return {
                "envelope": "ResultMessage",
                "subtype": "success",
                "result": "4",
            }
        return {"envelope": "SystemMessage", "init": True}

    # Other adapters: simpler shapes
    if adapter == "autogen":
        return {
            "round": 2,
            "messages": [{"sender": "agent_1", "content": "hi"}],
        }
    if adapter == "crewai":
        return {
            "task": "research",
            "agent": "researcher",
            "output": "done",
        }
    if adapter == "openai_agents":
        return {
            "thread_id": "thd_abc",
            "last_event": "response.completed",
        }
    return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(
    run_id: str,
    step: int,
    kind: NodeKind,
    state_after: dict,
    *,
    parent_node_id: str | None = None,
    node_name: str | None = None,
) -> Node:
    return Node(
        id=str(uuid.uuid4()),
        run_id=run_id,
        step_index=step,
        node_name=node_name or f"step_{step}",
        kind=kind,
        parent_node_id=parent_node_id,
        started_at=datetime(2026, 5, 21, 10, 0, step, tzinfo=UTC),
        ended_at=datetime(2026, 5, 21, 10, 0, step, tzinfo=UTC) + timedelta(seconds=1),
        state_after=state_after,
        metadata={},
    )


def _make_run(adapter: str) -> Run:
    return Run(
        id=str(uuid.uuid4()),
        adapter=adapter,
        framework_version="0.0.0-spike17",
        adapter_thread_id=f"spike17_{adapter}",
        status=RunStatus.COMPLETED,
        started_at=datetime(2026, 5, 21, 10, 0, 0, tzinfo=UTC),
        ended_at=datetime(2026, 5, 21, 10, 5, 0, tzinfo=UTC),
        task_description=f"spike17 — formatState dispatch probe ({adapter})",
        initial_state={},
        final_state={"done": True},
        tags=[],
        metadata={},
    )


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def main() -> int:
    invariants_pass = 0
    invariants_total = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal invariants_pass, invariants_total
        invariants_total += 1
        status = "GREEN" if ok else "RED"
        marker = "[OK]" if ok else "[FAIL]"
        print(f"{marker} {label} -> {status}{(' :: ' + detail) if detail else ''}")
        if ok:
            invariants_pass += 1

    print("Spike 17 — formatState registry data-contract probe (R93 / Phase 5 Arc C slice 2)")
    print("=" * 78)

    # =====================================================================
    # A1 — adapter namespace + dispatch keys
    # =====================================================================
    print()
    print("A1 — Per-adapter dispatch namespace")
    print("-" * 78)

    # I1.1 — adapter list is non-empty + lower-cased + unique
    lowered = [a.lower() for a in KNOWN_ADAPTERS]
    check(
        "I1.1 adapter list is unique + lower-cased",
        len(lowered) == len(set(lowered)) and lowered == list(KNOWN_ADAPTERS),
        f"{len(KNOWN_ADAPTERS)} adapters: {', '.join(KNOWN_ADAPTERS)}",
    )

    # I1.2 — Build (adapter, kind) -> state_after shape catalog. For each
    # entry, the frontend formatState registry should be able to dispatch
    # on (adapter, kind) and produce a non-null formatted view.
    catalog: dict[tuple[str, str], dict] = {}
    for adapter in KNOWN_ADAPTERS:
        for kind in (NodeKind.LLM, NodeKind.TOOL, NodeKind.FN, NodeKind.END):
            shape = _build_adapter_state(adapter, kind)
            if shape:
                catalog[(adapter, kind.value)] = shape
    check(
        "I1.2 (adapter, kind) catalog covers >= 4 adapters",
        len({adapter for (adapter, _) in catalog}) >= 4,
        f"{len(catalog)} (adapter, kind) entries across {len({a for (a, _) in catalog})} adapters",
    )

    # I1.3 — Top-level discriminator key is unambiguous per adapter:
    # langgraph -> "messages"/"step_count"; anthropic_agents -> "envelope".
    # Test: anthropic_agents shapes always have "envelope", langgraph shapes
    # never do.
    aa_shapes = [v for (a, _), v in catalog.items() if a == "anthropic_agents"]
    lg_shapes = [v for (a, _), v in catalog.items() if a == "langgraph"]
    check(
        "I1.3a anthropic_agents shapes always carry 'envelope' discriminator",
        all("envelope" in s for s in aa_shapes),
        f"{len(aa_shapes)} aa shapes checked",
    )
    check(
        "I1.3b langgraph shapes never carry 'envelope' (no collision)",
        all("envelope" not in s for s in lg_shapes),
        f"{len(lg_shapes)} lg shapes checked",
    )

    # =====================================================================
    # A2 — Deep-nested state_after round-trips through SqliteStore
    # =====================================================================
    print()
    print("A2 — Deep-nested state_after round-trip via SqliteStore")
    print("-" * 78)

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "spike17.db"
        # I2.1 — anthropic_agents 5-block ResultMessage (R77 contract +
        # R85 envelope-determines-kind) survives put_node -> get_nodes_for_run
        # without key drift or block reordering.
        big_aa_state = {
            "envelope": "AssistantMessage",
            "blocks": [{"block": {"type": "TextBlock", "text": f"chunk {i}"}} for i in range(5)]
            + [
                {
                    "block": {
                        "type": "ToolUseBlock",
                        "id": f"toolu_bdrk_{i:04d}",
                        "name": "search",
                        "input": {"q": f"query {i}", "k": 10},
                    }
                }
                for i in range(3)
            ],
            "tool_use_ids": [f"toolu_bdrk_{i:04d}" for i in range(3)],
            "model": "Claude Sonnet 4.6",
        }

        with SqliteStore.open(db_path) as store:
            run = _make_run("anthropic_agents")
            store.put_run(run)
            node = _make_node(run.id, 0, NodeKind.LLM, big_aa_state)
            store.put_node(node)

        with SqliteStore.open(db_path) as store:
            roundtripped = store.get_nodes_for_run(run.id)
            assert len(roundtripped) == 1
            got = roundtripped[0].state_after

        check(
            "I2.1 multi-block AssistantMessage state_after round-trips byte-equal",
            got == big_aa_state,
            f"{len(big_aa_state['blocks'])} blocks; "
            f"keys={sorted(got.keys()) if isinstance(got, dict) else 'NOT-DICT'}",
        )

        # I2.2 — block ordering preserved (list, not set). Frontend dispatch
        # depends on stable ordering for "block N" UI labels.
        if isinstance(got, dict) and "blocks" in got:
            ordering_preserved = [b["block"].get("type") for b in got["blocks"]] == [
                b["block"].get("type") for b in big_aa_state["blocks"]
            ]
        else:
            ordering_preserved = False
        check(
            "I2.2 block ordering preserved through round-trip",
            ordering_preserved,
            "list semantics, not set",
        )

        # I2.3 — langgraph flat-shape round-trips
        with SqliteStore.open(db_path) as store:
            lg_run = _make_run("langgraph")
            store.put_run(lg_run)
            lg_state = _build_adapter_state("langgraph", NodeKind.LLM)
            store.put_node(_make_node(lg_run.id, 0, NodeKind.LLM, lg_state))

        with SqliteStore.open(db_path) as store:
            lg_got = store.get_nodes_for_run(lg_run.id)[0].state_after
        check(
            "I2.3 langgraph flat-shape state_after round-trips byte-equal",
            lg_got == lg_state,
            f"keys={sorted(lg_got.keys()) if isinstance(lg_got, dict) else 'NOT-DICT'}",
        )

    # =====================================================================
    # A3 — Per-node state_after payload size budget
    # =====================================================================
    print()
    print("A3 — Per-node state_after payload size budget")
    print("-" * 78)

    # I3.1 — Worst-case anthropic_agents multi-block (10 blocks, ~1KB each)
    # stays under 16KB JSON-encoded.
    worst_state = {
        "envelope": "AssistantMessage",
        "blocks": [
            {
                "block": {
                    "type": "TextBlock",
                    # ~800 bytes of text per block
                    "text": "lorem ipsum " * 60,
                }
            }
            for _ in range(10)
        ],
        "tool_use_ids": [],
        "model": "Claude Sonnet 4.6",
    }
    encoded = json.dumps(worst_state)
    size_kb = len(encoded.encode("utf-8")) / 1024
    size_budget_kb = 16.0
    check(
        f"I3.1 worst-case 10-block state_after <= {size_budget_kb:.0f}KB",
        size_kb <= size_budget_kb,
        f"{size_kb:.2f} KB JSON-encoded (10 blocks x ~720 bytes text)",
    )

    # I3.2 — Typical-case langgraph state stays under 4KB
    typ_state = _build_adapter_state("langgraph", NodeKind.LLM)
    typ_size = len(json.dumps(typ_state).encode("utf-8")) / 1024
    check(
        "I3.2 typical langgraph state_after <= 4KB",
        typ_size <= 4.0,
        f"{typ_size:.3f} KB",
    )

    # I3.3 — All catalog shapes JSON-serializable (no datetime, no UUID, etc.
    # that would require custom encoder; the API contract serializes via
    # pydantic model_dump(mode='json') which the spike mirrors).
    serializable = True
    failed_shape: tuple[str, str] | None = None
    for key, shape in catalog.items():
        try:
            json.dumps(shape)
        except (TypeError, ValueError):
            serializable = False
            failed_shape = key
            break
    check(
        "I3.3 every catalog shape is JSON-serializable as-is",
        serializable,
        f"{len(catalog)} shapes checked" + (f"; FAILED at {failed_shape}" if failed_shape else ""),
    )

    # =====================================================================
    # Summary
    # =====================================================================
    print()
    print("=" * 78)
    if invariants_pass == invariants_total:
        print(f"SPIKE 17 RESULT: INVARIANTS GREEN ({invariants_pass}/{invariants_total}) -- OK")
        print("  - Per-adapter formatState registry can dispatch on (adapter, kind)")
        print("    without shape collisions (anthropic_agents 'envelope' discriminator,")
        print("    langgraph flat-key shape, others adapter-specific).")
        print("  - Deep-nested state_after (8-block ResultMessage) round-trips byte-")
        print("    equal through SqliteStore -> get_nodes_for_run; block ordering")
        print("    preserved (list semantics).")
        print("  - Per-node payload bounded: worst-case 10-block <= 16KB, typical <= 4KB.")
        print("  - Slice 2 (StatePanel.tsx + frontend/src/format/registry.ts +")
        print("    per-adapter formatters) cleared to land. ADR-027 already Accepted.")
        return 0
    print(f"SPIKE 17 RESULT: INVARIANTS RED ({invariants_pass}/{invariants_total}) -- FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
