// App root — hash routing, shared header/footer, page transitions.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Layout } from "antd";
import { AnimatePresence, motion } from "framer-motion";
import AppHeader from "./components/AppHeader";
import AppFooter from "./components/AppFooter";
import HelpDrawer from "./components/HelpDrawer";
import Landing from "./pages/Landing";
import RunList from "./pages/RunList";
import TreeView from "./pages/TreeView";
import DiffView from "./pages/DiffView";
import Replay from "./pages/Replay";
import ForkTreeView from "./pages/ForkTreeView";
import OnboardingTour from "./components/OnboardingTour";

type Route =
  | { name: "landing" }
  | { name: "runs" }
  | { name: "tree"; runId: string }
  | { name: "replay"; runId: string; initialStep?: number }
  | { name: "forks"; runId: string }
  | { name: "diff"; runAId: string; runBId: string };

// R97 (Phase 5 Arc C slice 5): split path?query so deep-links like
// `#/runs/<id>/replay?step=5` are honoured. URL is the source of truth on
// page load — Replay.tsx passes `initialStep` to usePlayback. Step navigation
// uses history.replaceState to keep the URL in sync without polluting
// browser back/forward history (clicking through 200 steps must NOT add
// 200 entries to session history).
function parseStepParam(query: string): number | undefined {
  if (!query) return undefined;
  // Defensive: URLSearchParams accepts leading "?" or none — tolerate both.
  const params = new URLSearchParams(query.replace(/^\?/, ""));
  const raw = params.get("step");
  if (raw === null) return undefined;
  // Strict integer parse — `Number()` accepts floats / "5e1" / whitespace,
  // which we don't want; require pure digits (optionally signed).
  if (!/^-?\d+$/.test(raw)) return undefined;
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 0) return undefined;
  return n;
}

function parseHash(): Route {
  const raw = window.location.hash.replace(/^#/, "");
  // Split path from query string. Anything after the first "?" is query.
  const qIdx = raw.indexOf("?");
  const h = qIdx >= 0 ? raw.slice(0, qIdx) : raw;
  const query = qIdx >= 0 ? raw.slice(qIdx) : "";

  if (!h || h === "/") return { name: "runs" };
  if (h === "/home") return { name: "landing" };
  // /runs/<a>/diff/<b> must be matched before /runs/<id>
  const diffMatch = h.match(/^\/runs\/([^/]+)\/diff\/([^/]+)$/);
  if (diffMatch) {
    return {
      name: "diff",
      runAId: decodeURIComponent(diffMatch[1]),
      runBId: decodeURIComponent(diffMatch[2]),
    };
  }
  // /runs/<id>/replay must be matched before /runs/<id>
  const replayMatch = h.match(/^\/runs\/([^/]+)\/replay$/);
  if (replayMatch) {
    const route: Route = {
      name: "replay",
      runId: decodeURIComponent(replayMatch[1]),
    };
    const initialStep = parseStepParam(query);
    if (initialStep !== undefined) route.initialStep = initialStep;
    return route;
  }
  // /runs/<id>/forks must be matched before /runs/<id>
  const forksMatch = h.match(/^\/runs\/([^/]+)\/forks$/);
  if (forksMatch) {
    return { name: "forks", runId: decodeURIComponent(forksMatch[1]) };
  }
  const m = h.match(/^\/runs\/([^/]+)$/);
  if (m) return { name: "tree", runId: decodeURIComponent(m[1]) };
  return { name: "runs" };
}

// Exported for r97 smoke harness (parseHash relies on window.location, so
// we expose the pure helper instead).
export { parseStepParam };

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseHash());
  const [helpOpen, setHelpOpen] = useState(false);

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const openHelp = useCallback(() => setHelpOpen(true), []);
  const closeHelp = useCallback(() => setHelpOpen(false), []);

  const page = useMemo(() => {
    switch (route.name) {
      case "landing":
        return <Landing key="landing" openHelp={openHelp} />;
      case "runs":
        return <RunList key="runs" />;
      case "tree":
        return <TreeView key={`tree-${route.runId}`} runId={route.runId} />;
      case "replay":
        return (
          <Replay
            key={`replay-${route.runId}`}
            runId={route.runId}
            initialStep={route.initialStep}
          />
        );
      case "forks":
        return <ForkTreeView key={`forks-${route.runId}`} runId={route.runId} />;
      case "diff":
        return (
          <DiffView
            key={`diff-${route.runAId}-${route.runBId}`}
            runAId={route.runAId}
            runBId={route.runBId}
          />
        );
    }
  }, [route, openHelp]);

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <AppHeader
        currentRoute={route.name}
        onHelpClick={openHelp}
      />
      <Layout.Content className={`chr-content chr-content--${route.name}`}>
        <AnimatePresence mode="wait">
          <motion.div
            key={
              route.name +
              ("runId" in route ? route.runId : "") +
              ("runAId" in route ? `${route.runAId}-${route.runBId}` : "")
            }
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            style={{ height: "100%" }}
          >
            {page}
          </motion.div>
        </AnimatePresence>
      </Layout.Content>
      <AppFooter />
      <HelpDrawer open={helpOpen} onClose={closeHelp} />
      <OnboardingTour onHelpClick={openHelp} />
    </Layout>
  );
}
