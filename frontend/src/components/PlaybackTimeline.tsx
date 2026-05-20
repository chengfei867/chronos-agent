// PlaybackTimeline — horizontal step bar for Phase 5 Arc C slice 1 Replay UI.
// Renders one bar per node, colored by node.kind, and a movable cursor at the
// active index. Click a bar to jump; the active one gets a halo. Hover shows
// step + node_name in a tooltip.
//
// Perf budget per ADR-027 §2: ≤16ms render for 200 nodes. We keep markup flat
// (single flex row of plain divs, no antd inside the loop) and memoize the
// minimal projection. Spike 16 confirmed the data shape (dense step_index).
import { memo, useMemo } from "react";
import { Tooltip } from "antd";
import type { Node as ChronosNode, NodeKind } from "../types";

const KIND_COLORS: Record<NodeKind, string> = {
  llm: "#a371f7",
  tool: "#58a6ff",
  fn: "#3fb950",
  router: "#d29922",
  fork: "#f778ba",
  end: "#8b949e",
};

interface PlaybackTimelineProps {
  /** Nodes already sorted by step_index (caller is responsible). */
  nodes: ChronosNode[];
  /** Currently active step index, or -1 if not started. */
  activeIndex: number;
  /** Click-to-jump handler (clamped by usePlayback.jumpTo). */
  onJump: (index: number) => void;
}

function PlaybackTimelineImpl({ nodes, activeIndex, onJump }: PlaybackTimelineProps) {
  // Minimal projection — only what the bar needs. Memoized so ref-stable
  // nodes prop doesn't trigger inner work.
  const bars = useMemo(
    () =>
      nodes.map((n) => ({
        id: n.id,
        step: n.step_index,
        name: n.node_name,
        kind: n.kind,
      })),
    [nodes],
  );

  const total = bars.length;
  if (total === 0) {
    return null;
  }

  return (
    <div
      className="chr-replay-timeline"
      role="slider"
      aria-label="Replay timeline"
      aria-valuemin={0}
      aria-valuemax={total - 1}
      aria-valuenow={Math.max(0, activeIndex)}
      style={{
        display: "flex",
        gap: 2,
        alignItems: "stretch",
        width: "100%",
        height: 40,
        padding: "4px 8px",
        background: "rgba(255,255,255,0.02)",
        border: "1px solid rgba(255,255,255,0.06)",
        borderRadius: 8,
      }}
    >
      {bars.map((b) => {
        const isActive = b.step === activeIndex;
        const isPast = activeIndex >= 0 && b.step < activeIndex;
        const color = KIND_COLORS[b.kind] ?? "#8b949e";
        return (
          <Tooltip
            key={b.id}
            title={`#${b.step} · ${b.name}`}
            mouseEnterDelay={0.15}
            placement="top"
          >
            <button
              type="button"
              onClick={() => onJump(b.step)}
              aria-label={`Step ${b.step}: ${b.name}`}
              aria-current={isActive ? "step" : undefined}
              className={
                "chr-replay-tick" +
                (isActive ? " is-active" : "") +
                (isPast ? " is-past" : "")
              }
              style={{
                flex: "1 1 0",
                minWidth: 2,
                maxWidth: 24,
                border: "none",
                padding: 0,
                cursor: "pointer",
                background: isActive
                  ? color
                  : isPast
                    ? `${color}99`
                    : `${color}33`,
                outline: isActive ? `2px solid ${color}` : "none",
                outlineOffset: 1,
                borderRadius: 2,
                transition: "background 120ms ease",
              }}
            />
          </Tooltip>
        );
      })}
    </div>
  );
}

const PlaybackTimeline = memo(PlaybackTimelineImpl);
export default PlaybackTimeline;
