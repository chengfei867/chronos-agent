// Chronos viewer entry — dark-first AntD + i18n + ReactFlow
import { StrictMode, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ConfigProvider, theme as antTheme, App as AntApp } from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import { useTranslation } from "react-i18next";
import "./i18n";
import App from "./App";
import { ThemeContext, type ThemeMode } from "./theme";
import "@xyflow/react/dist/style.css";
import "./styles.css";

function Root() {
  const { i18n } = useTranslation();

  // Theme persisted in localStorage. Default: dark (matches landing page palette).
  const [mode, setMode] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem("chronos.theme") as ThemeMode | null;
    return saved === "light" ? "light" : "dark";
  });

  useEffect(() => {
    localStorage.setItem("chronos.theme", mode);
    document.documentElement.dataset.theme = mode;
  }, [mode]);

  const antdLocale = i18n.language?.startsWith("zh") ? zhCN : enUS;

  const themeConfig = useMemo(
    () => ({
      algorithm: mode === "dark" ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
      token: {
        colorPrimary: "#58a6ff",
        colorInfo: "#58a6ff",
        borderRadius: 8,
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', 'Segoe UI', Roboto, 'Noto Sans', sans-serif",
        ...(mode === "dark"
          ? {
              colorBgBase: "#0d1117",
              colorBgContainer: "#161b22",
              colorBgElevated: "#1c2128",
              colorBorder: "#30363d",
              colorText: "#c9d1d9",
              colorTextSecondary: "#8b949e",
            }
          : {}),
      },
      components: {
        Layout: mode === "dark"
          ? { headerBg: "#0d1117", bodyBg: "#010409", siderBg: "#0d1117" }
          : {},
      },
    }),
    [mode],
  );

  const themeCtx = useMemo(() => ({ mode, setMode }), [mode]);

  return (
    <ConfigProvider locale={antdLocale} theme={themeConfig}>
      <AntApp>
        <ThemeContext.Provider value={themeCtx}>
          <App />
        </ThemeContext.Provider>
      </AntApp>
    </ConfigProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
