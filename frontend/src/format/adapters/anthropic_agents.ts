// anthropic_agents `formatState` formatter (R93, Phase 5 Arc C slice 2).
//
// anthropic_agents recorder (R71+, with R77 multi-block contract and R85
// envelope-determines-kind finding documented in
// docs/contracts/adapter-protocol.md) writes state_after as:
//
//     {
//       "envelope": "AssistantMessage" | "UserMessage" | "SystemMessage" |
//                   "ResultMessage",
//       "blocks": [{"block": <SDK block dict>}, ...],   // for Assistant /
//                                                       //   User envelopes
//       "tool_use_ids": ["toolu_…", ...],               // R76 linkage
//       "tool_use_id": "toolu_…",                       // for tool-result
//                                                       //   single-block
//       "model": "Claude Sonnet 4.6",
//       …
//     }
//
// Or for ResultMessage:
//
//     { "envelope": "ResultMessage", "subtype": "success", "result": "…" }
//
// Spike17 (R93) confirmed shapes round-trip byte-equal through the API
// and that `envelope` is a clean discriminator that doesn't collide with
// langgraph or other adapters.
//
// This formatter renders each block as its own section with a label like
// "Block 0 — TextBlock" and shows tool_use_id sub-labels for ToolUseBlock
// / ToolResultBlock.

import type { Node } from "../../types";
import type { FormattedSection, FormattedState } from "../registry";
import { safeStringify } from "./default";

interface AnthropicBlockEntry {
  block?: {
    type?: string;
    id?: string;
    tool_use_id?: string;
    name?: string;
    [k: string]: unknown;
  };
}

export function formatAnthropicAgents(node: Node): FormattedState {
  const state = (node.state_after ?? {}) as Record<string, unknown>;
  const raw = safeStringify(state);
  const sections: FormattedSection[] = [];

  const envelope =
    typeof state.envelope === "string" ? state.envelope : "unknown";

  // Header section — envelope + model
  const headerLines: string[] = [`envelope: ${envelope}`];
  if (typeof state.model === "string") {
    headerLines.push(`model: ${state.model}`);
  }
  if (typeof state.subtype === "string") {
    headerLines.push(`subtype: ${state.subtype}`);
  }
  if (typeof state.tool_use_id === "string") {
    headerLines.push(`tool_use_id: ${state.tool_use_id}`);
  }
  if (Array.isArray(state.tool_use_ids) && state.tool_use_ids.length > 0) {
    headerLines.push(
      `tool_use_ids: [${(state.tool_use_ids as unknown[]).map((x) => String(x)).join(", ")}]`,
    );
  }
  sections.push({
    id: "header",
    label: envelope,
    subLabel:
      typeof state.model === "string" ? (state.model as string) : undefined,
    payload: headerLines.join("\n"),
  });

  // Blocks section — one per block, with type sub-label
  const blocks = Array.isArray(state.blocks)
    ? (state.blocks as AnthropicBlockEntry[])
    : [];
  blocks.forEach((entry, idx) => {
    const block = entry?.block ?? {};
    const blockType = typeof block.type === "string" ? block.type : "unknown";
    const tuid =
      typeof block.id === "string"
        ? block.id
        : typeof block.tool_use_id === "string"
          ? block.tool_use_id
          : undefined;
    sections.push({
      id: `block-${idx}`,
      label: `Block ${idx} — ${blockType}`,
      subLabel: tuid,
      payload: safeStringify(block),
      // Collapse text blocks > 5 to keep the panel compact for long
      // conversations; first 5 stay open.
      collapsed: idx >= 5,
    });
  });

  // ResultMessage variant: no blocks, but a `result` field
  if (envelope === "ResultMessage" && typeof state.result !== "undefined") {
    sections.push({
      id: "result",
      label: "result",
      payload: safeStringify(state.result),
    });
  }

  // Catch-all "extras" section for any keys we didn't recognise above.
  // Excludes already-rendered keys.
  const known = new Set([
    "envelope",
    "blocks",
    "model",
    "subtype",
    "tool_use_id",
    "tool_use_ids",
    "result",
  ]);
  const extras: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(state)) {
    if (!known.has(k)) {
      extras[k] = v;
    }
  }
  if (Object.keys(extras).length > 0) {
    sections.push({
      id: "extras",
      label: "extras",
      payload: safeStringify(extras),
      collapsed: true,
    });
  }

  return {
    adapter: "anthropic_agents",
    envelope,
    sections,
    raw,
    isDefault: false,
  };
}
