// Runs page — AntD Table with status badges, adapter tag, click-to-drill.
// Supports text search + framework filter. Explanatory empty state for new users.
import { useEffect, useMemo, useState } from "react";
import {
  Table,
  Tag,
  Typography,
  Input,
  Select,
  Empty,
  Space,
  Badge,
  Alert,
  Skeleton,
  Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Search as SearchIcon } from "lucide-react";
import { fetchRuns } from "../api";
import type { Run, RunStatus } from "../types";
import ConceptTip from "../components/ConceptTip";

const { Title, Paragraph, Text } = Typography;

type EnrichedRun = Run & {
  _nodeCount?: number;
  _costUsd?: number;
  _durationMs?: number;
};

function statusColor(s: RunStatus): string {
  switch (s) {
    case "completed":
      return "success";
    case "running":
      return "processing";
    case "failed":
      return "error";
    case "forked":
      return "warning";
    case "pending":
      return "default";
    default:
      return "default";
  }
}

export default function RunList() {
  const { t, i18n } = useTranslation();
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [adapterFilter, setAdapterFilter] = useState<string>("all");

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchRuns(200)
      .then((res) => {
        if (!cancelled) setRuns(res.runs);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const adapters = useMemo(() => {
    if (!runs) return [];
    return Array.from(new Set(runs.map((r) => r.adapter))).sort();
  }, [runs]);

  const filtered = useMemo(() => {
    if (!runs) return [];
    const q = query.trim().toLowerCase();
    return runs.filter((r) => {
      if (adapterFilter !== "all" && r.adapter !== adapterFilter) return false;
      if (!q) return true;
      return (
        r.id.toLowerCase().includes(q) ||
        (r.task_description ?? "").toLowerCase().includes(q) ||
        r.adapter.toLowerCase().includes(q)
      );
    });
  }, [runs, query, adapterFilter]);

  const columns: ColumnsType<EnrichedRun> = [
    {
      title: t("runs.columns.status"),
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (status: RunStatus) => (
        <Badge status={statusColor(status) as "success" | "processing" | "error" | "warning" | "default"} text={t(`status.${status}`, { defaultValue: status })} />
      ),
      filters: ["completed", "running", "failed", "forked", "pending"].map((s) => ({
        text: t(`status.${s}`, { defaultValue: s }),
        value: s,
      })),
      onFilter: (value, record) => record.status === value,
    },
    {
      title: t("runs.columns.task"),
      dataIndex: "task_description",
      key: "task_description",
      ellipsis: true,
      render: (desc: string | null, row) => (
        <Space direction="vertical" size={2} style={{ lineHeight: 1.3 }}>
          <Text strong ellipsis style={{ maxWidth: 420 }}>
            {desc ?? <Text type="secondary" italic>(no description)</Text>}
          </Text>
          <Text type="secondary" style={{ fontSize: 11, fontFamily: "monospace" }}>
            {row.id}
          </Text>
        </Space>
      ),
    },
    {
      title: t("runs.columns.adapter"),
      dataIndex: "adapter",
      key: "adapter",
      width: 120,
      render: (a: string) => <Tag color="geekblue">{a}</Tag>,
    },
    {
      title: t("runs.columns.started"),
      dataIndex: "started_at",
      key: "started_at",
      width: 180,
      render: (ts: string) => (
        <Tooltip title={ts}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {new Date(ts).toLocaleString(i18n.language)}
          </Text>
        </Tooltip>
      ),
      sorter: (a, b) => (a.started_at > b.started_at ? 1 : -1),
      defaultSortOrder: "descend",
    },
  ];

  const handleRowClick = (run: Run) => {
    window.location.hash = `#/runs/${encodeURIComponent(run.id)}`;
  };

  return (
    <motion.div
      className="chr-page"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <div className="chr-page-head">
        <Title level={3} style={{ margin: 0 }}>
          {t("runs.title")}
        </Title>
        <Paragraph style={{ color: "var(--chr-text-secondary)", margin: "6px 0 0" }}>
          {t("runs.lead")} — <ConceptTip concept="run" asIcon />
        </Paragraph>
      </div>

      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          allowClear
          prefix={<SearchIcon size={14} />}
          placeholder={t("runs.searchPlaceholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ width: 320 }}
        />
        <Select
          value={adapterFilter}
          onChange={setAdapterFilter}
          style={{ minWidth: 160 }}
          options={[
            { value: "all", label: t("common.all") },
            ...adapters.map((a) => ({ value: a, label: a })),
          ]}
        />
      </Space>

      {error && (
        <Alert
          type="error"
          showIcon
          message={t("errors.apiFailed")}
          description={error}
          style={{ marginBottom: 16 }}
        />
      )}

      {runs === null && !error ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : (
        <Table<EnrichedRun>
          rowKey="id"
          dataSource={filtered}
          columns={columns}
          pagination={{ pageSize: 20, showSizeChanger: false, hideOnSinglePage: true }}
          onRow={(record) => ({
            onClick: () => handleRowClick(record),
            style: { cursor: "pointer" },
          })}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <Space direction="vertical" size={4}>
                    <Text>{t("runs.noRuns")}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {t("runs.noRunsHint")}
                    </Text>
                  </Space>
                }
              />
            ),
          }}
        />
      )}
    </motion.div>
  );
}
