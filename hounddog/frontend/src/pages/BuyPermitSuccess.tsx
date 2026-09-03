import { useEffect, useState } from "react";
import { Result, Spin, Button } from "antd";
import { useBranding } from "../useBranding";
import PublicPageNav from "../components/PublicPageNav";
import PublicFooter from "../components/PublicFooter";

export default function BuyPermitSuccess() {
  const brand = useBranding();
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
      <PublicPageNav subtitle="Parking Permits" />
      <main className="max-w-lg mx-auto px-6 py-16 text-center">
        {status === "loading" && <Spin size="large" />}
        {status === "success" && (
          <Result status="success" title="Payment Successful"
            subTitle={`Your parking ${permitType || "permit"} has been activated. You'll receive a confirmation email shortly.`}
            extra={<Button type="primary" href="/permits/buy">Back to Permits</Button>} />
        )}
        {status === "error" && (
          <Result status="error" title="Payment Issue"
            subTitle={`We couldn't verify your payment. If you were charged, please contact the ${brand.departmentName}.`}
            extra={<Button type="primary" href="/permits/buy">Try Again</Button>} />
        )}
      </main>
      <PublicFooter />
    </div>
  );
}
