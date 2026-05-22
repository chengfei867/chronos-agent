// anthropic_agents `formatState` formatter (R93, Phase 5 Arc C slice 2;
// extended at R94, slice 3 — block-content special rendering).
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
// R94 slice 3 adds shape-aware rendering for the three Anthropic block
// kinds:
//   - TextBlock        → `payload: { kind: 'text', text }`
//   - ToolUseBlock     → `payload: { kind: 'tool_use', name, toolUseId,
//                                   input }` (rendered as key→value table)
//   - ToolResultBlock  → `payload: { kind: 'tool_result', content,
//                                   isError, toolUseId }` (code-fenced)
//   - any other block  → `payload: { kind: 'json', value: <full block> }`
//                       (legacy fall-through)
// Header / extras / result sections keep using plain pretty-printed
// JSON strings — they don't gain from shape-aware rendering.

import type { Node } from "../../types";
import type {
  FormattedSection,
  FormattedState,
  StructuredPayload,
} from "../registry";
import { safeStringify } from "./default";

interface AnthropicBlockEntry {
  block?: {
    type?: string;
    id?: string;
    tool_use_id?: string;
    name?: string;
    text?: string;
    input?: Record<string, unknown>;
    content?: unknown;
    is_error?: boolean;
    [k: string]: unknown;
  };
}

/**
 * Build the structured payload for a single Anthropic block. Branches by
 * `block.type`:
 *   - `text`         → `{ kind: 'text', text }`
 *   - `tool_use`     → `{ kind: 'tool_use', name, toolUseId, input }`
 *   - `tool_result`  → `{ kind: 'tool_result', content, isError, toolUseId }`
 *   - anything else  → `{ kind: 'json', value: <full block> }` (legacy)
 *
 * Each branch is shape-defensive: missing/odd-typed fields fall through to
 * the `json` kind so the StatePanel never crashes on unexpected SDK output.
 * The whole formatter is also wrapped in `try/catch` by `registry.ts` (R93
 * F-2 safety net) — this is belt-and-braces.
 */
function buildBlockPayload(
  block: NonNullable<AnthropicBlockEntry["block"]>,
): StructuredPayload {
  const blockType = typeof block.type === "string" ? block.type : "";

  if (blockType === "text") {
    if (typeof block.text === "string") {
      return { kind: "text", text: block.text };
    }
    return { kind: "json", value: block };
  }

  if (blockType === "tool_use") {
    const input =
      block.input && typeof block.input === "object" && !Array.isArray(block.input)
        ? (block.input as Record<string, unknown>)
        : {};
    return {
      kind: "tool_use",
      name: typeof block.name === "string" ? block.name : undefined,
      toolUseId: typeof block.id === "string" ? block.id : undefined,
      input,
    };
  }

  if (blockType === "tool_result") {
    // SDK conventions: `content` may be a string OR a list of
    // `{type:"text",text:...}` chunks. Normalise both into a single
    // string so the renderer can drop it in a <pre>.
    let content: string;
    const rawContent: unknown = block.content;
    if (typeof rawContent === "string") {
      content = rawContent;
    } else if (Array.isArray(rawContent)) {
      content = rawContent
        .map((chunk) => {
          if (
            chunk &&
            typeof chunk === "object" &&
            "text" in chunk &&
            typeof (chunk as { text: unknown }).text === "string"
          ) {
            return (chunk as { text: string }).text;
          }
          return safeStringify(chunk);
        })
        .join("\n");
    } else {
      content = safeStringify(rawContent);
    }
    return {
      kind: "tool_result",
      content,
      isError: typeof block.is_error === "boolean" ? block.is_error : undefined,
      toolUseId:
        typeof block.tool_use_id === "string" ? block.tool_use_id : undefined,
    };
  }

  // Unknown block type — fall through to JSON view.
  return { kind: "json", value: block };
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
      // R94 slice 3: shape-aware payload (StatePanel switches on
      // `payload.kind`). Falls back to `{kind:'json'}` for unknown types
      // so the panel still renders a sensible JSON dump.
      payload: buildBlockPayload(block),
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
