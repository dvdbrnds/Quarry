import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";
import {
  Card, Button, Input, InputNumber, Select, Checkbox, Table, Form, DatePicker, Tag, Space, App, Spin, Empty,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

interface EnforcementSettingsData {
  payment_due_days: number; appeal_window_days: number;
  academic_year_start_month: number; academic_year_start_day: number;
  escalation_threshold: number; permit_fine_reduction: string;
  unpaid_blocks_registration: boolean; towing_enabled: boolean;
  towing_violation_codes: string[]; snow_emergency_active: boolean;
  updated_at: string; updated_by: string;
}

interface AcademicSeason {
  id: string; code: string; label: string; start_date: string; end_date: string; is_default: boolean;
}

export default function EnforcementSettings() {
  const { modal, message } = App.useApp();
  const [settings, setSettings] = useState<EnforcementSettingsData | null>(null);
  const [seasons, setSeasons] = useState<AcademicSeason[]>([]);
  const [saving, setSaving] = useState(false);
  const [newSeason, setNewSeason] = useState(false);
  const [seasonForm] = Form.useForm();
  const [editingSeason, setEditingSeason] = useState<AcademicSeason | null>(null);
  const [editForm] = Form.useForm();

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
    try {
      await fetch("/api/settings/enforcement", { method: "PUT", headers: await authHeaders(), body: JSON.stringify(settings) });
      message.success("Settings saved");
    } catch { message.error("Failed to save"); }
    finally { setSaving(false); }
  }

  async function handleAddSeason(values: any) {
    await fetch("/api/academic-calendar", { method: "POST", headers: await authHeaders(), body: JSON.stringify({
      ...values, start_date: values.start_date.format("YYYY-MM-DD"), end_date: values.end_date.format("YYYY-MM-DD"),
    })});
    message.success("Season added");
    setNewSeason(false); seasonForm.resetFields(); load();
  }

  function handleDeleteSeason(id: string) {
    modal.confirm({
      title: "Delete this season?", okText: "Delete", okButtonProps: { danger: true },
      onOk: async () => { await fetch(`/api/academic-calendar/${id}`, { method: "DELETE", headers: await authHeaders() }); message.success("Season deleted"); load(); },
    });
  }

  function startEditSeason(s: AcademicSeason) {
    setEditingSeason(s);
    editForm.setFieldsValue({ code: s.code, label: s.label, start_date: dayjs(s.start_date), end_date: dayjs(s.end_date), is_default: s.is_default });
  }

  async function handleUpdateSeason(values: any) {
    if (!editingSeason) return;
    await fetch(`/api/academic-calendar/${editingSeason.id}`, { method: "PUT", headers: await authHeaders(), body: JSON.stringify({
      ...values, start_date: values.start_date.format("YYYY-MM-DD"), end_date: values.end_date.format("YYYY-MM-DD"),
    })});
    message.success("Season updated");
    setEditingSeason(null); load();
  }

  if (!settings) return <Spin className="py-8 flex justify-center" />;

  const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

  const seasonColumns: ColumnsType<AcademicSeason> = [
    { title: "Code", dataIndex: "code", key: "code", render: v => <span className="font-mono text-xs">{v}</span> },
    { title: "Label", dataIndex: "label", key: "label" },
    { title: "Start", dataIndex: "start_date", key: "start" },
    { title: "End", dataIndex: "end_date", key: "end" },
    { title: "Default", dataIndex: "is_default", key: "default", render: v => v ? <Tag color="blue">Yes</Tag> : null },
    {
      title: "Actions", key: "actions", width: 120,
      render: (_, s) => (
        <Space>
          <Button type="link" size="small" onClick={() => startEditSeason(s)}>Edit</Button>
          <Button type="link" size="small" danger onClick={() => handleDeleteSeason(s.id)}>Delete</Button>
        </Space>
      ),
    },
  ];

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

      <div>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xl font-bold">Academic Calendar</h3>
          <Button type="primary" onClick={() => setNewSeason(true)}>+ Add Season</Button>
        </div>

        {newSeason && (
          <Card className="mb-4" title="New Season">
            <Form form={seasonForm} layout="vertical" onFinish={handleAddSeason}>
              <div className="grid grid-cols-2 gap-x-4">
                <Form.Item name="code" label="Code" rules={[{ required: true }]}><Input placeholder="fall_spring" /></Form.Item>
                <Form.Item name="label" label="Label" rules={[{ required: true }]}><Input placeholder="Fall/Spring 2025-2026" /></Form.Item>
                <Form.Item name="start_date" label="Start Date" rules={[{ required: true }]}><DatePicker className="w-full" /></Form.Item>
                <Form.Item name="end_date" label="End Date" rules={[{ required: true }]}><DatePicker className="w-full" /></Form.Item>
              </div>
              <Form.Item name="is_default" valuePropName="checked"><Checkbox>Default fallback season</Checkbox></Form.Item>
              <Space>
                <Button onClick={() => setNewSeason(false)}>Cancel</Button>
                <Button type="primary" htmlType="submit">Add Season</Button>
              </Space>
            </Form>
          </Card>
        )}

        {editingSeason && (
          <Card className="mb-4" title={`Edit Season: ${editingSeason.label}`}>
            <Form form={editForm} layout="vertical" onFinish={handleUpdateSeason}>
              <div className="grid grid-cols-2 gap-x-4">
                <Form.Item name="code" label="Code"><Input /></Form.Item>
                <Form.Item name="label" label="Label"><Input /></Form.Item>
                <Form.Item name="start_date" label="Start Date"><DatePicker className="w-full" /></Form.Item>
                <Form.Item name="end_date" label="End Date"><DatePicker className="w-full" /></Form.Item>
              </div>
              <Form.Item name="is_default" valuePropName="checked"><Checkbox>Default</Checkbox></Form.Item>
              <Space>
                <Button onClick={() => setEditingSeason(null)}>Cancel</Button>
                <Button type="primary" htmlType="submit">Save</Button>
              </Space>
            </Form>
          </Card>
        )}

        <Table dataSource={seasons} columns={seasonColumns} rowKey="id" size="small" pagination={false}
          locale={{ emptyText: <Empty description="No seasons configured" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }} />
      </div>
    </div>
  );
}
