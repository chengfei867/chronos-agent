// Default `formatState` formatter — used when no per-adapter formatter is
// registered for a given run.adapter. Pretty-prints `node.state_after` as
// a single JSON section.

import type { Node } from "../../types";
import type { FormattedState } from "../registry";

export function formatDefault(node: Node): FormattedState {
  const raw = safeStringify(node.state_after);
  return {
    adapter: "default",
    envelope: "default",
    sections: [
      {
        id: "state_after",
        label: "state_after",
        payload: raw,
      },
    ],
    raw,
    isDefault: true,
  };
}

export function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    // Cycle-safe fallback — shouldn't happen for state_after (JSON-loaded
    // server-side) but defensive.
    return String(value);
  }
}
