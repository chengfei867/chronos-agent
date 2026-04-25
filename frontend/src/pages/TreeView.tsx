// TreeView page — left: run summary | center: ReactFlow reasoning tree |
// right: node details drawer. Top toolbar has the "Play from start" killer.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  ReactFlowProvider,
  useReactFlow,
  useViewport,
  type Node as RFNode,
  type Edge as RFEdge,
} from "@xyflow/react";
import {
  Card,
  Typography,
  Space,
  Tag,
  Button,
  Drawer,
  Tooltip,
  Alert,
  Skeleton,
  Row,
  Col,
  Empty,
  Badge,
  Statistic,
  Switch,
} from "antd";
import {
  Play,
  Pause,
  RotateCcw,
  Maximize2,
  ArrowLeft,
  ArrowRight,
  Info,
  GitFork,
} from "lucide-react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { fetchTree, fetchRun } from "../api";
import type { Run, Tree } from "../types";
import { treeToReactFlow, type LaneInfo } from "../layout";
import ChronosNodeCard from "../components/nodes/ChronosNodeCard";
import PlaceholderNode from "../components/nodes/PlaceholderNode";
import NodeDetails from "../components/NodeDetails";
import Legend from "../components/Legend";
import ConceptTip from "../components/ConceptTip";
import ForkPlanModal from "../components/ForkPlanModal";
import { usePlayback } from "../hooks/usePlayback";

const { Text } = Typography;

const NODE_TYPES = {
  chronos: ChronosNodeCard,
  placeholder: PlaceholderNode,
};

function InnerTree({
  tree,
  run,
  includeDescendants,
  onToggleDescendants,
}: {
  tree: Tree;
  run: Run;
  includeDescendants: boolean;
  onToggleDescendants: (v: boolean) => void;
}) {
  const { t, i18n } = useTranslation();
  const rf = useReactFlow();

  // Nodes in the root run only — used for the "play from start" timeline so
  // the stepper stays focused on the user-selected run even when descendant
  // lanes are visible.
  const rootRunNodes = useMemo(
    () => tree.nodes.filter((n) => n.run_id === run.id),
    [tree.nodes, run.id],
  );

  const orderedNodes = useMemo(
    () => [...rootRunNodes].sort((a, b) => a.step_index - b.step_index),
    [rootRunNodes],
  );

  const playback = usePlayback(orderedNodes.length);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  // R46-A: fork preview modal state. null ⇒ closed. Intentionally separate
  // from selectedId so closing the fork modal doesn't close the node drawer.
  const [forkNodeId, setForkNodeId] = useState<string | null>(null);

  const { rfNodes: baseNodes, rfEdges: baseEdges, lanes } = useMemo(
    () => treeToReactFlow(tree),
    [tree],
  );

  // Overlay: per-node isPlaying / isPlayed / isSelected flags.
  const rfNodes = useMemo<RFNode[]>(() => {
    const currentId =
      playback.index >= 0 && playback.index < orderedNodes.length
        ? orderedNodes[playback.index].id
        : null;
    const playedIds = new Set<string>();
    if (playback.index >= 0) {
      for (let i = 0; i <= playback.index && i < orderedNodes.length; i++) {
        playedIds.add(orderedNodes[i].id);
      }
    }
    return baseNodes.map((n) => ({
      ...n,
      data: {
        ...n.data,
        isPlaying: n.id === currentId,
        isPlayed: playedIds.has(n.id),
        isSelected: n.id === selectedId,
      },
      selected: n.id === selectedId,
    }));
  }, [baseNodes, playback.index, orderedNodes, selectedId]);

  const rfEdges = useMemo<RFEdge[]>(
    () =>
      baseEdges.map((e) => {
        const isSel = e.id === selectedEdgeId;
        if (!selectedEdgeId) return e;
        if (!isSel) {
          return {
            ...e,
            style: { ...e.style, opacity: 0.65 },
          } as RFEdge;
        }
        const isFork = e.data?.kind === "fork";
        const accent = isFork ? "#c678f7" : "#58a6ff";
        const glowRgb = isFork ? "198, 120, 247" : "88, 166, 255";
        return {
          ...e,
          style: {
            ...e.style,
            stroke: accent,
            strokeWidth: 2.6,
            filter: `drop-shadow(0 0 6px rgba(${glowRgb}, 0.55))`,
            opacity: 1,
          },
        } as RFEdge;
      }),
    [baseEdges, selectedEdgeId],
  );

  // Auto-pan to the node that's currently "playing".
  useEffect(() => {
    if (playback.index < 0) return;
    const id = orderedNodes[playback.index]?.id;
    if (!id) return;
    const n = baseNodes.find((x) => x.id === id);
    if (!n) return;
    rf.setCenter(n.position.x + 100, n.position.y + 35, {
      zoom: 1.1,
      duration: 600,
    });
    setSelectedId(id);
  }, [playback.index, orderedNodes, baseNodes, rf]);

  const onNodeClick = useCallback(
    (_evt: React.MouseEvent, node: RFNode) => {
      if (node.type === "placeholder") return;
      setSelectedId(node.id);
      setSelectedEdgeId(null);
    },
    [],
  );

  const onEdgeClick = useCallback(
    (_evt: React.MouseEvent, edge: RFEdge) => {
      setSelectedEdgeId((prev) => (prev === edge.id ? null : edge.id));
      // Click an edge → deselect any node so the right inspector reflects edge state
      setSelectedId(null);
    },
    [],
  );

  const selectedNode = useMemo(
    () => tree.nodes.find((n) => n.id === selectedId) ?? null,
    [tree.nodes, selectedId],
  );
  const forkNode = useMemo(
    () => tree.nodes.find((n) => n.id === forkNodeId) ?? null,
    [tree.nodes, forkNodeId],
  );

  // Stats for the left panel
  const forkCount = useMemo(
    () => tree.edges.filter((e) => e.kind === "fork").length,
    [tree.edges],
  );
  const totalCost = useMemo(
    () =>
      tree.nodes.reduce(
        (sum, n) => sum + (n.cost_usd_cents ?? 0),
        0,
      ),
    [tree.nodes],
  );
  const runsInTreeCount = useMemo(
    () => new Set(tree.nodes.map((n) => n.run_id)).size,
    [tree.nodes],
  );

  const goBack = () => {
    window.location.hash = "#/";
  };

  const fitView = () => {
    rf.fitView({ duration: 400, padding: 0.2 });
  };

  return (
    <div className="chr-tree-wrap">
      {/* Toolbar */}
      <div className="chr-tree-toolbar">
        <Space wrap>
          <Button icon={<ArrowLeft size={14} />} onClick={goBack}>
            {t("common.backToList")}
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            <ConceptTip concept="run" asIcon /> {run.id}
          </Text>
        </Space>
        <Space wrap>
          <ConceptTip concept="step">
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("tree.stepOf", {
                current: Math.max(0, playback.index + 1),
                total: orderedNodes.length,
              })}
            </Text>
          </ConceptTip>
          {playback.playing ? (
            <Button icon={<Pause size={14} />} onClick={playback.pause}>
              {t("tree.pause")}
            </Button>
          ) : (
            <Tooltip title={t("tree.play")}>
              <Button
                type="primary"
                icon={<Play size={14} />}
                onClick={playback.play}
                disabled={orderedNodes.length === 0}
              >
                {t("tree.play")}
              </Button>
            </Tooltip>
          )}
          <Button icon={<RotateCcw size={14} />} onClick={playback.reset}>
            {t("tree.reset")}
          </Button>
          <Button icon={<Maximize2 size={14} />} onClick={fitView}>
            {t("tree.zoomFit")}
          </Button>
          <Tooltip title={t("tree.showDescendantsTip")}>
            <div
              className="chr-descendants-toggle"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "2px 10px",
                border: "1px solid var(--border)",
                borderRadius: 6,
                background: includeDescendants ? "rgba(88,166,255,0.08)" : "transparent",
              }}
            >
              <GitFork
                size={14}
                style={{
                  color: includeDescendants ? "var(--fork)" : "var(--text-dim)",
                }}
              />
              <Text style={{ fontSize: 12 }}>
                {t("tree.showDescendants")}
              </Text>
              <Switch
                size="small"
                checked={includeDescendants}
                onChange={onToggleDescendants}
              />
              {includeDescendants && runsInTreeCount > 1 && (
                <Tag color="purple" style={{ margin: 0, fontSize: 11 }}>
                  {t("tree.runsInTree", { count: runsInTreeCount })}
                </Tag>
              )}
            </div>
          </Tooltip>
        </Space>
      </div>

      {/* Body: left info + canvas */}
      <Row gutter={0} style={{ flex: 1, minHeight: 0 }}>
        <Col flex="280px" className="chr-tree-side">
          <Card size="small" title={t("tree.runInfo")} bordered={false}>
            <Space direction="vertical" size={8} style={{ width: "100%" }}>
              <div>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {t("runs.columns.status")}
                </Text>
                <div>
                  <Badge
                    status={
                      run.status === "completed"
                        ? "success"
                        : run.status === "failed"
                        ? "error"
                        : run.status === "running"
                        ? "processing"
                        : "default"
                    }
                    text={t(`status.${run.status}`, { defaultValue: run.status })}
                  />
                </div>
              </div>
              <div>
                <ConceptTip concept="framework">
                  <Text type="secondary" style={{ fontSize: 11, cursor: "help" }}>
                    {t("runs.columns.adapter")}
                  </Text>
                </ConceptTip>
                <div><Tag color="geekblue">{run.adapter}</Tag></div>
              </div>
              {run.task_description && (
                <div>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {t("runs.columns.task")}
                  </Text>
                  <div>
                    <Text>{run.task_description}</Text>
                  </div>
                </div>
              )}
              <div>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {t("runs.columns.started")}
                </Text>
                <div>
                  <Text style={{ fontSize: 12 }}>
                    {new Date(run.started_at).toLocaleString(i18n.language)}
                  </Text>
                </div>
              </div>
              <Row gutter={[8, 8]} style={{ marginTop: 4 }}>
                <Col span={12}>
                  <Statistic title={t("tree.nodeCount", { count: orderedNodes.length })} value={orderedNodes.length} />
                </Col>
                <Col span={12}>
                  <Statistic title={t("tree.forkCount", { count: forkCount })} value={forkCount} />
                </Col>
                <Col span={24}>
                  <Statistic
                    title={
                      <ConceptTip concept="usage">
                        <span style={{ cursor: "help" }}>
                          {t("nodeDetails.fields.costUsd")}
                        </span>
                      </ConceptTip>
                    }
                    value={totalCost === 0 ? "–" : (totalCost / 100).toFixed(4)}
                    prefix={totalCost > 0 ? "$" : ""}
                  />
                </Col>
              </Row>
              <Alert
                type="info"
                showIcon
                icon={<Info size={14} />}
                message={
                  selectedEdgeId ? t("tree.edgeSelectedHint") : t("tree.clickHint")
                }
                style={{ background: "transparent", padding: 8, fontSize: 12 }}
              />
            </Space>
          </Card>
        </Col>
        <Col flex="auto" className="chr-tree-canvas">
          {orderedNodes.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("tree.emptyTree")}
              style={{ marginTop: 80 }}
            />
          ) : (
            <ReactFlow
              nodes={rfNodes}
              edges={rfEdges}
              nodeTypes={NODE_TYPES}
              onNodeClick={onNodeClick}
              onEdgeClick={onEdgeClick}
              fitView
              fitViewOptions={{ padding: 0.15, minZoom: 0.5 }}
              minZoom={0.3}
              maxZoom={2}
              colorMode="dark"
              proOptions={{ hideAttribution: true }}
            >
              <Background
                variant={BackgroundVariant.Dots}
                gap={22}
                size={1.6}
                color="#3a4556"
              />
              {includeDescendants && lanes.length > 1 && (
                <LaneBackground lanes={lanes} rootRunId={run.id} />
              )}
              <Panel position="top-left" style={{ margin: 12, pointerEvents: "auto" }}>
                {selectedEdgeId && (
                  <SelectedEdgePanel
                    edge={baseEdges.find((e) => e.id === selectedEdgeId)}
                    tree={tree}
                    t={t}
                    onClose={() => setSelectedEdgeId(null)}
                  />
                )}
              </Panel>
              <Panel position="top-right" style={{ margin: 12, pointerEvents: "none" }}>
                <Legend showLanes={includeDescendants && lanes.length > 1} />
              </Panel>
              <Controls showInteractive={false} />
              <MiniMap
                pannable
                zoomable
                nodeColor="#58a6ff"
                maskColor="rgba(13,17,23,0.7)"
              />
            </ReactFlow>
          )}
        </Col>
      </Row>

      <Drawer
        title={t("nodeDetails.title")}
        open={!!selectedNode}
        onClose={() => setSelectedId(null)}
        width={520}
        destroyOnHidden
        mask={false}
      >
        {selectedNode && (
          <NodeDetails
            node={selectedNode}
            onFork={(n) => setForkNodeId(n.id)}
          />
        )}
      </Drawer>

      <ForkPlanModal
        runId={run.id}
        nodeId={forkNodeId}
        nodeName={forkNode?.node_name ?? null}
        stepIndex={forkNode?.step_index ?? null}
        onClose={() => setForkNodeId(null)}
      />
    </div>
  );
}

export default function TreeView({ runId }: { runId: string }) {
  const { t } = useTranslation();
  const [run, setRun] = useState<Run | null>(null);
  const [tree, setTree] = useState<Tree | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [includeDescendants, setIncludeDescendants] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setRun(null);
    setTree(null);
    Promise.all([fetchRun(runId), fetchTree(runId, includeDescendants)])
      .then(([runRes, treeRes]) => {
        if (cancelled) return;
        setRun(runRes.run);
        setTree(treeRes);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, includeDescendants]);

  if (error) {
    return (
      <motion.div className="chr-page" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <Alert
          type="error"
          showIcon
          message={t("errors.runNotFound")}
          description={error}
          action={
            <Button onClick={() => { window.location.hash = "#/"; }}>
              {t("common.backToList")}
            </Button>
          }
        />
      </motion.div>
    );
  }

  if (!run || !tree) {
    return (
      <div className="chr-page">
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    );
  }

  return (
    <div className="chr-page chr-tree-page">
      <ReactFlowProvider>
        <InnerTree
          tree={tree}
          run={run}
          includeDescendants={includeDescendants}
          onToggleDescendants={setIncludeDescendants}
        />
      </ReactFlowProvider>
    </div>
  );
}

/** Renders translucent horizontal swim-lanes behind the nodes to visually
 * separate descendant runs. Positioned in flow-space so it pans & zooms with
 * the graph. */
function LaneBackground({
  lanes,
  rootRunId,
}: {
  lanes: LaneInfo[];
  rootRunId: string;
}) {
  const { t } = useTranslation();
  const { x, y, zoom } = useViewport();
  return (
    <Panel position="top-left" style={{ pointerEvents: "none", margin: 0 }}>
      <div style={{ position: "relative" }}>
        {lanes.map((lane, idx) => {
          const isRoot = lane.runId === rootRunId;
          // flow-space → screen-space
          const screenX = x;
          const screenY = y + lane.y * zoom;
          const hue = isRoot ? "88,166,255" : (idx * 47) % 360;
          const bg = isRoot
            ? "rgba(88,166,255,0.04)"
            : `hsla(${hue}, 70%, 55%, 0.06)`;
          const borderColor = isRoot
            ? "rgba(88,166,255,0.35)"
            : `hsla(${hue}, 70%, 55%, 0.35)`;
          return (
            <div
              key={lane.runId}
              style={{
                position: "absolute",
                left: screenX - 24 * zoom,
                top: screenY,
                width: (lane.width + 48) * zoom,
                height: lane.height * zoom,
                background: bg,
                border: `1px dashed ${borderColor}`,
                borderRadius: 8 * zoom,
                padding: 0,
              }}
            >
              <div
                style={{
                  position: "absolute",
                  top: 6 * zoom,
                  left: 12 * zoom,
                  fontSize: 11 * zoom,
                  fontFamily: "monospace",
                  color: isRoot ? "#58a6ff" : `hsl(${hue},70%,70%)`,
                  letterSpacing: 0.5,
                  textTransform: "uppercase",
                  fontWeight: 700,
                  whiteSpace: "nowrap",
                }}
              >
                {isRoot ? t("tree.laneRoot") : t("tree.laneFork")}
                <span style={{ marginLeft: 8, opacity: 0.75, fontWeight: 500 }}>
                  {lane.adapter ? `[${lane.adapter}] ` : ""}
                  {lane.label.slice(0, 48)}
                  {lane.label.length > 48 ? "…" : ""}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function SelectedEdgePanel({
  edge,
  tree,
  t,
  onClose,
}: {
  edge: RFEdge | undefined;
  tree: Tree;
  t: (k: string, vars?: Record<string, unknown>) => string;
  onClose: () => void;
}) {
  if (!edge) return null;
  const isFork = edge.data?.kind === "fork";
  const sourceNode = tree.nodes.find((n) => n.id === edge.source);
  const targetNode = tree.nodes.find((n) => n.id === edge.target);
  const sourceLabel = sourceNode?.node_name ?? edge.source.slice(0, 12);
  const targetLabel = targetNode?.node_name ?? edge.target.slice(0, 12);
  const accent = isFork ? "#c678f7" : "#58a6ff";
  const accentSoft = isFork ? "rgba(198,120,247,0.08)" : "rgba(88,166,255,0.08)";
  return (
    <div
      style={{
        padding: "10px 14px",
        background: `linear-gradient(180deg, ${accentSoft}, rgba(13,17,23,0.92))`,
        border: `1px solid ${accent}55`,
        borderLeft: `3px solid ${accent}`,
        borderRadius: 8,
        fontSize: 12,
        position: "relative",
        minWidth: 220,
        boxShadow: "0 4px 16px rgba(0,0,0,0.4)",
      }}
    >
      <button
        onClick={onClose}
        aria-label="close"
        style={{
          position: "absolute",
          top: 6,
          right: 8,
          background: "transparent",
          border: "none",
          color: "#8b949e",
          cursor: "pointer",
          fontSize: 14,
          lineHeight: 1,
        }}
      >
        ×
      </button>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 6,
          color: accent,
          fontWeight: 600,
          letterSpacing: 0.3,
          fontSize: 11,
          textTransform: "uppercase",
        }}
      >
        {isFork ? <GitFork size={12} /> : <ArrowRight size={12} />}
        {isFork ? t("tree.edgeTypeFork") : t("tree.edgeTypeSequential")}
      </div>
      <div style={{ color: "#c9d1d9", fontFamily: "monospace", fontSize: 11, lineHeight: 1.6 }}>
        <span style={{ color: "#8b949e" }}>{t("tree.edgeFrom.from")}:</span>{" "}
        <span style={{ color: "#e6edf3" }}>{sourceLabel}</span>
        <br />
        <span style={{ color: "#8b949e" }}>{t("tree.edgeFrom.to")}:</span>{" "}
        <span style={{ color: "#e6edf3" }}>{targetLabel}</span>
      </div>
      <div style={{ marginTop: 8, color: "#8b949e", fontSize: 11, lineHeight: 1.5 }}>
        {isFork ? t("tree.edgeForkExplain") : t("tree.edgeSequentialExplain")}
      </div>
    </div>
  );
}
