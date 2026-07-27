import { useCallback, useEffect, useState } from "react";
import { Button, Card, Empty, Modal, Form, Input, Spin, Tag, App, Alert, Checkbox, Descriptions } from "antd";
import { CheckCircleOutlined } from "@ant-design/icons";
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
  permit_type: string; permit_type_label: string;
}

interface RenewalInfo {
  permit_holder_name: string; email: string; plates: string[];
  lot_assignment: string; permit_type: string; end_date: string | null; expired: boolean;
}

export default function StaffPermits() {
  const [authState, setAuthState] = useState<"loading" | "ready" | "error">("loading");
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    (async () => {
      try {
        await initAuth();
        const authed = await isAuthenticated();
        if (!authed) { sessionStorage.setItem("quarry_return_path", window.location.pathname + window.location.search); await login(); return; }
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

  if (user.role !== "admin" && user.role !== "staff") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Card className="max-w-md text-center">
          <h2 className="text-xl font-bold text-brand-primary mb-2">Access Restricted</h2>
          <p className="text-gray-500 mb-4">This page is for faculty and staff only. If you are a student, visit the <a href="/parking" className="text-blue-600 underline">student parking portal</a> instead.</p>
          <Button onClick={() => logout()}>Sign Out</Button>
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

  const renewToken = new URLSearchParams(window.location.search).get("renew");
  const [renewalInfo, setRenewalInfo] = useState<RenewalInfo | null>(null);
  const [renewalError, setRenewalError] = useState("");
  const [renewalLoading, setRenewalLoading] = useState(!!renewToken);
  const [renewalSubmitting, setRenewalSubmitting] = useState(false);
  const [renewalSuccess, setRenewalSuccess] = useState("");
  const [changePlate, setChangePlate] = useState(false);
  const [newPlate, setNewPlate] = useState("");

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

  useEffect(() => {
    if (!renewToken) return;
    setRenewalLoading(true);
    fetch(`/api/renewals/${renewToken}`)
      .then(async (res) => {
        if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Invalid renewal link"); }
        setRenewalInfo(await res.json());
      })
      .catch((e) => setRenewalError(e.message))
      .finally(() => setRenewalLoading(false));
  }, [renewToken]);

  async function handleConfirmRenewal() {
    if (!renewToken) return;
    setRenewalSubmitting(true); setRenewalError("");
    try {
      const res = await fetch(`/api/renewals/${renewToken}/confirm`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plate: changePlate && newPlate ? newPlate.toUpperCase().trim() : null }),
      });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Renewal failed"); }
      const data = await res.json();
      setRenewalSuccess(data.message);
      setRenewalInfo(null);
      load();
    } catch (e: any) { setRenewalError(e.message); }
    finally { setRenewalSubmitting(false); }
  }

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

  const fmtDate = (d: string) => new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

  return (
    <div className="min-h-screen bg-gray-50">
      <nav style={{ background: brand.primaryColor }} className="text-white/90 px-6 py-4 shadow-md">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            {brand.logoUrl && <img src={brand.logoUrl} alt={brand.brandName || "Logo"} className="h-8 w-auto" />}
            <div>
              {brand.brandName && <h1 style={{ color: brand.accentColor }} className="text-lg font-bold">{brand.brandName}</h1>}
              <span className="text-xs text-white/50">Employee Parking Portal</span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm text-white/70">{user.email}</span>
            <button onClick={() => logout()} className="text-xs text-white/40 hover:text-white transition-colors">Sign out</button>
          </div>
        </div>
      </nav>

      <main className="max-w-3xl mx-auto px-6 py-10">
        {loading || renewalLoading ? (
          <div className="flex justify-center py-20"><Spin size="large" /></div>
        ) : (
          <div className="space-y-8">
            {/* Renewal card (from email link) */}
            {renewalSuccess && (
              <Alert
                type="success"
                showIcon
                icon={<CheckCircleOutlined />}
                message="Permit Renewed"
                description={renewalSuccess}
                className="!mb-2"
              />
            )}

            {renewalError && !renewalInfo && !renewalSuccess && (
              <Alert type="error" showIcon message="Renewal Unavailable" description={renewalError} className="!mb-2" />
            )}

            {renewalInfo && !renewalSuccess && (
              <Card className="border-l-4 border-l-green-500 shadow-md">
                <h3 className="text-xl font-bold text-brand-primary mb-1">Renew Your Parking Permit</h3>
                <p className="text-sm text-gray-500 mb-4">Confirm the details below to renew. No payment required.</p>
                {renewalError && <Alert type="error" message={renewalError} className="!mb-4" />}
                <Descriptions column={1} size="small" className="mb-4">
                  <Descriptions.Item label="Name">{renewalInfo.permit_holder_name}</Descriptions.Item>
                  <Descriptions.Item label="Email">{renewalInfo.email}</Descriptions.Item>
                  <Descriptions.Item label="Type"><span className="capitalize">{renewalInfo.permit_type.replace(/_/g, " ")}</span></Descriptions.Item>
                  <Descriptions.Item label="Lots">{renewalInfo.lot_assignment}</Descriptions.Item>
                  <Descriptions.Item label="Current Plate(s)"><span className="font-mono">{renewalInfo.plates.join(", ")}</span></Descriptions.Item>
                  {renewalInfo.end_date && (
                    <Descriptions.Item label="Expires">
                      <span className={renewalInfo.expired ? "text-red-600 font-medium" : ""}>
                        {fmtDate(renewalInfo.end_date)}{renewalInfo.expired && " (expired)"}
                      </span>
                    </Descriptions.Item>
                  )}
                </Descriptions>
                <div className="border-t pt-4 mb-4">
                  <Checkbox checked={changePlate} onChange={e => setChangePlate(e.target.checked)}>
                    I need to update my license plate
                  </Checkbox>
                  {changePlate && (
                    <Input
                      value={newPlate}
                      onChange={e => setNewPlate(e.target.value.toUpperCase())}
                      placeholder="ABC1234"
                      className="mt-3 font-mono max-w-xs"
                    />
                  )}
                </div>
                <Button
                  type="primary"
                  size="large"
                  block
                  onClick={handleConfirmRenewal}
                  loading={renewalSubmitting}
                  disabled={changePlate && !newPlate}
                >
                  Confirm Renewal
                </Button>
                <p className="text-xs text-gray-400 text-center mt-2">No payment is required for faculty/staff renewals.</p>
              </Card>
            )}

            {/* Header */}
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-bold text-brand-primary">My Parking Permits</h2>
                <p className="text-gray-500 mt-1">View your permits and register new vehicles.</p>
              </div>
              {permitType && (
                <Button type="primary" onClick={() => setEnrolling(true)}>
                  + Register New Vehicle
                </Button>
              )}
            </div>

            {/* Enrollment info card */}
            {permitType && (
              <Card size="small" className="border-l-4 border-l-brand-primary">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-medium text-brand-primary">{permitType.label}</span>
                    <span className="text-sm text-gray-500 ml-3">{permitType.eligible}</span>
                    <span className="text-sm text-gray-400 ml-3">
                      Lots: {permitType.lot_assignments.join(", ")}
                    </span>
                  </div>
                  <Tag color="green" className="!text-xs !m-0">Free</Tag>
                </div>
              </Card>
            )}

            {/* Active permits */}
            {activeVehicles.length > 0 && (
              <div>
                <h3 className="text-lg font-semibold text-brand-primary mb-3">Active Permits</h3>
                <div className="space-y-3">
                  {activeVehicles.map(v => (
                    <Card key={v.id} className="hover:shadow-md transition-shadow">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="flex items-center gap-3">
                            <span className="font-mono text-lg font-bold text-brand-primary">{v.plate}</span>
                            <Tag color="green">Active</Tag>
                            {v.permit_type_label && (
                              <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded">{v.permit_type_label}</span>
                            )}
                          </div>
                          <div className="text-sm text-gray-500 mt-1">
                            {v.name}
                            {v.permit_number && <span className="ml-2 text-gray-400">Permit #{v.permit_number}</span>}
                          </div>
                          <div className="text-xs text-gray-400 mt-1">
                            Lots: {v.lot_assignment}
                            {v.end_date && <span className="ml-2">· Expires {fmtDate(v.end_date)}</span>}
                          </div>
                        </div>
                        {v.permit_type === "faculty_staff" && (
                          <Button size="small" danger onClick={() => handleRemove(v)}>Remove</Button>
                        )}
                      </div>
                    </Card>
                  ))}
                </div>
              </div>
            )}

            {/* Past / expired / renewed permits */}
            {pastVehicles.length > 0 && (
              <div>
                <h3 className="text-lg font-semibold text-gray-400 mb-3">Past Permits</h3>
                <div className="space-y-2">
                  {pastVehicles.map(v => (
                    <Card key={v.id} className="opacity-60">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <span className="font-mono font-medium text-gray-500">{v.plate}</span>
                          <Tag color="default">{v.status}</Tag>
                          {v.permit_type_label && (
                            <span className="text-xs text-gray-400">{v.permit_type_label}</span>
                          )}
                        </div>
                        <div className="text-xs text-gray-400">
                          {v.start_date && fmtDate(v.start_date)}
                          {v.end_date && <> — {fmtDate(v.end_date)}</>}
                        </div>
                      </div>
                    </Card>
                  ))}
                </div>
              </div>
            )}

            {activeVehicles.length === 0 && pastVehicles.length === 0 && !permitType && (
              <Card className="text-center py-12">
                <Empty description={<span className="text-gray-500">No permits found. Contact the {brand.departmentName} for assistance.</span>} />
              </Card>
            )}

            {activeVehicles.length === 0 && pastVehicles.length === 0 && permitType && (
              <Card className="text-center py-12">
                <Empty description={<span className="text-gray-500">You don't have any registered vehicles yet. Click "Register New Vehicle" above to get started.</span>} />
              </Card>
            )}

            <div className="text-center text-xs text-gray-400 pt-4 border-t">
              {brand.schoolName || "Campus"} {brand.departmentName}{brand.brandName ? ` — ${brand.brandName}` : ""}
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
  const brand = useBranding();
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
            <Button type="primary" htmlType="submit" loading={submitting} style={{ background: brand.primaryColor }}>Register Vehicle</Button>
          </div>
        </Form>
      )}
    </Modal>
  );
}
