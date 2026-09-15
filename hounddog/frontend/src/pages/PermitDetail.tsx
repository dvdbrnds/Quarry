import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, Lot } from "../api";
import { fmtDateTimeCompact } from "../dateUtils";
import { Button, Card, Tag, Table, Tabs, Statistic, Spin, Empty, Alert, Space, App, Timeline, Modal, Select, DatePicker, Input } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

interface PermitHistory {
  permit: any; has_hold: boolean; unpaid_amount: string;
  tickets: any[]; payments: any[]; audit_log: any[]; prior_permits: any[]; duplicates: any[];
}

export default function PermitDetail() {
  const { modal, message } = App.useApp();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<PermitHistory | null>(null);
  const [loading, setLoading] = useState(true);

  // Temp lot assignment state
  const [tempLotOpen, setTempLotOpen] = useState(false);
  const [tempLotLots, setTempLotLots] = useState<string[]>([]);
  const [tempLotExpiry, setTempLotExpiry] = useState<dayjs.Dayjs | null>(null);
  const [tempLotReason, setTempLotReason] = useState("");
  const [tempLotLoading, setTempLotLoading] = useState(false);
  const [lots, setLots] = useState<Lot[]>([]);

  // Send payment state
  const [sendPayLoading, setSendPayLoading] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try { setData(await api.permits.history(id)); } catch { navigate("/permits"); } finally { setLoading(false); }
  }, [id, navigate]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.lots.list().then(setLots).catch(() => {}); }, []);

  async function handleTempLotSubmit() {
    if (!id || !tempLotExpiry || tempLotLots.length === 0) return;
    setTempLotLoading(true);
    try {
      await api.permits.tempLots(id, {
        lots: tempLotLots,
        expires_at: tempLotExpiry.toISOString(),
        reason: tempLotReason,
      });
      message.success("Temporary lot access assigned");
      setTempLotOpen(false);
      setTempLotLots([]);
      setTempLotExpiry(null);
      setTempLotReason("");
      load();
    } catch (e: any) {
      message.error(e.message || "Failed to assign temp lots");
    } finally {
      setTempLotLoading(false);
    }
  }

  function handleRevertLots() {
    if (!id) return;
    modal.confirm({
      title: "Revert temporary lot access?",
      content: "This will restore the permit's original lot assignment.",
      okText: "Revert",
      onOk: async () => {
        await api.permits.revertLots(id);
        message.success("Lot assignment reverted to original");
        load();
      },
    });
  }

  function handleSendPayment() {
    if (!id) return;
    modal.confirm({
      title: "Send payment link?",
      content: `A new Stripe checkout link will be created and emailed to the permit holder (${data?.permit?.email || "N/A"}).`,
      okText: "Send Payment Link",
      onOk: async () => {
        setSendPayLoading(true);
        try {
          const res = await api.permits.sendPayment(id);
          message.success(`Payment link sent to ${res.email} (${res.amount})`);
          load();
        } catch (e: any) {
          message.error(e.message || "Failed to send payment link");
        } finally {
          setSendPayLoading(false);
        }
      },
    });
  }

  function handleRenew() {
    if (!id) return;
    modal.confirm({
      title: "Renew this permit?", content: "A new permit will be created with fresh dates.",
      okText: "Renew",
      onOk: async () => { await api.permits.renew(id); message.success("Permit renewed"); load(); },
    });
  }

  function handleReactivate() {
    if (!id) return;
    modal.confirm({
      title: "Reactivate this permit?", content: "This will set the permit status back to active.",
      okText: "Reactivate",
      onOk: async () => { await api.permits.update(id, { status: "active" } as any); message.success("Permit reactivated"); load(); },
    });
  }

  function handleExtend() {
    if (!id) return;
    modal.confirm({
      title: "Extend permit by 7 days?",
      content: "This will add 7 days to the permit's expiration date. If the permit is already expired, the extension starts from today.",
      okText: "Extend 7 Days",
      onOk: async () => { await api.permits.extend(id); message.success("Permit extended by 7 days"); load(); },
    });
  }

  if (loading || !data) return <div className="flex justify-center py-12"><Spin size="large" /></div>;

  const p = data.permit;

  const ticketCols: ColumnsType<any> = [
    { title: "Ticket #", dataIndex: "ticket_number", key: "ticket_number", render: (v, t) => v ? <a href={`/tickets?search=${v}`} className="font-mono text-xs font-medium text-blue-600 hover:underline">{v}</a> : "—" },
    { title: "Date", dataIndex: "issued_at", key: "date", render: v => v ? fmtDateTimeCompact(v) : "—" },
    { title: "Violation", dataIndex: "violation_type", key: "type", render: v => <span className="capitalize">{v?.replace(/_/g, " ")}</span> },
    { title: "Lot", dataIndex: "lot", key: "lot" },
    { title: "Fine", dataIndex: "fine_amount", key: "fine", render: v => `$${v}` },
    { title: "Status", dataIndex: "status", key: "status", render: s => <Tag color={s === "paid" ? "green" : s === "voided" ? "default" : s === "warning" ? "orange" : "red"}>{s}</Tag> },
  ];

  const paymentCols: ColumnsType<any> = [
    { title: "Date", dataIndex: "paid_at", key: "date", render: v => v ? fmtDateTimeCompact(v) : "—" },
    { title: "Description", dataIndex: "description", key: "desc", render: (v: string, r: any) => v || r.payment_type?.replace(/_/g, " ") || "Payment" },
    { title: "Amount", dataIndex: "amount", key: "amount", render: v => `$${v}` },
    { title: "Method", dataIndex: "method", key: "method", render: v => <span className="capitalize">{v?.replace(/_/g, " ")}</span> },
  ];

  const relatedCols: ColumnsType<any> = [
    { title: "Permit #", dataIndex: "permit_number", key: "permit_number", render: v => v ? <span className="font-mono text-xs">{v}</span> : <span className="text-ink-mute">Legacy</span> },
    { title: "Name", dataIndex: "name", key: "name" },
    { title: "Type", dataIndex: "permit_type", key: "type", render: v => <span className="capitalize">{v}</span> },
    { title: "Status", dataIndex: "status", key: "status", render: v => <span className="capitalize">{v}</span> },
    { title: "Dates", key: "dates", render: (_, r) => `${r.start_date} — ${r.end_date || "∞"}` },
  ];

  const tabItems = [
    {
      key: "overview", label: "Overview",
      children: (
        <div className="space-y-4">
          <h3 className="font-semibold">Summary</h3>
          <div className="grid grid-cols-3 gap-4">
            <Card size="small"><Statistic title="Total Tickets" value={data.tickets.length} /></Card>
            <Card size="small"><Statistic title="Payments" value={data.payments.length} /></Card>
            <Card size="small"><Statistic title="Unpaid Balance" value={data.has_hold ? `$${data.unpaid_amount}` : "$0"} valueStyle={data.has_hold ? { color: "#ef4444" } : {}} /></Card>
          </div>
          {data.duplicates.length > 0 && (
            <Alert type="warning" message="Duplicate Plate Warning" description={data.duplicates.map((d: any) => (
              <div key={d.permit_id}>{d.name} — {d.overlapping_plates.join(", ")} — {d.permit_type} ({d.lot_assignment})</div>
            ))} />
          )}
        </div>
      ),
    },
    {
      key: "tickets", label: <>Tickets{data.tickets.length > 0 && <Tag className="ml-1">{data.tickets.length}</Tag>}</>,
      children: <Table dataSource={data.tickets} columns={ticketCols} rowKey="id" size="small" pagination={false}
        locale={{ emptyText: <Empty description="No tickets issued" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }} />,
    },
    {
      key: "payments", label: "Payments",
      children: <Table dataSource={data.payments} columns={paymentCols} rowKey="id" size="small" pagination={false}
        locale={{ emptyText: <Empty description="No payments recorded" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }} />,
    },
    {
      key: "timeline", label: "Timeline",
      children: data.audit_log.length === 0
        ? <Empty description="No activity recorded" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        : <Timeline items={data.audit_log.map((entry: any) => {
            const actionColors: Record<string, string> = {
              CREATE: "green", APPLY: "blue", PAYMENT: "gold",
              UPDATE: "cyan", POST: "green", PUT: "cyan",
              PATCH: "cyan", DELETE: "red",
            };
            return {
              children: (
                <div className="flex gap-3 items-start">
                  <div className="flex-1"><div className="text-sm">{entry.summary}</div><div className="text-xs text-ink-mute">{fmtDateTimeCompact(entry.timestamp)} — {entry.user_email}</div></div>
                  <Tag color={actionColors[entry.action] || "default"}>{entry.action}</Tag>
                </div>
              ),
            };
          })} />,
    },
    {
      key: "related", label: "Related",
      children: (
        <div>
          <h3 className="font-semibold mb-3">Prior / Related Permits</h3>
          <Table dataSource={data.prior_permits} columns={relatedCols} rowKey="id" size="small" pagination={false}
            onRow={r => ({ onClick: () => navigate(`/permits/${r.id}`), className: "cursor-pointer" })}
            locale={{ emptyText: <Empty description="No related permits" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }} />
        </div>
      ),
    },
  ];

  return (
    <div>
      <Button type="link" onClick={() => navigate("/permits")} className="mb-4 px-0">&larr; Back to Permits</Button>

      <Card className="mb-6">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-baseline gap-3">
              <h2 className="text-2xl font-bold">{p.name}</h2>
              {p.permit_number && <span className="font-mono text-sm bg-brand-primary/10 rounded px-2 py-0.5">{p.permit_number}</span>}
            </div>
            <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-x-6 gap-y-2 text-sm">
              <div><span className="text-ink-mute">Student ID:</span> {p.student_id || "N/A"}</div>
              <div><span className="text-ink-mute">Plates:</span> <span className="font-mono">{p.plates?.join(", ")}</span></div>
              <div><span className="text-ink-mute">Type:</span> <span className="capitalize">{p.permit_type?.replace(/_/g, " ")}</span></div>
              <div><span className="text-ink-mute">SMS:</span> {p.sms_opt_in ? <Tag color="green">Opted In</Tag> : <Tag>Not opted in</Tag>}</div>
              <div className="col-span-2"><span className="text-ink-mute">Lot:</span> {p.lot_assignment}</div>
              <div><span className="text-ink-mute">Email:</span> {p.email || <span className="text-ink-mute italic">No email</span>}</div>
              <div><span className="text-ink-mute">Phone:</span> {p.phone || "—"}</div>
            </div>
            <Space className="mt-3">
              <Tag color={p.status === "active" ? "green" : p.status === "expired" || p.status === "renewed" ? "default" : "red"}>{p.status}</Tag>
              {data.has_hold && <Tag color="red">HOLD — ${data.unpaid_amount} unpaid</Tag>}
              {data.duplicates.length > 0 && <Tag color="orange">DUPLICATE PLATE</Tag>}
            </Space>
            <div className="mt-4 flex gap-4 text-sm"><span>Start: {p.start_date || "—"}</span><span>End: {p.end_date || "No expiry"}</span></div>
          </div>
          <Space wrap>
            <Button onClick={() => navigate(`/permits?edit=${id}`)}>Edit</Button>
            {(p.status === "revoked" || p.status === "suspended" || p.status === "expired") && (
              <Button onClick={handleReactivate}>Reactivate</Button>
            )}
            {(p.status === "expired" || p.status === "active") && (
              <Button onClick={handleExtend}>Extend 7 Days</Button>
            )}
            <Button onClick={() => setTempLotOpen(true)}>Temp Lot Access</Button>
            {p.email && (
              <Button onClick={handleSendPayment} loading={sendPayLoading}>Send Payment Link</Button>
            )}
            {(p.status === "expired" || p.status === "active") && (
              <Button type="primary" onClick={handleRenew}>Renew</Button>
            )}
          </Space>
        </div>
      </Card>

      {p.original_lot_assignment && p.temp_lot_expires_at && (
        <Alert
          type="info"
          className="mb-6"
          showIcon
          message="Temporary Lot Access Active"
          description={
            <div className="flex items-center justify-between">
              <span>
                Original lots: <strong>{p.original_lot_assignment}</strong> · Temp lots: <strong>{p.lot_assignment}</strong> · Expires: <strong>{new Date(p.temp_lot_expires_at).toLocaleString()}</strong>
              </span>
              <Button size="small" danger onClick={handleRevertLots}>Revert Now</Button>
            </div>
          }
        />
      )}

      <Card styles={{ body: { padding: 0 } }}><Tabs items={tabItems} className="px-4" /></Card>

      <Modal
        open={tempLotOpen}
        title="Temporary Lot Access"
        okText="Assign"
        onCancel={() => setTempLotOpen(false)}
        onOk={handleTempLotSubmit}
        confirmLoading={tempLotLoading}
        okButtonProps={{ disabled: tempLotLots.length === 0 || !tempLotExpiry }}
      >
        <div className="space-y-4 py-2">
          <div>
            <label className="block text-sm font-medium mb-1">Lots</label>
            <Select
              mode="multiple"
              placeholder="Select lots"
              value={tempLotLots}
              onChange={setTempLotLots}
              className="w-full"
              options={lots.map(l => ({ label: l.name, value: l.name }))}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Expires At</label>
            <DatePicker
              showTime
              className="w-full"
              value={tempLotExpiry}
              onChange={setTempLotExpiry}
              disabledDate={d => d.isBefore(dayjs(), "day")}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Reason (optional)</label>
            <Input.TextArea
              rows={2}
              placeholder="e.g. Lot closed for event, construction, etc."
              value={tempLotReason}
              onChange={e => setTempLotReason(e.target.value)}
            />
          </div>
        </div>
      </Modal>
    </div>
  );
}
