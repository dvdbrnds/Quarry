import { useCallback, useEffect, useRef, useState } from "react";
import {
  api, MessageTemplate, SendMessagePreview, PermitNotificationStatus, Lot,
} from "../api";
import {
  Tabs, Table, Button, Input, Select, Checkbox, Tag, Card, Form, Alert, Space, App, Spin, Empty,
} from "antd";
import ReactQuill from "react-quill-new";
import "react-quill-new/dist/quill.snow.css";
import type { ColumnsType } from "antd/es/table";

export default function Messaging() {
  return (
    <Tabs items={[
      { key: "templates", label: "Message Templates", children: <TemplatesSection /> },
      { key: "send", label: "Send Message", children: <SendSection /> },
      { key: "preferences", label: "Notification Preferences", children: <PreferencesSection /> },
    ]} />
  );
}

function TemplatesSection() {
  const { modal, message } = App.useApp();
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  const [editing, setEditing] = useState<MessageTemplate | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try { setTemplates(await api.messaging.templates.list()); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  function handleDelete(t: MessageTemplate) {
    modal.confirm({
      title: `Delete template "${t.reason_label}"?`, okText: "Delete", okButtonProps: { danger: true },
      onOk: async () => { await api.messaging.templates.delete(t.id); message.success("Template deleted"); load(); },
    });
  }

  const columns: ColumnsType<MessageTemplate> = [
    { title: "Reason", key: "reason", render: (_, t) => <>{t.reason_label} <span className="text-xs text-ink-mute">({t.reason_code})</span></> },
    { title: "Type", key: "type", render: (_, t) => <Tag color={t.is_emergency ? "red" : "default"}>{t.is_emergency ? "Emergency" : "Standard"}</Tag> },
    { title: "Email Subject", dataIndex: "email_subject", key: "subject", ellipsis: true },
    { title: "SMS Preview", dataIndex: "sms_body", key: "sms", ellipsis: true, render: (v) => <span className="text-xs text-ink-mute">{v}</span> },
    { title: "Active", dataIndex: "is_active", key: "active", render: (v) => <Tag color={v ? "green" : "default"}>{v ? "Active" : "Inactive"}</Tag> },
    {
      title: "Actions", key: "actions", width: 120,
      render: (_, t) => (
        <Space>
          <Button type="link" size="small" onClick={() => { setEditing(t); setCreating(false); }}>Edit</Button>
          <Button type="link" size="small" danger onClick={() => handleDelete(t)}>Delete</Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">Message Templates</h3>
        <Button type="primary" onClick={() => { setCreating(true); setEditing(null); }}>+ Add Template</Button>
      </div>
      {(creating || editing) && (
        <TemplateForm initial={editing ?? undefined}
          onSave={() => { setEditing(null); setCreating(false); load(); }}
          onCancel={() => { setEditing(null); setCreating(false); }} />
      )}
      <Table dataSource={templates} columns={columns} rowKey="id" loading={loading} size="small" pagination={false} />
    </div>
  );
}

const QUILL_MODULES = {
  toolbar: [
    [{ header: [1, 2, 3, false] }],
    ["bold", "italic", "underline"],
    [{ color: [] }, { background: [] }],
    [{ align: [] }],
    [{ list: "ordered" }, { list: "bullet" }],
    ["link"],
    ["clean"],
  ],
};

function EmailBodyEditor({ value, onChange }: { value?: string; onChange?: (v: string) => void }) {
  const quillRef = useRef<ReactQuill>(null);

  function handleInsertPlaceholder(placeholder: string) {
    const editor = quillRef.current?.getEditor();
    if (!editor) return;
    const range = editor.getSelection(true);
    editor.insertText(range.index, placeholder);
    editor.setSelection(range.index + placeholder.length, 0);
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-1">
        <span className="text-xs text-ink-mute mr-1 self-center">Insert:</span>
        {["{lot_name}", "{reason}", "{closes_at}", "{reopens_at}", "{school}", "{department}"].map(p => (
          <Button key={p} size="small" type="dashed" className="!text-xs !px-2 !h-6"
            onClick={() => handleInsertPlaceholder(p)}>{p}</Button>
        ))}
      </div>
      <ReactQuill
        ref={quillRef}
        theme="snow"
        value={value || ""}
        onChange={(content) => onChange?.(content)}
        modules={QUILL_MODULES}
        style={{ minHeight: 200 }}
      />
    </div>
  );
}

function TemplateForm({ initial, onSave, onCancel }: { initial?: MessageTemplate; onSave: () => void; onCancel: () => void }) {
  const { message: msg } = App.useApp();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const smsBody = Form.useWatch("sms_body", form) ?? "";

  useEffect(() => {
    if (initial) form.setFieldsValue(initial);
    else form.resetFields();
  }, [initial, form]);

  async function handleFinish(values: any) {
    setSaving(true);
    try {
      if (initial) await api.messaging.templates.update(initial.id, values);
      else await api.messaging.templates.create(values);
      msg.success(initial ? "Template updated" : "Template created");
      onSave();
    } catch { msg.error("Failed to save template"); }
    finally { setSaving(false); }
  }

  return (
    <Card className="mb-6" title={initial ? "Edit Template" : "New Template"}>
      <Form form={form} layout="vertical" onFinish={handleFinish}
        initialValues={{ is_active: true, is_emergency: false }}>
        <div className="grid grid-cols-2 gap-x-4">
          <Form.Item name="reason_code" label="Reason Code" rules={[{ required: true }]}>
            <Input placeholder="e.g. snow, repaving" disabled={!!initial} />
          </Form.Item>
          <Form.Item name="reason_label" label="Display Label" rules={[{ required: true }]}>
            <Input placeholder="e.g. Snow Emergency" />
          </Form.Item>
        </div>
        <Space className="mb-4">
          <Form.Item name="is_emergency" valuePropName="checked" noStyle>
            <Checkbox>Emergency Template</Checkbox>
          </Form.Item>
          <Form.Item name="is_active" valuePropName="checked" noStyle>
            <Checkbox>Active</Checkbox>
          </Form.Item>
        </Space>
        <Form.Item name="email_subject" label="Email Subject">
          <Input placeholder="{school} Parking: {lot_name} Closed" />
        </Form.Item>
        <Form.Item name="email_body" label="Email Body">
          <EmailBodyEditor />
        </Form.Item>
        <Form.Item name="sms_body" label={<>SMS Body <span className={`ml-2 text-xs ${smsBody.length > 160 ? "text-red-600 font-bold" : "text-ink-mute"}`}>{smsBody.length}/160</span></>}>
          <Input.TextArea rows={3} placeholder="{school} Parking: {lot_name} closed..." />
        </Form.Item>
        <Space>
          <Button onClick={onCancel}>Cancel</Button>
          <Button type="primary" htmlType="submit" loading={saving}>{initial ? "Update" : "Create"}</Button>
        </Space>
      </Form>
    </Card>
  );
}

function SendSection() {
  const { modal, message: msg } = App.useApp();
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  const [lots, setLots] = useState<Lot[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [selectedLotId, setSelectedLotId] = useState("");
  const [sendEmail, setSendEmail] = useState(true);
  const [sendSms, setSendSms] = useState(true);
  const [extraEmails, setExtraEmails] = useState("");
  const [extraPhones, setExtraPhones] = useState("");
  const [customSubject, setCustomSubject] = useState("");
  const [customSms, setCustomSms] = useState("");
  const [preview, setPreview] = useState<SendMessagePreview | null>(null);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ emails_sent: number; sms_sent: number } | null>(null);

  useEffect(() => { api.messaging.templates.list().then(setTemplates); api.lots.list().then(setLots); }, []);
  useEffect(() => {
    if (!selectedTemplateId && !selectedLotId) { setPreview(null); return; }
    api.messaging.preview({ template_id: selectedTemplateId || undefined, lot_id: selectedLotId || undefined }).then(setPreview);
  }, [selectedTemplateId, selectedLotId]);

  const selectedTemplate = templates.find(t => t.id === selectedTemplateId);

  function handleSend() {
    modal.confirm({
      title: "Send this message now?",
      onOk: async () => {
        setSending(true); setResult(null);
        try {
          const r = await api.messaging.send({
            template_id: selectedTemplateId || undefined, lot_id: selectedLotId || undefined,
            custom_email_subject: customSubject || undefined, custom_sms_body: customSms || undefined,
            send_email: sendEmail, send_sms: sendSms,
            extra_emails: extraEmails.split(",").map(e => e.trim()).filter(Boolean),
            extra_phones: extraPhones.split(",").map(p => p.trim()).filter(Boolean),
          });
          setResult(r); msg.success(`Sent: ${r.emails_sent} emails, ${r.sms_sent} SMS`);
        } catch { msg.error("Failed to send"); } finally { setSending(false); }
      },
    });
  }

  return (
    <div className="space-y-6">
      <h3 className="text-lg font-semibold">Send Message</h3>
      <Card>
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Template</label>
            <Select value={selectedTemplateId || undefined} onChange={v => setSelectedTemplateId(v || "")}
              placeholder="— Custom Message —" allowClear className="w-full"
              options={templates.filter(t => t.is_active).map(t => ({ label: `${t.reason_label}${t.is_emergency ? " (Emergency)" : ""}`, value: t.id }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Lot</label>
            <Select value={selectedLotId || undefined} onChange={v => setSelectedLotId(v || "")}
              placeholder="All Lots" allowClear className="w-full"
              options={lots.map(l => ({ label: l.name, value: l.id }))} />
          </div>
        </div>
        {!selectedTemplateId && (
          <div className="space-y-3 mb-4">
            <div><label className="block text-xs font-medium text-ink-mute mb-1">Custom Email Subject</label><Input value={customSubject} onChange={e => setCustomSubject(e.target.value)} /></div>
            <div><label className="block text-xs font-medium text-ink-mute mb-1">Custom SMS Body</label><Input.TextArea value={customSms} onChange={e => setCustomSms(e.target.value)} rows={2} /></div>
          </div>
        )}
        <Space className="mb-4">
          <Checkbox checked={sendEmail} onChange={e => setSendEmail(e.target.checked)}>Send via Email</Checkbox>
          <Checkbox checked={sendSms} onChange={e => setSendSms(e.target.checked)}>Send via SMS</Checkbox>
        </Space>
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Extra Emails</label><Input value={extraEmails} onChange={e => setExtraEmails(e.target.value)} /></div>
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Extra Phone Numbers</label><Input value={extraPhones} onChange={e => setExtraPhones(e.target.value)} /></div>
        </div>
        {preview && (
          <div className="border rounded-lg p-4 bg-bone/30 space-y-2 mb-4">
            <h4 className="font-medium text-sm">Preview</h4>
            {preview.rendered_email_subject && <p className="text-sm"><span className="text-ink-mute">Subject:</span> {preview.rendered_email_subject}</p>}
            {preview.rendered_sms_body && <p className="text-sm"><span className="text-ink-mute">SMS:</span> {preview.rendered_sms_body}</p>}
            <div className="flex gap-4 text-sm text-ink-mute">
              <span>Email: <strong className="text-ink">{preview.email_recipient_count}</strong> permit holders</span>
              {selectedTemplate?.is_emergency
                ? <span>SMS: <strong className="text-red-600">ALL {preview.sms_total_with_phone}</strong> (emergency override)</span>
                : <span>SMS: <strong className="text-ink">{preview.sms_opted_in_count}</strong> opted-in of {preview.sms_total_with_phone}</span>}
            </div>
          </div>
        )}
        {result && <Alert className="mb-4" type="success" showIcon message={`Message sent. ${result.emails_sent} emails, ${result.sms_sent} SMS delivered.`} />}
        <Button type="primary" onClick={handleSend} loading={sending}>Send Message</Button>
      </Card>
    </div>
  );
}

function PreferencesSection() {
  const [statuses, setStatuses] = useState<PermitNotificationStatus[]>([]);
  const [lots, setLots] = useState<Lot[]>([]);
  const [filterLot, setFilterLot] = useState("");
  const [filterOptIn, setFilterOptIn] = useState<"all" | "opted_in" | "opted_out">("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [prefs, lotList] = await Promise.all([api.messaging.preferences(filterLot || undefined), api.lots.list()]);
      setStatuses(prefs); setLots(lotList);
    } finally { setLoading(false); }
  }, [filterLot]);

  useEffect(() => { load(); }, [load]);

  const filtered = statuses.filter(s => {
    if (filterOptIn === "opted_in" && !s.sms_opt_in) return false;
    if (filterOptIn === "opted_out" && s.sms_opt_in) return false;
    if (search) { const q = search.toLowerCase(); return s.name.toLowerCase().includes(q) || s.email?.toLowerCase().includes(q) || s.phone?.includes(q); }
    return true;
  });

  const optedIn = statuses.filter(s => s.sms_opt_in).length;
  const withPhone = statuses.filter(s => s.phone).length;

  function copyLink(url: string, id: string) { navigator.clipboard.writeText(url); setCopiedId(id); setTimeout(() => setCopiedId(null), 2000); }

  const columns: ColumnsType<PermitNotificationStatus> = [
    { title: "Name", dataIndex: "name", key: "name" },
    { title: "Lot", dataIndex: "lot_assignment", key: "lot" },
    { title: "Email", dataIndex: "email", key: "email", ellipsis: true, render: v => v || "—" },
    { title: "Phone", dataIndex: "phone", key: "phone", render: v => v ? <span className="font-mono text-xs">{v}</span> : "—" },
    { title: "SMS Opt-In", dataIndex: "sms_opt_in", key: "sms", render: v => <Tag color={v ? "green" : "default"}>{v ? "Opted In" : "No"}</Tag> },
    {
      title: "Preference Link", key: "link",
      render: (_, s) => s.preference_url
        ? <Button type="link" size="small" onClick={() => copyLink(s.preference_url, s.permit_id)}>{copiedId === s.permit_id ? "Copied!" : "Copy Link"}</Button>
        : <span className="text-gray-400 text-xs">—</span>,
    },
  ];

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">Notification Preferences</h3>
      <Space wrap>
        <Tag color="green">{optedIn} opted in to SMS</Tag>
        <Tag>{withPhone} have a phone on file</Tag>
        <span className="text-ink-mute text-sm">{statuses.length} total</span>
      </Space>
      <Space wrap>
        <Input.Search value={search} onChange={e => setSearch(e.target.value)} placeholder="Search name, email, phone..." style={{ width: 260 }} allowClear />
        <Select value={filterLot || undefined} onChange={v => setFilterLot(v || "")} placeholder="All Lots" allowClear style={{ width: 140 }}
          options={lots.map(l => ({ label: l.name, value: l.name }))} />
        <Select value={filterOptIn} onChange={v => setFilterOptIn(v)} style={{ width: 130 }}
          options={[{ label: "All", value: "all" }, { label: "Opted In", value: "opted_in" }, { label: "Not Opted In", value: "opted_out" }]} />
      </Space>
      <Table dataSource={filtered} columns={columns} rowKey="permit_id" loading={loading} size="small" pagination={{ defaultPageSize: 50, showSizeChanger: true, showTotal: t => `${t} holders` }} />
    </div>
  );
}
