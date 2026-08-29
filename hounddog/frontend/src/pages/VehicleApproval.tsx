import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Button, Card, Spin, Result, App } from "antd";
import { useBranding } from "../useBranding";
import PublicPageNav from "../components/PublicPageNav";

interface RequestInfo {
  id: string;
  student_name: string;
  student_email: string;
  plate: string;
  plate_state: string;
  reason: string;
  status: string;
  permit_number: string | null;
  current_plates: string[];
  permit_type: string | null;
  already_decided: boolean;
  decision: string | null;
  created_at: string | null;
}

export default function VehicleApproval() {
  return (
    <App>
      <ApprovalPage />
    </App>
  );
}

function ApprovalPage() {
  const { token } = useParams<{ token: string }>();
  const brand = useBranding();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(true);
  const [info, setInfo] = useState<RequestInfo | null>(null);
  const [error, setError] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [decided, setDecided] = useState<"approved" | "denied" | null>(null);

  useEffect(() => {
    if (!token) return;
    (async () => {
      try {
        const res = await fetch(`/api/vehicle-requests/approve/${token}`);
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || "Failed to load request details");
        }
        const data: RequestInfo = await res.json();
        setInfo(data);
        if (data.already_decided) {
          setDecided(data.decision as "approved" | "denied");
        }
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [token]);

  async function handleDecision(decision: "approved" | "denied") {
    if (!token) return;
    setDeciding(true);
    try {
      const res = await fetch(`/api/vehicle-requests/approve/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to submit decision");
      }
      setDecided(decision);
      message.success(decision === "approved" ? "Vehicle approved and added to permit!" : "Request denied.");
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setDeciding(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">
        <PublicPageNav subtitle="Vehicle Request" />
        <div className="flex justify-center py-20"><Spin size="large" /></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50">
        <PublicPageNav subtitle="Vehicle Request" />
        <main className="max-w-lg mx-auto px-6 py-10">
          <Result status="error" title="Unable to Load" subTitle={error} />
        </main>
      </div>
    );
  }

  if (!info) return null;

  if (decided) {
    return (
      <div className="min-h-screen bg-gray-50">
        <PublicPageNav subtitle="Vehicle Request" />
        <main className="max-w-lg mx-auto px-6 py-10">
          <Result
            status={decided === "approved" ? "success" : "info"}
            title={decided === "approved" ? "Vehicle Approved" : "Request Denied"}
            subTitle={
              decided === "approved"
                ? `Plate ${info.plate} has been added to ${info.student_name}'s commuter permit (${info.permit_number || "N/A"}). The student has been notified.`
                : `The multi-vehicle request from ${info.student_name} for plate ${info.plate} has been denied. The student has been notified.`
            }
          />
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <PublicPageNav subtitle="Vehicle Request" />
      <main className="max-w-lg mx-auto px-6 py-10">
        <Card className="shadow-sm">
          <h2 className="text-xl font-bold text-gray-800 mb-2">Multi-Vehicle Request</h2>
          <p className="text-sm text-gray-500 mb-6">
            A commuter student has requested to add a second vehicle to their parking permit.
            Please review and approve or deny.
          </p>

          <table className="w-full text-sm mb-6">
            <tbody>
              <tr className="border-b">
                <td className="py-3 text-gray-500">Student</td>
                <td className="py-3 font-semibold text-right">{info.student_name}</td>
              </tr>
              <tr className="border-b">
                <td className="py-3 text-gray-500">Email</td>
                <td className="py-3 text-right">{info.student_email}</td>
              </tr>
              <tr className="border-b">
                <td className="py-3 text-gray-500">Permit #</td>
                <td className="py-3 font-mono font-semibold text-right">{info.permit_number || "N/A"}</td>
              </tr>
              <tr className="border-b">
                <td className="py-3 text-gray-500">Current Plate(s)</td>
                <td className="py-3 font-mono text-right">{info.current_plates.join(", ") || "None"}</td>
              </tr>
              <tr className="border-b">
                <td className="py-3 text-gray-500">Requested Plate</td>
                <td className="py-3 font-mono font-semibold text-right">
                  {info.plate}{info.plate_state ? ` (${info.plate_state})` : ""}
                </td>
              </tr>
              {info.reason && (
                <tr>
                  <td className="py-3 text-gray-500">Reason</td>
                  <td className="py-3 text-right">{info.reason}</td>
                </tr>
              )}
            </tbody>
          </table>

          <div className="flex gap-3 justify-end pt-4 border-t">
            <Button
              danger
              size="large"
              loading={deciding}
              onClick={() => handleDecision("denied")}
            >
              Deny
            </Button>
            <Button
              type="primary"
              size="large"
              loading={deciding}
              onClick={() => handleDecision("approved")}
              style={{ background: brand.primaryColor }}
            >
              Approve Vehicle
            </Button>
          </div>
        </Card>
      </main>
    </div>
  );
}
