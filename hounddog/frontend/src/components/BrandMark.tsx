import { useBranding } from "../useBranding";

const FALLBACK_ON_DARK = "/quarry-logo-light.png";
const FALLBACK_ON_LIGHT = "/quarry-logo.png";

/**
 * Always renders the campus/product logo.
 * Uses uploaded branding when available; otherwise the built-in Quarry mark.
 */
export default function BrandMark({
  className = "h-8 w-auto",
  variant = "onDark",
}: {
  className?: string;
  /** onDark = nav bars (navy). onLight = white/light cards. */
  variant?: "onDark" | "onLight";
}) {
  const brand = useBranding();
  const uploaded = brand.logoUrl && brand.logoUrl.startsWith("/api/branding/");
  const fallback = variant === "onDark" ? FALLBACK_ON_DARK : FALLBACK_ON_LIGHT;
  const src = uploaded ? brand.logoUrl! : (brand.logoUrl || fallback);
  // Built-in marks are white-on-black; screen blend punches out black on navy navs.
  const blend = !uploaded && variant === "onDark" ? "mix-blend-screen" : "";

  return (
    <img
      src={src}
      alt={brand.brandName || brand.schoolName || "Moravian Parking"}
      className={`${className} ${blend} shrink-0`.trim()}
      onError={(e) => {
        const el = e.currentTarget;
        if (el.dataset.fallback === "1") return;
        el.dataset.fallback = "1";
        el.src = fallback;
        if (variant === "onDark") el.classList.add("mix-blend-screen");
      }}
    />
  );
}
