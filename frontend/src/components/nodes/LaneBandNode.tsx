// LaneBandNode — R37 swimlane background band drawn as a ReactFlow node so
// it pans/zooms in lock-step with the real graph. Sits at z-index below the
// interactive chronos/placeholder nodes (handled via CSS `.chr-lane-band`).
//
// Props (via data):
//   agentId: string — the lane's agent name (displayed as header)
//   width: number   — band width in px (laneBand.x_max + right padding)
//   height: number  — band height in px
//   laneIndex: number — used to pick the band accent color (stable hash)
//   nodeCount: number — rendered as a subtle badge in the header

import React from "react";
import { useTranslation } from "react-i18next";

// Accent palette — deliberately muted so the real nodes stay visually dominant.
// Colors chosen to sit well on the #0d1117 background (R36-D cyber theme).
const LANE_ACCENTS = [
  { border: "rgba(88,166,255,0.28)", bg: "rgba(88,166,255,0.04)", text: "#79b8ff" },   // blue
  { border: "rgba(227,179,65,0.28)", bg: "rgba(227,179,65,0.04)", text: "#e3b341" },    // amber
  { border: "rgba(126,231,135,0.28)", bg: "rgba(126,231,135,0.04)", text: "#7ee787" },  // green
  { border: "rgba(210,153,255,0.28)", bg: "rgba(210,153,255,0.05)", text: "#d299ff" },  // purple
  { border: "rgba(255,128,171,0.28)", bg: "rgba(255,128,171,0.04)", text: "#ff80ab" },  // pink
  { border: "rgba(120,220,232,0.28)", bg: "rgba(120,220,232,0.04)", text: "#78dce8" },  // cyan
];

export function laneAccent(laneIndex: number) {
  return LANE_ACCENTS[laneIndex % LANE_ACCENTS.length];
}

interface LaneBandData {
  agentId: string;
  width: number;
  height: number;
  laneIndex: number;
  nodeCount: number;
}

export default function LaneBandNode({ data }: { data: LaneBandData }) {
  const { t } = useTranslation();
  const accent = laneAccent(data.laneIndex);
  return (
    <div
      className="chr-lane-band"
      style={{
        width: data.width,
        height: data.height,
        background: accent.bg,
        border: `1px dashed ${accent.border}`,
        borderRadius: 10,
        pointerEvents: "none", // lane bands don't steal clicks from real nodes
        position: "relative",
      }}
    >
      <div
        className="chr-lane-header"
        style={{
          position: "absolute",
          top: 6,
          left: 12,
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: 0.3,
          color: accent.text,
          textTransform: "uppercase",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span>{data.agentId}</span>
        <span
          style={{
            fontSize: 10,
            fontWeight: 500,
            opacity: 0.7,
            padding: "1px 6px",
            borderRadius: 4,
            background: "rgba(255,255,255,0.04)",
            color: accent.text,
          }}
        >
          {t("tree.lane.nodeCount", { count: data.nodeCount })}
        </span>
      </div>
    </div>
  );
}
