// Transforms a neutral-tree response from GET /runs/{id}/tree into the
// { nodes, edges } pair that ReactFlow expects, plus a deterministic layout.
//
// Design notes (R34-C → R37 update):
// - We do NOT ship dagre/elkjs for layout — those are ~80KB gzipped each and
//   this is a local-dev viewer, not a consumer app. A hand-rolled depth-by-
//   lane layered layout gives good-enough positions for trees up to ~30
//   nodes (which is 99% of local dev cases).
// - Fork edges point to the first node of a child run ("fork" kind). When
//   that child has no nodes yet (still-running fork), the edge target is
//   null and we render a placeholder node labeled "unresolved branch" — so
//   the user can see the branch exists even before the child completes.
// - R37 swimlanes: each distinct agent_id (from tree.lanes, sourced from
//   node.metadata.agent_id) gets a horizontal lane. X axis = depth (topo
//   distance from an agent-less root), Y axis = lane index. Nodes with the
//   same agent_id stack into the same horizontal band. Single-agent runs
//   (agent_id="main" for linear/langgraph, or just one lane for trivial
//   AutoGen runs) collapse to a single row — identical to pre-R37 visual.
// - Layout also returns `laneBands`: { agent_id, y_top, y_bottom, x_max }
//   so TreeView can paint lane backgrounds + lane headers behind the nodes
//   without re-computing geometry.

import type { Node as ChronosNode, Tree, TreeEdge } from "./types";
import type { Edge, Node as RFNode } from "@xyflow/react";

export const NODE_WIDTH = 200;
export const NODE_HEIGHT = 70;
export const H_GAP = 80; // horizontal gap between depth layers
export const V_GAP = 30; // vertical gap between siblings inside a lane
export const LANE_PADDING_TOP = 40; // space above first node in a lane (for lane header)
export const LANE_PADDING_BOTTOM = 20; // space below last node in a lane
export const LANE_GAP = 40; // vertical gap between two adjacent lanes

export interface LaneBand {
  agent_id: string;
  laneIndex: number;
  y_top: number;
  y_bottom: number;
  x_max: number;
  node_count: number;
}

export interface LayoutResult {
  rfNodes: RFNode[];
  rfEdges: Edge[];
  laneBands: LaneBand[];
  totalWidth: number;
  totalHeight: number;
}

interface Placeholder {
  id: string;
  label: string;
  fork_id: string;
  child_run_id: string;
}

function agentIdOf(n: ChronosNode): string {
  const a = n.metadata?.["agent_id"];
  return typeof a === "string" && a.length > 0 ? a : "main";
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

  // ---- Step 3: depth per node (distance from a seq-root).
  const depthCache = new Map<string, number>();
  function depth(nodeId: string): number {
    const cached = depthCache.get(nodeId);
    if (cached !== undefined) return cached;
    const parent = seqParents.get(nodeId);
    const d = parent === undefined ? 0 : depth(parent) + 1;
    depthCache.set(nodeId, d);
    return d;
  }

  // ---- Step 4: lane index assignment.
  // Prefer the order from tree.lanes (server-side first-appearance order);
  // fall back to harvesting unique agent_ids from nodes if the server is
  // somehow older and omitted lanes (defensive — new contract guarantees it).
  const laneOrder: string[] =
    tree.lanes && tree.lanes.length > 0
      ? tree.lanes.map((l) => l.agent_id)
      : Array.from(new Set(tree.nodes.map(agentIdOf)));
  const laneIndexFor = new Map<string, number>();
  laneOrder.forEach((agent, idx) => laneIndexFor.set(agent, idx));

  // ---- Step 5: within each lane, how many nodes at each depth? We stack
  // collisions vertically inside the lane band.
  const laneDepthCounts = new Map<string, number>(); // key = `${lane}:${depth}`
  const intraLanePositions = new Map<string, number>(); // nodeId → stackIndex within (lane, depth)
  const sortedNodes = [...tree.nodes].sort((a, b) => a.step_index - b.step_index);
  for (const n of sortedNodes) {
    const lane = agentIdOf(n);
    const d = depth(n.id);
    const key = `${lane}:${d}`;
    const cur = laneDepthCounts.get(key) ?? 0;
    intraLanePositions.set(n.id, cur);
    laneDepthCounts.set(key, cur + 1);
  }

  // ---- Step 6: lane band heights — each lane's height = max stack-count
  // across all depths × (NODE_HEIGHT + V_GAP) + paddings.
  const laneMaxStack = new Map<string, number>();
  for (const [key, count] of laneDepthCounts) {
    const lane = key.split(":")[0];
    laneMaxStack.set(lane, Math.max(laneMaxStack.get(lane) ?? 1, count));
  }
  // Ensure lanes that appear in tree.lanes but have 0 nodes still reserve
  // a minimum band — single-lane runs with 0 collisions still get one row.
  for (const lane of laneOrder) {
    if (!laneMaxStack.has(lane)) laneMaxStack.set(lane, 1);
  }

  // Compute y_top for each lane (cumulative sum).
  const laneYTop = new Map<string, number>();
  const laneYBottom = new Map<string, number>();
  let cursorY = 0;
  for (const lane of laneOrder) {
    const stack = laneMaxStack.get(lane) ?? 1;
    const bandHeight =
      LANE_PADDING_TOP +
      stack * NODE_HEIGHT +
      Math.max(0, stack - 1) * V_GAP +
      LANE_PADDING_BOTTOM;
    laneYTop.set(lane, cursorY);
    laneYBottom.set(lane, cursorY + bandHeight);
    cursorY += bandHeight + LANE_GAP;
  }
  const totalHeight = Math.max(0, cursorY - LANE_GAP);

  // ---- Step 7: place real nodes.
  const forkEdgesByParent = new Map<string, TreeEdge & { kind: "fork" }>();
  for (const e of tree.edges) {
    if (e.kind === "fork") forkEdgesByParent.set(e.from, e);
  }

  const rfNodes: RFNode[] = [];
  const rfEdges: Edge[] = [];
  const laneXMax = new Map<string, number>();

  for (const n of tree.nodes) {
    const lane = agentIdOf(n);
    const d = depth(n.id);
    const stackIdx = intraLanePositions.get(n.id) ?? 0;
    const x = d * (NODE_WIDTH + H_GAP);
    const y =
      (laneYTop.get(lane) ?? 0) +
      LANE_PADDING_TOP +
      stackIdx * (NODE_HEIGHT + V_GAP);
    rfNodes.push({
      id: n.id,
      type: "chronos",
      position: { x, y },
      data: { node: n },
    });
    laneXMax.set(lane, Math.max(laneXMax.get(lane) ?? 0, x + NODE_WIDTH));
  }

  // ---- Step 8: placeholders — belong to parent's lane so a stuck fork shows
  // up next to the producer.
  for (const p of placeholders) {
    let parentId: string | null = null;
    for (const [pid, fe] of forkEdgesByParent) {
      if (fe.fork_id === p.fork_id) {
        parentId = pid;
        break;
      }
    }
    const parentNode = parentId ? nodeById.get(parentId) : undefined;
    const lane = parentNode ? agentIdOf(parentNode) : laneOrder[0] ?? "main";
    const parentDepth = parentId ? depth(parentId) : 0;
    const placeDepth = parentDepth + 1;
    const key = `${lane}:${placeDepth}`;
    const cur = laneDepthCounts.get(key) ?? 0;
    laneDepthCounts.set(key, cur + 1);
    const x = placeDepth * (NODE_WIDTH + H_GAP);
    const y =
      (laneYTop.get(lane) ?? 0) +
      LANE_PADDING_TOP +
      cur * (NODE_HEIGHT + V_GAP);
    rfNodes.push({
      id: p.id,
      type: "placeholder",
      position: { x, y },
      data: { label: p.label, fork_id: p.fork_id, child_run_id: p.child_run_id },
    });
    laneXMax.set(lane, Math.max(laneXMax.get(lane) ?? 0, x + NODE_WIDTH));
  }

  // ---- Step 9: edges. R37 — if source and target agents differ, mark the
  // sequential edge as "cross-lane" so the renderer can style it differently
  // (e.g. for handoffs, tool returns). Fork edges always keep their own look.
  for (const e of tree.edges) {
    if (e.kind === "sequential") {
      const src = nodeById.get(e.from);
      const tgt = nodeById.get(e.to);
      const crossLane = !!src && !!tgt && agentIdOf(src) !== agentIdOf(tgt);
      rfEdges.push({
        id: `seq-${e.from}-${e.to}`,
        source: e.from,
        target: e.to,
        type: "smoothstep",
        style: crossLane
          ? { stroke: "var(--handoff, #e3b341)", strokeWidth: 1.75 }
          : { stroke: "var(--accent)", strokeWidth: 1.5 },
        data: { crossLane },
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

  // ---- Step 10: lane bands for TreeView's background rendering.
  const laneBands: LaneBand[] = laneOrder.map((agent_id, laneIndex) => ({
    agent_id,
    laneIndex,
    y_top: laneYTop.get(agent_id) ?? 0,
    y_bottom: laneYBottom.get(agent_id) ?? 0,
    x_max: laneXMax.get(agent_id) ?? NODE_WIDTH,
    node_count:
      tree.lanes?.find((l) => l.agent_id === agent_id)?.node_count ??
      tree.nodes.filter((n) => agentIdOf(n) === agent_id).length,
  }));

  const totalWidth = Math.max(
    NODE_WIDTH,
    ...laneBands.map((b) => b.x_max),
  );

  return { rfNodes, rfEdges, laneBands, totalWidth, totalHeight };
}
