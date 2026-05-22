// ForkTimeline.tsx — R95 / Phase 5 Arc C slice 4 (ADR-027 §2)
//
// Renders a fork tree (root run + descendants) as an AntD <Tree> with:
//   - root run at depth 0
//   - each child placed under its parent_run_id, ordered by branch_at_step
//   - per-node: adapter tag + step_count badge + branch-at-step caption
//   - click → navigate to #/runs/<that-run-id>/replay
//
// Data comes from `projectForkTree(tree)` (frontend/src/format/forkTree.ts),
// itself fed by `fetchTree(rid, includeDescendants=true)`. Spike 18
// validated the projection contract end-to-end (16/16 GREEN at R95).
//
// Slot-1 ship: bare AntD Tree + click navigation. Slot-2 (R96) layers
// on the side-panel state preview + a custom SVG timeline ribbon for
// step-aligned visualisation if the AntD Tree proves too sparse.

import { useMemo } from "react";
import { Empty, Space, Tag, Tree, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { DataNode } from "antd/es/tree";
import type { Tree as ChronosTree } from "../types";
import { projectForkTree, type ForkTreeNode } from "../format/forkTree";

interface ForkTimelineProps {
  tree: ChronosTree;
  /**
   * Currently-active run id (highlighted in the tree). Optional —
   * defaults to the root run when omitted.
   */
  activeRunId?: string;
  /** Click handler — invoked when a tree node is selected. */
  onSelectRun?: (runId: string) => void;
}

/**
 * Build the AntD `<Tree>` data structure from a flat depth-first list.
 *
 * The flat list from `projectForkTree` gives us deterministic order, but
 * AntD Tree wants nested `children`. We rebuild the nesting here using
 * the `parent_run_id` linkage; orphans (parent_run_id present but
 * parent missing from the flat list) are surfaced at the top level so
 * they're still visible.
 */
function toTreeData(
  flat: ForkTreeNode[],
  t: (k: string, opts?: Record<string, unknown>) => string,
): DataNode[] {
  const byId = new Map<string, DataNode>();
  const childrenMap = new Map<string, DataNode[]>();
  const roots: DataNode[] = [];

  for (const n of flat) {
    const stepLabel = t("replay.fork.stepCount", { count: n.step_count });
    const branchLabel =
      n.branch_at_step === null
        ? t("replay.fork.root")
        : t("replay.fork.branchAt", { step: n.branch_at_step });

    const title = (
      <Space size={6} wrap>
        <Typography.Text strong style={{ fontFamily: "var(--chr-font-mono, monospace)" }}>
          {n.run_id.slice(0, 8)}
        </Typography.Text>
        {n.adapter ? <Tag color="geekblue">{n.adapter}</Tag> : null}
        <Tag color="default">{stepLabel}</Tag>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {branchLabel}
        </Typography.Text>
        {n.task_description ? (
          <Typography.Text type="secondary" ellipsis style={{ fontSize: 12, maxWidth: 280 }}>
            — {n.task_description}
          </Typography.Text>
        ) : null}
      </Space>
    );

    const dataNode: DataNode = {
      key: n.run_id,
      title,
      children: [],
    };
    byId.set(n.run_id, dataNode);
    if (n.parent_run_id && byId.has(n.parent_run_id)) {
      const arr = childrenMap.get(n.parent_run_id) ?? [];
      arr.push(dataNode);
      childrenMap.set(n.parent_run_id, arr);
    } else {
      roots.push(dataNode);
    }
  }

  // Splice children arrays into their parent DataNode.
  for (const [pid, kids] of childrenMap.entries()) {
    const parent = byId.get(pid);
    if (parent) parent.children = kids;
  }

  return roots;
}

export default function ForkTimeline({
  tree,
  activeRunId,
  onSelectRun,
}: ForkTimelineProps) {
  const { t } = useTranslation();
  const projected = useMemo(() => projectForkTree(tree), [tree]);

  const treeData = useMemo(() => toTreeData(projected, t), [projected, t]);

  const expandedKeys = useMemo(
    () => projected.map((n) => n.run_id),
    [projected],
  );

  if (projected.length === 0) {
    return <Empty description={t("replay.fork.empty")} />;
  }

  const selectedKeys = activeRunId ? [activeRunId] : [tree.run_id];

  return (
    <Tree
      treeData={treeData}
      defaultExpandAll
      expandedKeys={expandedKeys}
      selectedKeys={selectedKeys}
      showLine={{ showLeafIcon: false }}
      blockNode
      onSelect={(keys) => {
        const first = keys[0];
        if (typeof first === "string" && onSelectRun) {
          onSelectRun(first);
        }
      }}
      style={{ background: "transparent" }}
    />
  );
}
