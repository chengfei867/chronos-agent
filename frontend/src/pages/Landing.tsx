// Landing page — hero + 3-step narrative (record -> browse -> fork) + CTA.
// Narrative-first: visitors (including non-technical readers) should come away
// understanding the core pitch in 10 seconds.
import { Button, Space, Typography, Row, Col, Card, Tag } from "antd";
import { GithubOutlined } from "@ant-design/icons";
import { motion } from "framer-motion";
import {
  Clock,
  Eye,
  GitBranch,
  Sparkles,
  Zap,
  ShieldCheck,
  Database,
} from "lucide-react";
import { useTranslation } from "react-i18next";

const { Title, Paragraph, Text } = Typography;

const STEP_ICONS = {
  record: <Clock size={28} />,
  browse: <Eye size={28} />,
  fork: <GitBranch size={28} />,
} as const;

export default function Landing({
  openHelp,
}: {
  openHelp: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="chr-landing">
      {/* Hero */}
      <motion.section
        className="chr-hero"
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
      >
        <div className="chr-hero-glow" aria-hidden />
        <div className="chr-hero-inner">
          <motion.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.1 }}
          >
            <Tag color="blue" icon={<Sparkles size={12} />} style={{ marginBottom: 16 }}>
              {t("app.tagline")}
            </Tag>
          </motion.div>
          <Title level={1} className="chr-hero-title">
            {t("app.name")} <span className="chr-hero-emoji">🕰️</span>
          </Title>
          <Paragraph className="chr-hero-lead">{t("landing.heroLead")}</Paragraph>
          <Space size="middle" wrap>
            <Button
              type="primary"
              size="large"
              onClick={() => {
                window.location.hash = "#/";
              }}
            >
              {t("landing.heroCTA")}
            </Button>
            <Button
              size="large"
              href="/docs"
              target="_blank"
            >
              {t("landing.heroSecondary")}
            </Button>
            <Button
              size="large"
              type="text"
              icon={<GithubOutlined />}
              href="https://github.com/chengfei867/chronos-agent"
              target="_blank"
              rel="noopener noreferrer"
            >
              GitHub
            </Button>
          </Space>
        </div>
      </motion.section>

      {/* 3 steps */}
      <section className="chr-steps">
        <Row gutter={[24, 24]}>
          {(["record", "browse", "fork"] as const).map((key, idx) => (
            <Col xs={24} md={8} key={key}>
              <motion.div
                initial={{ opacity: 0, y: 24 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-10% 0px" }}
                transition={{ duration: 0.4, delay: 0.1 + idx * 0.12 }}
              >
                <Card className="chr-step-card" hoverable>
                  <div className="chr-step-icon">{STEP_ICONS[key]}</div>
                  <Title level={4} style={{ marginTop: 12 }}>
                    {t(`landing.steps.${key}.title`)}
                  </Title>
                  <Paragraph style={{ color: "var(--chr-text-secondary)", margin: 0 }}>
                    {t(`landing.steps.${key}.desc`)}
                  </Paragraph>
                </Card>
              </motion.div>
            </Col>
          ))}
        </Row>
      </section>

      {/* Feature strip */}
      <section className="chr-features">
        <Row gutter={[16, 16]} align="middle">
          <Col xs={24} md={12}>
            <Space direction="vertical" size={8}>
              <Text strong style={{ fontSize: 16 }}>{t("landing.supports")}</Text>
              <Space wrap>
                <Tag color="geekblue">LangGraph</Tag>
                <Tag color="cyan">Linear</Tag>
                <Tag color="purple">AutoGen</Tag>
              </Space>
            </Space>
          </Col>
          <Col xs={24} md={12}>
            <Space size={16} wrap>
              <Space size={6}><Zap size={14} /><Text type="secondary">Local-first</Text></Space>
              <Space size={6}><ShieldCheck size={14} /><Text type="secondary">No telemetry</Text></Space>
              <Space size={6}><Database size={14} /><Text type="secondary">SQLite</Text></Space>
              <Button size="small" type="link" onClick={openHelp}>
                {t("app.nav.help")} →
              </Button>
            </Space>
          </Col>
        </Row>
      </section>
    </div>
  );
}
