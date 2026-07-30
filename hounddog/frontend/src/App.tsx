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
import LotteryApply from "./pages/LotteryApply";
import LotteryApplyV2 from "./pages/LotteryApplyV2";
import ParkingMap from "./pages/ParkingMap";
import AuthCallback from "./pages/AuthCallback";
import AuthGuard from "./components/AuthGuard";
import { logout, isAuthenticated, fetchCurrentUser, initAuth } from "./auth";
import type { AuthUser } from "./auth";
import { UserContext } from "./UserContext";
import { useBranding } from "./useBranding";
import { useState, useEffect } from "react";

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
        if (user?.role === "admin" || user?.role === "staff") {
          navigate("/dashboard", { replace: true });
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
        `px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
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
  return (
    <div className="min-h-screen">
      <nav style={{ background: brand.primaryColor }} className="text-bone px-6 py-3 flex items-center gap-6 shadow-md">
        <div className="flex items-center gap-2 mr-4">
          {brand.logoUrl && <img src={brand.logoUrl} alt={brand.brandName || "Logo"} className="h-8 w-auto" />}
          {brand.brandName && (
            <h1 style={{ color: brand.accentColor }} className="text-lg font-bold tracking-wide">
              {brand.brandName}
            </h1>
          )}
        </div>
        <NavItem to="/dashboard">Dashboard</NavItem>
        <NavItem to="/permits">Permits</NavItem>
        <NavItem to="/lots">Lots</NavItem>
        <NavItem to="/calendar">Calendar</NavItem>
        <NavItem to="/tickets">Tickets</NavItem>
        <NavItem to="/finance">Finance</NavItem>
        <NavItem to="/alerts">Alerts</NavItem>
        <NavItem to="/settings">Settings</NavItem>

        <div className="ml-auto flex items-center gap-3">
          <a
            href="/employee-parking"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs px-3 py-1 rounded-md font-medium transition-colors"
            style={{ background: `${brand.accentColor}22`, color: brand.accentColor, border: `1px solid ${brand.accentColor}44` }}
          >
            My Permit
          </a>
          <span className="text-xs text-bone/70">{user.email}</span>
          <span
            style={{ background: `${brand.accentColor}33`, color: brand.accentColor }}
            className="text-[10px] px-2 py-0.5 rounded-full font-medium uppercase tracking-wide"
          >
            {user.role}
          </span>
          <button
            onClick={() => logout()}
            className="text-xs text-bone/50 hover:text-bone transition-colors"
          >
            Sign out
          </button>
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
          <Route path="/finance" element={<Finance />} />
          <Route path="/alerts" element={<Alerts />} />
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
      <nav style={{ background: brand.primaryColor }} className="text-bone px-6 py-3 flex items-center gap-6 shadow-md">
        <div className="flex items-center gap-2 mr-4">
          {brand.logoUrl && <img src={brand.logoUrl} alt={brand.brandName || "Logo"} className="h-8 w-auto" />}
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
  const isLotteryRoute = location.pathname === "/parking";
  const isLotteryV2Route = location.pathname === "/parking/lottery-v2";
  const isEmployeeParkingRoute = location.pathname === "/employee-parking";
  const isParkingMapRoute = location.pathname === "/parking-map";
  const isVisitorRoute = location.pathname.startsWith("/visitor");
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
        <Route path="/parking" element={<LotteryApply />} />
      </Routes>
    );
  }

  if (isLotteryV2Route) {
    return (
      <Routes>
        <Route path="/parking/lottery-v2" element={<LotteryApplyV2 />} />
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
          {user.role === "admin" || user.role === "staff" ? (
            <AdminShell user={user} />
          ) : (
            <StudentShell user={user} />
          )}
        </UserContext.Provider>
      )}
    </AuthGuard>
  );
}
