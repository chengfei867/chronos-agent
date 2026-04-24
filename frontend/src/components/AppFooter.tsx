// Footer — compact, unobtrusive credit line.
import { Layout, Typography, Space } from "antd";
import { useTranslation } from "react-i18next";

export default function AppFooter() {
  const { t } = useTranslation();
  return (
    <Layout.Footer className="chr-footer">
      <Space split={<span className="chr-footer-split">·</span>}>
        <Typography.Text type="secondary">{t("app.name")}</Typography.Text>
        <Typography.Link href="https://github.com/chengfei867/chronos-agent" target="_blank" rel="noopener noreferrer">
          GitHub
        </Typography.Link>
        <Typography.Link href="/docs" target="_blank">
          {t("app.nav.api")}
        </Typography.Link>
      </Space>
    </Layout.Footer>
  );
}
