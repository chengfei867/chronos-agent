# Architectural Decision Records (ADRs)

Every architectural choice in Chronos is recorded as a single-page ADR. Each one lists Status / Context / Decision / Out of scope / Consequences in roughly that order.

## Phase 1 — Foundations

| # | Title |
|---|---|
| [ADR-001](ADR-001-language.md) | Language choice: Python 3.11+ |
| [ADR-002](ADR-002-langgraph-first-adapter.md) | LangGraph as the first adapter |
| [ADR-003](ADR-003-sqlite-schema.md) | SQLite schema |
| [ADR-004](ADR-004-langgraph-snapshot-mapping.md) | LangGraph snapshot → Node mapping |
| [ADR-005](ADR-005-fork-semantics.md) | Fork semantics |
| [ADR-006](ADR-006-diff-alignment.md) | Diff/compare alignment |
| [ADR-007](ADR-007-replay-tui-framework.md) | Replay TUI framework |
| [ADR-008](ADR-008-fork-cli-plan-artifact.md) | Fork CLI plan artifact |

## Phase 2 — Adapters & Usage

| # | Title |
|---|---|
| [ADR-009](ADR-009-usage-extractor-hook.md) | Usage extractor hook (CLI) |
| [ADR-010](ADR-010-native-usage-extractors.md) | Native usage extractors |
| [ADR-011](ADR-011-state-serialization-boundary.md) | State serialization boundary |
| [ADR-012](ADR-012-multi-llm-per-node-usage.md) | Multi-LLM per-node usage |
| [ADR-013](ADR-013-fork-auto-execution-stay-frozen.md) | Fork auto-execution stays frozen |
| [ADR-014](ADR-014-phase-2-entry-criteria.md) | Phase 2 entry criteria |
| [ADR-015](ADR-015-extractor-contract-v2.md) | Extractor contract v2 |
| [ADR-016](ADR-016-adapter-interface.md) | Adapter interface (RecorderProtocol) |

## Phase 3 — Effect-aware fork UX

| # | Title |
|---|---|
| [ADR-017](ADR-017-autogen-adapter-sync-wrap.md) | AutoGen adapter sync-wrap |
| [ADR-018](ADR-018-compare-is-diff.md) | Compare is diff |
| [ADR-019](ADR-019-chronos-does-not-sandbox.md) | Chronos does not sandbox |
| [ADR-020](ADR-020-adapter-tool-node-name-shape.md) | Adapter tool node-name shape |

## Phase 4 — N-run compare + fork-tree

| # | Title |
|---|---|
| [ADR-021](ADR-021-crewai-adapter.md) | CrewAI adapter |
| [ADR-022](ADR-022-crewai-version-pin-bump.md) | CrewAI version pin bump |
| [ADR-023](ADR-023-phase-4-charter-skeleton.md) | Phase 4 charter |
| [ADR-024](ADR-024-multi-pivot-compare.md) | Multi-pivot compare |
| [ADR-025](ADR-025-fork-tree-viz-scope.md) | Fork-tree visualisation scope |

## Phase 5 — Anthropic Agents SDK + Linear + Golden traces

| # | Title |
|---|---|
| [ADR-026](ADR-026-arc-b-scope.md) | Phase 5 Arc B scope (Anthropic Agents SDK) |
| [ADR-027](ADR-027-phase-5-arc-selection.md) | Phase 5 arc selection |
| [ADR-028](ADR-028-phase-5-arc-d-golden-traces.md) | Phase 5 Arc D — Golden traces |

## Phase 6 — v1.0 RC + Cost + Eval

| # | Title |
|---|---|
| [ADR-029](ADR-029-cost-visibility.md) | Cost & Token Tracking visibility uplift |
| [ADR-030](ADR-030-evaluation-scoring.md) | Evaluation & Scoring |

---

## Status conventions

| Status | Meaning |
|---|---|
| `Proposed` | Drafted; awaiting ratification by the next cron round. |
| `Accepted` | Ratified; implementation has landed or is in flight. |
| `Superseded by ADR-NNN` | Decision was changed; see linked successor. |
| `Deprecated` | Decision was abandoned without a direct successor. |

The full **template** for new ADRs lives at [ADR-000-template.md](ADR-000-template.md).

---

## See also

- [Concepts](../concepts/index.md) — load-bearing vocabulary the ADRs assume.
- [Roadmap](../roadmap.md) — phase-level plan and current status.
