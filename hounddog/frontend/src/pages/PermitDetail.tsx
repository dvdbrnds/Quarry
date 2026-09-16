import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, Lot, PermitNote, LegacyRecord } from "../api";
import { authHeaders } from "../auth";
import { fmtDateTimeCompact } from "../dateUtils";
import { Button, Card, Tag, Table, Tabs, Statistic, Spin, Empty, Alert, Space, App, Timeline, Modal, Select, DatePicker, Input } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

interface PermitHistory {
  permit: any; has_hold: boolean; unpaid_amount: string;
  tickets: any[]; payments: any[]; audit_log: any[]; prior_permits: any[]; duplicates: any[];
  notes: PermitNote[];
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
  const [payModalOpen, setPayModalOpen] = useState(false);
  const [payAmount, setPayAmount] = useState<string>("");

  // Notes state
  const [newNote, setNewNote] = useState("");
  const [addingNote, setAddingNote] = useState(false);

  // Permit type selector for temp assignment
  const [tempPermitType, setTempPermitType] = useState<string>("");
  const [permitTypes, setPermitTypes] = useState<{ code: string; label: string; lot_assignments: string[] }[]>([]);

  // Legacy Omnigo record state
  const [legacyRecord, setLegacyRecord] = useState<LegacyRecord | null>(null);
  const [legacyImporting, setLegacyImporting] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try { setData(await api.permits.history(id)); } catch { navigate("/permits"); } finally { setLoading(false); }
  }, [id, navigate]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    (async () => {
      try {
        const [lotsData, ptRes] = await Promise.all([
          api.lots.list(),
          fetch("/api/permit-types", { headers: await authHeaders() }).then(r => r.json()),
        ]);
        setLots(lotsData);
        if (Array.isArray(ptRes)) {
          setPermitTypes(ptRes.map((pt: any) => ({ code: pt.code, label: pt.label || pt.code, lot_assignments: pt.lot_assignments || [] })));
        }
      } catch (e) {
        console.error("Failed to load lots/permit types", e);
      }
    })();
  }, []);

  useEffect(() => {
    if (!data?.permit?.plates?.length) { setLegacyRecord(null); return; }
    let cancelled = false;
    Promise.all(data.permit.plates.map((plate: string) => api.legacy.lookup(plate)))
      .then((results) => {
        if (!cancelled) setLegacyRecord(results.find((r) => r != null) ?? null);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [data?.permit?.id]);

  function handleTempPermitTypeChange(code: string) {
    setTempPermitType(code);
    const pt = permitTypes.find(p => p.code === code);
    if (pt && pt.lot_assignments.length > 0) {
      setTempLotLots(pt.lot_assignments);
    }
  }

  async function handleTempLotSubmit() {
    if (!id || !tempLotExpiry || tempLotLots.length === 0) return;
    setTempLotLoading(true);
    try {
      await api.permits.tempLots(id, {
        lots: tempLotLots,
        expires_at: tempLotExpiry.toISOString(),
        reason: tempLotReason,
        permit_type: tempPermitType || undefined,
      });
      message.success("Temporary access assigned");
      setTempLotOpen(false);
      setTempLotLots([]);
      setTempLotExpiry(null);
      setTempLotReason("");
      setTempPermitType("");
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

  function openPayModal() {
    if (!data) return;
    setPayAmount(data.remaining_balance ? Number(data.remaining_balance).toFixed(2) : "0.00");
    setPayModalOpen(true);
  }

  async function handleSendPayment() {
    if (!id) return;
    setSendPayLoading(true);
    try {
      const amt = parseFloat(payAmount);
      if (isNaN(amt) || amt <= 0) {
        message.error("Please enter a valid amount");
        setSendPayLoading(false);
        return;
      }
      const res = await api.permits.sendPayment(id, amt);
      message.success(`Payment link sent to ${res.email} (${res.amount})`);
      setPayModalOpen(false);
      load();
    } catch (e: any) {
      message.error(e.message || "Failed to send payment link");
    } finally {
      setSendPayLoading(false);
    }
  }

  async function handleAddNote() {
    if (!id || !newNote.trim()) return;
    setAddingNote(true);
    try {
      await api.permits.addNote(id, newNote.trim());
      setNewNote("");
      message.success("Note added");
      load();
    } catch (e: any) {
      message.error(e.message || "Failed to add note");
    } finally {
      setAddingNote(false);
    }
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
    {
      key: "notes", label: <>Notes{(data.notes?.length || 0) > 0 && <Tag className="ml-1">{data.notes.length}</Tag>}</>,
      children: (
        <div className="space-y-4">
          <div className="flex gap-2">
            <Input.TextArea
              rows={2}
              placeholder="Add a note…"
              value={newNote}
              onChange={e => setNewNote(e.target.value)}
              onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); handleAddNote(); } }}
            />
            <Button type="primary" onClick={handleAddNote} loading={addingNote} disabled={!newNote.trim()}>
              Add
            </Button>
          </div>
          {(!data.notes || data.notes.length === 0) ? (
            <Empty description="No notes yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : (
            <div className="space-y-3">
              {data.notes.map((n: any) => (
                <Card key={n.id} size="small">
                  <div className="text-sm whitespace-pre-wrap">{n.note}</div>
                  <div className="text-xs text-ink-mute mt-2">
                    {n.created_by} &middot; {fmtDateTimeCompact(n.created_at)}
                  </div>
                </Card>
              ))}
            </div>
          )}
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
              {p.home_address && <div className="col-span-2"><span className="text-ink-mute">Address:</span> {p.home_address}</div>}
            </div>
            <Space className="mt-3">
              <Tag color={p.status === "active" ? "green" : p.status === "expired" || p.status === "renewed" ? "default" : "red"}>{p.status}</Tag>
              {data.has_hold && <Tag color="red">HOLD — ${data.unpaid_amount} unpaid</Tag>}
              {data.duplicates.length > 0 && <Tag color="orange">DUPLICATE PLATE</Tag>}
              {legacyRecord && <Tag color="orange">LEGACY RECORD</Tag>}
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
              <Button onClick={openPayModal} loading={sendPayLoading}>Send Payment Link</Button>
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
          message="Temporary Permit Assignment Active"
          description={
            <div className="flex items-center justify-between">
              <span>
                {p.original_permit_type && <><strong className="capitalize">{p.original_permit_type.replace(/_/g, " ")}</strong> → <strong className="capitalize">{p.permit_type.replace(/_/g, " ")}</strong> · </>}
                Original lots: <strong>{p.original_lot_assignment}</strong> · Temp lots: <strong>{p.lot_assignment}</strong> · Expires: <strong>{new Date(p.temp_lot_expires_at).toLocaleString()}</strong>
              </span>
              <Button size="small" danger onClick={handleRevertLots}>Revert Now</Button>
            </div>
          }
        />
      )}

      {legacyRecord && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-6">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Tag color="orange">LEGACY</Tag>
              <span className="font-medium text-amber-800">Omnigo Record Found for {legacyRecord.plate_normalized}</span>
            </div>
            {!legacyRecord.imported_at ? (
              <Button
                size="small"
                type="primary"
                loading={legacyImporting}
                onClick={async () => {
                  setLegacyImporting(true);
                  try {
                    await api.legacy.importTag(legacyRecord.id);
                    message.success("Imported as vehicle tag");
                    setLegacyRecord({ ...legacyRecord, imported_at: new Date().toISOString() });
                  } catch (e: any) {
                    message.error(e?.message || "Import failed");
                  } finally {
                    setLegacyImporting(false);
                  }
                }}
              >Import as Vehicle Tag</Button>
            ) : (
              <Tag color="green">Already Imported</Tag>
            )}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-1 text-sm">
            <div><span className="text-amber-600">Owner:</span> {legacyRecord.owner_name}</div>
            <div><span className="text-amber-600">Permit #:</span> {legacyRecord.permit_number || "—"}</div>
            <div><span className="text-amber-600">Type:</span> <span className="capitalize">{legacyRecord.permit_type}</span></div>
            <div><span className="text-amber-600">Lot/Zone:</span> {legacyRecord.lot_zone || "—"}</div>
            {legacyRecord.vehicle_description && (
              <div className="col-span-2"><span className="text-amber-600">Vehicle:</span> {legacyRecord.vehicle_description}</div>
            )}
            {legacyRecord.record_date && (
              <div><span className="text-amber-600">Recorded:</span> {legacyRecord.record_date}</div>
            )}
          </div>
        </div>
      )}

      <Card styles={{ body: { padding: 0 } }}><Tabs items={tabItems} className="px-4" /></Card>

      <Modal
        open={tempLotOpen}
        title="Temporary Permit Assignment"
        okText="Assign"
        onCancel={() => setTempLotOpen(false)}
        onOk={handleTempLotSubmit}
        confirmLoading={tempLotLoading}
        okButtonProps={{ disabled: tempLotLots.length === 0 || !tempLotExpiry }}
      >
        <div className="space-y-4 py-2">
          <div>
            <label className="block text-sm font-medium mb-1">Permit Type (optional — leave blank to keep current)</label>
            <Select
              placeholder="Keep current type"
              value={tempPermitType || undefined}
              onChange={handleTempPermitTypeChange}
              allowClear
              className="w-full"
              options={permitTypes.map(pt => ({ label: pt.label, value: pt.code }))}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Lots</label>
            <Select
              mode="multiple"
              placeholder="Select lots"
              value={tempLotLots}
              onChange={setTempLotLots}
              className="w-full"
              showSearch
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

      <Modal
        open={payModalOpen}
        title="Send Payment Link"
        okText="Send Payment Link"
        onCancel={() => setPayModalOpen(false)}
        onOk={handleSendPayment}
        confirmLoading={sendPayLoading}
        okButtonProps={{ disabled: !payAmount || parseFloat(payAmount) <= 0 }}
      >
        {data && (
          <div className="space-y-4 py-2">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div><span className="text-ink-mute">Permit Type:</span> <span className="capitalize">{data.permit_type_label || data.permit?.permit_type}</span></div>
              <div><span className="text-ink-mute">Full Price:</span> ${Number(data.permit_type_price || 0).toFixed(2)}</div>
              <div><span className="text-ink-mute">Amount Paid:</span> ${Number(data.amount_paid || 0).toFixed(2)}</div>
              <div><span className="text-ink-mute font-semibold">Remaining:</span> <span className="font-semibold">${Number(data.remaining_balance || 0).toFixed(2)}</span></div>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Amount to Charge</label>
              <Input
                prefix="$"
                type="number"
                step="0.01"
                min="0.01"
                value={payAmount}
                onChange={e => setPayAmount(e.target.value)}
                placeholder="0.00"
              />
              <div className="text-xs text-ink-mute mt-1">
                Defaults to the remaining balance. Override to charge a different amount.
              </div>
            </div>
            <div className="text-sm text-ink-mute">
              A Stripe checkout link will be emailed to <strong>{data.permit?.email}</strong>.
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
