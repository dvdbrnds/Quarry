import { useState } from "react";

interface TicketResult {
  id: string;
  plate: string;
  lot: string;
  violation_type: string;
  fine_amount: string;
  status: string;
  issued_at: string;
}

export default function Pay() {
  const [lookup, setLookup] = useState("");
  const [tickets, setTickets] = useState<TicketResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [paying, setPaying] = useState<string | null>(null);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!lookup.trim()) return;
    setLoading(true);
    setError("");
    setTickets([]);

    try {
      const res = await fetch(`/api/tickets?search=${encodeURIComponent(lookup.trim())}&page_size=20`);
      if (!res.ok) throw new Error("Search failed");
      const data = await res.json();
      const unpaid = data.items.filter(
        (t: TicketResult) => !["paid", "voided"].includes(t.status)
      );
      if (unpaid.length === 0) {
        setError("No outstanding tickets found for that plate or ticket number.");
      }
      setTickets(unpaid);
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

  return (
    <div className="min-h-screen bg-bone-light flex items-start justify-center pt-16 px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-navy">Pay a Parking Ticket</h1>
          <p className="text-ink-mute mt-2">
            Enter your license plate number or ticket ID to look up and pay outstanding fines.
          </p>
        </div>

        <form onSubmit={handleSearch} className="flex gap-2 mb-6">
          <input
            type="text"
            value={lookup}
            onChange={(e) => setLookup(e.target.value.toUpperCase())}
            placeholder="Plate # or Ticket ID"
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

        {tickets.map((t) => (
          <div key={t.id} className="bg-white rounded-xl shadow p-5 mb-4">
            <div className="flex justify-between items-start mb-3">
              <div>
                <div className="font-mono text-lg font-bold">{t.plate}</div>
                <div className="text-sm text-ink-mute capitalize">
                  {t.violation_type.replace("_", " ")} &middot; {t.lot}
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
            <button
              onClick={() => handlePay(t.id)}
              disabled={paying === t.id}
              className="w-full py-3 bg-brass text-navy-deep font-semibold rounded-lg hover:bg-brass-deep transition-colors disabled:opacity-50"
            >
              {paying === t.id ? "Redirecting to payment..." : "Pay Now"}
            </button>
          </div>
        ))}

        <div className="text-center text-xs text-ink-mute mt-8">
          Payments processed securely via Stripe. &copy; Quarry Parking Systems
        </div>
      </div>
    </div>
  );
}
