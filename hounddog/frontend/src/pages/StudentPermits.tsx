import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";
import { Button, Card, Tag, Empty, Alert, Modal, Form, Input, InputNumber, Spin, Space, App } from "antd";

interface AvailablePermit {
  id: string; code: string; label: string; eligible: string; price: string;
  max_capacity: number; remaining: number; lot_assignments: string[];
  valid_days: number; min_class_year: number | null;
  application_closes_at: string | null; requires_lottery: boolean;
  current_applicants: number | null; approximate_odds: string | null;
}

interface MyApplication {
  id: string; student_name: string; class_year: number; plate: string;
  status: string; permit_type_label: string; permit_type_code: string;
  permit_type_price: string; lot_assignments: string[];
  lot_preferences: string[]; assigned_lot: string | null;
  waitlist_position: number | null; offer_expires_at: string | null; created_at: string;
  waitlist_message: string | null; fee_exempt: boolean;
}

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  pending: { text: "Pending lottery", color: "gold" },
  selected: { text: "Selected — accept offer", color: "green" },
  waitlisted: { text: "Waitlisted", color: "blue" },
  accepted: { text: "Permit active", color: "lime" },
  expired: { text: "Offer expired", color: "default" },
  declined: { text: "Declined", color: "default" },
};

export default function StudentPermits() {
  const { modal, message } = App.useApp();
  const [available, setAvailable] = useState<AvailablePermit[]>([]);
  const [applications, setApplications] = useState<MyApplication[]>([]);
  const [applying, setApplying] = useState<AvailablePermit | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const headers = await authHeaders();
      const [avRes, myRes] = await Promise.all([
        fetch("/api/student/permits/available", { headers }),
        fetch("/api/student/permits/my-applications", { headers }),
      ]);
      if (avRes.ok) setAvailable(await avRes.json());
      if (myRes.ok) setApplications(await myRes.json());
    } catch { message.error("Failed to load permit data"); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("accepted")) {
      message.success("Payment received — your permit is now active.");
      window.history.replaceState({}, "", "/student/permits");
      load();
    }
  }, [load]);

  async function handleAccept(appId: string) {
    try {
      const res = await fetch(`/api/student/permits/${appId}/accept`, { method: "POST", headers: await authHeaders() });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Accept failed"); }
      const data = await res.json();
      if (data.fee_exempt) {
        message.success(data.message || "Thank you — your permit has been issued at no charge.");
        load();
      } else {
        window.location.href = data.checkout_url;
      }
    } catch (e: any) { message.error(e.message); }
  }

  function handleDecline(appId: string) {
    modal.confirm({
      title: "Decline this offer?",
      content: "The spot will go to the next person on the waitlist.",
      okText: "Decline", okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const res = await fetch(`/api/student/permits/${appId}/decline`, { method: "POST", headers: await authHeaders() });
          if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Decline failed"); }
          message.success("Offer declined"); load();
        } catch (e: any) { message.error(e.message); }
      },
    });
  }

  const appliedTypeIds = new Set(applications.filter(a => !["expired", "declined"].includes(a.status)).map(a => a.permit_type_code));

  if (loading) return <div className="flex justify-center py-20"><Spin size="large" /></div>;

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-brand-primary">Parking Permits</h2>
        <p className="text-sm text-ink-mute mt-1">Apply for a parking permit. Lottery-based permits will be drawn after the application window closes.</p>
      </div>

      {applications.length > 0 && (
        <div>
          <h3 className="text-lg font-semibold text-brand-primary mb-3">My applications</h3>
          <div className="space-y-3">
            {applications.map(app => {
              const st = STATUS_LABELS[app.status] || { text: app.status, color: "default" };
              const isExpiredOrDeclined = ["expired", "declined"].includes(app.status);
              return (
                <Card key={app.id} className={isExpiredOrDeclined ? "opacity-50" : ""}>
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="font-medium text-brand-primary">{app.permit_type_label}</div>
                      <div className="text-xs text-ink-mute mt-0.5">
                        Plate: <span className="font-mono">{app.plate}</span> &middot; Class of {app.class_year} &middot; Lots: {app.lot_assignments.join(", ")}
                        {app.assigned_lot && <span className="ml-1 text-green-700 font-medium">&middot; Assigned: {app.assigned_lot}</span>}
                      </div>
                      {app.status === "waitlisted" && app.waitlist_message && <div className="text-xs text-blue-600 mt-1">{app.waitlist_message}</div>}
                      {app.status === "waitlisted" && !app.waitlist_message && app.waitlist_position != null && <div className="text-xs text-blue-600 mt-1">Waitlist position #{app.waitlist_position}</div>}
                      {app.status === "selected" && app.offer_expires_at && (
                        <div className="text-xs text-green-700 mt-1">
                          Accept by {new Date(app.offer_expires_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                        </div>
                      )}
                    </div>
                    <Space>
                      <Tag color={st.color}>{st.text}</Tag>
                      {app.status === "selected" && (
                        <>
                          <Button type="primary" size="small" onClick={() => handleAccept(app.id)}>
                            Accept & Pay
                          </Button>
                          <Button size="small" onClick={() => handleDecline(app.id)}>Decline</Button>
                        </>
                      )}
                    </Space>
                  </div>
                </Card>
              );
            })}
          </div>
        </div>
      )}

      {available.length > 0 && (
        <div>
          <h3 className="text-lg font-semibold text-brand-primary mb-3">Available permits</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {available.map(pt => {
              const alreadyApplied = appliedTypeIds.has(pt.code);
              return (
                <Card key={pt.id} className="flex flex-col">
                  <div className="flex items-start justify-between">
                    <div className="font-medium text-brand-primary">{pt.label}</div>
                    <div className="text-lg font-bold text-brand-primary">${Number(pt.price).toFixed(0)}</div>
                  </div>
                  <div className="text-xs text-ink-mute mt-1">{pt.eligible}</div>
                  <div className="text-xs text-ink-mute mt-1">Lots: {pt.lot_assignments.join(", ")} &middot; Valid {pt.valid_days} days</div>
                  <Space className="mt-2" wrap>
                    {pt.requires_lottery && <Tag color="purple">Lottery</Tag>}
                  </Space>
                  {pt.application_closes_at && <div className="text-xs text-amber-700 mt-1">Deadline: {new Date(pt.application_closes_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" })}</div>}
                  {pt.min_class_year && <div className="text-xs text-ink-mute mt-1">Eligibility: Class of {pt.min_class_year} or earlier only</div>}
                  <div className="mt-4">
                    {alreadyApplied ? <span className="text-xs text-ink-mute italic">Already applied</span>
                      : pt.remaining <= 0 ? <span className="text-xs text-red-600">Unavailable</span>
                      : <Button type="primary" block onClick={() => setApplying(pt)}>Apply</Button>}
                  </div>
                </Card>
              );
            })}
          </div>
        </div>
      )}

      {available.length === 0 && applications.length === 0 && <Empty description="No permit types are currently open for application" />}

      <ApplyModal permit={applying} onClose={() => setApplying(null)}
        onSuccess={() => { setApplying(null); message.success("Application submitted successfully"); load(); }}
        onError={msg => { message.error(msg); setApplying(null); }} />
    </div>
  );
}

interface OktaProfile {
  display_name: string;
  given_name: string;
  family_name: string;
  email: string;
  class_year: number | null;
}

function ApplyModal({ permit, onClose, onSuccess, onError }: {
  permit: AvailablePermit | null; onClose: () => void; onSuccess: () => void; onError: (msg: string) => void;
}) {
  const [form] = Form.useForm();
  const [lotPreferences, setLotPreferences] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [profile, setProfile] = useState<OktaProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);

  useEffect(() => {
    if (permit) {
      form.resetFields();
      setLotPreferences(permit.lot_assignments);
      setProfileLoading(true);
      (async () => {
        try {
          const res = await fetch("/api/auth/profile", { headers: await authHeaders() });
          if (res.ok) {
            const p: OktaProfile = await res.json();
            setProfile(p);
            const prefill: Record<string, unknown> = {};
            if (p.display_name) prefill.name = p.display_name;
            if (p.class_year) prefill.class_year = p.class_year;
            form.setFieldsValue(prefill);
          }
        } catch { /* fallback to manual entry */ }
        finally { setProfileLoading(false); }
      })();
    }
  }, [permit, form]);

  function moveLot(index: number, direction: -1 | 1) {
    const n = [...lotPreferences];
    const t = index + direction;
    if (t < 0 || t >= n.length) return;
    [n[index], n[t]] = [n[t], n[index]];
    setLotPreferences(n);
  }

  async function handleFinish(values: any) {
    if (!permit) return;
    setSubmitting(true);
    try {
      const res = await fetch("/api/student/permits/apply", {
        method: "POST", headers: await authHeaders(),
        body: JSON.stringify({
          permit_type_id: permit.id, student_name: values.name,
          plate: values.plate.toUpperCase().trim(), class_year: values.class_year,
          phone: values.phone || null, lot_preferences: lotPreferences,
        }),
      });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Application failed"); }
      onSuccess();
    } catch (e: any) { onError(e.message); onClose(); } finally { setSubmitting(false); }
  }

  const nameFromOkta = !!profile?.display_name;
  const classYearFromOkta = !!profile?.class_year;

  return (
    <Modal open={!!permit} onCancel={onClose} footer={null} title={permit ? `Apply for ${permit.label}` : ""} destroyOnClose>
      {permit && (
        <>
          <p className="text-sm text-ink-mute mb-4">${Number(permit.price).toFixed(0)} &middot; Lots: {permit.lot_assignments.join(", ")}{permit.requires_lottery ? " (lottery)" : ""}</p>
          {profileLoading ? <div className="flex justify-center py-4"><Spin size="small" /></div> : (
            <Form form={form} layout="vertical" onFinish={handleFinish}>
              <Form.Item name="name" label="Full Name" rules={[{ required: true }]} tooltip={nameFromOkta ? "Auto-filled from your university account" : undefined}>
                <Input disabled={nameFromOkta} className={nameFromOkta ? "bg-gray-50" : ""} />
              </Form.Item>
              <Form.Item name="plate" label="License Plate" rules={[{ required: true }]}><Input placeholder="ABC1234" className="font-mono" /></Form.Item>
              <Form.Item name="class_year" label="Graduation Year" rules={[{ required: true }]} tooltip={classYearFromOkta ? "Auto-filled from your university account" : undefined}>
                <InputNumber min={2024} max={2035} placeholder="2027" className="w-full" disabled={classYearFromOkta} />
              </Form.Item>
              <Form.Item name="phone" label="Phone (optional)"><Input placeholder="610-555-0123" /></Form.Item>
              {permit.lot_assignments.length > 1 && (
                <Form.Item label="Lot Preferences (#1 is your top choice)">
                  <div className="space-y-1.5">
                    {lotPreferences.map((lot, idx) => (
                      <div key={lot} className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2">
                        <span className="text-xs font-bold text-ink-mute w-5">{idx + 1}.</span>
                        <span className="text-sm font-medium flex-1">{lot}</span>
                        <Button type="text" size="small" disabled={idx === 0} onClick={() => moveLot(idx, -1)}>▲</Button>
                        <Button type="text" size="small" disabled={idx === lotPreferences.length - 1} onClick={() => moveLot(idx, 1)}>▼</Button>
                      </div>
                    ))}
                  </div>
                  <p className="text-[10px] text-ink-mute mt-1">You will be assigned your highest-preference lot with available capacity.</p>
                </Form.Item>
              )}
              <div className="flex justify-end gap-3 pt-2">
                <Button onClick={onClose}>Cancel</Button>
                <Button type="primary" htmlType="submit" loading={submitting}>Submit Application</Button>
              </div>
            </Form>
          )}
        </>
      )}
    </Modal>
  );
}
