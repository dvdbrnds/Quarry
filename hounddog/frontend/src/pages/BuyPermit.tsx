import { useEffect, useState } from "react";
import { Button, Card, Modal, Form, Input, InputNumber, Alert, Spin, Empty, App } from "antd";
import { useBranding } from "../useBranding";
import PublicPageNav from "../components/PublicPageNav";

interface AvailablePermit {
  id: string; code: string; label: string; price: string;
  remaining: number; lot_assignments: string[]; valid_days: number;
}

interface AvailablePermitsResponse { permit_types: AvailablePermit[]; ticket_fine_after_purchase: string; }

export default function BuyPermit() {
  const { message } = App.useApp();
  const brand = useBranding();
  const [permits, setPermits] = useState<AvailablePermit[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<AvailablePermit | null>(null);

  useEffect(() => { loadPermits(); }, []);

  async function loadPermits() {
    setLoading(true); setError("");
    try {
      const res = await fetch("/api/payments/permits/available");
      if (!res.ok) throw new Error("Failed");
      const data: AvailablePermitsResponse = await res.json();
      setPermits(data.permit_types);
    } catch { setError("Unable to load permits. Please try again later."); } finally { setLoading(false); }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <PublicPageNav subtitle="Parking Permits" />

      <main className="max-w-4xl mx-auto px-6 py-10">
        <div className="mb-8">
          <h2 className="text-2xl font-bold text-brand-primary">Purchase a Parking Permit</h2>
          <p className="text-sm text-ink-mute mt-1">Select a permit type below. Payment processed securely via Stripe.</p>
        </div>

        {error && <Alert type="error" message={error} className="mb-6" showIcon />}

        {loading ? (
          <div className="flex justify-center py-20"><Spin size="large" /></div>
        ) : permits.length === 0 ? (
          <Empty description="No permits currently available for online purchase" className="py-16" />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {permits.map(pt => (
              <Card key={pt.id} hoverable className="flex flex-col">
                <div className="flex items-start justify-between">
                  <div className="font-semibold text-brand-primary text-lg">{pt.label}</div>
                  <div className="text-xl font-bold text-brand-primary">${Number(pt.price).toFixed(0)}</div>
                </div>
                <div className="text-sm text-ink-mute mt-2">Lots: {pt.lot_assignments.join(", ")}</div>
                <div className="text-sm text-ink-mute mt-1">Valid for {pt.valid_days} days</div>
                <div className="mt-5">
                  {pt.remaining > 0
                    ? <Button type="primary" block onClick={() => setSelected(pt)}>Purchase</Button>
                    : <div className="text-center text-sm text-red-600 font-medium py-2">Sold Out</div>}
                </div>
              </Card>
            ))}
          </div>
        )}

        <PurchaseModal permit={selected} onClose={() => setSelected(null)} onError={msg => { setError(msg); setSelected(null); }} />
      </main>
    </div>
  );
}

function PurchaseModal({ permit, onClose, onError }: {
  permit: AvailablePermit | null; onClose: () => void; onError: (msg: string) => void;
}) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  async function handleFinish(values: any) {
    if (!permit) return;
    setSubmitting(true);
    try {
      const res = await fetch("/api/payments/standalone-purchase", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ permit_type_id: permit.id, student_name: values.name, plate: values.plate.toUpperCase().trim(),
          plate_state: (values.plate_state || "").toUpperCase().trim(), email: values.email,
          phone: values.phone || null, class_year: values.class_year || null }),
      });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Purchase failed"); }
      const { checkout_url } = await res.json();
      window.location.href = checkout_url;
    } catch (e: any) { onError(e.message); } finally { setSubmitting(false); }
  }

  return (
    <Modal open={!!permit} onCancel={onClose} footer={null} title={permit ? `Purchase ${permit.label}` : ""} destroyOnClose>
      {permit && (
        <>
          <p className="text-sm text-ink-mute mb-4">${Number(permit.price).toFixed(0)} &middot; Lots: {permit.lot_assignments.join(", ")} &middot; Valid {permit.valid_days} days</p>
          <Form form={form} layout="vertical" onFinish={handleFinish}>
            <Form.Item name="name" label="Full Name" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="email" label="Email" rules={[{ required: true, type: "email" }]}><Input placeholder="you@moravian.edu" /></Form.Item>
            <div className="grid grid-cols-3 gap-3">
              <Form.Item name="plate" label="License Plate" rules={[{ required: true }]} className="col-span-2"><Input placeholder="ABC1234" className="font-mono" /></Form.Item>
              <Form.Item name="plate_state" label="State" rules={[{ required: true, message: "State required" }]}><Input placeholder="PA" maxLength={2} className="font-mono uppercase" /></Form.Item>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Form.Item name="class_year" label="Graduation Year"><InputNumber min={2024} max={2035} placeholder="2027" className="w-full" /></Form.Item>
              <Form.Item name="phone" label="Phone"><Input placeholder="610-555-0123" /></Form.Item>
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <Button onClick={onClose}>Cancel</Button>
              <Button type="primary" htmlType="submit" loading={submitting}>Pay ${Number(permit.price).toFixed(0)}</Button>
            </div>
          </Form>
        </>
      )}
    </Modal>
  );
}
