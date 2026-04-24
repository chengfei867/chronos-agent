import { useEffect, useMemo, useState, useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type NodeProps,
  type Node as RFNode,
  type Edge as RFEdge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { Node as ChronosNode, Tree } from "./types";
import { fetchTree } from "./api";
import { treeToReactFlow } from "./layout";
import { NodeDetails } from "./NodeDetails";

interface Props {
  runId: string;
}

// Derive a short preview string for a node from whatever structured fields it
// has. We don't have a dedicated `content_preview` on the API contract (the
// neutral tree stays minimal), so we fall back through the most-likely signal
// sources in order.
function previewOf(n: ChronosNode): string {
  const sources: unknown[] = [
    n.tool_output,
    n.tool_input,
    n.state_after,
    n.metadata,
  ];
  for (const src of sources) {
    if (!src || typeof src !== "object") continue;
    const obj = src as Record<string, unknown>;
    // Prefer a stringy value keyed under a handful of conventional names.
    for (const key of ["text", "answer", "output", "result", "content"]) {
      const v = obj[key];
      if (typeof v === "string" && v.length > 0) return v;
    }
    // Otherwise pick the first stringy value at all.
    for (const v of Object.values(obj)) {
      if (typeof v === "string" && v.length > 0) return v;
    }
  }
  if (n.error_message) return `⚠ ${n.error_message}`;
  return "";
}

// Custom node renderer for Chronos reasoning nodes.
// Data shape is { node: ChronosNode } — see layout.ts.
function ChronosNodeView({ data }: NodeProps) {
  const n = (data as { node: ChronosNode }).node;
  const title = n.node_name || n.kind.toUpperCase();
  const raw = previewOf(n);
  const sub = raw.length > 36 ? raw.slice(0, 36) + "…" : raw;
  return (
    <div className={`chronos-node kind-${n.kind}`}>
      <div className="kind-badge">
        {n.kind} · #{n.step_index}
      </div>
      <div className="node-title">{title}</div>
      {sub ? <div className="node-sub">{sub}</div> : null}
    </div>
  );
}

// Placeholder rendered for fork edges whose child run has no nodes yet.
function PlaceholderView({ data }: NodeProps) {
  const label = (data as { label: string }).label;
  return (
    <div
      className="chronos-node kind-fork"
      style={{
        borderStyle: "dashed",
        opacity: 0.75,
        fontStyle: "italic",
      }}
    >
      <div className="kind-badge">fork</div>
      <div className="node-title">{label}</div>
    </div>
  );
}

const nodeTypes = {
  chronos: ChronosNodeView,
  placeholder: PlaceholderView,
};

export function TreeView({ runId }: Props) {
  const [tree, setTree] = useState<Tree | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<ChronosNode | null>(null);

  useEffect(() => {
    let cancelled = false;
    setTree(null);
    setErr(null);
    setSelected(null);
    fetchTree(runId)
      .then((t) => {
        if (!cancelled) setTree(t);
      })
      .catch((e: Error) => {
        if (!cancelled) setErr(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const graph = useMemo<{ rfNodes: RFNode[]; rfEdges: RFEdge[] }>(() => {
    if (!tree) return { rfNodes: [], rfEdges: [] };
    return treeToReactFlow(tree);
  }, [tree]);

  const onNodeClick = useCallback(
    (_evt: React.MouseEvent, rf: RFNode) => {
      if (rf.type !== "chronos") return;
      const payload = rf.data as { node: ChronosNode };
      setSelected(payload.node);
    },
    [],
  );

  if (err) return <div className="banner err">Failed to load tree: {err}</div>;
  if (!tree) return <div className="banner loading">Loading tree…</div>;
  if (tree.nodes.length === 0) {
    return (
      <div className="banner">
        This run has no recorded nodes yet. It may still be in progress, or it
        failed before the first step.
      </div>
    );
  }

  return (
    <div className="tree-view">
      <ReactFlow
        nodes={graph.rfNodes}
        edges={graph.rfEdges}
        nodeTypes={nodeTypes}
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#30363d" gap={20} />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeColor={() => "#58a6ff"}
          maskColor="rgba(13, 17, 23, 0.75)"
          style={{ background: "#161b22", border: "1px solid #30363d" }}
        />
      </ReactFlow>

      <div className="legend">
        <h5>Legend</h5>
        <div className="row">
          <div className="swatch" /> sequential
        </div>
        <div className="row">
          <div className="swatch fork" /> fork (cross-run)
        </div>
      </div>

      <NodeDetails node={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
