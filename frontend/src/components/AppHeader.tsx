// Top bar: logo + nav + language switcher + theme toggle + help button.
import { useContext } from "react";
import { Layout, Space, Button, Dropdown, Typography, Tooltip } from "antd";
import {
  QuestionCircleOutlined,
  GithubOutlined,
  ApiOutlined,
  GlobalOutlined,
  BulbOutlined,
  BulbFilled,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { ThemeContext } from "../theme";

type RouteName = "landing" | "runs" | "tree" | "diff";

export default function AppHeader({
  currentRoute,
  onHelpClick,
}: {
  currentRoute: RouteName;
  onHelpClick: () => void;
}) {
  const { t, i18n } = useTranslation();
  const { mode, setMode } = useContext(ThemeContext);

  const goHome = () => {
    window.location.hash = "#/home";
  };
  const goRuns = () => {
    window.location.hash = "#/";
  };

  const setLang = (lng: "zh" | "en") => {
    void i18n.changeLanguage(lng);
  };

  return (
    <Layout.Header className="chr-header">
      <div
        className="chr-brand"
        onClick={goHome}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") goHome();
        }}
      >
        <span className="chr-logo-mark" aria-hidden>🕰️</span>
        <div className="chr-brand-text">
          <Typography.Text strong className="chr-brand-name">
            {t("app.name")}
          </Typography.Text>
          <Typography.Text type="secondary" className="chr-brand-tag">
            {t("app.tagline")}
          </Typography.Text>
        </div>
      </div>

      <Space size="small" wrap>
        <Button
          type={currentRoute === "runs" || currentRoute === "tree" || currentRoute === "diff" ? "primary" : "text"}
          ghost={currentRoute === "runs" || currentRoute === "tree" || currentRoute === "diff"}
          onClick={goRuns}
          id="tour-anchor-runs"
        >
          {t("app.nav.runs")}
        </Button>

        <Tooltip title={t("app.nav.help")}>
          <Button
            icon={<QuestionCircleOutlined />}
            type="text"
            onClick={onHelpClick}
            id="tour-anchor-help"
            aria-label={t("app.nav.help")}
          />
        </Tooltip>

        <Dropdown
          menu={{
            items: [
              { key: "zh", label: "中文" },
              { key: "en", label: "English" },
            ],
            onClick: ({ key }) => setLang(key as "zh" | "en"),
            selectedKeys: [i18n.language?.startsWith("en") ? "en" : "zh"],
          }}
          placement="bottomRight"
        >
          <Tooltip title={t("common.lang")}>
            <Button
              icon={<GlobalOutlined />}
              type="text"
              id="tour-anchor-lang"
              aria-label={t("common.lang")}
            >
              {i18n.language?.startsWith("en") ? "EN" : "中"}
            </Button>
          </Tooltip>
        </Dropdown>

        <Tooltip title={t("common.theme")}>
          <Button
            icon={mode === "dark" ? <BulbOutlined /> : <BulbFilled />}
            type="text"
            onClick={() => setMode(mode === "dark" ? "light" : "dark")}
            aria-label={t("common.theme")}
          />
        </Tooltip>

        <Tooltip title={t("app.nav.api")}>
          <Button
            icon={<ApiOutlined />}
            type="text"
            href="/docs"
            target="_blank"
            aria-label={t("app.nav.api")}
          />
        </Tooltip>

        <Tooltip title={t("app.nav.github")}>
          <Button
            icon={<GithubOutlined />}
            type="text"
            href="https://github.com/chengfei867/chronos-agent"
            target="_blank"
            rel="noopener noreferrer"
            aria-label={t("app.nav.github")}
          />
        </Tooltip>
      </Space>
    </Layout.Header>
  );
}
