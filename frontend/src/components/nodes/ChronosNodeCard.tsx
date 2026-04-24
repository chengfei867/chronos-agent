// Custom ReactFlow node for Chronos — polished card-style rendering with
// kind icon, status dot, step index, and an optional "playing" halo when
// the play-from-start feature is currently highlighting this node.
import React from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Tag, Typography, Tooltip } from "antd";
import {
  Brain,
  Wrench,
  Code2,
  GitFork,
  Flag,
  Split,
} from "lucide-react";
import type { Node as ChronosNode, NodeKind } from "../../types";
import { useTranslation } from "react-i18next";

const KIND_ICONS: Record<NodeKind, React.ReactNode> = {
  llm: <Brain size={14} />,
  tool: <Wrench size={14} />,
  fn: <Code2 size={14} />,
  router: <Split size={14} />,
  fork: <GitFork size={14} />,
  end: <Flag size={14} />,
};

const KIND_COLORS: Record<NodeKind, string> = {
  llm: "#a371f7",      // purple
  tool: "#58a6ff",     // blue
  fn: "#3fb950",       // green
  router: "#d29922",   // gold
  fork: "#f778ba",     // pink
  end: "#8b949e",      // muted
};

interface ChronosNodeData {
  node: ChronosNode;
  isPlaying?: boolean;
  isPlayed?: boolean;
  isSelected?: boolean;
  /** R39-A diff mode: when set, tints the card border to convey diff status. */
  diffStatus?: "equal" | "changed" | "added" | "removed";
  /** R39-A diff mode: when true, this node is currently highlighted via alignment list click. */
  diffFocused?: boolean;
}

export default function ChronosNodeCard({ data, selected }: NodeProps) {
  const { t } = useTranslation();
  const { node, isPlaying, isPlayed, diffStatus, diffFocused } = (data as unknown) as ChronosNodeData;
  const color = KIND_COLORS[node.kind];
  const icon = KIND_ICONS[node.kind];
  const kindLabel = t(`nodeKind.${node.kind}`, { defaultValue: node.kind });
  const hasError = !!node.error_message;

  const classNames = [
    "chr-node-card",
    selected ? "is-selected" : "",
    isPlaying ? "is-playing" : "",
    isPlayed ? "is-played" : "",
    hasError ? "has-error" : "",
    diffStatus ? `chr-node-card--diff-${diffStatus}` : "",
    diffFocused ? "chr-node-card--diff-focused" : "",
  ].filter(Boolean).join(" ");

  return (
    <div className={classNames} style={{ ["--accent" as string]: color }}>
      <Handle type="target" position={Position.Left} className="chr-node-handle" />
      <div className="chr-node-card-head">
        <span className="chr-node-kind-icon" aria-hidden>{icon}</span>
        <Tag color={hasError ? "red" : undefined} bordered={false} style={{ marginInlineEnd: 0 }}>
          {kindLabel}
        </Tag>
        <span className="chr-node-step">#{node.step_index}</span>
      </div>
      <Tooltip title={node.node_name} mouseEnterDelay={0.3}>
        <Typography.Text strong ellipsis className="chr-node-name">
          {node.node_name}
        </Typography.Text>
      </Tooltip>
      {node.model_name && (
        <Typography.Text type="secondary" ellipsis className="chr-node-sub">
          {node.model_name}
        </Typography.Text>
      )}
      {hasError && (
        <Typography.Text type="danger" ellipsis className="chr-node-sub">
          ⚠ {node.error_message}
        </Typography.Text>
      )}
      <Handle type="source" position={Position.Right} className="chr-node-handle" />
    </div>
  );
}
