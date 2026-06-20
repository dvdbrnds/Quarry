import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";

interface PermitTypeRow {
  id: string;
  code: string;
  label: string;
  eligible: string;
  price: string;
  max_capacity: number;
  valid_days: number;
  lot_assignments: string[];
  time_restriction: string | null;
  is_purchasable_online: boolean;
  is_active: boolean;
  sort_order: number;
  active_count: number;
  remaining: number;
}

function PermitTypeForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: PermitTypeRow;
  onSave: () => void;
  onCancel: () => void;
}) {
  const [code, setCode] = useState(initial?.code ?? "");
  const [label, setLabel] = useState(initial?.label ?? "");
  const [eligible, setEligible] = useState(initial?.eligible ?? "");
  const [price, setPrice] = useState(initial?.price ?? "0.00");
  const [maxCapacity, setMaxCapacity] = useState(initial?.max_capacity ?? 100);
  const [validDays, setValidDays] = useState(initial?.valid_days ?? 365);
  const [lots, setLots] = useState(initial?.lot_assignments.join(", ") ?? "");
  const [purchasable, setPurchasable] = useState(initial?.is_purchasable_online ?? false);
  const [sortOrder, setSortOrder] = useState(initial?.sort_order ?? 0);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    const body = {
      code,
      label,
      eligible,
      price,
      max_capacity: maxCapacity,
      valid_days: validDays,
      lot_assignments: lots.split(",").map((l) => l.trim()).filter(Boolean),
      is_purchasable_online: purchasable,
      sort_order: sortOrder,
    };
    try {
      const method = initial ? "PUT" : "POST";
      const url = initial ? `/api/permit-types/${initial.id}` : "/api/permit-types";
      await fetch(url, { method, headers: await authHeaders(), body: JSON.stringify(body) });
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
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Label</label>
        <input value={label} onChange={(e) => setLabel(e.target.value)} required
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Eligible</label>
        <input value={eligible} onChange={(e) => setEligible(e.target.value)}
          placeholder="Who can purchase this type"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Price ($)</label>
        <input type="number" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Max Capacity</label>
        <input type="number" value={maxCapacity} onChange={(e) => setMaxCapacity(Number(e.target.value))}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Valid Days</label>
        <input type="number" value={validDays} onChange={(e) => setValidDays(Number(e.target.value))}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Lot Assignments (comma-separated)</label>
        <input value={lots} onChange={(e) => setLots(e.target.value)}
          placeholder="A, F, H, M"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Sort Order</label>
        <input type="number" value={sortOrder} onChange={(e) => setSortOrder(Number(e.target.value))}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div className="col-span-2 flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={purchasable} onChange={(e) => setPurchasable(e.target.checked)}
            className="rounded border-gray-300 text-brass focus:ring-brass" />
          Available for online purchase (payment portal)
        </label>
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

export default function PermitTypes() {
  const [types, setTypes] = useState<PermitTypeRow[]>([]);
  const [editing, setEditing] = useState<PermitTypeRow | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    const res = await fetch("/api/permit-types?all=true", { headers: await authHeaders() });
    if (res.ok) setTypes(await res.json());
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleDeactivate(id: string) {
    if (!confirm("Deactivate this permit type?")) return;
    await fetch(`/api/permit-types/${id}`, { method: "DELETE", headers: await authHeaders() });
    load();
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Permit Types</h2>
        <button onClick={() => { setCreating(true); setEditing(null); }}
          className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep">
          + New Permit Type
        </button>
      </div>

      {(creating || editing) && (
        <PermitTypeForm
          initial={editing ?? undefined}
          onSave={() => { setCreating(false); setEditing(null); load(); }}
          onCancel={() => { setCreating(false); setEditing(null); }}
        />
      )}

      <div className="bg-white rounded-xl shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-navy text-bone text-left">
            <tr>
              <th className="px-4 py-3 font-medium">Label</th>
              <th className="px-4 py-3 font-medium">Code</th>
              <th className="px-4 py-3 font-medium">Price</th>
              <th className="px-4 py-3 font-medium">Capacity</th>
              <th className="px-4 py-3 font-medium">Used / Remaining</th>
              <th className="px-4 py-3 font-medium">Online</th>
              <th className="px-4 py-3 font-medium w-24">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {types.map((pt) => (
              <tr key={pt.id} className={`hover:bg-bone/50 ${!pt.is_active ? "opacity-50" : ""}`}>
                <td className="px-4 py-3 font-medium">{pt.label}</td>
                <td className="px-4 py-3 font-mono text-xs">{pt.code}</td>
                <td className="px-4 py-3">{Number(pt.price) === 0 ? "Free" : `$${Number(pt.price).toFixed(0)}`}</td>
                <td className="px-4 py-3">{pt.max_capacity}</td>
                <td className="px-4 py-3">
                  <span className="text-ink-mute">{pt.active_count}</span>
                  <span className="mx-1">/</span>
                  <span className={pt.remaining === 0 ? "text-signal-red font-medium" : "text-signal-green"}>
                    {pt.remaining} left
                  </span>
                </td>
                <td className="px-4 py-3">
                  {pt.is_purchasable_online ? (
                    <span className="text-signal-green text-xs font-medium">Yes</span>
                  ) : (
                    <span className="text-ink-mute text-xs">No</span>
                  )}
                </td>
                <td className="px-4 py-3 flex gap-2">
                  <button onClick={() => { setEditing(pt); setCreating(false); }}
                    className="text-brass-deep hover:text-brass text-xs">Edit</button>
                  {pt.is_active && (
                    <button onClick={() => handleDeactivate(pt.id)}
                      className="text-signal-red/70 hover:text-signal-red text-xs">Deactivate</button>
                  )}
                </td>
              </tr>
            ))}
            {types.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-ink-mute">No permit types configured</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
