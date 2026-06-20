import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";

interface EnforcementSettingsData {
  payment_due_days: number;
  appeal_window_days: number;
  academic_year_start_month: number;
  academic_year_start_day: number;
  escalation_threshold: number;
  permit_fine_reduction: string;
  unpaid_blocks_registration: boolean;
  towing_enabled: boolean;
  towing_violation_codes: string[];
  snow_emergency_active: boolean;
  updated_at: string;
  updated_by: string;
}

interface AcademicSeason {
  id: string;
  code: string;
  label: string;
  start_date: string;
  end_date: string;
  is_default: boolean;
}

export default function EnforcementSettings() {
  const [settings, setSettings] = useState<EnforcementSettingsData | null>(null);
  const [seasons, setSeasons] = useState<AcademicSeason[]>([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [newSeason, setNewSeason] = useState(false);
  const [seasonForm, setSeasonForm] = useState({ code: "", label: "", start_date: "", end_date: "", is_default: false });

  const load = useCallback(async () => {
    const [settingsRes, seasonsRes] = await Promise.all([
      fetch("/api/settings/enforcement", { headers: await authHeaders() }),
      fetch("/api/academic-calendar", { headers: await authHeaders() }),
    ]);
    if (settingsRes.ok) setSettings(await settingsRes.json());
    if (seasonsRes.ok) setSeasons(await seasonsRes.json());
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleSave() {
    if (!settings) return;
    setSaving(true);
    setSaved(false);
    await fetch("/api/settings/enforcement", {
      method: "PUT",
      headers: await authHeaders(),
      body: JSON.stringify(settings),
    });
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  }

  async function handleAddSeason(e: React.FormEvent) {
    e.preventDefault();
    await fetch("/api/academic-calendar", {
      method: "POST",
      headers: await authHeaders(),
      body: JSON.stringify(seasonForm),
    });
    setNewSeason(false);
    setSeasonForm({ code: "", label: "", start_date: "", end_date: "", is_default: false });
    load();
  }

  async function handleDeleteSeason(id: string) {
    if (!confirm("Delete this season?")) return;
    await fetch(`/api/academic-calendar/${id}`, { method: "DELETE", headers: await authHeaders() });
    load();
  }

  if (!settings) return <div className="text-center text-ink-mute py-8">Loading...</div>;

  return (
    <div className="space-y-8">
      <div>
        <h3 className="text-xl font-bold mb-4">Enforcement Rules</h3>

        <div className="bg-white rounded-xl shadow p-6 space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-6">
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Payment Due (business days)</label>
              <input type="number" value={settings.payment_due_days}
                onChange={(e) => setSettings({ ...settings, payment_due_days: Number(e.target.value) })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Appeal Window (days)</label>
              <input type="number" value={settings.appeal_window_days}
                onChange={(e) => setSettings({ ...settings, appeal_window_days: Number(e.target.value) })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Escalation Threshold (violations)</label>
              <input type="number" value={settings.escalation_threshold}
                onChange={(e) => setSettings({ ...settings, escalation_threshold: Number(e.target.value) })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Permit Fine Reduction ($)</label>
              <input type="number" step="0.01" value={settings.permit_fine_reduction}
                onChange={(e) => setSettings({ ...settings, permit_fine_reduction: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
              <p className="text-xs text-ink-mute mt-1">Ticket reduced to this amount when student buys a permit</p>
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Academic Year Starts</label>
              <div className="flex gap-2">
                <select value={settings.academic_year_start_month}
                  onChange={(e) => setSettings({ ...settings, academic_year_start_month: Number(e.target.value) })}
                  className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none">
                  {["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].map((m, i) => (
                    <option key={i} value={i + 1}>{m}</option>
                  ))}
                </select>
                <input type="number" min={1} max={31} value={settings.academic_year_start_day}
                  onChange={(e) => setSettings({ ...settings, academic_year_start_day: Number(e.target.value) })}
                  className="w-16 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Towing Violation Codes</label>
              <input value={settings.towing_violation_codes.join(", ")}
                onChange={(e) => setSettings({ ...settings, towing_violation_codes: e.target.value.split(",").map(s => s.trim()).filter(Boolean) })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
            </div>
          </div>

          <div className="flex flex-wrap gap-6">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={settings.unpaid_blocks_registration}
                onChange={(e) => setSettings({ ...settings, unpaid_blocks_registration: e.target.checked })}
                className="rounded border-gray-300 text-brass focus:ring-brass" />
              Unpaid fines block registration/transcripts
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={settings.towing_enabled}
                onChange={(e) => setSettings({ ...settings, towing_enabled: e.target.checked })}
                className="rounded border-gray-300 text-brass focus:ring-brass" />
              Towing enabled
            </label>
            <label className="flex items-center gap-2 text-sm font-medium">
              <input type="checkbox" checked={settings.snow_emergency_active}
                onChange={(e) => setSettings({ ...settings, snow_emergency_active: e.target.checked })}
                className="rounded border-gray-300 text-signal-red focus:ring-signal-red" />
              <span className={settings.snow_emergency_active ? "text-signal-red" : ""}>
                Snow Emergency Active
              </span>
            </label>
          </div>

          <div className="flex items-center gap-4 pt-2 border-t border-gray-100">
            <button onClick={handleSave} disabled={saving}
              className="px-6 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors disabled:opacity-50">
              {saving ? "Saving..." : "Save Settings"}
            </button>
            {saved && <span className="text-signal-green text-sm font-medium">Saved</span>}
            <span className="ml-auto text-xs text-ink-mute">
              Last updated by {settings.updated_by} on {new Date(settings.updated_at).toLocaleString()}
            </span>
          </div>
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xl font-bold">Academic Calendar</h3>
          <button onClick={() => setNewSeason(true)}
            className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep">
            + Add Season
          </button>
        </div>

        {newSeason && (
          <form onSubmit={handleAddSeason} className="bg-white rounded-xl shadow p-6 mb-4 grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Code</label>
              <input value={seasonForm.code} onChange={(e) => setSeasonForm({ ...seasonForm, code: e.target.value })}
                required placeholder="fall_spring"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Label</label>
              <input value={seasonForm.label} onChange={(e) => setSeasonForm({ ...seasonForm, label: e.target.value })}
                required placeholder="Fall/Spring 2025-2026"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Start Date</label>
              <input type="date" value={seasonForm.start_date}
                onChange={(e) => setSeasonForm({ ...seasonForm, start_date: e.target.value })} required
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">End Date</label>
              <input type="date" value={seasonForm.end_date}
                onChange={(e) => setSeasonForm({ ...seasonForm, end_date: e.target.value })} required
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
            </div>
            <div className="col-span-2 flex items-center gap-4">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={seasonForm.is_default}
                  onChange={(e) => setSeasonForm({ ...seasonForm, is_default: e.target.checked })}
                  className="rounded border-gray-300 text-brass focus:ring-brass" />
                Default fallback season
              </label>
              <div className="ml-auto flex gap-3">
                <button type="button" onClick={() => setNewSeason(false)}
                  className="px-4 py-2 text-sm text-ink-mute">Cancel</button>
                <button type="submit"
                  className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep">
                  Add Season
                </button>
              </div>
            </div>
          </form>
        )}

        <div className="bg-white rounded-xl shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-navy text-bone text-left">
              <tr>
                <th className="px-4 py-3 font-medium">Code</th>
                <th className="px-4 py-3 font-medium">Label</th>
                <th className="px-4 py-3 font-medium">Start</th>
                <th className="px-4 py-3 font-medium">End</th>
                <th className="px-4 py-3 font-medium">Default</th>
                <th className="px-4 py-3 font-medium w-20">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {seasons.map((s) => (
                <tr key={s.id} className="hover:bg-bone/50">
                  <td className="px-4 py-3 font-mono text-xs">{s.code}</td>
                  <td className="px-4 py-3">{s.label}</td>
                  <td className="px-4 py-3">{s.start_date}</td>
                  <td className="px-4 py-3">{s.end_date}</td>
                  <td className="px-4 py-3">{s.is_default ? "Yes" : ""}</td>
                  <td className="px-4 py-3">
                    <button onClick={() => handleDeleteSeason(s.id)}
                      className="text-signal-red/70 hover:text-signal-red text-xs">Delete</button>
                  </td>
                </tr>
              ))}
              {seasons.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-ink-mute">No seasons configured</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
