import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";

interface ViolationType {
  id: string;
  code: string;
  label: string;
  category: string;
  fine_first: string;
  fine_second: string | null;
  fine_third_plus: string | null;
  is_active: boolean;
  sort_order: number;
}

function ViolationTypeForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: ViolationType;
  onSave: () => void;
  onCancel: () => void;
}) {
  const [code, setCode] = useState(initial?.code ?? "");
  const [label, setLabel] = useState(initial?.label ?? "");
  const [category, setCategory] = useState(initial?.category ?? "parking");
  const [fineFirst, setFineFirst] = useState(initial?.fine_first ?? "35.00");
  const [fineSecond, setFineSecond] = useState(initial?.fine_second ?? "");
  const [fineThird, setFineThird] = useState(initial?.fine_third_plus ?? "");
  const [sortOrder, setSortOrder] = useState(initial?.sort_order ?? 0);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    const body = {
      code,
      label,
      category,
      fine_first: fineFirst,
      fine_second: fineSecond || null,
      fine_third_plus: fineThird || null,
      sort_order: sortOrder,
    };
    try {
      const method = initial ? "PUT" : "POST";
      const url = initial
        ? `/api/violation-types/${initial.id}`
        : "/api/violation-types";
      await fetch(url, {
        method,
        headers: await authHeaders(),
        body: JSON.stringify(body),
      });
      onSave();
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow p-6 mb-6 grid grid-cols-2 gap-4">
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Code</label>
        <input value={code} onChange={(e) => setCode(e.target.value)} required
          placeholder="e.g. no_permit"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Label</label>
        <input value={label} onChange={(e) => setLabel(e.target.value)} required
          placeholder="e.g. No Valid Permit"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Category</label>
        <select value={category} onChange={(e) => setCategory(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none">
          <option value="parking">Parking</option>
          <option value="moving">Moving</option>
        </select>
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Sort Order</label>
        <input type="number" value={sortOrder} onChange={(e) => setSortOrder(Number(e.target.value))}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Fine (1st Offense)</label>
        <input type="number" step="0.01" value={fineFirst} onChange={(e) => setFineFirst(e.target.value)} required
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Fine (2nd Offense)</label>
        <input type="number" step="0.01" value={fineSecond} onChange={(e) => setFineSecond(e.target.value)}
          placeholder="Leave blank if no escalation"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Fine (3rd+ Offense)</label>
        <input type="number" step="0.01" value={fineThird} onChange={(e) => setFineThird(e.target.value)}
          placeholder="Leave blank if no escalation"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div className="flex items-end">
        <div className="flex gap-3">
          <button type="button" onClick={onCancel}
            className="px-4 py-2 text-sm text-ink-mute hover:text-ink">Cancel</button>
          <button type="submit" disabled={saving}
            className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors disabled:opacity-50">
            {saving ? "Saving..." : initial ? "Update" : "Create"}
          </button>
        </div>
      </div>
    </form>
  );
}

export default function ViolationTypes() {
  const [types, setTypes] = useState<ViolationType[]>([]);
  const [editing, setEditing] = useState<ViolationType | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    const res = await fetch("/api/violation-types?all=true", { headers: await authHeaders() });
    if (res.ok) setTypes(await res.json());
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleDeactivate(id: string) {
    if (!confirm("Deactivate this violation type?")) return;
    await fetch(`/api/violation-types/${id}`, { method: "DELETE", headers: await authHeaders() });
    load();
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Violation Types</h2>
        <button onClick={() => { setCreating(true); setEditing(null); }}
          className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep">
          + New Violation Type
        </button>
      </div>

      {(creating || editing) && (
        <ViolationTypeForm
          initial={editing ?? undefined}
          onSave={() => { setCreating(false); setEditing(null); load(); }}
          onCancel={() => { setCreating(false); setEditing(null); }}
        />
      )}

      <div className="bg-white rounded-xl shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-navy text-bone text-left">
            <tr>
              <th className="px-4 py-3 font-medium">#</th>
              <th className="px-4 py-3 font-medium">Code</th>
              <th className="px-4 py-3 font-medium">Label</th>
              <th className="px-4 py-3 font-medium">Category</th>
              <th className="px-4 py-3 font-medium">1st</th>
              <th className="px-4 py-3 font-medium">2nd</th>
              <th className="px-4 py-3 font-medium">3rd+</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium w-24">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {types.map((vt) => (
              <tr key={vt.id} className={`hover:bg-bone/50 ${!vt.is_active ? "opacity-50" : ""}`}>
                <td className="px-4 py-3 text-ink-mute">{vt.sort_order}</td>
                <td className="px-4 py-3 font-mono text-xs">{vt.code}</td>
                <td className="px-4 py-3">{vt.label}</td>
                <td className="px-4 py-3 capitalize">{vt.category}</td>
                <td className="px-4 py-3">${Number(vt.fine_first).toFixed(0)}</td>
                <td className="px-4 py-3 text-ink-mute">{vt.fine_second ? `$${Number(vt.fine_second).toFixed(0)}` : "—"}</td>
                <td className="px-4 py-3 text-ink-mute">{vt.fine_third_plus ? `$${Number(vt.fine_third_plus).toFixed(0)}` : "—"}</td>
                <td className="px-4 py-3">
                  <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                    vt.is_active ? "bg-signal-green/15 text-green-700" : "bg-gray-100 text-gray-500"
                  }`}>{vt.is_active ? "Active" : "Inactive"}</span>
                </td>
                <td className="px-4 py-3 flex gap-2">
                  <button onClick={() => { setEditing(vt); setCreating(false); }}
                    className="text-brass-deep hover:text-brass text-xs">Edit</button>
                  {vt.is_active && (
                    <button onClick={() => handleDeactivate(vt.id)}
                      className="text-signal-red/70 hover:text-signal-red text-xs">Deactivate</button>
                  )}
                </td>
              </tr>
            ))}
            {types.length === 0 && (
              <tr><td colSpan={9} className="px-4 py-8 text-center text-ink-mute">No violation types configured</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
