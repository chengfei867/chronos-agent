// R39-A: run comparison page — side-by-side dual ReactFlow panels driven by
// GET /runs/compare, with the alignment report rendered as a clickable list
// underneath. Clicking a row focuses the corresponding node in BOTH panels.
//
// Visual language (subtle, per user feedback on UI polish):
//  - equal  -> dimmed card
//  - changed -> amber border
//  - added   -> green border (B-only)
//  - removed -> muted gray + reduced opacity (A-only)
// Focus ring uses the existing --chr-accent blue.
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Skeleton,
  Space,
  Switch,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  ReactFlowProvider,
  type Edge,
  type Node as RFNode,
  type NodeMouseHandler,
} from "@xyflow/react";
import { motion } from "framer-motion";
import { ArrowLeft, ArrowLeftRight, GitCompare } from "lucide-react";
import { useTranslation } from "react-i18next";
import { fetchCompare } from "../api";
import type {
  CompareResponse,
  DiffEntry,
  DiffTag,
} from "../types";
import { treeToReactFlow } from "../layout";
import ChronosNodeCard from "../components/nodes/ChronosNodeCard";
import PlaceholderNode from "../components/nodes/PlaceholderNode";
import DiffNodeDetails from "../components/DiffNodeDetails";
import ConceptTip from "../components/ConceptTip";
import Legend from "../components/Legend";

const { Title, Paragraph, Text } = Typography;

const NODE_TYPES = {
  chronos: ChronosNodeCard,
  placeholder: PlaceholderNode,
};

interface DiffViewProps {
  runAId: string;
  runBId: string;
}

/** Build a `nodeId -> DiffTag` map from the diff report.
 *  - 'equal'/'changed' entries tag BOTH sides with the same tag.
 *  - 'added' entries exist only on B (b != null, a == null) — B-side tag.
 *  - 'removed' entries exist only on A (a != null, b == null) — A-side tag.
 */
function buildStatusMaps(entries: DiffEntry[]): {
  a: Map<string, DiffTag>;
  b: Map<string, DiffTag>;
} {
  const aMap = new Map<string, DiffTag>();
  const bMap = new Map<string, DiffTag>();
  for (const e of entries) {
    if (e.a) aMap.set(e.a.id, e.tag);
    if (e.b) bMap.set(e.b.id, e.tag);
  }
  return { a: aMap, b: bMap };
}

/** Paint a DiffTag onto every real ('chronos') RFNode using its id. */
function paintNodes(
  rfNodes: RFNode[],
  statusMap: Map<string, DiffTag>,
  focusedId: string | null,
): RFNode[] {
  return rfNodes.map((n) => {
    if (n.type !== "chronos") return n;
    const tag = statusMap.get(n.id);
    const existing = (n.data ?? {}) as Record<string, unknown>;
    return {
      ...n,
      data: {
        ...existing,
        diffStatus: tag,
        diffFocused: focusedId === n.id,
      },
    };
  });
}

export default function DiffView({ runAId, runBId }: DiffViewProps) {
  const { t } = useTranslation();
  const [data, setData] = useState<CompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restrict, setRestrict] = useState(true);
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<DiffEntry | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    setFocusedNodeId(null);
    (async () => {
      try {
        const res = await fetchCompare(runAId, runBId, restrict);
        // Fork relationship is directional: core.diff only recognises
        // "A is a fork of B". If the user selected runs in the opposite
        // order, transparently swap and retry so the UI shows the parent/
        // child relationship + downstream-only toggle becomes usable.
        if (!res.diff.fork_of) {
          const swapped = await fetchCompare(runBId, runAId, restrict);
          if (swapped.diff.fork_of) {
            if (cancelled) return;
            // Update the URL so a Swap A/B click is the inverse operation,
            // but don't trigger a re-fetch (useEffect watches runAId/runBId
            // which come from the hash — replaceState skips that signal).
            window.history.replaceState(
              null,
              "",
              `#/runs/${runBId}/diff/${runAId}`,
            );
            setData(swapped);
            return;
          }
        }
        if (!cancelled) setData(res);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runAId, runBId, restrict]);

  const layoutA = useMemo(() => {
    if (!data) return null;
    return treeToReactFlow(data.tree_a);
  }, [data]);
  const layoutB = useMemo(() => {
    if (!data) return null;
    return treeToReactFlow(data.tree_b);
  }, [data]);

  const statusMaps = useMemo(
    () => (data ? buildStatusMaps(data.diff.entries) : null),
    [data],
  );

  const paintedA = useMemo<{ nodes: RFNode[]; edges: Edge[] } | null>(() => {
    if (!layoutA || !statusMaps) return null;
    return {
      nodes: paintNodes(layoutA.rfNodes, statusMaps.a, focusedNodeId),
      edges: layoutA.rfEdges,
    };
  }, [layoutA, statusMaps, focusedNodeId]);
  const paintedB = useMemo<{ nodes: RFNode[]; edges: Edge[] } | null>(() => {
    if (!layoutB || !statusMaps) return null;
    return {
      nodes: paintNodes(layoutB.rfNodes, statusMaps.b, focusedNodeId),
      edges: layoutB.rfEdges,
    };
  }, [layoutB, statusMaps, focusedNodeId]);

  const openEntry = useCallback((entry: DiffEntry) => {
    setSelectedEntry(entry);
    setDrawerOpen(true);
    // Focus both sides simultaneously when possible.
    const focusId = entry.a?.id ?? entry.b?.id ?? null;
    setFocusedNodeId(focusId);
  }, []);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_ev, node) => {
      if (node.type !== "chronos") return;
      if (!data) return;
      // Find the entry that contains this node id.
      const entry = data.diff.entries.find(
        (e) => e.a?.id === node.id || e.b?.id === node.id,
      );
      if (entry) openEntry(entry);
    },
    [data, openEntry],
  );

  const onSwap = () => {
    window.location.hash = `#/runs/${encodeURIComponent(runBId)}/diff/${encodeURIComponent(runAId)}`;
  };
  const onBack = () => {
    window.location.hash = "#/";
  };

  // -------------------------------- render
  if (error) {
    return (
      <div className="chr-page">
        <Alert
          type="error"
          showIcon
          message={t("errors.apiFailed")}
          description={error}
          action={
            <Button size="small" onClick={onBack}>
              {t("diff.backToList")}
            </Button>
          }
        />
      </div>
    );
  }

  if (!data || !paintedA || !paintedB) {
    return (
      <div className="chr-page">
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    );
  }

  const { diff } = data;
  const { summary, fork_of, entries } = diff;

  return (
    <motion.div
      className="chr-diff-page"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      {/* ---------- Header ---------- */}
      <div className="chr-diff-head">
        <Space align="center" style={{ width: "100%", justifyContent: "space-between" }} wrap>
          <Space align="center" size={12}>
            <Button
              type="text"
              size="small"
              icon={<ArrowLeft size={14} />}
              onClick={onBack}
            >
              {t("diff.backToList")}
            </Button>
            <Title level={4} style={{ margin: 0 }}>
              <GitCompare size={18} style={{ marginRight: 8, verticalAlign: -3 }} />
              {t("diff.title")}
            </Title>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("diff.subtitle")} — <ConceptTip concept="run" asIcon />
            </Text>
          </Space>
          <Space size={10}>
            <Tooltip title={restrict ? t("diff.restrictOnHint") : t("diff.restrictOffHint")}>
              <Space size={6}>
                <Switch
                  size="small"
                  checked={restrict}
                  onChange={setRestrict}
                  disabled={!fork_of}
                />
                <Text style={{ fontSize: 12 }}>{t("diff.restrictToggle")}</Text>
              </Space>
            </Tooltip>
            <Button
              size="small"
              icon={<ArrowLeftRight size={14} />}
              onClick={onSwap}
            >
              {t("diff.swap")}
            </Button>
          </Space>
        </Space>

        {/* Fork context banner */}
        <div style={{ marginTop: 8 }}>
          {fork_of ? (
            <Alert
              type="info"
              showIcon
              message={t("diff.forkBanner", {
                forkPoint: fork_of.parent_node_name ?? fork_of.parent_node_id.slice(0, 8),
              })}
            />
          ) : (
            <Alert type="warning" showIcon message={t("diff.noForkBanner")} />
          )}
        </div>

        {/* Summary chips */}
        <div className="chr-diff-summary">
          <span className="chr-diff-summary-chip is-equal">
            <span className="chr-dot" /> {t("diff.summary.equal")}: <strong>{summary.equal}</strong>
          </span>
          <span className="chr-diff-summary-chip is-changed">
            <span className="chr-dot" /> {t("diff.summary.changed")}: <strong>{summary.changed}</strong>
          </span>
          <span className="chr-diff-summary-chip is-added">
            <span className="chr-dot" /> {t("diff.summary.added")}: <strong>{summary.added}</strong>
          </span>
          <span className="chr-diff-summary-chip is-removed">
            <span className="chr-dot" /> {t("diff.summary.removed")}: <strong>{summary.removed}</strong>
          </span>
          <Tag color="geekblue" bordered={false}>
            A: {diff.run_a.id.slice(0, 8)} · {diff.run_a.adapter}
          </Tag>
          <Tag color="purple" bordered={false}>
            B: {diff.run_b.id.slice(0, 8)} · {diff.run_b.adapter}
          </Tag>
        </div>
      </div>

      {/* ---------- Body: two ReactFlow panels + alignment list ---------- */}
      <div className="chr-diff-body">
        <div className="chr-diff-pane">
          <span className="chr-diff-pane-label is-a">{t("diff.runSide.a")}</span>
          <ReactFlowProvider>
            <ReactFlow
              nodes={paintedA.nodes}
              edges={paintedA.edges}
              nodeTypes={NODE_TYPES}
              onNodeClick={onNodeClick}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              proOptions={{ hideAttribution: true }}
              minZoom={0.3}
              maxZoom={2}
              nodesDraggable={false}
            >
              <Background gap={24} color="var(--chr-border)" />
              <Panel position="top-right" style={{ margin: 12, pointerEvents: "none" }}>
                <Legend showDiff />
              </Panel>
              <Controls showInteractive={false} />
              <MiniMap pannable zoomable style={{ background: "var(--chr-bg-elev)" }} />
            </ReactFlow>
          </ReactFlowProvider>
        </div>

        <div className="chr-diff-pane">
          <span className="chr-diff-pane-label is-b">{t("diff.runSide.b")}</span>
          <ReactFlowProvider>
            <ReactFlow
              nodes={paintedB.nodes}
              edges={paintedB.edges}
              nodeTypes={NODE_TYPES}
              onNodeClick={onNodeClick}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              proOptions={{ hideAttribution: true }}
              minZoom={0.3}
              maxZoom={2}
              nodesDraggable={false}
            >
              <Background gap={24} color="var(--chr-border)" />
              <Controls showInteractive={false} />
              <MiniMap pannable zoomable style={{ background: "var(--chr-bg-elev)" }} />
            </ReactFlow>
          </ReactFlowProvider>
        </div>

        {/* Alignment list, spans both columns */}
        <div className="chr-diff-entries">
          <Paragraph style={{ margin: "0 0 6px", fontSize: 12, color: "var(--chr-text-secondary)" }}>
            <strong>{t("diff.entries.title")}</strong> — {t("diff.entries.hint")}
          </Paragraph>
          {entries.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("diff.entries.emptyAll")}
            />
          ) : (
            entries.map((e, idx) => {
              const key = `${idx}-${e.a?.id ?? "null"}-${e.b?.id ?? "null"}`;
              const focused =
                focusedNodeId !== null &&
                (e.a?.id === focusedNodeId || e.b?.id === focusedNodeId);
              return (
                <div
                  key={key}
                  className={`chr-diff-entry-row ${focused ? "is-focused" : ""}`}
                  onClick={() => openEntry(e)}
                >
                  <div>
                    <DiffTagBadge tag={e.tag} />
                  </div>
                  <DiffEntrySide node={e.a} />
                  <DiffEntrySide node={e.b} />
                </div>
              );
            })
          )}
        </div>
      </div>

      <Drawer
        title={t("diff.nodeDetails.title")}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={560}
        destroyOnClose
      >
        {selectedEntry && <DiffNodeDetails entry={selectedEntry} />}
      </Drawer>
    </motion.div>
  );
}

function DiffTagBadge({ tag }: { tag: DiffTag }) {
  const { t } = useTranslation();
  const colorMap: Record<DiffTag, string> = {
    equal: "default",
    changed: "gold",
    added: "green",
    removed: "volcano",
  };
  return (
    <Tag color={colorMap[tag]} bordered={false} style={{ fontSize: 11 }}>
      {t(`diff.entries.tag${tag.charAt(0).toUpperCase() + tag.slice(1)}`, { defaultValue: tag })}
    </Tag>
  );
}

function DiffEntrySide({ node }: { node: { node_name: string; step_index: number } | null }) {
  if (!node) {
    return <span className="chr-diff-entry-side is-empty">—</span>;
  }
  return (
    <span className="chr-diff-entry-side" title={node.node_name}>
      #{node.step_index} {node.node_name}
    </span>
  );
}
