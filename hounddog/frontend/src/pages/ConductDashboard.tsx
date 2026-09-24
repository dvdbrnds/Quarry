import { useCallback, useEffect, useState } from "react";
import { App, Button, Descriptions, Empty, Input, Modal, Segmented, Space, Spin, Table, Tag } from "antd";
import { PrinterOutlined, DownloadOutlined, CheckCircleOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { initAuth, isAuthenticated, login, authHeaders, fetchCurrentUser, type AuthUser } from "../auth";
import { useBranding } from "../useBranding";
import PublicPageNav from "../components/PublicPageNav";
import PublicFooter from "../components/PublicFooter";

interface PermitInfo {
  permit_id: string;
  permit_number: string | null;
  permit_type: string;
  lot_zone: string;
  plates: string[];
  status: string;
  is_tag_only: boolean;
  name: string;
  email: string;
}

interface CaseRow {
  id: string;
  student_id: string;
  student_name: string;
  student_email: string;
  plate: string;
  ticket_count: number;
  ticket_ids: string[];
  status: string;
  details: string | null;
  created_at: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  permit: PermitInfo | null;
}

interface TicketDetail {
  id: string;
  ticket_number: string | null;
  plate: string;
  lot: string;
  violation_type: string;
  fine_amount: string;
  status: string;
  issued_at: string | null;
  officer_name: string | null;
  officer_notes: string | null;
  vehicle_description: string | null;
  photo_url: string | null;
  appeal_decision: string | null;
  appeal_note: string | null;
  owner_name: string | null;
  notification_email: string | null;
  location_text: string | null;
  location_lat: number | null;
  location_lng: number | null;
  _extra?: boolean;
}

interface CaseDetail extends CaseRow {
  tickets: TicketDetail[];
}

type StatusFilter = "all" | "active" | "resolved";

const STATUS_COLORS: Record<string, string> = {
  sent: "red",
  resolved: "green",
  paid: "green",
  unpaid: "orange",
  voided: "default",
  appealed: "blue",
};

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export default function ConductDashboard() {
  return (
    <App>
      <ConductPage />
    </App>
  );
}

function ConductPage() {
  const brand = useBranding();
  const { message } = App.useApp();
  const [authState, setAuthState] = useState<"loading" | "ready" | "error">("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<StatusFilter>("active");
  const [selected, setSelected] = useState<CaseDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [resolveNote, setResolveNote] = useState("");
  const [resolveModalOpen, setResolveModalOpen] = useState(false);
  const [newNote, setNewNote] = useState("");
  const [noteSaving, setNoteSaving] = useState(false);

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

  const loadCases = useCallback(async () => {
    setLoading(true);
    try {
      const headers = await authHeaders();
      const res = await fetch(`/api/conduct/cases?status=${filter}`, { headers });
      if (res.status === 403) {
        setAuthState("error");
        return;
      }
      if (!res.ok) throw new Error("Failed to load cases");
      setCases(await res.json());
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setLoading(false);
    }
  }, [filter, message]);

  useEffect(() => {
    if (authState === "ready") loadCases();
  }, [authState, loadCases]);

  async function openCase(row: CaseRow) {
    setDetailLoading(true);
    try {
      const headers = await authHeaders();
      const res = await fetch(`/api/conduct/cases/${row.id}`, { headers });
      if (!res.ok) throw new Error("Failed to load case details");
      setSelected(await res.json());
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleResolve() {
    if (!selected) return;
    setResolving(true);
    try {
      const headers = await authHeaders();
      const res = await fetch(`/api/conduct/cases/${selected.id}/resolve`, {
        method: "PUT",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ note: resolveNote }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to resolve");
      }
      message.success("Case resolved");
      setResolveModalOpen(false);
      setResolveNote("");
      setSelected(null);
      loadCases();
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setResolving(false);
    }
  }

  async function handleAddNote() {
    if (!selected || !newNote.trim()) return;
    setNoteSaving(true);
    try {
      const headers = await authHeaders();
      const res = await fetch(`/api/conduct/cases/${selected.id}/note`, {
        method: "PUT",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ note: newNote.trim() }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed to save note");
      }
      const data = await res.json();
      setSelected(prev => prev ? { ...prev, details: data.details } : null);
      setNewNote("");
      message.success("Note saved");
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setNoteSaving(false);
    }
  }

  function handlePrint() {
    if (!selected) return;
    const w = window.open("", "_blank");
    if (!w) return;
    const p = selected.permit;
    w.document.write(`<!DOCTYPE html><html><head><title>Conduct Case — ${selected.student_name}</title>
      <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 24px; max-width: 800px; margin: 0 auto; }
        h1 { font-size: 18px; margin-bottom: 4px; }
        h2 { font-size: 15px; margin: 16px 0 8px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
        .sub { font-size: 12px; color: #666; margin-bottom: 16px; }
        table { border-collapse: collapse; width: 100%; font-size: 13px; margin-bottom: 16px; }
        th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
        th { background: #f5f5f5; font-weight: 600; }
        .mono { font-family: monospace; }
        .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 16px; font-size: 13px; margin-bottom: 12px; }
        .info-grid dt { color: #666; }
        .info-grid dd { margin: 0; font-weight: 600; }
        @media print { body { padding: 0; } }
      </style></head><body>
      <h1>Conduct Referral — ${selected.student_name || selected.student_id}</h1>
      <div class="sub">Referred ${fmtDate(selected.created_at)} · ${selected.ticket_count} violation${selected.ticket_count !== 1 ? "s" : ""} · Status: ${selected.status}</div>
      <h2>Student Information</h2>
      <dl class="info-grid">
        <dt>Name</dt><dd>${selected.student_name || "—"}</dd>
        <dt>Email</dt><dd>${selected.student_email || "—"}</dd>
        <dt>Student ID</dt><dd>${selected.student_id || "—"}</dd>
        <dt>Plate</dt><dd class="mono">${selected.plate || "—"}</dd>
        ${p ? `<dt>Permit</dt><dd>${p.is_tag_only ? "Vehicle Tag" : (p.permit_type || "").replace(/_/g, " ")} ${p.permit_number ? "#" + p.permit_number : ""}</dd>
        <dt>Lot</dt><dd>${p.lot_zone || "—"}</dd>` : ""}
      </dl>
      <h2>Citations (${selected.tickets.length})</h2>
      <table>
        <tr><th>#</th><th>Plate</th><th>Violation</th><th>Lot</th><th>Fine</th><th>Status</th><th>Issued</th><th>Officer</th></tr>
        ${selected.tickets.map(t => `<tr>
          <td>${t.ticket_number || "—"}</td>
          <td class="mono">${t.plate}</td>
          <td>${(t.violation_type || "").replace(/_/g, " ")}</td>
          <td>${t.lot || "—"}</td>
          <td>$${Number(t.fine_amount).toFixed(2)}</td>
          <td>${t.status}</td>
          <td>${fmtDate(t.issued_at)}</td>
          <td>${t.officer_name || "—"}</td>
        </tr>`).join("")}
      </table>
      ${selected.details ? `<h2>Notes</h2><p style="font-size:13px;white-space:pre-wrap;">${selected.details}</p>` : ""}
      <div class="sub" style="margin-top:24px;">Printed ${new Date().toLocaleString()} by ${user?.email || ""}</div>
    </body></html>`);
    w.document.close();
    w.print();
  }

  function exportCSV() {
    const rows = cases.map(c => ({
      "Student Name": c.student_name || "",
      "Student Email": c.student_email || "",
      "Student ID": c.student_id || "",
      "Plate": c.plate || "",
      "Ticket Count": c.ticket_count,
      "Permit Type": c.permit ? (c.permit.is_tag_only ? "Vehicle Tag" : c.permit.permit_type) : "",
      "Referred": c.created_at || "",
      "Status": c.status || "",
      "Resolved At": c.resolved_at || "",
      "Resolved By": c.resolved_by || "",
    }));
    if (rows.length === 0) return;
    const header = Object.keys(rows[0]).join(",");
    const csv = [header, ...rows.map(r =>
      Object.values(r).map(v => `"${String(v).replace(/"/g, '""')}"`).join(",")
    )].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `conduct-cases-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
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
        <PublicPageNav subtitle="Conduct Portal" />
        <main className="max-w-3xl mx-auto px-6 py-16 text-center">
          <p className="text-gray-500">You do not have access to this portal. Contact the parking office if you believe this is an error.</p>
          <Button type="primary" onClick={() => window.location.reload()} className="mt-4">Retry</Button>
        </main>
        <PublicFooter />
      </div>
    );
  }

  const columns: ColumnsType<CaseRow> = [
    {
      title: "Student",
      key: "student",
      render: (_: unknown, r: CaseRow) => (
        <div>
          <div className="font-semibold">{r.student_name || "—"}</div>
          <div className="text-xs text-gray-500">{r.student_email}</div>
        </div>
      ),
      sorter: (a, b) => (a.student_name || "").localeCompare(b.student_name || ""),
    },
    {
      title: "Student ID",
      dataIndex: "student_id",
      key: "student_id",
      width: 110,
      render: (v: string) => <span className="text-xs font-mono">{v || "—"}</span>,
    },
    {
      title: "Plate",
      dataIndex: "plate",
      key: "plate",
      width: 110,
      render: (v: string) => <span className="font-mono">{v || "—"}</span>,
    },
    {
      title: "Permit / Tag",
      key: "permit",
      width: 150,
      render: (_: unknown, r: CaseRow) => {
        if (!r.permit) return <span className="text-gray-400 text-xs">None</span>;
        const p = r.permit;
        return (
          <div>
            <Tag color={p.is_tag_only ? "cyan" : "blue"}>
              {p.is_tag_only ? "Vehicle Tag" : (p.permit_type || "").replace(/_/g, " ")}
            </Tag>
            {p.permit_number && <div className="text-xs text-gray-400">#{p.permit_number}</div>}
          </div>
        );
      },
    },
    {
      title: "Tickets",
      dataIndex: "ticket_count",
      key: "ticket_count",
      width: 80,
      align: "center",
      render: (v: number) => <span className="font-semibold text-red-600">{v}</span>,
      sorter: (a, b) => a.ticket_count - b.ticket_count,
    },
    {
      title: "Referred",
      dataIndex: "created_at",
      key: "created_at",
      width: 140,
      render: (v: string) => <span className="text-xs">{fmtDate(v)}</span>,
      sorter: (a, b) => (a.created_at || "").localeCompare(b.created_at || ""),
      defaultSortOrder: "descend",
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (v: string) => <Tag color={STATUS_COLORS[v] || "default"}>{v}</Tag>,
    },
    {
      title: "Resolved By",
      dataIndex: "resolved_by",
      key: "resolved_by",
      width: 160,
      render: (v: string | null, r: CaseRow) => v
        ? <div><div className="text-xs">{v}</div><div className="text-xs text-gray-400">{fmtDate(r.resolved_at)}</div></div>
        : <span className="text-gray-300">—</span>,
    },
  ];

  const ticketColumns: ColumnsType<TicketDetail> = [
    {
      title: "Ticket #",
      dataIndex: "ticket_number",
      key: "ticket_number",
      width: 100,
      render: (v: string) => <span className="font-mono text-xs">{v || "—"}</span>,
    },
    {
      title: "Plate",
      dataIndex: "plate",
      key: "plate",
      width: 100,
      render: (v: string) => <span className="font-mono">{v}</span>,
    },
    {
      title: "Violation",
      dataIndex: "violation_type",
      key: "violation_type",
      render: (v: string) => <span className="capitalize text-xs">{(v || "").replace(/_/g, " ")}</span>,
    },
    {
      title: "Lot",
      dataIndex: "lot",
      key: "lot",
      width: 60,
    },
    {
      title: "Fine",
      dataIndex: "fine_amount",
      key: "fine_amount",
      width: 80,
      render: (v: string) => <span className="font-semibold">${Number(v).toFixed(2)}</span>,
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      width: 90,
      render: (v: string) => <Tag color={STATUS_COLORS[v] || "default"}>{v}</Tag>,
    },
    {
      title: "Issued",
      dataIndex: "issued_at",
      key: "issued_at",
      width: 140,
      render: (v: string) => <span className="text-xs">{fmtDateTime(v)}</span>,
    },
    {
      title: "Officer",
      dataIndex: "officer_name",
      key: "officer",
      width: 120,
      render: (v: string) => <span className="text-xs">{v || "—"}</span>,
    },
    {
      title: "Appeal",
      dataIndex: "appeal_decision",
      key: "appeal",
      width: 90,
      render: (v: string | null) => v
        ? <Tag color={v === "approved" ? "green" : v === "denied" ? "red" : "orange"}>{v}</Tag>
        : null,
    },
  ];

  const totalFines = selected?.tickets.reduce((sum, t) => sum + Number(t.fine_amount), 0) ?? 0;

  return (
    <div className="min-h-screen bg-gray-50">
      <PublicPageNav subtitle="Conduct Portal" />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-xl font-bold text-gray-800">Conduct Referrals</h1>
            <p className="text-sm text-gray-500">Students referred for conduct review due to parking violations</p>
          </div>
          <Space>
            <Button icon={<DownloadOutlined />} size="small" onClick={exportCSV} disabled={cases.length === 0}>Export CSV</Button>
          </Space>
        </div>

        <div className="mb-4">
          <Segmented
            options={[
              { label: `Active (${cases.length && filter === "active" ? cases.length : "..."})`, value: "active" },
              { label: "Resolved", value: "resolved" },
              { label: "All", value: "all" },
            ]}
            value={filter}
            onChange={v => setFilter(v as StatusFilter)}
          />
        </div>

        <Table
          dataSource={cases}
          columns={columns}
          rowKey="id"
          loading={loading}
          size="small"
          pagination={{ pageSize: 25, showSizeChanger: true, showTotal: (t) => `${t} case${t !== 1 ? "s" : ""}` }}
          onRow={(r) => ({ onClick: () => openCase(r), className: "cursor-pointer" })}
          locale={{ emptyText: <Empty description={filter === "active" ? "No active conduct referrals" : "No conduct referrals found"} /> }}
        />
      </main>

      <PublicFooter />

      {/* Case Detail Modal */}
      <Modal
        open={!!selected}
        onCancel={() => setSelected(null)}
        title={
          <Space>
            <span>Conduct Case — {selected?.student_name || selected?.student_id || ""}</span>
            {selected?.status === "sent" && <Tag color="red">Active</Tag>}
            {selected?.status === "resolved" && <Tag color="green">Resolved</Tag>}
          </Space>
        }
        footer={
          <div className="flex items-center gap-2">
            <Button onClick={() => setSelected(null)}>Close</Button>
            <Button icon={<PrinterOutlined />} onClick={handlePrint}>Print</Button>
            <div className="flex-1" />
            {selected && selected.status !== "resolved" && (
              <Button
                type="primary"
                icon={<CheckCircleOutlined />}
                onClick={() => { setResolveNote(""); setResolveModalOpen(true); }}
              >
                Mark Resolved
              </Button>
            )}
          </div>
        }
        width="85vw"
        style={{ maxWidth: 1000 }}
        styles={{ body: { maxHeight: "80vh", overflow: "auto" } }}
        loading={detailLoading}
      >
        {selected && (
          <div className="space-y-4">
            {/* Student + Permit Info */}
            <Descriptions size="small" column={{ xs: 1, sm: 2 }} bordered>
              <Descriptions.Item label="Student Name">{selected.student_name || "—"}</Descriptions.Item>
              <Descriptions.Item label="Email">{selected.student_email || "—"}</Descriptions.Item>
              <Descriptions.Item label="Student ID">{selected.student_id || "—"}</Descriptions.Item>
              <Descriptions.Item label="Plate"><span className="font-mono">{selected.plate || "—"}</span></Descriptions.Item>
              {selected.permit && (
                <>
                  <Descriptions.Item label="Permit Type">
                    <Tag color={selected.permit.is_tag_only ? "cyan" : "blue"}>
                      {selected.permit.is_tag_only ? "Vehicle Tag" : (selected.permit.permit_type || "").replace(/_/g, " ")}
                    </Tag>
                    {selected.permit.permit_number && <span className="ml-2">#{selected.permit.permit_number}</span>}
                  </Descriptions.Item>
                  <Descriptions.Item label="Lot Assignment">{selected.permit.lot_zone || "—"}</Descriptions.Item>
                </>
              )}
              <Descriptions.Item label="Referred">{fmtDateTime(selected.created_at)}</Descriptions.Item>
              <Descriptions.Item label="Ticket Count"><span className="font-semibold text-red-600">{selected.ticket_count}</span></Descriptions.Item>
              {selected.resolved_at && (
                <>
                  <Descriptions.Item label="Resolved">{fmtDateTime(selected.resolved_at)}</Descriptions.Item>
                  <Descriptions.Item label="Resolved By">{selected.resolved_by || "—"}</Descriptions.Item>
                </>
              )}
            </Descriptions>

            {/* Notes */}
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
              <div className="text-xs font-medium text-gray-600 mb-2">Case Notes</div>
              {selected.details ? (
                <div className="text-sm whitespace-pre-wrap mb-3 bg-white rounded p-2 border border-gray-100 max-h-40 overflow-auto">{selected.details}</div>
              ) : (
                <div className="text-xs text-gray-400 mb-3 italic">No notes yet</div>
              )}
              <div className="flex gap-2">
                <Input.TextArea
                  rows={2}
                  value={newNote}
                  onChange={e => setNewNote(e.target.value)}
                  placeholder="Add a note..."
                  className="flex-1"
                  onPressEnter={e => { if (e.metaKey || e.ctrlKey) handleAddNote(); }}
                />
                <Button
                  type="primary"
                  size="small"
                  loading={noteSaving}
                  disabled={!newNote.trim()}
                  onClick={handleAddNote}
                  style={{ alignSelf: "flex-end" }}
                >
                  Add Note
                </Button>
              </div>
            </div>

            {/* Tickets */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-semibold text-sm">
                  Citations ({selected.tickets.length})
                  {selected.tickets.some(t => t._extra) && (
                    <span className="text-xs text-gray-400 font-normal ml-2">
                      includes tickets added after referral
                    </span>
                  )}
                </h3>
                <span className="text-sm font-semibold text-red-600">
                  Total: ${totalFines.toFixed(2)}
                </span>
              </div>
              <Table
                dataSource={selected.tickets}
                columns={ticketColumns}
                rowKey="id"
                size="small"
                pagination={false}
                scroll={{ y: 400 }}
                expandable={{
                  expandedRowRender: (t: TicketDetail) => (
                    <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm p-2">
                      {t.vehicle_description && (
                        <div><span className="text-gray-500">Vehicle:</span> {t.vehicle_description}</div>
                      )}
                      {t.officer_notes && (
                        <div className="col-span-2"><span className="text-gray-500">Officer Notes:</span> {t.officer_notes}</div>
                      )}
                      {t.appeal_note && (
                        <div className="col-span-2"><span className="text-gray-500">Appeal Note:</span> {t.appeal_note}</div>
                      )}
                      {t.location_lat && t.location_lng && (
                        <div>
                          <span className="text-gray-500">GPS:</span>{" "}
                          <a
                            href={`https://maps.google.com/?q=${t.location_lat},${t.location_lng}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:underline font-mono text-xs"
                          >
                            {t.location_lat.toFixed(6)}, {t.location_lng.toFixed(6)}
                          </a>
                        </div>
                      )}
                      {t.photo_url && (
                        <div className="col-span-2">
                          <img
                            src={t.photo_url}
                            alt="Citation photo"
                            className="max-w-xs rounded border mt-1"
                          />
                        </div>
                      )}
                    </div>
                  ),
                  rowExpandable: (t: TicketDetail) => !!(t.officer_notes || t.vehicle_description || t.photo_url || t.appeal_note || t.location_lat),
                }}
                rowClassName={(t: TicketDetail) => t._extra ? "bg-yellow-50" : ""}
              />
            </div>
          </div>
        )}
      </Modal>

      {/* Resolve Modal */}
      <Modal
        open={resolveModalOpen}
        onCancel={() => setResolveModalOpen(false)}
        title="Resolve Conduct Case"
        okText="Resolve"
        confirmLoading={resolving}
        onOk={handleResolve}
      >
        <p className="text-sm text-gray-600 mb-3">
          Mark this case as resolved. Add an optional note about the outcome.
        </p>
        <Input.TextArea
          rows={3}
          value={resolveNote}
          onChange={e => setResolveNote(e.target.value)}
          placeholder="e.g. Met with student, payment plan arranged, referred to Dean of Students..."
        />
      </Modal>
    </div>
  );
}
