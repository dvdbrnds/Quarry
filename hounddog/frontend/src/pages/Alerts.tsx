import { useCallback, useEffect, useRef, useState } from "react";
import {
  api, ActiveAlert, AlertChannelInfo, AlertSubscriber, AlertSendPreview,
  AlertSendResult, AlertTestSendResult, AlertLogEntry, SignageScreen,
} from "../api";
import {
  Tabs, Table, Button, Input, Select, Checkbox, Tag, Card, Form, Alert, Space, App, Spin, Empty, Modal, Segmented,
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
  sms: "QUARRY_TWILIO_ACCOUNT_SID, QUARRY_TWILIO_AUTH_TOKEN, QUARRY_TWILIO_FROM_NUMBER",
  email: "QUARRY_SMTP_HOST, QUARRY_SMTP_FROM_ADDRESS", voice: "Same as SMS (Twilio)",
  signage: "Always on", banner: "Always on", teams: "QUARRY_TEAMS_WEBHOOK_URL",
  extron: "QUARRY_EXTRON_ROOM_AGENT_URL", pa: "QUARRY_QSYS_CORE_HOST",
  zoom_phone: "QUARRY_ZOOM_ACCOUNT_ID, QUARRY_ZOOM_CLIENT_ID, ...",
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
        { key: "history", label: "History", children: <HistorySection /> },
        { key: "subscribers", label: "Subscribers", children: <SubscribersSection /> },
        { key: "channels", label: "Channels", children: <ChannelsSection /> },
        { key: "test", label: "Test", children: <TestConsole /> },
        { key: "signage", label: "Signage", children: <SignageSection /> },
      ]} />
    </div>
  );
}

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

  useEffect(() => { api.alerts.preview(category).then(setPreview); }, [category]);

  const isEmergency = category === "emergency";

  function handleSend() {
    const catInfo = CATEGORIES.find(c => c.id === category);
    modal.confirm({
      title: isEmergency ? "Confirm Emergency Alert" : "Confirm Alert",
      content: (
        <div className="text-sm space-y-1">
          <p><strong>Category:</strong> {catInfo?.label}</p>
          <p><strong>Subject:</strong> {subject}</p>
          {preview && <p><strong>Recipients:</strong> {sendEmail ? `${preview.email_recipient_count} email` : ""}{sendEmail && sendSms ? ", " : ""}{sendSms ? `${preview.sms_recipient_count} SMS` : ""}</p>}
          {isEmergency && <p className="text-red-600 font-medium">This will immediately notify all subscribers.</p>}
        </div>
      ),
      okText: isEmergency ? "Send Emergency Alert" : "Send Alert",
      okButtonProps: isEmergency ? { danger: true } : {},
      onOk: async () => {
        setSending(true); setResult(null);
        try {
          const r = await api.alerts.send({ category, subject, body_text: bodyText, body_sms: bodySms, send_email: sendEmail, send_sms: sendSms });
          setResult(r); setSubject(""); setBodyText(""); setBodySms(""); onSent();
          message.success(`Alert sent: ${r.emails_sent} emails, ${r.sms_sent} SMS`);
        } catch { message.error("Failed to send alert"); } finally { setSending(false); }
      },
    });
  }

  return (
    <Card>
      <div className="space-y-5">
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-2">Alert Category</label>
          <Segmented value={category} onChange={v => setCategory(v as string)}
            options={CATEGORIES.map(c => ({ label: c.label, value: c.id }))} />
        </div>
        {isEmergency && <Alert type="error" showIcon message="Emergency alerts are sent to all subscribers regardless of category preferences." />}
        <div><label className="block text-xs font-medium text-ink-mute mb-1">Subject</label><Input value={subject} onChange={e => setSubject(e.target.value)} placeholder="Alert subject line..." /></div>
        <div><label className="block text-xs font-medium text-ink-mute mb-1">Email Body</label><Input.TextArea value={bodyText} onChange={e => setBodyText(e.target.value)} rows={5} /></div>
        <div><label className="block text-xs font-medium text-ink-mute mb-1">SMS Body <span className={`ml-2 text-xs ${bodySms.length > 160 ? "text-red-600 font-bold" : "text-ink-mute"}`}>{bodySms.length}/160</span></label><Input.TextArea value={bodySms} onChange={e => setBodySms(e.target.value)} rows={3} /></div>
        <Space><Checkbox checked={sendEmail} onChange={e => setSendEmail(e.target.checked)}>Send via Email</Checkbox><Checkbox checked={sendSms} onChange={e => setSendSms(e.target.checked)}>Send via SMS</Checkbox></Space>
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
        <Button type="primary" danger={isEmergency} onClick={handleSend} disabled={!subject} loading={sending}>
          {isEmergency ? "Send Emergency Alert" : "Send Alert"}
        </Button>
      </div>
    </Card>
  );
}

function HistorySection() {
  const [entries, setEntries] = useState<AlertLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [includeTests, setIncludeTests] = useState(false);

  useEffect(() => {
    setLoading(true);
    api.alerts.history({ limit: 100, include_tests: includeTests }).then(setEntries).finally(() => setLoading(false));
  }, [includeTests]);

  const columns: ColumnsType<AlertLogEntry> = [
    { title: "Time", dataIndex: "sent_at", key: "time", width: 160, render: d => new Date(d).toLocaleString() },
    { title: "Category", dataIndex: "category", key: "cat", render: c => <Tag color={CATEGORIES.find(ci => ci.id === c)?.color}>{CATEGORIES.find(ci => ci.id === c)?.label ?? c}</Tag> },
    { title: "Status", dataIndex: "status", key: "status", render: s => <Tag color={s === "active" ? "red" : s === "test" ? "blue" : "default"}>{s}</Tag> },
    { title: "Subject", dataIndex: "subject", key: "subject", ellipsis: true },
    { title: "Delivery", key: "delivery", render: (_, e) => `${e.email_count} email, ${e.sms_count} SMS` },
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
    </div>
  );
}

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
