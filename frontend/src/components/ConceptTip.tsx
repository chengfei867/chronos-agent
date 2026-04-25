// Inline concept tip — wraps jargon words (Node / Fork / Adapter…) with
// a Popover that shows the short help text. Keep it lightweight so it can be
// sprinkled anywhere without hurting readability.
import React from "react";
import { Popover, Typography } from "antd";
import { InfoCircleOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

export type ConceptKey =
  | "run"
  | "node"
  | "fork"
  | "adapter"
  | "usage"
  | "thread"
  | "step"
  | "framework"
  | "timeline"
  | "effects";

export default function ConceptTip({
  concept,
  children,
  asIcon = false,
}: {
  concept: ConceptKey;
  children?: React.ReactNode;
  asIcon?: boolean;
}) {
  const { t } = useTranslation();

  const content = (
    <div style={{ maxWidth: 280 }}>
      <Typography.Text strong>{t(`help.concepts.${concept}.title`)}</Typography.Text>
      <Typography.Paragraph style={{ margin: "4px 0 0", color: "var(--chr-text-secondary)" }}>
        {t(`help.concepts.${concept}.body`)}
      </Typography.Paragraph>
    </div>
  );

  return (
    <Popover
      content={content}
      trigger={["hover", "focus"]}
      placement="top"
      mouseEnterDelay={0.1}
    >
      <span className="chr-concept-tip" tabIndex={0} role="button">
        {children ?? t(`help.concepts.${concept}.title`)}
        {asIcon && <InfoCircleOutlined style={{ marginLeft: 4, fontSize: 12 }} />}
      </span>
    </Popover>
  );
}
