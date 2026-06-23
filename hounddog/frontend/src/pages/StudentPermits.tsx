import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";

interface AvailablePermit {
  id: string;
  code: string;
  label: string;
  eligible: string;
  price: string;
  max_capacity: number;
  remaining: number;
  lot_assignments: string[];
  valid_days: number;
  application_closes_at: string | null;
  requires_lottery: boolean;
}

interface MyApplication {
  id: string;
  student_name: string;
  class_year: number;
  plate: string;
  status: string;
  permit_type_label: string;
  permit_type_code: string;
  permit_type_price: string;
  lot_assignments: string[];
  waitlist_position: number | null;
  offer_expires_at: string | null;
  created_at: string;
}

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  pending: { text: "Pending lottery", color: "bg-yellow-100 text-yellow-800" },
  selected: { text: "Selected — accept offer", color: "bg-green-100 text-green-800" },
  waitlisted: { text: "Waitlisted", color: "bg-blue-100 text-blue-700" },
  accepted: { text: "Permit active", color: "bg-green-50 text-green-700" },
  expired: { text: "Offer expired", color: "bg-gray-100 text-gray-500" },
  declined: { text: "Declined", color: "bg-gray-100 text-gray-500" },
};

export default function StudentPermits() {
  const [available, setAvailable] = useState<AvailablePermit[]>([]);
  const [applications, setApplications] = useState<MyApplication[]>([]);
  const [applying, setApplying] = useState<AvailablePermit | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const load = useCallback(async () => {
    try {
      const headers = await authHeaders();
      const [avRes, myRes] = await Promise.all([
        fetch("/api/student/permits/available", { headers }),
        fetch("/api/student/permits/my-applications", { headers }),
      ]);
      if (avRes.ok) setAvailable(await avRes.json());
      if (myRes.ok) setApplications(await myRes.json());
    } catch {
      setError("Failed to load permit data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Check for post-payment redirect
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("accepted")) {
      setSuccess("Payment received — your permit is now active.");
      window.history.replaceState({}, "", "/student/permits");
      load();
    }
  }, [load]);

  async function handleAccept(appId: string) {
    setError("");
    try {
      const res = await fetch(`/api/student/permits/${appId}/accept`, {
        method: "POST",
        headers: await authHeaders(),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Accept failed");
      }
      const { checkout_url } = await res.json();
      window.location.href = checkout_url;
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function handleDecline(appId: string) {
    if (!confirm("Are you sure you want to decline this offer? The spot will go to the next person on the waitlist.")) return;
    setError("");
    try {
      const res = await fetch(`/api/student/permits/${appId}/decline`, {
        method: "POST",
        headers: await authHeaders(),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Decline failed");
      }
      load();
    } catch (e: any) {
      setError(e.message);
    }
  }

  const appliedTypeIds = new Set(
    applications
      .filter((a) => !["expired", "declined"].includes(a.status))
      .map((a) => a.permit_type_code)
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-ink-mute text-sm">
        Loading...
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-navy">Parking Permits</h2>
        <p className="text-sm text-ink-mute mt-1">
          Apply for a parking permit. Lottery-based permits will be drawn after
          the application window closes.
        </p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {success && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-sm text-green-700">
          {success}
        </div>
      )}

      {/* My Applications */}
      {applications.length > 0 && (
        <div>
          <h3 className="text-lg font-semibold text-navy mb-3">
            My applications
          </h3>
          <div className="space-y-3">
            {applications.map((app) => {
              const st = STATUS_LABELS[app.status] || {
                text: app.status,
                color: "bg-gray-100",
              };
              const isExpiredOrDeclined = ["expired", "declined"].includes(
                app.status
              );
              return (
                <div
                  key={app.id}
                  className={`bg-white rounded-xl shadow p-5 ${
                    isExpiredOrDeclined ? "opacity-50" : ""
                  }`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="font-medium text-navy">
                        {app.permit_type_label}
                      </div>
                      <div className="text-xs text-ink-mute mt-0.5">
                        Plate: <span className="font-mono">{app.plate}</span>{" "}
                        &middot; Class of {app.class_year} &middot; Lots:{" "}
                        {app.lot_assignments.join(", ")}
                      </div>
                      {app.status === "waitlisted" &&
                        app.waitlist_position != null && (
                          <div className="text-xs text-blue-600 mt-1">
                            Waitlist position #{app.waitlist_position}
                          </div>
                        )}
                      {app.status === "selected" && app.offer_expires_at && (
                        <div className="text-xs text-green-700 mt-1">
                          Accept by{" "}
                          {new Date(app.offer_expires_at).toLocaleDateString(
                            "en-US",
                            {
                              month: "short",
                              day: "numeric",
                              year: "numeric",
                            }
                          )}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <span
                        className={`text-xs font-medium px-2.5 py-1 rounded-full ${st.color}`}
                      >
                        {st.text}
                      </span>
                      {app.status === "selected" && (
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleAccept(app.id)}
                            className="px-4 py-1.5 bg-brass text-navy-deep text-sm font-medium rounded-lg hover:bg-brass-deep transition-colors"
                          >
                            Accept & Pay
                          </button>
                          <button
                            onClick={() => handleDecline(app.id)}
                            className="px-3 py-1.5 border border-gray-300 text-sm rounded-lg hover:bg-gray-50 transition-colors"
                          >
                            Decline
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Available Permits */}
      {available.length > 0 && (
        <div>
          <h3 className="text-lg font-semibold text-navy mb-3">
            Available permits
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {available.map((pt) => {
              const alreadyApplied = appliedTypeIds.has(pt.code);
              return (
                <div
                  key={pt.id}
                  className="bg-white rounded-xl shadow p-5 flex flex-col"
                >
                  <div className="flex-1">
                    <div className="flex items-start justify-between">
                      <div className="font-medium text-navy">{pt.label}</div>
                      <div className="text-lg font-bold text-navy">
                        ${Number(pt.price).toFixed(0)}
                      </div>
                    </div>
                    <div className="text-xs text-ink-mute mt-1">
                      {pt.eligible}
                    </div>
                    <div className="text-xs text-ink-mute mt-1">
                      Lots: {pt.lot_assignments.join(", ")} &middot; Valid{" "}
                      {pt.valid_days} days
                    </div>
                    <div className="flex items-center gap-3 mt-2">
                      <span className="text-xs text-ink-mute">
                        {pt.remaining} of {pt.max_capacity} spots remaining
                      </span>
                      {pt.requires_lottery && (
                        <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-purple-100 text-purple-700">
                          Lottery
                        </span>
                      )}
                    </div>
                    {pt.application_closes_at && (
                      <div className="text-xs text-amber-700 mt-1">
                        Deadline:{" "}
                        {new Date(pt.application_closes_at).toLocaleDateString(
                          "en-US",
                          {
                            month: "short",
                            day: "numeric",
                            year: "numeric",
                            hour: "numeric",
                            minute: "2-digit",
                          }
                        )}
                      </div>
                    )}
                  </div>
                  <div className="mt-4">
                    {alreadyApplied ? (
                      <div className="text-xs text-ink-mute italic">
                        Already applied
                      </div>
                    ) : pt.remaining <= 0 ? (
                      <div className="text-xs text-red-600">
                        No spots remaining
                      </div>
                    ) : (
                      <button
                        onClick={() => setApplying(pt)}
                        className="w-full py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors"
                      >
                        Apply
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {available.length === 0 && applications.length === 0 && (
        <div className="text-center text-ink-mute py-16 text-sm">
          No permit types are currently open for application.
        </div>
      )}

      {/* Apply Modal */}
      {applying && (
        <ApplyModal
          permit={applying}
          onClose={() => setApplying(null)}
          onSuccess={() => {
            setApplying(null);
            setSuccess("Application submitted successfully.");
            load();
          }}
          onError={(msg) => setError(msg)}
        />
      )}
    </div>
  );
}

function ApplyModal({
  permit,
  onClose,
  onSuccess,
  onError,
}: {
  permit: AvailablePermit;
  onClose: () => void;
  onSuccess: () => void;
  onError: (msg: string) => void;
}) {
  const [name, setName] = useState("");
  const [plate, setPlate] = useState("");
  const [classYear, setClassYear] = useState("");
  const [phone, setPhone] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await fetch("/api/student/permits/apply", {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({
          permit_type_id: permit.id,
          student_name: name,
          plate: plate.toUpperCase().trim(),
          class_year: parseInt(classYear),
          phone: phone || null,
        }),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Application failed");
      }
      onSuccess();
    } catch (e: any) {
      onError(e.message);
      onClose();
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
          Apply for {permit.label}
        </h3>
        <p className="text-sm text-ink-mute mb-4">
          ${Number(permit.price).toFixed(0)} &middot; Lots:{" "}
          {permit.lot_assignments.join(", ")}
          {permit.requires_lottery && " (lottery)"}
        </p>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">
              Full Name
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
              License Plate
            </label>
            <input
              value={plate}
              onChange={(e) => setPlate(e.target.value.toUpperCase())}
              required
              placeholder="ABC1234"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-brass focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">
              Graduation Year
            </label>
            <input
              type="number"
              value={classYear}
              onChange={(e) => setClassYear(e.target.value)}
              required
              placeholder="2027"
              min="2024"
              max="2035"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">
              Phone (optional)
            </label>
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="610-555-0123"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
            />
          </div>
          <div className="flex gap-3 justify-end pt-2">
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
              className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors disabled:opacity-50"
            >
              {submitting ? "Submitting..." : "Submit Application"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
