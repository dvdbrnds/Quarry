import { useEffect, useState } from "react";

interface TicketResult {
  id: string;
  plate: string;
  lot: string;
  violation_type: string;
  fine_amount: string;
  status: string;
  issued_at: string;
  ticket_category: string;
  vehicle_description: string | null;
}

interface AvailablePermit {
  id: string;
  code: string;
  label: string;
  price: string;
  remaining: number;
  lot_assignments: string[];
  valid_days: number;
}

interface AvailablePermitsResponse {
  permit_types: AvailablePermit[];
  ticket_fine_after_purchase: string;
}

export default function Pay() {
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
    const params = new URLSearchParams(window.location.search);
    const ticketId = params.get("ticket");
    if (ticketId) {
      loadTicketById(ticketId);
    }
  }, []);

  async function loadTicketById(id: string) {
    setLoading(true);
    setError("");
    setTickets([]);
    try {
      const res = await fetch(`/api/payments/lookup/${encodeURIComponent(id)}`);
      if (res.status === 404) {
        setError("Ticket not found. It may have been voided or the link is invalid.");
        return;
      }
      if (!res.ok) throw new Error("Lookup failed");
      const ticket: TicketResult = await res.json();
      if (ticket.status === "paid") {
        setError("This ticket has already been paid.");
      } else if (ticket.status === "voided") {
        setError("This ticket has been voided. No payment is required.");
      } else if (ticket.status === "resolved_permit") {
        setError("This ticket has been resolved through a permit purchase.");
      } else {
        setTickets([ticket]);
      }
    } catch {
      setError("Unable to load ticket. Please try searching by plate number instead.");
    } finally {
      setLoading(false);
    }
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!lookup.trim()) return;
    setLoading(true);
    setError("");
    setTickets([]);

    try {
      const res = await fetch(
        `/api/payments/lookup?plate=${encodeURIComponent(lookup.trim())}`
      );
      if (!res.ok) throw new Error("Search failed");
      const data = await res.json();
      if (data.tickets.length === 0) {
        setError("No outstanding tickets found for that plate number.");
      }
      setTickets(data.tickets);
    } catch {
      setError("Unable to look up tickets. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  async function handlePay(ticketId: string) {
    setPaying(ticketId);
    try {
      const res = await fetch("/api/payments/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticket_id: ticketId,
          success_url: "/pay/success",
          cancel_url: "/pay",
        }),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Payment failed");
      }
      const { checkout_url } = await res.json();
      window.location.href = checkout_url;
    } catch (e: any) {
      setError(e.message || "Payment failed");
      setPaying(null);
    }
  }

  async function handleShowPermits(ticket: TicketResult) {
    setPermitTicket(ticket);
    try {
      const res = await fetch(`/api/payments/permits/available?ticket_id=${ticket.id}`);
      if (res.ok) setAvailablePermits(await res.json());
    } catch {
      setError("Unable to load available permits.");
    }
  }

  async function handleBuyPermit(permitTypeId: string) {
    if (!permitTicket) return;
    const name = prompt("Your full name:");
    if (!name) return;
    const email = prompt("Your email address:");
    if (!email) return;

    try {
      const res = await fetch("/api/payments/purchase-permit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticket_id: permitTicket.id,
          permit_type_id: permitTypeId,
          student_name: name,
          plate: permitTicket.plate,
          email,
          success_url: "/pay/success",
          cancel_url: "/pay",
        }),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Purchase failed");
      }
      const { checkout_url } = await res.json();
      window.location.href = checkout_url;
    } catch (e: any) {
      setError(e.message || "Purchase failed");
    }
  }

  return (
    <div className="min-h-screen bg-bone-light flex items-start justify-center pt-16 px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-navy">Pay a Parking Ticket</h1>
          <p className="text-ink-mute mt-2">
            Enter your license plate number to look up and pay outstanding fines.
          </p>
        </div>

        <form onSubmit={handleSearch} className="flex gap-2 mb-6">
          <input
            type="text"
            value={lookup}
            onChange={(e) => setLookup(e.target.value.toUpperCase())}
            placeholder="License Plate #"
            className="flex-1 border border-gray-300 rounded-lg px-4 py-3 text-center font-mono text-lg tracking-wider focus:ring-2 focus:ring-brass focus:outline-none"
          />
          <button
            type="submit"
            disabled={loading}
            className="px-6 py-3 bg-brass text-navy-deep font-medium rounded-lg hover:bg-brass-deep transition-colors disabled:opacity-50"
          >
            {loading ? "..." : "Search"}
          </button>
        </form>

        {error && (
          <div className="bg-signal-red/10 border border-signal-red/30 rounded-lg px-4 py-3 mb-4 text-sm text-red-700">
            {error}
          </div>
        )}

        {success && (
          <div className="bg-signal-green/10 border border-signal-green/30 rounded-lg px-4 py-3 mb-4 text-sm text-green-700">
            {success}
          </div>
        )}

        {tickets.map((t) => (
          <div key={t.id} className="bg-white rounded-xl shadow p-5 mb-4">
            <div className="flex justify-between items-start mb-3">
              <div>
                <div className="font-mono text-lg font-bold">{t.plate}</div>
                <div className="text-sm text-ink-mute capitalize">
                  {t.violation_type.replace(/_/g, " ")} &middot; {t.lot || "N/A"}
                </div>
              </div>
              <div className="text-right">
                <div className="text-2xl font-bold text-navy">
                  ${Number(t.fine_amount).toFixed(2)}
                </div>
                <div className="text-xs text-ink-mute">
                  {new Date(t.issued_at).toLocaleDateString()}
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <button
                onClick={() => handlePay(t.id)}
                disabled={paying === t.id}
                className="w-full py-3 bg-brass text-navy-deep font-semibold rounded-lg hover:bg-brass-deep transition-colors disabled:opacity-50"
              >
                {paying === t.id ? "Redirecting to payment..." : "Pay Now"}
              </button>

              <div className="flex gap-2">
                <button
                  onClick={() => setDisputeTicket(t)}
                  className="flex-1 py-2 border border-gray-300 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors"
                >
                  Dispute This Ticket
                </button>
                <button
                  onClick={() => handleShowPermits(t)}
                  className="flex-1 py-2 border border-brass text-brass-deep text-sm font-medium rounded-lg hover:bg-brass/10 transition-colors"
                >
                  Buy a Permit Instead
                </button>
              </div>
            </div>
          </div>
        ))}

        <div className="text-center text-xs text-ink-mute mt-8">
          Payments processed securely via Stripe. &copy; Quarry Parking Systems
        </div>
      </div>

      {/* Dispute Modal */}
      {disputeTicket && (
        <DisputeModal
          ticket={disputeTicket}
          onClose={() => setDisputeTicket(null)}
          onSuccess={(msg) => {
            setDisputeTicket(null);
            setSuccess(msg);
            setTickets([]);
          }}
        />
      )}

      {/* Permit Purchase Modal */}
      {permitTicket && availablePermits && (
        <PermitModal
          permits={availablePermits}
          onClose={() => { setPermitTicket(null); setAvailablePermits(null); }}
          onSelect={handleBuyPermit}
        />
      )}
    </div>
  );
}

function DisputeModal({
  ticket,
  onClose,
  onSuccess,
}: {
  ticket: TicketResult;
  onClose: () => void;
  onSuccess: (msg: string) => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [explanation, setExplanation] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const res = await fetch(`/api/payments/dispute/${ticket.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, phone, explanation }),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Dispute submission failed");
      }
      const data = await res.json();
      onSuccess(data.message);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-1">Dispute Ticket</h3>
        <p className="text-sm text-ink-mute mb-4">
          Plate: <span className="font-mono">{ticket.plate}</span> &middot; Fine: ${Number(ticket.fine_amount).toFixed(2)}
        </p>

        {error && (
          <div className="bg-signal-red/10 border border-signal-red/30 rounded-lg px-3 py-2 mb-4 text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Your Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Phone</label>
            <input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Explanation</label>
            <textarea value={explanation} onChange={(e) => setExplanation(e.target.value)} required
              rows={4} placeholder="Explain why you believe this ticket should be dismissed..."
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none resize-none" />
          </div>
          <div className="flex gap-3 justify-end pt-2">
            <button type="button" onClick={onClose}
              className="px-4 py-2 text-sm text-ink-mute hover:text-ink">Cancel</button>
            <button type="submit" disabled={submitting}
              className="px-4 py-2 bg-navy text-bone font-medium rounded-lg text-sm hover:bg-navy-700 transition-colors disabled:opacity-50">
              {submitting ? "Submitting..." : "Submit Dispute"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function PermitModal({
  permits,
  onClose,
  onSelect,
}: {
  permits: AvailablePermitsResponse;
  onClose: () => void;
  onSelect: (permitTypeId: string) => void;
}) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-1">Buy a Permit Instead</h3>
        <p className="text-sm text-ink-mute mb-4">
          Purchase a valid parking permit and your ticket fine will be reduced to ${Number(permits.ticket_fine_after_purchase).toFixed(2)}.
        </p>

        {permits.permit_types.length === 0 ? (
          <div className="text-center text-ink-mute py-6">
            No permits are currently available for online purchase.
          </div>
        ) : (
          <div className="space-y-3 max-h-80 overflow-y-auto">
            {permits.permit_types.map((pt) => (
              <div key={pt.id} className="border border-gray-200 rounded-lg p-4 hover:border-brass transition-colors">
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-medium">{pt.label}</div>
                    <div className="text-xs text-ink-mute mt-1">
                      Lots: {pt.lot_assignments.join(", ")} &middot; Valid {pt.valid_days} days
                    </div>
                    <div className="text-xs text-ink-mute">
                      {pt.remaining} permits remaining
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-lg font-bold text-navy">${Number(pt.price).toFixed(0)}</div>
                    <button
                      onClick={() => onSelect(pt.id)}
                      className="mt-1 px-3 py-1 bg-brass text-navy-deep text-xs font-medium rounded-lg hover:bg-brass-deep transition-colors"
                    >
                      Select
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="flex justify-end pt-4">
          <button onClick={onClose}
            className="px-4 py-2 text-sm text-ink-mute hover:text-ink">Close</button>
        </div>
      </div>
    </div>
  );
}
