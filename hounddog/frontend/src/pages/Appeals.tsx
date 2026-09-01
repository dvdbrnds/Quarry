import { useEffect, useState } from "react";
import { Alert, Button, Card, Empty, Form, Input, Modal, Spin, Tag, App as AntApp } from "antd";
import { initAuth, isAuthenticated, login, authHeaders } from "../auth";
import { useBranding } from "../useBranding";
import PublicPageNav from "../components/PublicPageNav";

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

interface MyTicketsResponse {
  tickets: TicketSummary[];
  appeal_window_days: number;
}

type Mode = "choose" | "student" | "guest";

export default function Appeals() {
  const { message } = AntApp.useApp();
  const brand = useBranding();
  const [mode, setMode] = useState<Mode>("choose");
  const [authState, setAuthState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [tickets, setTickets] = useState<TicketSummary[]>([]);
  const [appealWindowDays, setAppealWindowDays] = useState(5);
  const [loading, setLoading] = useState(false);
  const [appealTicket, setAppealTicket] = useState<TicketSummary | null>(null);

  // Guest lookup state
  const [lookupId, setLookupId] = useState("");
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupError, setLookupError] = useState("");

  // Check for direct ticket link (e.g., /appeals?ticket=uuid)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const ticketParam = params.get("ticket");
    if (ticketParam) {
      setMode("guest");
      setLookupId(ticketParam);
      lookupTicket(ticketParam);
    }
  }, []);

  async function handleStudentLogin() {
    setAuthState("loading");
    try {
      await initAuth();
      const authed = await isAuthenticated();
      if (!authed) {
        sessionStorage.setItem("quarry_return_path", "/appeals");
        await login();
        return;
      }
      setAuthState("ready");
      setMode("student");
      loadTickets();
    } catch {
      setAuthState("error");
    }
  }

  // Auto-login if returning from Okta redirect
  useEffect(() => {
    (async () => {
      try {
        await initAuth();
        const authed = await isAuthenticated();
        if (authed && mode === "choose") {
          setAuthState("ready");
          setMode("student");
          loadTickets();
        }
      } catch { /* not logged in, that's fine */ }
    })();
  }, []);

  async function loadTickets() {
    setLoading(true);
    try {
      const headers = await authHeaders();
      const res = await fetch("/api/appeals/my-tickets", { headers });
      if (!res.ok) throw new Error("Failed to load");
      const data: MyTicketsResponse = await res.json();
      setTickets(data.tickets);
      setAppealWindowDays(data.appeal_window_days);
    } catch {
      message.error("Unable to load your citation history.");
    } finally {
      setLoading(false);
    }
  }

  async function lookupTicket(id?: string) {
    const ticketId = id || lookupId.trim();
    if (!ticketId) return;
    setLookupLoading(true);
    setLookupError("");
    setTickets([]);
    try {
      const res = await fetch(`/api/appeals/lookup/${encodeURIComponent(ticketId)}`);
      if (res.status === 404) {
        setLookupError("Ticket not found. Please check the ticket ID and try again.");
        return;
      }
      if (!res.ok) throw new Error("Lookup failed");
      const data = await res.json();
      setTickets([data.ticket]);
      setAppealWindowDays(data.appeal_window_days);
    } catch {
      setLookupError("Unable to look up this ticket. Please try again.");
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

  return (
    <div className="min-h-screen bg-gray-50">
      <PublicPageNav subtitle="Citation Appeals" />
      <div className="max-w-2xl mx-auto px-4 pt-8 pb-16">
        <h1 className="text-2xl font-bold mb-2" style={{ color: brand.primaryColor }}>
          Citation Appeals
        </h1>

        <div className="mb-6 p-4 rounded-lg border-l-4" style={{ borderColor: brand.primaryColor, background: `${brand.primaryColor}08` }}>
          <p className="font-semibold text-gray-800 mb-2">
            Appeals are accepted at the time a citation is issued, before any payment is made. Once
            payment is processed, the citation is considered resolved and no refund will be issued.
          </p>
          <p className="text-sm text-gray-600 m-0">
            We recognize that this process doesn't always go smoothly. If you believe a citation was
            issued in error or there are extenuating circumstances, we encourage you to submit your
            appeal. Our team will review each case individually.
          </p>
        </div>

        {/* Mode selection — shown when not yet chosen */}
        {mode === "choose" && (
          <div className="space-y-4">
            <Card hoverable onClick={handleStudentLogin} className="cursor-pointer">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-full flex items-center justify-center text-xl" style={{ background: `${brand.primaryColor}15`, color: brand.primaryColor }}>
                  🎓
                </div>
                <div>
                  <div className="font-semibold text-base">Moravian Student, Staff, or Faculty</div>
                  <div className="text-sm text-gray-500">Sign in with your university account to view all your citations</div>
                </div>
              </div>
            </Card>
            <Card hoverable onClick={() => setMode("guest")} className="cursor-pointer">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-full flex items-center justify-center text-xl" style={{ background: `${brand.primaryColor}15`, color: brand.primaryColor }}>
                  🚗
                </div>
                <div>
                  <div className="font-semibold text-base">Community Member or Visitor</div>
                  <div className="text-sm text-gray-500">Look up a specific citation using the ticket ID from your notice</div>
                </div>
              </div>
            </Card>
          </div>
        )}

        {/* Student auth loading */}
        {authState === "loading" && (
          <div className="text-center py-12">
            <Spin size="large" />
            <p className="text-gray-500 mt-4">Signing in...</p>
          </div>
        )}

        {authState === "error" && (
          <Alert type="error" message="Authentication failed. Please try again." showIcon className="mb-4" />
        )}

        {/* Guest lookup form */}
        {mode === "guest" && tickets.length === 0 && (
          <Card>
            <p className="text-sm text-gray-600 mb-4">
              Enter the ticket ID from your citation notice, email, or the QR code on your ticket.
            </p>
            <div className="flex gap-2">
              <Input
                placeholder="Ticket ID"
                value={lookupId}
                onChange={(e) => setLookupId(e.target.value)}
                onPressEnter={() => lookupTicket()}
                className="font-mono"
              />
              <Button type="primary" onClick={() => lookupTicket()} loading={lookupLoading}>
                Look Up
              </Button>
            </div>
            {lookupError && <Alert type="error" message={lookupError} className="mt-3" showIcon />}
            <p className="text-xs text-gray-400 mt-4 mb-0">
              Don't have your ticket ID? Contact the parking office for assistance.
            </p>
            <Button type="link" size="small" className="px-0 mt-2" onClick={() => { setMode("choose"); setLookupError(""); }}>
              &larr; Back
            </Button>
          </Card>
        )}

        {/* Ticket list (shared between student and guest modes) */}
        {loading && (
          <div className="text-center py-12">
            <Spin size="large" />
          </div>
        )}

        {!loading && mode === "student" && tickets.length === 0 && authState === "ready" && (
          <Card>
            <Empty
              description={
                <div className="text-center">
                  <p className="text-base text-gray-600">No citations on file</p>
                  <p className="text-sm text-gray-500">
                    This page displays your citation history and the status of any appeals.
                    You currently have no citations associated with your account.
                  </p>
                </div>
              }
            />
          </Card>
        )}

        {!loading && tickets.length > 0 && (
          <div className="space-y-3">
            {mode === "guest" && (
              <Button type="link" size="small" className="px-0 mb-2" onClick={() => { setMode("choose"); setTickets([]); setLookupId(""); }}>
                &larr; Back
              </Button>
            )}
            {tickets.map((t) => (
              <Card key={t.id} size="small">
                <div className="flex justify-between items-start gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="font-mono font-bold text-sm">{t.plate}</span>
                      {t.ticket_number && (
                        <span className="text-xs text-gray-500">#{t.ticket_number}</span>
                      )}
                      {statusTag(t)}
                    </div>
                    <div className="text-sm text-gray-600">
                      <span className="capitalize">{t.violation_type.replace(/_/g, " ")}</span>
                      {t.lot && <> &middot; {t.lot}</>}
                    </div>
                    <div className="text-xs text-gray-400 mt-1">
                      Issued {new Date(t.issued_at).toLocaleDateString()}
                    </div>

                    {t.appeal_decision === "pending" && (
                      <div className="mt-2 text-xs text-blue-600 bg-blue-50 px-2 py-1 rounded inline-block">
                        Your appeal is under review.
                      </div>
                    )}
                    {t.appeal_decision === "denied" && (
                      <div className="mt-2 text-xs text-red-700 bg-red-50 px-2 py-1 rounded">
                        Your appeal was denied. The citation stands.
                      </div>
                    )}
                    {t.appeal_decision === "approved" && (
                      <div className="mt-2 text-xs text-green-700 bg-green-50 px-2 py-1 rounded">
                        Your appeal was approved. This citation has been voided.
                      </div>
                    )}
                  </div>

                  <div className="text-right shrink-0">
                    <div className="text-lg font-bold" style={{ color: t.status === "warning" ? "#ea580c" : brand.primaryColor }}>
                      {t.status === "warning" ? "Warning" : `$${Number(t.fine_amount).toFixed(2)}`}
                    </div>
                    {t.can_appeal && (
                      <Button
                        type="primary"
                        size="small"
                        className="mt-2"
                        onClick={() => setAppealTicket(t)}
                      >
                        Appeal
                      </Button>
                    )}
                    {!t.can_appeal && !t.appeal_decision && (t.status === "issued" || t.status === "warning") && (
                      <div className="text-xs text-gray-400 mt-2">
                        Window closed
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            ))}
          </div>
        )}

        <div className="text-center text-xs text-gray-400 mt-10">
          Appeals must be submitted within {appealWindowDays} day(s) of citation issuance.
          &copy; {brand.schoolName || "Campus"} {brand.departmentName}
        </div>
      </div>

      <AppealModal
        ticket={appealTicket}
        isGuest={mode === "guest"}
        onClose={() => setAppealTicket(null)}
        onSuccess={() => {
          setAppealTicket(null);
          if (mode === "student") loadTickets();
          else if (mode === "guest" && lookupId) lookupTicket();
        }}
      />
    </div>
  );
}

function AppealModal({
  ticket,
  isGuest,
  onClose,
  onSuccess,
}: {
  ticket: TicketSummary | null;
  isGuest: boolean;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const { message } = AntApp.useApp();
  const brand = useBranding();
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  async function handleFinish(values: { explanation: string; name?: string; email?: string; phone?: string }) {
    if (!ticket) return;
    setSubmitting(true);
    try {
      let res: Response;
      if (isGuest) {
        res = await fetch("/api/appeals/public-submit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ticket_id: ticket.id,
            explanation: values.explanation,
            name: values.name,
            email: values.email,
            phone: values.phone || "",
          }),
        });
      } else {
        const headers = await authHeaders();
        res = await fetch("/api/appeals/submit", {
          method: "POST",
          headers,
          body: JSON.stringify({ ticket_id: ticket.id, explanation: values.explanation }),
        });
      }
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Failed to submit appeal");
      }
      message.success("Your appeal has been submitted and is under review.");
      onSuccess();
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={!!ticket}
      onCancel={onClose}
      footer={null}
      title="Submit Appeal"
      destroyOnClose
    >
      {ticket && (
        <>
          <div className="mb-3 p-3 bg-gray-50 rounded border">
            <div className="flex justify-between">
              <div>
                <span className="font-mono font-bold">{ticket.plate}</span>
                {ticket.ticket_number && (
                  <span className="text-gray-500 ml-2">#{ticket.ticket_number}</span>
                )}
              </div>
              <span className="font-bold" style={{ color: brand.primaryColor }}>
                ${Number(ticket.fine_amount).toFixed(2)}
              </span>
            </div>
            <div className="text-sm text-gray-500 mt-1 capitalize">
              {ticket.violation_type.replace(/_/g, " ")} &middot; {ticket.lot || "N/A"}
              &middot; {new Date(ticket.issued_at).toLocaleDateString()}
            </div>
          </div>

          <Alert
            type="warning"
            showIcon
            className="mb-4"
            message="Important"
            description="By submitting this appeal, you affirm you have not yet paid this citation. Appeals submitted after payment will not be considered for refund."
          />

          <Form form={form} layout="vertical" onFinish={handleFinish}>
            {isGuest && (
              <>
                <Form.Item name="name" label="Your Name" rules={[{ required: true, message: "Name is required" }]}>
                  <Input placeholder="Full name" />
                </Form.Item>
                <Form.Item name="email" label="Email" rules={[{ required: true, type: "email", message: "Valid email is required" }]}>
                  <Input placeholder="you@email.com" />
                </Form.Item>
                <Form.Item name="phone" label="Phone (optional)">
                  <Input placeholder="(555) 555-5555" />
                </Form.Item>
              </>
            )}
            <Form.Item
              name="explanation"
              label="Why should this citation be reconsidered?"
              rules={[
                { required: true, message: "Please provide an explanation" },
                { min: 20, message: "Please provide more detail (at least 20 characters)" },
              ]}
            >
              <Input.TextArea
                rows={5}
                placeholder="Explain the circumstances. Include any relevant details such as permit numbers, events, or extenuating circumstances..."
              />
            </Form.Item>
            <div className="flex justify-end gap-3">
              <Button onClick={onClose}>Cancel</Button>
              <Button type="primary" htmlType="submit" loading={submitting}>
                Submit Appeal
              </Button>
            </div>
          </Form>
        </>
      )}
    </Modal>
  );
}
