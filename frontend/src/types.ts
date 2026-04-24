// Type definitions mirroring the FastAPI contract from
// src/chronos/api/server.py. When the server's pydantic models change, these
// need to change in lockstep — but the shape is deliberately small and stable
// (see ADR-014 and the R34-A neutral-tree decision in docs/CONTEXT.md §5).
//
// Source of truth: the pydantic models in src/chronos/core/models.py.
// `_run_to_dict` / `_node_to_dict` / `_fork_to_dict` use `model_dump(mode="json")`
// so field names and nullability here MUST match the python side exactly.

export type NodeKind = "llm" | "tool" | "fn" | "router" | "fork" | "end";

export type RunStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "forked";

export interface Usage {
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
}

export interface Node {
  id: string;
  run_id: string;
  step_index: number;
  node_name: string;
  kind: NodeKind;
  parent_node_id: string | null;
  started_at: string;
  ended_at: string | null;
  state_after: Record<string, unknown>;
  model_name: string | null;
  usage: Usage | null;
  cost_usd_cents: number | null;
  tool_name: string | null;
  tool_input: Record<string, unknown> | null;
  tool_output: Record<string, unknown> | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
}

export interface Run {
  id: string;
  adapter: string;
  adapter_thread_id: string;
  status: RunStatus;
  started_at: string;
  ended_at: string | null;
  task_description: string | null;
  initial_state: Record<string, unknown>;
  final_state: Record<string, unknown> | null;
  tags: string[];
  metadata: Record<string, unknown>;
}

export interface Fork {
  id: string;
  parent_run_id: string;
  parent_node_id: string;
  child_run_id: string;
  edited_fields: Record<string, unknown>;
  created_at: string;
}

export type TreeEdge =
  | {
      from: string;
      to: string;
      kind: "sequential";
    }
  | {
      from: string;
      to: string | null;
      kind: "fork";
      fork_id: string;
      child_run_id: string;
      edited_fields: Record<string, unknown>;
    };

export interface Tree {
  run_id: string;
  nodes: Node[];
  edges: TreeEdge[];
  child_runs: Fork[];
  /** Only present on include_descendants=true responses. Root run first, then
   * DFS-ordered descendants. */
  descendant_run_ids?: string[];
  /** Only present on include_descendants=true responses. Keyed by run_id. */
  run_summaries?: Record<string, RunSummary>;
}

export interface RunSummary {
  id: string;
  adapter: string;
  status: RunStatus;
  task_description: string | null;
  started_at: string;
}

// ---------------------------------------------------------------------------
// Diff / compare shapes — mirror chronos.core.diff (ADR-006) +
// chronos.api.server /runs/compare wrapper. See src/chronos/core/diff.py.
// ---------------------------------------------------------------------------

export type DiffTag = "equal" | "changed" | "added" | "removed";

export interface DiffStateDiff {
  added_keys: string[];
  removed_keys: string[];
  /** changed_keys[key] = {a: <value in run A>, b: <value in run B>} */
  changed_keys: Record<string, { a: unknown; b: unknown }>;
}

export interface DiffNodeBrief {
  id: string;
  run_id: string;
  step_index: number;
  node_name: string;
  kind: NodeKind;
  state_after: Record<string, unknown>;
}

export interface DiffEntry {
  tag: DiffTag;
  node_name: string;
  a: DiffNodeBrief | null;
  b: DiffNodeBrief | null;
  state_diff: DiffStateDiff | null;
}

export interface DiffRunBrief {
  id: string;
  adapter: string;
  status: RunStatus;
  task_description: string | null;
}

export interface DiffForkInfo {
  id: string;
  parent_run_id: string;
  parent_node_id: string;
  parent_node_name: string | null;
  edited_fields: Record<string, unknown>;
  reason: string;
}

export interface DiffReport {
  run_a: DiffRunBrief;
  run_b: DiffRunBrief;
  fork_of: DiffForkInfo | null;
  restricted_to_downstream: boolean;
  entries: DiffEntry[];
  summary: { equal: number; changed: number; added: number; removed: number };
}

export interface CompareResponse {
  diff: DiffReport;
  tree_a: Tree;
  tree_b: Tree;
}

export interface RunsResponse {
  runs: Run[];
  count: number;
}
