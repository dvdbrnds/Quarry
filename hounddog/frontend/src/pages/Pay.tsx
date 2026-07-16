import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Button, Card, Input, Form, Modal, Alert, Spin, Empty, Space, App } from "antd";
import { useBranding } from "../useBranding";

interface TicketResult {
  id: string; plate: string; lot: string; violation_type: string;
  fine_amount: string; status: string; issued_at: string;
  ticket_category: string; vehicle_description: string | null;
  is_commuter_lot: boolean;
}

interface AvailablePermit {
  id: string; code: string; label: string; price: string;
  remaining: number; lot_assignments: string[]; valid_days: number;
}

interface AvailablePermitsResponse { permit_types: AvailablePermit[]; ticket_fine_after_purchase: string; }

export default function Pay() {
  const { message } = App.useApp();
  const brand = useBranding();
  const { ticketId: pathTicketId } = useParams<{ ticketId: string }>();
  const [lookup, setLookup] = useState("");
  const [tickets, setTickets] = useState<TicketResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [paying, setPaying] = useState<string | null>(null);
  const [disputeTicket, setDisputeTicket] = useState<TicketResult | null>(null);
  const [permitTicket, setPermitTicket] = useState<TicketResult | null>(null);
  const [availablePermits, setAvailablePermits] = useState<AvailablePermitsResponse | null>(null);
  const [success, setSuccess] = useState("");

  useEffect(() => {
    const id = pathTicketId || new URLSearchParams(window.location.search).get("ticket");
    if (id) loadTicketById(id);
  }, [pathTicketId]);

  async function loadTicketById(id: string) {
    setLoading(true); setError(""); setTickets([]);
    try {
      const res = await fetch(`/api/payments/lookup/${encodeURIComponent(id)}`);
      if (res.status === 404) { setError("Ticket not found."); return; }
      if (!res.ok) throw new Error("Lookup failed");
      const ticket: TicketResult = await res.json();
      if (ticket.status === "paid") setError("This ticket has already been paid.");
      else if (ticket.status === "voided") setError("This ticket has been voided. No payment required.");
      else if (ticket.status === "resolved_permit") setError("Resolved through permit purchase.");
      else setTickets([ticket]);
    } catch { setError("Unable to load ticket. Try searching by plate."); } finally { setLoading(false); }
  }

  async function handleSearch() {
    if (!lookup.trim()) return;
    setLoading(true); setError(""); setTickets([]);
    try {
      const res = await fetch(`/api/payments/lookup?plate=${encodeURIComponent(lookup.trim())}`);
      if (!res.ok) throw new Error("Search failed");
      const data = await res.json();
      if (data.tickets.length === 0) setError("No outstanding tickets found.");
      setTickets(data.tickets);
    } catch { setError("Unable to look up tickets."); } finally { setLoading(false); }
  }

  async function handlePay(ticketId: string) {
    setPaying(ticketId);
    try {
      const res = await fetch("/api/payments/checkout", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticket_id: ticketId, success_url: "/pay/success", cancel_url: "/pay" }) });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Payment failed"); }
      const { checkout_url } = await res.json();
      window.location.href = checkout_url;
    } catch (e: any) { setError(e.message); setPaying(null); }
  }

  async function handleShowPermits(ticket: TicketResult) {
    setPermitTicket(ticket);
    try { const res = await fetch(`/api/payments/permits/available?ticket_id=${ticket.id}`); if (res.ok) setAvailablePermits(await res.json()); }
    catch { setError("Unable to load available permits."); }
  }

  async function handleBuyPermit(permitTypeId: string) {
    if (!permitTicket) return;
    const name = prompt("Your full name:");
    if (!name) return;
    const email = prompt("Your email address:");
    if (!email) return;
    try {
      const res = await fetch("/api/payments/purchase-permit", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticket_id: permitTicket.id, permit_type_id: permitTypeId, student_name: name, plate: permitTicket.plate, email, success_url: "/pay/success", cancel_url: "/pay" }) });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Purchase failed"); }
      const { checkout_url } = await res.json();
      window.location.href = checkout_url;
    } catch (e: any) { setError(e.message); }
  }

  return (
    <div className="min-h-screen bg-bone-light flex items-start justify-center pt-16 px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-navy">Pay a Parking Ticket</h1>
          <p className="text-ink-mute mt-2">Enter your license plate number to look up and pay outstanding fines.</p>
        </div>

        <Space.Compact className="w-full mb-6">
          <Input value={lookup} onChange={e => setLookup(e.target.value.toUpperCase())} placeholder="License Plate #"
            className="font-mono text-lg text-center tracking-wider" size="large" onPressEnter={handleSearch} />
          <Button type="primary" size="large" onClick={handleSearch} loading={loading}>Search</Button>
        </Space.Compact>

        {error && <Alert type="error" message={error} className="mb-4" showIcon />}
        {success && <Alert type="success" message={success} className="mb-4" showIcon />}

        {tickets.map(t => (
          <Card key={t.id} className="mb-4">
            <div className="flex justify-between items-start mb-3">
              <div>
                <div className="font-mono text-lg font-bold">{t.plate}</div>
                <div className="text-sm text-ink-mute capitalize">{t.violation_type.replace(/_/g, " ")} &middot; {t.lot || "N/A"}</div>
              </div>
              <div className="text-right">
                <div className="text-2xl font-bold text-navy">${Number(t.fine_amount).toFixed(2)}</div>
                <div className="text-xs text-ink-mute">{new Date(t.issued_at).toLocaleDateString()}</div>
              </div>
            </div>
            <Space direction="vertical" className="w-full">
              <Button type="primary" block size="large" loading={paying === t.id} onClick={() => handlePay(t.id)}>
                {paying === t.id ? "Redirecting..." : "Pay Now"}
              </Button>
              <Space className="w-full">
                <Button block onClick={() => setDisputeTicket(t)}>Dispute This Ticket</Button>
                {t.is_commuter_lot && <Button block onClick={() => handleShowPermits(t)} style={{ borderColor: "#C5A55A", color: "#9B7E35" }}>Buy a Commuter Permit</Button>}
              </Space>
            </Space>
          </Card>
        ))}

        <div className="text-center text-xs text-ink-mute mt-8">Payments processed securely via Stripe. &copy; {brand.brandName} Parking</div>
      </div>

      <DisputeModal ticket={disputeTicket} onClose={() => setDisputeTicket(null)}
        onSuccess={msg => { setDisputeTicket(null); setSuccess(msg); setTickets([]); }} />

      {permitTicket && availablePermits && (
        <PermitModal permits={availablePermits} onClose={() => { setPermitTicket(null); setAvailablePermits(null); }} onSelect={handleBuyPermit} />
      )}
    </div>
  );
}

function DisputeModal({ ticket, onClose, onSuccess }: { ticket: TicketResult | null; onClose: () => void; onSuccess: (msg: string) => void }) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  async function handleFinish(values: any) {
    if (!ticket) return;
    setSubmitting(true);
    try {
      const res = await fetch(`/api/payments/dispute/${ticket.id}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Failed"); }
      const data = await res.json();
      onSuccess(data.message);
    } catch (e: any) { message.error(e.message); } finally { setSubmitting(false); }
  }

  return (
    <Modal open={!!ticket} onCancel={onClose} footer={null} title="Dispute Ticket" destroyOnClose>
      {ticket && (
        <>
          <p className="text-sm text-ink-mute mb-4">Plate: <span className="font-mono">{ticket.plate}</span> &middot; Fine: ${Number(ticket.fine_amount).toFixed(2)}</p>
          <Form form={form} layout="vertical" onFinish={handleFinish}>
            <Form.Item name="name" label="Your Name" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="email" label="Email" rules={[{ required: true, type: "email" }]}><Input /></Form.Item>
            <Form.Item name="phone" label="Phone" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="explanation" label="Explanation" rules={[{ required: true }]}>
              <Input.TextArea rows={4} placeholder="Explain why this ticket should be dismissed..." />
            </Form.Item>
            <div className="flex justify-end gap-3">
              <Button onClick={onClose}>Cancel</Button>
              <Button type="primary" htmlType="submit" loading={submitting}>Submit Dispute</Button>
            </div>
          </Form>
        </>
      )}
    </Modal>
  );
}

function PermitModal({ permits, onClose, onSelect }: {
  permits: AvailablePermitsResponse; onClose: () => void; onSelect: (id: string) => void;
}) {
  return (
    <Modal open onCancel={onClose} footer={<Button onClick={onClose}>Close</Button>} title="Buy a Commuter Permit" width={520}>
      <p className="text-sm text-ink-mute mb-4">Purchase a commuter parking permit and your ticket fine will be reduced to ${Number(permits.ticket_fine_after_purchase).toFixed(2)}. Subject to availability.</p>
      {permits.permit_types.length === 0 ? <Empty description="No commuter permits currently available" /> : (
        <div className="space-y-3 max-h-80 overflow-y-auto">
          {permits.permit_types.map(pt => (
            <Card key={pt.id} size="small" hoverable>
              <div className="flex justify-between items-start">
                <div>
                  <div className="font-medium">{pt.label}</div>
                  <div className="text-xs text-ink-mute mt-1">Lots: {pt.lot_assignments.join(", ")} &middot; Valid {pt.valid_days} days</div>
                  <div className="text-xs text-ink-mute">{pt.remaining} remaining</div>
                </div>
                <div className="text-right">
                  <div className="text-lg font-bold text-navy">${Number(pt.price).toFixed(0)}</div>
                  <Button type="primary" size="small" className="mt-1" onClick={() => onSelect(pt.id)}>Select</Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </Modal>
  );
}
