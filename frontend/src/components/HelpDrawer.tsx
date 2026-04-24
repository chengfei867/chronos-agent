// Help center — full-height Drawer with concept cards + FAQ collapse.
// Designed so non-technical readers can answer "what the hell is a Node?".
import { Drawer, Typography, Collapse, Card, Space, Tag, Divider, Alert } from "antd";
import {
  BranchesOutlined,
  CodeOutlined,
  DollarOutlined,
  ExperimentOutlined,
  NodeIndexOutlined,
  PlayCircleOutlined,
  MessageOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";

const { Title, Paragraph, Text } = Typography;

const CONCEPT_ORDER = [
  { key: "run", icon: <PlayCircleOutlined /> },
  { key: "node", icon: <NodeIndexOutlined /> },
  { key: "fork", icon: <BranchesOutlined /> },
  { key: "adapter", icon: <ExperimentOutlined /> },
  { key: "usage", icon: <DollarOutlined /> },
  { key: "thread", icon: <MessageOutlined /> },
] as const;

export default function HelpDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();

  return (
    <Drawer
      title={<Title level={4} style={{ margin: 0 }}>{t("help.title")}</Title>}
      open={open}
      onClose={onClose}
      width={560}
      placement="right"
      destroyOnHidden
      className="chr-help-drawer"
    >
      <Alert
        type="info"
        showIcon
        message={t("help.intro")}
        style={{ marginBottom: 20, background: "transparent" }}
      />

      <Title level={5}>{t("help.sections.whatIs")}</Title>
      <Paragraph>{t("help.whatIs.p1")}</Paragraph>
      <Paragraph>{t("help.whatIs.p2")}</Paragraph>

      <Divider />

      <Title level={5}>{t("help.sections.concepts")}</Title>
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        {CONCEPT_ORDER.map(({ key, icon }) => (
          <Card key={key} size="small" className="chr-concept-card">
            <Space align="start" size={12}>
              <span className="chr-concept-icon" aria-hidden>{icon}</span>
              <div>
                <Text strong>{t(`help.concepts.${key}.title`)}</Text>
                <Paragraph style={{ margin: "4px 0 0", color: "var(--chr-text-secondary)" }}>
                  {t(`help.concepts.${key}.body`)}
                </Paragraph>
              </div>
            </Space>
          </Card>
        ))}
      </Space>

      <Divider />

      <Title level={5}>{t("help.sections.howToUse")}</Title>
      <Space direction="vertical" size={6} style={{ width: "100%" }}>
        {[1, 2, 3, 4].map((i) => (
          <Paragraph key={i} style={{ margin: 0 }}>
            {t(`help.howToUse.p${i}`)}
          </Paragraph>
        ))}
      </Space>

      <Divider />

      <Title level={5}>{t("help.sections.faq")}</Title>
      <Collapse
        accordion
        items={[1, 2, 3, 4].map((i) => ({
          key: String(i),
          label: t(`help.faq.q${i}.q`),
          children: <Paragraph style={{ margin: 0 }}>{t(`help.faq.q${i}.a`)}</Paragraph>,
        }))}
      />

      <Divider />

      <Space size={6} wrap>
        <Tag icon={<CodeOutlined />}>LangGraph</Tag>
        <Tag icon={<CodeOutlined />}>Linear</Tag>
        <Tag icon={<CodeOutlined />}>AutoGen</Tag>
      </Space>
    </Drawer>
  );
}
