// Placeholder node for unresolved fork branches (child run has no nodes yet).
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Typography } from "antd";
import { HelpCircle } from "lucide-react";

interface PlaceholderData {
  label: string;
  fork_id: string;
  child_run_id: string;
}

export default function PlaceholderNode({ data }: NodeProps) {
  const d = (data as unknown) as PlaceholderData;
  return (
    <div className="chr-node-placeholder">
      <Handle type="target" position={Position.Left} className="chr-node-handle" />
      <HelpCircle size={14} style={{ marginRight: 6 }} />
      <Typography.Text type="secondary" italic>{d.label}</Typography.Text>
      <Handle type="source" position={Position.Right} className="chr-node-handle" />
    </div>
  );
}
