import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Result, Spin, Card } from "antd";

export default function AlertUnsubscribe() {
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
    <div className="min-h-screen bg-gradient-to-b from-navy to-navy-700 flex items-center justify-center px-4">
      <Card className="max-w-md w-full text-center">
        {status === "loading" && <Spin size="large" />}
        {status === "success" && <Result status="success" title="Unsubscribed" subTitle={msg} />}
        {status === "error" && <Result status="error" title="Oops" subTitle={msg} />}
      </Card>
    </div>
  );
}
