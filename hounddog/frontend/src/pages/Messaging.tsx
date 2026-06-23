import { useCallback, useEffect, useState } from "react";
import {
  api,
  MessageTemplate,
  SendMessagePreview,
  PermitNotificationStatus,
  Lot,
} from "../api";

type Section = "templates" | "send" | "preferences";

export default function Messaging() {
  const [section, setSection] = useState<Section>("templates");

  return (
    <div>
      <div className="flex gap-2 mb-6">
        {([
          { id: "templates" as Section, label: "Message Templates" },
          { id: "send" as Section, label: "Send Message" },
          { id: "preferences" as Section, label: "Notification Preferences" },
        ]).map((s) => (
          <button
            key={s.id}
            onClick={() => setSection(s.id)}
            className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
              section === s.id
                ? "bg-navy text-bone"
                : "bg-gray-100 text-ink-mute hover:bg-gray-200"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {section === "templates" && <TemplatesSection />}
      {section === "send" && <SendSection />}
      {section === "preferences" && <PreferencesSection />}
    </div>
  );
}

/* ============================================================
   SECTION A — Message Templates
   ============================================================ */

function TemplatesSection() {
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  const [editing, setEditing] = useState<MessageTemplate | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setTemplates(await api.messaging.templates.list());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">Message Templates</h3>
        <button
          onClick={() => { setCreating(true); setEditing(null); }}
          className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep"
        >
          + Add Template
        </button>
      </div>

      {(creating || editing) && (
        <TemplateForm
          initial={editing ?? undefined}
          onSave={() => { setEditing(null); setCreating(false); load(); }}
          onCancel={() => { setEditing(null); setCreating(false); }}
        />
      )}

      {loading ? (
        <p className="text-ink-mute text-center py-6">Loading...</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-navy text-bone text-left">
            <tr>
              <th className="px-3 py-3 font-medium">Reason</th>
              <th className="px-3 py-3 font-medium">Type</th>
              <th className="px-3 py-3 font-medium">Email Subject</th>
              <th className="px-3 py-3 font-medium">SMS Preview</th>
              <th className="px-3 py-3 font-medium">Active</th>
              <th className="px-3 py-3 font-medium w-28">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {templates.map((t) => (
              <tr key={t.id} className="hover:bg-bone/50">
                <td className="px-3 py-2">
                  {t.reason_label}
                  <span className="ml-1 text-xs text-ink-mute">({t.reason_code})</span>
                </td>
                <td className="px-3 py-2">
                  {t.is_emergency ? (
                    <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-signal-red/15 text-red-700">
                      Emergency
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600">
                      Standard
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 max-w-xs truncate">{t.email_subject}</td>
                <td className="px-3 py-2 max-w-xs truncate text-ink-mute text-xs">{t.sms_body}</td>
                <td className="px-3 py-2">
                  {t.is_active ? (
                    <span className="text-green-600 text-xs font-medium">Active</span>
                  ) : (
                    <span className="text-gray-400 text-xs">Inactive</span>
                  )}
                </td>
                <td className="px-3 py-2 flex gap-2">
                  <button
                    onClick={() => { setEditing(t); setCreating(false); }}
                    className="text-xs text-brass-deep hover:text-brass"
                  >
                    Edit
                  </button>
                  <button
                    onClick={async () => {
                      if (!confirm(`Delete template "${t.reason_label}"?`)) return;
                      await api.messaging.templates.delete(t.id);
                      load();
                    }}
                    className="text-xs text-signal-red hover:text-red-800"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function TemplateForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: MessageTemplate;
  onSave: () => void;
  onCancel: () => void;
}) {
  const [reasonCode, setReasonCode] = useState(initial?.reason_code ?? "");
  const [reasonLabel, setReasonLabel] = useState(initial?.reason_label ?? "");
  const [isEmergency, setIsEmergency] = useState(initial?.is_emergency ?? false);
  const [emailSubject, setEmailSubject] = useState(initial?.email_subject ?? "");
  const [emailBody, setEmailBody] = useState(initial?.email_body ?? "");
  const [smsBody, setSmsBody] = useState(initial?.sms_body ?? "");
  const [isActive, setIsActive] = useState(initial?.is_active ?? true);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const data = { reason_code: reasonCode, reason_label: reasonLabel, is_emergency: isEmergency, email_subject: emailSubject, email_body: emailBody, sms_body: smsBody, is_active: isActive };
      if (initial) {
        await api.messaging.templates.update(initial.id, data);
      } else {
        await api.messaging.templates.create(data);
      }
      onSave();
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow p-6 mb-6 space-y-4">
      <h4 className="font-semibold">{initial ? "Edit Template" : "New Template"}</h4>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Reason Code</label>
          <input value={reasonCode} onChange={(e) => setReasonCode(e.target.value)} required
            disabled={!!initial}
            placeholder="e.g. snow, repaving, event"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm disabled:bg-gray-50" />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Display Label</label>
          <input value={reasonLabel} onChange={(e) => setReasonLabel(e.target.value)} required
            placeholder="e.g. Snow Emergency"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
        </div>
      </div>

      <div className="flex items-center gap-6">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={isEmergency} onChange={(e) => setIsEmergency(e.target.checked)} className="accent-signal-red" />
          <span>Emergency Template</span>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
          <span>Active</span>
        </label>
      </div>

      {isEmergency && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          Emergency templates send SMS to <strong>all</strong> permit holders with a phone number, even those who haven't opted in.
        </div>
      )}

      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Email Subject</label>
        <input value={emailSubject} onChange={(e) => setEmailSubject(e.target.value)}
          placeholder="{school} Parking: {lot_name} Closed"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
      </div>

      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Email Body (HTML)</label>
        <textarea value={emailBody} onChange={(e) => setEmailBody(e.target.value)} rows={6}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono" />
      </div>

      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">
          SMS Body
          <span className={`ml-2 text-xs ${smsBody.length > 160 ? "text-signal-red font-bold" : "text-ink-mute"}`}>
            {smsBody.length}/160
          </span>
        </label>
        <textarea value={smsBody} onChange={(e) => setSmsBody(e.target.value)} rows={3}
          placeholder="{school} Parking: {lot_name} closed..."
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
      </div>

      <p className="text-xs text-ink-mute">
        Available placeholders: <code className="bg-gray-100 px-1 rounded">{"{lot_name}"}</code>{" "}
        <code className="bg-gray-100 px-1 rounded">{"{reason}"}</code>{" "}
        <code className="bg-gray-100 px-1 rounded">{"{closes_at}"}</code>{" "}
        <code className="bg-gray-100 px-1 rounded">{"{reopens_at}"}</code>{" "}
        <code className="bg-gray-100 px-1 rounded">{"{school}"}</code>
      </p>

      <div className="flex gap-2">
        <button type="submit" disabled={saving}
          className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep disabled:opacity-50">
          {saving ? "Saving..." : initial ? "Update" : "Create"}
        </button>
        <button type="button" onClick={onCancel}
          className="px-4 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">
          Cancel
        </button>
      </div>
    </form>
  );
}

/* ============================================================
   SECTION B — Send Message
   ============================================================ */

function SendSection() {
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

  useEffect(() => {
    api.messaging.templates.list().then(setTemplates);
    api.lots.list().then(setLots);
  }, []);

  useEffect(() => {
    if (!selectedTemplateId && !selectedLotId) {
      setPreview(null);
      return;
    }
    api.messaging
      .preview({
        template_id: selectedTemplateId || undefined,
        lot_id: selectedLotId || undefined,
      })
      .then(setPreview);
  }, [selectedTemplateId, selectedLotId]);

  async function handleSend() {
    if (!confirm("Send this message now?")) return;
    setSending(true);
    setResult(null);
    try {
      const r = await api.messaging.send({
        template_id: selectedTemplateId || undefined,
        lot_id: selectedLotId || undefined,
        custom_email_subject: customSubject || undefined,
        custom_sms_body: customSms || undefined,
        send_email: sendEmail,
        send_sms: sendSms,
        extra_emails: extraEmails.split(",").map((e) => e.trim()).filter(Boolean),
        extra_phones: extraPhones.split(",").map((p) => p.trim()).filter(Boolean),
      });
      setResult(r);
    } finally {
      setSending(false);
    }
  }

  const selectedTemplate = templates.find((t) => t.id === selectedTemplateId);

  return (
    <div className="space-y-6">
      <h3 className="text-lg font-semibold">Send Message</h3>

      <div className="bg-white rounded-xl shadow p-6 space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Template</label>
            <select
              value={selectedTemplateId}
              onChange={(e) => setSelectedTemplateId(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            >
              <option value="">— Custom Message —</option>
              {templates.filter((t) => t.is_active).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.reason_label}
                  {t.is_emergency ? " ⚠️" : ""}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Lot</label>
            <select
              value={selectedLotId}
              onChange={(e) => setSelectedLotId(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            >
              <option value="">All Lots</option>
              {lots.map((l) => (
                <option key={l.id} value={l.id}>{l.name}</option>
              ))}
            </select>
          </div>
        </div>

        {!selectedTemplateId && (
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Custom Email Subject</label>
              <input
                value={customSubject}
                onChange={(e) => setCustomSubject(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-mute mb-1">Custom SMS Body</label>
              <textarea
                value={customSms}
                onChange={(e) => setCustomSms(e.target.value)}
                rows={2}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              />
            </div>
          </div>
        )}

        <div className="flex gap-6">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={sendEmail} onChange={(e) => setSendEmail(e.target.checked)} />
            Send via Email
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={sendSms} onChange={(e) => setSendSms(e.target.checked)} />
            Send via SMS
          </label>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Extra Emails (comma-separated)</label>
            <input value={extraEmails} onChange={(e) => setExtraEmails(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Extra Phone Numbers (comma-separated)</label>
            <input value={extraPhones} onChange={(e) => setExtraPhones(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
          </div>
        </div>

        {/* Preview panel */}
        {preview && (
          <div className="border rounded-lg p-4 bg-bone/30 space-y-2">
            <h4 className="font-medium text-sm">Preview</h4>
            {preview.rendered_email_subject && (
              <p className="text-sm"><span className="text-ink-mute">Subject:</span> {preview.rendered_email_subject}</p>
            )}
            {preview.rendered_sms_body && (
              <p className="text-sm"><span className="text-ink-mute">SMS:</span> {preview.rendered_sms_body}</p>
            )}
            <div className="flex gap-4 text-sm text-ink-mute">
              <span>Email: <strong className="text-ink">{preview.email_recipient_count}</strong> permit holders</span>
              {selectedTemplate?.is_emergency ? (
                <span>
                  SMS: <strong className="text-signal-red">ALL {preview.sms_total_with_phone}</strong> with a phone on file (emergency override)
                </span>
              ) : (
                <span>
                  SMS: <strong className="text-ink">{preview.sms_opted_in_count}</strong> opted-in of {preview.sms_total_with_phone}
                </span>
              )}
            </div>
          </div>
        )}

        {result && (
          <div className="border border-green-200 bg-green-50 rounded-lg p-4 text-sm text-green-800">
            Message sent. {result.emails_sent} emails, {result.sms_sent} SMS delivered.
          </div>
        )}

        <button
          onClick={handleSend}
          disabled={sending}
          className="px-6 py-2 bg-navy text-bone font-medium rounded-lg text-sm hover:bg-navy-700 disabled:opacity-50"
        >
          {sending ? "Sending..." : "Send Message"}
        </button>
      </div>
    </div>
  );
}

/* ============================================================
   SECTION C — Notification Preferences Overview
   ============================================================ */

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
      const [prefs, lotList] = await Promise.all([
        api.messaging.preferences(filterLot || undefined),
        api.lots.list(),
      ]);
      setStatuses(prefs);
      setLots(lotList);
    } finally {
      setLoading(false);
    }
  }, [filterLot]);

  useEffect(() => { load(); }, [load]);

  const filtered = statuses.filter((s) => {
    if (filterOptIn === "opted_in" && !s.sms_opt_in) return false;
    if (filterOptIn === "opted_out" && s.sms_opt_in) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        s.name.toLowerCase().includes(q) ||
        (s.email?.toLowerCase().includes(q)) ||
        (s.phone?.includes(q))
      );
    }
    return true;
  });

  const optedIn = statuses.filter((s) => s.sms_opt_in).length;
  const withPhone = statuses.filter((s) => s.phone).length;

  function copyLink(url: string, id: string) {
    navigator.clipboard.writeText(url);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">Notification Preferences</h3>

      <div className="flex gap-4 items-center flex-wrap">
        <div className="flex gap-3 text-sm">
          <span className="bg-signal-green/10 text-green-700 px-3 py-1 rounded-full font-medium">
            {optedIn} opted in to SMS
          </span>
          <span className="bg-gray-100 text-gray-600 px-3 py-1 rounded-full">
            {withPhone} have a phone on file
          </span>
          <span className="text-ink-mute px-3 py-1">
            {statuses.length} total permit holders
          </span>
        </div>
      </div>

      <div className="flex gap-3 items-center">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search name, email, phone..."
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-64"
        />
        <select
          value={filterLot}
          onChange={(e) => setFilterLot(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
        >
          <option value="">All Lots</option>
          {lots.map((l) => (
            <option key={l.id} value={l.name}>{l.name}</option>
          ))}
        </select>
        <select
          value={filterOptIn}
          onChange={(e) => setFilterOptIn(e.target.value as "all" | "opted_in" | "opted_out")}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
        >
          <option value="all">All</option>
          <option value="opted_in">Opted In</option>
          <option value="opted_out">Not Opted In</option>
        </select>
      </div>

      {loading ? (
        <p className="text-ink-mute text-center py-6">Loading...</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-navy text-bone text-left">
            <tr>
              <th className="px-3 py-3 font-medium">Name</th>
              <th className="px-3 py-3 font-medium">Lot</th>
              <th className="px-3 py-3 font-medium">Email</th>
              <th className="px-3 py-3 font-medium">Phone</th>
              <th className="px-3 py-3 font-medium">SMS Opt-In</th>
              <th className="px-3 py-3 font-medium w-28">Preference Link</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.map((s) => (
              <tr key={s.permit_id} className="hover:bg-bone/50">
                <td className="px-3 py-2">{s.name}</td>
                <td className="px-3 py-2">{s.lot_assignment}</td>
                <td className="px-3 py-2 text-xs truncate max-w-[180px]">{s.email || "—"}</td>
                <td className="px-3 py-2 font-mono text-xs">{s.phone || "—"}</td>
                <td className="px-3 py-2">
                  {s.sms_opt_in ? (
                    <span className="text-green-600 text-xs font-medium">Opted In</span>
                  ) : (
                    <span className="text-gray-400 text-xs">No</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  {s.preference_url ? (
                    <button
                      onClick={() => copyLink(s.preference_url, s.permit_id)}
                      className="text-xs text-brass-deep hover:text-brass"
                    >
                      {copiedId === s.permit_id ? "Copied!" : "Copy Link"}
                    </button>
                  ) : (
                    <span className="text-gray-400 text-xs">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
