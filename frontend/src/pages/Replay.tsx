// Replay.tsx — Phase 5 Arc C slice 1 (R92, ADR-027 §2)
//
// Linear replay UI: renders one run as a sequence of steps. Reuses the existing
// usePlayback hook (R37, extended in R92 with stepBack/stepForward/jumpTo) to
// drive a horizontal PlaybackTimeline plus an "active step" card. No new API —
// data comes from the existing GET /runs/{id} endpoint (validated by spike16).
//
// Keyboard contract (ADR-027 §2):
//   ←  step back     (clamped at 0)
//   →  step forward  (clamped at N-1)
//   Space  toggle play/pause
//   q  quit → navigate back to /runs
//
// Design choice: this is a *linear* view — siblings/forks are ignored. For the
// reasoning *tree*, users go to TreeView (#/runs/<id>). Replay is the
// "watch the agent think, frame by frame" experience.
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Skeleton,
  Space,
  Tag,
  Typography,
  theme,
} from "antd";
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  RotateCcw,
  ArrowLeft,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { fetchRun } from "../api";
import type { Node as ChronosNode, NodeKind, Run } from "../types";
import { usePlayback } from "../hooks/usePlayback";
import PlaybackTimeline from "../components/PlaybackTimeline";
import StatePanel from "../components/StatePanel";

const KIND_COLORS: Record<NodeKind, string> = {
  llm: "#a371f7",
  tool: "#58a6ff",
  fn: "#3fb950",
  router: "#d29922",
  fork: "#f778ba",
  end: "#8b949e",
};

interface ReplayProps {
  runId: string;
}

export default function Replay({ runId }: ReplayProps) {
  const { t } = useTranslation();
  const { token } = theme.useToken();
  const [run, setRun] = useState<Run | null>(null);
  const [nodes, setNodes] = useState<ChronosNode[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Fetch run + nodes via the same endpoint TreeView uses. No /replay endpoint
  // (ADR-027 §2: no API change for slice 1).
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchRun(runId)
      .then((res) => {
        if (cancelled) return;
        setRun(res.run);
        // Sort by step_index — spike16 confirmed dense 0..N-1.
        const sorted = [...res.nodes].sort((a, b) => a.step_index - b.step_index);
        setNodes(sorted);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setError(e.message ?? String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const total = nodes.length;
  const {
    playing,
    index,
    play,
    pause,
    reset,
    stepBack,
    stepForward,
    jumpTo,
  } = usePlayback(total);

  // Active node — index === -1 means "not started"; show step 0 as a preview
  // so users see what's coming without auto-advancing.
  const activeIndex = index < 0 ? 0 : index;
  const activeNode = nodes[activeIndex];

  const goBack = useCallback(() => {
    window.location.hash = "#/";
  }, []);

  // Keyboard nav per ADR-027 §2.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Don't hijack typing in inputs/textareas.
      const tgt = e.target as HTMLElement | null;
      if (
        tgt &&
        (tgt.tagName === "INPUT" ||
          tgt.tagName === "TEXTAREA" ||
          tgt.isContentEditable)
      ) {
        return;
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        stepBack();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        stepForward();
      } else if (e.key === " " || e.code === "Space") {
        e.preventDefault();
        if (playing) {
          pause();
        } else {
          play();
        }
      } else if (e.key === "q" || e.key === "Q") {
        e.preventDefault();
        goBack();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [stepBack, stepForward, play, pause, playing, goBack]);

  const headerTitle = useMemo(() => {
    if (!run) return runId;
    return run.task_description?.trim() || run.adapter_thread_id || run.id;
  }, [run, runId]);

  if (loading) {
    return (
      <div style={{ padding: 24 }}>
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <Alert
          type="error"
          showIcon
          message={t("replay.errorTitle")}
          description={error}
          action={
            <Button size="small" onClick={goBack}>
              {t("replay.back")}
            </Button>
          }
        />
      </div>
    );
  }

  if (!run || total === 0) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description={t("replay.empty")} />
        <div style={{ marginTop: 16, textAlign: "center" }}>
          <Button onClick={goBack} icon={<ArrowLeft size={14} />}>
            {t("replay.back")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div
      className="chr-replay-page"
      style={{
        padding: 24,
        maxWidth: 1100,
        margin: "0 auto",
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <Button
          icon={<ArrowLeft size={14} />}
          onClick={goBack}
          aria-label={t("replay.back")}
        >
          {t("replay.back")}
        </Button>
        <Typography.Title level={4} style={{ margin: 0, flex: 1 }} ellipsis>
          {t("replay.title")} · {headerTitle}
        </Typography.Title>
        <Tag color="geekblue">{run.adapter}</Tag>
        <Typography.Text type="secondary">
          {t("replay.stepOf", { current: activeIndex + 1, total })}
        </Typography.Text>
      </div>

      {/* Controls */}
      <Space wrap>
        <Button
          icon={<SkipBack size={14} />}
          onClick={stepBack}
          disabled={index <= 0}
          aria-label={t("replay.stepBack")}
        >
          {t("replay.stepBack")}
        </Button>
        {playing ? (
          <Button
            type="primary"
            icon={<Pause size={14} />}
            onClick={pause}
            aria-label={t("tree.pause")}
          >
            {t("tree.pause")}
          </Button>
        ) : (
          <Button
            type="primary"
            icon={<Play size={14} />}
            onClick={play}
            aria-label={t("tree.play")}
          >
            {t("tree.play")}
          </Button>
        )}
        <Button
          icon={<SkipForward size={14} />}
          onClick={stepForward}
          disabled={index >= total - 1}
          aria-label={t("replay.stepForward")}
        >
          {t("replay.stepForward")}
        </Button>
        <Button
          icon={<RotateCcw size={14} />}
          onClick={reset}
          aria-label={t("tree.reset")}
        >
          {t("tree.reset")}
        </Button>
        <Typography.Text type="secondary" style={{ marginInlineStart: 8 }}>
          {t("replay.kbdHint")}
        </Typography.Text>
      </Space>

      {/* Timeline */}
      <PlaybackTimeline
        nodes={nodes}
        activeIndex={activeIndex}
        onJump={jumpTo}
      />

      {/* Active node card */}
      {activeNode && (
        <Card
          size="small"
          className="chr-replay-active-node"
          style={{
            borderLeft: `3px solid ${KIND_COLORS[activeNode.kind] ?? token.colorPrimary}`,
          }}
          title={
            <Space size={8} wrap>
              <Tag color="blue">#{activeNode.step_index}</Tag>
              <Tag color={activeNode.error_message ? "red" : undefined}>
                {t(`nodeKind.${activeNode.kind}`, {
                  defaultValue: activeNode.kind,
                })}
              </Tag>
              <Typography.Text strong>{activeNode.node_name}</Typography.Text>
            </Space>
          }
        >
          <Descriptions
            size="small"
            column={1}
            colon={false}
            labelStyle={{ width: 140, color: token.colorTextSecondary }}
          >
            {activeNode.model_name && (
              <Descriptions.Item label={t("replay.model")}>
                {activeNode.model_name}
              </Descriptions.Item>
            )}
            {activeNode.tool_name && (
              <Descriptions.Item label={t("replay.tool")}>
                {activeNode.tool_name}
              </Descriptions.Item>
            )}
            {activeNode.error_message && (
              <Descriptions.Item label={t("replay.errorTitle")}>
                <Typography.Text type="danger">
                  {activeNode.error_message}
                </Typography.Text>
              </Descriptions.Item>
            )}
            <Descriptions.Item label={t("replay.stateAfter")}>
              <StatePanel node={activeNode} adapter={run.adapter} />
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}
    </div>
  );
}
