import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Result, Spin, Card } from "antd";
import { useBranding } from "../useBranding";
import BrandMark from "../components/BrandMark";

export default function AlertUnsubscribe() {
  const brand = useBranding();
  const { token } = useParams<{ token: string }>();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!token) { setStatus("error"); setMsg("Invalid unsubscribe link."); return; }
    fetch(`/api/alerts/unsubscribe/${token}`)
      .then(async res => {
        const data = await res.json();
        if (res.ok) { setStatus("success"); setMsg(data.message || "You have been unsubscribed."); }
        else { setStatus("error"); setMsg(data.detail || "Invalid or already used."); }
      }).catch(() => { setStatus("error"); setMsg("Something went wrong."); });
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center px-4" style={{ background: `linear-gradient(to bottom, ${brand.primaryColor}, ${brand.primaryColor}dd)` }}>
      <Card className="max-w-md w-full text-center">
        <BrandMark variant="onLight" className="h-12 w-auto mx-auto mb-4" />
        {status === "loading" && <Spin size="large" />}
        {status === "success" && <Result status="success" title="Unsubscribed" subTitle={msg} />}
        {status === "error" && <Result status="error" title="Oops" subTitle={msg} />}
      </Card>
    </div>
  );
}
