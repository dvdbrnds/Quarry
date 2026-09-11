import { useEffect, useState } from "react";
import { Button, Card, Empty, Space, Spin, Tag, Table, App, Segmented, Descriptions, Modal, Form, Input, DatePicker, Popconfirm } from "antd";
import { DownloadOutlined, PrinterOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { initAuth, isAuthenticated, login, authHeaders, fetchCurrentUser, type AuthUser } from "../auth";
import { useBranding } from "../useBranding";
import PublicPageNav from "../components/PublicPageNav";
import PublicFooter from "../components/PublicFooter";

interface SponsorPermit {
  permit_id: string;
  permit_number: string | null;
  name: string;
  company_name: string;
  plate: string;
  student_name: string;
  instructor_name: string;
  work_description: string;
  sponsor_department: string;
  start_date: string;
  end_date: string | null;
  status: string;
  decision: string | null;
  token: string;
  created_at: string;
}

type StatusFilter = "all" | "pending_approval" | "active" | "denied";

const STATUS_COLORS: Record<string, string> = {
  pending_approval: "orange",
  active: "green",
  denied: "red",
  expired: "default",
};

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso + (iso.includes("T") ? "" : "T00:00"));
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export default function SponsorDashboard() {
  return (
    <App>
      <SponsorPage />
    </App>
  );
}

function SponsorPage() {
  const brand = useBranding();
  const { message } = App.useApp();
  const [authState, setAuthState] = useState<"loading" | "ready" | "error">("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [permits, setPermits] = useState<SponsorPermit[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [deciding, setDeciding] = useState<string | null>(null);
  const [selected, setSelected] = useState<SponsorPermit | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    (async () => {
      try {
        await initAuth();
        const authed = await isAuthenticated();
        if (!authed) {
          sessionStorage.setItem("quarry_return_path", window.location.pathname);
          await login();
          return;
        }
        const u = await fetchCurrentUser();
        setUser(u);
        setAuthState(u ? "ready" : "error");
      } catch {
        setAuthState("error");
      }
    })();
  }, []);

  useEffect(() => {
    if (authState === "ready") loadPermits();
  }, [authState]);

  async function loadPermits() {
    setLoading(true);
    try {
      const headers = await authHeaders();
      const res = await fetch("/api/visitor/permits/sponsor/my-permits", { headers });
      if (!res.ok) throw new Error("Failed to load permits");
      setPermits(await res.json());
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDecision(token: string, decision: "approved" | "denied") {
    setDeciding(token);
    try {
      const headers = await authHeaders();
      const res = await fetch(`/api/visitor/permits/sponsor/decide/${token}`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to submit decision");
      }
      message.success(decision === "approved" ? "Permit approved!" : "Permit denied.");
      await loadPermits();
      setSelected(null);
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setDeciding(null);
    }
  }

  function openDetail(permit: SponsorPermit) {
    setSelected(permit);
    setEditing(false);
    form.setFieldsValue({
      name: permit.name,
      plate: permit.plate,
      end_date: permit.end_date ? dayjs(permit.end_date) : null,
    });
  }

  async function handleSave() {
    if (!selected) return;
    setSaving(true);
    try {
      const values = form.getFieldsValue();
      const headers = await authHeaders();
      const res = await fetch(`/api/visitor/permits/sponsor/permit/${selected.token}`, {
        method: "PATCH",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          name: values.name,
          plate: values.plate,
          end_date: values.end_date ? values.end_date.format("YYYY-MM-DD") : null,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to save changes");
      }
      message.success("Permit updated.");
      setEditing(false);
      setSelected(null);
      await loadPermits();
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleRevoke() {
    if (!selected) return;
    setSaving(true);
    try {
      const headers = await authHeaders();
      const res = await fetch(`/api/visitor/permits/sponsor/permit/${selected.token}`, {
        method: "PATCH",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ revoke: true }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to revoke permit");
      }
      message.success("Permit revoked.");
      setSelected(null);
      await loadPermits();
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!selected) return;
    setSaving(true);
    try {
      const headers = await authHeaders();
      const res = await fetch(`/api/visitor/permits/sponsor/permit/${selected.token}`, {
        method: "PATCH",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ remove: true }),
      });
      if (!res.ok) {
        const text = await res.text();
        let detail = "Failed to delete";
        try { detail = JSON.parse(text).detail || `${res.status}: ${text.slice(0, 200)}`; } catch { detail = `${res.status}: ${text.slice(0, 200)}`; }
        throw new Error(detail);
      }
      message.success("Permit deleted.");
      setSelected(null);
      await loadPermits();
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setSaving(false);
    }
  }

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
      <div className="min-h-screen bg-gray-50">
        <PublicPageNav subtitle="Sponsor Dashboard" />
        <main className="max-w-3xl mx-auto px-6 py-16 text-center">
          <p className="text-gray-500">Unable to sign in. Please try again.</p>
          <Button type="primary" onClick={() => window.location.reload()} className="mt-4">Retry</Button>
        </main>
        <PublicFooter />
      </div>
    );
  }

  function exportCSV() {
    const rows = filtered.map(p => ({
      Vendor: p.name,
      Company: p.company_name,
      Student: p.student_name || "",
      Instructor: p.instructor_name || "",
      Plate: p.plate,
      Start: p.start_date || "",
      End: p.end_date || "",
      Status: p.status === "pending_approval" ? "Pending" : p.status,
      Decision: p.decision || "",
      Submitted: p.created_at || "",
    }));
    const header = Object.keys(rows[0] || {}).join(",");
    const csv = [header, ...rows.map(r =>
      Object.values(r).map(v => `"${String(v).replace(/"/g, '""')}"`).join(",")
    )].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `vendor-permits-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function handlePrint() {
    const rows = filtered;
    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(`<!DOCTYPE html><html><head><title>Vendor Permits</title>
      <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 24px; }
        h1 { font-size: 18px; margin-bottom: 4px; }
        .sub { font-size: 12px; color: #666; margin-bottom: 16px; }
        table { border-collapse: collapse; width: 100%; font-size: 13px; }
        th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
        th { background: #f5f5f5; font-weight: 600; }
        .mono { font-family: monospace; }
        @media print { body { padding: 0; } }
      </style></head><body>
      <h1>Vendor Permits</h1>
      <div class="sub">Sponsor: ${user?.email || ""} · Exported ${new Date().toLocaleDateString()} · ${rows.length} permit${rows.length !== 1 ? "s" : ""}</div>
      <table>
        <tr><th>Vendor</th><th>Company</th><th>Student</th><th>Plate</th><th>Duration</th><th>Status</th></tr>
        ${rows.map(r => `<tr>
          <td>${r.name}</td>
          <td>${r.company_name}</td>
          <td>${r.student_name || r.instructor_name || "—"}</td>
          <td class="mono">${r.plate}</td>
          <td>${fmtDate(r.start_date)}${r.end_date ? " — " + fmtDate(r.end_date) : ""}</td>
          <td>${r.status === "pending_approval" ? "Pending" : r.status}</td>
        </tr>`).join("")}
      </table></body></html>`);
    w.document.close();
    w.print();
  }

  const filtered = filter === "all" ? permits : permits.filter(p => p.status === filter);

  const columns: ColumnsType<SponsorPermit> = [
    {
      title: "Vendor",
      dataIndex: "name",
      key: "name",
      render: (v: string, r) => (
        <div>
          <div className="font-semibold">{v}</div>
          <div className="text-xs text-gray-500">{r.company_name}</div>
        </div>
      ),
    },
    {
      title: "Student",
      key: "student",
      render: (_, r) => (
        <div>
          {r.student_name && <div>{r.student_name}</div>}
          {r.instructor_name && <div className="text-xs text-gray-500">{r.instructor_name}</div>}
          {!r.student_name && !r.instructor_name && <span className="text-gray-400">—</span>}
        </div>
      ),
    },
    {
      title: "Vehicle",
      dataIndex: "plate",
      key: "plate",
      render: (v: string) => <span className="font-mono">{v}</span>,
    },
    {
      title: "Duration",
      key: "duration",
      render: (_, r) => (
        <span className="text-sm">
          {fmtDate(r.start_date)}{r.end_date ? ` — ${fmtDate(r.end_date)}` : ""}
        </span>
      ),
    },
    {
      title: "Status",
      key: "status",
      render: (_, r) => (
        <Tag color={STATUS_COLORS[r.status] || "default"}>
          {r.status === "pending_approval" ? "Pending" : r.status}
        </Tag>
      ),
      filters: [
        { text: "Pending", value: "pending_approval" },
        { text: "Active", value: "active" },
        { text: "Denied", value: "denied" },
      ],
      onFilter: (v, r) => r.status === v,
    },
    {
      title: "Actions",
      key: "actions",
      render: (_, r) => (
        <div className="flex gap-2 items-center">
          {r.status === "pending_approval" && !r.decision && (
            <>
              <Button
                size="small"
                type="primary"
                loading={deciding === r.token}
                onClick={(e) => { e.stopPropagation(); handleDecision(r.token, "approved"); }}
                style={{ background: brand.primaryColor }}
              >
                Approve
              </Button>
              <Button
                size="small"
                danger
                loading={deciding === r.token}
                onClick={(e) => { e.stopPropagation(); handleDecision(r.token, "denied"); }}
              >
                Deny
              </Button>
            </>
          )}
          {r.decision && (
            <Tag color={r.decision === "approved" ? "green" : "red"}>
              {r.decision === "approved" ? "Approved" : "Denied"}
            </Tag>
          )}
          <Popconfirm
            title="Delete this permit?"
            description="This will permanently remove this entry."
            onConfirm={async () => {
              try {
                const headers = await authHeaders();
                const res = await fetch(`/api/visitor/permits/sponsor/permit/${r.token}`, {
                  method: "PATCH",
                  headers: { ...headers, "Content-Type": "application/json" },
                  body: JSON.stringify({ remove: true }),
                });
                if (!res.ok) {
                  const text = await res.text();
                  let detail = "Failed to delete";
                  try { detail = JSON.parse(text).detail || `${res.status}: ${text.slice(0, 200)}`; } catch { detail = `${res.status}: ${text.slice(0, 200)}`; }
                  throw new Error(detail);
                }
                message.success("Permit deleted.");
                await loadPermits();
              } catch (e: any) { message.error(e.message); }
            }}
            okText="Delete"
            okButtonProps={{ danger: true }}
          >
            <Button size="small" danger type="text" onClick={(e) => e.stopPropagation()}>Delete</Button>
          </Popconfirm>
        </div>
      ),
    },
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      <PublicPageNav subtitle="Sponsor Dashboard" />
      <main className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-800">Your Vendor Permits</h1>
            <p className="text-sm text-gray-500 mt-1">
              Signed in as <span className="font-medium">{user.email}</span>
            </p>
          </div>
          <Button size="small" onClick={() => { import("../auth").then(a => a.logout()); }}>
            Sign Out
          </Button>
        </div>

        <Card className="shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <Segmented
              value={filter}
              onChange={v => setFilter(v as StatusFilter)}
              options={[
                { label: `All (${permits.length})`, value: "all" },
                { label: `Pending (${permits.filter(p => p.status === "pending_approval").length})`, value: "pending_approval" },
                { label: `Active (${permits.filter(p => p.status === "active").length})`, value: "active" },
                { label: `Denied (${permits.filter(p => p.status === "denied").length})`, value: "denied" },
              ]}
            />
            <Space size="small">
              <Button size="small" icon={<DownloadOutlined />} onClick={exportCSV} disabled={filtered.length === 0}>Export CSV</Button>
              <Button size="small" icon={<PrinterOutlined />} onClick={handlePrint} disabled={filtered.length === 0}>Print</Button>
              <Button size="small" onClick={loadPermits} loading={loading}>Refresh</Button>
            </Space>
          </div>

          <Table
            dataSource={filtered}
            columns={columns}
            rowKey="permit_id"
            loading={loading}
            pagination={false}
            locale={{ emptyText: <Empty description="No permits found" /> }}
            onRow={r => ({ onClick: () => openDetail(r), style: { cursor: "pointer" } })}
            size="middle"
          />
        </Card>
      </main>

      <Modal
        open={!!selected}
        onCancel={() => { setSelected(null); setEditing(false); }}
        destroyOnClose
        footer={
          !selected ? null : editing ? (
            <div className="flex gap-2 justify-end">
              <Button onClick={() => setEditing(false)}>Cancel</Button>
              <Button type="primary" loading={saving} onClick={handleSave} style={{ background: brand.primaryColor }}>
                Save Changes
              </Button>
            </div>
          ) : (
            <div className="flex justify-between">
              <div className="flex gap-2">
                {selected.status === "active" && (
                  <Popconfirm
                    title="Revoke this permit?"
                    description="The vendor will no longer be authorized to park."
                    onConfirm={handleRevoke}
                    okText="Revoke"
                    okButtonProps={{ danger: true }}
                  >
                    <Button danger loading={saving}>Revoke</Button>
                  </Popconfirm>
                )}
                <Popconfirm
                  title="Delete this permit request?"
                  description="This will permanently remove this entry."
                  onConfirm={handleDelete}
                  okText="Delete"
                  okButtonProps={{ danger: true }}
                >
                  <Button danger loading={saving}>Delete</Button>
                </Popconfirm>
              </div>
              <div className="flex gap-2">
                {selected.status === "pending_approval" && !selected.decision && (
                  <>
                    <Button
                      danger
                      loading={deciding === selected.token}
                      onClick={() => handleDecision(selected.token, "denied")}
                    >
                      Deny
                    </Button>
                    <Button
                      type="primary"
                      loading={deciding === selected.token}
                      onClick={() => handleDecision(selected.token, "approved")}
                      style={{ background: brand.primaryColor }}
                    >
                      Approve
                    </Button>
                  </>
                )}
                {(selected.status === "active" || selected.status === "pending_approval") && (
                  <Button onClick={() => setEditing(true)}>Edit</Button>
                )}
              </div>
            </div>
          )
        }
        title={editing ? "Edit Vendor Permit" : "Vendor Permit Details"}
        width={560}
      >
        {selected && !editing && (
          <Descriptions column={1} bordered size="small" className="mt-4">
            <Descriptions.Item label="Vendor Name">{selected.name}</Descriptions.Item>
            <Descriptions.Item label="Company">{selected.company_name}</Descriptions.Item>
            {selected.student_name && (
              <Descriptions.Item label="Student">{selected.student_name}</Descriptions.Item>
            )}
            {selected.instructor_name && (
              <Descriptions.Item label="Instructor / Ensemble">{selected.instructor_name}</Descriptions.Item>
            )}
            <Descriptions.Item label="Vehicle"><span className="font-mono">{selected.plate}</span></Descriptions.Item>
            <Descriptions.Item label="Work Description">{selected.work_description || "Not provided"}</Descriptions.Item>
            <Descriptions.Item label="Department">{selected.sponsor_department || "—"}</Descriptions.Item>
            <Descriptions.Item label="Duration">
              {fmtDate(selected.start_date)}{selected.end_date ? ` — ${fmtDate(selected.end_date)}` : ""}
            </Descriptions.Item>
            <Descriptions.Item label="Status">
              <Tag color={STATUS_COLORS[selected.status] || "default"}>
                {selected.status === "pending_approval" ? "Pending Approval" : selected.status}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Submitted">{fmtDate(selected.created_at)}</Descriptions.Item>
          </Descriptions>
        )}
        {selected && editing && (
          <Form form={form} layout="vertical" className="mt-4">
            <Form.Item label="Vendor Name" name="name" rules={[{ required: true, message: "Name is required" }]}>
              <Input />
            </Form.Item>
            <Form.Item label="License Plate" name="plate" rules={[{ required: true, message: "Plate is required" }]}>
              <Input style={{ textTransform: "uppercase", fontFamily: "monospace" }} />
            </Form.Item>
            <Form.Item label="End Date" name="end_date">
              <DatePicker className="w-full" />
            </Form.Item>
            <Descriptions column={1} size="small" className="mt-2">
              <Descriptions.Item label="Company">{selected.company_name}</Descriptions.Item>
              {selected.student_name && <Descriptions.Item label="Student">{selected.student_name}</Descriptions.Item>}
              {selected.instructor_name && <Descriptions.Item label="Instructor / Ensemble">{selected.instructor_name}</Descriptions.Item>}
              <Descriptions.Item label="Start Date">{fmtDate(selected.start_date)}</Descriptions.Item>
            </Descriptions>
          </Form>
        )}
      </Modal>

      <PublicFooter />
    </div>
  );
}
