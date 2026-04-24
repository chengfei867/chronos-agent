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

import type { Tree, RunsResponse, Run, Node, Fork } from "./types";

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

export async function fetchTree(runId: string): Promise<Tree> {
  return getJSON<Tree>(`/runs/${encodeURIComponent(runId)}/tree`);
}

export async function fetchForks(
  runId: string,
): Promise<{ forks: Fork[]; count: number }> {
  return getJSON<{ forks: Fork[]; count: number }>(
    `/runs/${encodeURIComponent(runId)}/forks`,
  );
}
