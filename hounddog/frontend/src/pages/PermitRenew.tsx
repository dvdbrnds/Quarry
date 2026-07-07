import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

interface RenewalInfo {
  permit_holder_name: string;
  email: string;
  plates: string[];
  lot_assignment: string;
  permit_type: string;
  end_date: string | null;
  expired: boolean;
}

export default function PermitRenew() {
  const { token } = useParams<{ token: string }>();
  const [info, setInfo] = useState<RenewalInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [newPlate, setNewPlate] = useState("");
  const [changePlate, setChangePlate] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState("");

  useEffect(() => {
    if (!token) return;
    loadRenewalInfo();
  }, [token]);

  async function loadRenewalInfo() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`/api/renewals/${token}`);
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Invalid renewal link");
      }
      const data: RenewalInfo = await res.json();
      setInfo(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm() {
    if (!token) return;
    setSubmitting(true);
    setError("");
    try {
      const res = await fetch(`/api/renewals/${token}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plate: changePlate && newPlate ? newPlate.toUpperCase().trim() : null,
        }),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Renewal failed");
      }
      const data = await res.json();
      setSuccess(data.message);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
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
          <span className="text-sm text-bone/70 ml-2">Permit Renewal</span>
        </div>
      </nav>

      <main className="max-w-lg mx-auto px-6 py-12">
        {loading && (
          <div className="text-center text-ink-mute text-sm py-20">
            Verifying renewal link...
          </div>
        )}

        {error && !success && (
          <div className="bg-white rounded-xl shadow p-8 text-center">
            <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.732 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
            </div>
            <h2 className="text-lg font-bold text-navy mb-2">Renewal Unavailable</h2>
            <p className="text-sm text-ink-mute">{error}</p>
          </div>
        )}

        {success && (
          <div className="bg-white rounded-xl shadow p-8 text-center">
            <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-xl font-bold text-navy mb-2">Permit Renewed</h2>
            <p className="text-sm text-ink-mute">{success}</p>
          </div>
        )}

        {info && !success && !error && (
          <div className="bg-white rounded-xl shadow p-6">
            <h2 className="text-xl font-bold text-navy mb-1">Renew Your Parking Permit</h2>
            <p className="text-sm text-ink-mute mb-6">
              Confirm the details below to renew your permit. No payment is required.
            </p>

            <div className="space-y-3 mb-6">
              <div className="flex justify-between text-sm">
                <span className="text-ink-mute">Name</span>
                <span className="font-medium text-navy">{info.permit_holder_name}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-ink-mute">Email</span>
                <span className="font-medium text-navy">{info.email}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-ink-mute">Permit Type</span>
                <span className="font-medium text-navy capitalize">{info.permit_type.replace(/_/g, " ")}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-ink-mute">Lots</span>
                <span className="font-medium text-navy">{info.lot_assignment}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-ink-mute">Current Plate(s)</span>
                <span className="font-mono font-medium text-navy">{info.plates.join(", ")}</span>
              </div>
              {info.end_date && (
                <div className="flex justify-between text-sm">
                  <span className="text-ink-mute">Expires</span>
                  <span className={`font-medium ${info.expired ? "text-red-600" : "text-navy"}`}>
                    {new Date(info.end_date).toLocaleDateString("en-US", {
                      month: "short", day: "numeric", year: "numeric",
                    })}
                    {info.expired && " (expired)"}
                  </span>
                </div>
              )}
            </div>

            <div className="border-t pt-4 mb-6">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={changePlate}
                  onChange={(e) => setChangePlate(e.target.checked)}
                  className="rounded border-gray-300"
                />
                <span className="text-ink-mute">I need to update my license plate</span>
              </label>

              {changePlate && (
                <div className="mt-3">
                  <label className="block text-xs font-medium text-ink-mute mb-1">
                    New License Plate
                  </label>
                  <input
                    value={newPlate}
                    onChange={(e) => setNewPlate(e.target.value.toUpperCase())}
                    placeholder="ABC1234"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-brass focus:outline-none"
                  />
                </div>
              )}
            </div>

            <button
              onClick={handleConfirm}
              disabled={submitting || (changePlate && !newPlate)}
              className="w-full py-3 bg-brass text-navy-deep font-semibold rounded-lg text-sm hover:bg-brass-deep transition-colors disabled:opacity-50"
            >
              {submitting ? "Renewing..." : "Confirm Renewal"}
            </button>

            <p className="text-xs text-ink-mute text-center mt-3">
              No payment is required for faculty/staff permit renewals.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
