import { useState } from "react";
import { api } from "../api";

const CATEGORIES = [
  { id: "emergency", label: "Emergency Alerts", description: "Critical safety and security notifications" },
  { id: "weather", label: "Weather Alerts", description: "Severe weather warnings and closures" },
  { id: "campus_closing", label: "Campus Closings", description: "Unplanned campus or building closures" },
  { id: "parking", label: "Parking Notices", description: "Lot closures, snow bans, and enforcement changes" },
  { id: "general", label: "General Notices", description: "Other campus-wide announcements" },
];

export default function AlertSubscribe() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [selectedCats, setSelectedCats] = useState<string[]>(
    CATEGORIES.map((c) => c.id)
  );
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  function toggleCat(cat: string) {
    setSelectedCats((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email && !phone) {
      setError("Please provide at least an email address or phone number.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await api.alerts.subscribe({
        name,
        email: email || undefined,
        phone: phone || undefined,
        categories: selectedCats,
      });
      setSuccess(true);
    } catch (err: any) {
      const msg = err.message || "Something went wrong";
      if (msg.includes("409")) {
        setError("This email is already subscribed.");
      } else {
        setError(msg);
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (success) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-navy to-navy-700 flex items-center justify-center px-4">
        <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-8 text-center space-y-4">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto">
            <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-navy">You're Subscribed</h2>
          <p className="text-ink-mute text-sm">
            You will receive alerts at the contact information you provided.
            Every message includes an unsubscribe link.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-navy to-navy-700 flex items-center justify-center px-4 py-12">
      <div className="bg-white rounded-2xl shadow-xl max-w-lg w-full p-8 space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-navy">Campus Alerts</h1>
          <p className="text-ink-mute text-sm mt-1">
            Subscribe to receive emergency and campus notifications via email and SMS.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-ink mb-1">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              placeholder="Your full name"
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-brass focus:border-brass outline-none"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-ink mb-1">Email Address</label>
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              type="email"
              placeholder="you@example.edu"
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-brass focus:border-brass outline-none"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-ink mb-1">Phone Number (for SMS)</label>
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+1 (555) 123-4567"
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-brass focus:border-brass outline-none"
            />
            <p className="text-xs text-ink-mute mt-1">At least one of email or phone is required.</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-ink mb-2">Alert Categories</label>
            <div className="space-y-2">
              {CATEGORIES.map((c) => (
                <label key={c.id} className="flex items-start gap-3 p-2 rounded-lg hover:bg-gray-50 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedCats.includes(c.id)}
                    onChange={() => toggleCat(c.id)}
                    className="mt-0.5 accent-navy"
                  />
                  <div>
                    <span className="text-sm font-medium">{c.label}</span>
                    <p className="text-xs text-ink-mute">{c.description}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full py-3 bg-navy text-bone font-medium rounded-lg text-sm hover:bg-navy-700 transition-colors disabled:opacity-50"
          >
            {submitting ? "Subscribing..." : "Subscribe to Alerts"}
          </button>

          <p className="text-xs text-ink-mute text-center">
            You can unsubscribe at any time using the link in any alert message.
          </p>
        </form>
      </div>
    </div>
  );
}
