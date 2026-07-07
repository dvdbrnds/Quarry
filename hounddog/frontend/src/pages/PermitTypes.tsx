import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
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
  requires_lottery: boolean;
  lottery_strategy: string;
  min_class_year: number | null;
  application_opens_at: string | null;
  application_closes_at: string | null;
  offer_window_days: number;
  lottery_run_at: string | null;
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
  const [requiresLottery, setRequiresLottery] = useState(initial?.requires_lottery ?? false);
  const [lotteryStrategy, setLotteryStrategy] = useState(initial?.lottery_strategy ?? "seniority_timestamp");
  const [minClassYear, setMinClassYear] = useState<string>(initial?.min_class_year?.toString() ?? "");
  const [opensAt, setOpensAt] = useState(initial?.application_opens_at?.slice(0, 16) ?? "");
  const [closesAt, setClosesAt] = useState(initial?.application_closes_at?.slice(0, 16) ?? "");
  const [offerDays, setOfferDays] = useState(initial?.offer_window_days ?? 5);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    const body: Record<string, unknown> = {
      code,
      label,
      eligible,
      price,
      max_capacity: maxCapacity,
      valid_days: validDays,
      lot_assignments: lots.split(",").map((l) => l.trim()).filter(Boolean),
      is_purchasable_online: purchasable,
      sort_order: sortOrder,
      requires_lottery: requiresLottery,
      lottery_strategy: lotteryStrategy,
      min_class_year: minClassYear ? parseInt(minClassYear) : null,
      offer_window_days: offerDays,
      application_opens_at: opensAt ? new Date(opensAt).toISOString() : null,
      application_closes_at: closesAt ? new Date(closesAt).toISOString() : null,
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

      <div className="col-span-2 flex items-center gap-6">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={purchasable} onChange={(e) => setPurchasable(e.target.checked)}
            className="rounded border-gray-300 text-brass focus:ring-brass" />
          Available for online purchase
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={requiresLottery} onChange={(e) => setRequiresLottery(e.target.checked)}
            className="rounded border-gray-300 text-brass focus:ring-brass" />
          Requires lottery
        </label>
      </div>

      {requiresLottery && (
        <>
          <div className="col-span-2 border-t pt-4 mt-2">
            <h4 className="text-sm font-semibold text-navy mb-3">Lottery Configuration</h4>
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Strategy</label>
            <select value={lotteryStrategy} onChange={(e) => setLotteryStrategy(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none">
              <option value="seniority_timestamp">Seniority + Timestamp (Moravian default)</option>
              <option value="seniority_weighted">Seniority Weighted (random)</option>
              <option value="pure_random">Pure Random</option>
              <option value="class_priority">Class Priority (random tiebreak)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Min. Class Year (blank = all)</label>
            <input type="number" value={minClassYear} onChange={(e) => setMinClassYear(e.target.value)}
              placeholder="e.g. 2027 = sophomores+"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
            <p className="text-[10px] text-ink-mute mt-0.5">Students with a graduation year above this cannot apply (blocks first-years)</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Offer Window (days)</label>
            <input type="number" value={offerDays} onChange={(e) => setOfferDays(Number(e.target.value))}
              min={1} max={30}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Application Opens</label>
            <input type="datetime-local" value={opensAt} onChange={(e) => setOpensAt(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Application Closes</label>
            <input type="datetime-local" value={closesAt} onChange={(e) => setClosesAt(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
          </div>
        </>
      )}

      <div className="col-span-2 flex gap-3 justify-end pt-2">
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
  const navigate = useNavigate();
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
              <th className="px-4 py-3 font-medium">Type</th>
              <th className="px-4 py-3 font-medium w-32">Actions</th>
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
                  {pt.requires_lottery ? (
                    <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-purple-100 text-purple-700">
                      Lottery
                    </span>
                  ) : pt.is_purchasable_online ? (
                    <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-green-100 text-green-700">
                      Online
                    </span>
                  ) : (
                    <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
                      Manual
                    </span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button onClick={() => { setEditing(pt); setCreating(false); }}
                      className="text-brass-deep hover:text-brass text-xs">Edit</button>
                    {pt.requires_lottery && pt.is_active && (
                      <button onClick={() => navigate("/permits#lottery")}
                        className="text-purple-600 hover:text-purple-800 text-xs">Manage Lottery</button>
                    )}
                    {pt.is_active && (
                      <button onClick={() => handleDeactivate(pt.id)}
                        className="text-signal-red/70 hover:text-signal-red text-xs">Deactivate</button>
                    )}
                  </div>
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
