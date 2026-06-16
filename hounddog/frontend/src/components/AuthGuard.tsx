import { useEffect, useState } from "react";
import { initAuth, isAuthenticated, login, fetchCurrentUser, type AuthUser } from "../auth";

interface Props {
  children: (user: AuthUser) => React.ReactNode;
}

export default function AuthGuard({ children }: Props) {
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await initAuth();
        const authed = await isAuthenticated();
        if (!authed) {
          await login();
          return;
        }
        const u = await fetchCurrentUser();
        if (!cancelled) {
          setUser(u);
          setState(u ? "ready" : "error");
        }
      } catch {
        if (!cancelled) setState("error");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (state === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bone-light">
        <div className="text-center">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-navy mx-auto mb-4" />
          <p className="text-ink-mute">Loading...</p>
        </div>
      </div>
    );
  }

  if (state === "error" || !user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bone-light">
        <div className="bg-white rounded-xl shadow-lg p-8 max-w-md text-center">
          <h1 className="text-xl font-bold text-signal-red mb-4">Authentication Error</h1>
          <p className="text-ink-mute mb-6">Unable to verify your identity.</p>
          <button
            onClick={() => window.location.reload()}
            className="px-6 py-2 bg-navy text-bone rounded-lg hover:bg-navy-700 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return <>{children(user)}</>;
}
