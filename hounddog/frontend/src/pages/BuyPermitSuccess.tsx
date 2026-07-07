import { useEffect, useState } from "react";

export default function BuyPermitSuccess() {
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [permitType, setPermitType] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get("session_id");
    if (!sessionId) {
      setStatus("error");
      return;
    }
    verifySession(sessionId);
  }, []);

  async function verifySession(sessionId: string) {
    try {
      const res = await fetch(`/api/payments/verify-session?session_id=${encodeURIComponent(sessionId)}`);
      if (!res.ok) throw new Error("Verification failed");
      const data = await res.json();
      if (data.payment_status === "paid") {
        setPermitType(data.payment_type === "standalone_permit_purchase" ? "permit" : "");
        setStatus("success");
      } else {
        setStatus("error");
      }
    } catch {
      setStatus("error");
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-navy text-bone px-6 py-4 shadow-md">
        <div className="max-w-4xl mx-auto flex items-center gap-3">
          <img src="/quarry-logo.png" alt="Quarry" className="h-8 w-auto" />
          <h1 className="text-lg font-bold tracking-wide text-brass">
            Quarry
          </h1>
          <span className="text-sm text-bone/70 ml-2">Parking Permits</span>
        </div>
      </nav>

      <main className="max-w-lg mx-auto px-6 py-16 text-center">
        {status === "loading" && (
          <div className="text-ink-mute text-sm">Verifying payment...</div>
        )}

        {status === "success" && (
          <div className="bg-white rounded-xl shadow p-8">
            <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-xl font-bold text-navy mb-2">Payment Successful</h2>
            <p className="text-sm text-ink-mute mb-6">
              Your parking {permitType || "permit"} has been activated. You'll receive a confirmation
              email shortly with your permit details.
            </p>
            <a
              href="/permits/buy"
              className="inline-block px-5 py-2 bg-navy text-bone rounded-lg text-sm font-medium hover:bg-navy-700 transition-colors"
            >
              Back to Permits
            </a>
          </div>
        )}

        {status === "error" && (
          <div className="bg-white rounded-xl shadow p-8">
            <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <h2 className="text-xl font-bold text-navy mb-2">Payment Issue</h2>
            <p className="text-sm text-ink-mute mb-6">
              We couldn't verify your payment. If you were charged, please contact Parking Services.
            </p>
            <a
              href="/permits/buy"
              className="inline-block px-5 py-2 bg-navy text-bone rounded-lg text-sm font-medium hover:bg-navy-700 transition-colors"
            >
              Try Again
            </a>
          </div>
        )}
      </main>
    </div>
  );
}
