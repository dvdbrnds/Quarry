import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

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
          brandName: data.brand_name || DEFAULTS.brandName,
          primaryColor: data.primary_color || DEFAULTS.primaryColor,
          accentColor: data.accent_color || DEFAULTS.accentColor,
          logoUrl: data.logo_url ?? null,
          faviconUrl: data.favicon_url || DEFAULTS.faviconUrl,
          schoolName: data.school_name || DEFAULTS.schoolName,
        });
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const link: HTMLLinkElement =
      document.querySelector('link[rel="icon"]') || document.createElement("link");
    link.rel = "icon";
    link.type = "image/png";
    link.href = branding.faviconUrl;
    if (!link.parentNode) document.head.appendChild(link);
  }, [branding.faviconUrl]);

  return <BrandingContext.Provider value={branding}>{children}</BrandingContext.Provider>;
}

export function useBranding() {
  return useContext(BrandingContext);
}
