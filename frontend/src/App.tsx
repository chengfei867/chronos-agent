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
import OnboardingTour from "./components/OnboardingTour";

type Route =
  | { name: "landing" }
  | { name: "runs" }
  | { name: "tree"; runId: string }
  | { name: "diff"; runAId: string; runBId: string };

function parseHash(): Route {
  const h = window.location.hash.replace(/^#/, "");
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
  const m = h.match(/^\/runs\/([^/]+)$/);
  if (m) return { name: "tree", runId: decodeURIComponent(m[1]) };
  return { name: "runs" };
}

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
