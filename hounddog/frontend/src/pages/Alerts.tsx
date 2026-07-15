import { useCallback, useEffect, useRef, useState } from "react";
import {
  api, ActiveAlert, AlertChannelInfo, AlertSubscriber, AlertSendPreview,
  AlertSendResult, AlertTestSendResult, AlertLogEntry, SignageScreen,
  AlertTemplate, AlertResponseSummary, AlertResponseEntry, CheckInStatus,
  SubscriberGroup, AlertScenario, ScenarioStep, RunningScenario,
  AlertAnalyticsDashboard, AfterActionReport, WeatherAlertConfig, SisSubscriberSyncConfig,
} from "../api";
import {
  Tabs, Table, Button, Input, Select, Checkbox, Tag, Card, Form, Alert, Space, App, Spin, Empty, Modal, Segmented,
  InputNumber, Progress, Statistic,
} from "antd";
import type { ColumnsType } from "antd/es/table";

const CATEGORIES = [
  { id: "emergency", label: "Emergency", color: "red" },
  { id: "weather", label: "Weather", color: "blue" },
  { id: "campus_closing", label: "Campus Closing", color: "gold" },
  { id: "parking", label: "Parking", color: "purple" },
  { id: "general", label: "General", color: "default" },
];

const CHANNEL_LABELS: Record<string, string> = {
  sms: "SMS (Twilio)", email: "Email (SMTP)", voice: "Voice Calls (Twilio)",
  signage: "Digital Signage", banner: "Website Banner", teams: "Microsoft Teams",
  extron: "Extron Scheduling Panels", pa: "PA / Siren (Q-SYS)", zoom_phone: "Zoom Phone Paging",
};

const CHANNEL_DESCRIPTIONS: Record<string, string> = {
  sms: "Twilio SMS to all subscribers", email: "SMTP email to all subscribers",
  voice: "Twilio robocalls with TTS", signage: "Override digital signage screens",
  banner: "Website banner via polling", teams: "Adaptive Card to Teams webhook",
  extron: "Override Extron TouchLink panels", pa: "Siren + TTS via Q-SYS QRC",
  zoom_phone: "Page all Zoom phones via paging group",
};

const CHANNEL_ENV_HINTS: Record<string, string> = {
  sms: "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER",
  email: "SMTP_HOST, SMTP_FROM_ADDRESS", voice: "Same as SMS (Twilio)",
  signage: "Always on", banner: "Always on", teams: "TEAMS_WEBHOOK_URL",
  extron: "EXTRON_ROOM_AGENT_URL", pa: "QSYS_CORE_HOST",
  zoom_phone: "ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ...",
};

const GROUP_TYPE_LABELS: Record<string, string> = {
  building: "Building", department: "Department", role: "Role", custom: "Custom",
};

export default function Alerts() {
  const { modal, message } = App.useApp();
  const [activeAlert, setActiveAlert] = useState<ActiveAlert | null>(null);

  const loadActive = useCallback(async () => {
    try { setActiveAlert(await api.alerts.active()); } catch { setActiveAlert(null); }
  }, []);

  useEffect(() => { loadActive(); const iv = setInterval(loadActive, 15_000); return () => clearInterval(iv); }, [loadActive]);

  function handleClear() {
    if (!activeAlert) return;
    modal.confirm({
      title: "Clear this active alert?",
      content: "This will dismiss signage and banner displays.",
      okText: "Clear Alert", okButtonProps: { danger: true },
      onOk: async () => {
        try { await api.alerts.clear(activeAlert.id); setActiveAlert(null); message.success("Alert cleared"); }
        catch (err: any) { message.error(`Failed: ${err.message}`); }
      },
    });
  }

  return (
    <div>
      {activeAlert && (
        <Alert type={activeAlert.category === "emergency" ? "error" : "warning"} showIcon className="mb-6"
          message={<><span className="font-bold">Active Alert:</span> {activeAlert.subject}</>}
          description={`${activeAlert.category.toUpperCase()} — sent ${new Date(activeAlert.sent_at).toLocaleString()}`}
          action={<Button size="small" danger onClick={handleClear}>Clear Alert</Button>}
        />
      )}

      <h2 className="text-2xl font-bold text-navy mb-4">Alerts</h2>

      <Tabs items={[
        { key: "send", label: "Send Alert", children: <SendSection onSent={loadActive} /> },
        { key: "templates", label: "Templates", children: <TemplatesSection /> },
        { key: "scheduled", label: "Scheduled", children: <ScheduledSection /> },
        { key: "history", label: "History", children: <HistorySection /> },
        { key: "analytics", label: "Analytics", children: <AnalyticsSection /> },
        { key: "subscribers", label: "Subscribers", children: <SubscribersSection /> },
        { key: "groups", label: "Groups", children: <GroupsSection /> },
        { key: "scenarios", label: "Scenarios", children: <ScenariosSection /> },
        { key: "channels", label: "Channels", children: <ChannelsSection /> },
        { key: "weather", label: "Weather", children: <WeatherSection /> },
        { key: "sis-sync", label: "SIS Sync", children: <SisSyncSection /> },
        { key: "test", label: "Test", children: <TestConsole /> },
        { key: "signage", label: "Signage", children: <SignageSection /> },
      ]} />
    </div>
  );
}


// ===========================================================================
// Send Section (with template picker, response options, groups, check-in)
// ===========================================================================

function SendSection({ onSent }: { onSent: () => void }) {
  const { modal, message } = App.useApp();
  const [category, setCategory] = useState("emergency");
  const [subject, setSubject] = useState("");
  const [bodyText, setBodyText] = useState("");
  const [bodySms, setBodySms] = useState("");
  const [sendEmail, setSendEmail] = useState(true);
  const [sendSms, setSendSms] = useState(true);
  const [preview, setPreview] = useState<AlertSendPreview | null>(null);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<AlertSendResult | null>(null);

  const [templates, setTemplates] = useState<AlertTemplate[]>([]);
  const [groups, setGroups] = useState<SubscriberGroup[]>([]);
  const [selectedGroupIds, setSelectedGroupIds] = useState<string[]>([]);
  const [requestResponses, setRequestResponses] = useState(false);
  const [responseOptions, setResponseOptions] = useState("1=Safe, 2=Need Help");
  const [isCheckin, setIsCheckin] = useState(false);
  const [isScheduled, setIsScheduled] = useState(false);
  const [scheduledFor, setScheduledFor] = useState("");
  const [recurrenceRule, setRecurrenceRule] = useState<string | null>(null);

  useEffect(() => {
    api.alerts.templates.list().then(setTemplates);
    api.alerts.groups.list().then(setGroups);
  }, []);

  useEffect(() => { api.alerts.preview(category).then(setPreview); }, [category]);

  const isEmergency = category === "emergency";

  function applyTemplate(templateId: string) {
    const t = templates.find(tpl => tpl.id === templateId);
    if (!t) return;
    setCategory(t.category);
    setSubject(t.subject);
    setBodyText(t.body_text);
    setBodySms(t.body_sms);
  }

  function handleSaveAsTemplate() {
    const name = window.prompt("Template name:");
    if (!name) return;
    api.alerts.templates.create({ name, category, subject, body_text: bodyText, body_sms: bodySms })
      .then((t) => { setTemplates(prev => [...prev, t]); message.success("Template saved"); })
      .catch(() => message.error("Failed to save template"));
  }

  function handleSend() {
    const catInfo = CATEGORIES.find(c => c.id === category);
    modal.confirm({
      title: isEmergency ? "Confirm Emergency Alert" : "Confirm Alert",
      content: (
        <div className="text-sm space-y-1">
          <p><strong>Category:</strong> {catInfo?.label}</p>
          <p><strong>Subject:</strong> {subject}</p>
          {preview && <p><strong>Recipients:</strong> {sendEmail ? `${preview.email_recipient_count} email` : ""}{sendEmail && sendSms ? ", " : ""}{sendSms ? `${preview.sms_recipient_count} SMS` : ""}</p>}
          {selectedGroupIds.length > 0 && <p><strong>Groups:</strong> {selectedGroupIds.map(gid => groups.find(g => g.id === gid)?.name).filter(Boolean).join(", ")}</p>}
          {isCheckin && <p className="text-blue-600 font-medium">Safety Check-In enabled — subscribers will be asked to reply SAFE or HELP.</p>}
          {isEmergency && <p className="text-red-600 font-medium">This will immediately notify all subscribers.</p>}
        </div>
      ),
      okText: isEmergency ? "Send Emergency Alert" : "Send Alert",
      okButtonProps: isEmergency ? { danger: true } : {},
      onOk: async () => {
        setSending(true); setResult(null);
        try {
          const opts = requestResponses || isCheckin
            ? (isCheckin ? ["SAFE", "HELP"] : responseOptions.split(",").map(s => s.trim()).filter(Boolean))
            : undefined;
          const r = await api.alerts.send({
            category, subject, body_text: bodyText, body_sms: bodySms,
            send_email: sendEmail, send_sms: sendSms,
            response_options: opts || null,
            group_ids: selectedGroupIds.length > 0 ? selectedGroupIds : null,
            is_checkin: isCheckin,
            scheduled_for: isScheduled && scheduledFor ? new Date(scheduledFor).toISOString() : null,
            recurrence_rule: isScheduled ? recurrenceRule : null,
          });
          setResult(r); setSubject(""); setBodyText(""); setBodySms(""); onSent();
          if (isScheduled) {
            message.success("Alert scheduled successfully");
          } else {
            message.success(`Alert sent: ${r.emails_sent} emails, ${r.sms_sent} SMS`);
          }
        } catch { message.error("Failed to send alert"); } finally { setSending(false); }
      },
    });
  }

  return (
    <Card>
      <div className="space-y-5">
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-2">Load Template</label>
          <Select placeholder="Select a template..." allowClear style={{ width: 360 }}
            onChange={(v) => { if (v) applyTemplate(v); }}
            options={templates.map(t => ({ label: `${t.name} (${CATEGORIES.find(c => c.id === t.category)?.label ?? t.category})`, value: t.id }))}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-2">Alert Category</label>
          <Segmented value={category} onChange={v => setCategory(v as string)}
            options={CATEGORIES.map(c => ({ label: c.label, value: c.id }))} />
        </div>
        {isEmergency && <Alert type="error" showIcon message="Emergency alerts are sent to all subscribers regardless of category preferences." />}
        <div><label className="block text-xs font-medium text-ink-mute mb-1">Subject</label><Input value={subject} onChange={e => setSubject(e.target.value)} placeholder="Alert subject line..." /></div>
        <div><label className="block text-xs font-medium text-ink-mute mb-1">Email Body</label><Input.TextArea value={bodyText} onChange={e => setBodyText(e.target.value)} rows={5} /></div>
        <div><label className="block text-xs font-medium text-ink-mute mb-1">SMS Body <span className={`ml-2 text-xs ${bodySms.length > 160 ? "text-red-600 font-bold" : "text-ink-mute"}`}>{bodySms.length}/160</span></label><Input.TextArea value={bodySms} onChange={e => setBodySms(e.target.value)} rows={3} /></div>
        {subject && <Button type="link" size="small" onClick={handleSaveAsTemplate}>Save as Template</Button>}

        <Space direction="vertical" className="w-full">
          <Space>
            <Checkbox checked={sendEmail} onChange={e => setSendEmail(e.target.checked)}>Send via Email</Checkbox>
            <Checkbox checked={sendSms} onChange={e => setSendSms(e.target.checked)}>Send via SMS</Checkbox>
          </Space>
          <Space>
            <Checkbox checked={requestResponses} onChange={e => { setRequestResponses(e.target.checked); if (!e.target.checked) setIsCheckin(false); }}>Request SMS Responses</Checkbox>
            {requestResponses && (
              <Checkbox checked={isCheckin} onChange={e => setIsCheckin(e.target.checked)}>Safety Check-In</Checkbox>
            )}
          </Space>
          {requestResponses && !isCheckin && (
            <div>
              <label className="block text-xs text-ink-mute mb-1">Response Options (comma-separated)</label>
              <Input value={responseOptions} onChange={e => setResponseOptions(e.target.value)} placeholder="1=Safe, 2=Need Help" style={{ width: 360 }} />
            </div>
          )}
          {isCheckin && <Alert type="info" showIcon message="Subscribers will be asked to reply SAFE or HELP. Responses will be tracked in real time." />}
        </Space>

        {groups.length > 0 && (
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Target Groups (optional — leave empty for all subscribers)</label>
            <Select mode="multiple" value={selectedGroupIds} onChange={setSelectedGroupIds} placeholder="All subscribers"
              style={{ width: "100%" }} allowClear
              options={groups.map(g => ({ label: `${g.name} (${g.member_count})`, value: g.id }))} />
          </div>
        )}

        <Space direction="vertical" className="w-full">
          <Checkbox checked={isScheduled} onChange={e => { setIsScheduled(e.target.checked); if (!e.target.checked) { setScheduledFor(""); setRecurrenceRule(null); } }}>
            Schedule for later
          </Checkbox>
          {isScheduled && (
            <div className="flex gap-4 items-end">
              <div>
                <label className="block text-xs text-ink-mute mb-1">Send At</label>
                <input type="datetime-local" value={scheduledFor} onChange={e => setScheduledFor(e.target.value)}
                  className="border rounded px-3 py-1.5 text-sm" />
              </div>
              <div>
                <label className="block text-xs text-ink-mute mb-1">Repeat</label>
                <Select value={recurrenceRule} onChange={setRecurrenceRule} allowClear placeholder="No repeat" style={{ width: 160 }}
                  options={[
                    { label: "Daily", value: "daily" },
                    { label: "Weekly", value: "weekly" },
                    { label: "Biweekly", value: "biweekly" },
                    { label: "Monthly", value: "monthly" },
                    { label: "Quarterly", value: "quarterly" },
                    { label: "Yearly", value: "yearly" },
                  ]} />
              </div>
            </div>
          )}
        </Space>

        {preview && (
          <Card size="small" className="bg-bone/30">
            <h4 className="font-medium text-sm mb-2">Recipients Preview</h4>
            <Space className="text-sm text-ink-mute">
              <span>Email: <strong className="text-ink">{preview.email_recipient_count}</strong></span>
              <span>SMS: <strong className="text-ink">{preview.sms_recipient_count}</strong></span>
              <span className="text-xs">({preview.total_subscribers} total)</span>
            </Space>
            {isEmergency && <p className="text-xs text-red-600 font-medium mt-1">Emergency override: all subscribers contacted</p>}
          </Card>
        )}
        {result && (
          <Alert type="success" showIcon message={`Alert sent. ${result.emails_sent} emails, ${result.sms_sent} SMS.`}
            description={result.channel_results && Object.keys(result.channel_results).length > 0 ? (
              <div className="text-xs space-y-1">{Object.entries(result.channel_results).map(([ch, r]) => (
                <div key={ch}><strong className="capitalize">{ch}:</strong> {r.sent} sent{r.failed > 0 ? `, ${r.failed} failed` : ""}{r.error ? ` (${r.error})` : ""}</div>
              ))}</div>
            ) : undefined} />
        )}
        <Button type="primary" danger={isEmergency && !isScheduled} onClick={handleSend} disabled={!subject || (isScheduled && !scheduledFor)} loading={sending}>
          {isScheduled ? "Schedule Alert" : isCheckin ? "Send Check-In" : isEmergency ? "Send Emergency Alert" : "Send Alert"}
        </Button>
      </div>
    </Card>
  );
}


// ===========================================================================
// Templates Section
// ===========================================================================

function TemplatesSection() {
  const { modal, message } = App.useApp();
  const [templates, setTemplates] = useState<AlertTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<AlertTemplate | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => { setLoading(true); try { setTemplates(await api.alerts.templates.list()); } finally { setLoading(false); } }, []);
  useEffect(() => { load(); }, [load]);

  function handleDelete(t: AlertTemplate) {
    modal.confirm({
      title: `Delete template "${t.name}"?`, okText: "Delete", okButtonProps: { danger: true },
      onOk: async () => { await api.alerts.templates.delete(t.id); message.success("Deleted"); load(); },
    });
  }

  const columns: ColumnsType<AlertTemplate> = [
    { title: "Name", dataIndex: "name", key: "name" },
    { title: "Category", dataIndex: "category", key: "cat", render: c => <Tag color={CATEGORIES.find(ci => ci.id === c)?.color}>{CATEGORIES.find(ci => ci.id === c)?.label ?? c}</Tag> },
    { title: "Subject", dataIndex: "subject", key: "subject", ellipsis: true },
    { title: "Default", dataIndex: "is_default", key: "default", render: v => v ? <Tag color="green">Default</Tag> : null },
    { title: "Actions", key: "actions", width: 120, render: (_, t) => <Space><Button type="link" size="small" onClick={() => { setEditing(t); setCreating(false); }}>Edit</Button><Button type="link" size="small" danger onClick={() => handleDelete(t)}>Delete</Button></Space> },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Alert Templates</h3>
        <Button type="primary" onClick={() => { setCreating(true); setEditing(null); }}>+ Add Template</Button>
      </div>
      {(creating || editing) && (
        <TemplateForm initial={editing ?? undefined} onSave={() => { setCreating(false); setEditing(null); load(); }} onCancel={() => { setCreating(false); setEditing(null); }} />
      )}
      <Table dataSource={templates} columns={columns} rowKey="id" loading={loading} size="small" pagination={false} />
    </div>
  );
}

function TemplateForm({ initial, onSave, onCancel }: { initial?: AlertTemplate; onSave: () => void; onCancel: () => void }) {
  const { message } = App.useApp();
  const [name, setName] = useState(initial?.name ?? "");
  const [category, setCategory] = useState(initial?.category ?? "emergency");
  const [subject, setSubject] = useState(initial?.subject ?? "");
  const [bodyText, setBodyText] = useState(initial?.body_text ?? "");
  const [bodySms, setBodySms] = useState(initial?.body_sms ?? "");
  const [isDefault, setIsDefault] = useState(initial?.is_default ?? false);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault(); setSaving(true);
    try {
      if (initial) await api.alerts.templates.update(initial.id, { name, category, subject, body_text: bodyText, body_sms: bodySms, is_default: isDefault });
      else await api.alerts.templates.create({ name, category, subject, body_text: bodyText, body_sms: bodySms, is_default: isDefault });
      message.success(initial ? "Template updated" : "Template created"); onSave();
    } catch { message.error("Failed to save"); } finally { setSaving(false); }
  }

  return (
    <Card title={initial ? "Edit Template" : "Add Template"}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Name</label><Input value={name} onChange={e => setName(e.target.value)} required /></div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Category</label>
            <Select value={category} onChange={setCategory} style={{ width: "100%" }} options={CATEGORIES.map(c => ({ label: c.label, value: c.id }))} />
          </div>
        </div>
        <div><label className="block text-xs font-medium text-ink-mute mb-1">Subject</label><Input value={subject} onChange={e => setSubject(e.target.value)} required /></div>
        <div><label className="block text-xs font-medium text-ink-mute mb-1">Email Body</label><Input.TextArea value={bodyText} onChange={e => setBodyText(e.target.value)} rows={4} /></div>
        <div><label className="block text-xs font-medium text-ink-mute mb-1">SMS Body <span className={`ml-2 text-xs ${bodySms.length > 160 ? "text-red-600 font-bold" : ""}`}>{bodySms.length}/160</span></label><Input.TextArea value={bodySms} onChange={e => setBodySms(e.target.value)} rows={2} /></div>
        <Checkbox checked={isDefault} onChange={e => setIsDefault(e.target.checked)}>Set as default for this category</Checkbox>
        <Space><Button onClick={onCancel}>Cancel</Button><Button type="primary" htmlType="submit" loading={saving}>{initial ? "Update" : "Create Template"}</Button></Space>
      </form>
    </Card>
  );
}


// ===========================================================================
// History Section (with response summary)
// ===========================================================================

function HistorySection() {
  const { message } = App.useApp();
  const [entries, setEntries] = useState<AlertLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [includeTests, setIncludeTests] = useState(false);
  const [responseModal, setResponseModal] = useState<string | null>(null);
  const [responseSummary, setResponseSummary] = useState<AlertResponseSummary | null>(null);
  const [checkinStatus, setCheckinStatus] = useState<CheckInStatus | null>(null);
  const [responseDetails, setResponseDetails] = useState<AlertResponseEntry[]>([]);

  useEffect(() => {
    setLoading(true);
    api.alerts.history({ limit: 100, include_tests: includeTests }).then(setEntries).finally(() => setLoading(false));
  }, [includeTests]);

  async function openResponses(alertId: string, isCheckin: boolean) {
    setResponseModal(alertId);
    try {
      const [summary, details] = await Promise.all([
        api.alerts.responses.summary(alertId),
        api.alerts.responses.detail(alertId),
      ]);
      setResponseSummary(summary);
      setResponseDetails(details);
      if (isCheckin) {
        setCheckinStatus(await api.alerts.responses.checkinStatus(alertId));
      } else {
        setCheckinStatus(null);
      }
    } catch { message.error("Failed to load responses"); }
  }

  async function handleResend(alertId: string) {
    try {
      const r = await api.alerts.responses.resendNonResponders(alertId);
      message.success(`Re-sent to non-responders: ${r.sms_sent} SMS`);
    } catch { message.error("Failed to resend"); }
  }

  const columns: ColumnsType<AlertLogEntry> = [
    { title: "Time", dataIndex: "sent_at", key: "time", width: 160, render: d => new Date(d).toLocaleString() },
    { title: "Category", dataIndex: "category", key: "cat", render: c => <Tag color={CATEGORIES.find(ci => ci.id === c)?.color}>{CATEGORIES.find(ci => ci.id === c)?.label ?? c}</Tag> },
    { title: "Status", dataIndex: "status", key: "status", render: (s, e) => <Space size={4}><Tag color={s === "active" ? "red" : s === "test" ? "blue" : "default"}>{s}</Tag>{e.is_checkin && <Tag color="cyan">Check-In</Tag>}</Space> },
    { title: "Subject", dataIndex: "subject", key: "subject", ellipsis: true },
    { title: "Delivery", key: "delivery", render: (_, e) => `${e.email_count} email, ${e.sms_count} SMS` },
    { title: "Responses", key: "responses", render: (_, e) => e.response_options ? <Button type="link" size="small" onClick={() => openResponses(e.id, e.is_checkin)}>View</Button> : "—" },
    { title: "Sent By", dataIndex: "sent_by", key: "by", ellipsis: true },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">Alert History</h3>
        <Checkbox checked={includeTests} onChange={e => setIncludeTests(e.target.checked)}>Show test alerts</Checkbox>
      </div>
      <Table dataSource={entries} columns={columns} rowKey="id" loading={loading} size="small"
        expandable={{
          expandedRowRender: e => (
            <div className="space-y-3">
              {e.cleared_at && <p className="text-xs text-ink-mute">Cleared {new Date(e.cleared_at).toLocaleString()} by {e.cleared_by}</p>}
              {e.channel_results && Object.keys(e.channel_results).length > 0 && (
                <Space wrap>{Object.entries(e.channel_results).map(([ch, r]) => (
                  <Tag key={ch}>{ch}: {r.sent} sent{r.failed > 0 ? `, ${r.failed} failed` : ""}</Tag>
                ))}</Space>
              )}
              {e.body_text && <div><p className="text-xs font-medium text-ink-mute mb-1">Email Body</p><div className="bg-bone/30 rounded p-3 text-sm whitespace-pre-wrap">{e.body_text}</div></div>}
              {e.body_sms && <div><p className="text-xs font-medium text-ink-mute mb-1">SMS Body</p><div className="bg-bone/30 rounded p-3 text-sm">{e.body_sms}</div></div>}
            </div>
          ),
        }}
        pagination={false}
        locale={{ emptyText: <Empty description="No alerts sent yet" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />

      <Modal title="Alert Responses" open={!!responseModal} onCancel={() => setResponseModal(null)} footer={null} width={640}>
        {checkinStatus ? (
          <div className="space-y-4">
            <div className="grid grid-cols-4 gap-4">
              <Card size="small"><Statistic title="Total" value={checkinStatus.total_subscribers} /></Card>
              <Card size="small"><Statistic title="Safe" value={checkinStatus.responded_safe} valueStyle={{ color: "#52c41a" }} /></Card>
              <Card size="small"><Statistic title="Need Help" value={checkinStatus.responded_help} valueStyle={{ color: "#ff4d4f" }} /></Card>
              <Card size="small"><Statistic title="No Response" value={checkinStatus.no_response} valueStyle={{ color: "#faad14" }} /></Card>
            </div>
            {checkinStatus.total_subscribers > 0 && (
              <Progress percent={Math.round(((checkinStatus.responded_safe + checkinStatus.responded_help) / checkinStatus.total_subscribers) * 100)} status={checkinStatus.responded_help > 0 ? "exception" : "active"} />
            )}
            {checkinStatus.responded_help > 0 && (
              <div>
                <h4 className="font-medium text-sm text-red-600 mb-2">HELP Responses</h4>
                {checkinStatus.help_details.map(d => <div key={d.id} className="text-sm bg-red-50 rounded p-2 mb-1"><span className="font-mono">{d.phone}</span> — {new Date(d.received_at).toLocaleTimeString()}</div>)}
              </div>
            )}
            {checkinStatus.no_response > 0 && responseModal && (
              <Button type="primary" danger onClick={() => handleResend(responseModal)}>Re-send to {checkinStatus.no_response} Non-Responders</Button>
            )}
          </div>
        ) : responseSummary ? (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-4">
              <Card size="small"><Statistic title="Total Sent" value={responseSummary.total_sent} /></Card>
              <Card size="small"><Statistic title="Responses" value={responseSummary.total_responses} /></Card>
              <Card size="small"><Statistic title="Non-Responders" value={responseSummary.non_responder_count} /></Card>
            </div>
            {Object.keys(responseSummary.response_counts).length > 0 && (
              <div>
                <h4 className="font-medium text-sm mb-2">Response Breakdown</h4>
                <Space wrap>{Object.entries(responseSummary.response_counts).map(([key, count]) => (
                  <Tag key={key} color="blue">{key}: {count}</Tag>
                ))}</Space>
              </div>
            )}
            {responseDetails.length > 0 && (
              <div>
                <h4 className="font-medium text-sm mb-2">Individual Responses</h4>
                <Table dataSource={responseDetails} rowKey="id" size="small" pagination={{ pageSize: 20 }}
                  columns={[
                    { title: "Phone", dataIndex: "phone", key: "phone", render: v => <span className="font-mono text-xs">{v || "—"}</span> },
                    { title: "Response", dataIndex: "response_text", key: "response" },
                    { title: "Time", dataIndex: "received_at", key: "time", render: v => new Date(v).toLocaleTimeString() },
                  ]} />
              </div>
            )}
            {responseSummary.non_responder_count > 0 && responseModal && (
              <Button type="primary" danger onClick={() => handleResend(responseModal)}>Re-send to {responseSummary.non_responder_count} Non-Responders</Button>
            )}
          </div>
        ) : <Spin className="py-8 flex justify-center" />}
      </Modal>
    </div>
  );
}


// ===========================================================================
// Groups Section
// ===========================================================================

function GroupsSection() {
  const { modal, message } = App.useApp();
  const [groups, setGroups] = useState<SubscriberGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<SubscriberGroup | null>(null);
  const [managingMembers, setManagingMembers] = useState<SubscriberGroup | null>(null);
  const [members, setMembers] = useState<AlertSubscriber[]>([]);
  const [allSubscribers, setAllSubscribers] = useState<AlertSubscriber[]>([]);
  const [addIds, setAddIds] = useState<string[]>([]);

  const load = useCallback(async () => { setLoading(true); try { setGroups(await api.alerts.groups.list()); } finally { setLoading(false); } }, []);
  useEffect(() => { load(); }, [load]);

  function handleDelete(g: SubscriberGroup) {
    modal.confirm({
      title: `Delete group "${g.name}"?`, okText: "Delete", okButtonProps: { danger: true },
      onOk: async () => { await api.alerts.groups.delete(g.id); message.success("Group deleted"); load(); },
    });
  }

  async function openMembers(g: SubscriberGroup) {
    setManagingMembers(g);
    const [m, all] = await Promise.all([api.alerts.groups.members(g.id), api.alerts.subscribers.list()]);
    setMembers(m);
    setAllSubscribers(all);
    setAddIds([]);
  }

  async function handleAddMembers() {
    if (!managingMembers || addIds.length === 0) return;
    const result = await api.alerts.groups.addMembers(managingMembers.id, addIds);
    message.success(`Added ${result.added} members`);
    setAddIds([]);
    setMembers(await api.alerts.groups.members(managingMembers.id));
    load();
  }

  async function handleRemoveMember(subscriberId: string) {
    if (!managingMembers) return;
    await api.alerts.groups.removeMembers(managingMembers.id, [subscriberId]);
    setMembers(prev => prev.filter(m => m.id !== subscriberId));
    load();
  }

  const columns: ColumnsType<SubscriberGroup> = [
    { title: "Name", dataIndex: "name", key: "name" },
    { title: "Type", dataIndex: "group_type", key: "type", render: v => <Tag>{GROUP_TYPE_LABELS[v] ?? v}</Tag> },
    { title: "Members", dataIndex: "member_count", key: "members" },
    { title: "Actions", key: "actions", width: 200, render: (_, g) => (
      <Space>
        <Button type="link" size="small" onClick={() => openMembers(g)}>Members</Button>
        <Button type="link" size="small" onClick={() => { setEditing(g); setCreating(false); }}>Edit</Button>
        <Button type="link" size="small" danger onClick={() => handleDelete(g)}>Delete</Button>
      </Space>
    )},
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Subscriber Groups</h3>
        <Button type="primary" onClick={() => { setCreating(true); setEditing(null); }}>+ Add Group</Button>
      </div>
      {(creating || editing) && (
        <GroupForm initial={editing ?? undefined} onSave={() => { setCreating(false); setEditing(null); load(); }} onCancel={() => { setCreating(false); setEditing(null); }} />
      )}
      <Table dataSource={groups} columns={columns} rowKey="id" loading={loading} size="small" pagination={false} />

      <Modal title={`Members — ${managingMembers?.name}`} open={!!managingMembers} onCancel={() => setManagingMembers(null)} footer={null} width={640}>
        <div className="space-y-4">
          <div className="flex gap-2">
            <Select mode="multiple" value={addIds} onChange={setAddIds} placeholder="Add subscribers..." style={{ flex: 1 }}
              options={allSubscribers.filter(s => !members.some(m => m.id === s.id)).map(s => ({ label: `${s.name} (${s.email || s.phone})`, value: s.id }))}
              filterOption={(input, option) => (option?.label ?? "").toLowerCase().includes(input.toLowerCase())}
            />
            <Button type="primary" onClick={handleAddMembers} disabled={addIds.length === 0}>Add</Button>
          </div>
          <Table dataSource={members} rowKey="id" size="small" pagination={{ pageSize: 20 }}
            columns={[
              { title: "Name", dataIndex: "name", key: "name" },
              { title: "Email", dataIndex: "email", key: "email", ellipsis: true, render: v => v || "—" },
              { title: "Phone", dataIndex: "phone", key: "phone", render: v => v ? <span className="font-mono text-xs">{v}</span> : "—" },
              { title: "", key: "rm", width: 60, render: (_, s) => <Button type="text" size="small" danger onClick={() => handleRemoveMember(s.id)}>Remove</Button> },
            ]} />
        </div>
      </Modal>
    </div>
  );
}

function GroupForm({ initial, onSave, onCancel }: { initial?: SubscriberGroup; onSave: () => void; onCancel: () => void }) {
  const { message } = App.useApp();
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [groupType, setGroupType] = useState(initial?.group_type ?? "custom");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault(); setSaving(true);
    try {
      if (initial) await api.alerts.groups.update(initial.id, { name, description, group_type: groupType });
      else await api.alerts.groups.create({ name, description, group_type: groupType });
      message.success(initial ? "Group updated" : "Group created"); onSave();
    } catch { message.error("Failed to save"); } finally { setSaving(false); }
  }

  return (
    <Card title={initial ? "Edit Group" : "Add Group"}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Name</label><Input value={name} onChange={e => setName(e.target.value)} required /></div>
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Type</label>
            <Select value={groupType} onChange={setGroupType} style={{ width: "100%" }}
              options={Object.entries(GROUP_TYPE_LABELS).map(([v, l]) => ({ label: l, value: v }))} />
          </div>
        </div>
        <div><label className="block text-xs font-medium text-ink-mute mb-1">Description</label><Input.TextArea value={description} onChange={e => setDescription(e.target.value)} rows={2} /></div>
        <Space><Button onClick={onCancel}>Cancel</Button><Button type="primary" htmlType="submit" loading={saving}>{initial ? "Update" : "Create Group"}</Button></Space>
      </form>
    </Card>
  );
}


// ===========================================================================
// Scenarios Section
// ===========================================================================

function ScenariosSection() {
  const { modal, message } = App.useApp();
  const [scenarios, setScenarios] = useState<AlertScenario[]>([]);
  const [templates, setTemplates] = useState<AlertTemplate[]>([]);
  const [groups, setGroups] = useState<SubscriberGroup[]>([]);
  const [running, setRunning] = useState<RunningScenario[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<AlertScenario | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, t, g, r] = await Promise.all([
        api.alerts.scenarios.list(), api.alerts.templates.list(),
        api.alerts.groups.list(), api.alerts.scenarios.running(),
      ]);
      setScenarios(s); setTemplates(t); setGroups(g); setRunning(r);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  function handleDelete(s: AlertScenario) {
    modal.confirm({
      title: `Delete scenario "${s.name}"?`, okText: "Delete", okButtonProps: { danger: true },
      onOk: async () => { await api.alerts.scenarios.delete(s.id); message.success("Deleted"); load(); },
    });
  }

  function handleRun(s: AlertScenario) {
    modal.confirm({
      title: `Run scenario "${s.name}"?`,
      content: `This will execute ${s.steps.length} steps in sequence. Are you sure?`,
      okText: "Run Scenario", okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const { task_id } = await api.alerts.scenarios.run(s.id);
          message.success(`Scenario started (task: ${task_id.slice(0, 8)}...)`);
          load();
        } catch { message.error("Failed to start scenario"); }
      },
    });
  }

  async function handleAbort(taskId: string) {
    try { await api.alerts.scenarios.abort(taskId); message.success("Scenario aborted"); load(); }
    catch { message.error("Failed to abort"); }
  }

  const columns: ColumnsType<AlertScenario> = [
    { title: "Name", dataIndex: "name", key: "name" },
    { title: "Description", dataIndex: "description", key: "desc", ellipsis: true },
    { title: "Steps", key: "steps", render: (_, s) => s.steps.length },
    { title: "Actions", key: "actions", width: 200, render: (_, s) => (
      <Space>
        <Button type="primary" size="small" onClick={() => handleRun(s)}>Run</Button>
        <Button type="link" size="small" onClick={() => { setEditing(s); setCreating(false); }}>Edit</Button>
        <Button type="link" size="small" danger onClick={() => handleDelete(s)}>Delete</Button>
      </Space>
    )},
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Alert Scenarios</h3>
        <Button type="primary" onClick={() => { setCreating(true); setEditing(null); }}>+ Add Scenario</Button>
      </div>

      {running.length > 0 && (
        <Card size="small" className="!border-l-4 !border-l-red-500">
          <h4 className="font-medium text-sm mb-2">Running Scenarios</h4>
          {running.map(r => (
            <div key={r.task_id} className="flex items-center justify-between py-1">
              <div>
                <span className="font-medium">{r.scenario_name}</span>
                <span className="text-xs text-ink-mute ml-2">Step {r.current_step}/{r.total_steps} — by {r.started_by}</span>
              </div>
              <Button size="small" danger onClick={() => handleAbort(r.task_id)}>Abort</Button>
            </div>
          ))}
        </Card>
      )}

      {(creating || editing) && (
        <ScenarioForm initial={editing ?? undefined} templates={templates} groups={groups}
          onSave={() => { setCreating(false); setEditing(null); load(); }}
          onCancel={() => { setCreating(false); setEditing(null); }} />
      )}
      <Table dataSource={scenarios} columns={columns} rowKey="id" loading={loading} size="small" pagination={false} />
    </div>
  );
}

function ScenarioForm({ initial, templates, groups, onSave, onCancel }: {
  initial?: AlertScenario; templates: AlertTemplate[]; groups: SubscriberGroup[];
  onSave: () => void; onCancel: () => void;
}) {
  const { message } = App.useApp();
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [steps, setSteps] = useState<ScenarioStep[]>(initial?.steps ?? []);
  const [saving, setSaving] = useState(false);

  function addStep(action: "send_alert" | "wait" | "clear_previous") {
    setSteps([...steps, { action, delay_seconds: action === "wait" ? 60 : 0 }]);
  }

  function updateStep(i: number, patch: Partial<ScenarioStep>) {
    const updated = [...steps];
    updated[i] = { ...updated[i], ...patch };
    setSteps(updated);
  }

  function removeStep(i: number) { setSteps(steps.filter((_, j) => j !== i)); }

  function moveStep(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= steps.length) return;
    const updated = [...steps];
    [updated[i], updated[j]] = [updated[j], updated[i]];
    setSteps(updated);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault(); setSaving(true);
    try {
      if (initial) await api.alerts.scenarios.update(initial.id, { name, description, steps });
      else await api.alerts.scenarios.create({ name, description, steps });
      message.success(initial ? "Scenario updated" : "Scenario created"); onSave();
    } catch { message.error("Failed to save"); } finally { setSaving(false); }
  }

  return (
    <Card title={initial ? "Edit Scenario" : "Add Scenario"}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Name</label><Input value={name} onChange={e => setName(e.target.value)} required /></div>
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Description</label><Input value={description} onChange={e => setDescription(e.target.value)} /></div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs font-medium text-ink-mute">Steps</label>
            <Space>
              <Button size="small" onClick={() => addStep("send_alert")}>+ Send Alert</Button>
              <Button size="small" onClick={() => addStep("wait")}>+ Wait</Button>
              <Button size="small" onClick={() => addStep("clear_previous")}>+ Clear Previous</Button>
            </Space>
          </div>
          {steps.length === 0 ? <Empty description="No steps" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
            <div className="space-y-2">
              {steps.map((step, i) => (
                <Card key={i} size="small" className="!bg-bone/30">
                  <div className="flex items-start gap-3">
                    <div className="flex flex-col gap-1">
                      <Button size="small" type="text" onClick={() => moveStep(i, -1)} disabled={i === 0}>↑</Button>
                      <Button size="small" type="text" onClick={() => moveStep(i, 1)} disabled={i === steps.length - 1}>↓</Button>
                    </div>
                    <div className="flex-1">
                      <Tag color={step.action === "send_alert" ? "blue" : step.action === "wait" ? "gold" : "default"} className="mb-2">
                        {step.action === "send_alert" ? "Send Alert" : step.action === "wait" ? "Wait" : "Clear Previous"}
                      </Tag>
                      {step.action === "send_alert" && (
                        <div className="space-y-2">
                          <Select placeholder="Select template..." value={step.template_id} onChange={v => updateStep(i, { template_id: v })}
                            style={{ width: "100%" }}
                            options={templates.map(t => ({ label: `${t.name} (${t.category})`, value: t.id }))} />
                          <Select mode="multiple" placeholder="Target groups (optional)" value={step.group_ids || []}
                            onChange={v => updateStep(i, { group_ids: v })} style={{ width: "100%" }}
                            options={groups.map(g => ({ label: g.name, value: g.id }))} />
                        </div>
                      )}
                      {step.action === "wait" && (
                        <div className="flex items-center gap-2">
                          <span className="text-xs">Wait</span>
                          <InputNumber size="small" min={1} value={step.delay_seconds} onChange={v => updateStep(i, { delay_seconds: v ?? 60 })} />
                          <span className="text-xs">seconds</span>
                        </div>
                      )}
                    </div>
                    <Button type="text" size="small" danger onClick={() => removeStep(i)}>Remove</Button>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>

        <Space><Button onClick={onCancel}>Cancel</Button><Button type="primary" htmlType="submit" loading={saving} disabled={steps.length === 0}>{initial ? "Update" : "Create Scenario"}</Button></Space>
      </form>
    </Card>
  );
}


// ===========================================================================
// Subscribers Section (unchanged from original)
// ===========================================================================

function SubscribersSection() {
  const { modal, message } = App.useApp();
  const [subscribers, setSubscribers] = useState<AlertSubscriber[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<AlertSubscriber | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try { setSubscribers(await api.alerts.subscribers.list({ search: search || undefined, category: filterCategory || undefined })); }
    finally { setLoading(false); }
  }, [search, filterCategory]);

  useEffect(() => { load(); }, [load]);

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; if (!file) return;
    try { const result = await api.alerts.subscribers.importCsv(file); message.success(`Import: ${result.created} created, ${result.skipped} skipped`); load(); }
    catch (err: any) { message.error(`Import failed: ${err.message}`); }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleExport() {
    const token = (await import("../auth")).getAccessToken();
    const t = await token;
    const res = await fetch(api.alerts.subscribers.exportUrl, { headers: t ? { Authorization: `Bearer ${t}` } : {} });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "alert_subscribers.csv"; a.click(); URL.revokeObjectURL(url);
  }

  function handleDelete(s: AlertSubscriber) {
    modal.confirm({
      title: `Remove subscriber "${s.name}"?`, okText: "Delete", okButtonProps: { danger: true },
      onOk: async () => { await api.alerts.subscribers.delete(s.id); message.success("Subscriber removed"); load(); },
    });
  }

  const columns: ColumnsType<AlertSubscriber> = [
    { title: "Name", dataIndex: "name", key: "name" },
    { title: "Email", dataIndex: "email", key: "email", ellipsis: true, render: (v, s) => <>{v || "—"}{v && !s.email_enabled && <Tag color="red" className="ml-1 !text-[10px]">off</Tag>}</> },
    { title: "Phone", dataIndex: "phone", key: "phone", render: (v, s) => <>{v ? <span className="font-mono text-xs">{v}</span> : "—"}{v && !s.sms_enabled && <Tag color="red" className="ml-1 !text-[10px]">off</Tag>}</> },
    { title: "Categories", key: "cats", render: (_, s) => <Space size={2} wrap>{s.categories.map(c => <Tag key={c} color={CATEGORIES.find(ci => ci.id === c)?.color} className="!text-[10px]">{CATEGORIES.find(ci => ci.id === c)?.label ?? c}</Tag>)}</Space> },
    { title: "Source", dataIndex: "source", key: "source", render: v => <span className="text-xs capitalize">{v}</span> },
    {
      title: "Actions", key: "actions", width: 120,
      render: (_, s) => <Space><Button type="link" size="small" onClick={() => { setEditing(s); setCreating(false); }}>Edit</Button><Button type="link" size="small" danger onClick={() => handleDelete(s)}>Delete</Button></Space>,
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Subscribers</h3>
        <Space>
          <input ref={fileInputRef} type="file" accept=".csv" onChange={handleImport} className="hidden" />
          <Button onClick={() => fileInputRef.current?.click()}>Import CSV</Button>
          <Button onClick={handleExport}>Export CSV</Button>
          <Button type="primary" onClick={() => { setCreating(true); setEditing(null); }}>+ Add Subscriber</Button>
        </Space>
      </div>
      <Space>
        <Input.Search value={search} onChange={e => setSearch(e.target.value)} placeholder="Search..." style={{ width: 260 }} allowClear />
        <Select value={filterCategory || undefined} onChange={v => setFilterCategory(v || "")} placeholder="All Categories" allowClear style={{ width: 160 }}
          options={CATEGORIES.map(c => ({ label: c.label, value: c.id }))} />
        <span className="text-sm text-ink-mute">{subscribers.length} subscribers</span>
      </Space>
      {(creating || editing) && <SubscriberForm initial={editing ?? undefined} onSave={() => { setCreating(false); setEditing(null); load(); }} onCancel={() => { setCreating(false); setEditing(null); }} />}
      <Table dataSource={subscribers} columns={columns} rowKey="id" loading={loading} size="small" pagination={{ pageSize: 50 }} />
    </div>
  );
}

function SubscriberForm({ initial, onSave, onCancel }: { initial?: AlertSubscriber; onSave: () => void; onCancel: () => void }) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (initial) form.setFieldsValue(initial);
    else form.resetFields();
  }, [initial, form]);

  async function handleFinish(values: any) {
    setSaving(true);
    try {
      if (initial) await api.alerts.subscribers.update(initial.id, values);
      else await api.alerts.subscribers.create({ ...values, source: "admin" });
      message.success(initial ? "Subscriber updated" : "Subscriber added");
      onSave();
    } catch { message.error("Failed to save"); } finally { setSaving(false); }
  }

  return (
    <Card title={initial ? "Edit Subscriber" : "Add Subscriber"}>
      <Form form={form} layout="vertical" onFinish={handleFinish}
        initialValues={{ sms_enabled: true, email_enabled: true, categories: ["emergency", "weather", "campus_closing", "parking", "general"] }}>
        <div className="grid grid-cols-3 gap-x-4">
          <Form.Item name="name" label="Name" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="email" label="Email"><Input type="email" /></Form.Item>
          <Form.Item name="phone" label="Phone"><Input placeholder="+15551234567" /></Form.Item>
        </div>
        <Form.Item name="categories" label="Alert Categories">
          <Checkbox.Group options={CATEGORIES.map(c => ({ label: c.label, value: c.id }))} />
        </Form.Item>
        <Space className="mb-4">
          <Form.Item name="email_enabled" valuePropName="checked" noStyle><Checkbox>Email enabled</Checkbox></Form.Item>
          <Form.Item name="sms_enabled" valuePropName="checked" noStyle><Checkbox>SMS enabled</Checkbox></Form.Item>
        </Space>
        <Space>
          <Button onClick={onCancel}>Cancel</Button>
          <Button type="primary" htmlType="submit" loading={saving}>{initial ? "Update" : "Add Subscriber"}</Button>
        </Space>
      </Form>
    </Card>
  );
}


// ===========================================================================
// Channels Section (unchanged)
// ===========================================================================

function ChannelsSection() {
  const [channels, setChannels] = useState<AlertChannelInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { api.alerts.channels().then(setChannels).finally(() => setLoading(false)); }, []);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">Alert Channels</h3>
        <span className="text-xs text-ink-mute">{channels.filter(c => c.configured).length}/{channels.length} configured</span>
      </div>
      <Spin spinning={loading}>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {channels.map(ch => (
            <Card key={ch.name} size="small" className={`!border-l-4 ${ch.configured ? "!border-l-green-500" : "!border-l-gray-300"}`}>
              <div className="flex items-center justify-between mb-1">
                <h4 className="font-medium text-sm">{CHANNEL_LABELS[ch.name] ?? ch.name}</h4>
                <Tag color={ch.configured ? "green" : "default"}>{ch.configured ? "Configured" : "Not Configured"}</Tag>
              </div>
              <p className="text-xs text-ink-mute mb-1">{CHANNEL_DESCRIPTIONS[ch.name] ?? ""}</p>
              {ch.emergency_only && <Tag color="red" className="!text-[10px]">Emergency Only</Tag>}
              {!ch.configured && <p className="text-[10px] text-ink-mute font-mono mt-1 break-all">{CHANNEL_ENV_HINTS[ch.name] ?? ""}</p>}
            </Card>
          ))}
        </div>
      </Spin>
    </div>
  );
}


// ===========================================================================
// Test Console (unchanged)
// ===========================================================================

function TestConsole() {
  const { message } = App.useApp();
  const [channels, setChannels] = useState<AlertChannelInfo[]>([]);
  const [screens, setScreens] = useState<SignageScreen[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedChannel, setSelectedChannel] = useState("");
  const [category, setCategory] = useState("general");
  const [subject, setSubject] = useState("Alert channel test");
  const [bodyText, setBodyText] = useState("This is an automated test. No action required.");
  const [bodySms, setBodySms] = useState("TEST: Alert channel test. No action required.");
  const [testEmail, setTestEmail] = useState("");
  const [testPhone, setTestPhone] = useState("");
  const [screenId, setScreenId] = useState("");
  const [sending, setSending] = useState(false);
  const [results, setResults] = useState<AlertTestSendResult[]>([]);

  useEffect(() => {
    Promise.all([api.alerts.channels(), api.signage.screens.list()]).then(([ch, sc]) => {
      setChannels(ch); setScreens(sc);
      const first = ch.find(c => c.configured);
      if (first) setSelectedChannel(first.name);
    }).finally(() => setLoading(false));
  }, []);

  const channelInfo = channels.find(c => c.name === selectedChannel);
  const needsRecipient = ["sms", "email", "voice"].includes(selectedChannel);
  const isEmergencyOnly = channelInfo?.emergency_only ?? false;

  useEffect(() => { if (isEmergencyOnly) setCategory("emergency"); }, [isEmergencyOnly]);

  const canSend = selectedChannel && (!needsRecipient || testEmail || testPhone) && subject;

  async function handleSend() {
    setSending(true);
    try {
      const r = await api.alerts.testSend({ channel: selectedChannel, category, subject, body_text: bodyText, body_sms: bodySms, test_email: testEmail || null, test_phone: testPhone || null, screen_id: screenId || null });
      setResults(prev => [r, ...prev]);
      message.success("Test sent");
    } catch (err: any) {
      setResults(prev => [{ alert_id: "", channel: selectedChannel, sent: 0, failed: 1, error: err.message, status: "error" }, ...prev]);
      message.error("Test failed");
    } finally { setSending(false); }
  }

  if (loading) return <Spin className="py-8 flex justify-center" />;
  const configuredChannels = channels.filter(c => c.configured);

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold mb-1">Test Console</h3>
        <p className="text-sm text-ink-mute">Send isolated test alerts to a single channel without affecting real subscribers.</p>
      </div>
      {configuredChannels.length === 0
        ? <Alert type="warning" showIcon message="No channels configured. Set environment variables on the Channels tab first." />
        : (
          <Card>
            <div className="space-y-5">
              <div>
                <label className="block text-xs font-medium text-ink-mute mb-2">Channel to Test</label>
                <Segmented value={selectedChannel} onChange={v => setSelectedChannel(v as string)}
                  options={configuredChannels.map(ch => ({ label: CHANNEL_LABELS[ch.name] ?? ch.name, value: ch.name }))} />
              </div>
              <div>
                <label className="block text-xs font-medium text-ink-mute mb-2">Alert Category</label>
                <Segmented value={category} onChange={v => !isEmergencyOnly && setCategory(v as string)}
                  options={CATEGORIES.map(c => ({ label: c.label, value: c.id, disabled: isEmergencyOnly && c.id !== "emergency" }))} />
              </div>
              {needsRecipient && (
                <Alert type="info" showIcon message="Test recipient — only this person receives the test."
                  description={
                    <div className="grid grid-cols-2 gap-4 mt-2">
                      <div><label className="block text-xs mb-1">Email</label><Input value={testEmail} onChange={e => setTestEmail(e.target.value)} type="email" placeholder="you@example.edu" /></div>
                      <div><label className="block text-xs mb-1">Phone</label><Input value={testPhone} onChange={e => setTestPhone(e.target.value)} placeholder="+15551234567" /></div>
                    </div>
                  } />
              )}
              {selectedChannel === "signage" && screens.length > 0 && (
                <div>
                  <label className="block text-xs font-medium text-ink-mute mb-1">Target Screen</label>
                  <Select value={screenId || undefined} onChange={v => setScreenId(v || "")} placeholder="All screens" allowClear style={{ width: 300 }}
                    options={screens.map(s => ({ label: `${s.name} — ${s.location}`, value: s.id }))} />
                </div>
              )}
              <details>
                <summary className="text-xs font-medium text-ink-mute cursor-pointer">Customize test message</summary>
                <div className="mt-3 space-y-3">
                  <div><label className="block text-xs mb-1">Subject</label><Input value={subject} onChange={e => setSubject(e.target.value)} /></div>
                  <div><label className="block text-xs mb-1">Body</label><Input.TextArea value={bodyText} onChange={e => setBodyText(e.target.value)} rows={3} /></div>
                  <div><label className="block text-xs mb-1">SMS <span className={`ml-2 ${bodySms.length > 160 ? "text-red-600 font-bold" : ""}`}>{bodySms.length}/160</span></label><Input.TextArea value={bodySms} onChange={e => setBodySms(e.target.value)} rows={2} /></div>
                </div>
              </details>
              <Button type="primary" onClick={handleSend} disabled={!canSend} loading={sending}>
                Test {CHANNEL_LABELS[selectedChannel] ?? selectedChannel}
              </Button>
            </div>
          </Card>
        )}
      {results.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h4 className="font-medium text-sm">Test Results</h4>
            <Button type="text" size="small" onClick={() => setResults([])}>Clear</Button>
          </div>
          <div className="space-y-2">
            {results.map((r, i) => (
              <Alert key={i} type={r.error ? "error" : "success"} showIcon
                message={<><span className="font-medium capitalize">{CHANNEL_LABELS[r.channel] ?? r.channel}</span> — {r.error ? r.error : `${r.sent} sent, ${r.failed} failed`}</>} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


// ===========================================================================
// Signage Section (unchanged)
// ===========================================================================

function SignageSection() {
  const { modal, message } = App.useApp();
  const [screens, setScreens] = useState<SignageScreen[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingScreen, setEditingScreen] = useState<SignageScreen | null>(null);

  const load = useCallback(async () => { setLoading(true); try { setScreens(await api.signage.screens.list()); } finally { setLoading(false); } }, []);
  useEffect(() => { load(); }, [load]);

  function handleDeleteScreen(s: SignageScreen) {
    modal.confirm({
      title: `Delete screen "${s.name}"?`, okText: "Delete", okButtonProps: { danger: true },
      onOk: async () => { await api.signage.screens.delete(s.id); message.success("Screen deleted"); load(); },
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Digital Signage Screens</h3>
        <Button type="primary" onClick={() => { setShowForm(true); setEditingScreen(null); }}>+ Add Screen</Button>
      </div>
      {(showForm || editingScreen) && (
        <ScreenForm initial={editingScreen ?? undefined}
          onSave={() => { setShowForm(false); setEditingScreen(null); load(); }}
          onCancel={() => { setShowForm(false); setEditingScreen(null); }} />
      )}
      <Spin spinning={loading}>
        {screens.length === 0
          ? <Empty description="No signage screens configured" />
          : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {screens.map(s => (
                <Card key={s.id} size="small">
                  <Space className="mb-2"><span className={`w-2.5 h-2.5 rounded-full inline-block ${s.is_online ? "bg-green-500" : "bg-gray-400"}`} /><h4 className="font-medium text-sm">{s.name}</h4></Space>
                  {s.location && <p className="text-xs text-ink-mute mb-2">{s.location}</p>}
                  <p className="text-xs text-ink-mute">{s.playlist.length} slide{s.playlist.length !== 1 ? "s" : ""}</p>
                  {s.last_seen && <p className="text-xs text-ink-mute mt-1">Last seen: {new Date(s.last_seen).toLocaleString()}</p>}
                  <Space className="mt-3">
                    <Button type="link" size="small" onClick={() => window.open(`/signage/player/${s.id}`, "_blank")}>Preview</Button>
                    <Button type="link" size="small" onClick={() => { setEditingScreen(s); setShowForm(false); }}>Edit</Button>
                    <Button type="link" size="small" danger onClick={() => handleDeleteScreen(s)}>Delete</Button>
                  </Space>
                </Card>
              ))}
            </div>
          )}
      </Spin>
    </div>
  );
}

function ScreenForm({ initial, onSave, onCancel }: { initial?: SignageScreen; onSave: () => void; onCancel: () => void }) {
  const { message } = App.useApp();
  const [name, setName] = useState(initial?.name ?? "");
  const [location, setLocation] = useState(initial?.location ?? "");
  const [playlist, setPlaylist] = useState<{ type: string; url: string; duration: number }[]>(initial?.playlist ?? []);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault(); setSaving(true);
    try {
      if (initial) await api.signage.screens.update(initial.id, { name, location, playlist });
      else await api.signage.screens.create({ name, location, playlist });
      message.success(initial ? "Screen updated" : "Screen added");
      onSave();
    } catch { message.error("Failed to save"); } finally { setSaving(false); }
  }

  return (
    <Card title={initial ? "Edit Screen" : "Add Screen"}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Name</label><Input value={name} onChange={e => setName(e.target.value)} required placeholder="HUB Lobby Display" /></div>
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Location</label><Input value={location} onChange={e => setLocation(e.target.value)} placeholder="HUB 1st Floor" /></div>
        </div>
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs font-medium text-ink-mute">Playlist</label>
            <Button type="link" size="small" onClick={() => setPlaylist([...playlist, { type: "image", url: "", duration: 10 }])}>+ Add Slide</Button>
          </div>
          {playlist.length === 0 ? <Empty description="No slides" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
            <div className="space-y-2">
              {playlist.map((slide, i) => (
                <Space key={i} className="w-full bg-bone/30 rounded-lg p-2">
                  <Select size="small" value={slide.type} onChange={v => { const u = [...playlist]; u[i].type = v; setPlaylist(u); }} style={{ width: 100 }}
                    options={[{ label: "Image", value: "image" }, { label: "HTML", value: "html" }, { label: "IFrame", value: "iframe" }]} />
                  <Input size="small" value={slide.url} onChange={e => { const u = [...playlist]; u[i].url = e.target.value; setPlaylist(u); }} placeholder="URL..." style={{ width: 240 }} />
                  <Input size="small" type="number" value={slide.duration} onChange={e => { const u = [...playlist]; u[i].duration = parseInt(e.target.value) || 10; setPlaylist(u); }} style={{ width: 60 }} suffix="sec" />
                  <Button type="text" size="small" danger onClick={() => setPlaylist(playlist.filter((_, j) => j !== i))}>Remove</Button>
                </Space>
              ))}
            </div>
          )}
        </div>
        <Space>
          <Button onClick={onCancel}>Cancel</Button>
          <Button type="primary" htmlType="submit" loading={saving}>{initial ? "Update Screen" : "Add Screen"}</Button>
        </Space>
      </form>
    </Card>
  );
}


// ===========================================================================
// Scheduled Alerts Section
// ===========================================================================

function ScheduledSection() {
  const { modal, message } = App.useApp();
  const [alerts, setAlerts] = useState<AlertLogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try { setAlerts(await api.alerts.scheduled.list()); } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  function handleCancel(a: AlertLogEntry) {
    modal.confirm({
      title: "Cancel scheduled alert?",
      content: `"${a.subject}" scheduled for ${new Date(a.scheduled_for!).toLocaleString()}`,
      okText: "Cancel Alert", okButtonProps: { danger: true },
      onOk: async () => {
        try { await api.alerts.scheduled.cancel(a.id); message.success("Scheduled alert cancelled"); load(); }
        catch { message.error("Failed to cancel"); }
      },
    });
  }

  const RECURRENCE_LABELS: Record<string, string> = {
    daily: "Daily", weekly: "Weekly", biweekly: "Biweekly",
    monthly: "Monthly", quarterly: "Quarterly", yearly: "Yearly",
  };

  const columns: ColumnsType<AlertLogEntry> = [
    { title: "Subject", dataIndex: "subject", key: "subject" },
    { title: "Category", dataIndex: "category", key: "category",
      render: (c: string) => { const ci = CATEGORIES.find(cat => cat.id === c); return <Tag color={ci?.color}>{ci?.label ?? c}</Tag>; }
    },
    { title: "Scheduled For", dataIndex: "scheduled_for", key: "scheduled_for",
      render: (v: string) => v ? new Date(v).toLocaleString() : "—",
    },
    { title: "Repeat", dataIndex: "recurrence_rule", key: "recurrence_rule",
      render: (v: string | null) => v ? <Tag color="blue">{RECURRENCE_LABELS[v] ?? v}</Tag> : "—",
    },
    { title: "Created By", dataIndex: "sent_by", key: "sent_by" },
    { title: "", key: "actions", render: (_: unknown, record: AlertLogEntry) => (
      <Button type="link" danger size="small" onClick={() => handleCancel(record)}>Cancel</Button>
    )},
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Scheduled & Recurring Alerts</h3>
        <Button onClick={load}>Refresh</Button>
      </div>
      <Table dataSource={alerts} columns={columns} rowKey="id" loading={loading} pagination={false}
        locale={{ emptyText: <Empty description="No scheduled alerts" /> }} />
    </div>
  );
}


// ===========================================================================
// Analytics Section
// ===========================================================================

function AnalyticsSection() {
  const { message } = App.useApp();
  const [dashboard, setDashboard] = useState<AlertAnalyticsDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(90);
  const [afterAction, setAfterAction] = useState<AfterActionReport | null>(null);
  const [aaModalOpen, setAaModalOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { setDashboard(await api.alerts.analytics.dashboard(days)); } finally { setLoading(false); }
  }, [days]);
  useEffect(() => { load(); }, [load]);

  async function showAfterAction(alertId: string) {
    try {
      const report = await api.alerts.analytics.afterAction(alertId);
      setAfterAction(report);
      setAaModalOpen(true);
    } catch { message.error("Failed to load report"); }
  }

  if (loading) return <Spin className="w-full flex justify-center py-12" />;
  if (!dashboard) return <Empty description="No analytics data" />;

  const { summary, channel_stats, recent_response_rates } = dashboard;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Alert Analytics</h3>
        <Select value={days} onChange={setDays} style={{ width: 140 }}
          options={[
            { label: "Last 30 days", value: 30 },
            { label: "Last 90 days", value: 90 },
            { label: "Last 180 days", value: 180 },
            { label: "Last year", value: 365 },
          ]} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card size="small"><Statistic title="Total Alerts" value={summary.total_alerts} /></Card>
        <Card size="small"><Statistic title="Emails Sent" value={summary.total_emails} /></Card>
        <Card size="small"><Statistic title="SMS Sent" value={summary.total_sms} /></Card>
        <Card size="small"><Statistic title="Avg Channels/Alert" value={summary.avg_channels_per_alert} precision={1} /></Card>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card title="Alerts by Category" size="small">
          {Object.keys(summary.by_category).length === 0
            ? <Empty description="No data" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            : <div className="space-y-2">
                {Object.entries(summary.by_category).map(([cat, count]) => {
                  const ci = CATEGORIES.find(c => c.id === cat);
                  const pct = summary.total_alerts > 0 ? Math.round(count / summary.total_alerts * 100) : 0;
                  return (
                    <div key={cat} className="flex items-center gap-3">
                      <Tag color={ci?.color}>{ci?.label ?? cat}</Tag>
                      <Progress percent={pct} size="small" className="flex-1" format={() => `${count}`} />
                    </div>
                  );
                })}
              </div>}
        </Card>

        <Card title="Channel Delivery" size="small">
          {channel_stats.length === 0
            ? <Empty description="No channel data" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            : <div className="space-y-2">
                {channel_stats.map(cs => (
                  <div key={cs.channel} className="flex items-center gap-3">
                    <span className="text-xs font-medium w-20 capitalize">{cs.channel}</span>
                    <Progress percent={Math.round(cs.success_rate)} size="small" className="flex-1"
                      status={cs.success_rate >= 95 ? "success" : cs.success_rate >= 80 ? "normal" : "exception"} />
                    <span className="text-xs text-ink-mute">{cs.total_sent} sent</span>
                  </div>
                ))}
              </div>}
        </Card>
      </div>

      {summary.by_month.length > 0 && (
        <Card title="Monthly Trend" size="small">
          <div className="overflow-x-auto">
            <div className="flex gap-2 items-end min-w-[400px]" style={{ height: 120 }}>
              {summary.by_month.map(m => {
                const maxCount = Math.max(...summary.by_month.map(x => x.count), 1);
                const h = Math.max((m.count / maxCount) * 100, 4);
                return (
                  <div key={m.month} className="flex flex-col items-center flex-1">
                    <span className="text-xs font-medium mb-1">{m.count}</span>
                    <div className="w-full bg-blue-500 rounded-t" style={{ height: `${h}px` }} />
                    <span className="text-[10px] text-ink-mute mt-1">{m.month.slice(5)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </Card>
      )}

      {recent_response_rates.length > 0 && (
        <Card title="Response Rates" size="small">
          <Table dataSource={recent_response_rates} rowKey="alert_id" pagination={false} size="small"
            columns={[
              { title: "Alert", dataIndex: "subject", key: "subject", ellipsis: true },
              { title: "Category", dataIndex: "category", key: "category",
                render: (c: string) => { const ci = CATEGORIES.find(cat => cat.id === c); return <Tag color={ci?.color}>{ci?.label ?? c}</Tag>; }
              },
              { title: "Responses", key: "responses",
                render: (_: unknown, r: typeof recent_response_rates[0]) => `${r.total_responses} / ${r.total_subscribers}`,
              },
              { title: "Rate", dataIndex: "response_rate", key: "rate",
                render: (v: number) => <Progress type="circle" percent={Math.round(v)} size={32} />,
              },
              { title: "Safe / Help", key: "checkin",
                render: (_: unknown, r: typeof recent_response_rates[0]) =>
                  r.checkin_safe || r.checkin_help
                    ? <span className="text-xs"><span className="text-green-600">{r.checkin_safe} safe</span> / <span className="text-red-600">{r.checkin_help} help</span></span>
                    : "—",
              },
              { title: "Sent", dataIndex: "sent_at", key: "sent_at",
                render: (v: string) => new Date(v).toLocaleDateString(),
              },
              { title: "", key: "report",
                render: (_: unknown, r: typeof recent_response_rates[0]) => (
                  <Button type="link" size="small" onClick={() => showAfterAction(r.alert_id)}>After-Action</Button>
                ),
              },
            ]} />
        </Card>
      )}

      <Modal title="After-Action Report" open={aaModalOpen} onCancel={() => setAaModalOpen(false)} footer={null} width={700}>
        {afterAction && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div><span className="text-xs text-ink-mute">Subject</span><p className="font-medium">{afterAction.subject}</p></div>
              <div><span className="text-xs text-ink-mute">Category</span><p><Tag color={CATEGORIES.find(c => c.id === afterAction.category)?.color}>{afterAction.category}</Tag></p></div>
              <div><span className="text-xs text-ink-mute">Sent By</span><p>{afterAction.sent_by}</p></div>
              <div><span className="text-xs text-ink-mute">Sent At</span><p>{new Date(afterAction.sent_at).toLocaleString()}</p></div>
              {afterAction.cleared_at && (
                <div><span className="text-xs text-ink-mute">Cleared At</span><p>{new Date(afterAction.cleared_at).toLocaleString()}</p></div>
              )}
            </div>

            <Card size="small" title="Response Summary">
              <div className="grid grid-cols-3 gap-4">
                <Statistic title="Total Subscribers" value={afterAction.total_subscribers} />
                <Statistic title="Total Responses" value={afterAction.total_responses} />
                <Statistic title="Response Rate" value={afterAction.response_rate} suffix="%" precision={1} />
              </div>
            </Card>

            {Object.keys(afterAction.response_breakdown).length > 0 && (
              <Card size="small" title="Response Breakdown">
                <div className="flex gap-4 flex-wrap">
                  {Object.entries(afterAction.response_breakdown).map(([resp, count]) => (
                    <Tag key={resp} color={resp === "SAFE" ? "green" : resp === "HELP" ? "red" : "default"}>
                      {resp}: {count}
                    </Tag>
                  ))}
                </div>
              </Card>
            )}

            {afterAction.channel_results && (
              <Card size="small" title="Channel Results">
                <div className="space-y-1">
                  {Object.entries(afterAction.channel_results).map(([ch, r]) => (
                    <div key={ch} className="flex items-center gap-3 text-sm">
                      <span className="font-medium capitalize w-24">{ch}</span>
                      <span className="text-green-600">{r.sent} sent</span>
                      {r.failed > 0 && <span className="text-red-600">{r.failed} failed</span>}
                      {r.error && <span className="text-ink-mute text-xs">({r.error})</span>}
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {afterAction.timeline.length > 0 && (
              <Card size="small" title={`Response Timeline (${afterAction.timeline.length})`}>
                <div className="max-h-60 overflow-y-auto space-y-1">
                  {afterAction.timeline.map((entry, i) => (
                    <div key={i} className="flex gap-3 text-xs">
                      <span className="text-ink-mute w-36">{new Date(entry.time).toLocaleString()}</span>
                      <span className="w-28 font-mono">{entry.phone}</span>
                      <Tag>{entry.response}</Tag>
                    </div>
                  ))}
                </div>
              </Card>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}


// ===========================================================================
// Weather Auto-Triggers Section
// ===========================================================================

function WeatherSection() {
  const { message } = App.useApp();
  const [config, setConfig] = useState<WeatherAlertConfig | null>(null);
  const [recent, setRecent] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cfg, r] = await Promise.all([
        api.alerts.weather.config(),
        api.alerts.weather.recent(),
      ]);
      setConfig(cfg);
      setRecent(r.seen_events);
    } catch {
      message.error("Failed to load weather config");
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (loading) return <Spin className="w-full flex justify-center py-12" />;

  return (
    <div className="space-y-6">
      <h3 className="text-lg font-semibold">NWS Weather Auto-Triggers</h3>

      <Card size="small">
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <div>
            <span className="text-xs text-ink-mute">Status</span>
            <p><Tag color={config?.enabled ? "green" : "default"}>{config?.enabled ? "Active" : "Disabled"}</Tag></p>
          </div>
          <div>
            <span className="text-xs text-ink-mute">Zone ID</span>
            <p className="font-mono text-sm">{config?.zone_id}</p>
          </div>
          <div>
            <span className="text-xs text-ink-mute">Poll Interval</span>
            <p>{config?.poll_interval_seconds}s</p>
          </div>
        </div>
        <p className="text-xs text-ink-mute mt-3">
          Configure via environment variables: NWS_ALERTS_ENABLED, NWS_ZONE_ID, NWS_POLL_INTERVAL_SECONDS
        </p>
      </Card>

      <Card title="Event Mappings" size="small">
        {config?.event_mappings.length === 0
          ? <Empty description="No event mappings configured" />
          : (
            <Table dataSource={config?.event_mappings ?? []} rowKey="event" pagination={false} size="small"
              columns={[
                { title: "Weather Event", dataIndex: "event", key: "event" },
                { title: "Category", dataIndex: "category", key: "category",
                  render: (c: string) => { const ci = CATEGORIES.find(cat => cat.id === c); return <Tag color={ci?.color}>{ci?.label ?? c}</Tag>; }
                },
                { title: "Auto-Send", dataIndex: "auto_send", key: "auto_send",
                  render: (v: boolean) => <Tag color={v ? "green" : "default"}>{v ? "Yes" : "Manual"}</Tag>,
                },
              ]} />
          )}
      </Card>

      <Card title={`Recent Events (${recent.length} seen this session)`} size="small">
        {recent.length === 0
          ? <Empty description="No weather events seen since server start" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          : (
            <div className="space-y-1 max-h-40 overflow-y-auto">
              {recent.map((id, i) => <div key={i} className="text-xs font-mono text-ink-mute">{id}</div>)}
            </div>
          )}
      </Card>
    </div>
  );
}


// ===========================================================================
// SIS Subscriber Sync Section
// ===========================================================================

function SisSyncSection() {
  const { message } = App.useApp();
  const [config, setConfig] = useState<SisSubscriberSyncConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { setConfig(await api.alerts.sisSync.status()); }
    catch { message.error("Failed to load SIS sync status"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function handleSync() {
    setSyncing(true);
    try {
      const result = await api.alerts.sisSync.trigger();
      setConfig(result);
      message.success(`SIS sync complete: ${result.total_synced} records`);
    } catch (err: any) {
      message.error(`Sync failed: ${err.message}`);
    } finally { setSyncing(false); }
  }

  if (loading) return <Spin className="w-full flex justify-center py-12" />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">SIS / Colleague Subscriber Sync</h3>
        <Button type="primary" onClick={handleSync} loading={syncing} disabled={!config?.enabled}>
          Sync Now
        </Button>
      </div>

      <Card size="small">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <span className="text-xs text-ink-mute">Status</span>
            <p><Tag color={config?.enabled ? "green" : "default"}>{config?.enabled ? "Enabled" : "Disabled"}</Tag></p>
          </div>
          <div>
            <span className="text-xs text-ink-mute">Sync URL</span>
            <p className="font-mono text-xs truncate">{config?.sync_url || "Not configured"}</p>
          </div>
          <div>
            <span className="text-xs text-ink-mute">Last Sync</span>
            <p className="text-sm">{config?.last_sync_at ? new Date(config.last_sync_at).toLocaleString() : "Never"}</p>
          </div>
          <div>
            <span className="text-xs text-ink-mute">Records Synced</span>
            <p className="text-sm font-medium">{config?.total_synced ?? 0}</p>
          </div>
        </div>
        <p className="text-xs text-ink-mute mt-4">
          Configure via environment variables: SIS_SUBSCRIBER_SYNC_ENABLED, SIS_SUBSCRIBER_SYNC_URL, SIS_SUBSCRIBER_SYNC_KEY
        </p>
      </Card>

      <Alert type="info" showIcon
        message="How SIS Sync Works"
        description={
          <ul className="text-xs list-disc ml-4 mt-1 space-y-1">
            <li>Pulls student and staff directory from the configured SIS API endpoint</li>
            <li>Creates or updates alert subscribers with email, phone, and name</li>
            <li>Auto-assigns subscribers to groups based on role (Students, Faculty & Staff, etc.)</li>
            <li>Handles classification-based groups (First Year, Sophomore, Junior, Senior)</li>
            <li>Distinguishes Residential vs Commuter students when SIS provides that data</li>
          </ul>
        }
      />
    </div>
  );
}
