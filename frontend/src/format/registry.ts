// Per-adapter `formatState` registry — Phase 5 Arc C slice 2 (R93, ADR-027 §2).
//
// The Replay UI's StatePanel renders `node.state_after` for each step. The
// raw JSON.stringify fallback is fine as a baseline, but each adapter has
// its own structural conventions (per docs/contracts/adapter-protocol.md
// and the per-adapter docs in docs/adapters/). The registry dispatches on
// `(adapter, node.kind)` and returns a structured "formatted view" that
// the StatePanel can render with adapter-aware UI affordances (block
// breakdown for anthropic_agents multi-block ResultMessages; flat key
// table for langgraph; etc.).
//
// Registry contract (validated by spike17, green at R93):
//   - `formatState(node, adapter)` returns a `FormattedState` describing
//     either a list of "sections" (each with a label + payload) or a
//     fallback raw JSON dump.
//   - Adapter formatters MUST be pure (no React state, no hooks, no DOM).
//   - Adapter formatters MUST be import-cycle-safe — they import only
//     from `frontend/src/types.ts`, never from components or pages.
//
// To add a new adapter formatter: write `adapters/<name>.ts` exporting
// `formatStateFor<Name>(node) -> FormattedState`, then register it in the
// `ADAPTER_FORMATTERS` map below.

import type { Node } from "../types";
import { formatAnthropicAgents } from "./adapters/anthropic_agents";
import { formatDefault } from "./adapters/default";
import { formatLangGraph } from "./adapters/langgraph";

/** A single labelled chunk in the formatted view. */
export interface FormattedSection {
  /** Stable id for React keys; e.g. `"block-0"`, `"tool_use_ids"`. */
  id: string;
  /** Short translatable-or-literal label, e.g. `"Block 0 — TextBlock"`. */
  label: string;
  /** Optional sub-label, e.g. `"toolu_bdrk_01ABC"`. */
  subLabel?: string;
  /** Pretty-printed JSON payload to show under the label. */
  payload: string;
  /** When true, the section renders collapsed by default. */
  collapsed?: boolean;
}

/** Output of a `formatState` call. */
export interface FormattedState {
  /** Adapter that produced this view (informational; for UI badges). */
  adapter: string;
  /** Discriminator used for dispatch; same value lands on the StatePanel
   *  badge. e.g. `"AssistantMessage"` for anthropic_agents, `"flat"` for
   *  langgraph. */
  envelope?: string;
  /** Structured sections to render. Empty list means "fall back to raw". */
  sections: FormattedSection[];
  /** Always-available raw JSON dump (e.g. for "Show raw" toggle). */
  raw: string;
  /** True when no specialised formatter applied; UI may show a "default
   *  view" hint. */
  isDefault: boolean;
}

/** Type of an adapter formatter function. */
export type AdapterFormatter = (node: Node) => FormattedState;

/** Registry of (lower-cased adapter string -> formatter). */
const ADAPTER_FORMATTERS: Record<string, AdapterFormatter> = {
  langgraph: formatLangGraph,
  anthropic_agents: formatAnthropicAgents,
  // Other adapters fall back to default for now (R94+ candidates):
  //   - autogen: TODO if state shape diverges enough to warrant
  //   - crewai: TODO
  //   - openai_agents: TODO
};

/**
 * Format a node's state_after for the Replay UI StatePanel.
 *
 * Dispatches on the `adapter` string (lower-cased) → per-adapter formatter
 * if registered; falls back to a generic JSON-dump formatter otherwise.
 *
 * Spike17 (R93) verified the (adapter, kind) dispatch space is collision-free
 * and that worst-case state_after payloads fit in 16KB JSON-encoded.
 */
export function formatState(
  node: Node,
  adapter: string | null | undefined,
): FormattedState {
  const key = (adapter ?? "").toLowerCase().trim();
  const formatter = key ? ADAPTER_FORMATTERS[key] : undefined;
  if (formatter) {
    try {
      return formatter(node);
    } catch (err) {
      // Adapter formatter blew up on unexpected shape — fall back to default.
      // This is the registry's safety net so a per-adapter regression can't
      // crash the whole Replay page.
      // eslint-disable-next-line no-console
      console.warn(
        `[chronos] formatState/${key} threw, falling back to default`,
        err,
      );
      return formatDefault(node);
    }
  }
  return formatDefault(node);
}

/** List of adapters that have a specialised formatter (for diagnostics). */
export function listSpecialisedAdapters(): string[] {
  return Object.keys(ADAPTER_FORMATTERS).sort();
}
