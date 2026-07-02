import { Routes, Route, NavLink, Navigate, useLocation } from "react-router-dom";
import Permits from "./pages/Permits";
import Lots from "./pages/Lots";
import Dashboard from "./pages/Dashboard";
import Tickets from "./pages/Tickets";
import Pay from "./pages/Pay";
import PaySuccess from "./pages/PaySuccess";
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
import AuthCallback from "./pages/AuthCallback";
import AuthGuard from "./components/AuthGuard";
import { logout } from "./auth";
import type { AuthUser } from "./auth";
import { UserContext } from "./UserContext";

function NavItem({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
          isActive
            ? "bg-brass text-navy-deep"
            : "text-bone hover:bg-navy-700"
        }`
      }
    >
      {children}
    </NavLink>
  );
}

function AdminShell({ user }: { user: AuthUser }) {
  return (
    <div className="min-h-screen">
      <nav className="bg-navy text-bone px-6 py-3 flex items-center gap-6 shadow-md">
        <div className="flex items-center gap-2 mr-4">
          <img src="/quarry-logo.png" alt="Quarry" className="h-8 w-auto" />
          <h1 className="text-lg font-bold tracking-wide text-brass">
            Quarry
          </h1>
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
          <span className="text-xs text-bone/70">{user.email}</span>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-brass/20 text-brass font-medium uppercase tracking-wide">
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
  return (
    <div className="min-h-screen">
      <nav className="bg-navy text-bone px-6 py-3 flex items-center gap-6 shadow-md">
        <div className="flex items-center gap-2 mr-4">
          <img src="/quarry-logo.png" alt="Quarry" className="h-8 w-auto" />
          <h1 className="text-lg font-bold tracking-wide text-brass">
            Quarry
          </h1>
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
  const isNotificationsRoute = location.pathname.startsWith("/notifications/");
  const isAlertSubscribeRoute = location.pathname.startsWith("/alerts/subscribe") || location.pathname.startsWith("/alerts/unsubscribe");
  const isSignageRoute = location.pathname.startsWith("/signage/player");
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
