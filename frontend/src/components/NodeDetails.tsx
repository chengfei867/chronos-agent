// Node details drawer body — grouped into tabs so the wall of JSON isn't
// dumped on the user at once. Every label uses i18n; every concept has a tip.
import { Tabs, Typography, Descriptions, Tag, Empty, Button, Space, App as AntApp, Alert } from "antd";
import { Copy } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Node as ChronosNode, NodeKind } from "../types";
import ConceptTip from "./ConceptTip";

function prettyJSON(v: unknown): string {
  if (v === null || v === undefined) return "";
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

function durationMs(node: ChronosNode): number | null {
  if (!node.ended_at) return null;
  const s = Date.parse(node.started_at);
  const e = Date.parse(node.ended_at);
  if (Number.isNaN(s) || Number.isNaN(e)) return null;
  return e - s;
}

function CodeBlock({ value }: { value: string }) {
  const { t } = useTranslation();
  const { message } = AntApp.useApp();
  if (!value || value === "null" || value === "{}") {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("nodeDetails.noData")} style={{ margin: "8px 0" }} />;
  }
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      void message.success(t("common.copied"));
    } catch {
      void message.error(t("common.error"));
    }
  };
  return (
    <div className="chr-code-block">
      <Button
        size="small"
        type="text"
        icon={<Copy size={12} />}
        className="chr-code-copy"
        onClick={copy}
        aria-label={t("common.copy")}
      />
      <pre>{value}</pre>
    </div>
  );
}

export default function NodeDetails({
  node,
  onFork,
}: {
  node: ChronosNode;
  onFork?: (node: ChronosNode) => void;
}) {
  const { t } = useTranslation();
  const kind = node.kind as NodeKind;
  const ms = durationMs(node);

  const identityTab = (
    <Descriptions size="small" column={1} bordered>
      <Descriptions.Item label={t("nodeDetails.fields.id")}>
        <Typography.Text code style={{ fontSize: 11 }}>{node.id}</Typography.Text>
      </Descriptions.Item>
      <Descriptions.Item label={t("nodeDetails.fields.name")}>{node.node_name}</Descriptions.Item>
      <Descriptions.Item label={t("nodeDetails.fields.kind")}>
        <Space>
          <Tag>{t(`nodeKind.${kind}`, { defaultValue: kind })}</Tag>
          <ConceptTip concept={kind === "fork" ? "fork" : "node"} asIcon>
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              {t("common.details")}
            </Typography.Text>
          </ConceptTip>
        </Space>
      </Descriptions.Item>
      <Descriptions.Item label={t("nodeDetails.fields.startedAt")}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {node.started_at}
        </Typography.Text>
      </Descriptions.Item>
      <Descriptions.Item label={t("nodeDetails.fields.endedAt")}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {node.ended_at ?? "–"}
        </Typography.Text>
      </Descriptions.Item>
      <Descriptions.Item label={t("nodeDetails.fields.durationMs")}>
        {ms == null ? "–" : `${ms} ms`}
      </Descriptions.Item>
      {node.parent_node_id && (
        <Descriptions.Item label={t("nodeDetails.fields.parent")}>
          <Typography.Text code style={{ fontSize: 11 }}>{node.parent_node_id}</Typography.Text>
        </Descriptions.Item>
      )}
    </Descriptions>
  );

  const ioTab = (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      {node.error_message && (
        <Alert type="error" showIcon message={t("nodeDetails.fields.errorMessage")} description={node.error_message} />
      )}
      {node.tool_name && (
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label={t("nodeDetails.fields.toolName")}>{node.tool_name}</Descriptions.Item>
        </Descriptions>
      )}
      {node.tool_input && (
        <div>
          <Typography.Text strong>{t("nodeDetails.fields.toolInput")}</Typography.Text>
          <CodeBlock value={prettyJSON(node.tool_input)} />
        </div>
      )}
      {node.tool_output && (
        <div>
          <Typography.Text strong>{t("nodeDetails.fields.toolOutput")}</Typography.Text>
          <CodeBlock value={prettyJSON(node.tool_output)} />
        </div>
      )}
      {!node.tool_input && !node.tool_output && !node.tool_name && !node.error_message && (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("nodeDetails.noData")} />
      )}
    </Space>
  );

  const stateTab = (
    <div>
      <Typography.Text strong>{t("nodeDetails.fields.stateAfter")}</Typography.Text>
      <CodeBlock value={prettyJSON(node.state_after)} />
    </div>
  );

  const metaTab = (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      {node.model_name && (
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label={t("nodeDetails.fields.model")}>
            <Tag color="purple">{node.model_name}</Tag>
          </Descriptions.Item>
        </Descriptions>
      )}
      {node.usage && (
        <Descriptions size="small" column={2} bordered>
          <Descriptions.Item label={t("nodeDetails.fields.promptTokens")}>
            {node.usage.prompt_tokens ?? "–"}
          </Descriptions.Item>
          <Descriptions.Item label={t("nodeDetails.fields.completionTokens")}>
            {node.usage.completion_tokens ?? "–"}
          </Descriptions.Item>
          <Descriptions.Item label={t("nodeDetails.fields.totalTokens")}>
            {node.usage.total_tokens ?? "–"}
          </Descriptions.Item>
          <Descriptions.Item label={t("nodeDetails.fields.costUsd")}>
            {node.cost_usd_cents == null ? "–" : `$${(node.cost_usd_cents / 100).toFixed(4)}`}
          </Descriptions.Item>
        </Descriptions>
      )}
      <div>
        <Typography.Text strong>{t("nodeDetails.fields.metadata")}</Typography.Text>
        <CodeBlock value={prettyJSON(node.metadata)} />
      </div>
    </Space>
  );

  return (
    <div>
      <Tabs
        defaultActiveKey="identity"
        items={[
          { key: "identity", label: t("nodeDetails.tabs.identity"), children: identityTab },
          { key: "io", label: t("nodeDetails.tabs.io"), children: ioTab },
          { key: "state", label: t("nodeDetails.tabs.state"), children: stateTab },
          { key: "meta", label: t("nodeDetails.tabs.meta"), children: metaTab },
        ]}
      />
      {onFork && (
        <div style={{ marginTop: 12 }}>
          <Button block onClick={() => onFork(node)}>
            {t("tree.forkThis")}
          </Button>
        </div>
      )}
    </div>
  );
}
