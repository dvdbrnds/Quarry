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
  requires_lottery: boolean;
  lottery_strategy: string;
  application_opens_at: string | null;
  application_closes_at: string | null;
  offer_window_days: number;
  lottery_run_at: string | null;
}

interface Application {
  id: string;
  student_email: string;
  student_name: string;
  class_year: number;
  plate: string;
  phone: string | null;
  status: string;
  lottery_rank: number | null;
  waitlist_position: number | null;
  offer_expires_at: string | null;
  created_at: string;
}

const STRATEGY_LABELS: Record<string, string> = {
  seniority_weighted: "Seniority Weighted (random, seniors favored)",
  pure_random: "Pure Random (equal chance)",
  class_priority: "Class Priority (seniors first, deterministic)",
};

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
  const [lotteryStrategy, setLotteryStrategy] = useState(initial?.lottery_strategy ?? "seniority_weighted");
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
              <option value="seniority_weighted">Seniority Weighted</option>
              <option value="pure_random">Pure Random</option>
              <option value="class_priority">Class Priority (seniors first)</option>
            </select>
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

function LotteryPanel({
  permitType,
  onDone,
}: {
  permitType: PermitTypeRow;
  onDone: () => void;
}) {
  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [advancing, setAdvancing] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/permit-types/${permitType.id}/applications`, {
        headers: await authHeaders(),
      });
      if (res.ok) setApplications(await res.json());
    } finally {
      setLoading(false);
    }
  }, [permitType.id]);

  useEffect(() => { load(); }, [load]);

  const now = new Date();
  const windowClosed = permitType.application_closes_at
    ? new Date(permitType.application_closes_at) < now
    : true;
  const lotteryAlreadyRun = !!permitType.lottery_run_at;
  const pendingCount = applications.filter((a) => a.status === "pending").length;
  const selectedCount = applications.filter((a) => a.status === "selected").length;
  const waitlistedCount = applications.filter((a) => a.status === "waitlisted").length;
  const acceptedCount = applications.filter((a) => a.status === "accepted").length;

  async function handleRunLottery() {
    if (!confirm(`Run the lottery for ${permitType.label}? This will select winners from ${pendingCount} pending applications.`)) return;
    setRunning(true);
    setError("");
    setMessage("");
    try {
      const res = await fetch(`/api/permit-types/${permitType.id}/run-lottery`, {
        method: "POST",
        headers: await authHeaders(),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Lottery failed");
      }
      const result = await res.json();
      setMessage(`Lottery complete: ${result.selected} selected, ${result.waitlisted} waitlisted out of ${result.total_applicants} applicants.`);
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  }

  async function handleAdvanceWaitlist() {
    setAdvancing(true);
    setError("");
    setMessage("");
    try {
      const res = await fetch(`/api/permit-types/${permitType.id}/advance-waitlist`, {
        method: "POST",
        headers: await authHeaders(),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Failed");
      }
      const result = await res.json();
      setMessage(`Expired ${result.expired} overdue offers, advanced ${result.advanced} from waitlist.`);
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setAdvancing(false);
    }
  }

  const STATUS_COLORS: Record<string, string> = {
    pending: "bg-yellow-100 text-yellow-800",
    selected: "bg-green-100 text-green-800",
    waitlisted: "bg-blue-100 text-blue-700",
    accepted: "bg-green-50 text-green-700",
    expired: "bg-gray-100 text-gray-500",
    declined: "bg-gray-100 text-gray-500",
  };

  return (
    <div className="bg-white rounded-xl shadow p-6 mb-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-navy">
            Lottery: {permitType.label}
          </h3>
          <p className="text-xs text-ink-mute mt-0.5">
            Strategy: {STRATEGY_LABELS[permitType.lottery_strategy] || permitType.lottery_strategy}
          </p>
        </div>
        <button onClick={onDone} className="text-sm text-ink-mute hover:text-ink">
          Close
        </button>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-5 gap-3 mb-5">
        <div className="bg-gray-50 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-navy">{applications.length}</div>
          <div className="text-[10px] text-ink-mute uppercase tracking-wide">Total</div>
        </div>
        <div className="bg-yellow-50 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-yellow-700">{pendingCount}</div>
          <div className="text-[10px] text-ink-mute uppercase tracking-wide">Pending</div>
        </div>
        <div className="bg-green-50 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-green-700">{selectedCount}</div>
          <div className="text-[10px] text-ink-mute uppercase tracking-wide">Selected</div>
        </div>
        <div className="bg-blue-50 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-blue-700">{waitlistedCount}</div>
          <div className="text-[10px] text-ink-mute uppercase tracking-wide">Waitlisted</div>
        </div>
        <div className="bg-green-50 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-green-700">{acceptedCount}</div>
          <div className="text-[10px] text-ink-mute uppercase tracking-wide">Accepted</div>
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-3 mb-5">
        <button
          onClick={handleRunLottery}
          disabled={running || pendingCount === 0 || !windowClosed}
          className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {running ? "Running..." : "Run Lottery"}
        </button>
        <button
          onClick={handleAdvanceWaitlist}
          disabled={advancing || (selectedCount === 0 && waitlistedCount === 0)}
          className="px-4 py-2 border border-gray-300 text-sm rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {advancing ? "Processing..." : "Advance Waitlist"}
        </button>
        {!windowClosed && (
          <span className="text-xs text-amber-700">
            Application window still open until{" "}
            {new Date(permitType.application_closes_at!).toLocaleDateString("en-US", {
              month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
            })}
          </span>
        )}
        {windowClosed && pendingCount === 0 && lotteryAlreadyRun && (
          <span className="text-xs text-ink-mute">
            Lottery ran {new Date(permitType.lottery_run_at!).toLocaleDateString("en-US", {
              month: "short", day: "numeric", year: "numeric",
            })}
          </span>
        )}
      </div>

      {message && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-2 text-sm text-green-700 mb-4">
          {message}
        </div>
      )}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2 text-sm text-red-700 mb-4">
          {error}
        </div>
      )}

      {/* Applications table */}
      {loading ? (
        <div className="text-center text-ink-mute text-sm py-8">Loading applications...</div>
      ) : applications.length === 0 ? (
        <div className="text-center text-ink-mute text-sm py-8">No applications yet.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-3 py-2 font-medium text-ink-mute text-xs">Name</th>
                <th className="px-3 py-2 font-medium text-ink-mute text-xs">Email</th>
                <th className="px-3 py-2 font-medium text-ink-mute text-xs">Class</th>
                <th className="px-3 py-2 font-medium text-ink-mute text-xs">Plate</th>
                <th className="px-3 py-2 font-medium text-ink-mute text-xs">Status</th>
                <th className="px-3 py-2 font-medium text-ink-mute text-xs">Rank / Position</th>
                <th className="px-3 py-2 font-medium text-ink-mute text-xs">Applied</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {applications.map((app) => (
                <tr key={app.id} className="hover:bg-bone/30">
                  <td className="px-3 py-2 font-medium">{app.student_name}</td>
                  <td className="px-3 py-2 text-ink-mute text-xs">{app.student_email}</td>
                  <td className="px-3 py-2">{app.class_year}</td>
                  <td className="px-3 py-2 font-mono text-xs">{app.plate}</td>
                  <td className="px-3 py-2">
                    <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${STATUS_COLORS[app.status] || "bg-gray-100"}`}>
                      {app.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-ink-mute">
                    {app.lottery_rank ? `#${app.lottery_rank}` : ""}
                    {app.waitlist_position ? `WL #${app.waitlist_position}` : ""}
                    {app.offer_expires_at && app.status === "selected" && (
                      <span className="ml-1 text-amber-700">
                        (exp {new Date(app.offer_expires_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })})
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-ink-mute">
                    {new Date(app.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function PermitTypes() {
  const [types, setTypes] = useState<PermitTypeRow[]>([]);
  const [editing, setEditing] = useState<PermitTypeRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [lotteryPanel, setLotteryPanel] = useState<PermitTypeRow | null>(null);

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
        <button onClick={() => { setCreating(true); setEditing(null); setLotteryPanel(null); }}
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

      {lotteryPanel && (
        <LotteryPanel
          permitType={lotteryPanel}
          onDone={() => { setLotteryPanel(null); load(); }}
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
                    <button onClick={() => { setEditing(pt); setCreating(false); setLotteryPanel(null); }}
                      className="text-brass-deep hover:text-brass text-xs">Edit</button>
                    {pt.requires_lottery && pt.is_active && (
                      <button onClick={() => { setLotteryPanel(pt); setEditing(null); setCreating(false); }}
                        className="text-purple-600 hover:text-purple-800 text-xs">Lottery</button>
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
