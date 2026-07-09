import { useEffect, useState } from "react";
import { Result, Spin, Button } from "antd";
import { CheckCircleOutlined, CloseCircleOutlined } from "@ant-design/icons";

export default function BuyPermitSuccess() {
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [permitType, setPermitType] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get("session_id");
    if (!sessionId) { setStatus("error"); return; }
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
      } else { setStatus("error"); }
    } catch { setStatus("error"); }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-navy text-bone px-6 py-4 shadow-md">
        <div className="max-w-4xl mx-auto flex items-center gap-3">
          <img src="/quarry-logo.png" alt="Quarry" className="h-8 w-auto" />
          <h1 className="text-lg font-bold tracking-wide text-brass">Quarry</h1>
          <span className="text-sm text-bone/70 ml-2">Parking Permits</span>
        </div>
      </nav>
      <main className="max-w-lg mx-auto px-6 py-16 text-center">
        {status === "loading" && <Spin size="large" />}
        {status === "success" && (
          <Result status="success" title="Payment Successful"
            subTitle={`Your parking ${permitType || "permit"} has been activated. You'll receive a confirmation email shortly.`}
            extra={<Button type="primary" href="/permits/buy">Back to Permits</Button>} />
        )}
        {status === "error" && (
          <Result status="error" title="Payment Issue"
            subTitle="We couldn't verify your payment. If you were charged, please contact Parking Services."
            extra={<Button type="primary" href="/permits/buy">Try Again</Button>} />
        )}
      </main>
    </div>
  );
}
