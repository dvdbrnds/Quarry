import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { initAuth, handleCallback, fetchCurrentUser, isOfficeRole } from "../auth";
import BrandMark from "../components/BrandMark";

export default function AuthCallback() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    initAuth()
      .then(() => handleCallback())
      .then(() => fetchCurrentUser())
      .then((user) => {
        const savedPath = sessionStorage.getItem("quarry_return_path");
        sessionStorage.removeItem("quarry_return_path");

        if (savedPath) {
          navigate(savedPath, { replace: true });
        } else if (isOfficeRole(user?.role)) {
          navigate("/dashboard", { replace: true });
        } else if (user?.role === "staff") {
          navigate("/employee-parking", { replace: true });
        } else {
          navigate("/parking", { replace: true });
        }
      })
      .catch((err) => setError(err.message || "Login failed"));
  }, [navigate]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bone-light">
        <div className="bg-white rounded-xl shadow-lg p-8 max-w-md text-center">
          <BrandMark variant="onLight" className="h-12 w-auto mx-auto mb-4" />
          <h1 className="text-xl font-bold text-signal-red mb-4">Login Error</h1>
          <p className="text-ink-mute mb-6">{error}</p>
          <a
            href="/"
            className="px-6 py-2 bg-brand-primary text-white rounded-lg hover:opacity-90 transition-colors"
          >
            Try Again
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-bone-light">
      <div className="text-center">
        <BrandMark variant="onLight" className="h-14 w-auto mx-auto mb-6" />
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-brand-primary mx-auto mb-4" />
        <p className="text-ink-mute">Signing in...</p>
      </div>
    </div>
  );
}
