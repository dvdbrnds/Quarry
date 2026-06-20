import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";

interface AuditEntry {
  id: string;
  timestamp: string;
  user_email: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  endpoint: string;
  summary: string;
  response_status: number;
  ip_address: string | null;
  changes: Record<string, any> | null;
}

interface AuditListResponse {
  items: AuditEntry[];
  total: number;
  page: number;
  page_size: number;
}

const ACTION_COLORS: Record<string, string> = {
  POST: "bg-signal-green/10 text-green-700",
  PUT: "bg-blue-50 text-blue-700",
  PATCH: "bg-amber-50 text-amber-700",
  DELETE: "bg-signal-red/10 text-red-700",
};

const RESOURCE_TYPES = [
  "permits", "tickets", "lots", "devices", "violation_types",
  "permit_types", "academic_calendar", "settings", "payments",
];

export default function ActivityLog() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filterUser, setFilterUser] = useState("");
  const [filterResource, setFilterResource] = useState("");
  const [filterAction, setFilterAction] = useState("");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    const qs = new URLSearchParams();
    qs.set("page", String(page));
    qs.set("page_size", "50");
    if (filterUser) qs.set("user_email", filterUser);
    if (filterResource) qs.set("resource_type", filterResource);
    if (filterAction) qs.set("action", filterAction);
    if (search) qs.set("search", search);

    const res = await fetch(`/api/audit?${qs}`, { headers: await authHeaders() });
    if (res.ok) {
      const data: AuditListResponse = await res.json();
      setEntries(data.items);
      setTotal(data.total);
    }
  }, [page, filterUser, filterResource, filterAction, search]);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Activity Log</h2>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <input
          type="text"
          placeholder="Search actions..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-56 focus:ring-2 focus:ring-brass focus:outline-none"
        />
        <input
          type="text"
          placeholder="Filter by user email..."
          value={filterUser}
          onChange={(e) => { setFilterUser(e.target.value); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-48 focus:ring-2 focus:ring-brass focus:outline-none"
        />
        <select value={filterResource} onChange={(e) => { setFilterResource(e.target.value); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none">
          <option value="">All Resources</option>
          {RESOURCE_TYPES.map(r => (
            <option key={r} value={r}>{r.replace(/_/g, " ")}</option>
          ))}
        </select>
        <select value={filterAction} onChange={(e) => { setFilterAction(e.target.value); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none">
          <option value="">All Actions</option>
          <option value="POST">Create</option>
          <option value="PUT">Update</option>
          <option value="DELETE">Delete</option>
          <option value="PATCH">Patch</option>
        </select>
        {(filterUser || filterResource || filterAction || search) && (
          <button onClick={() => { setFilterUser(""); setFilterResource(""); setFilterAction(""); setSearch(""); setPage(1); }}
            className="text-xs text-signal-red hover:underline">Clear</button>
        )}
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-navy text-bone text-left">
            <tr>
              <th className="px-4 py-3 font-medium">Time</th>
              <th className="px-4 py-3 font-medium">User</th>
              <th className="px-4 py-3 font-medium">Action</th>
              <th className="px-4 py-3 font-medium">Resource</th>
              <th className="px-4 py-3 font-medium">Summary</th>
              <th className="px-4 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {entries.map((entry) => (
              <tr key={entry.id}
                className="hover:bg-bone/50 cursor-pointer"
                onClick={() => setExpanded(expanded === entry.id ? null : entry.id)}>
                <td className="px-4 py-3 text-xs whitespace-nowrap">
                  {new Date(entry.timestamp).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-xs">{entry.user_email}</td>
                <td className="px-4 py-3">
                  <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${ACTION_COLORS[entry.action] || "bg-gray-100"}`}>
                    {entry.action}
                  </span>
                </td>
                <td className="px-4 py-3 capitalize text-xs">
                  {entry.resource_type.replace(/_/g, " ")}
                  {entry.resource_id && (
                    <span className="text-ink-mute ml-1">#{entry.resource_id.slice(0, 8)}</span>
                  )}
                </td>
                <td className="px-4 py-3">{entry.summary}</td>
                <td className="px-4 py-3">
                  <span className={`text-xs font-mono ${entry.response_status < 300 ? "text-green-600" : entry.response_status < 500 ? "text-amber-600" : "text-red-600"}`}>
                    {entry.response_status}
                  </span>
                </td>
              </tr>
            ))}
            {entries.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-ink-mute">No activity recorded yet</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Expanded detail */}
      {expanded && (() => {
        const entry = entries.find(e => e.id === expanded);
        if (!entry?.changes) return null;
        return (
          <div className="mt-2 bg-gray-50 rounded-lg p-4 text-xs font-mono">
            <h4 className="font-bold mb-2 text-sm font-sans">Changes</h4>
            {Object.entries(entry.changes).map(([field, vals]: [string, any]) => (
              <div key={field} className="flex gap-2 mb-1">
                <span className="font-medium w-32">{field}:</span>
                <span className="text-signal-red line-through">{JSON.stringify(vals?.old)}</span>
                <span>&rarr;</span>
                <span className="text-signal-green">{JSON.stringify(vals?.new)}</span>
              </div>
            ))}
          </div>
        );
      })()}

      {/* Pagination */}
      <div className="flex justify-between items-center mt-4">
        <span className="text-sm text-ink-mute">
          {total > 0 ? `Showing ${(page - 1) * 50 + 1}–${Math.min(page * 50, total)} of ${total}` : "No entries"}
        </span>
        <div className="flex gap-2">
          <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1}
            className="px-3 py-1 rounded border text-sm disabled:opacity-30">Prev</button>
          <button onClick={() => setPage(page + 1)} disabled={page >= Math.ceil(total / 50)}
            className="px-3 py-1 rounded border text-sm disabled:opacity-30">Next</button>
        </div>
      </div>
    </div>
  );
}
