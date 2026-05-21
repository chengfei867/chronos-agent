// LangGraph `formatState` formatter (R93, Phase 5 Arc C slice 2).
//
// LangGraph state_after is the user-defined State (TypedDict / Pydantic)
// after each step. Shape is flat key/value with arbitrarily-typed values.
// Common keys: `messages`, `step_count`, custom keys per graph definition.
//
// Strategy: render each top-level key as its own section. Values that are
// JSON-stringifiable are pretty-printed; primitive values are inline.

import type { Node } from "../../types";
import type { FormattedSection, FormattedState } from "../registry";
import { safeStringify } from "./default";

export function formatLangGraph(node: Node): FormattedState {
  const state = node.state_after ?? {};
  const raw = safeStringify(state);
  const sections: FormattedSection[] = [];

  if (state && typeof state === "object" && !Array.isArray(state)) {
    const entries = Object.entries(state as Record<string, unknown>);
    if (entries.length === 0) {
      sections.push({
        id: "empty",
        label: "(empty state)",
        payload: "{}",
      });
    } else {
      for (const [key, value] of entries) {
        sections.push({
          id: `lg-${key}`,
          label: key,
          subLabel: typeOf(value),
          payload: safeStringify(value),
          // Collapse arrays/objects with > 5 entries by default to keep the
          // panel scannable; primitives stay inline.
          collapsed: shouldCollapse(value),
        });
      }
    }
  } else {
    // state_after wasn't an object (unusual for langgraph but defensive)
    sections.push({
      id: "scalar",
      label: "value",
      payload: raw,
    });
  }

  return {
    adapter: "langgraph",
    envelope: "flat",
    sections,
    raw,
    isDefault: false,
  };
}

function typeOf(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return `array[${value.length}]`;
  return typeof value;
}

function shouldCollapse(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 5;
  if (value && typeof value === "object") {
    return Object.keys(value as Record<string, unknown>).length > 5;
  }
  return false;
}
