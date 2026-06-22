import { useEffect, useState } from "react";

interface VerifyResult {
  payment_status: string;
  payment_type?: string;
  ticket_id?: string;
  ticket_plate?: string;
}

export default function PaySuccess() {
  const [sessionId, setSessionId] = useState("");
  const [verifying, setVerifying] = useState(true);
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [verifyError, setVerifyError] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sid = params.get("session_id") || "";
    setSessionId(sid);

    if (!sid) {
      setVerifying(false);
      return;
    }

    fetch(`/api/payments/verify-session?session_id=${encodeURIComponent(sid)}`)
      .then((r) => r.json())
      .then((data) => {
        setResult(data);
        setVerifying(false);
      })
      .catch(() => {
        setVerifyError(true);
        setVerifying(false);
      });
  }, []);

  const isPaid = result?.payment_status === "paid";

  return (
    <div className="min-h-screen bg-bone-light flex items-start justify-center pt-16 px-4">
      <div className="w-full max-w-md text-center">
        {verifying ? (
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-navy mx-auto mb-4" />
        ) : (
          <>
            <div className={`rounded-full w-20 h-20 flex items-center justify-center mx-auto mb-6 ${
              isPaid ? "bg-signal-green/15" : "bg-amber-100"
            }`}>
              {isPaid ? (
                <svg className="w-10 h-10 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              ) : (
                <svg className="w-10 h-10 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M12 3a9 9 0 100 18A9 9 0 0012 3z" />
                </svg>
              )}
            </div>

            <h1 className={`text-3xl font-bold mb-3 ${isPaid ? "text-navy" : "text-amber-700"}`}>
              {isPaid ? "Payment Confirmed" : verifyError ? "Payment Submitted" : "Processing Payment"}
            </h1>

            <p className="text-ink-mute mb-4">
              {isPaid
                ? result?.payment_type === "permit_purchase"
                  ? "Your permit purchase is complete. Your permit will be active shortly."
                  : "Your parking ticket payment has been confirmed."
                : verifyError
                  ? "We couldn't verify your payment status. If you completed checkout, your payment was processed."
                  : "Your payment may still be processing. Please check your email for confirmation."}
            </p>

            {result?.ticket_plate && (
              <p className="text-sm font-mono bg-bone rounded-lg px-4 py-2 inline-block mb-4">
                Plate: {result.ticket_plate}
              </p>
            )}

            {sessionId && (
              <p className="text-xs text-ink-mute font-mono mb-6">
                Reference: {sessionId.slice(0, 20)}...
              </p>
            )}
          </>
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
