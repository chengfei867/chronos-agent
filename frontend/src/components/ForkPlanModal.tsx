// ForkPlanModal — R46-A
//
// Displays the fork plan artifact + downstream side-effects summary for
// a selected node. Per ADR-013, Chronos does NOT execute forks from the
// viewer; the UX here is:
//
//   1. User clicks "Fork from here" on a node.
//   2. This modal shows what `chronos fork plan <run> --at-node <step>`
//      would produce — a JSON artifact describing the fork's parent /
//      thread / overrides envelope, plus a summary of which downstream
//      nodes would re-run (and how many carry dangerous side-effects).
//   3. User downloads the JSON (or copies it), edits the overrides block
//      in their editor, then runs `chronos fork apply <plan.json>` from
//      the CLI. Chronos is out of the execution loop (ADR-013).
//
// Design choices:
// - Modal, not Drawer — the plan JSON is a deliverable the user wants
//   to see front-and-center, not a side panel that competes with the
//   node viewer.
// - Effects summary stays at the top because the dangerous-count is
//   the whole reason we added the preview — "you're about to burn money /
//   hit prod" needs to land before the JSON block.
// - No in-modal editing of overrides. That was considered and rejected
//   in ADR-019 (no-sandbox): any editor we ship would invite users to
//   assume Chronos runs the fork, which it deliberately doesn't.

import { useEffect, useState } from "react";
import { Modal, Space, Tag, Alert, Button, Typography, message } from "antd";
import { Download, Copy, AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  fetchForkPlanPreview,
  type ForkPlanPreviewResponse,
} from "../api";
import ConceptTip from "./ConceptTip";
import { EffectTag } from "./NodeDetails";

const { Paragraph, Text } = Typography;

interface Props {
  runId: string;
  nodeId: string | null; // null ⇒ modal closed
  nodeName: string | null;
  stepIndex: number | null;
  onClose: () => void;
}

export default function ForkPlanModal({
  runId,
  nodeId,
  nodeName,
  stepIndex,
  onClose,
}: Props) {
  const { t } = useTranslation();
  const [data, setData] = useState<ForkPlanPreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msgApi, msgHolder] = message.useMessage();

  useEffect(() => {
    if (!nodeId) {
      setData(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    fetchForkPlanPreview(runId, nodeId)
      .then((resp) => {
        if (!cancelled) setData(resp);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, nodeId]);

  const planJson = data ? JSON.stringify(data.plan, null, 2) : "";

  const handleDownload = () => {
    if (!data) return;
    const blob = new Blob([planJson], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    // Filename: fork-plan-<runIdPrefix>-step<N>.json — short and searchable.
    const runShort = runId.slice(0, 8);
    a.download = `fork-plan-${runShort}-step${stepIndex ?? "x"}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    msgApi.success(t("forkModal.downloaded"));
  };

  const handleCopy = async () => {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(planJson);
      msgApi.success(t("forkModal.copied"));
    } catch {
      msgApi.error(t("forkModal.copyFailed"));
    }
  };

  const summary = data?.effects_summary;
  const dangerous = summary && summary.dangerous_count > 0;

  return (
    <Modal
      open={nodeId !== null}
      onCancel={onClose}
      title={
        <Space>
          <span>{t("forkModal.title")}</span>
          {nodeName !== null && stepIndex !== null && (
            <Tag color="geekblue">
              {t("forkModal.atNode", { step: stepIndex, name: nodeName })}
            </Tag>
          )}
          <ConceptTip concept="fork" asIcon />
        </Space>
      }
      width={760}
      footer={[
        <Button key="close" onClick={onClose}>
          {t("forkModal.close")}
        </Button>,
        <Button
          key="copy"
          icon={<Copy size={14} />}
          onClick={handleCopy}
          disabled={!data}
        >
          {t("forkModal.copy")}
        </Button>,
        <Button
          key="download"
          type="primary"
          icon={<Download size={14} />}
          onClick={handleDownload}
          disabled={!data}
        >
          {t("forkModal.download")}
        </Button>,
      ]}
      destroyOnHidden
    >
      {msgHolder}

      <Paragraph type="secondary" style={{ marginTop: 0 }}>
        {t("forkModal.intro")}
      </Paragraph>

      {loading && <Paragraph>{t("forkModal.loading")}</Paragraph>}

      {error && (
        <Alert
          type="error"
          showIcon
          message={t("forkModal.errorTitle")}
          description={error}
        />
      )}

      {data && summary && (
        <>
          {dangerous ? (
            <Alert
              type="warning"
              showIcon
              icon={<AlertTriangle size={16} />}
              style={{ marginBottom: 12 }}
              message={t("forkModal.dangerous.title", {
                count: summary.dangerous_count,
                total: summary.total,
              })}
              description={
                <div>
                  <div style={{ marginBottom: 6 }}>
                    {t("forkModal.dangerous.breakdown")}:
                    <Space size={4} wrap style={{ marginLeft: 6 }}>
                      {Object.entries(summary.tag_counts).map(([tag, n]) => (
                        <EffectTag key={tag} tag={tag} label={`${tag}:${n}`} />
                      ))}
                    </Space>
                  </div>
                  {summary.dangerous_samples.length > 0 && (
                    <div>
                      {t("forkModal.dangerous.examples")}:
                      <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
                        {summary.dangerous_samples.map(([step, name, tags]) => (
                          <li key={step}>
                            <Text code>step {step}</Text> {name}
                            <Space size={2} wrap style={{ marginLeft: 6 }}>
                              {tags.map((tag) => (
                                <EffectTag key={tag} tag={tag} />
                              ))}
                            </Space>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              }
            />
          ) : (
            <Alert
              type="success"
              showIcon
              style={{ marginBottom: 12 }}
              message={
                summary.total === 0
                  ? t("forkModal.safe.lastNode")
                  : t("forkModal.safe.pureLlm", { total: summary.total })
              }
            />
          )}

          <Paragraph strong style={{ marginBottom: 4 }}>
            {t("forkModal.planJson")}
          </Paragraph>
          <pre
            style={{
              background: "#0d1117",
              border: "1px solid #30363d",
              borderRadius: 6,
              padding: 12,
              fontSize: 12,
              maxHeight: 320,
              overflow: "auto",
              color: "#c9d1d9",
              margin: 0,
            }}
          >
            {planJson}
          </pre>

          <Paragraph type="secondary" style={{ marginTop: 12, fontSize: 12 }}>
            {t("forkModal.nextSteps")}
          </Paragraph>
        </>
      )}
    </Modal>
  );
}
