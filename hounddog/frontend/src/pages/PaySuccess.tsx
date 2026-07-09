import { useEffect, useState } from "react";
import { Result, Spin, Button } from "antd";

interface VerifyResult { payment_status: string; payment_type?: string; ticket_id?: string; ticket_plate?: string; }

export default function PaySuccess() {
  const [sessionId, setSessionId] = useState("");
  const [verifying, setVerifying] = useState(true);
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [verifyError, setVerifyError] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sid = params.get("session_id") || "";
    setSessionId(sid);
    if (!sid) { setVerifying(false); return; }
    fetch(`/api/payments/verify-session?session_id=${encodeURIComponent(sid)}`)
      .then(r => r.json()).then(data => { setResult(data); setVerifying(false); })
      .catch(() => { setVerifyError(true); setVerifying(false); });
  }, []);

  const isPaid = result?.payment_status === "paid";

  return (
    <div className="min-h-screen bg-bone-light flex items-start justify-center pt-16 px-4">
      <div className="w-full max-w-md text-center">
        {verifying ? <Spin size="large" /> : (
          <Result
            status={isPaid ? "success" : "warning"}
            title={isPaid ? "Payment Confirmed" : verifyError ? "Payment Submitted" : "Processing Payment"}
            subTitle={isPaid
              ? result?.payment_type === "permit_purchase" ? "Your permit purchase is complete." : "Your parking ticket payment has been confirmed."
              : verifyError ? "If you completed checkout, your payment was processed." : "Your payment may still be processing."}
            extra={[
              result?.ticket_plate && <p key="plate" className="text-sm font-mono bg-bone rounded-lg px-4 py-2 inline-block mb-4">Plate: {result.ticket_plate}</p>,
              sessionId && <p key="ref" className="text-xs text-ink-mute font-mono mb-4">Reference: {sessionId.slice(0, 20)}...</p>,
              <Button key="back" type="primary" href="/pay">Pay Another Ticket</Button>,
            ]}
          />
        )}
        <div className="text-center text-xs text-ink-mute mt-8">&copy; Quarry Parking Systems</div>
      </div>
    </div>
  );
}
