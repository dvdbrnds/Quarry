import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { initAuth, handleCallback } from "../auth";

export default function AuthCallback() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    initAuth()
      .then(() => handleCallback())
      .then(() => navigate("/dashboard", { replace: true }))
      .catch((err) => setError(err.message || "Login failed"));
  }, [navigate]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bone-light">
        <div className="bg-white rounded-xl shadow-lg p-8 max-w-md text-center">
          <h1 className="text-xl font-bold text-signal-red mb-4">Login Error</h1>
          <p className="text-ink-mute mb-6">{error}</p>
          <a
            href="/"
            className="px-6 py-2 bg-navy text-bone rounded-lg hover:bg-navy-700 transition-colors"
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
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-navy mx-auto mb-4" />
        <p className="text-ink-mute">Signing in...</p>
      </div>
    </div>
  );
}
