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
// - Single-run layout: depth = sequential-parent chain length, grouped by
//   depth into columns, siblings stacked vertically. Old behaviour preserved
//   for include_descendants=false callers.
// - Multi-run layout (R37.5-C): when nodes span multiple run_ids the layout
//   produces horizontal super-lanes, one per run, stacked top-to-bottom in
//   the order they appear in tree.descendant_run_ids. Within each lane the
//   classic depth-column layout is reused. Fork edges cross lanes visually,
//   turning the diagram into a proper "family tree" (see ADR-018, R37.5).

import type { Node as ChronosNode, Tree, TreeEdge } from "./types";
import type { Edge, Node as RFNode } from "@xyflow/react";

const NODE_WIDTH = 200;
const NODE_HEIGHT = 70;
const H_GAP = 80; // horizontal gap between layers
const V_GAP = 30; // vertical gap between siblings in same layer
const LANE_GAP = 80; // vertical gap between run-lanes
const LANE_HEADER_HEIGHT = 42; // space for the run-label at the top of a lane
const LANE_PADDING_TOP = 12;

interface LayoutResult {
  rfNodes: RFNode[];
  rfEdges: Edge[];
  lanes: LaneInfo[];
}

export interface LaneInfo {
  runId: string;
  y: number;
  height: number;
  width: number;
  label: string;
  adapter: string;
  status: string;
}

interface Placeholder {
  id: string;
  label: string;
  fork_id: string;
  child_run_id: string;
  parentRunId: string;
}

/** Layout helper: compute column (depth) + row index for each node within a
 * single run's nodes-subset. Returns positions relative to the lane origin. */
function layoutSingleRun(
  nodes: ChronosNode[],
  edges: TreeEdge[],
): { positions: Map<string, { col: number; row: number }>; maxCol: number; maxRow: number } {
  const seqChildren = new Map<string, string[]>();
  const seqParents = new Map<string, string>();
  const nodeIds = new Set(nodes.map((n) => n.id));
  for (const e of edges) {
    if (e.kind !== "sequential") continue;
    if (!nodeIds.has(e.from) || !nodeIds.has(e.to)) continue;
    const arr = seqChildren.get(e.from) ?? [];
    arr.push(e.to);
    seqChildren.set(e.from, arr);
    seqParents.set(e.to, e.from);
  }

  const depthCache = new Map<string, number>();
  function depth(nodeId: string): number {
    const cached = depthCache.get(nodeId);
    if (cached !== undefined) return cached;
    const parent = seqParents.get(nodeId);
    const d = parent === undefined ? 0 : depth(parent) + 1;
    depthCache.set(nodeId, d);
    return d;
  }

  const byDepth = new Map<number, ChronosNode[]>();
  for (const n of nodes) {
    const d = depth(n.id);
    const arr = byDepth.get(d) ?? [];
    arr.push(n);
    byDepth.set(d, arr);
  }
  for (const arr of byDepth.values()) {
    arr.sort((a, b) => a.step_index - b.step_index);
  }

  const positions = new Map<string, { col: number; row: number }>();
  let maxCol = 0;
  let maxRow = 0;
  for (const [d, arr] of byDepth) {
    if (d > maxCol) maxCol = d;
    for (let i = 0; i < arr.length; i++) {
      positions.set(arr[i].id, { col: d, row: i });
      if (i > maxRow) maxRow = i;
    }
  }
  return { positions, maxCol, maxRow };
}

export function treeToReactFlow(tree: Tree): LayoutResult {
  // ---- Partition nodes by run_id. For a plain /tree response every node
  // lives in tree.run_id (single-run layout). For ?include_descendants=true
  // each node already carries run_id and multiple runs may coexist.
  const nodesByRun = new Map<string, ChronosNode[]>();
  for (const n of tree.nodes) {
    const arr = nodesByRun.get(n.run_id) ?? [];
    arr.push(n);
    nodesByRun.set(n.run_id, arr);
  }

  // Ordered list of runs: prefer server-provided DFS order, else fall back
  // to root-first insertion order.
  const runOrder: string[] =
    tree.descendant_run_ids && tree.descendant_run_ids.length > 0
      ? tree.descendant_run_ids.filter((r) => nodesByRun.has(r))
      : Array.from(nodesByRun.keys());
  // Guarantee root is first if it has nodes but wasn't in descendant list
  // (e.g. server bug or plain /tree with single run).
  if (!runOrder.includes(tree.run_id) && nodesByRun.has(tree.run_id)) {
    runOrder.unshift(tree.run_id);
  }

  // ---- Step: placeholders for fork edges whose child run has no nodes yet.
  const placeholders: Placeholder[] = [];
  for (const e of tree.edges) {
    if (e.kind === "fork" && e.to === null) {
      // Find which run this fork originates from (the source node's run_id).
      const src = tree.nodes.find((n) => n.id === e.from);
      placeholders.push({
        id: `fork-placeholder-${e.fork_id}`,
        label: "unresolved branch",
        fork_id: e.fork_id,
        child_run_id: e.child_run_id,
        parentRunId: src?.run_id ?? tree.run_id,
      });
    }
  }

  // ---- Layout each run and accumulate lane rects.
  const rfNodes: RFNode[] = [];
  const rfEdges: Edge[] = [];
  const lanes: LaneInfo[] = [];

  let laneTop = 0;
  const runToLaneTop = new Map<string, number>();
  const runToMaxCol = new Map<string, number>();

  for (const runId of runOrder) {
    const nodes = nodesByRun.get(runId) ?? [];
    const { positions, maxCol, maxRow } = layoutSingleRun(nodes, tree.edges);

    // Count placeholders attached to this run for extra row space.
    const lanePlaceholders = placeholders.filter((p) => p.parentRunId === runId);
    const laneMaxRow = Math.max(maxRow, lanePlaceholders.length - 1);
    const laneHeight =
      LANE_HEADER_HEIGHT +
      LANE_PADDING_TOP +
      (laneMaxRow + 1) * NODE_HEIGHT +
      laneMaxRow * V_GAP;
    const laneWidth = (maxCol + 1) * NODE_WIDTH + maxCol * H_GAP;

    const summary = tree.run_summaries?.[runId];
    lanes.push({
      runId,
      y: laneTop,
      height: laneHeight,
      width: laneWidth,
      label: summary?.task_description ?? runId,
      adapter: summary?.adapter ?? "",
      status: summary?.status ?? "",
    });
    runToLaneTop.set(runId, laneTop);
    runToMaxCol.set(runId, maxCol);

    // Emit RFNodes for real nodes in this lane.
    for (const n of nodes) {
      const pos = positions.get(n.id)!;
      rfNodes.push({
        id: n.id,
        type: "chronos",
        position: {
          x: pos.col * (NODE_WIDTH + H_GAP),
          y: laneTop + LANE_HEADER_HEIGHT + LANE_PADDING_TOP + pos.row * (NODE_HEIGHT + V_GAP),
        },
        data: { node: n, runId },
      });
    }

    // Emit placeholder nodes for this run's unresolved forks.
    lanePlaceholders.forEach((p, idx) => {
      const parent = tree.nodes.find((n) => {
        const fe = tree.edges.find(
          (e) => e.kind === "fork" && e.fork_id === p.fork_id,
        );
        return fe && fe.from === n.id;
      });
      const parentCol = parent ? positions.get(parent.id)?.col ?? 0 : 0;
      const placeCol = parentCol + 1;
      rfNodes.push({
        id: p.id,
        type: "placeholder",
        position: {
          x: placeCol * (NODE_WIDTH + H_GAP),
          y:
            laneTop +
            LANE_HEADER_HEIGHT +
            LANE_PADDING_TOP +
            (laneMaxRow + idx) * (NODE_HEIGHT + V_GAP),
        },
        data: { label: p.label, fork_id: p.fork_id, child_run_id: p.child_run_id },
      });
    });

    laneTop += laneHeight + LANE_GAP;
  }

  // ---- Edges: sequential within a run; fork crossing lanes.
  for (const e of tree.edges) {
    if (e.kind === "sequential") {
      rfEdges.push({
        id: `seq-${e.from}-${e.to}`,
        source: e.from,
        target: e.to,
        type: "smoothstep",
        style: { stroke: "var(--chr-accent)", strokeWidth: 2 },
        markerEnd: { type: "arrowclosed" as const, color: "#58a6ff", width: 18, height: 18 },
      });
    } else {
      const target = e.to ?? `fork-placeholder-${e.fork_id}`;
      rfEdges.push({
        id: `fork-${e.fork_id}`,
        source: e.from,
        target,
        type: "smoothstep",
        animated: true,
        style: {
          stroke: "var(--chr-purple)",
          strokeWidth: 2.2,
          strokeDasharray: "6 4",
        },
        markerEnd: { type: "arrowclosed" as const, color: "#a371f7", width: 18, height: 18 },
        label: "fork",
        labelStyle: { fill: "var(--chr-purple)", fontSize: 11, fontWeight: 600 },
        labelBgStyle: { fill: "var(--chr-bg-elev)" },
        data: { childRunId: e.child_run_id },
      });
    }
  }

  return { rfNodes, rfEdges, lanes };
}
