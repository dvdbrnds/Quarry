import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

interface Preferences {
  first_name: string;
  phone: string | null;
  sms_opt_in: boolean;
  email_always_on: boolean;
}

const BASE = "/api";

export default function NotificationPreferences() {
  const { token } = useParams<{ token: string }>();
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [phone, setPhone] = useState("");
  const [smsOptIn, setSmsOptIn] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await fetch(`${BASE}/notifications/${token}`);
      if (!res.ok) throw new Error("Link not found or expired.");
      const data: Preferences = await res.json();
      setPrefs(data);
      setPhone(data.phone ?? "");
      setSmsOptIn(data.sms_opt_in);
    } catch (e: any) {
      setError(e.message || "Failed to load preferences.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  async function handleSave() {
    if (!token) return;
    setSaving(true);
    setSaved(false);
    try {
      const res = await fetch(`${BASE}/notifications/${token}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sms_opt_in: smsOptIn, phone: phone || null }),
      });
      if (!res.ok) throw new Error("Save failed.");
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-gray-500">Loading...</p>
      </div>
    );
  }

  if (error || !prefs) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="bg-white rounded-xl shadow-lg p-8 max-w-md text-center">
          <h2 className="text-xl font-bold text-red-600 mb-2">Link Not Found</h2>
          <p className="text-gray-600">{error || "This notification preference link is invalid or has expired."}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-lg p-8 max-w-md w-full">
        <div className="text-center mb-6">
          <div className="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-3">
            <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-5 5v-5zM4 19h6v-2H4v2zM4 15h8v-2H4v2zM4 11h12V9H4v2zM4 7h16V5H4v2z" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-gray-900">Hi {prefs.first_name}</h2>
          <p className="text-gray-600 text-sm mt-1">Manage your parking notification preferences</p>
        </div>

        <div className="space-y-5">
          {/* Email — always on */}
          <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
            <div>
              <div className="font-medium text-sm text-gray-900">Email Notifications</div>
              <div className="text-xs text-gray-500">Lot closures, citations, and updates</div>
            </div>
            <span className="text-xs font-medium bg-green-100 text-green-700 px-2 py-1 rounded-full">
              Always Active
            </span>
          </div>

          {/* Phone number */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Phone Number</label>
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+1 (555) 123-4567"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:outline-none"
            />
            <p className="text-xs text-gray-400 mt-1">Required for SMS notifications</p>
          </div>

          {/* SMS toggle */}
          <div className="flex items-center justify-between p-3 border rounded-lg">
            <div>
              <div className="font-medium text-sm text-gray-900">SMS Notifications</div>
              <div className="text-xs text-gray-500">Receive text messages for lot closures</div>
            </div>
            <button
              onClick={() => setSmsOptIn(!smsOptIn)}
              className={`relative w-12 h-6 rounded-full transition-colors ${
                smsOptIn ? "bg-blue-600" : "bg-gray-300"
              }`}
            >
              <span
                className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                  smsOptIn ? "translate-x-6" : "translate-x-0.5"
                }`}
              />
            </button>
          </div>

          {/* Emergency warning */}
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
            <p className="text-xs text-amber-800">
              <strong>Emergency notifications</strong> (safety alerts, immediate lot closures)
              will always be sent regardless of your preferences.
            </p>
          </div>

          {/* Save */}
          <button
            onClick={handleSave}
            disabled={saving}
            className="w-full py-2.5 bg-blue-600 text-white font-medium rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {saving ? "Saving..." : "Save Preferences"}
          </button>

          {saved && (
            <div className="text-center text-sm text-green-600 font-medium">
              Preferences saved successfully.
            </div>
          )}
        </div>

        <p className="text-center text-xs text-gray-400 mt-6">
          Parking Services — Quarry
        </p>
      </div>
    </div>
  );
}
