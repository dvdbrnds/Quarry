import { Routes, Route, NavLink, Navigate, useLocation, useNavigate } from "react-router-dom";
import Permits from "./pages/Permits";
import Lots from "./pages/Lots";
import Dashboard from "./pages/Dashboard";
import Tickets from "./pages/Tickets";
import Pay from "./pages/Pay";
import PaySuccess from "./pages/PaySuccess";
import BuyPermit from "./pages/BuyPermit";
import BuyPermitSuccess from "./pages/BuyPermitSuccess";
import PermitRenew from "./pages/PermitRenew";
import VisitorPortal from "./pages/VisitorPortal";
import VisitorApproval from "./pages/VisitorApproval";
import NotificationPreferences from "./pages/NotificationPreferences";
import Finance from "./pages/Finance";
import OperationsCalendar from "./pages/OperationsCalendar";
import Settings from "./pages/Settings";
import Alerts from "./pages/Alerts";
import AlertSubscribe from "./pages/AlertSubscribe";
import AlertUnsubscribe from "./pages/AlertUnsubscribe";
import SignagePlayer from "./pages/SignagePlayer";
import PermitDetail from "./pages/PermitDetail";
import StudentPermits from "./pages/StudentPermits";
import StaffPermits from "./pages/StaffPermits";
import LotteryApplyV2 from "./pages/LotteryApplyV2";
import ParkingMap from "./pages/ParkingMap";
import Appeals from "./pages/Appeals";
import VehicleApproval from "./pages/VehicleApproval";
import AuthCallback from "./pages/AuthCallback";
import AuthGuard from "./components/AuthGuard";
import { logout, isAuthenticated, fetchCurrentUser, initAuth, isOfficeRole, isAdminRole } from "./auth";
import type { AuthUser } from "./auth";
import { UserContext } from "./UserContext";
import { useBranding } from "./useBranding";
import BrandMark from "./components/BrandMark";
import { useState, useEffect, useRef } from "react";

function RootRedirect() {
  const navigate = useNavigate();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    initAuth()
      .then(() => isAuthenticated())
      .then(async (authed) => {
        if (!authed) {
          navigate("/parking", { replace: true });
          return;
        }
        const user = await fetchCurrentUser();
        if (isOfficeRole(user?.role)) {
          navigate("/dashboard", { replace: true });
        } else if (user?.role === "staff") {
          navigate("/employee-parking", { replace: true });
        } else {
          navigate("/parking", { replace: true });
        }
      })
      .catch(() => navigate("/parking", { replace: true }))
      .finally(() => setChecking(false));
  }, [navigate]);

  if (checking) return null;
  return null;
}

function NavItem({ to, children }: { to: string; children: React.ReactNode }) {
  const brand = useBranding();
  return (
    <NavLink
      to={to}
      style={({ isActive }) =>
        isActive ? { background: brand.accentColor, color: brand.primaryColor } : {}
      }
      className={({ isActive }) =>
        `px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
          isActive ? "" : "text-bone hover:bg-white/10"
        }`
      }
    >
      {children}
    </NavLink>
  );
}

function AdminShell({ user }: { user: AuthUser }) {
  const brand = useBranding();
  const [menuOpen, setMenuOpen] = useState(false);
  const [impersonateInput, setImpersonateInput] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onPointerDown(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  function handleImpersonate() {
    const email = impersonateInput.trim();
    if (!email) return;
    window.open(`/parking?impersonate=${encodeURIComponent(email)}`, "_blank");
  }

  const displayName = user.email?.split("@")[0] || user.email || "Account";

  return (
    <div className="min-h-screen">
      <nav style={{ background: brand.primaryColor }} className="text-bone shadow-md">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center gap-1">
        <div className="flex items-center gap-2 mr-3 shrink-0">
          <BrandMark />
          {brand.brandName && (
            <h1 style={{ color: brand.accentColor }} className="text-lg font-bold tracking-wide">
              {brand.brandName}
            </h1>
          )}
        </div>
        <NavItem to="/dashboard">Dashboard</NavItem>
        <NavItem to="/permits">Permits</NavItem>
        <NavItem to="/tickets">Tickets</NavItem>
        <NavItem to="/lots">Lots</NavItem>
        <NavItem to="/calendar">Calendar</NavItem>
        {isAdminRole(user.role) && <NavItem to="/finance">Finance</NavItem>}
        {isAdminRole(user.role) && <NavItem to="/alerts">Alerts</NavItem>}
        <NavItem to="/settings">Settings</NavItem>

        <div className="ml-auto flex items-center gap-2">
          <div className="flex items-center gap-1">
            <input
              type="email"
              placeholder="View as user..."
              value={impersonateInput}
              onChange={(e) => setImpersonateInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleImpersonate(); }}
              aria-label="View as user"
              className="text-xs px-2 py-1 rounded-md w-40 bg-white/10 border border-white/20 text-bone placeholder-bone/40 focus:outline-none focus:border-white/50"
            />
            <button
              type="button"
              onClick={handleImpersonate}
              disabled={!impersonateInput.trim()}
              className="text-xs px-2 py-1 rounded-md font-medium transition-colors disabled:opacity-30"
              style={{ background: `${brand.accentColor}22`, color: brand.accentColor, border: `1px solid ${brand.accentColor}44` }}
            >
              Go
            </button>
          </div>

          <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((o) => !o)}
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            className="flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg hover:bg-white/10 transition-colors"
          >
            <span className="text-bone/90 max-w-[10rem] truncate">{displayName}</span>
            <span
              style={{ background: `${brand.accentColor}33`, color: brand.accentColor }}
              className="text-[10px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wide"
            >
              {user.role}
            </span>
            <svg className={`w-3.5 h-3.5 text-bone/50 transition-transform ${menuOpen ? "rotate-180" : ""}`} viewBox="0 0 20 20" fill="currentColor" aria-hidden>
              <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
            </svg>
          </button>

          {menuOpen && (
            <div
              role="menu"
              className="absolute right-0 top-full mt-2 w-72 rounded-lg bg-white text-slate-800 shadow-xl border border-slate-200 z-50 overflow-hidden"
            >
              <div className="px-4 py-3 border-b border-slate-100">
                <div className="text-sm font-medium truncate">{user.email}</div>
                <div className="text-[10px] uppercase tracking-wide text-slate-400 mt-0.5">{user.role}</div>
              </div>

              <div className="py-1">
                <a
                  href="/visitor"
                  target="_blank"
                  rel="noopener noreferrer"
                  role="menuitem"
                  className="block px-4 py-2 text-sm hover:bg-slate-50"
                  onClick={() => setMenuOpen(false)}
                >
                  Visitor Portal
                </a>
                <a
                  href="/employee-parking"
                  target="_blank"
                  rel="noopener noreferrer"
                  role="menuitem"
                  className="block px-4 py-2 text-sm hover:bg-slate-50"
                  onClick={() => setMenuOpen(false)}
                >
                  My Permit
                </a>
                <a
                  href="/docs/staff-manual.pdf"
                  target="_blank"
                  rel="noopener noreferrer"
                  role="menuitem"
                  className="flex items-center gap-2 px-4 py-2 text-sm hover:bg-slate-50"
                  onClick={() => setMenuOpen(false)}
                >
                  <svg className="w-4 h-4 text-slate-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                    <path d="M10.75 16.82A7.462 7.462 0 0115 15.5c.71 0 1.396.098 2.046.282A.75.75 0 0018 15.06V4.44a.75.75 0 00-.546-.721A9.006 9.006 0 0015 3.5a9.006 9.006 0 00-4.25 1.065v12.255zM9.25 4.565A9.006 9.006 0 005 3.5a9.006 9.006 0 00-2.454.219A.75.75 0 002 4.44v10.62a.75.75 0 00.954.721A7.462 7.462 0 015 15.5c1.579 0 3.042.487 4.25 1.32V4.565z" />
                  </svg>
                  Staff Manual
                </a>
              </div>

              <div className="border-t border-slate-100 py-1">
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => logout()}
                  className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50"
                >
                  Sign out
                </button>
              </div>
            </div>
          )}
          </div>
        </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-6 py-8">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/permits" element={<Permits />} />
          <Route path="/lots" element={<Lots />} />
          <Route path="/calendar" element={<OperationsCalendar />} />
          <Route path="/tickets" element={<Tickets />} />
          <Route path="/finance" element={isAdminRole(user.role) ? <Finance /> : <Navigate to="/dashboard" replace />} />
          <Route path="/alerts" element={isAdminRole(user.role) ? <Alerts /> : <Navigate to="/dashboard" replace />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/permits/:id" element={<PermitDetail />} />
          <Route path="/student/permits" element={<StudentPermits />} />
        </Routes>
      </main>
    </div>
  );
}

function StudentShell({ user }: { user: AuthUser }) {
  const brand = useBranding();
  return (
    <div className="min-h-screen">
      <nav style={{ background: brand.primaryColor }} className="text-bone shadow-md">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center gap-6">
        <div className="flex items-center gap-2 mr-4">
          <BrandMark />
          {brand.brandName && (
            <h1 style={{ color: brand.accentColor }} className="text-lg font-bold tracking-wide">
              {brand.brandName}
            </h1>
          )}
        </div>
        <NavItem to="/student/permits">My Permits</NavItem>

        <div className="ml-auto flex items-center gap-3">
          <span className="text-xs text-bone/70">{user.email}</span>
          <button
            onClick={() => logout()}
            className="text-xs text-bone/50 hover:text-bone transition-colors"
          >
            Sign out
          </button>
        </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-6 py-8">
        <Routes>
          <Route path="/" element={<Navigate to="/student/permits" replace />} />
          <Route path="/student/permits" element={<StudentPermits />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  const location = useLocation();
  const isPayRoute = location.pathname.startsWith("/pay");
  const isBuyPermitRoute = location.pathname.startsWith("/permits/buy");
  const isRenewRoute = location.pathname.startsWith("/permits/renew");
  const isNotificationsRoute = location.pathname.startsWith("/notifications/");
  const isAlertSubscribeRoute = location.pathname.startsWith("/alerts/subscribe") || location.pathname.startsWith("/alerts/unsubscribe");
  const isSignageRoute = location.pathname.startsWith("/signage/player");
  const isLotteryRoute = location.pathname === "/parking" || location.pathname === "/parking/lottery-v2";
  const isEmployeeParkingRoute = location.pathname === "/employee-parking";
  const isParkingMapRoute = location.pathname === "/parking-map";
  const isVisitorRoute = location.pathname.startsWith("/visitor");
  const isAppealsRoute = location.pathname === "/appeals";
  const isVehicleApproveRoute = location.pathname.startsWith("/vehicle-approve");
  const isRootRoute = location.pathname === "/";
  const isAuthCallback = location.pathname === "/auth/callback";

  if (isAuthCallback) {
    return (
      <Routes>
        <Route path="/auth/callback" element={<AuthCallback />} />
      </Routes>
    );
  }

  if (isPayRoute) {
    return (
      <Routes>
        <Route path="/pay" element={<Pay />} />
        <Route path="/pay/success" element={<PaySuccess />} />
        <Route path="/pay/:ticketId" element={<Pay />} />
      </Routes>
    );
  }

  if (isBuyPermitRoute) {
    return (
      <Routes>
        <Route path="/permits/buy" element={<BuyPermit />} />
        <Route path="/permits/buy/success" element={<BuyPermitSuccess />} />
      </Routes>
    );
  }

  if (isRenewRoute) {
    return (
      <Routes>
        <Route path="/permits/renew/:token" element={<PermitRenew />} />
      </Routes>
    );
  }

  if (isNotificationsRoute) {
    return (
      <Routes>
        <Route path="/notifications/:token" element={<NotificationPreferences />} />
      </Routes>
    );
  }

  if (isAlertSubscribeRoute) {
    return (
      <Routes>
        <Route path="/alerts/subscribe" element={<AlertSubscribe />} />
        <Route path="/alerts/unsubscribe/:token" element={<AlertUnsubscribe />} />
      </Routes>
    );
  }

  if (isSignageRoute) {
    return (
      <Routes>
        <Route path="/signage/player/:screenId" element={<SignagePlayer />} />
      </Routes>
    );
  }

  if (isLotteryRoute) {
    return (
      <Routes>
        <Route path="/parking" element={<LotteryApplyV2 />} />
        <Route path="/parking/lottery-v2" element={<Navigate to="/parking" replace />} />
      </Routes>
    );
  }

  if (isEmployeeParkingRoute) {
    return (
      <Routes>
        <Route path="/employee-parking" element={<StaffPermits />} />
      </Routes>
    );
  }

  if (isParkingMapRoute) {
    return (
      <Routes>
        <Route path="/parking-map" element={<ParkingMap />} />
      </Routes>
    );
  }

  if (isVisitorRoute) {
    return (
      <Routes>
        <Route path="/visitor" element={<VisitorPortal />} />
        <Route path="/visitor/approve/:token" element={<VisitorApproval />} />
        <Route path="/visitor/:slug" element={<VisitorPortal />} />
      </Routes>
    );
  }

  if (isAppealsRoute) {
    return (
      <Routes>
        <Route path="/appeals" element={<Appeals />} />
      </Routes>
    );
  }

  if (isVehicleApproveRoute) {
    return (
      <Routes>
        <Route path="/vehicle-approve/:token" element={<VehicleApproval />} />
      </Routes>
    );
  }

  if (isRootRoute) {
    return <RootRedirect />;
  }

  return (
    <AuthGuard>
      {(user) => (
        <UserContext.Provider value={user}>
          {isOfficeRole(user.role) ? (
            <AdminShell user={user} />
          ) : user.role === "staff" ? (
            <Navigate to="/employee-parking" replace />
          ) : (
            <StudentShell user={user} />
          )}
        </UserContext.Provider>
      )}
    </AuthGuard>
  );
}
