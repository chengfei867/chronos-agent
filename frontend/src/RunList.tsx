import { useEffect, useState } from "react";
import type { Run } from "./types";
import { fetchRuns } from "./api";

interface Props {
  onOpenRun: (runId: string) => void;
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const delta = (now - then) / 1000;
  if (!Number.isFinite(delta) || delta < 0) return iso;
  if (delta < 60) return `${Math.floor(delta)}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

export function RunList({ onOpenRun }: Props) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchRuns(200)
      .then((r) => {
        if (!cancelled) setRuns(r.runs);
      })
      .catch((e: Error) => {
        if (!cancelled) setErr(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (err) {
    return <div className="banner err">Failed to load runs: {err}</div>;
  }
  if (runs === null) {
    return <div className="banner loading">Loading runs…</div>;
  }
  if (runs.length === 0) {
    return (
      <div className="run-list">
        <h2>No runs yet</h2>
        <div className="empty">
          <p>
            Record your first run, then refresh. Example with the LangGraph
            adapter:
          </p>
          <p>
            <code>chronos agent-run examples/langgraph_smoke.py</code>
          </p>
          <p>
            Or see{" "}
            <a href="/" target="_self">
              the landing page
            </a>{" "}
            for more options.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="run-list">
      <h2>
        Runs <span style={{ color: "var(--fg-muted)", fontWeight: 400 }}>({runs.length})</span>
      </h2>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Adapter</th>
            <th>Status</th>
            <th>Started</th>
            <th>Task</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr
              key={r.id}
              className="clickable"
              onClick={() => onOpenRun(r.id)}
              title="Open reasoning tree"
            >
              <td className="mono">{r.id.slice(0, 8)}…</td>
              <td>{r.adapter}</td>
              <td>
                <span className={`tag status-${r.status}`}>{r.status}</span>
              </td>
              <td>{formatRelative(r.started_at)}</td>
              <td
                className="task-cell"
                title={r.task_description ?? r.adapter_thread_id}
              >
                {r.task_description ?? (
                  <span className="mono" style={{ color: "var(--fg-muted)" }}>
                    {r.adapter_thread_id}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
