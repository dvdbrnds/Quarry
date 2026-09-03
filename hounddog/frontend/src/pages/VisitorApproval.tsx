import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Button, Card, Spin, Result, App } from "antd";
import { useBranding } from "../useBranding";
import PublicPageNav from "../components/PublicPageNav";
import PublicFooter from "../components/PublicFooter";

interface ApprovalInfo {
  permit_id: string;
  permit_number: string | null;
  name: string;
  company_name: string;
  plate: string;
  work_description: string;
  sponsor_department: string;
  start_date: string;
  end_date: string | null;
  status: string;
  already_decided: boolean;
  decision: string | null;
}

export default function VisitorApproval() {
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
  const [info, setInfo] = useState<ApprovalInfo | null>(null);
  const [error, setError] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [decided, setDecided] = useState<"approved" | "denied" | null>(null);

  useEffect(() => {
    if (!token) return;
    (async () => {
      try {
        const res = await fetch(`/api/visitor/permits/approve/${token}`);
        if (!res.ok) {
          const body = await res.json();
          throw new Error(body.detail || "Failed to load approval details");
        }
        const data: ApprovalInfo = await res.json();
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
      const res = await fetch(`/api/visitor/permits/approve/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Failed to submit decision");
      }
      setDecided(decision);
      message.success(decision === "approved" ? "Permit approved!" : "Permit denied.");
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setDeciding(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">
        <PublicPageNav subtitle="Permit Approval" />
        <div className="flex justify-center py-20"><Spin size="large" /></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50">
        <PublicPageNav subtitle="Permit Approval" />
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
        <PublicPageNav subtitle="Permit Approval" />
        <main className="max-w-lg mx-auto px-6 py-10">
          <Result
            status={decided === "approved" ? "success" : "info"}
            title={decided === "approved" ? "Permit Approved" : "Permit Denied"}
            subTitle={
              decided === "approved"
                ? `The parking permit for ${info.name} (${info.company_name}) is now active. Their plate ${info.plate} has been registered.`
                : `The parking permit request from ${info.name} (${info.company_name}) has been denied.`
            }
          />
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <PublicPageNav subtitle="Permit Approval" />
      <main className="max-w-lg mx-auto px-6 py-10">
        <Card className="shadow-sm">
          <h2 className="text-xl font-bold text-gray-800 mb-2">Vendor Parking Permit Approval</h2>
          <p className="text-sm text-gray-500 mb-6">
            A vendor has requested a long-term parking permit and listed you as their campus sponsor.
            Please review and approve or deny.
          </p>

          <table className="w-full text-sm mb-6">
            <tbody>
              <tr className="border-b">
                <td className="py-3 text-gray-500">Vendor Name</td>
                <td className="py-3 font-semibold text-right">{info.name}</td>
              </tr>
              <tr className="border-b">
                <td className="py-3 text-gray-500">Company</td>
                <td className="py-3 font-semibold text-right">{info.company_name}</td>
              </tr>
              <tr className="border-b">
                <td className="py-3 text-gray-500">Vehicle</td>
                <td className="py-3 font-mono font-semibold text-right">{info.plate}</td>
              </tr>
              <tr className="border-b">
                <td className="py-3 text-gray-500">Work Description</td>
                <td className="py-3 text-right">{info.work_description || "Not provided"}</td>
              </tr>
              <tr className="border-b">
                <td className="py-3 text-gray-500">Department</td>
                <td className="py-3 text-right">{info.sponsor_department || "—"}</td>
              </tr>
              <tr>
                <td className="py-3 text-gray-500">Duration</td>
                <td className="py-3 text-right">
                  {info.start_date}
                  {info.end_date && ` — ${info.end_date}`}
                </td>
              </tr>
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
              Approve Permit
            </Button>
          </div>
        </Card>
      </main>
      <PublicFooter />
    </div>
  );
}
