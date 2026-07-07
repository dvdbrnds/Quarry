import { useCallback, useEffect, useRef, useState } from "react";
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
  is_active: boolean;
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

interface Application {
  id: string;
  student_email: string;
  student_name: string;
  class_year: number;
  plate: string;
  phone: string | null;
  lot_preferences: string[];
  assigned_lot: string | null;
  status: string;
  lottery_rank: number | null;
  waitlist_position: number | null;
  offer_expires_at: string | null;
  created_at: string;
  updated_at: string;
}

interface SimulationResult {
  selected: SimulatedApp[];
  waitlisted: SimulatedApp[];
  total_applicants: number;
  spots_available: number;
  strategy_used: string;
}

interface SimulatedApp {
  id: string;
  student_name: string;
  student_email: string;
  class_year: number;
  plate: string;
  lot_preferences: string[];
  assigned_lot: string | null;
  rank: number;
}

interface ActivityEvent {
  id: string;
  student_name: string;
  old_status: string;
  new_status: string;
  timestamp: string;
}

const STRATEGY_LABELS: Record<string, string> = {
  seniority_weighted: "Seniority Weighted",
  pure_random: "Pure Random",
  class_priority: "Class Priority",
  seniority_timestamp: "Seniority + Timestamp",
};

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  selected: "bg-green-100 text-green-800",
  waitlisted: "bg-blue-100 text-blue-700",
  accepted: "bg-green-50 text-green-700",
  expired: "bg-gray-100 text-gray-500",
  declined: "bg-gray-100 text-gray-500",
};

type View = "overview" | "manage" | "simulate" | "live";

export default function LotteryManager() {
  const [types, setTypes] = useState<PermitTypeRow[]>([]);
  const [selected, setSelected] = useState<PermitTypeRow | null>(null);
  const [view, setView] = useState<View>("overview");

  const load = useCallback(async () => {
    const res = await fetch("/api/permit-types?all=true", { headers: await authHeaders() });
    if (res.ok) {
      const all: PermitTypeRow[] = await res.json();
      setTypes(all.filter((t) => t.is_active));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function openManage(pt: PermitTypeRow) {
    setSelected(pt);
    setView("manage");
  }

  function goBack() {
    if (view === "simulate" || view === "live") {
      setView("manage");
    } else {
      setSelected(null);
      setView("overview");
      load();
    }
  }

  if (view === "overview" || !selected) {
    return <OverviewGrid types={types} onSelect={openManage} onReload={load} />;
  }

  if (view === "simulate") {
    return <SimulationView permitType={selected} onBack={goBack} />;
  }

  if (view === "live") {
    return <LiveDashboard permitType={selected} onBack={goBack} />;
  }

  return (
    <ManageView
      permitType={selected}
      onBack={goBack}
      onSimulate={() => setView("simulate")}
      onGoLive={() => setView("live")}
    />
  );
}

function OverviewGrid({
  types,
  onSelect,
  onReload,
}: {
  types: PermitTypeRow[];
  onSelect: (pt: PermitTypeRow) => void;
  onReload: () => void;
}) {
  const now = new Date();
  const [toggling, setToggling] = useState<string | null>(null);

  const lotteryTypes = types.filter((t) => t.requires_lottery);
  const otherTypes = types.filter((t) => !t.requires_lottery);

  function getStatus(pt: PermitTypeRow) {
    if (pt.lottery_run_at) return { label: "Completed", color: "bg-green-100 text-green-700" };
    if (pt.application_closes_at && new Date(pt.application_closes_at) < now) return { label: "Ready to run", color: "bg-amber-100 text-amber-700" };
    if (pt.application_opens_at && new Date(pt.application_opens_at) < now) return { label: "Accepting applications", color: "bg-blue-100 text-blue-700" };
    if (pt.application_opens_at) return { label: "Scheduled", color: "bg-gray-100 text-gray-600" };
    return { label: "Not configured", color: "bg-gray-100 text-gray-500" };
  }

  async function enableLottery(pt: PermitTypeRow) {
    setToggling(pt.id);
    try {
      await fetch(`/api/permit-types/${pt.id}`, {
        method: "PUT",
        headers: await authHeaders(),
        body: JSON.stringify({ requires_lottery: true, lottery_strategy: "seniority_timestamp" }),
      });
      onReload();
    } finally {
      setToggling(null);
    }
  }

  async function disableLottery(pt: PermitTypeRow) {
    if (!confirm(`Disable lottery for "${pt.label}"? Existing applications will be preserved.`)) return;
    setToggling(pt.id);
    try {
      await fetch(`/api/permit-types/${pt.id}`, {
        method: "PUT",
        headers: await authHeaders(),
        body: JSON.stringify({ requires_lottery: false }),
      });
      onReload();
    } finally {
      setToggling(null);
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-navy">Lottery Management</h2>
        <p className="text-sm text-ink-mute mt-1">Manage lotteries, run simulations, and monitor live draws.</p>
      </div>

      {/* Lottery-enabled permit types */}
      {lotteryTypes.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
          {lotteryTypes.map((pt) => {
            const status = getStatus(pt);
            return (
              <div
                key={pt.id}
                className="bg-white rounded-xl shadow p-5 hover:shadow-md transition-all"
              >
                <div className="flex items-start justify-between mb-2">
                  <h3 className="font-semibold text-navy">{pt.label}</h3>
                  <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${status.color}`}>
                    {status.label}
                  </span>
                </div>
                <div className="text-xs text-ink-mute space-y-1 mb-4">
                  <div>Strategy: {STRATEGY_LABELS[pt.lottery_strategy] || pt.lottery_strategy}</div>
                  <div>Capacity: {pt.max_capacity} &middot; {pt.remaining} remaining</div>
                  <div>Lots: {pt.lot_assignments.join(", ") || "None"}</div>
                  {pt.application_closes_at && (
                    <div>
                      Closes: {new Date(pt.application_closes_at).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
                    </div>
                  )}
                  {pt.lottery_run_at && (
                    <div className="text-green-700">
                      Ran: {new Date(pt.lottery_run_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => onSelect(pt)}
                    className="flex-1 py-2 bg-brass text-navy-deep font-medium rounded-lg text-xs hover:bg-brass-deep transition-colors"
                  >
                    Manage
                  </button>
                  <button
                    onClick={() => disableLottery(pt)}
                    disabled={toggling === pt.id}
                    className="px-3 py-2 text-xs text-ink-mute hover:text-signal-red transition-colors"
                  >
                    Disable
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {lotteryTypes.length === 0 && (
        <div className="bg-white rounded-xl shadow p-8 text-center mb-8">
          <p className="text-ink-mute">No permit types have lottery enabled yet.</p>
          <p className="text-xs text-ink-mute mt-1">Enable lottery on a permit type below to get started.</p>
        </div>
      )}

      {/* Other permit types that can be lottery-enabled */}
      {otherTypes.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-ink-mute uppercase tracking-wide mb-3">
            Available Permit Types
          </h3>
          <div className="bg-white rounded-xl shadow overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left">
                <tr>
                  <th className="px-4 py-2 font-medium text-ink-mute text-xs">Permit Type</th>
                  <th className="px-4 py-2 font-medium text-ink-mute text-xs">Capacity</th>
                  <th className="px-4 py-2 font-medium text-ink-mute text-xs">Price</th>
                  <th className="px-4 py-2 font-medium text-ink-mute text-xs">Lots</th>
                  <th className="px-4 py-2 font-medium text-ink-mute text-xs w-40"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {otherTypes.map((pt) => (
                  <tr key={pt.id} className="hover:bg-bone/30">
                    <td className="px-4 py-3">
                      <div className="font-medium">{pt.label}</div>
                      <div className="text-xs text-ink-mute">{pt.code}</div>
                    </td>
                    <td className="px-4 py-3 text-xs">{pt.max_capacity}</td>
                    <td className="px-4 py-3 text-xs">{Number(pt.price) === 0 ? "Free" : `$${Number(pt.price).toFixed(0)}`}</td>
                    <td className="px-4 py-3 text-xs text-ink-mute">{pt.lot_assignments.join(", ") || "—"}</td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => enableLottery(pt)}
                        disabled={toggling === pt.id}
                        className="px-3 py-1.5 border border-purple-300 text-purple-700 font-medium rounded-lg text-xs hover:bg-purple-50 transition-colors disabled:opacity-50"
                      >
                        {toggling === pt.id ? "Enabling..." : "Enable Lottery"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function ManageView({
  permitType,
  onBack,
  onSimulate,
  onGoLive,
}: {
  permitType: PermitTypeRow;
  onBack: () => void;
  onSimulate: () => void;
  onGoLive: () => void;
}) {
  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [advancing, setAdvancing] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [showConfig, setShowConfig] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [strategy, setStrategy] = useState(permitType.lottery_strategy);
  const [minClassYear, setMinClassYear] = useState(permitType.min_class_year?.toString() ?? "");
  const [offerDays, setOfferDays] = useState(permitType.offer_window_days);
  const [opensAt, setOpensAt] = useState(permitType.application_opens_at?.slice(0, 16) ?? "");
  const [closesAt, setClosesAt] = useState(permitType.application_closes_at?.slice(0, 16) ?? "");

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
  const expiredCount = applications.filter((a) => a.status === "expired").length;

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

  async function saveConfig() {
    setConfigSaving(true);
    try {
      await fetch(`/api/permit-types/${permitType.id}`, {
        method: "PUT",
        headers: await authHeaders(),
        body: JSON.stringify({
          lottery_strategy: strategy,
          min_class_year: minClassYear ? parseInt(minClassYear) : null,
          offer_window_days: offerDays,
          application_opens_at: opensAt ? new Date(opensAt).toISOString() : null,
          application_closes_at: closesAt ? new Date(closesAt).toISOString() : null,
        }),
      });
      setMessage("Configuration saved.");
    } finally {
      setConfigSaving(false);
    }
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="text-ink-mute hover:text-ink text-sm">&larr; Back</button>
          <div>
            <h2 className="text-2xl font-bold text-navy">{permitType.label}</h2>
            <p className="text-xs text-ink-mute">
              {STRATEGY_LABELS[permitType.lottery_strategy] || permitType.lottery_strategy}
              {permitType.min_class_year && ` · Min class year: ${permitType.min_class_year}`}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowConfig(!showConfig)}
            className={`px-4 py-2 border text-sm font-medium rounded-lg transition-colors ${showConfig ? "border-navy bg-navy/5 text-navy" : "border-gray-300 text-ink-mute hover:bg-gray-50"}`}
          >
            Configure
          </button>
          <button
            onClick={onSimulate}
            disabled={applications.length === 0}
            className="px-4 py-2 border border-purple-300 text-purple-700 font-medium rounded-lg text-sm hover:bg-purple-50 transition-colors disabled:opacity-40"
          >
            Simulate
          </button>
          <button
            onClick={onGoLive}
            disabled={!lotteryAlreadyRun}
            className="px-4 py-2 border border-green-300 text-green-700 font-medium rounded-lg text-sm hover:bg-green-50 transition-colors disabled:opacity-40"
          >
            Go Live
          </button>
        </div>
      </div>

      {/* Configuration panel */}
      {showConfig && (
        <div className="bg-white rounded-xl shadow p-5 mb-5">
          <h3 className="text-sm font-semibold text-navy mb-3">Lottery Configuration</h3>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Strategy</label>
              <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none">
                <option value="seniority_timestamp">Seniority + Timestamp</option>
                <option value="seniority_weighted">Seniority Weighted</option>
                <option value="pure_random">Pure Random</option>
                <option value="class_priority">Class Priority</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Min Class Year</label>
              <input type="number" value={minClassYear} onChange={(e) => setMinClassYear(e.target.value)}
                placeholder="None"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
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
          </div>
          <div className="flex justify-end mt-3">
            <button onClick={saveConfig} disabled={configSaving}
              className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors disabled:opacity-50">
              {configSaving ? "Saving..." : "Save Configuration"}
            </button>
          </div>
        </div>
      )}

      {/* Stats bar */}
      <div className="grid grid-cols-6 gap-3 mb-5">
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
        <div className="bg-gray-50 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-gray-500">{expiredCount}</div>
          <div className="text-[10px] text-ink-mute uppercase tracking-wide">Expired</div>
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
      <div className="bg-white rounded-xl shadow overflow-hidden">
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
                  <th className="px-3 py-2 font-medium text-ink-mute text-xs">Lot Prefs</th>
                  <th className="px-3 py-2 font-medium text-ink-mute text-xs">Assigned</th>
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
                      {app.lot_preferences?.length > 0 ? app.lot_preferences.join(" > ") : "—"}
                    </td>
                    <td className="px-3 py-2 text-xs font-medium">
                      {app.assigned_lot ? (
                        <span className="text-green-700">{app.assigned_lot}</span>
                      ) : "—"}
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
    </div>
  );
}

function SimulationView({
  permitType,
  onBack,
}: {
  permitType: PermitTypeRow;
  onBack: () => void;
}) {
  const [strategy, setStrategy] = useState(permitType.lottery_strategy);
  const [capacityOverride, setCapacityOverride] = useState<string>("");
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [previewIdx, setPreviewIdx] = useState<number>(0);

  async function runSimulation() {
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const body: Record<string, unknown> = { strategy };
      if (capacityOverride) body.capacity_override = parseInt(capacityOverride);
      const res = await fetch(`/api/permit-types/${permitType.id}/simulate-lottery`, {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Simulation failed");
      }
      setResult(await res.json());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { runSimulation(); }, []);

  const previewStudent = result?.selected[previewIdx] || null;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="text-ink-mute hover:text-ink text-sm">&larr; Back</button>
          <div>
            <h2 className="text-2xl font-bold text-navy">Simulation: {permitType.label}</h2>
            <p className="text-xs text-ink-mute">Dry run — no data is saved</p>
          </div>
        </div>
        <span className="text-[10px] font-medium px-3 py-1 rounded-full bg-purple-100 text-purple-700 uppercase tracking-wide">
          Simulation Mode
        </span>
      </div>

      {/* Controls */}
      <div className="bg-white rounded-xl shadow p-4 mb-5 flex items-end gap-4">
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Strategy</label>
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none">
            <option value="seniority_timestamp">Seniority + Timestamp</option>
            <option value="seniority_weighted">Seniority Weighted</option>
            <option value="pure_random">Pure Random</option>
            <option value="class_priority">Class Priority</option>
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Capacity Override</label>
          <input
            type="number"
            value={capacityOverride}
            onChange={(e) => setCapacityOverride(e.target.value)}
            placeholder={`${permitType.max_capacity} (default)`}
            className="w-36 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
          />
        </div>
        <button
          onClick={runSimulation}
          disabled={loading}
          className="px-4 py-2 bg-purple-600 text-white font-medium rounded-lg text-sm hover:bg-purple-700 transition-colors disabled:opacity-50"
        >
          {loading ? "Simulating..." : "Re-run Simulation"}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2 text-sm text-red-700 mb-4">
          {error}
        </div>
      )}

      {result && (
        <div className="grid grid-cols-3 gap-5">
          {/* Results table */}
          <div className="col-span-2 bg-white rounded-xl shadow overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
              <h3 className="font-semibold text-navy text-sm">Projected Results</h3>
              <div className="text-xs text-ink-mute">
                {result.selected.length} selected / {result.waitlisted.length} waitlisted / {result.spots_available} spots
              </div>
            </div>
            <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-left sticky top-0">
                  <tr>
                    <th className="px-3 py-2 font-medium text-ink-mute text-xs">#</th>
                    <th className="px-3 py-2 font-medium text-ink-mute text-xs">Name</th>
                    <th className="px-3 py-2 font-medium text-ink-mute text-xs">Class</th>
                    <th className="px-3 py-2 font-medium text-ink-mute text-xs">Outcome</th>
                    <th className="px-3 py-2 font-medium text-ink-mute text-xs">Lot</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {result.selected.map((app, i) => (
                    <tr
                      key={app.id}
                      className={`hover:bg-bone/30 cursor-pointer ${previewIdx === i ? "bg-brass/10" : ""}`}
                      onClick={() => setPreviewIdx(i)}
                    >
                      <td className="px-3 py-2 text-xs text-ink-mute">{app.rank}</td>
                      <td className="px-3 py-2 font-medium">{app.student_name}</td>
                      <td className="px-3 py-2">{app.class_year}</td>
                      <td className="px-3 py-2">
                        <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-green-100 text-green-800">
                          selected
                        </span>
                      </td>
                      <td className="px-3 py-2 text-xs font-medium text-green-700">{app.assigned_lot || "—"}</td>
                    </tr>
                  ))}
                  {result.waitlisted.map((app) => (
                    <tr key={app.id} className="hover:bg-bone/30 opacity-60">
                      <td className="px-3 py-2 text-xs text-ink-mute">WL {app.rank}</td>
                      <td className="px-3 py-2 font-medium">{app.student_name}</td>
                      <td className="px-3 py-2">{app.class_year}</td>
                      <td className="px-3 py-2">
                        <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                          waitlisted
                        </span>
                      </td>
                      <td className="px-3 py-2 text-xs text-ink-mute">—</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Student preview */}
          <div className="bg-white rounded-xl shadow p-5">
            <h3 className="font-semibold text-navy text-sm mb-3">Student Preview</h3>
            <p className="text-[10px] text-ink-mute mb-4 uppercase tracking-wide">What the selected student would see</p>
            {previewStudent ? (
              <div className="space-y-4">
                <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                  <div className="text-sm font-medium text-green-800 mb-2">
                    Congratulations, {previewStudent.student_name.split(" ")[0]}!
                  </div>
                  <p className="text-xs text-green-700">
                    You've been selected in the lottery for <strong>{permitType.label}</strong>.
                  </p>
                  {previewStudent.assigned_lot && (
                    <p className="text-xs text-green-700 mt-1">
                      Your assigned lot: <strong>{previewStudent.assigned_lot}</strong>
                    </p>
                  )}
                  <p className="text-xs text-green-700 mt-2">
                    You have {permitType.offer_window_days} days to accept and pay ${Number(permitType.price).toFixed(0)}.
                  </p>
                </div>
                <div className="text-xs space-y-1 text-ink-mute">
                  <div><strong>Rank:</strong> #{previewStudent.rank} of {result.selected.length}</div>
                  <div><strong>Email:</strong> {previewStudent.student_email}</div>
                  <div><strong>Class:</strong> {previewStudent.class_year}</div>
                  <div><strong>Plate:</strong> {previewStudent.plate}</div>
                  <div><strong>Lot Preferences:</strong> {previewStudent.lot_preferences.length > 0 ? previewStudent.lot_preferences.join(" > ") : "None submitted"}</div>
                </div>
              </div>
            ) : (
              <p className="text-xs text-ink-mute">Click a selected student to preview their experience.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function LiveDashboard({
  permitType,
  onBack,
}: {
  permitType: PermitTypeRow;
  onBack: () => void;
}) {
  const [applications, setApplications] = useState<Application[]>([]);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [isLive, setIsLive] = useState(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());

  const fetchData = useCallback(async () => {
    try {
      const [appsRes, actRes] = await Promise.all([
        fetch(`/api/permit-types/${permitType.id}/applications`, { headers: await authHeaders() }),
        fetch(`/api/permit-types/${permitType.id}/lottery-activity`, { headers: await authHeaders() }),
      ]);
      if (appsRes.ok) setApplications(await appsRes.json());
      if (actRes.ok) setActivity(await actRes.json());
      setLastUpdate(new Date());
    } catch { /* silent */ }
  }, [permitType.id]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (isLive) {
      intervalRef.current = setInterval(fetchData, 4000);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isLive, fetchData]);

  const pendingCount = applications.filter((a) => a.status === "pending").length;
  const selectedCount = applications.filter((a) => a.status === "selected").length;
  const waitlistedCount = applications.filter((a) => a.status === "waitlisted").length;
  const acceptedCount = applications.filter((a) => a.status === "accepted").length;
  const expiredCount = applications.filter((a) => a.status === "expired").length;
  const declinedCount = applications.filter((a) => a.status === "declined").length;
  const totalOffered = selectedCount + acceptedCount + expiredCount + declinedCount;
  const acceptRate = totalOffered > 0 ? Math.round((acceptedCount / totalOffered) * 100) : 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="text-ink-mute hover:text-ink text-sm">&larr; Back</button>
          <div>
            <h2 className="text-2xl font-bold text-navy">Live: {permitType.label}</h2>
            <p className="text-xs text-ink-mute">
              Last updated: {lastUpdate.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" })}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setIsLive(!isLive)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              isLive ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-600"
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${isLive ? "bg-green-500 animate-pulse" : "bg-gray-400"}`} />
            {isLive ? "Live" : "Paused"}
          </button>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-6 gap-3 mb-6">
        <div className="bg-yellow-50 rounded-lg p-4 text-center">
          <div className="text-3xl font-bold text-yellow-700 transition-all">{pendingCount}</div>
          <div className="text-[10px] text-ink-mute uppercase tracking-wide mt-1">Pending</div>
        </div>
        <div className="bg-green-50 rounded-lg p-4 text-center">
          <div className="text-3xl font-bold text-green-700 transition-all">{selectedCount}</div>
          <div className="text-[10px] text-ink-mute uppercase tracking-wide mt-1">Awaiting Response</div>
        </div>
        <div className="bg-green-100 rounded-lg p-4 text-center">
          <div className="text-3xl font-bold text-green-800 transition-all">{acceptedCount}</div>
          <div className="text-[10px] text-ink-mute uppercase tracking-wide mt-1">Accepted</div>
        </div>
        <div className="bg-blue-50 rounded-lg p-4 text-center">
          <div className="text-3xl font-bold text-blue-700 transition-all">{waitlistedCount}</div>
          <div className="text-[10px] text-ink-mute uppercase tracking-wide mt-1">Waitlisted</div>
        </div>
        <div className="bg-gray-50 rounded-lg p-4 text-center">
          <div className="text-3xl font-bold text-gray-500 transition-all">{expiredCount}</div>
          <div className="text-[10px] text-ink-mute uppercase tracking-wide mt-1">Expired</div>
        </div>
        <div className="bg-gray-50 rounded-lg p-4 text-center">
          <div className="text-3xl font-bold text-gray-500 transition-all">{declinedCount}</div>
          <div className="text-[10px] text-ink-mute uppercase tracking-wide mt-1">Declined</div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-5">
        {/* Progress section */}
        <div className="col-span-2 space-y-5">
          {/* Acceptance progress bar */}
          <div className="bg-white rounded-xl shadow p-5">
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-semibold text-navy text-sm">Acceptance Progress</h3>
              <span className="text-xs text-ink-mute">{acceptRate}% acceptance rate</span>
            </div>
            <div className="w-full bg-gray-100 rounded-full h-4 overflow-hidden">
              <div className="h-full flex">
                <div
                  className="bg-green-500 transition-all duration-700"
                  style={{ width: `${totalOffered > 0 ? (acceptedCount / totalOffered) * 100 : 0}%` }}
                />
                <div
                  className="bg-yellow-400 transition-all duration-700"
                  style={{ width: `${totalOffered > 0 ? (selectedCount / totalOffered) * 100 : 0}%` }}
                />
                <div
                  className="bg-gray-300 transition-all duration-700"
                  style={{ width: `${totalOffered > 0 ? ((expiredCount + declinedCount) / totalOffered) * 100 : 0}%` }}
                />
              </div>
            </div>
            <div className="flex gap-4 mt-2 text-[10px] text-ink-mute">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500" /> Accepted ({acceptedCount})</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-yellow-400" /> Awaiting ({selectedCount})</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gray-300" /> Lost ({expiredCount + declinedCount})</span>
            </div>
          </div>

          {/* Capacity fill */}
          <div className="bg-white rounded-xl shadow p-5">
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-semibold text-navy text-sm">Capacity Fill</h3>
              <span className="text-xs text-ink-mute">
                {permitType.max_capacity - permitType.remaining} / {permitType.max_capacity} permits issued
              </span>
            </div>
            <div className="w-full bg-gray-100 rounded-full h-3 overflow-hidden">
              <div
                className="bg-navy h-full transition-all duration-700"
                style={{ width: `${((permitType.max_capacity - permitType.remaining) / permitType.max_capacity) * 100}%` }}
              />
            </div>
          </div>
        </div>

        {/* Activity feed */}
        <div className="bg-white rounded-xl shadow p-5">
          <h3 className="font-semibold text-navy text-sm mb-3">Recent Activity</h3>
          {activity.length === 0 ? (
            <p className="text-xs text-ink-mute">No recent activity.</p>
          ) : (
            <div className="space-y-2 max-h-[360px] overflow-y-auto">
              {activity.map((evt) => (
                <div key={evt.id} className="flex items-start gap-2 text-xs border-b border-gray-50 pb-2">
                  <span className={`w-2 h-2 rounded-full mt-1 flex-shrink-0 ${
                    evt.new_status === "accepted" ? "bg-green-500" :
                    evt.new_status === "selected" ? "bg-yellow-500" :
                    evt.new_status === "expired" ? "bg-gray-400" :
                    evt.new_status === "waitlisted" ? "bg-blue-500" :
                    "bg-gray-300"
                  }`} />
                  <div className="flex-1 min-w-0">
                    <span className="font-medium">{evt.student_name}</span>{" "}
                    <span className="text-ink-mute">
                      {evt.old_status} &rarr; {evt.new_status}
                    </span>
                    <div className="text-[10px] text-ink-mute mt-0.5">
                      {new Date(evt.timestamp).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
