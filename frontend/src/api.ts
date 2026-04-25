// Thin fetch wrapper targeting the Chronos FastAPI server.
//
// Design notes:
// - Base URL defaults to "" (same origin) because the production deployment
//   mounts this bundle under /app/ on the same FastAPI app that serves /runs.
//   A developer running `npm run dev` gets vite.config.ts's proxy routing.
// - Errors are thrown as Error with the HTTP status prefixed, so call sites
//   can pattern-match on `e.message.startsWith("404")` without reaching for a
//   custom error class hierarchy. Cheap and works for a read-only viewer.
// - No retry, no cache, no timeout. Single-user local tool — if the server
//   is down, the user sees the error and fixes it themselves.

import type {
  Tree,
  RunsResponse,
  Run,
  Node,
  Fork,
  CompareResponse,
} from "./types";

const BASE = ""; // same-origin

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      // body wasn't JSON — fall through with statusText
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return (await res.json()) as T;
}

export async function fetchRuns(limit = 100): Promise<RunsResponse> {
  return getJSON<RunsResponse>(`/runs?limit=${limit}`);
}

export async function fetchRun(
  runId: string,
): Promise<{ run: Run; nodes: Node[] }> {
  return getJSON<{ run: Run; nodes: Node[] }>(`/runs/${encodeURIComponent(runId)}`);
}

export async function fetchTree(
  runId: string,
  includeDescendants: boolean = false,
): Promise<Tree> {
  const suffix = includeDescendants ? "?include_descendants=true" : "";
  return getJSON<Tree>(`/runs/${encodeURIComponent(runId)}/tree${suffix}`);
}

export async function fetchForks(
  runId: string,
): Promise<{ forks: Fork[]; count: number }> {
  return getJSON<{ forks: Fork[]; count: number }>(
    `/runs/${encodeURIComponent(runId)}/forks`,
  );
}

export async function fetchCompare(
  runAId: string,
  runBId: string,
  restrictToDownstream: boolean = true,
): Promise<CompareResponse> {
  const params = new URLSearchParams({
    a: runAId,
    b: runBId,
    restrict_to_downstream: String(restrictToDownstream),
  });
  return getJSON<CompareResponse>(`/runs/compare?${params.toString()}`);
}

// R46-A: fork plan preview. Returns the ForkPlan artifact (per ADR-013,
// Chronos only *plans*; the user runs `chronos fork apply` locally) plus
// a downstream side-effects summary for the "💥 This fork re-runs N
// dangerous nodes" warning block.
export interface ForkPlanPreviewResponse {
  plan: Record<string, unknown>;
  effects_summary: {
    total: number;
    dangerous_count: number;
    tag_counts: Record<string, number>;
    dangerous_samples: Array<[number, string, string[]]>;
  };
}

export async function fetchForkPlanPreview(
  runId: string,
  nodeId: string,
): Promise<ForkPlanPreviewResponse> {
  return getJSON<ForkPlanPreviewResponse>(
    `/runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}/fork-plan`,
  );
}
