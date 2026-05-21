// StatePanel — adapter-aware renderer for `node.state_after` (R93, ADR-027 §2).
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
//   - For langgraph: top-level keys become sections; small leaf values render
//     inline, complex objects render as JSON.
//   - For other adapters: same UI as before (raw JSON dump) so we don't
//     regress them while we add formatters incrementally.
//
// All visible strings route through i18n under `replay.state.*`.
import { Collapse, Empty, Space, Switch, Tag, Typography, theme } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { formatState } from "../format/registry";
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
            children: (
              <pre style={{ ...codeBlockStyle, maxHeight: 220 }}>
                {section.payload}
              </pre>
            ),
          }))}
        />
      )}
    </div>
  );
}
