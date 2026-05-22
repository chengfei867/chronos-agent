// R95 / Phase 5 Arc C slice 4 — fork-tree projection helper.
//
// Mirrors the Python reference in tests/spikes/spike18_fork_tree_replay.py;
// keeping both in lockstep catches projection drift via spike re-run.
//
// One-way import contract (per format/registry.ts convention): this
// module imports ONLY from `../types`. It is React-free, framework-free,
// and trivially testable from `frontend/scripts/r95-slice4-smoke.mjs`.
//
// Spike 18 invariants validated:
//   A1: fork-tree round-trip via assemble_tree_with_descendants
//   A2: projection is deterministic (same input → identical output) and
//       respects depth = parent.depth + 1
//   A3: ≤16ms / ≤16KB JSON for a 50-node / 6-run worst-case fork tree

import type { Tree } from "../types";

/** A single node in the projected fork tree. Depth-first ordered. */
export interface ForkTreeNode {
  /** Run id of this node (== a row in `Tree.run_summaries`). */
  run_id: string;
  /** Parent run id; null only for the root. */
  parent_run_id: string | null;
  /** 0 for root; child.depth = parent.depth + 1. */
  depth: number;
  /**
   * step_index in the parent run at which this child branched. null for
   * root and for orphans whose parent_node_id can't be resolved (rare;
   * defensive against bulk imports).
   */
  branch_at_step: number | null;
  /** len(nodes) for this run within the descendant tree. */
  step_count: number;
  /** Adapter string from run_summaries (empty string if missing). */
  adapter: string;
  /** Optional task description from run_summaries. */
  task_description: string | null;
}

/**
 * Project a `Tree` (returned by `fetchTree(rid, includeDescendants=true)`)
 * into a deterministic depth-first ordered list of `ForkTreeNode`
 * records.
 *
 * Stable ordering: children of a parent are visited in
 * `(branch_at_step, child_run_id)` order so the rendered fork timeline
 * is reproducible across reloads.
 *
 * Defensive: orphaned descendants (parent_run_id present in fork edges
 * but parent run missing from the tree) are appended at depth 0 — never
 * dropped, never crash. Mirrors the Python reference exactly.
 */
export function projectForkTree(tree: Tree): ForkTreeNode[] {
  // Group nodes by run, with stable per-run step_index ordering.
  const nodesByRun = new Map<string, Tree["nodes"]>();
  for (const n of tree.nodes) {
    const arr = nodesByRun.get(n.run_id) ?? [];
    arr.push(n);
    nodesByRun.set(n.run_id, arr);
  }
  for (const arr of nodesByRun.values()) {
    arr.sort((a, b) => a.step_index - b.step_index);
  }

  const summaries = tree.run_summaries ?? {};
  const forks = tree.child_runs ?? [];

  // Build parent_by_child + branch_by_child lookups.
  const parentByChild = new Map<string, string>();
  const branchByChild = new Map<string, number>();
  for (const fork of forks) {
    parentByChild.set(fork.child_run_id, fork.parent_run_id);
    const parentNodes = nodesByRun.get(fork.parent_run_id) ?? [];
    for (const pn of parentNodes) {
      if (pn.id === fork.parent_node_id) {
        branchByChild.set(fork.child_run_id, pn.step_index);
        break;
      }
    }
  }

  // Build children_by_parent with stable (branch_at_step, child_run_id) ordering.
  const childrenByParent = new Map<string, string[]>();
  for (const fork of forks) {
    const arr = childrenByParent.get(fork.parent_run_id) ?? [];
    arr.push(fork.child_run_id);
    childrenByParent.set(fork.parent_run_id, arr);
  }
  for (const kids of childrenByParent.values()) {
    kids.sort((a, b) => {
      const ba = branchByChild.get(a) ?? -1;
      const bb = branchByChild.get(b) ?? -1;
      if (ba !== bb) return ba - bb;
      return a < b ? -1 : a > b ? 1 : 0;
    });
  }

  const summaryFor = (rid: string): { adapter: string; task_description: string | null } => {
    const s = summaries[rid] as
      | { adapter?: string; task_description?: string | null }
      | undefined;
    return {
      adapter: s?.adapter ?? "",
      task_description: s?.task_description ?? null,
    };
  };

  const stepCount = (rid: string): number => (nodesByRun.get(rid) ?? []).length;

  const out: ForkTreeNode[] = [];
  const visited = new Set<string>();

  const walk = (rid: string, depth: number): void => {
    if (visited.has(rid)) return;
    visited.add(rid);
    const s = summaryFor(rid);
    out.push({
      run_id: rid,
      parent_run_id: parentByChild.get(rid) ?? null,
      depth,
      branch_at_step: branchByChild.get(rid) ?? null,
      step_count: stepCount(rid),
      adapter: s.adapter,
      task_description: s.task_description,
    });
    const kids = childrenByParent.get(rid) ?? [];
    for (const cid of kids) {
      walk(cid, depth + 1);
    }
  };

  walk(tree.run_id, 0);

  // Defensive: append any orphaned descendants at depth 0 so they're at
  // least surfaced in the UI rather than silently dropped.
  for (const rid of tree.descendant_run_ids ?? []) {
    if (visited.has(rid)) continue;
    const s = summaryFor(rid);
    out.push({
      run_id: rid,
      parent_run_id: parentByChild.get(rid) ?? null,
      depth: 0,
      branch_at_step: branchByChild.get(rid) ?? null,
      step_count: stepCount(rid),
      adapter: s.adapter,
      task_description: s.task_description,
    });
  }

  return out;
}
