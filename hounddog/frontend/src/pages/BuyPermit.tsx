import { useEffect, useState } from "react";

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

export default function BuyPermit() {
  const [permits, setPermits] = useState<AvailablePermit[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<AvailablePermit | null>(null);

  useEffect(() => {
    loadPermits();
  }, []);

  async function loadPermits() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/payments/permits/available");
      if (!res.ok) throw new Error("Failed to load available permits");
      const data: AvailablePermitsResponse = await res.json();
      setPermits(data.permit_types);
    } catch {
      setError("Unable to load available permits. Please try again later.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-navy text-bone px-6 py-4 shadow-md">
        <div className="max-w-4xl mx-auto flex items-center gap-3">
          <img src="/quarry-logo.png" alt="Quarry" className="h-8 w-auto" />
          <h1 className="text-lg font-bold tracking-wide text-brass">
            Quarry
          </h1>
          <span className="text-sm text-bone/70 ml-2">Parking Permits</span>
        </div>
      </nav>

      <main className="max-w-4xl mx-auto px-6 py-10">
        <div className="mb-8">
          <h2 className="text-2xl font-bold text-navy">Purchase a Parking Permit</h2>
          <p className="text-sm text-ink-mute mt-1">
            Select a permit type below to purchase online. Payment is processed securely via Stripe.
          </p>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700 mb-6">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-20 text-ink-mute text-sm">
            Loading available permits...
          </div>
        ) : permits.length === 0 ? (
          <div className="text-center text-ink-mute py-16 text-sm">
            No permits are currently available for online purchase.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {permits.map((pt) => (
              <div
                key={pt.id}
                className="bg-white rounded-xl shadow p-6 flex flex-col"
              >
                <div className="flex-1">
                  <div className="flex items-start justify-between">
                    <div className="font-semibold text-navy text-lg">{pt.label}</div>
                    <div className="text-xl font-bold text-navy">
                      ${Number(pt.price).toFixed(0)}
                    </div>
                  </div>
                  <div className="text-sm text-ink-mute mt-2">
                    Lots: {pt.lot_assignments.join(", ")}
                  </div>
                  <div className="text-sm text-ink-mute mt-1">
                    Valid for {pt.valid_days} days
                  </div>
                  <div className="text-sm mt-2">
                    <span className={pt.remaining <= 5 ? "text-amber-700 font-medium" : "text-ink-mute"}>
                      {pt.remaining} spot{pt.remaining !== 1 ? "s" : ""} remaining
                    </span>
                  </div>
                </div>
                <div className="mt-5">
                  {pt.remaining > 0 ? (
                    <button
                      onClick={() => setSelected(pt)}
                      className="w-full py-2.5 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors"
                    >
                      Purchase
                    </button>
                  ) : (
                    <div className="text-center text-sm text-red-600 font-medium py-2">
                      Sold Out
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {selected && (
          <PurchaseModal
            permit={selected}
            onClose={() => setSelected(null)}
            onError={(msg) => {
              setError(msg);
              setSelected(null);
            }}
          />
        )}
      </main>
    </div>
  );
}

function PurchaseModal({
  permit,
  onClose,
  onError,
}: {
  permit: AvailablePermit;
  onClose: () => void;
  onError: (msg: string) => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [plate, setPlate] = useState("");
  const [classYear, setClassYear] = useState("");
  const [phone, setPhone] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await fetch("/api/payments/standalone-purchase", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          permit_type_id: permit.id,
          student_name: name,
          plate: plate.toUpperCase().trim(),
          email,
          phone: phone || null,
          class_year: classYear ? parseInt(classYear) : null,
        }),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Purchase failed");
      }
      const { checkout_url } = await res.json();
      window.location.href = checkout_url;
    } catch (e: any) {
      onError(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-xl p-6 w-full max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-semibold text-navy mb-1">
          Purchase {permit.label}
        </h3>
        <p className="text-sm text-ink-mute mb-4">
          ${Number(permit.price).toFixed(0)} &middot; Lots:{" "}
          {permit.lot_assignments.join(", ")} &middot; Valid {permit.valid_days} days
        </p>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">
              Full Name *
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">
              Email *
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="you@moravian.edu"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">
              License Plate *
            </label>
            <input
              value={plate}
              onChange={(e) => setPlate(e.target.value.toUpperCase())}
              required
              placeholder="ABC1234"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-brass focus:outline-none"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">
                Graduation Year
              </label>
              <input
                type="number"
                value={classYear}
                onChange={(e) => setClassYear(e.target.value)}
                placeholder="2027"
                min="2024"
                max="2035"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">
                Phone
              </label>
              <input
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="610-555-0123"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
              />
            </div>
          </div>

          <div className="flex gap-3 justify-end pt-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-ink-mute hover:text-ink"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-5 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors disabled:opacity-50"
            >
              {submitting ? "Processing..." : `Pay $${Number(permit.price).toFixed(0)}`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
