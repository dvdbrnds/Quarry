import { useEffect, useState } from "react";

export default function PaySuccess() {
  const [sessionId, setSessionId] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setSessionId(params.get("session_id") || "");
  }, []);

  return (
    <div className="min-h-screen bg-bone-light flex items-start justify-center pt-16 px-4">
      <div className="w-full max-w-md text-center">
        <div className="bg-signal-green/15 rounded-full w-20 h-20 flex items-center justify-center mx-auto mb-6">
          <svg className="w-10 h-10 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>

        <h1 className="text-3xl font-bold text-navy mb-3">Payment Successful</h1>
        <p className="text-ink-mute mb-6">
          Your parking ticket has been paid. You should receive a confirmation email shortly.
        </p>

        {sessionId && (
          <p className="text-xs text-ink-mute font-mono mb-6">
            Reference: {sessionId.slice(0, 16)}...
          </p>
        )}

        <a
          href="/pay"
          className="inline-block px-6 py-3 bg-navy text-bone rounded-lg font-medium hover:bg-navy-700 transition-colors"
        >
          Pay Another Ticket
        </a>

        <div className="text-center text-xs text-ink-mute mt-8">
          &copy; Quarry Parking Systems
        </div>
      </div>
    </div>
  );
}
