import { Link, useLocation } from "react-router-dom";
import { useBranding } from "../useBranding";
import BrandMark from "./BrandMark";

const PUBLIC_LINKS = [
  { to: "/parking", label: "Students" },
  { to: "/visitor", label: "Visitors" },
  { to: "/employee-parking", label: "Employees" },
  { to: "/appeals", label: "Appeals" },
  { to: "/parking-map", label: "Map" },
] as const;

export default function PublicPageNav({ subtitle, hideLinks }: { subtitle: string; hideLinks?: boolean }) {
  const brand = useBranding();
  const location = useLocation();

  return (
    <>
      {brand.announcementText && (
        <div
          style={{ background: brand.accentColor, color: brand.primaryColor }}
          className="px-6 py-2.5 text-center text-sm font-medium"
        >
          {brand.announcementUrl ? (
            <a
              href={brand.announcementUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 font-semibold"
              style={{ color: brand.primaryColor }}
            >
              {brand.announcementText}
            </a>
          ) : (
            brand.announcementText
          )}
        </div>
      )}
      <nav
        style={{ background: brand.primaryColor }}
        className="px-6 py-4 shadow-md"
      >
        <div className="max-w-4xl mx-auto flex items-center gap-3 flex-wrap">
          <Link to="/visitor" className="flex items-center gap-3 no-underline">
            <BrandMark />
            {(brand.brandName || brand.schoolName) && (
              <h1
                style={{ color: brand.accentColor }}
                className="text-lg font-bold tracking-wide m-0"
              >
                {brand.brandName || brand.schoolName}
              </h1>
            )}
          </Link>
          <span className="text-sm text-white/60 ml-1">{subtitle}</span>
          {!hideLinks && <div className="ml-auto flex items-center gap-1 sm:gap-2">
            {PUBLIC_LINKS.map((link) => {
              const active =
                link.to === "/visitor"
                  ? location.pathname.startsWith("/visitor")
                  : location.pathname === link.to;
              return (
                <Link
                  key={link.to}
                  to={link.to}
                  className={`text-xs sm:text-sm px-2.5 py-1 rounded-md transition-colors no-underline ${
                    active ? "font-semibold" : "text-white/70 hover:text-white hover:bg-white/10"
                  }`}
                  style={
                    active
                      ? { background: brand.accentColor, color: brand.primaryColor }
                      : undefined
                  }
                >
                  {link.label}
                </Link>
              );
            })}
          </div>}
        </div>
      </nav>
    </>
  );
}
