import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  AlertSubscriber,
  AlertSendPreview,
  AlertLogEntry,
} from "../api";

const CATEGORIES = [
  { id: "emergency", label: "Emergency", color: "bg-red-600" },
  { id: "weather", label: "Weather", color: "bg-sky-600" },
  { id: "campus_closing", label: "Campus Closing", color: "bg-amber-600" },
  { id: "parking", label: "Parking", color: "bg-indigo-600" },
  { id: "general", label: "General", color: "bg-gray-600" },
];

type Section = "send" | "history" | "subscribers";

export default function Alerts() {
  const [section, setSection] = useState<Section>("send");

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-navy">Alerts</h2>
        <div className="flex gap-2">
          {([
            { id: "send" as Section, label: "Send Alert" },
            { id: "history" as Section, label: "History" },
            { id: "subscribers" as Section, label: "Subscribers" },
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

      {section === "send" && <SendSection />}
      {section === "history" && <HistorySection />}
      {section === "subscribers" && <SubscribersSection />}
    </div>
  );
}

/* ============================================================
   SECTION A — Send Alert
   ============================================================ */

function SendSection() {
  const [category, setCategory] = useState("emergency");
  const [subject, setSubject] = useState("");
  const [bodyText, setBodyText] = useState("");
  const [bodySms, setBodySms] = useState("");
  const [sendEmail, setSendEmail] = useState(true);
  const [sendSms, setSendSms] = useState(true);
  const [preview, setPreview] = useState<AlertSendPreview | null>(null);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ emails_sent: number; sms_sent: number } | null>(null);
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
            {isEmergency && (
              <p className="text-xs text-red-600 font-medium">
                Emergency override: all subscribers will be contacted
              </p>
            )}
          </div>
        )}

        {result && (
          <div className="border border-green-200 bg-green-50 rounded-lg p-4 text-sm text-green-800">
            Alert sent successfully. {result.emails_sent} emails, {result.sms_sent} SMS delivered.
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
                <span className="font-medium text-sm flex-1 truncate">{e.subject}</span>
                <span className="text-xs text-ink-mute shrink-0">
                  {e.email_count} email, {e.sms_count} SMS
                </span>
                <span className="text-xs text-ink-mute shrink-0">by {e.sent_by}</span>
                <span className="text-xs text-ink-mute">{expandedId === e.id ? "\u25B2" : "\u25BC"}</span>
              </button>

              {expandedId === e.id && (
                <div className="px-4 pb-4 border-t border-gray-100 pt-3 space-y-3">
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
