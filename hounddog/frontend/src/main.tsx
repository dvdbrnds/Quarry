import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ConfigProvider, App as AntApp } from "antd";
import App from "./App";
import { BrandingProvider } from "./useBranding";
import "./index.css";

const theme = {
  token: {
    colorPrimary: "#C5A55A",
    colorError: "#EF4444",
    colorSuccess: "#22C55E",
    colorWarning: "#F59E0B",
    colorInfo: "#0A1628",
    colorBgBase: "#FFFFFF",
    colorTextBase: "#1A1A1A",
    borderRadius: 8,
    fontFamily: "inherit",
  },
  components: {
    Button: {
      colorPrimary: "#C5A55A",
      colorPrimaryHover: "#9B7E35",
      colorPrimaryActive: "#9B7E35",
      algorithm: true,
    },
    Table: {
      headerBg: "#0A1628",
      headerColor: "#F5F0E8",
      headerSortActiveBg: "#162440",
      headerSortHoverBg: "#162440",
      rowHoverBg: "rgba(245,240,232,0.5)",
    },
    Menu: {
      darkItemBg: "#0A1628",
    },
    Tabs: {
      inkBarColor: "#C5A55A",
      itemActiveColor: "#0A1628",
      itemSelectedColor: "#0A1628",
    },
  },
};

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider theme={theme}>
      <AntApp>
        <BrowserRouter>
          <BrandingProvider>
            <App />
          </BrandingProvider>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>
);
