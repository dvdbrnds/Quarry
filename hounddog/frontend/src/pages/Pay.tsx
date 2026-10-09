import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Button, Card, Input, Form, Modal, Alert, Spin, Empty, Space, App, Divider } from "antd";
import { SearchOutlined, LoginOutlined } from "@ant-design/icons";
import { useBranding } from "../useBranding";
import { initAuth, isAuthenticated, login, authHeaders } from "../auth";
import PublicPageNav from "../components/PublicPageNav";
import PublicFooter from "../components/PublicFooter";

interface TicketResult {
  id: string; plate: string; lot: string; violation_type: string;
  fine_amount: string; status: string; issued_at: string;
  ticket_category: string; vehicle_description: string | null;
  is_commuter_lot: boolean; processing_fee: string;
}

interface AvailablePermit {
  id: string; code: string; label: string; price: string;
  remaining: number; lot_assignments: string[]; valid_days: number;
}

interface AvailablePermitsResponse { permit_types: AvailablePermit[]; ticket_fine_after_purchase: string; }

const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 2000;

export default function Pay() {
  const { message } = App.useApp();
  const brand = useBranding();
  const { ticketId: pathTicketId } = useParams<{ ticketId: string }>();
  const [tickets, setTickets] = useState<TicketResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [paying, setPaying] = useState<string | null>(null);
  const [disputeTicket, setDisputeTicket] = useState<TicketResult | null>(null);
  const [permitTicket, setPermitTicket] = useState<TicketResult | null>(null);
  const [availablePermits, setAvailablePermits] = useState<AvailablePermitsResponse | null>(null);
  const [success, setSuccess] = useState("");
  const [retrying, setRetrying] = useState(false);
  const retryAbort = useRef<AbortController | null>(null);
  const [plateSearch, setPlateSearch] = useState("");
  const [searchLoading, setSearchLoading] = useState(false);
  const [myTicketsLoaded, setMyTicketsLoaded] = useState(false);
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    (async () => {
      const id = pathTicketId || new URLSearchParams(window.location.search).get("ticket");
      if (id) {
        loadTicketById(id);
        setAuthChecked(true);
        return;
      }
      // Try to auto-detect Okta session
      try {
        await initAuth();
        const authed = await isAuthenticated();
        if (authed) {
          setIsLoggedIn(true);
          await loadMyTickets();
        }
      } catch {}
      setAuthChecked(true);
    })();
    return () => { retryAbort.current?.abort(); };
  }, [pathTicketId]);

  async function loadMyTickets() {
    try {
      const headers = await authHeaders();
      if (!headers.Authorization) return;
      setIsLoggedIn(true);
      setLoading(true);
      const res = await fetch("/api/payments/my-tickets", { headers });
      if (!res.ok) return;
      const data: TicketResult[] = await res.json();
      if (data.length > 0) setTickets(data);
      setMyTicketsLoaded(true);
    } catch {
    } finally { setLoading(false); }
  }

  async function handleSignIn() {
    try {
      await initAuth();
      sessionStorage.setItem("quarry_return_path", "/pay");
      await login();
    } catch {}
  }

  async function searchByPlate() {
    const plate = plateSearch.trim().toUpperCase();
    if (!plate) return;
    setSearchLoading(true); setError(""); setTickets([]); setSuccess("");
    try {
      const res = await fetch(`/api/payments/lookup?plate=${encodeURIComponent(plate)}`);
      if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error(b.detail || "Lookup failed"); }
      const data: TicketResult[] = await res.json();
      if (data.length === 0) setError("No unpaid tickets found for that plate.");
      else setTickets(data);
    } catch (e: any) { setError(e.message || "Lookup failed"); }
    finally { setSearchLoading(false); }
  }

  async function loadTicketById(id: string, attempt = 0) {
    setLoading(true); setError(""); setTickets([]);
    if (attempt === 0) setRetrying(false);
    try {
      const res = await fetch(`/api/payments/lookup/${encodeURIComponent(id)}`);
      if (res.status === 404) {
        if (attempt < MAX_RETRIES) {
          setRetrying(true);
          setError("Ticket is being processed. Checking again shortly...");
          const abort = new AbortController();
          retryAbort.current = abort;
          await new Promise<void>((resolve, reject) => {
            const timer = setTimeout(resolve, RETRY_DELAY_MS);
            abort.signal.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("Aborted")); });
          });
          return loadTicketById(id, attempt + 1);
        }
        setRetrying(false);
        setError("Ticket not found. It may still be syncing - please try again in a minute.");
        return;
      }
      setRetrying(false);
      if (!res.ok) throw new Error("Lookup failed");
      const ticket: TicketResult = await res.json();
      if (ticket.status === "paid") setError("This ticket has already been paid.");
      else if (ticket.status === "voided") setError("This ticket has been voided. No payment required.");
      else if (ticket.status === "warning") setError("This is a warning — no fine is due.");
      else if (ticket.status === "resolved_permit") setError("Resolved through permit purchase.");
      else setTickets([ticket]);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setRetrying(false);
      setError("Unable to load ticket. Please try again.");
    } finally { setLoading(false); }
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

  const hasTicket = pathTicketId || new URLSearchParams(window.location.search).get("ticket");

  return (
    <div className="min-h-screen bg-gray-50">
      <PublicPageNav subtitle="Pay a Ticket" />
      <div className="max-w-md mx-auto px-4 pt-10">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold" style={{ color: brand.primaryColor }}>Pay a Parking Ticket</h1>
          {!hasTicket && (
            <p className="text-ink-mute mt-2">
              Scan the QR code on your parking ticket, use the link from your email, or look up by plate.
            </p>
          )}
        </div>

        {!hasTicket && tickets.length === 0 && !loading && (
          <div className="mb-6">
            <div className="flex gap-2">
              <Input
                placeholder="Enter license plate…"
                className="font-mono"
                size="large"
                value={plateSearch}
                onChange={e => setPlateSearch(e.target.value.toUpperCase())}
                onPressEnter={searchByPlate}
                allowClear
              />
              <Button
                type="primary"
                size="large"
                icon={<SearchOutlined />}
                loading={searchLoading}
                onClick={searchByPlate}
              >
                Look Up
              </Button>
            </div>
          </div>
        )}

        {loading && <div className="text-center py-8"><Spin size="large" /></div>}

        {error && <Alert type={retrying ? "info" : "error"} message={error} className="mb-4" showIcon
          icon={retrying ? <Spin size="small" /> : undefined} />}
        {success && <Alert type="success" message={success} className="mb-4" showIcon />}

        {tickets.length > 0 && (
          <>
            {tickets.length > 1 && (
              <div className="text-sm font-medium text-gray-600 mb-3">
                {tickets.length} unpaid citation{tickets.length > 1 ? "s" : ""} found
              </div>
            )}
            <Alert
              type="warning"
              showIcon
              className="mb-4"
              message="Appeal Before You Pay"
              description="If you believe a ticket was issued in error, you must appeal it BEFORE paying. Once payment is submitted, the fine is final. There are no refunds."
            />
          </>
        )}

        {tickets.map(t => (
          <Card key={t.id} className="mb-4">
            <div className="flex justify-between items-start mb-3">
              <div>
                <div className="font-mono text-lg font-bold">{t.plate}</div>
                <div className="text-sm text-ink-mute capitalize">{t.violation_type.replace(/_/g, " ")} &middot; {t.lot || "N/A"}</div>
              </div>
              <div className="text-right">
                <div className="text-2xl font-bold" style={{ color: brand.primaryColor }}>${(Number(t.fine_amount) + Number(t.processing_fee)).toFixed(2)}</div>
                <div className="text-xs text-ink-mute">{new Date(t.issued_at).toLocaleDateString()}</div>
              </div>
            </div>
            {Number(t.processing_fee) > 0 && (
              <div className="text-xs text-gray-500 mb-3 border-t pt-2">
                <div className="flex justify-between"><span>Citation fine</span><span>${Number(t.fine_amount).toFixed(2)}</span></div>
                <div className="flex justify-between"><span>Processing fee</span><span>${Number(t.processing_fee).toFixed(2)}</span></div>
                <div className="flex justify-between font-medium mt-1 pt-1 border-t"><span>Total due</span><span>${(Number(t.fine_amount) + Number(t.processing_fee)).toFixed(2)}</span></div>
              </div>
            )}
            {t.status === "expired_magistrate" ? (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-center">
                <p className="text-sm font-semibold text-red-800 mb-1">⚖️ Referred to Magistrate</p>
                <p className="text-xs text-red-700">
                  This moving violation has exceeded the 10-day response period and has been
                  referred to the local Magisterial District Court. It can no longer be paid online.
                </p>
              </div>
            ) : (
              <Space direction="vertical" className="w-full">
                <Button block onClick={() => setDisputeTicket(t)}>Appeal This Ticket</Button>
                {t.is_commuter_lot && <Button block onClick={() => handleShowPermits(t)} style={{ borderColor: brand.accentColor, color: brand.accentColor }}>Buy a Commuter Permit</Button>}
                <Button type="primary" block size="large" loading={paying === t.id} onClick={() => handlePay(t.id)}>
                  {paying === t.id ? "Redirecting..." : "Pay Now"}
                </Button>
                <p className="text-xs text-center text-red-600 font-medium">By paying, you accept the fine. No refunds will be issued.</p>
              </Space>
            )}
          </Card>
        ))}

        {!hasTicket && !loading && tickets.length === 0 && !error && myTicketsLoaded && (
          <div className="text-center py-8 text-ink-mute">
            <Empty description={isLoggedIn ? "No unpaid tickets" : "No ticket loaded"} />
            <p className="mt-4 text-sm">
              {isLoggedIn
                ? "You have no outstanding parking citations. 🎉"
                : "Enter your license plate above, scan the QR code on your citation, or log in to see all your tickets."}
            </p>
          </div>
        )}
        {!hasTicket && !loading && tickets.length === 0 && !error && !myTicketsLoaded && !searchLoading && authChecked && (
          <div className="text-center py-8 text-ink-mute">
            <Empty description="No ticket loaded" />
            <p className="mt-4 text-sm">
              Enter your license plate above, or scan the QR code printed on the citation.
            </p>
            {!isLoggedIn && (
              <Button type="primary" icon={<LoginOutlined />} className="mt-4" onClick={handleSignIn}>
                Sign in to see your tickets
              </Button>
            )}
          </div>
        )}

        <div className="text-center text-xs text-ink-mute mt-8">Payments processed securely via Stripe. &copy; {brand.schoolName || "Campus"} {brand.departmentName}</div>

        <DisputeModal ticket={disputeTicket} onClose={() => setDisputeTicket(null)}
          onSuccess={msg => { setDisputeTicket(null); setSuccess(msg); setTickets([]); }} />

        {permitTicket && availablePermits && (
          <PermitModal permits={availablePermits} onClose={() => { setPermitTicket(null); setAvailablePermits(null); }} onSelect={handleBuyPermit} />
        )}
      </div>
      <PublicFooter />
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
    <Modal open={!!ticket} onCancel={onClose} footer={null} title="Appeal Ticket" destroyOnClose>
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
              <Button type="primary" htmlType="submit" loading={submitting}>Submit Appeal</Button>
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
                </div>
                <div className="text-right">
                  <div className="text-lg font-bold text-brand-primary">${Number(pt.price).toFixed(0)}</div>
                  <Button type="primary" size="small" className="mt-1" onClick={() => onSelect(pt.id)} disabled={pt.remaining <= 0}>
                    {pt.remaining <= 0 ? "Full" : "Select"}
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </Modal>
  );
}
