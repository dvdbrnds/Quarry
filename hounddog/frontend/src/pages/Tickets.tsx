import React, { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Table, Input, Select, Tag, Button, Modal, Descriptions, Space, App, Image, Empty, Popconfirm } from "antd";
import type { ColumnsType } from "antd/es/table";
import { authHeaders } from "../auth";
import { useCurrentUser } from "../UserContext";

interface Ticket {
  id: string;
  ticket_number: string | null;
  plate: string;
  lot: string;
  zone: string | null;
  violation_type: string;
  fine_amount: string;
  photo_url: string | null;
  officer_id: string;
  officer_name: string | null;
  officer_email: string | null;
  owner_name: string | null;
  permit_number: string | null;
  issued_at: string;
  status: string;
  ticket_category: string;
  location_text: string | null;
  vehicle_description: string | null;
  driver_name: string | null;
  driver_license: string | null;
  officer_notes: string | null;
  appeal_note: string | null;
  appeal_decision: string | null;
  appeal_decided_by: string | null;
  dispute_name: string | null;
  dispute_email: string | null;
  dispute_phone: string | null;
}

const STATUS_COLORS: Record<string, string> = {
  issued: "red",
  overdue: "volcano",
  pending_payment: "orange",
  paid: "green",
  appealed: "gold",
  escalated: "purple",
  voided: "default",
};

export default function Tickets() {
  const { modal, message } = App.useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const user = useCurrentUser();
  const isAdmin = user?.role === "admin";
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState(searchParams.get("search") ?? "");
  const [statusFilter, setStatusFilter] = useState(searchParams.get("status") ?? "");
  const [categoryFilter, setCategoryFilter] = useState(searchParams.get("category") ?? "");
  const [selected, setSelected] = useState<Ticket | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [bulkVoiding, setBulkVoiding] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (statusFilter) params.set("status", statusFilter);
    if (categoryFilter) params.set("category", categoryFilter);
    setSearchParams(params, { replace: true });
  }, [search, statusFilter, categoryFilter, setSearchParams]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      qs.set("page", String(page));
      if (search) qs.set("search", search);
      if (statusFilter) qs.set("status", statusFilter);
      if (categoryFilter) qs.set("category", categoryFilter);
      const res = await fetch(`/api/tickets?${qs}`, { headers: await authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setTickets(data.items);
        setTotal(data.total);
      }
    } catch {
      message.error("Failed to load tickets");
    } finally {
      setLoading(false);
    }
  }, [page, search, statusFilter, categoryFilter, message]);

  useEffect(() => { load(); }, [load]);

  async function handleVoid(id: string) {
    if (!isAdmin) return;
    modal.confirm({
      title: "Void this ticket?",
      content: "This action will void the ticket and cannot be easily reversed.",
      okText: "Void Ticket",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await fetch(`/api/tickets/${id}/void`, { method: "POST", headers: await authHeaders() });
          message.success("Ticket voided");
          load();
          setSelected(null);
        } catch {
          message.error("Failed to void ticket");
        }
      },
    });
  }

  async function handleBulkVoid() {
    if (selectedRowKeys.length === 0) return;
    setBulkVoiding(true);
    try {
      const res = await fetch("/api/tickets/bulk-void", {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({ ids: selectedRowKeys }),
      });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Bulk void failed"); }
      const { voided, skipped } = await res.json();
      message.success(`${voided} ticket(s) voided${skipped > 0 ? `, ${skipped} skipped (already paid/voided)` : ""}`);
      setSelectedRowKeys([]);
      load();
    } catch (e: any) { message.error(e.message); }
    finally { setBulkVoiding(false); }
  }

  async function handleAppealDecision(id: string, decision: string) {
    if (!isAdmin) return;
    const decided_by = user?.email || "admin";
    try {
      await fetch(`/api/tickets/${id}/appeal/decide`, {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({ decision, decided_by }),
      });
      message.success(`Appeal ${decision}`);
      load();
      setSelected(null);
    } catch {
      message.error("Failed to process appeal decision");
    }
  }

  const columns: ColumnsType<Ticket> = [
    {
      title: "Ticket #",
      dataIndex: "ticket_number",
      key: "ticket_number",
      width: 120,
      render: (num: string | null) => <span className="font-mono text-brand-primary font-medium">{num || "—"}</span>,
    },
    {
      title: "Plate",
      dataIndex: "plate",
      key: "plate",
      render: (plate: string) => <span className="font-mono">{plate}</span>,
    },
    {
      title: "Location",
      key: "location",
      render: (_, t) => t.ticket_category === "moving" ? (t.location_text || "—") : t.lot,
    },
    {
      title: "Violation",
      key: "violation",
      render: (_, t) => (
        <Space>
          <span className="capitalize">{t.violation_type.replace(/_/g, " ")}</span>
          {t.ticket_category === "moving" && <Tag color="red">MOVING</Tag>}
        </Space>
      ),
    },
    {
      title: "Fine",
      dataIndex: "fine_amount",
      key: "fine",
      render: (amt: string) => `$${Number(amt).toFixed(2)}`,
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string) => (
        <Tag color={STATUS_COLORS[status] || "default"}>
          {status.replace("_", " ")}
        </Tag>
      ),
    },
    {
      title: "Issued",
      dataIndex: "issued_at",
      key: "issued_at",
      render: (d: string) => new Date(d).toLocaleDateString(),
    },
    {
      title: "Actions",
      key: "actions",
      width: 100,
      render: (_, t) =>
        isAdmin && !["paid", "voided"].includes(t.status) ? (
          <Button type="link" danger size="small" onClick={(e) => { e.stopPropagation(); handleVoid(t.id); }}>
            Void
          </Button>
        ) : null,
    },
  ];

  const [mailNoticesOpen, setMailNoticesOpen] = useState(false);
  const [pendingNotices, setPendingNotices] = useState<any[]>([]);
  const [noticesLoading, setNoticesLoading] = useState(false);
  const [markingMailed, setMarkingMailed] = useState(false);
  const printRef = useRef<HTMLDivElement>(null);

  async function loadPendingNotices() {
    setNoticesLoading(true);
    try {
      const res = await fetch("/api/tickets/mail-notices/pending", { headers: await authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setPendingNotices(data.tickets);
      }
    } catch { message.error("Failed to load pending notices"); }
    finally { setNoticesLoading(false); }
  }

  async function handleMarkMailed() {
    if (pendingNotices.length === 0) return;
    setMarkingMailed(true);
    try {
      const res = await fetch("/api/tickets/mail-notices/mark-mailed", {
        method: "POST", headers: await authHeaders(),
        body: JSON.stringify({ ticket_ids: pendingNotices.map(t => t.id) }),
      });
      if (res.ok) {
        const data = await res.json();
        message.success(`${data.marked} notice(s) marked as mailed`);
        setPendingNotices([]);
        setMailNoticesOpen(false);
      }
    } catch { message.error("Failed to mark notices"); }
    finally { setMarkingMailed(false); }
  }

  function handlePrintNotices() {
    const printWindow = window.open("", "_blank");
    if (!printWindow) return;
    printWindow.document.write(`
      <html><head><title>Mail Notices - Unpaid Citations</title>
      <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 0; margin: 0; }
        .notice { page-break-after: always; padding: 48px; max-width: 8.5in; margin: 0 auto; }
        .notice:last-child { page-break-after: auto; }
        .header { text-align: center; border-bottom: 2px solid #1a2744; padding-bottom: 16px; margin-bottom: 24px; }
        .header h1 { margin: 0; font-size: 18px; color: #1a2744; }
        .header p { margin: 4px 0 0; font-size: 12px; color: #666; }
        .details { border: 1px solid #ddd; border-radius: 4px; padding: 16px; margin: 16px 0; }
        .details table { width: 100%; border-collapse: collapse; }
        .details td { padding: 6px 8px; font-size: 13px; }
        .details td:first-child { color: #666; width: 140px; }
        .details td:last-child { font-weight: 600; }
        .warning { background: #fef2f2; border: 1px solid #fecaca; border-radius: 4px; padding: 12px 16px; margin: 20px 0; font-size: 12px; color: #991b1b; }
        .payment { text-align: center; margin: 24px 0; padding: 16px; background: #f8f9fa; border-radius: 4px; }
        .payment p { margin: 0 0 8px; font-size: 13px; }
        .payment .url { font-family: monospace; font-size: 11px; color: #1a2744; word-break: break-all; }
        .footer { text-align: center; font-size: 11px; color: #999; margin-top: 32px; border-top: 1px solid #eee; padding-top: 16px; }
        @media print { body { margin: 0; } .notice { padding: 0.5in; } }
      </style></head><body>`);
    for (const t of pendingNotices) {
      printWindow.document.write(`
        <div class="notice">
          <div class="header">
            <h1>MORAVIAN UNIVERSITY POLICE DEPARTMENT</h1>
            <p>Unpaid Parking Citation Notice</p>
          </div>
          <p style="font-size:13px;color:#333;">A parking citation was issued to a vehicle registered to this address. The citation remains unpaid and is now overdue. Failure to pay or appeal within 10 days of this notice may result in a state citation being issued through the local Magisterial District Court, which carries additional court costs and fees.</p>
          <div class="details"><table>
            <tr><td>Citation #</td><td>${t.ticket_number || t.id.slice(0, 8).toUpperCase()}</td></tr>
            <tr><td>License Plate</td><td style="font-family:monospace;letter-spacing:1px;">${t.plate}</td></tr>
            <tr><td>Violation</td><td>${(t.violation_type || "").replace(/_/g, " ")}</td></tr>
            <tr><td>Location</td><td>${t.lot || "—"}</td></tr>
            <tr><td>Date Issued</td><td>${t.issued_at ? new Date(t.issued_at).toLocaleDateString() : "—"}</td></tr>
            <tr><td>Fine Amount</td><td style="color:#dc2626;font-size:16px;">$${Number(t.fine_amount).toFixed(2)}</td></tr>
            <tr><td>Status</td><td>${t.status.toUpperCase()}</td></tr>
            ${t.vehicle_description ? `<tr><td>Vehicle</td><td>${t.vehicle_description}</td></tr>` : ""}
          </table></div>
          <div class="warning">
            <strong>NOTICE:</strong> If this citation is not paid or appealed within 10 days of the date on this notice, a state citation will be issued through the local Magisterial District Court, carrying mandatory court costs and fees — often totaling more than $100 on top of the fine itself.
          </div>
          <div class="payment">
            <p><strong>Pay Online:</strong></p>
            <p class="url">${t.payment_url}</p>
            <p style="margin-top:12px;font-size:11px;color:#666;">Or mail payment (check/money order) to:<br/>Moravian University Police Department<br/>119 West Greenwich Street, Bethlehem, PA 18018</p>
          </div>
          <div class="footer">
            <p>Moravian University Police Department &middot; 119 West Greenwich Street &middot; Bethlehem, PA 18018</p>
            <p>Questions? Contact us at campuspolice@moravian.edu</p>
          </div>
        </div>`);
    }
    printWindow.document.write("</body></html>");
    printWindow.document.close();
    printWindow.print();
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Tickets</h2>
        <Space>
          {isAdmin && selectedRowKeys.length > 0 && (
            <Popconfirm
              title={`Void ${selectedRowKeys.length} ticket(s)?`}
              description="This will void all selected tickets. Paid and already-voided tickets will be skipped."
              onConfirm={handleBulkVoid}
              okText="Void All"
              okButtonProps={{ danger: true, loading: bulkVoiding }}
            >
              <Button danger loading={bulkVoiding}>
                Void Selected ({selectedRowKeys.length})
              </Button>
            </Popconfirm>
          )}
          {isAdmin && (
            <Button onClick={() => { setMailNoticesOpen(true); loadPendingNotices(); }}>
              Mail Notices
            </Button>
          )}
        </Space>
      </div>

      <Space className="mb-4" wrap>
        <Input.Search
          placeholder="Search by ticket #, plate, or officer..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          onSearch={() => setPage(1)}
          style={{ width: 300 }}
          allowClear
        />
        <Select
          value={statusFilter || undefined}
          onChange={(val) => { setStatusFilter(val || ""); setPage(1); }}
          placeholder="All Statuses"
          allowClear
          style={{ width: 170 }}
          options={[
            { label: "Issued", value: "issued" },
            { label: "Overdue", value: "overdue" },
            { label: "Pending Payment", value: "pending_payment" },
            { label: "Paid", value: "paid" },
            { label: "Appealed", value: "appealed" },
            { label: "Escalated", value: "escalated" },
            { label: "Voided", value: "voided" },
          ]}
        />
        <Select
          value={categoryFilter || undefined}
          onChange={(val) => { setCategoryFilter(val || ""); setPage(1); }}
          placeholder="All Types"
          allowClear
          style={{ width: 140 }}
          options={[
            { label: "Parking", value: "parking" },
            { label: "Moving", value: "moving" },
          ]}
        />
      </Space>

      <Table
        dataSource={tickets}
        columns={columns}
        rowKey="id"
        loading={loading}
        rowSelection={isAdmin ? {
          selectedRowKeys,
          onChange: setSelectedRowKeys,
          getCheckboxProps: (t) => ({
            disabled: ["paid", "voided"].includes(t.status),
          }),
        } : undefined}
        onRow={(t) => ({ onClick: () => setSelected(t), className: "cursor-pointer" })}
        pagination={{
          current: page,
          total,
          pageSize: 50,
          onChange: setPage,
          showSizeChanger: false,
          showTotal: (t) => `${t} tickets`,
        }}
        locale={{ emptyText: <Empty description="No tickets found" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />

      <Modal
        open={!!selected}
        onCancel={() => setSelected(null)}
        title={
          <Space>
            {selected?.ticket_number || (selected?.ticket_category === "moving" ? "Citation Detail" : "Ticket Detail")}
            {selected?.ticket_category === "moving" && <Tag color="red">Moving Violation</Tag>}
          </Space>
        }
        footer={
          <Space>
            <Button onClick={() => setSelected(null)}>Close</Button>
            {isAdmin && selected?.appeal_decision === "pending" && (
              <>
                <Button type="primary" style={{ background: "#22C55E" }} onClick={() => handleAppealDecision(selected!.id, "approved")}>
                  Approve Appeal
                </Button>
                <Button danger onClick={() => handleAppealDecision(selected!.id, "denied")}>
                  Deny Appeal
                </Button>
              </>
            )}
            {isAdmin && selected && !["paid", "voided"].includes(selected.status) && (
              <Button danger type="primary" onClick={() => handleVoid(selected.id)}>Void Ticket</Button>
            )}
          </Space>
        }
        width={560}
      >
        {selected && (
          <div className="space-y-4">
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="Plate"><span className="font-mono">{selected.plate}</span></Descriptions.Item>
              <Descriptions.Item label={selected.ticket_category === "moving" ? "Location" : "Lot"}>
                {selected.ticket_category === "moving" ? (selected.location_text || "—") : selected.lot}
              </Descriptions.Item>
              <Descriptions.Item label="Violation">{selected.violation_type.replace(/_/g, " ")}</Descriptions.Item>
              <Descriptions.Item label="Fine">${Number(selected.fine_amount).toFixed(2)}</Descriptions.Item>
              <Descriptions.Item label="Status"><Tag color={STATUS_COLORS[selected.status]}>{selected.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="Officer">{selected.officer_name || selected.officer_id}</Descriptions.Item>
              {selected.owner_name && <Descriptions.Item label="Owner">{selected.owner_name}</Descriptions.Item>}
              {selected.permit_number && <Descriptions.Item label="Permit #">{selected.permit_number}</Descriptions.Item>}
              <Descriptions.Item label="Issued" span={2}>{new Date(selected.issued_at).toLocaleString()}</Descriptions.Item>
            </Descriptions>

            {selected.ticket_category === "moving" && (
              <div className="bg-red-50 border border-red-100 rounded-lg p-3 text-sm">
                <div className="font-medium text-red-800 mb-2">Driver & Vehicle</div>
                <Descriptions size="small" column={2}>
                  {selected.driver_name && <Descriptions.Item label="Driver">{selected.driver_name}</Descriptions.Item>}
                  {selected.driver_license && <Descriptions.Item label="License"><span className="font-mono">{selected.driver_license}</span></Descriptions.Item>}
                  {selected.vehicle_description && <Descriptions.Item label="Vehicle" span={2}>{selected.vehicle_description}</Descriptions.Item>}
                  {selected.officer_notes && <Descriptions.Item label="Notes" span={2}>{selected.officer_notes}</Descriptions.Item>}
                </Descriptions>
              </div>
            )}

            {selected.photo_url && (
              <Image src={selected.photo_url} alt="Violation photo" className="rounded-lg max-h-48 object-cover" />
            )}

            {selected.appeal_note && (
              <div className="bg-yellow-50 rounded-lg p-3 text-sm">
                <div className="font-medium text-yellow-800 mb-1">Appeal Note</div>
                <p>{selected.appeal_note}</p>
                {(selected.dispute_name || selected.dispute_email || selected.dispute_phone) && (
                  <div className="mt-2 pt-2 border-t border-yellow-200 text-xs text-ink-mute space-y-0.5">
                    {selected.dispute_name && <div>Name: <span className="text-ink">{selected.dispute_name}</span></div>}
                    {selected.dispute_email && (
                      <div>Email: <a href={`mailto:${selected.dispute_email}`} className="text-brand-primary hover:underline">{selected.dispute_email}</a></div>
                    )}
                    {selected.dispute_phone && <div>Phone: <span className="text-ink">{selected.dispute_phone}</span></div>}
                  </div>
                )}
                {selected.appeal_decision && (
                  <div className="mt-2 text-xs text-ink-mute">
                    Decision: <strong>{selected.appeal_decision}</strong>
                    {selected.appeal_decided_by && ` by ${selected.appeal_decided_by}`}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </Modal>

      <Modal
        open={mailNoticesOpen}
        onCancel={() => setMailNoticesOpen(false)}
        title="Mail Notices — Unpaid Guest/Visitor Citations"
        width={700}
        footer={
          <Space>
            <Button onClick={() => setMailNoticesOpen(false)}>Close</Button>
            {pendingNotices.length > 0 && (
              <>
                <Button onClick={handlePrintNotices}>Print Notices ({pendingNotices.length})</Button>
                <Button type="primary" loading={markingMailed} onClick={handleMarkMailed}>
                  Mark All as Mailed ({pendingNotices.length})
                </Button>
              </>
            )}
          </Space>
        }
      >
        <p className="text-sm text-ink-mute mb-4">
          Overdue citations for unregistered vehicles (guests/visitors) that have not yet received a mailed notice.
          Print these notices and mail them to the registered vehicle owner via DMV records.
        </p>
        {noticesLoading ? (
          <div className="text-center py-8 text-ink-mute">Loading...</div>
        ) : pendingNotices.length === 0 ? (
          <Empty description="No pending mail notices" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div ref={printRef}>
            <Table
              dataSource={pendingNotices}
              rowKey="id"
              size="small"
              pagination={false}
              scroll={{ y: 400 }}
              columns={[
                { title: "Ticket #", dataIndex: "ticket_number", width: 100, render: (v: string) => <span className="font-mono text-xs">{v || "—"}</span> },
                { title: "Plate", dataIndex: "plate", width: 100, render: (v: string) => <span className="font-mono">{v}</span> },
                { title: "Violation", dataIndex: "violation_type", render: (v: string) => <span className="capitalize text-xs">{(v || "").replace(/_/g, " ")}</span> },
                { title: "Lot", dataIndex: "lot", width: 60 },
                { title: "Fine", dataIndex: "fine_amount", width: 80, render: (v: string) => `$${Number(v).toFixed(2)}` },
                { title: "Issued", dataIndex: "issued_at", width: 100, render: (v: string) => v ? new Date(v).toLocaleDateString() : "—" },
                { title: "Status", dataIndex: "status", width: 90, render: (v: string) => <Tag color={STATUS_COLORS[v] || "default"}>{v}</Tag> },
              ]}
            />
          </div>
        )}
      </Modal>
    </div>
  );
}
