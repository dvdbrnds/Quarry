import { useCallback, useEffect, useState } from "react";
import { Button, Card, Empty, Modal, Form, Input, Spin, Tag, App } from "antd";
import { initAuth, isAuthenticated, login, authHeaders, logout, fetchCurrentUser, type AuthUser } from "../auth";
import { useBranding } from "../useBranding";

interface StaffPermitType {
  id: string; code: string; label: string; eligible: string;
  lot_assignments: string[]; valid_days: number;
}

interface RegisteredVehicle {
  id: string; permit_number: string | null; name: string; email: string | null;
  plate: string; lot_assignment: string; status: string;
  start_date: string; end_date: string | null;
}

export default function StaffPermits() {
  const [authState, setAuthState] = useState<"loading" | "ready" | "error">("loading");
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    (async () => {
      try {
        await initAuth();
        const authed = await isAuthenticated();
        if (!authed) { sessionStorage.setItem("quarry_return_path", "/employee-parking"); await login(); return; }
        const u = await fetchCurrentUser();
        setUser(u);
        setAuthState(u ? "ready" : "error");
      } catch { setAuthState("error"); }
    })();
  }, []);

  if (authState === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <Spin size="large" />
          <p className="mt-4 text-gray-500">Signing you in...</p>
        </div>
      </div>
    );
  }

  if (authState === "error" || !user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Card className="max-w-md text-center">
          <h2 className="text-xl font-bold text-red-600 mb-2">Sign-In Error</h2>
          <p className="text-gray-500 mb-4">We couldn't verify your identity. Make sure you're using your university account.</p>
          <Button onClick={() => window.location.reload()}>Try Again</Button>
        </Card>
      </div>
    );
  }

  return (
    <App>
      <StaffPage user={user} />
    </App>
  );
}

function StaffPage({ user }: { user: AuthUser }) {
  const brand = useBranding();
  const { modal, message } = App.useApp();
  const [permitType, setPermitType] = useState<StaffPermitType | null>(null);
  const [vehicles, setVehicles] = useState<RegisteredVehicle[]>([]);
  const [loading, setLoading] = useState(true);
  const [enrolling, setEnrolling] = useState(false);

  const load = useCallback(async () => {
    try {
      const headers = await authHeaders();
      const [avRes, myRes] = await Promise.all([
        fetch("/api/staff/permits/available", { headers }),
        fetch("/api/staff/permits/my-vehicles", { headers }),
      ]);
      if (avRes.ok) {
        const types: StaffPermitType[] = await avRes.json();
        setPermitType(types[0] || null);
      }
      if (myRes.ok) setVehicles(await myRes.json());
    } catch { message.error("Failed to load data"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  function handleRemove(v: RegisteredVehicle) {
    modal.confirm({
      title: "Remove this vehicle?",
      content: `This will deactivate the permit for plate ${v.plate}.`,
      okText: "Remove", okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const res = await fetch(`/api/staff/permits/${v.id}`, { method: "DELETE", headers: await authHeaders() });
          if (!res.ok && res.status !== 204) { const b = await res.json(); throw new Error(b.detail || "Remove failed"); }
          message.success("Vehicle removed"); load();
        } catch (e: any) { message.error(e.message); }
      },
    });
  }

  const activeVehicles = vehicles.filter(v => v.status === "active");
  const pastVehicles = vehicles.filter(v => v.status !== "active");

  return (
    <div className="min-h-screen bg-gray-50">
      <nav style={{ background: brand.primaryColor }} className="text-[#f5f0e8] px-6 py-4 shadow-md">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            {brand.logoUrl && <img src={brand.logoUrl} alt={brand.brandName} className="h-8 w-auto" />}
            <div>
              <h1 style={{ color: brand.accentColor }} className="text-lg font-bold">{brand.brandName}</h1>
              <span className="text-xs text-[#f5f0e8]/60">Employee Vehicle Registration</span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm text-[#f5f0e8]/80">{user.email}</span>
            <button onClick={() => logout()} className="text-xs text-[#f5f0e8]/50 hover:text-[#f5f0e8] transition-colors">Sign out</button>
          </div>
        </div>
      </nav>

      <main className="max-w-3xl mx-auto px-6 py-10">
        {loading ? (
          <div className="flex justify-center py-20"><Spin size="large" /></div>
        ) : (
          <div className="space-y-8">
            <div>
              <h2 className="text-2xl font-bold text-[#1a2744]">Vehicle Registration</h2>
              <p className="text-gray-500 mt-1">Register your vehicles for campus parking. There is no cost for faculty and staff permits.</p>
            </div>

            {permitType && (
              <Card className="border-l-4 border-l-[#c9a84c]">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-semibold text-[#1a2744] text-lg">{permitType.label}</div>
                    <p className="text-sm text-gray-500 mt-1">{permitType.eligible}</p>
                    <div className="text-sm text-gray-500 mt-2">
                      <span>Lots: </span>
                      <span className="inline-flex flex-wrap gap-1">
                        {permitType.lot_assignments.map(lot => (
                          <Tag key={lot} color="blue" className="!text-xs">Lot {lot}</Tag>
                        ))}
                      </span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-bold text-green-700">Free</div>
                    <Button
                      type="primary"
                      className="mt-3"
                      style={{ background: "#1a2744" }}
                      onClick={() => setEnrolling(true)}
                    >
                      Register Vehicle
                    </Button>
                  </div>
                </div>
              </Card>
            )}

            {activeVehicles.length > 0 && (
              <div>
                <h3 className="text-lg font-semibold text-[#1a2744] mb-3">Your Registered Vehicles</h3>
                <div className="space-y-3">
                  {activeVehicles.map(v => (
                    <Card key={v.id} className="hover:shadow-md transition-shadow">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="flex items-center gap-3">
                            <span className="font-mono text-lg font-bold text-[#1a2744]">{v.plate}</span>
                            <Tag color="green">Active</Tag>
                          </div>
                          <div className="text-sm text-gray-500 mt-1">
                            {v.name}
                            {v.permit_number && <span className="ml-2 text-gray-400">Permit #{v.permit_number}</span>}
                          </div>
                          <div className="text-xs text-gray-400 mt-1">
                            Lots: {v.lot_assignment}
                            {v.end_date && <span className="ml-2">· Expires {new Date(v.end_date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span>}
                          </div>
                        </div>
                        <Button size="small" danger onClick={() => handleRemove(v)}>Remove</Button>
                      </div>
                    </Card>
                  ))}
                </div>
              </div>
            )}

            {pastVehicles.length > 0 && (
              <div>
                <h3 className="text-lg font-semibold text-gray-400 mb-3">Past Registrations</h3>
                <div className="space-y-2">
                  {pastVehicles.map(v => (
                    <Card key={v.id} className="opacity-50">
                      <div className="flex items-center justify-between">
                        <div>
                          <span className="font-mono font-medium text-gray-500">{v.plate}</span>
                          <Tag className="ml-2" color="default">{v.status}</Tag>
                          <span className="text-xs text-gray-400 ml-2">{v.name}</span>
                        </div>
                      </div>
                    </Card>
                  ))}
                </div>
              </div>
            )}

            {activeVehicles.length === 0 && !permitType && (
              <Card className="text-center py-12">
                <Empty description={<span className="text-gray-500">No employee permit types are currently available. Contact Parking Services for assistance.</span>} />
              </Card>
            )}

            <div className="text-center text-xs text-gray-400 pt-4 border-t">
              {brand.schoolName || "Campus"} Parking Services — {brand.brandName}
            </div>
          </div>
        )}
      </main>

      <EnrollModal
        open={enrolling}
        onClose={() => setEnrolling(false)}
        onSuccess={() => { setEnrolling(false); message.success("Vehicle registered successfully!"); load(); }}
        onError={msg => { message.error(msg); setEnrolling(false); }}
      />
    </div>
  );
}

function EnrollModal({ open, onClose, onSuccess, onError }: {
  open: boolean; onClose: () => void; onSuccess: () => void; onError: (msg: string) => void;
}) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [profileLoading, setProfileLoading] = useState(false);
  const [nameFromProfile, setNameFromProfile] = useState(false);

  useEffect(() => {
    if (open) {
      form.resetFields();
      setNameFromProfile(false);
      setProfileLoading(true);
      (async () => {
        try {
          const res = await fetch("/api/auth/profile", { headers: await authHeaders() });
          if (res.ok) {
            const p = await res.json();
            if (p.display_name) {
              form.setFieldsValue({ name: p.display_name });
              setNameFromProfile(true);
            }
          }
        } catch { /* manual entry fallback */ }
        finally { setProfileLoading(false); }
      })();
    }
  }, [open, form]);

  async function handleFinish(values: any) {
    setSubmitting(true);
    try {
      const res = await fetch("/api/staff/permits/enroll", {
        method: "POST", headers: await authHeaders(),
        body: JSON.stringify({
          name: values.name.trim(),
          plate: values.plate.toUpperCase().trim(),
          plate_state: (values.plate_state || "").toUpperCase().trim(),
        }),
      });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Registration failed"); }
      onSuccess();
    } catch (e: any) { onError(e.message); } finally { setSubmitting(false); }
  }

  return (
    <Modal open={open} onCancel={onClose} footer={null} title="Register a Vehicle" destroyOnClose width={480}>
      {profileLoading ? (
        <div className="flex justify-center py-4"><Spin size="small" /></div>
      ) : (
        <Form form={form} layout="vertical" onFinish={handleFinish} className="pt-2">
          <Form.Item name="name" label="Full Name" rules={[{ required: true }]} tooltip={nameFromProfile ? "From your university account" : undefined}>
            <Input disabled={nameFromProfile} className={nameFromProfile ? "bg-gray-50" : ""} />
          </Form.Item>
          <div className="grid grid-cols-3 gap-3">
            <Form.Item name="plate" label="License Plate" rules={[{ required: true }]} className="col-span-2">
              <Input placeholder="ABC1234" className="font-mono" />
            </Form.Item>
            <Form.Item name="plate_state" label="State" rules={[{ required: true, message: "State required" }]}>
              <Input placeholder="PA" maxLength={2} className="font-mono uppercase" />
            </Form.Item>
          </div>
          <div className="flex justify-end gap-3 pt-4 border-t mt-4">
            <Button onClick={onClose}>Cancel</Button>
            <Button type="primary" htmlType="submit" loading={submitting} style={{ background: "#1a2744" }}>Register Vehicle</Button>
          </div>
        </Form>
      )}
    </Modal>
  );
}
