import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Permit, ImportResult } from "../api";
import { authHeaders } from "../auth";

interface PermitStats {
  total: number;
  active: number;
  expired: number;
  expiring_soon: number;
  revoked: number;
}

interface PermitTypeOption {
  code: string;
  label: string;
}

interface LotOption {
  id: string;
  name: string;
}

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className={`rounded-lg border px-4 py-3 ${color}`}>
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-xs text-ink-mute">{label}</div>
    </div>
  );
}

function PermitForm({
  initial,
  permitTypes,
  lots,
  onSave,
  onCancel,
}: {
  initial?: Permit;
  permitTypes: PermitTypeOption[];
  lots: LotOption[];
  onSave: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [plates, setPlates] = useState(initial?.plates.join(", ") ?? "");
  const [studentId, setStudentId] = useState(initial?.student_id ?? "");
  const [lot, setLot] = useState(initial?.lot_assignment ?? "");
  const [permitType, setPermitType] = useState(initial?.permit_type ?? "");
  const [status, setStatus] = useState(initial?.status ?? "active");
  const [startDate, setStartDate] = useState(initial?.start_date ?? new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState(initial?.end_date ?? "");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    const data = {
      name,
      plates: plates.split(",").map((p) => p.trim().toUpperCase()).filter(Boolean),
      student_id: studentId,
      lot_assignment: lot,
      permit_type: permitType,
      status,
      start_date: startDate || undefined,
      end_date: endDate || null,
    };
    try {
      if (initial) {
        await api.permits.update(initial.id, data);
      } else {
        await api.permits.create(data);
      }
      onSave();
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow p-6 mb-6 grid grid-cols-2 gap-4">
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} required
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Plates (comma-separated)</label>
        <input value={plates} onChange={(e) => setPlates(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Student ID</label>
        <input value={studentId} onChange={(e) => setStudentId(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Lot Assignment</label>
        <select value={lot} onChange={(e) => setLot(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none">
          <option value="">— Select —</option>
          {lots.map(l => <option key={l.id} value={l.name}>{l.name}</option>)}
        </select>
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Permit Type</label>
        <select value={permitType} onChange={(e) => setPermitType(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none">
          <option value="">— Select —</option>
          {permitTypes.map(pt => <option key={pt.code} value={pt.code}>{pt.label}</option>)}
        </select>
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Status</label>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none">
          <option value="active">Active</option>
          <option value="expired">Expired</option>
          <option value="revoked">Revoked</option>
          <option value="suspended">Suspended</option>
        </select>
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Start Date</label>
        <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">End Date</label>
        <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div className="col-span-2 flex gap-3 justify-end">
        <button type="button" onClick={onCancel}
          className="px-4 py-2 text-sm text-ink-mute hover:text-ink">Cancel</button>
        <button type="submit" disabled={saving}
          className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors disabled:opacity-50">
          {saving ? "Saving..." : initial ? "Update" : "Create"}
        </button>
      </div>
    </form>
  );
}

function ImportModal({ onClose, onImported }: { onClose: () => void; onImported: (result: ImportResult) => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);

  async function handleFile() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const text = await file.text();
      const lines = text.split("\n").filter(Boolean);
      if (lines.length < 2) return;
      const headers = lines[0].split(",").map((h) => h.trim().toLowerCase());
      const permits = lines.slice(1).map((line) => {
        const vals = line.split(",");
        const row: Record<string, string> = {};
        headers.forEach((h, i) => (row[h] = vals[i]?.trim() ?? ""));
        return {
          plate_normalized: row.plate_normalized || row.plate || "",
          owner_name: row.owner_name || row.name || "",
          permit_number: row.permit_number || row.student_id || "",
          permit_type: row.permit_type || "student",
          permit_status: row.permit_status || row.status || "active",
          lot_zone: row.lot_zone || row.lot || "",
        };
      });
      const result = await api.permits.importJson(permits);
      onImported(result);
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-md">
        <h3 className="text-lg font-semibold mb-4">Import Permits (CSV)</h3>
        <p className="text-sm text-ink-mute mb-4">
          CSV columns: <code>plate_normalized</code>, <code>owner_name</code>, <code>permit_number</code>, <code>permit_type</code>, <code>lot_zone</code>
        </p>
        <input ref={fileRef} type="file" accept=".csv" className="mb-4" />
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-ink-mute">Cancel</button>
          <button onClick={handleFile} disabled={importing}
            className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm disabled:opacity-50">
            {importing ? "Importing..." : "Import"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Permits() {
  const navigate = useNavigate();
  const [permits, setPermits] = useState<Permit[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterLot, setFilterLot] = useState("");
  const [sort, setSort] = useState("");
  const [editing, setEditing] = useState<Permit | null>(null);
  const [creating, setCreating] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [stats, setStats] = useState<PermitStats | null>(null);
  const [permitTypes, setPermitTypes] = useState<PermitTypeOption[]>([]);
  const [lots, setLots] = useState<LotOption[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkAction, setBulkAction] = useState("");

  const load = useCallback(async () => {
    const data = await api.permits.list({
      page,
      search: search || undefined,
      status: filterStatus || undefined,
      lot: filterLot || undefined,
      permit_type: filterType || undefined,
      sort: sort || undefined,
    });
    setPermits(data.items);
    setTotal(data.total);
  }, [page, search, filterStatus, filterType, filterLot, sort]);

  const loadMeta = useCallback(async () => {
    const [s, ptRes, lotsRes] = await Promise.all([
      api.permits.stats(),
      fetch("/api/permit-types", { headers: await authHeaders() }).then(r => r.json()),
      api.lots.list(),
    ]);
    setStats(s);
    setPermitTypes(ptRes.map((pt: any) => ({ code: pt.code, label: pt.label })));
    setLots(lotsRes.map((l: any) => ({ id: l.id, name: l.name })));
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadMeta(); }, [loadMeta]);

  async function handleDelete(id: string) {
    if (!confirm("Delete this permit?")) return;
    await api.permits.delete(id);
    load();
    loadMeta();
  }

  async function handleBulkAction() {
    if (!bulkAction || selected.size === 0) return;
    if (!confirm(`Set ${selected.size} permits to "${bulkAction}"?`)) return;
    await api.permits.bulkStatus(Array.from(selected), bulkAction);
    setSelected(new Set());
    setBulkAction("");
    load();
    loadMeta();
  }

  function toggleSelect(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelected(next);
  }

  function toggleAll() {
    if (selected.size === permits.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(permits.map(p => p.id)));
    }
  }

  function handleSort(field: string) {
    if (sort === field) setSort(`-${field}`);
    else if (sort === `-${field}`) setSort("");
    else setSort(field);
  }

  function sortIcon(field: string) {
    if (sort === field) return " ▲";
    if (sort === `-${field}`) return " ▼";
    return "";
  }

  const hasFilters = filterStatus || filterType || filterLot;
  const isExpiringSoon = (p: Permit) => {
    if (!p.end_date || p.status !== "active") return false;
    const end = new Date(p.end_date);
    const now = new Date();
    const diff = (end.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);
    return diff >= 0 && diff <= 30;
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">Permits</h2>
        <div className="flex gap-3">
          <button onClick={() => setShowImport(true)}
            className="px-4 py-2 border border-brass text-brass-deep rounded-lg text-sm hover:bg-brass/10">
            Import CSV
          </button>
          <a href="/api/permits/export/csv" target="_blank"
            className="px-4 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">
            Export CSV
          </a>
          <button onClick={() => { setCreating(true); setEditing(null); }}
            className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep">
            + New Permit
          </button>
        </div>
      </div>

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-5 gap-3 mb-4">
          <StatCard label="Total" value={stats.total} color="bg-white border-gray-200" />
          <StatCard label="Active" value={stats.active} color="bg-signal-green/5 border-signal-green/20" />
          <StatCard label="Expiring Soon" value={stats.expiring_soon} color="bg-amber-50 border-amber-200" />
          <StatCard label="Expired" value={stats.expired} color="bg-signal-red/5 border-signal-red/20" />
          <StatCard label="Revoked" value={stats.revoked} color="bg-gray-50 border-gray-200" />
        </div>
      )}

      {/* Filter Bar */}
      <div className="flex flex-wrap gap-3 mb-4 items-center">
        <input
          type="text"
          placeholder="Search name, ID, or plate..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-64 focus:ring-2 focus:ring-brass focus:outline-none"
        />
        <select value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none">
          <option value="">All Statuses</option>
          <option value="active">Active</option>
          <option value="expiring_soon">Expiring Soon</option>
          <option value="expired">Expired</option>
          <option value="revoked">Revoked</option>
          <option value="suspended">Suspended</option>
        </select>
        <select value={filterType} onChange={(e) => { setFilterType(e.target.value); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none">
          <option value="">All Types</option>
          {permitTypes.map(pt => <option key={pt.code} value={pt.code}>{pt.label}</option>)}
        </select>
        <select value={filterLot} onChange={(e) => { setFilterLot(e.target.value); setPage(1); }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none">
          <option value="">All Lots</option>
          {lots.map(l => <option key={l.id} value={l.name}>{l.name}</option>)}
        </select>
        {hasFilters && (
          <button onClick={() => { setFilterStatus(""); setFilterType(""); setFilterLot(""); setPage(1); }}
            className="text-xs text-signal-red hover:underline">Clear Filters</button>
        )}
      </div>

      {importResult && (
        <div className="bg-signal-green/10 border border-signal-green/30 rounded-lg px-4 py-3 mb-4 text-sm flex justify-between items-center">
          <span>Imported: {importResult.inserted} new, {importResult.updated} updated, {importResult.skipped} skipped</span>
          <button onClick={() => setImportResult(null)} className="text-ink-mute hover:text-ink">&times;</button>
        </div>
      )}

      {(creating || editing) && (
        <PermitForm
          initial={editing ?? undefined}
          permitTypes={permitTypes}
          lots={lots}
          onSave={() => { setCreating(false); setEditing(null); load(); loadMeta(); }}
          onCancel={() => { setCreating(false); setEditing(null); }}
        />
      )}

      {/* Bulk Actions */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 mb-3 bg-navy/5 rounded-lg px-4 py-2">
          <span className="text-sm font-medium">{selected.size} selected</span>
          <select value={bulkAction} onChange={(e) => setBulkAction(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1 text-sm">
            <option value="">— Action —</option>
            <option value="revoked">Revoke</option>
            <option value="expired">Expire</option>
            <option value="suspended">Suspend</option>
            <option value="active">Reactivate</option>
          </select>
          <button onClick={handleBulkAction} disabled={!bulkAction}
            className="px-3 py-1 bg-navy text-bone text-sm rounded disabled:opacity-50">Apply</button>
          <button onClick={() => setSelected(new Set())} className="text-xs text-ink-mute ml-auto">Deselect All</button>
        </div>
      )}

      {/* Table */}
      <div className="bg-white rounded-xl shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-navy text-bone text-left">
            <tr>
              <th className="px-3 py-3 w-8">
                <input type="checkbox" checked={selected.size === permits.length && permits.length > 0}
                  onChange={toggleAll} className="rounded border-gray-300" />
              </th>
              <th className="px-3 py-3 font-medium cursor-pointer" onClick={() => handleSort("name")}>
                Name{sortIcon("name")}
              </th>
              <th className="px-3 py-3 font-medium">Plates</th>
              <th className="px-3 py-3 font-medium cursor-pointer" onClick={() => handleSort("lot_assignment")}>
                Lot{sortIcon("lot_assignment")}
              </th>
              <th className="px-3 py-3 font-medium cursor-pointer" onClick={() => handleSort("permit_type")}>
                Type{sortIcon("permit_type")}
              </th>
              <th className="px-3 py-3 font-medium cursor-pointer" onClick={() => handleSort("end_date")}>
                Expires{sortIcon("end_date")}
              </th>
              <th className="px-3 py-3 font-medium cursor-pointer" onClick={() => handleSort("status")}>
                Status{sortIcon("status")}
              </th>
              <th className="px-3 py-3 font-medium w-24">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {permits.map((p) => (
              <tr key={p.id} className="hover:bg-bone/50 cursor-pointer"
                onClick={() => navigate(`/permits/${p.id}`)}>
                <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={selected.has(p.id)}
                    onChange={() => toggleSelect(p.id)} className="rounded border-gray-300" />
                </td>
                <td className="px-3 py-3 font-medium">{p.name}</td>
                <td className="px-3 py-3 font-mono text-xs">{p.plates.join(", ")}</td>
                <td className="px-3 py-3">{p.lot_assignment}</td>
                <td className="px-3 py-3 capitalize">{p.permit_type}</td>
                <td className="px-3 py-3">
                  {p.end_date ? (
                    <span className={isExpiringSoon(p) ? "text-amber-600 font-medium" : ""}>
                      {p.end_date}
                    </span>
                  ) : <span className="text-ink-mute">—</span>}
                </td>
                <td className="px-3 py-3">
                  <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                    p.status === "active" ? "bg-signal-green/15 text-green-700" :
                    p.status === "expired" || p.status === "renewed" ? "bg-gray-100 text-gray-500" :
                    "bg-signal-red/15 text-red-700"
                  }`}>{p.status}</span>
                  {isExpiringSoon(p) && (
                    <span className="ml-1 inline-block px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-100 text-amber-700">EXPIRING</span>
                  )}
                </td>
                <td className="px-3 py-3 flex gap-2" onClick={(e) => e.stopPropagation()}>
                  <button onClick={() => { setEditing(p); setCreating(false); }}
                    className="text-brass-deep hover:text-brass text-xs">Edit</button>
                  <button onClick={() => handleDelete(p.id)}
                    className="text-signal-red/70 hover:text-signal-red text-xs">Del</button>
                </td>
              </tr>
            ))}
            {permits.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-ink-mute">No permits found</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex justify-between items-center mt-4">
        <span className="text-sm text-ink-mute">
          Showing {Math.min((page - 1) * 50 + 1, total)}–{Math.min(page * 50, total)} of {total}
        </span>
        <div className="flex gap-2">
          <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1}
            className="px-3 py-1 rounded border text-sm disabled:opacity-30">Prev</button>
          <button onClick={() => setPage(page + 1)} disabled={page >= Math.ceil(total / 50)}
            className="px-3 py-1 rounded border text-sm disabled:opacity-30">Next</button>
        </div>
      </div>

      {showImport && (
        <ImportModal
          onClose={() => setShowImport(false)}
          onImported={(result) => {
            setImportResult(result);
            setShowImport(false);
            load();
            loadMeta();
          }}
        />
      )}
    </div>
  );
}
