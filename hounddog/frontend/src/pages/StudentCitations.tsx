import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";
import { Button, Card, Empty, Form, Input, Modal, Spin, Tag, App, Alert } from "antd";
import { useBranding } from "../useBranding";

interface TicketSummary {
  id: string;
  ticket_number: string | null;
  plate: string;
  lot: string;
  violation_type: string;
  fine_amount: string;
  status: string;
  issued_at: string;
  appeal_note: string | null;
  appeal_decision: string | null;
  appeal_decided_by: string | null;
  can_appeal: boolean;
  appeal_deadline: string | null;
}

export default function StudentCitations() {
  const { message } = App.useApp();
  const brand = useBranding();
  const [tickets, setTickets] = useState<TicketSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [appealWindowDays, setAppealWindowDays] = useState(5);
  const [appealTicket, setAppealTicket] = useState<TicketSummary | null>(null);

  // Plate/citation lookup
  const [lookupValue, setLookupValue] = useState("");
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupResult, setLookupResult] = useState<TicketSummary[] | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/appeals/my-tickets", { headers: await authHeaders() });
      if (!res.ok) throw new Error("Failed to load");
      const data = await res.json();
      setTickets(data.tickets);
      setAppealWindowDays(data.appeal_window_days);
    } catch {
      message.error("Unable to load your citations.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleLookup() {
    const val = lookupValue.trim();
    if (!val) return;
    setLookupLoading(true);
    setLookupResult(null);
    try {
      const headers = await authHeaders();
      const res = await fetch("/api/appeals/claim-plate", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ plate: val }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new Error(b.detail || "Lookup failed");
      }
      const data = await res.json();
      if (data.tickets.length > 0) {
        setLookupResult(data.tickets);
        // Refresh main list since claim-plate links tickets to this student
        load();
        message.success(`Found ${data.tickets.length} citation${data.tickets.length > 1 ? "s" : ""}`);
      } else {
        setLookupResult([]);
      }
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setLookupLoading(false);
    }
  }

  function statusTag(t: TicketSummary) {
    if (t.appeal_decision === "pending") return <Tag color="blue">Under Review</Tag>;
    if (t.appeal_decision === "approved") return <Tag color="green">Appeal Approved</Tag>;
    if (t.appeal_decision === "denied") return <Tag color="red">Appeal Denied</Tag>;
    if (t.status === "paid") return <Tag color="default">Paid</Tag>;
    if (t.status === "voided") return <Tag color="default">Voided</Tag>;
    if (t.status === "warning") return <Tag color="orange">Warning</Tag>;
    if (t.status === "resolved_permit") return <Tag color="default">Resolved</Tag>;
    if (t.status === "overdue") return <Tag color="orange">Overdue</Tag>;
    if (t.status === "escalated") return <Tag color="red">Escalated</Tag>;
    return <Tag color="gold">Issued</Tag>;
  }

  function renderTicket(t: TicketSummary) {
    const isPaid = ["paid", "voided", "warning", "resolved_permit"].includes(t.status) || t.appeal_decision === "approved";
    return (
      <Card key={t.id} className={isPaid ? "opacity-60" : ""}>
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className="font-mono font-bold">{t.plate}</span>
              {statusTag(t)}
            </div>
            <div className="text-sm text-ink-mute mt-1 capitalize">
              {t.violation_type.replace(/_/g, " ")} · {t.lot || "N/A"}
            </div>
            <div className="text-xs text-ink-mute mt-0.5">
              {new Date(t.issued_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" })}
              {t.ticket_number && <span className="ml-2 font-mono">#{t.ticket_number}</span>}
            </div>
            {t.appeal_decision === "pending" && (
              <div className="text-xs text-blue-600 mt-1">Your appeal is being reviewed</div>
            )}
            {t.appeal_decision === "denied" && (
              <div className="text-xs text-red-600 mt-1">Appeal denied — fine is still due</div>
            )}
            {t.appeal_decision === "approved" && (
              <div className="text-xs text-green-600 mt-1">Appeal approved — citation dismissed</div>
            )}
          </div>
          <div className="text-right flex flex-col items-end gap-2">
            <div className="text-lg font-bold" style={{ color: isPaid ? "#999" : brand.primaryColor }}>
              ${Number(t.fine_amount).toFixed(2)}
            </div>
            {(() => {
              const showAppeal = !isPaid && t.appeal_decision !== "pending" && t.can_appeal;
              const showPay = !isPaid && t.status !== "warning";
              if (!showAppeal && !showPay) return null;
              return (
                <div className="flex gap-2">
                  {showAppeal && <Button size="small" onClick={() => setAppealTicket(t)}>Appeal</Button>}
                  {showPay && <Button type="primary" size="small" href={`/pay/${t.id}`}>Pay</Button>}
                </div>
              );
            })()}
          </div>
        </div>
      </Card>
    );
  }

  const unpaid = tickets.filter(t => !["paid", "voided", "warning", "resolved_permit"].includes(t.status) && t.appeal_decision !== "approved");
  const totalOwed = unpaid.reduce((sum, t) => sum + Number(t.fine_amount), 0);

  if (loading) return <div className="flex justify-center py-20"><Spin size="large" /></div>;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-brand-primary">My Citations</h2>
        <p className="text-sm text-ink-mute mt-1">View your parking citations, pay fines, or submit appeals.</p>
      </div>

      {totalOwed > 0 && (
        <Card size="small" className="border-l-4" style={{ borderLeftColor: brand.primaryColor }}>
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-ink-mute">Outstanding Balance</div>
              <div className="text-2xl font-bold" style={{ color: brand.primaryColor }}>${totalOwed.toFixed(2)}</div>
              <div className="text-xs text-ink-mute">{unpaid.length} unpaid citation{unpaid.length !== 1 ? "s" : ""}</div>
            </div>
          </div>
        </Card>
      )}

      {tickets.length > 0 && (
        <div className="space-y-3">
          {tickets.map(renderTicket)}
        </div>
      )}

      {/* Plate / Citation # lookup */}
      <Card size="small">
        <div className="text-sm font-medium mb-2">
          {tickets.length === 0 ? "Look up a citation" : "Don't see a citation?"}
        </div>
        <p className="text-xs text-ink-mute mb-3">
          Enter your license plate number or citation number to find citations linked to your vehicle.
        </p>
        <div className="flex gap-2">
          <Input
            placeholder="License plate or citation #"
            value={lookupValue}
            onChange={e => setLookupValue(e.target.value)}
            onPressEnter={handleLookup}
            className="font-mono"
            style={{ maxWidth: 280 }}
          />
          <Button type="primary" onClick={handleLookup} loading={lookupLoading}>
            Look Up
          </Button>
        </div>
        {lookupResult !== null && lookupResult.length === 0 && (
          <Alert type="info" message="No citations found for that plate or citation number." className="mt-3" showIcon />
        )}
      </Card>

      <AppealModal ticket={appealTicket} onClose={() => setAppealTicket(null)}
        onSuccess={() => { setAppealTicket(null); message.success("Appeal submitted"); load(); }} />
    </div>
  );
}

function AppealModal({ ticket, onClose, onSuccess }: {
  ticket: TicketSummary | null; onClose: () => void; onSuccess: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  async function handleFinish(values: { explanation: string }) {
    if (!ticket) return;
    setSubmitting(true);
    try {
      const res = await fetch("/api/appeals/submit", {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({ ticket_id: ticket.id, explanation: values.explanation }),
      });
      if (!res.ok) {
        const b = await res.json();
        throw new Error(b.detail || "Appeal failed");
      }
      onSuccess();
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal open={!!ticket} onCancel={onClose} footer={null} title="Appeal Citation" destroyOnClose>
      {ticket && (
        <>
          <div className="mb-4 text-sm text-ink-mute">
            <span className="font-mono font-medium">{ticket.plate}</span> · {ticket.violation_type.replace(/_/g, " ")} · ${Number(ticket.fine_amount).toFixed(2)}
          </div>
          <Form form={form} layout="vertical" onFinish={handleFinish}>
            <Form.Item name="explanation" label="Why should this citation be dismissed?" rules={[{ required: true, message: "Please explain your appeal" }]}>
              <Input.TextArea rows={4} placeholder="Explain the circumstances..." />
            </Form.Item>
            <div className="flex justify-end gap-3">
              <Button onClick={onClose}>Cancel</Button>
              <Button type="primary" htmlType="submit" loading={submitting}>Submit Appeal</Button>
            </div>
          </Form>
        </>
      )}
    </Modal>
  );
}
