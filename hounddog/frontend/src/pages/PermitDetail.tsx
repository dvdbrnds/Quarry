import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api";

interface PermitHistory {
  permit: any;
  has_hold: boolean;
  unpaid_amount: string;
  tickets: any[];
  payments: any[];
  audit_log: any[];
  prior_permits: any[];
  duplicates: any[];
}

type Tab = "overview" | "tickets" | "payments" | "timeline" | "related";

export default function PermitDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<PermitHistory | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const result = await api.permits.history(id);
      setData(result);
    } catch {
      navigate("/permits");
    } finally {
      setLoading(false);
    }
  }, [id, navigate]);

  useEffect(() => { load(); }, [load]);

  async function handleRenew() {
    if (!id || !confirm("Renew this permit? A new permit will be created with fresh dates.")) return;
    await api.permits.renew(id);
    load();
  }

  if (loading || !data) {
    return <div className="text-center py-12 text-ink-mute">Loading...</div>;
  }

  const p = data.permit;

  return (
    <div>
      <button onClick={() => navigate("/permits")} className="text-sm text-brass-deep hover:text-brass mb-4 inline-block">
        &larr; Back to Permits
      </button>

      {/* Header */}
      <div className="bg-white rounded-xl shadow p-6 mb-6">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-2xl font-bold">{p.name}</h2>
            <div className="flex gap-3 mt-2 text-sm text-ink-mute">
              <span>ID: {p.student_id || "N/A"}</span>
              <span>Plates: <span className="font-mono">{p.plates?.join(", ")}</span></span>
              <span>Lot: {p.lot_assignment}</span>
              <span className="capitalize">Type: {p.permit_type}</span>
            </div>
            <div className="flex gap-2 mt-3">
              <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                p.status === "active" ? "bg-signal-green/15 text-green-700" :
                p.status === "expired" || p.status === "renewed" ? "bg-gray-100 text-gray-500" :
                "bg-signal-red/15 text-red-700"
              }`}>{p.status}</span>
              {data.has_hold && (
                <span className="inline-block px-2 py-0.5 rounded-full text-xs font-bold bg-signal-red/15 text-red-700">
                  HOLD — ${data.unpaid_amount} unpaid
                </span>
              )}
              {data.duplicates.length > 0 && (
                <span className="inline-block px-2 py-0.5 rounded-full text-xs font-bold bg-amber-100 text-amber-700">
                  DUPLICATE PLATE
                </span>
              )}
            </div>
          </div>
          <div className="flex gap-2">
            {(p.status === "expired" || p.status === "active") && (
              <button onClick={handleRenew}
                className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep">
                Renew
              </button>
            )}
          </div>
        </div>
        <div className="mt-4 flex gap-4 text-sm">
          <span>Start: {p.start_date || "—"}</span>
          <span>End: {p.end_date || "No expiry"}</span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b border-gray-200">
        {(["overview", "tickets", "payments", "timeline", "related"] as Tab[]).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize rounded-t-lg ${
              tab === t ? "bg-white border border-b-0 border-gray-200 -mb-px" : "text-ink-mute hover:text-ink"
            }`}>
            {t}
            {t === "tickets" && data.tickets.length > 0 && (
              <span className="ml-1 text-xs bg-gray-100 rounded-full px-1.5">{data.tickets.length}</span>
            )}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="bg-white rounded-xl shadow p-6">
        {tab === "overview" && (
          <div className="space-y-4">
            <h3 className="font-semibold">Summary</h3>
            <div className="grid grid-cols-3 gap-4 text-sm">
              <div className="border rounded-lg p-3">
                <div className="text-2xl font-bold">{data.tickets.length}</div>
                <div className="text-ink-mute text-xs">Total Tickets</div>
              </div>
              <div className="border rounded-lg p-3">
                <div className="text-2xl font-bold">{data.payments.length}</div>
                <div className="text-ink-mute text-xs">Payments</div>
              </div>
              <div className="border rounded-lg p-3">
                <div className="text-2xl font-bold text-signal-red">{data.has_hold ? `$${data.unpaid_amount}` : "$0"}</div>
                <div className="text-ink-mute text-xs">Unpaid Balance</div>
              </div>
            </div>
            {data.duplicates.length > 0 && (
              <div className="border border-amber-200 bg-amber-50 rounded-lg p-4">
                <h4 className="font-medium text-amber-800 text-sm mb-2">Duplicate Plate Warning</h4>
                {data.duplicates.map((d: any) => (
                  <div key={d.permit_id} className="text-sm text-amber-700">
                    {d.name} — {d.overlapping_plates.join(", ")} — {d.permit_type} ({d.lot_assignment})
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {tab === "tickets" && (
          <div>
            {data.tickets.length === 0 ? (
              <p className="text-ink-mute text-center py-6">No tickets issued to this permit holder</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-left">
                  <tr>
                    <th className="px-3 py-2 font-medium">Date</th>
                    <th className="px-3 py-2 font-medium">Violation</th>
                    <th className="px-3 py-2 font-medium">Lot</th>
                    <th className="px-3 py-2 font-medium">Fine</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.tickets.map((t: any) => (
                    <tr key={t.id}>
                      <td className="px-3 py-2">{t.issued_at ? new Date(t.issued_at).toLocaleDateString() : "—"}</td>
                      <td className="px-3 py-2 capitalize">{t.violation_type?.replace(/_/g, " ")}</td>
                      <td className="px-3 py-2">{t.lot}</td>
                      <td className="px-3 py-2">${t.fine_amount}</td>
                      <td className="px-3 py-2">
                        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                          t.status === "paid" ? "bg-signal-green/15 text-green-700" :
                          t.status === "voided" ? "bg-gray-100 text-gray-500" :
                          "bg-signal-red/15 text-red-700"
                        }`}>{t.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {tab === "payments" && (
          <div>
            {data.payments.length === 0 ? (
              <p className="text-ink-mute text-center py-6">No payments recorded</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-left">
                  <tr>
                    <th className="px-3 py-2 font-medium">Date</th>
                    <th className="px-3 py-2 font-medium">Amount</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.payments.map((pay: any) => (
                    <tr key={pay.id}>
                      <td className="px-3 py-2">{pay.created_at ? new Date(pay.created_at).toLocaleDateString() : "—"}</td>
                      <td className="px-3 py-2">${pay.amount}</td>
                      <td className="px-3 py-2 capitalize">{pay.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {tab === "timeline" && (
          <div className="space-y-3">
            {data.audit_log.length === 0 ? (
              <p className="text-ink-mute text-center py-6">No activity recorded yet</p>
            ) : (
              data.audit_log.map((entry: any) => (
                <div key={entry.id} className="flex gap-3 items-start border-l-2 border-gray-200 pl-4 py-1">
                  <div className="flex-1">
                    <div className="text-sm">{entry.summary}</div>
                    <div className="text-xs text-ink-mute">
                      {new Date(entry.timestamp).toLocaleString()} by {entry.user_email}
                    </div>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    entry.action === "POST" ? "bg-signal-green/10 text-green-700" :
                    entry.action === "DELETE" ? "bg-signal-red/10 text-red-700" :
                    "bg-blue-50 text-blue-700"
                  }`}>{entry.action}</span>
                </div>
              ))
            )}
          </div>
        )}

        {tab === "related" && (
          <div>
            <h3 className="font-semibold mb-3">Prior / Related Permits</h3>
            {data.prior_permits.length === 0 ? (
              <p className="text-ink-mute text-center py-6">No related permits found</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-left">
                  <tr>
                    <th className="px-3 py-2 font-medium">Name</th>
                    <th className="px-3 py-2 font-medium">Type</th>
                    <th className="px-3 py-2 font-medium">Status</th>
                    <th className="px-3 py-2 font-medium">Dates</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.prior_permits.map((pp: any) => (
                    <tr key={pp.id} className="hover:bg-bone/50 cursor-pointer"
                      onClick={() => navigate(`/permits/${pp.id}`)}>
                      <td className="px-3 py-2">{pp.name}</td>
                      <td className="px-3 py-2 capitalize">{pp.permit_type}</td>
                      <td className="px-3 py-2 capitalize">{pp.status}</td>
                      <td className="px-3 py-2 text-xs">{pp.start_date} — {pp.end_date || "∞"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
