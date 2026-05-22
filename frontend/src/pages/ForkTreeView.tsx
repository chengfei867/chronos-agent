// ForkTreeView.tsx — R95 / Phase 5 Arc C slice 4 (ADR-027 §2)
//
// Page at #/runs/<id>/forks. Fetches the descendant tree
// (`fetchTree(rid, includeDescendants=true)`) and renders the
// ForkTimeline component. Click on any fork-tree node navigates to
// that run's linear replay (#/runs/<that-id>/replay).
//
// Slot-1 ship (R95): bare page + breadcrumb + ForkTimeline. Slot-2
// (R96) layers on the side-panel state preview re-using StatePanel.

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Breadcrumb,
  Card,
  Empty,
  Skeleton,
  Space,
  Typography,
} from "antd";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { fetchTree } from "../api";
import type { Tree } from "../types";
import ForkTimeline from "../components/ForkTimeline";

interface ForkTreeViewProps {
  runId: string;
}

export default function ForkTreeView({ runId }: ForkTreeViewProps) {
  const { t } = useTranslation();
  const [tree, setTree] = useState<Tree | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchTree(runId, true)
      .then((res) => {
        if (cancelled) return;
        setTree(res);
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

  const handleSelectRun = useCallback((rid: string) => {
    window.location.hash = `/runs/${encodeURIComponent(rid)}/replay`;
  }, []);

  const handleBack = useCallback(() => {
    window.location.hash = `/runs/${encodeURIComponent(runId)}`;
  }, [runId]);

  return (
    <div style={{ padding: "24px", maxWidth: 1100, margin: "0 auto" }}>
      <Breadcrumb
        style={{ marginBottom: 12 }}
        items={[
          {
            title: (
              <a
                onClick={(e) => {
                  e.preventDefault();
                  window.location.hash = "/runs";
                }}
                href="#/runs"
              >
                {t("replay.back")}
              </a>
            ),
          },
          {
            title: (
              <a
                onClick={(e) => {
                  e.preventDefault();
                  handleBack();
                }}
                href={`#/runs/${encodeURIComponent(runId)}`}
              >
                {runId.slice(0, 8)}
              </a>
            ),
          },
          { title: t("replay.fork.title") },
        ]}
      />

      <Typography.Title level={3} style={{ marginTop: 0 }}>
        <Space>
          <ArrowLeft
            size={18}
            style={{ cursor: "pointer", verticalAlign: "middle" }}
            onClick={handleBack}
          />
          {t("replay.fork.title")}
        </Space>
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginTop: -4 }}>
        {t("replay.fork.subtitle")}
      </Typography.Paragraph>

      {loading ? (
        <Card>
          <Skeleton active paragraph={{ rows: 5 }} />
        </Card>
      ) : error ? (
        <Alert type="error" message={t("replay.errorTitle")} description={error} showIcon />
      ) : !tree || (tree.descendant_run_ids?.length ?? 0) <= 1 ? (
        <Card>
          <Empty description={t("replay.fork.empty")} />
        </Card>
      ) : (
        <Card>
          <ForkTimeline tree={tree} activeRunId={runId} onSelectRun={handleSelectRun} />
        </Card>
      )}
    </div>
  );
}
