// StatePanel — adapter-aware renderer for `node.state_after` (R93, ADR-027 §2;
// extended at R94 slice 3 — shape-aware block-content rendering).
//
// Replaces the raw `JSON.stringify(node.state_after, null, 2)` <pre> block in
// Replay.tsx with a structured view: per-adapter formatters in
// `frontend/src/format/registry.ts` produce a list of labelled sections; this
// component renders them as a stack of collapsible blocks plus a "Show raw"
// toggle that falls back to the original JSON dump.
//
// Goals (per ADR-027 §2):
//   - For anthropic_agents: each Anthropic block becomes its own section,
//     ToolUseBlock / ToolResultBlock surface their tool_use_id as a sub-label.
//     R94 slice 3 adds: TextBlock body as plain text, ToolUseBlock input as a
//     key→value table, ToolResultBlock content as a code-fenced block with an
//     error tag when `is_error` is set.
//   - For langgraph: top-level keys become sections; small leaf values render
//     inline, complex objects render as JSON.
//   - For other adapters: same UI as before (raw JSON dump) so we don't
//     regress them while we add formatters incrementally.
//
// All visible strings route through i18n under `replay.state.*`.
import {
  Collapse,
  Descriptions,
  Empty,
  Space,
  Switch,
  Tag,
  Typography,
  theme,
} from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { safeStringify } from "../format/adapters/default";
import {
  formatState,
  type SectionPayload,
} from "../format/registry";
import type { Node } from "../types";

interface StatePanelProps {
  node: Node;
  adapter: string | null | undefined;
}

export default function StatePanel({ node, adapter }: StatePanelProps) {
  const { t } = useTranslation();
  const { token } = theme.useToken();
  const [showRaw, setShowRaw] = useState(false);

  // Memoise on (node id, adapter) — the formatter is pure and can be a bit
  // chatty for large multi-block ResultMessages, so we don't want to redo it
  // on every unrelated re-render.
  const formatted = useMemo(
    () => formatState(node, adapter),
    [node, adapter],
  );

  const empty =
    node.state_after === null ||
    node.state_after === undefined ||
    (typeof node.state_after === "object" &&
      !Array.isArray(node.state_after) &&
      Object.keys(node.state_after as Record<string, unknown>).length === 0);

  if (empty) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t("replay.state.empty")}
        style={{ margin: "8px 0" }}
      />
    );
  }

  const codeBlockStyle: React.CSSProperties = {
    margin: 0,
    maxHeight: 280,
    overflow: "auto",
    background: token.colorFillTertiary,
    padding: 8,
    borderRadius: 4,
    fontSize: 12,
    fontFamily:
      "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  };

  // "Show raw" branch or fall through to default formatter (no sections):
  // render the raw JSON dump as before.
  const renderRaw = showRaw || formatted.sections.length === 0;

  // ---------------------------------------------------------------------------
  // Per-section body renderer — switches on the discriminated `payload.kind`.
  // String payloads (default / langgraph / header / extras) keep the legacy
  // <pre> code-block; structured payloads from anthropic_agents (R94 slice 3)
  // render with shape-aware affordances.
  // ---------------------------------------------------------------------------
  const sectionBodyStyle: React.CSSProperties = { ...codeBlockStyle, maxHeight: 220 };

  function renderPayload(payload: SectionPayload): React.ReactNode {
    if (typeof payload === "string") {
      return <pre style={sectionBodyStyle}>{payload}</pre>;
    }

    switch (payload.kind) {
      case "text": {
        const body = payload.text.length > 0
          ? payload.text
          : t("replay.state.textBlockEmpty");
        return (
          <Typography.Paragraph
            style={{
              margin: 0,
              padding: 8,
              background: token.colorFillTertiary,
              borderRadius: 4,
              fontSize: 13,
              maxHeight: 280,
              overflow: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {body}
          </Typography.Paragraph>
        );
      }

      case "tool_use": {
        const entries = Object.entries(payload.input);
        return (
          <Space direction="vertical" size={6} style={{ width: "100%" }}>
            <Space size={6} wrap>
              <Tag color="purple">{t("replay.state.toolUseBlock")}</Tag>
              {payload.name && (
                <Typography.Text strong style={{ fontSize: 12 }}>
                  {payload.name}
                </Typography.Text>
              )}
            </Space>
            {entries.length === 0 ? (
              <Typography.Text
                type="secondary"
                style={{ fontSize: 12, fontStyle: "italic" }}
              >
                {t("replay.state.toolUseEmpty")}
              </Typography.Text>
            ) : (
              <Descriptions
                size="small"
                column={1}
                bordered
                style={{ background: token.colorBgContainer }}
              >
                {entries.map(([k, v]) => (
                  <Descriptions.Item
                    key={k}
                    label={
                      <Typography.Text
                        style={{ fontSize: 12, fontFamily: "monospace" }}
                      >
                        {k}
                      </Typography.Text>
                    }
                  >
                    <pre
                      style={{
                        ...sectionBodyStyle,
                        margin: 0,
                        maxHeight: 180,
                        background: "transparent",
                        padding: 4,
                      }}
                    >
                      {typeof v === "string" ? v : safeStringify(v)}
                    </pre>
                  </Descriptions.Item>
                ))}
              </Descriptions>
            )}
          </Space>
        );
      }

      case "tool_result": {
        return (
          <Space direction="vertical" size={6} style={{ width: "100%" }}>
            <Space size={6} wrap>
              <Tag color="cyan">{t("replay.state.toolResultBlock")}</Tag>
              {payload.isError && (
                <Tag color="red">{t("replay.state.toolError")}</Tag>
              )}
            </Space>
            <pre
              style={{
                ...sectionBodyStyle,
                background: payload.isError
                  ? token.colorErrorBg
                  : token.colorFillTertiary,
              }}
            >
              {payload.content.length > 0
                ? payload.content
                : t("replay.state.toolResultEmpty")}
            </pre>
          </Space>
        );
      }

      case "json":
      default:
        return <pre style={sectionBodyStyle}>{safeStringify(payload.value)}</pre>;
    }
  }

  return (
    <div>
      <Space
        size={8}
        style={{ marginBottom: 8, flexWrap: "wrap" }}
        align="center"
      >
        {formatted.envelope && !formatted.isDefault && (
          <Tag color="geekblue" style={{ marginInlineEnd: 0 }}>
            {formatted.envelope}
          </Tag>
        )}
        {formatted.isDefault ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t("replay.state.defaultHint")}
          </Typography.Text>
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t("replay.state.formatterHint", { adapter: formatted.adapter })}
          </Typography.Text>
        )}
        {!formatted.isDefault && formatted.sections.length > 0 && (
          <Space size={6} align="center">
            <Typography.Text style={{ fontSize: 12 }}>
              {t("replay.state.showRaw")}
            </Typography.Text>
            <Switch
              size="small"
              checked={showRaw}
              onChange={setShowRaw}
              aria-label={t("replay.state.showRaw")}
            />
          </Space>
        )}
      </Space>

      {renderRaw ? (
        <pre style={codeBlockStyle}>{formatted.raw}</pre>
      ) : (
        <Collapse
          size="small"
          bordered={false}
          defaultActiveKey={formatted.sections
            .filter((s) => !s.collapsed)
            .map((s) => s.id)}
          items={formatted.sections.map((section) => ({
            key: section.id,
            label: (
              <Space size={6} align="center" style={{ flexWrap: "wrap" }}>
                <Typography.Text strong style={{ fontSize: 12 }}>
                  {section.label}
                </Typography.Text>
                {section.subLabel && (
                  <Typography.Text
                    type="secondary"
                    style={{ fontSize: 11, fontFamily: "monospace" }}
                  >
                    {section.subLabel}
                  </Typography.Text>
                )}
              </Space>
            ),
            children: renderPayload(section.payload),
          }))}
        />
      )}
    </div>
  );
}
