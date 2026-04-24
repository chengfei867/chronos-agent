// TreeView page — left: run summary | center: ReactFlow reasoning tree |
// right: node details drawer. Top toolbar has the "Play from start" killer.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  useReactFlow,
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
} from "antd";
import {
  Play,
  Pause,
  RotateCcw,
  Maximize2,
  ArrowLeft,
  Info,
} from "lucide-react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { fetchTree, fetchRun } from "../api";
import type { Run, Tree } from "../types";
import { treeToReactFlow } from "../layout";
import ChronosNodeCard from "../components/nodes/ChronosNodeCard";
import PlaceholderNode from "../components/nodes/PlaceholderNode";
import NodeDetails from "../components/NodeDetails";
import ConceptTip from "../components/ConceptTip";
import { usePlayback } from "../hooks/usePlayback";

const { Text } = Typography;

const NODE_TYPES = {
  chronos: ChronosNodeCard,
  placeholder: PlaceholderNode,
};

function InnerTree({
  tree,
  run,
}: {
  tree: Tree;
  run: Run;
}) {
  const { t, i18n } = useTranslation();
  const rf = useReactFlow();

  const orderedNodes = useMemo(
    () => [...tree.nodes].sort((a, b) => a.step_index - b.step_index),
    [tree.nodes],
  );

  const playback = usePlayback(orderedNodes.length);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { rfNodes: baseNodes, rfEdges: baseEdges } = useMemo(
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

  const rfEdges = useMemo<RFEdge[]>(() => baseEdges, [baseEdges]);

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
    },
    [],
  );

  const selectedNode = useMemo(
    () => orderedNodes.find((n) => n.id === selectedId) ?? null,
    [orderedNodes, selectedId],
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
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t("tree.stepOf", {
              current: Math.max(0, playback.index + 1),
              total: orderedNodes.length,
            })}
          </Text>
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
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {t("runs.columns.adapter")}
                </Text>
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
                    title={t("nodeDetails.fields.costUsd")}
                    value={totalCost === 0 ? "–" : (totalCost / 100).toFixed(4)}
                    prefix={totalCost > 0 ? "$" : ""}
                  />
                </Col>
              </Row>
              <Alert
                type="info"
                showIcon
                icon={<Info size={14} />}
                message={t("tree.clickHint")}
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
              fitView
              fitViewOptions={{ padding: 0.2 }}
              minZoom={0.3}
              maxZoom={2}
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={24} size={1} color="#30363d" />
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
        {selectedNode && <NodeDetails node={selectedNode} />}
      </Drawer>
    </div>
  );
}

export default function TreeView({ runId }: { runId: string }) {
  const { t } = useTranslation();
  const [run, setRun] = useState<Run | null>(null);
  const [tree, setTree] = useState<Tree | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setRun(null);
    setTree(null);
    Promise.all([fetchRun(runId), fetchTree(runId)])
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
  }, [runId]);

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
        <InnerTree tree={tree} run={run} />
      </ReactFlowProvider>
    </div>
  );
}
