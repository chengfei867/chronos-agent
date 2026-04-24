import { useEffect, useState, useCallback } from "react";
import { RunList } from "./RunList";
import { TreeView } from "./TreeView";

// Minimal hash-based router. Two routes:
//   #/               — run list
//   #/runs/<run_id>  — reasoning tree for that run
//
// Why hash routing instead of history API: the FastAPI server mounts this
// SPA under /app and doesn't do HTML5-history fallback for client-side
// routes. Hash routing keeps everything client-only with no server config.

type Route = { name: "list" } | { name: "run"; runId: string };

function parseHash(hash: string): Route {
  const stripped = hash.replace(/^#/, "").replace(/^\//, "");
  if (stripped === "" || stripped === "/") return { name: "list" };
  const m = stripped.match(/^runs\/([^/]+)$/);
  if (m) return { name: "run", runId: decodeURIComponent(m[1]) };
  return { name: "list" };
}

export function App() {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));

  useEffect(() => {
    const onHash = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const openRun = useCallback((runId: string) => {
    window.location.hash = `#/runs/${encodeURIComponent(runId)}`;
  }, []);

  const goList = useCallback(() => {
    window.location.hash = "#/";
  }, []);

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>⏱ Chronos Viewer</h1>
        {route.name === "run" ? (
          <>
            <button onClick={goList} title="Back to run list">
              ← Runs
            </button>
            <span className="crumb">run · {route.runId.slice(0, 12)}…</span>
          </>
        ) : null}
        <div className="spacer" />
        <a href="/" title="Back to the landing page">
          / landing
        </a>
        <a href="/docs" target="_blank" rel="noreferrer">
          /docs
        </a>
      </header>
      <main className="app-body">
        {route.name === "list" ? (
          <RunList onOpenRun={openRun} />
        ) : (
          <TreeView runId={route.runId} />
        )}
      </main>
    </div>
  );
}
