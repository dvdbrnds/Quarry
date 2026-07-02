import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ActiveAlert,
  AlertChannelInfo,
  AlertSubscriber,
  AlertSendPreview,
  AlertSendResult,
  AlertLogEntry,
  SignageScreen,
} from "../api";

const CATEGORIES = [
  { id: "emergency", label: "Emergency", color: "bg-red-600" },
  { id: "weather", label: "Weather", color: "bg-sky-600" },
  { id: "campus_closing", label: "Campus Closing", color: "bg-amber-600" },
  { id: "parking", label: "Parking", color: "bg-indigo-600" },
  { id: "general", label: "General", color: "bg-gray-600" },
];

type Section = "send" | "history" | "subscribers" | "channels" | "signage";

export default function Alerts() {
  const [section, setSection] = useState<Section>("send");
  const [activeAlert, setActiveAlert] = useState<ActiveAlert | null>(null);

  const loadActive = useCallback(async () => {
    try {
      const a = await api.alerts.active();
      setActiveAlert(a);
    } catch {
      setActiveAlert(null);
    }
  }, []);

  useEffect(() => {
    loadActive();
    const iv = setInterval(loadActive, 15_000);
    return () => clearInterval(iv);
  }, [loadActive]);

  async function handleClear() {
    if (!activeAlert) return;
    if (!confirm("Clear this active alert? This will dismiss signage and banner displays.")) return;
    try {
      await api.alerts.clear(activeAlert.id);
      setActiveAlert(null);
    } catch (err: any) {
      alert(`Failed to clear alert: ${err.message}`);
    }
  }

  return (
    <div>
      {activeAlert && (
        <div className={`rounded-xl p-4 mb-6 flex items-center justify-between ${
          activeAlert.category === "emergency" ? "bg-red-600 text-white" : "bg-amber-500 text-white"
        }`}>
          <div>
            <p className="font-bold text-sm uppercase tracking-wide">Active Alert</p>
            <p className="text-lg font-semibold">{activeAlert.subject}</p>
            <p className="text-sm opacity-90">{activeAlert.category.toUpperCase()} &mdash; sent {new Date(activeAlert.sent_at).toLocaleString()}</p>
          </div>
          <button
            onClick={handleClear}
            className="px-4 py-2 bg-white/20 hover:bg-white/30 rounded-lg text-sm font-medium"
          >
            Clear Alert
          </button>
        </div>
      )}

      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-navy">Alerts</h2>
        <div className="flex gap-2">
          {([
            { id: "send" as Section, label: "Send Alert" },
            { id: "history" as Section, label: "History" },
            { id: "subscribers" as Section, label: "Subscribers" },
            { id: "channels" as Section, label: "Channels" },
            { id: "signage" as Section, label: "Signage" },
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
      </div>

      {section === "send" && <SendSection onSent={loadActive} />}
      {section === "history" && <HistorySection />}
      {section === "subscribers" && <SubscribersSection />}
      {section === "channels" && <ChannelsSection />}
      {section === "signage" && <SignageSection />}
    </div>
  );
}

/* ============================================================
   SECTION A — Send Alert
   ============================================================ */

function SendSection({ onSent }: { onSent: () => void }) {
  const [category, setCategory] = useState("emergency");
  const [subject, setSubject] = useState("");
  const [bodyText, setBodyText] = useState("");
  const [bodySms, setBodySms] = useState("");
  const [sendEmail, setSendEmail] = useState(true);
  const [sendSms, setSendSms] = useState(true);
  const [preview, setPreview] = useState<AlertSendPreview | null>(null);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<AlertSendResult | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    api.alerts.preview(category).then(setPreview);
  }, [category]);

  async function handleSend() {
    setConfirmOpen(false);
    setSending(true);
    setResult(null);
    try {
      const r = await api.alerts.send({
        category,
        subject,
        body_text: bodyText,
        body_sms: bodySms,
        send_email: sendEmail,
        send_sms: sendSms,
      });
      setResult(r);
      setSubject("");
      setBodyText("");
      setBodySms("");
      onSent();
    } finally {
      setSending(false);
    }
  }

  const isEmergency = category === "emergency";
  const catInfo = CATEGORIES.find((c) => c.id === category);

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl shadow p-6 space-y-5">
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-2">Alert Category</label>
          <div className="flex gap-2 flex-wrap">
            {CATEGORIES.map((c) => (
              <button
                key={c.id}
                onClick={() => setCategory(c.id)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  category === c.id
                    ? `${c.color} text-white`
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>

        {isEmergency && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
            Emergency alerts are sent to <strong>all subscribers</strong> regardless of their category preferences.
          </div>
        )}

        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Subject</label>
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Alert subject line..."
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Email Body</label>
          <textarea
            value={bodyText}
            onChange={(e) => setBodyText(e.target.value)}
            rows={5}
            placeholder="Full alert message for email..."
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">
            SMS Body
            <span className={`ml-2 text-xs ${bodySms.length > 160 ? "text-red-600 font-bold" : "text-ink-mute"}`}>
              {bodySms.length}/160
            </span>
          </label>
          <textarea
            value={bodySms}
            onChange={(e) => setBodySms(e.target.value)}
            rows={3}
            placeholder="Short message for SMS..."
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
        </div>

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

        {preview && (
          <div className="border rounded-lg p-4 bg-bone/30 space-y-2">
            <h4 className="font-medium text-sm">Recipients Preview</h4>
            <div className="flex gap-6 text-sm text-ink-mute">
              <span>Email: <strong className="text-ink">{preview.email_recipient_count}</strong> subscribers</span>
              <span>SMS: <strong className="text-ink">{preview.sms_recipient_count}</strong> subscribers</span>
              <span className="text-xs">({preview.total_subscribers} total in system)</span>
            </div>
            {preview.configured_channels.length > 0 && (
              <p className="text-xs text-ink-mute">
                Channels: {preview.configured_channels.join(", ")}
              </p>
            )}
            {isEmergency && (
              <p className="text-xs text-red-600 font-medium">
                Emergency override: all subscribers will be contacted
              </p>
            )}
          </div>
        )}

        {result && (
          <div className="border border-green-200 bg-green-50 rounded-lg p-4 text-sm text-green-800 space-y-2">
            <p>Alert sent successfully. {result.emails_sent} emails, {result.sms_sent} SMS delivered.</p>
            {result.channel_results && Object.keys(result.channel_results).length > 0 && (
              <div className="text-xs space-y-1">
                {Object.entries(result.channel_results).map(([ch, r]) => (
                  <div key={ch} className="flex gap-2">
                    <span className="font-medium capitalize">{ch}:</span>
                    <span>{r.sent} sent</span>
                    {r.failed > 0 && <span className="text-red-600">{r.failed} failed</span>}
                    {r.error && <span className="text-red-600">({r.error})</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <button
          onClick={() => setConfirmOpen(true)}
          disabled={sending || !subject}
          className={`px-6 py-3 font-medium rounded-lg text-sm transition-colors disabled:opacity-50 ${
            isEmergency
              ? "bg-red-600 text-white hover:bg-red-700"
              : "bg-navy text-bone hover:bg-navy-700"
          }`}
        >
          {sending ? "Sending..." : isEmergency ? "Send Emergency Alert" : "Send Alert"}
        </button>
      </div>

      {confirmOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl p-6 max-w-md w-full mx-4 space-y-4">
            <h3 className={`text-lg font-bold ${isEmergency ? "text-red-600" : "text-navy"}`}>
              {isEmergency ? "Confirm Emergency Alert" : "Confirm Alert"}
            </h3>
            <div className="text-sm space-y-1">
              <p><strong>Category:</strong> {catInfo?.label}</p>
              <p><strong>Subject:</strong> {subject}</p>
              {preview && (
                <p>
                  <strong>Recipients:</strong>{" "}
                  {sendEmail ? `${preview.email_recipient_count} email` : ""}
                  {sendEmail && sendSms ? ", " : ""}
                  {sendSms ? `${preview.sms_recipient_count} SMS` : ""}
                </p>
              )}
            </div>
            {isEmergency && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
                This will immediately notify all subscribers. This action cannot be undone.
              </div>
            )}
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setConfirmOpen(false)}
                className="px-4 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSend}
                className={`px-4 py-2 font-medium rounded-lg text-sm ${
                  isEmergency
                    ? "bg-red-600 text-white hover:bg-red-700"
                    : "bg-navy text-bone hover:bg-navy-700"
                }`}
              >
                {isEmergency ? "Send Emergency Alert" : "Send Alert"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ============================================================
   SECTION B — Alert History
   ============================================================ */

function HistorySection() {
  const [entries, setEntries] = useState<AlertLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api.alerts.history({ limit: 100 }).then(setEntries).finally(() => setLoading(false));
  }, []);

  function categoryBadge(cat: string) {
    const info = CATEGORIES.find((c) => c.id === cat);
    return (
      <span className={`px-2 py-0.5 rounded-full text-xs font-medium text-white ${info?.color ?? "bg-gray-500"}`}>
        {info?.label ?? cat}
      </span>
    );
  }

  function statusBadge(status: string) {
    if (status === "active") {
      return <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">Active</span>;
    }
    return <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">Cleared</span>;
  }

  return (
    <div>
      <h3 className="text-lg font-semibold mb-4">Alert History</h3>

      {loading ? (
        <p className="text-ink-mute text-center py-6">Loading...</p>
      ) : entries.length === 0 ? (
        <p className="text-ink-mute text-center py-6">No alerts have been sent yet.</p>
      ) : (
        <div className="space-y-2">
          {entries.map((e) => (
            <div key={e.id} className="bg-white rounded-xl shadow">
              <button
                onClick={() => setExpandedId(expandedId === e.id ? null : e.id)}
                className="w-full px-4 py-3 flex items-center gap-4 text-left hover:bg-bone/30 rounded-xl transition-colors"
              >
                <span className="text-xs text-ink-mute w-36 shrink-0">
                  {new Date(e.sent_at).toLocaleString()}
                </span>
                {categoryBadge(e.category)}
                {statusBadge(e.status)}
                <span className="font-medium text-sm flex-1 truncate">{e.subject}</span>
                <span className="text-xs text-ink-mute shrink-0">
                  {e.email_count} email, {e.sms_count} SMS
                </span>
                <span className="text-xs text-ink-mute shrink-0">by {e.sent_by}</span>
                <span className="text-xs text-ink-mute">{expandedId === e.id ? "\u25B2" : "\u25BC"}</span>
              </button>

              {expandedId === e.id && (
                <div className="px-4 pb-4 border-t border-gray-100 pt-3 space-y-3">
                  {e.cleared_at && (
                    <p className="text-xs text-ink-mute">
                      Cleared {new Date(e.cleared_at).toLocaleString()} by {e.cleared_by}
                    </p>
                  )}
                  {e.channel_results && Object.keys(e.channel_results).length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-ink-mute mb-1">Channel Breakdown</p>
                      <div className="flex gap-4 flex-wrap">
                        {Object.entries(e.channel_results).map(([ch, r]) => (
                          <div key={ch} className="bg-bone/30 rounded-lg px-3 py-2 text-xs">
                            <span className="font-medium capitalize">{ch}</span>
                            <span className="ml-2">{r.sent} sent</span>
                            {r.failed > 0 && <span className="ml-1 text-red-600">{r.failed} failed</span>}
                            {r.error && <span className="ml-1 text-red-500 italic">({r.error})</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {e.body_text && (
                    <div>
                      <p className="text-xs font-medium text-ink-mute mb-1">Email Body</p>
                      <div className="bg-bone/30 rounded-lg p-3 text-sm whitespace-pre-wrap">{e.body_text}</div>
                    </div>
                  )}
                  {e.body_sms && (
                    <div>
                      <p className="text-xs font-medium text-ink-mute mb-1">SMS Body</p>
                      <div className="bg-bone/30 rounded-lg p-3 text-sm">{e.body_sms}</div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ============================================================
   SECTION C — Subscribers
   ============================================================ */

function SubscribersSection() {
  const [subscribers, setSubscribers] = useState<AlertSubscriber[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<AlertSubscriber | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSubscribers(
        await api.alerts.subscribers.list({
          search: search || undefined,
          category: filterCategory || undefined,
        })
      );
    } finally {
      setLoading(false);
    }
  }, [search, filterCategory]);

  useEffect(() => { load(); }, [load]);

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const result = await api.alerts.subscribers.importCsv(file);
      alert(`Import complete: ${result.created} created, ${result.skipped} skipped`);
      load();
    } catch (err: any) {
      alert(`Import failed: ${err.message}`);
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleExport() {
    const token = (await import("../auth")).getAccessToken();
    const t = await token;
    const res = await fetch(api.alerts.subscribers.exportUrl, {
      headers: t ? { Authorization: `Bearer ${t}` } : {},
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "alert_subscribers.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  function categoryBadges(cats: string[]) {
    return (
      <div className="flex gap-1 flex-wrap">
        {cats.map((c) => {
          const info = CATEGORIES.find((ci) => ci.id === c);
          return (
            <span key={c} className={`px-1.5 py-0.5 rounded text-[10px] font-medium text-white ${info?.color ?? "bg-gray-400"}`}>
              {info?.label ?? c}
            </span>
          );
        })}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Subscribers</h3>
        <div className="flex gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            onChange={handleImport}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="px-3 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50"
          >
            Import CSV
          </button>
          <button
            onClick={handleExport}
            className="px-3 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50"
          >
            Export CSV
          </button>
          <button
            onClick={() => { setCreating(true); setEditing(null); }}
            className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep"
          >
            + Add Subscriber
          </button>
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
          value={filterCategory}
          onChange={(e) => setFilterCategory(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
        >
          <option value="">All Categories</option>
          {CATEGORIES.map((c) => (
            <option key={c.id} value={c.id}>{c.label}</option>
          ))}
        </select>
        <span className="text-sm text-ink-mute">{subscribers.length} subscribers</span>
      </div>

      {(creating || editing) && (
        <SubscriberForm
          initial={editing ?? undefined}
          onSave={() => { setCreating(false); setEditing(null); load(); }}
          onCancel={() => { setCreating(false); setEditing(null); }}
        />
      )}

      {loading ? (
        <p className="text-ink-mute text-center py-6">Loading...</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-navy text-bone text-left">
            <tr>
              <th className="px-3 py-3 font-medium">Name</th>
              <th className="px-3 py-3 font-medium">Email</th>
              <th className="px-3 py-3 font-medium">Phone</th>
              <th className="px-3 py-3 font-medium">Categories</th>
              <th className="px-3 py-3 font-medium">Source</th>
              <th className="px-3 py-3 font-medium w-28">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {subscribers.map((s) => (
              <tr key={s.id} className="hover:bg-bone/50">
                <td className="px-3 py-2">{s.name}</td>
                <td className="px-3 py-2 text-xs truncate max-w-[200px]">
                  {s.email || "\u2014"}
                  {s.email && !s.email_enabled && (
                    <span className="ml-1 text-[10px] text-red-400">(off)</span>
                  )}
                </td>
                <td className="px-3 py-2 font-mono text-xs">
                  {s.phone || "\u2014"}
                  {s.phone && !s.sms_enabled && (
                    <span className="ml-1 text-[10px] text-red-400">(off)</span>
                  )}
                </td>
                <td className="px-3 py-2">{categoryBadges(s.categories)}</td>
                <td className="px-3 py-2">
                  <span className="text-xs text-ink-mute capitalize">{s.source}</span>
                </td>
                <td className="px-3 py-2 flex gap-2">
                  <button
                    onClick={() => { setEditing(s); setCreating(false); }}
                    className="text-xs text-brass-deep hover:text-brass"
                  >
                    Edit
                  </button>
                  <button
                    onClick={async () => {
                      if (!confirm(`Remove subscriber "${s.name}"?`)) return;
                      await api.alerts.subscribers.delete(s.id);
                      load();
                    }}
                    className="text-xs text-red-600 hover:text-red-800"
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

/* ============================================================
   Subscriber Form (Create / Edit)
   ============================================================ */

function SubscriberForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: AlertSubscriber;
  onSave: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [email, setEmail] = useState(initial?.email ?? "");
  const [phone, setPhone] = useState(initial?.phone ?? "");
  const [smsEnabled, setSmsEnabled] = useState(initial?.sms_enabled ?? true);
  const [emailEnabled, setEmailEnabled] = useState(initial?.email_enabled ?? true);
  const [selectedCats, setSelectedCats] = useState<string[]>(
    initial?.categories ?? ["emergency", "weather", "campus_closing", "parking", "general"]
  );
  const [saving, setSaving] = useState(false);

  function toggleCat(cat: string) {
    setSelectedCats((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const data = {
        name,
        email: email || null,
        phone: phone || null,
        sms_enabled: smsEnabled,
        email_enabled: emailEnabled,
        categories: selectedCats,
      };
      if (initial) {
        await api.alerts.subscribers.update(initial.id, data);
      } else {
        await api.alerts.subscribers.create({ ...data, source: "admin" });
      }
      onSave();
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow p-6 space-y-4">
      <h4 className="font-semibold">{initial ? "Edit Subscriber" : "Add Subscriber"}</h4>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} required
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Email</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} type="email"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Phone</label>
          <input value={phone} onChange={(e) => setPhone(e.target.value)}
            placeholder="+15551234567"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-ink-mute mb-2">Alert Categories</label>
        <div className="flex gap-3 flex-wrap">
          {CATEGORIES.map((c) => (
            <label key={c.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={selectedCats.includes(c.id)}
                onChange={() => toggleCat(c.id)}
              />
              {c.label}
            </label>
          ))}
        </div>
      </div>

      <div className="flex gap-6">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={emailEnabled} onChange={(e) => setEmailEnabled(e.target.checked)} />
          Email notifications enabled
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={smsEnabled} onChange={(e) => setSmsEnabled(e.target.checked)} />
          SMS notifications enabled
        </label>
      </div>

      <div className="flex gap-2">
        <button type="submit" disabled={saving}
          className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep disabled:opacity-50">
          {saving ? "Saving..." : initial ? "Update" : "Add Subscriber"}
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
   SECTION D — Channels
   ============================================================ */

function ChannelsSection() {
  const [channels, setChannels] = useState<AlertChannelInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.alerts.channels().then(setChannels).finally(() => setLoading(false));
  }, []);

  const CHANNEL_LABELS: Record<string, string> = {
    sms: "SMS (Twilio)",
    email: "Email (SMTP)",
    voice: "Voice Calls (Twilio)",
    signage: "Digital Signage",
    banner: "Website Banner",
    teams: "Microsoft Teams",
    crestron: "Crestron Panels",
    pa: "PA System",
    zoom_phone: "Zoom Phone",
  };

  return (
    <div>
      <h3 className="text-lg font-semibold mb-4">Alert Channels</h3>
      <p className="text-sm text-ink-mute mb-4">
        Channels are configured via environment variables. When an alert is sent, all configured channels deliver simultaneously.
      </p>
      {loading ? (
        <p className="text-ink-mute text-center py-6">Loading...</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {channels.map((ch) => (
            <div
              key={ch.name}
              className={`bg-white rounded-xl shadow p-4 border-l-4 ${
                ch.configured ? "border-green-500" : "border-gray-300"
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <h4 className="font-medium text-sm">{CHANNEL_LABELS[ch.name] ?? ch.name}</h4>
                <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                  ch.configured ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
                }`}>
                  {ch.configured ? "Configured" : "Not Configured"}
                </span>
              </div>
              {ch.emergency_only && (
                <p className="text-xs text-red-600 font-medium">Emergency Only</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ============================================================
   SECTION E — Signage
   ============================================================ */

function SignageSection() {
  const [screens, setScreens] = useState<SignageScreen[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingScreen, setEditingScreen] = useState<SignageScreen | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setScreens(await api.signage.screens.list());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Digital Signage Screens</h3>
        <button
          onClick={() => { setShowForm(true); setEditingScreen(null); }}
          className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep"
        >
          + Add Screen
        </button>
      </div>

      {(showForm || editingScreen) && (
        <ScreenForm
          initial={editingScreen ?? undefined}
          onSave={() => { setShowForm(false); setEditingScreen(null); load(); }}
          onCancel={() => { setShowForm(false); setEditingScreen(null); }}
        />
      )}

      {loading ? (
        <p className="text-ink-mute text-center py-6">Loading...</p>
      ) : screens.length === 0 ? (
        <p className="text-ink-mute text-center py-6">No signage screens configured.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {screens.map((s) => (
            <div key={s.id} className="bg-white rounded-xl shadow p-4">
              <div className="flex items-center gap-2 mb-2">
                <span className={`w-2.5 h-2.5 rounded-full ${s.is_online ? "bg-green-500" : "bg-gray-400"}`} />
                <h4 className="font-medium text-sm flex-1">{s.name}</h4>
              </div>
              {s.location && <p className="text-xs text-ink-mute mb-2">{s.location}</p>}
              <p className="text-xs text-ink-mute">
                {s.playlist.length} slide{s.playlist.length !== 1 ? "s" : ""} in playlist
              </p>
              {s.last_seen && (
                <p className="text-xs text-ink-mute mt-1">
                  Last seen: {new Date(s.last_seen).toLocaleString()}
                </p>
              )}
              <div className="flex gap-2 mt-3">
                <button
                  onClick={() => window.open(`/signage/player/${s.id}`, "_blank")}
                  className="text-xs text-brass-deep hover:text-brass"
                >
                  Preview
                </button>
                <button
                  onClick={() => { setEditingScreen(s); setShowForm(false); }}
                  className="text-xs text-brass-deep hover:text-brass"
                >
                  Edit
                </button>
                <button
                  onClick={async () => {
                    if (!confirm(`Delete screen "${s.name}"?`)) return;
                    await api.signage.screens.delete(s.id);
                    load();
                  }}
                  className="text-xs text-red-600 hover:text-red-800"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ScreenForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: SignageScreen;
  onSave: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [location, setLocation] = useState(initial?.location ?? "");
  const [playlist, setPlaylist] = useState<{ type: string; url: string; duration: number }[]>(
    initial?.playlist ?? []
  );
  const [saving, setSaving] = useState(false);

  function addSlide() {
    setPlaylist([...playlist, { type: "image", url: "", duration: 10 }]);
  }

  function updateSlide(idx: number, field: string, value: string | number) {
    const updated = [...playlist];
    (updated[idx] as any)[field] = value;
    setPlaylist(updated);
  }

  function removeSlide(idx: number) {
    setPlaylist(playlist.filter((_, i) => i !== idx));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      if (initial) {
        await api.signage.screens.update(initial.id, { name, location, playlist });
      } else {
        await api.signage.screens.create({ name, location, playlist });
      }
      onSave();
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow p-6 space-y-4">
      <h4 className="font-semibold">{initial ? "Edit Screen" : "Add Screen"}</h4>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} required
            placeholder="HUB Lobby Display"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Location</label>
          <input value={location} onChange={(e) => setLocation(e.target.value)}
            placeholder="HUB 1st Floor"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-xs font-medium text-ink-mute">Playlist</label>
          <button type="button" onClick={addSlide} className="text-xs text-brass-deep hover:text-brass">
            + Add Slide
          </button>
        </div>
        {playlist.length === 0 ? (
          <p className="text-xs text-ink-mute">No slides. Add one above.</p>
        ) : (
          <div className="space-y-2">
            {playlist.map((slide, i) => (
              <div key={i} className="flex gap-2 items-center bg-bone/30 rounded-lg p-2">
                <select
                  value={slide.type}
                  onChange={(e) => updateSlide(i, "type", e.target.value)}
                  className="border border-gray-300 rounded px-2 py-1 text-xs"
                >
                  <option value="image">Image</option>
                  <option value="html">HTML</option>
                  <option value="iframe">IFrame</option>
                </select>
                <input
                  value={slide.url}
                  onChange={(e) => updateSlide(i, "url", e.target.value)}
                  placeholder="URL..."
                  className="flex-1 border border-gray-300 rounded px-2 py-1 text-xs"
                />
                <input
                  type="number"
                  value={slide.duration}
                  onChange={(e) => updateSlide(i, "duration", parseInt(e.target.value) || 10)}
                  min={1}
                  className="w-16 border border-gray-300 rounded px-2 py-1 text-xs"
                />
                <span className="text-xs text-ink-mute">sec</span>
                <button type="button" onClick={() => removeSlide(i)} className="text-xs text-red-600 hover:text-red-800">
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex gap-2">
        <button type="submit" disabled={saving}
          className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep disabled:opacity-50">
          {saving ? "Saving..." : initial ? "Update Screen" : "Add Screen"}
        </button>
        <button type="button" onClick={onCancel}
          className="px-4 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">
          Cancel
        </button>
      </div>
    </form>
  );
}
