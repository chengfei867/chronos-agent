// R39-A: field-level diff renderer for a single DiffEntry, shown in the
// DiffView drawer. Mirrors the DiffStateDiff shape from the backend:
//   - added_keys: only in B
//   - removed_keys: only in A
//   - changed_keys: in both, value differs (per-key {a, b})
//
// Values are stringified via JSON.stringify with 2-space indent so nested
// objects render readably. Long strings are wrapped (pre-wrap + word-break).
import type React from "react";
import { Typography, Tag, Empty, Divider } from "antd";
import { useTranslation } from "react-i18next";
import type { DiffEntry } from "../types";

const { Text, Paragraph } = Typography;

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        margin: "12px 0 6px",
        paddingBottom: 4,
        borderBottom: "1px solid var(--chr-border)",
        fontSize: 12,
        color: "var(--chr-text-secondary)",
        textTransform: "uppercase",
        letterSpacing: "0.06em",
      }}
    >
      {children}
    </div>
  );
}

function formatValue(v: unknown): string {
  if (v === null) return "null";
  if (v === undefined) return "undefined";
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

function ValueBlock({ label, value, tone }: { label: string; value: unknown; tone: "add" | "remove" | "a" | "b" }) {
  const bg = {
    add: "rgba(63, 185, 80, 0.12)",
    remove: "rgba(248, 81, 73, 0.12)",
    a: "rgba(88, 166, 255, 0.08)",
    b: "rgba(163, 113, 247, 0.1)",
  }[tone];
  const border = {
    add: "rgba(63, 185, 80, 0.35)",
    remove: "rgba(248, 81, 73, 0.35)",
    a: "rgba(88, 166, 255, 0.3)",
    b: "rgba(163, 113, 247, 0.3)",
  }[tone];
  return (
    <div style={{ marginTop: 4 }}>
      <Text type="secondary" style={{ fontSize: 11 }}>{label}</Text>
      <pre
        style={{
          margin: "2px 0 0",
          padding: "6px 10px",
          background: bg,
          border: `1px solid ${border}`,
          borderRadius: 6,
          fontSize: 11,
          fontFamily: "monospace",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          maxHeight: 200,
          overflow: "auto",
        }}
      >
        {formatValue(value)}
      </pre>
    </div>
  );
}

export default function DiffNodeDetails({ entry }: { entry: DiffEntry }) {
  const { t } = useTranslation();
  const { tag, node_name, a, b, state_diff } = entry;

  // Header summary
  const header = (
    <div>
      <Text strong style={{ fontSize: 13 }}>{node_name}</Text>{" "}
      <Tag
        color={
          tag === "equal" ? "default" : tag === "changed" ? "gold" : tag === "added" ? "green" : "volcano"
        }
        bordered={false}
        style={{ marginLeft: 4 }}
      >
        {t(`diff.entries.tag${tag.charAt(0).toUpperCase() + tag.slice(1)}`, { defaultValue: tag })}
      </Tag>
      <Paragraph type="secondary" style={{ fontSize: 12, margin: "4px 0 0" }}>
        {tag === "equal" && t("diff.nodeDetails.hintEqual")}
        {tag === "removed" && t("diff.nodeDetails.hintOnlyA")}
        {tag === "added" && t("diff.nodeDetails.hintOnlyB")}
        {tag === "changed" && t("diff.nodeDetails.hintChanged")}
      </Paragraph>
    </div>
  );

  // Body: depends on tag
  let body: React.ReactNode = null;

  if (tag === "added" && b) {
    body = (
      <div>
        <Text type="secondary" style={{ fontSize: 12 }}>
          B · #{b.step_index} · {b.kind}
        </Text>
        <ValueBlock label="state_after (B)" value={b.state_after} tone="add" />
      </div>
    );
  } else if (tag === "removed" && a) {
    body = (
      <div>
        <Text type="secondary" style={{ fontSize: 12 }}>
          A · #{a.step_index} · {a.kind}
        </Text>
        <ValueBlock label="state_after (A)" value={a.state_after} tone="remove" />
      </div>
    );
  } else if (tag === "changed" && state_diff) {
    const { added_keys, removed_keys, changed_keys } = state_diff;
    const empty =
      added_keys.length === 0 &&
      removed_keys.length === 0 &&
      Object.keys(changed_keys).length === 0;
    if (empty) {
      body = (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("diff.nodeDetails.noStateDiff")}
        />
      );
    } else {
      body = (
        <div>
          {Object.keys(changed_keys).length > 0 && (
            <>
              <SectionTitle>{t("diff.nodeDetails.changedKeys")} ({Object.keys(changed_keys).length})</SectionTitle>
              {Object.entries(changed_keys).map(([k, v]) => (
                <div key={`chg-${k}`} style={{ marginBottom: 10 }}>
                  <Tag color="gold" bordered={false}>{k}</Tag>
                  <ValueBlock label={t("diff.nodeDetails.valueA")} value={v.a} tone="a" />
                  <ValueBlock label={t("diff.nodeDetails.valueB")} value={v.b} tone="b" />
                </div>
              ))}
            </>
          )}
          {added_keys.length > 0 && b && (
            <>
              <SectionTitle>{t("diff.nodeDetails.addedKeys")} ({added_keys.length})</SectionTitle>
              {added_keys.map((k) => (
                <div key={`add-${k}`} style={{ marginBottom: 8 }}>
                  <Tag color="green" bordered={false}>{k}</Tag>
                  <ValueBlock label={t("diff.nodeDetails.valueB")} value={b.state_after[k]} tone="add" />
                </div>
              ))}
            </>
          )}
          {removed_keys.length > 0 && a && (
            <>
              <SectionTitle>{t("diff.nodeDetails.removedKeys")} ({removed_keys.length})</SectionTitle>
              {removed_keys.map((k) => (
                <div key={`rem-${k}`} style={{ marginBottom: 8 }}>
                  <Tag color="volcano" bordered={false}>{k}</Tag>
                  <ValueBlock label={t("diff.nodeDetails.valueA")} value={a.state_after[k]} tone="remove" />
                </div>
              ))}
            </>
          )}
        </div>
      );
    }
  } else if (tag === "equal" && a && b) {
    body = (
      <div>
        <Text type="secondary" style={{ fontSize: 12 }}>
          #{a.step_index} · {a.kind}
        </Text>
        <ValueBlock label="state_after" value={a.state_after} tone="a" />
      </div>
    );
  }

  return (
    <div>
      {header}
      <Divider style={{ margin: "12px 0" }} />
      {body}
    </div>
  );
}
