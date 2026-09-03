import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Button, Card, Checkbox, Input, Result, Spin, Descriptions, Alert, App } from "antd";
import { useBranding } from "../useBranding";
import PublicPageNav from "../components/PublicPageNav";
import PublicFooter from "../components/PublicFooter";

interface RenewalInfo {
  permit_holder_name: string; email: string; plates: string[];
  lot_assignment: string; permit_type: string; end_date: string | null; expired: boolean;
}

export default function PermitRenew() {
  const { message } = App.useApp();
  const brand = useBranding();
  const { token } = useParams<{ token: string }>();
  const [info, setInfo] = useState<RenewalInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [newPlate, setNewPlate] = useState("");
  const [changePlate, setChangePlate] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState("");

  useEffect(() => { if (token) loadRenewalInfo(); }, [token]);

  async function loadRenewalInfo() {
    setLoading(true); setError("");
    try {
      const res = await fetch(`/api/renewals/${token}`);
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Invalid renewal link"); }
      setInfo(await res.json());
    } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  }

  async function handleConfirm() {
    if (!token) return;
    setSubmitting(true); setError("");
    try {
      const res = await fetch(`/api/renewals/${token}/confirm`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plate: changePlate && newPlate ? newPlate.toUpperCase().trim() : null }),
      });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Renewal failed"); }
      const data = await res.json();
      setSuccess(data.message);
    } catch (e: any) { setError(e.message); } finally { setSubmitting(false); }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <PublicPageNav subtitle="Permit Renewal" />
      <main className="max-w-lg mx-auto px-6 py-12">
        {loading && <div className="flex justify-center py-20"><Spin size="large" /></div>}
        {error && !success && <Result status="error" title="Renewal Unavailable" subTitle={error} />}
        {success && <Result status="success" title="Permit Renewed" subTitle={success} />}
        {info && !success && !error && (
          <Card>
            <h2 className="text-xl font-bold text-brand-primary mb-1">Renew Your Parking Permit</h2>
            <p className="text-sm text-ink-mute mb-6">Confirm the details below. No payment required.</p>
            <Descriptions column={1} size="small" className="mb-6">
              <Descriptions.Item label="Name">{info.permit_holder_name}</Descriptions.Item>
              <Descriptions.Item label="Email">{info.email}</Descriptions.Item>
              <Descriptions.Item label="Type"><span className="capitalize">{info.permit_type.replace(/_/g, " ")}</span></Descriptions.Item>
              <Descriptions.Item label="Lots">{info.lot_assignment}</Descriptions.Item>
              <Descriptions.Item label="Plates"><span className="font-mono">{info.plates.join(", ")}</span></Descriptions.Item>
              {info.end_date && <Descriptions.Item label="Expires">
                <span className={info.expired ? "text-red-600" : ""}>{new Date(info.end_date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}{info.expired && " (expired)"}</span>
              </Descriptions.Item>}
            </Descriptions>
            <div className="border-t pt-4 mb-6">
              <Checkbox checked={changePlate} onChange={e => setChangePlate(e.target.checked)}>I need to update my license plate</Checkbox>
              {changePlate && <Input value={newPlate} onChange={e => setNewPlate(e.target.value.toUpperCase())} placeholder="ABC1234" className="mt-3 font-mono" />}
            </div>
            <Button type="primary" block size="large" onClick={handleConfirm} loading={submitting} disabled={changePlate && !newPlate}>Confirm Renewal</Button>
            <p className="text-xs text-ink-mute text-center mt-3">No payment is required for faculty/staff permit renewals.</p>
          </Card>
        )}
      </main>
      <PublicFooter />
    </div>
  );
}
