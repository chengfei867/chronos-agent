// Transforms a neutral-tree response from GET /runs/{id}/tree into the
// { nodes, edges } pair that ReactFlow expects, plus a deterministic layout.
//
// Design notes:
// - We do NOT ship dagre/elkjs for layout — those are ~80KB gzipped each and
//   this is a local-dev viewer, not a consumer app. A hand-rolled
//   breadth-first layered layout gives good-enough positions for trees up to
//   ~30 nodes (which is 99% of local dev cases).
// - Fork edges point to the first node of a child run ("fork" kind). When
//   that child has no nodes yet (still-running fork), the edge target is
//   null and we render a placeholder node labeled "unresolved branch" — so
//   the user can see the branch exists even before the child completes.
// - Layout algorithm: compute depth (longest sequential-parent chain) for
//   every node, group by depth, place siblings horizontally. Forks bump the
//   child's first node into a new column to the right of the parent's last
//   sequential descendant.

import type { Node as ChronosNode, Tree, TreeEdge } from "./types";
import type { Edge, Node as RFNode } from "@xyflow/react";

const NODE_WIDTH = 200;
const NODE_HEIGHT = 70;
const H_GAP = 80; // horizontal gap between layers
const V_GAP = 30; // vertical gap between siblings in same layer

interface LayoutResult {
  rfNodes: RFNode[];
  rfEdges: Edge[];
}

interface Placeholder {
  id: string;
  label: string;
  fork_id: string;
  child_run_id: string;
}

export function treeToReactFlow(tree: Tree): LayoutResult {
  const nodeById = new Map<string, ChronosNode>();
  for (const n of tree.nodes) nodeById.set(n.id, n);

  // ---- Step 1: build adjacency from sequential edges (ignore fork edges for
  // depth computation so forks don't cause the within-run tree to spread).
  const seqChildren = new Map<string, string[]>();
  const seqParents = new Map<string, string>();
  for (const e of tree.edges) {
    if (e.kind !== "sequential") continue;
    const arr = seqChildren.get(e.from) ?? [];
    arr.push(e.to);
    seqChildren.set(e.from, arr);
    seqParents.set(e.to, e.from);
  }

  // ---- Step 2: placeholder synthesis for forks with null target.
  const placeholders: Placeholder[] = [];
  for (const e of tree.edges) {
    if (e.kind === "fork" && e.to === null) {
      placeholders.push({
        id: `fork-placeholder-${e.fork_id}`,
        label: "unresolved branch",
        fork_id: e.fork_id,
        child_run_id: e.child_run_id,
      });
    }
  }

  // ---- Step 3: compute depth for every real node (distance from an ancestor
  // that has no sequential parent). Simple memoized recursion — the graph is
  // a forest of trees by construction (parent_node_id is a scalar).
  const depthCache = new Map<string, number>();
  function depth(nodeId: string): number {
    const cached = depthCache.get(nodeId);
    if (cached !== undefined) return cached;
    const parent = seqParents.get(nodeId);
    const d = parent === undefined ? 0 : depth(parent) + 1;
    depthCache.set(nodeId, d);
    return d;
  }

  // ---- Step 4: group real nodes by depth, sort within a depth by step_index
  // (which reflects real-world ordering from the recorder).
  const byDepth = new Map<number, ChronosNode[]>();
  for (const n of tree.nodes) {
    const d = depth(n.id);
    const arr = byDepth.get(d) ?? [];
    arr.push(n);
    byDepth.set(d, arr);
  }
  for (const arr of byDepth.values()) {
    arr.sort((a, b) => a.step_index - b.step_index);
  }

  // ---- Step 5: placeholders get placed at (parent_depth + 1) in their own
  // column after the real nodes at that depth.
  const forkEdgesByParent = new Map<string, TreeEdge & { kind: "fork" }>();
  for (const e of tree.edges) {
    if (e.kind === "fork") forkEdgesByParent.set(e.from, e);
  }

  const rfNodes: RFNode[] = [];
  const rfEdges: Edge[] = [];

  // Real nodes
  for (const [d, arr] of byDepth) {
    for (let i = 0; i < arr.length; i++) {
      const n = arr[i];
      rfNodes.push({
        id: n.id,
        type: "chronos",
        position: {
          x: d * (NODE_WIDTH + H_GAP),
          y: i * (NODE_HEIGHT + V_GAP),
        },
        data: { node: n },
      });
    }
  }

  // Placeholder nodes: place each one at parent_depth + 1, stacked below the
  // last real node at that depth.
  for (const p of placeholders) {
    // Find the fork edge this placeholder belongs to.
    let parentId: string | null = null;
    for (const [pid, fe] of forkEdgesByParent) {
      if (fe.fork_id === p.fork_id) {
        parentId = pid;
        break;
      }
    }
    const parentDepth = parentId ? depth(parentId) : 0;
    const placeDepth = parentDepth + 1;
    const existing = byDepth.get(placeDepth)?.length ?? 0;
    const yIdx =
      existing + placeholders.filter((x) => x.fork_id <= p.fork_id).length - 1;
    rfNodes.push({
      id: p.id,
      type: "placeholder",
      position: {
        x: placeDepth * (NODE_WIDTH + H_GAP),
        y: yIdx * (NODE_HEIGHT + V_GAP),
      },
      data: { label: p.label, fork_id: p.fork_id, child_run_id: p.child_run_id },
    });
  }

  // Edges
  for (const e of tree.edges) {
    if (e.kind === "sequential") {
      rfEdges.push({
        id: `seq-${e.from}-${e.to}`,
        source: e.from,
        target: e.to,
        type: "smoothstep",
        style: { stroke: "var(--accent)", strokeWidth: 1.5 },
      });
    } else {
      // fork edge
      const target = e.to ?? `fork-placeholder-${e.fork_id}`;
      rfEdges.push({
        id: `fork-${e.fork_id}`,
        source: e.from,
        target,
        type: "smoothstep",
        animated: true,
        style: {
          stroke: "var(--fork)",
          strokeWidth: 1.5,
          strokeDasharray: "6 4",
        },
        label: "fork",
        labelStyle: { fill: "var(--fork)", fontSize: 11, fontWeight: 600 },
        labelBgStyle: { fill: "var(--bg-elev)" },
      });
    }
  }

  void nodeById; // silence unused-import guard — reserved for future hover enrichment
  return { rfNodes, rfEdges };
}
