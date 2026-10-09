import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useBranding } from "../useBranding";
import { authHeadersAs, getImpersonateEmail, clearImpersonation } from "../auth";
import BrandMark from "./BrandMark";

const PUBLIC_LINKS = [
  { to: "/parking", label: "Permits" },
  { to: "/visitor", label: "Visitors" },
  { to: "/employee-parking", label: "Employees" },
  { to: "/citations", label: "Citations" },
  { to: "/pay", label: "Pay" },
  { to: "/parking-map", label: "Map" },
] as const;

function useUnpaidTicketCount(): number {
  const [count, setCount] = useState(0);
  useEffect(() => {
    (async () => {
      try {
        const headers = await authHeadersAs(getImpersonateEmail());
        if (!headers.Authorization) return;
        const res = await fetch("/api/payments/my-tickets", { headers });
        if (res.ok) setCount((await res.json()).length);
      } catch {}
    })();
  }, []);
  return count;
}

export default function PublicPageNav({ subtitle, hideLinks }: { subtitle: string; hideLinks?: boolean }) {
  const brand = useBranding();
  const location = useLocation();
  const unpaidCount = useUnpaidTicketCount();
  const isPayPage = location.pathname.startsWith("/pay");
  const impersonateEmail = getImpersonateEmail();

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
        <div className={`max-w-4xl mx-auto flex items-center gap-3 flex-wrap ${hideLinks ? "justify-center" : ""}`}>
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
          <span style={{ color: "rgba(255,255,255,0.6)" }} className="text-sm">{subtitle}</span>
          {!hideLinks && <div className="ml-auto flex items-center gap-1 sm:gap-2">
            {PUBLIC_LINKS.map((link) => {
              const active =
                link.to === "/visitor"
                  ? location.pathname.startsWith("/visitor")
                  : link.to === "/pay"
                  ? location.pathname.startsWith("/pay")
                  : link.to === "/parking"
                  ? location.pathname === "/parking" || location.pathname.startsWith("/student/permits") || location.pathname.startsWith("/permits/buy")
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
            <a href="/regulations" target="_blank" rel="noopener noreferrer" className="text-xs sm:text-sm px-2.5 py-1 rounded-md no-underline text-white/70 hover:text-white hover:bg-white/10 transition-colors">Regulations</a>
          </div>}
          {hideLinks && <a href="/regulations" target="_blank" rel="noopener noreferrer" className="ml-auto text-xs font-medium px-3 py-1 rounded no-underline" style={{ background: "rgba(255,255,255,0.2)", color: brand.accentColor }}>📋 Parking Regulations</a>}
        </div>
      </nav>
      {impersonateEmail && (
        <div className="bg-amber-50 border-b-2 border-amber-400 px-6 py-2 flex items-center justify-between">
          <span className="text-sm font-semibold text-amber-800">
            Viewing as: {impersonateEmail}
          </span>
          <button
            onClick={() => { clearImpersonation(); window.location.href = "/dashboard"; }}
            className="text-xs font-medium text-amber-700 bg-amber-200 hover:bg-amber-300 px-3 py-1 rounded transition-colors"
          >
            Exit Impersonation
          </button>
        </div>
      )}
      {unpaidCount > 0 && !isPayPage && (
        <a href="/pay" className="block no-underline">
          <div className="bg-red-50 border-b border-red-200 px-6 py-3 flex items-center justify-center gap-3 hover:bg-red-100 transition-colors">
            <span className="text-sm font-semibold text-red-800">
              You have {unpaidCount} unpaid citation{unpaidCount !== 1 ? "s" : ""} — academic holds may apply and can take up to 4 hours to update after payment.
            </span>
            <span className="text-xs font-medium text-red-700 bg-red-200 px-2 py-0.5 rounded whitespace-nowrap">Pay Now →</span>
          </div>
        </a>
      )}
    </>
  );
}
