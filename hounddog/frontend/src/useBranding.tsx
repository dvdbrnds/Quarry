import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ConfigProvider } from "antd";

export interface Branding {
  brandName: string;
  primaryColor: string;
  accentColor: string;
  logoUrl: string | null;
  faviconUrl: string;
  schoolName: string;
}

const DEFAULTS: Branding = {
  brandName: "Quarry",
  primaryColor: "#1a2744",
  accentColor: "#c9a84c",
  logoUrl: null,
  faviconUrl: "/favicon.png",
  schoolName: "",
};

const BrandingContext = createContext<Branding>(DEFAULTS);

export function BrandingProvider({ children }: { children: ReactNode }) {
  const [branding, setBranding] = useState<Branding>(DEFAULTS);

  useEffect(() => {
    fetch("/api/branding")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data) => {
        setBranding({
          brandName: data.brand_name ?? DEFAULTS.brandName,
          primaryColor: data.primary_color || DEFAULTS.primaryColor,
          accentColor: data.accent_color || DEFAULTS.accentColor,
          logoUrl: data.logo_url ?? null,
          faviconUrl: data.favicon_url || DEFAULTS.faviconUrl,
          schoolName: data.school_name ?? DEFAULTS.schoolName,
        });
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty("--brand-primary", branding.primaryColor);
    root.style.setProperty("--brand-accent", branding.accentColor);
  }, [branding.primaryColor, branding.accentColor]);

  useEffect(() => {
    const link: HTMLLinkElement =
      document.querySelector('link[rel="icon"]') || document.createElement("link");
    link.rel = "icon";
    link.type = "image/png";
    link.href = branding.faviconUrl;
    if (!link.parentNode) document.head.appendChild(link);
  }, [branding.faviconUrl]);

  const theme = useMemo(() => ({
    token: {
      colorPrimary: branding.primaryColor,
      colorError: "#EF4444",
      colorSuccess: "#22C55E",
      colorWarning: "#F59E0B",
      colorInfo: branding.primaryColor,
      colorBgBase: "#FFFFFF",
      colorTextBase: "#1A1A1A",
      borderRadius: 8,
      fontFamily: "inherit",
    },
    components: {
      Button: {
        colorPrimary: branding.primaryColor,
        algorithm: true as const,
      },
      Table: {
        headerBg: branding.primaryColor,
        headerColor: "#FFFFFF",
        headerSortActiveBg: branding.primaryColor,
        headerSortHoverBg: branding.primaryColor,
        rowHoverBg: "rgba(0,0,0,0.03)",
      },
      Menu: {
        darkItemBg: branding.primaryColor,
      },
      Tabs: {
        inkBarColor: branding.primaryColor,
        itemActiveColor: branding.primaryColor,
        itemSelectedColor: branding.primaryColor,
      },
    },
  }), [branding.primaryColor, branding.accentColor]);

  return (
    <BrandingContext.Provider value={branding}>
      <ConfigProvider theme={theme}>
        {children}
      </ConfigProvider>
    </BrandingContext.Provider>
  );
}

export function useBranding() {
  return useContext(BrandingContext);
}
