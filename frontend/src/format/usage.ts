// R112 — token/cost rendering helpers, shared across NodeDetails / TreeView /
// Replay / Diff. Matches the CLI ``_RunUsageSummary`` rendering rules so the
// web UI never disagrees with ``chronos runs show``.
import type { Usage } from "../types";

/**
 * Best-effort total token count.
 *
 * Backends that source usage from an LLM provider may emit ``total_tokens``
 * directly; cheaper agent harnesses often record only ``prompt_tokens`` /
 * ``completion_tokens`` and leave ``total_tokens`` null. Fall back to the
 * sum so the UI never shows ``–`` when we can compute it client-side.
 *
 * Returns ``null`` if no token fields are populated at all.
 */
export function totalTokens(usage: Usage | null | undefined): number | null {
  if (!usage) return null;
  if (typeof usage.total_tokens === "number") return usage.total_tokens;
  const p = usage.prompt_tokens ?? null;
  const c = usage.completion_tokens ?? null;
  if (p == null && c == null) return null;
  return (p ?? 0) + (c ?? 0);
}

/** Format a token count for compact chip display ("1.2k" for ≥1000). */
export function formatTokensCompact(value: number | null): string {
  if (value == null) return "–";
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

/** Format USD cents → ``$0.0800``; returns ``"–"`` when null. */
export function formatCostUsd(centsValue: number | null | undefined): string {
  if (centsValue == null) return "–";
  return `$${(centsValue / 100).toFixed(4)}`;
}

/** Signed delta for diff overlays; returns ``"+12"`` / ``"-3"`` / ``"±0"``. */
export function formatTokenDelta(delta: number): string {
  if (delta === 0) return "±0";
  return delta > 0 ? `+${delta}` : String(delta);
}

/** Signed cost delta in USD (cents → dollars, 4dp). */
export function formatCostDelta(deltaCents: number): string {
  if (deltaCents === 0) return "±$0.0000";
  const sign = deltaCents > 0 ? "+" : "-";
  const abs = Math.abs(deltaCents);
  return `${sign}$${(abs / 100).toFixed(4)}`;
}
