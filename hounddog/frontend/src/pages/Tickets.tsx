import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";

interface Ticket {
  id: string;
  plate: string;
  lot: string;
  zone: string | null;
  violation_type: string;
  fine_amount: string;
  photo_url: string | null;
  officer_id: string;
  officer_name: string | null;
  officer_email: string | null;
  issued_at: string;
  status: string;
  appeal_note: string | null;
  appeal_decision: string | null;
  appeal_decided_by: string | null;
}

interface TicketList {
  items: Ticket[];
  total: number;
  page: number;
  page_size: number;
}

const STATUS_COLORS: Record<string, string> = {
  issued: "bg-signal-red/15 text-red-700",
  pending_payment: "bg-orange-100 text-orange-700",
  paid: "bg-signal-green/15 text-green-700",
  appealed: "bg-yellow-100 text-yellow-700",
  escalated: "bg-purple-100 text-purple-700",
  voided: "bg-gray-100 text-gray-500",
};

export default function Tickets() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selected, setSelected] = useState<Ticket | null>(null);

  const load = useCallback(async () => {
    const qs = new URLSearchParams();
    qs.set("page", String(page));
    if (search) qs.set("search", search);
    if (statusFilter) qs.set("status", statusFilter);
    const res = await fetch(`/api/tickets?${qs}`, { headers: await authHeaders() });
    if (res.ok) {
      const data: TicketList = await res.json();
      setTickets(data.items);
      setTotal(data.total);
    }
  }, [page, search, statusFilter]);

  useEffect(() => { load(); }, [load]);

  async function handleVoid(id: string) {
    if (!confirm("Void this ticket?")) return;
    await fetch(`/api/tickets/${id}/void`, { method: "POST", headers: await authHeaders() });
    load();
    setSelected(null);
  }

  async function handleAppealDecision(id: string, decision: string) {
    const decided_by = prompt("Your name for the record:");
    if (!decided_by) return;
    await fetch(`/api/tickets/${id}/appeal/decide`, {
      method: "POST",
      headers: await authHeaders(),
      body: JSON.stringify({ decision, decided_by }),
    });
    load();
    setSelected(null);
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Tickets</h2>
      </div>

      <div className="flex gap-3 mb-4">
        <input
          type="text"
          placeholder="Search by plate or officer..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          className="flex-1 max-w-md border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
        />
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
        >
          <option value="">All Statuses</option>
          <option value="issued">Issued</option>
          <option value="pending_payment">Pending Payment</option>
          <option value="paid">Paid</option>
          <option value="appealed">Appealed</option>
          <option value="escalated">Escalated</option>
          <option value="voided">Voided</option>
        </select>
      </div>

      <div className="bg-white rounded-xl shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-navy text-bone text-left">
            <tr>
              <th className="px-4 py-3 font-medium">Plate</th>
              <th className="px-4 py-3 font-medium">Lot</th>
              <th className="px-4 py-3 font-medium">Violation</th>
              <th className="px-4 py-3 font-medium">Fine</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Issued</th>
              <th className="px-4 py-3 font-medium w-24">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {tickets.map((t) => (
              <tr key={t.id} className="hover:bg-bone/50 cursor-pointer" onClick={() => setSelected(t)}>
                <td className="px-4 py-3 font-mono">{t.plate}</td>
                <td className="px-4 py-3">{t.lot}</td>
                <td className="px-4 py-3 capitalize">{t.violation_type.replace("_", " ")}</td>
                <td className="px-4 py-3">${Number(t.fine_amount).toFixed(2)}</td>
                <td className="px-4 py-3">
                  <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                    STATUS_COLORS[t.status] || "bg-gray-100"
                  }`}>{t.status.replace("_", " ")}</span>
                </td>
                <td className="px-4 py-3 text-xs text-ink-mute">
                  {new Date(t.issued_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3">
                  {!["paid", "voided"].includes(t.status) && (
                    <button onClick={(e) => { e.stopPropagation(); handleVoid(t.id); }}
                      className="text-signal-red/70 hover:text-signal-red text-xs">Void</button>
                  )}
                </td>
              </tr>
            ))}
            {tickets.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-ink-mute">No tickets found</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {total > 50 && (
        <div className="flex justify-center gap-2 mt-4">
          <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1}
            className="px-3 py-1 rounded border text-sm disabled:opacity-30">Prev</button>
          <span className="px-3 py-1 text-sm text-ink-mute">
            Page {page} of {Math.ceil(total / 50)}
          </span>
          <button onClick={() => setPage(page + 1)} disabled={page >= Math.ceil(total / 50)}
            className="px-3 py-1 rounded border text-sm disabled:opacity-30">Next</button>
        </div>
      )}

      {selected && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setSelected(null)}>
          <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-4">Ticket Detail</h3>
            <div className="grid grid-cols-2 gap-3 text-sm mb-4">
              <div><span className="text-ink-mute">Plate:</span> <span className="font-mono">{selected.plate}</span></div>
              <div><span className="text-ink-mute">Lot:</span> {selected.lot}</div>
              <div><span className="text-ink-mute">Violation:</span> {selected.violation_type}</div>
              <div><span className="text-ink-mute">Fine:</span> ${Number(selected.fine_amount).toFixed(2)}</div>
              <div><span className="text-ink-mute">Status:</span> {selected.status}</div>
              <div><span className="text-ink-mute">Officer:</span> {selected.officer_name || selected.officer_id}</div>
              <div className="col-span-2"><span className="text-ink-mute">Issued:</span> {new Date(selected.issued_at).toLocaleString()}</div>
            </div>

            {selected.photo_url && (
              <img src={selected.photo_url} alt="Violation photo" className="w-full rounded-lg mb-4 max-h-48 object-cover" />
            )}

            {selected.appeal_note && (
              <div className="bg-yellow-50 rounded-lg p-3 mb-4 text-sm">
                <div className="font-medium text-yellow-800 mb-1">Appeal Note</div>
                <p>{selected.appeal_note}</p>
                {selected.appeal_decision && (
                  <div className="mt-2 text-xs text-ink-mute">
                    Decision: <strong>{selected.appeal_decision}</strong>
                    {selected.appeal_decided_by && ` by ${selected.appeal_decided_by}`}
                  </div>
                )}
              </div>
            )}

            <div className="flex gap-3 justify-end">
              <button onClick={() => setSelected(null)} className="px-4 py-2 text-sm text-ink-mute">Close</button>
              {selected.appeal_decision === "pending" && (
                <>
                  <button onClick={() => handleAppealDecision(selected.id, "approved")}
                    className="px-4 py-2 bg-signal-green text-white rounded-lg text-sm">Approve Appeal</button>
                  <button onClick={() => handleAppealDecision(selected.id, "denied")}
                    className="px-4 py-2 bg-signal-red text-white rounded-lg text-sm">Deny Appeal</button>
                </>
              )}
              {!["paid", "voided"].includes(selected.status) && (
                <button onClick={() => handleVoid(selected.id)}
                  className="px-4 py-2 bg-signal-red/80 text-white rounded-lg text-sm">Void Ticket</button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
