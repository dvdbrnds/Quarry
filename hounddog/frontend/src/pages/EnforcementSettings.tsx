import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";
import {
  Card, Button, Input, InputNumber, Select, Checkbox, Space, App, Spin,
} from "antd";
import ViolationTypes from "./ViolationTypes";

interface EnforcementSettingsData {
  payment_due_days: number; appeal_window_days: number;
  academic_year_start_month: number; academic_year_start_day: number;
  escalation_threshold: number; permit_fine_reduction: string;
  unpaid_blocks_registration: boolean; towing_enabled: boolean;
  towing_violation_codes: string[]; snow_emergency_active: boolean;
  updated_at: string; updated_by: string;
}

export default function EnforcementSettings() {
  const { message } = App.useApp();
  const [settings, setSettings] = useState<EnforcementSettingsData | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const res = await fetch("/api/settings/enforcement", { headers: await authHeaders() });
    if (res.ok) setSettings(await res.json());
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleSave() {
    if (!settings) return;
    setSaving(true);
    try {
      await fetch("/api/settings/enforcement", { method: "PUT", headers: await authHeaders(), body: JSON.stringify(settings) });
      message.success("Settings saved");
    } catch { message.error("Failed to save"); }
    finally { setSaving(false); }
  }

  if (!settings) return <Spin className="py-8 flex justify-center" />;

  const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

  return (
    <div className="space-y-8">
      <div>
        <h3 className="text-xl font-bold mb-4">Enforcement Rules</h3>
        <Card>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-6 mb-6">
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Payment Due (business days)</label>
              <InputNumber value={settings.payment_due_days} onChange={v => setSettings({ ...settings, payment_due_days: v ?? 0 })} className="w-full" />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Appeal Window (days)</label>
              <InputNumber value={settings.appeal_window_days} onChange={v => setSettings({ ...settings, appeal_window_days: v ?? 0 })} className="w-full" />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Escalation Threshold</label>
              <InputNumber value={settings.escalation_threshold} onChange={v => setSettings({ ...settings, escalation_threshold: v ?? 0 })} className="w-full" />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Permit Fine Reduction ($)</label>
              <Input type="number" step="0.01" value={settings.permit_fine_reduction} onChange={e => setSettings({ ...settings, permit_fine_reduction: e.target.value })} />
              <p className="text-xs text-ink-mute mt-1">Ticket reduced to this amount when student buys a permit</p>
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Academic Year Starts</label>
              <Space>
                <Select value={settings.academic_year_start_month} onChange={v => setSettings({ ...settings, academic_year_start_month: v })}
                  options={MONTHS.map((m, i) => ({ label: m, value: i + 1 }))} style={{ width: 100 }} />
                <InputNumber value={settings.academic_year_start_day} min={1} max={31}
                  onChange={v => setSettings({ ...settings, academic_year_start_day: v ?? 1 })} style={{ width: 60 }} />
              </Space>
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Towing Violation Codes</label>
              <Input value={settings.towing_violation_codes.join(", ")}
                onChange={e => setSettings({ ...settings, towing_violation_codes: e.target.value.split(",").map(s => s.trim()).filter(Boolean) })} />
            </div>
          </div>
          <Space className="mb-6" wrap>
            <Checkbox checked={settings.unpaid_blocks_registration} onChange={e => setSettings({ ...settings, unpaid_blocks_registration: e.target.checked })}>
              Unpaid fines block registration/transcripts
            </Checkbox>
            <Checkbox checked={settings.towing_enabled} onChange={e => setSettings({ ...settings, towing_enabled: e.target.checked })}>
              Towing enabled
            </Checkbox>
            <Checkbox checked={settings.snow_emergency_active} onChange={e => setSettings({ ...settings, snow_emergency_active: e.target.checked })}>
              <span className={settings.snow_emergency_active ? "text-red-600 font-medium" : ""}>Snow Emergency Active</span>
            </Checkbox>
          </Space>
          <div className="flex items-center gap-4 pt-4 border-t">
            <Button type="primary" onClick={handleSave} loading={saving}>Save Settings</Button>
            <span className="ml-auto text-xs text-ink-mute">
              Last updated by {settings.updated_by} on {new Date(settings.updated_at).toLocaleString()}
            </span>
          </div>
        </Card>
      </div>

      <ViolationTypes />
    </div>
  );
}
