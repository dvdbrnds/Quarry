import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Card, Input, Button, Switch, Tag, Result, Spin, Alert, App } from "antd";
import { useBranding } from "../useBranding";

interface Preferences { first_name: string; phone: string | null; sms_opt_in: boolean; email_always_on: boolean; }

export default function NotificationPreferences() {
  const { message } = App.useApp();
  const brand = useBranding();
  const { token } = useParams<{ token: string }>();
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [phone, setPhone] = useState("");
  const [smsOptIn, setSmsOptIn] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/notifications/${token}`);
      if (!res.ok) throw new Error("Link not found or expired.");
      const data: Preferences = await res.json();
      setPrefs(data); setPhone(data.phone ?? ""); setSmsOptIn(data.sms_opt_in);
    } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  async function handleSave() {
    if (!token) return;
    setSaving(true);
    try {
      const res = await fetch(`/api/notifications/${token}`, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sms_opt_in: smsOptIn, phone: phone || null }) });
      if (!res.ok) throw new Error("Save failed.");
      message.success("Preferences saved");
    } catch (e: any) { message.error(e.message); } finally { setSaving(false); }
  }

  if (loading) return <div className="min-h-screen bg-gray-50 flex items-center justify-center"><Spin size="large" /></div>;
  if (error || !prefs) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <Card className="max-w-md"><Result status="error" title="Link Not Found" subTitle={error || "Invalid or expired."} /></Card>
    </div>
  );

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <Card className="max-w-md w-full">
        <div className="text-center mb-6">
          <h2 className="text-xl font-bold">Hi {prefs.first_name}</h2>
          <p className="text-ink-mute text-sm mt-1">Manage your parking notification preferences</p>
        </div>
        <div className="space-y-5">
          <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
            <div><div className="font-medium text-sm">Email Notifications</div><div className="text-xs text-ink-mute">Lot closures, citations, and updates</div></div>
            <Tag color="green">Always Active</Tag>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Phone Number</label>
            <Input type="tel" value={phone} onChange={e => setPhone(e.target.value)} placeholder="+1 (555) 123-4567" />
            <p className="text-xs text-ink-mute mt-1">Required for SMS notifications</p>
          </div>
          <div className="flex items-center justify-between p-3 border rounded-lg">
            <div><div className="font-medium text-sm">SMS Notifications</div><div className="text-xs text-ink-mute">Receive text messages for lot closures</div></div>
            <Switch checked={smsOptIn} onChange={setSmsOptIn} />
          </div>
          <Alert type="warning" message="Emergency notifications will always be sent regardless of preferences." />
          <Button type="primary" block onClick={handleSave} loading={saving}>Save Preferences</Button>
        </div>
        <p className="text-center text-xs text-ink-mute mt-6">{brand.departmentName} — {brand.brandName}</p>
      </Card>
    </div>
  );
}
