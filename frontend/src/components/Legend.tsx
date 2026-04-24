// Legend — compact floating card that explains the node colors, edge styles,
// and super-lane layout to non-technical readers. Rendered inside a ReactFlow
// Panel so it stays pinned to the canvas corner regardless of pan/zoom.
//
// Collapsed by default to stay out of the way; click to expand. State persists
// via localStorage so repeat visitors don't have to re-collapse every time.
import { useState, useEffect } from "react";
import { Card, Typography, Space, Button } from "antd";
import {
  Brain,
  Wrench,
  Code2,
  GitFork,
  Flag,
  Split,
  ChevronDown,
  ChevronUp,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { NodeKind } from "../types";

const LS_KEY = "chronos.legend.expanded.v1";

const KIND_ROWS: { kind: NodeKind; color: string; Icon: LucideIcon }[] = [
  { kind: "llm", color: "#a371f7", Icon: Brain },
  { kind: "tool", color: "#58a6ff", Icon: Wrench },
  { kind: "fn", color: "#3fb950", Icon: Code2 },
  { kind: "router", color: "#d29922", Icon: Split },
  { kind: "fork", color: "#f778ba", Icon: GitFork },
  { kind: "end", color: "#8b949e", Icon: Flag },
];

export default function Legend({
  showLanes,
  showDiff,
}: {
  showLanes?: boolean;
  showDiff?: boolean;
}) {
  const { t } = useTranslation();
  // Diff mode has many sections (kinds + edges + diff) so start collapsed
  // to avoid covering the narrow side-by-side graph panels on small screens.
  const lsKey = showDiff ? `${LS_KEY}.diff` : LS_KEY;
  const defaultExpanded = !showDiff;
  const [expanded, setExpanded] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem(lsKey);
      return stored === null ? defaultExpanded : stored === "1";
    } catch {
      return defaultExpanded;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(lsKey, expanded ? "1" : "0");
    } catch {
      /* ignore quota / privacy-mode failures */
    }
  }, [expanded, lsKey]);

  return (
    <Card
      size="small"
      className="chr-legend"
      styles={{
        body: { padding: expanded ? 12 : "6px 10px" },
      }}
      style={{
        background: "rgba(22, 27, 34, 0.92)",
        borderColor: "rgba(88,166,255,0.25)",
        backdropFilter: "blur(6px)",
        WebkitBackdropFilter: "blur(6px)",
        minWidth: expanded ? 220 : undefined,
        maxWidth: 260,
        maxHeight: "calc(100vh - 220px)",
        overflowY: "auto",
        pointerEvents: "auto",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          cursor: "pointer",
          userSelect: "none",
        }}
        onClick={() => setExpanded((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setExpanded((v) => !v);
          }
        }}
        tabIndex={0}
        role="button"
        aria-expanded={expanded}
        aria-label={t("legend.title")}
      >
        <Typography.Text strong style={{ fontSize: 12 }}>
          {t("legend.title")}
        </Typography.Text>
        <Button
          type="text"
          size="small"
          icon={expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          style={{ height: 20, width: 20, padding: 0 }}
          onClick={(e) => {
            e.stopPropagation();
            setExpanded((v) => !v);
          }}
        />
      </div>

      {expanded && (
        <Space direction="vertical" size={8} style={{ width: "100%", marginTop: 8 }}>
          <div>
            <Typography.Text
              type="secondary"
              style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 }}
            >
              {t("legend.nodeKinds")}
            </Typography.Text>
            <div style={{ marginTop: 4, display: "grid", gap: 4 }}>
              {KIND_ROWS.map(({ kind, color, Icon }) => (
                <div
                  key={kind}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 11,
                  }}
                >
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      width: 18,
                      height: 18,
                      borderRadius: 4,
                      background: `${color}22`,
                      color,
                      borderLeft: `3px solid ${color}`,
                    }}
                  >
                    <Icon size={11} />
                  </span>
                  <Typography.Text style={{ fontSize: 11 }}>
                    {t(`nodeKind.${kind}`)}
                  </Typography.Text>
                  <Typography.Text
                    type="secondary"
                    style={{ fontSize: 10, marginLeft: "auto" }}
                  >
                    {t(`legend.kindHint.${kind}`)}
                  </Typography.Text>
                </div>
              ))}
            </div>
          </div>

          <div>
            <Typography.Text
              type="secondary"
              style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 }}
            >
              {t("legend.edges")}
            </Typography.Text>
            <div style={{ marginTop: 4, display: "grid", gap: 3 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11 }}>
                <svg width="28" height="8" style={{ flexShrink: 0 }}>
                  <line x1="0" y1="4" x2="28" y2="4" stroke="#58a6ff" strokeWidth="2" />
                </svg>
                <Typography.Text style={{ fontSize: 11 }}>
                  {t("legend.edgeSequential")}
                </Typography.Text>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11 }}>
                <svg width="28" height="8" style={{ flexShrink: 0 }}>
                  <line
                    x1="0"
                    y1="4"
                    x2="28"
                    y2="4"
                    stroke="#a371f7"
                    strokeWidth="2.2"
                    strokeDasharray="4,3"
                  />
                </svg>
                <Typography.Text style={{ fontSize: 11 }}>
                  {t("legend.edgeFork")}
                </Typography.Text>
              </div>
            </div>
          </div>

          {showLanes && (
            <div>
              <Typography.Text
                type="secondary"
                style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 }}
              >
                {t("legend.lanes")}
              </Typography.Text>
              <Typography.Paragraph
                style={{ margin: "4px 0 0", fontSize: 11, color: "var(--chr-text-secondary)" }}
              >
                {t("legend.lanesBody")}
              </Typography.Paragraph>
            </div>
          )}

          {showDiff && (
            <div>
              <Typography.Text
                type="secondary"
                style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 }}
              >
                {t("legend.diff")}
              </Typography.Text>
              <div style={{ marginTop: 4, display: "grid", gap: 4 }}>
                {[
                  { tag: "same", color: "#8b949e" },
                  { tag: "changed", color: "#d29922" },
                  { tag: "added", color: "#3fb950" },
                  { tag: "missing", color: "#f85149" },
                ].map(({ tag, color }) => (
                  <div
                    key={tag}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      fontSize: 11,
                    }}
                  >
                    <span
                      style={{
                        display: "inline-block",
                        width: 14,
                        height: 14,
                        borderRadius: 3,
                        background: `${color}33`,
                        border: `1.5px solid ${color}`,
                        flexShrink: 0,
                      }}
                    />
                    <Typography.Text style={{ fontSize: 11 }}>
                      {t(`legend.diffTag.${tag}`)}
                    </Typography.Text>
                    <Typography.Text
                      type="secondary"
                      style={{ fontSize: 10, marginLeft: "auto" }}
                    >
                      {t(`legend.diffHint.${tag}`)}
                    </Typography.Text>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Space>
      )}
    </Card>
  );
}
