import { useCallback, useEffect, useState } from "react";
import { Card, Switch, App, Spin, Typography, Input, Button } from "antd";
import { authHeaders } from "../auth";

const { Text, Paragraph } = Typography;

interface FeatureFlags {
  vouchers_enabled: boolean;
  vehicle_request_notify_email: string;
}

export default function FeatureSettings() {
  const { message } = App.useApp();
  const [flags, setFlags] = useState<FeatureFlags | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notifyEmail, setNotifyEmail] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/branding/features", { headers: await authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setFlags(data);
        setNotifyEmail(data.vehicle_request_notify_email || "");
      }
    } catch {
      message.error("Failed to load feature settings");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => { load(); }, [load]);

  async function saveFlags(next: FeatureFlags, successMsg?: string) {
    const prev = flags;
    setFlags(next);
    setSaving(true);
    try {
      const res = await fetch("/api/branding/features", {
        method: "PUT",
        headers: { ...(await authHeaders()), "Content-Type": "application/json" },
        body: JSON.stringify(next),
      });
      if (!res.ok) {
        message.error("Failed to save");
        setFlags(prev);
        return;
      }
      if (successMsg) message.success(successMsg);
    } catch {
      message.error("Failed to save");
      setFlags(prev);
    } finally {
      setSaving(false);
    }
  }

  async function updateFlag(key: keyof FeatureFlags, value: boolean) {
    if (!flags) return;
    const next = { ...flags, [key]: value };
    await saveFlags(next, value ? "Vouchers enabled" : "Vouchers disabled");
    setTimeout(() => window.location.reload(), 400);
  }

  async function saveNotifyEmail() {
    if (!flags) return;
    const next = { ...flags, vehicle_request_notify_email: notifyEmail.trim() };
    await saveFlags(next, "Notification email saved");
  }

  if (loading || !flags) {
    return <div className="py-12 text-center"><Spin /></div>;
  }

  return (
    <div className="max-w-2xl space-y-4">
      <Card title="Modules">
        <div className="flex items-start justify-between gap-6">
          <div>
            <Text strong>Vouchers</Text>
            <Paragraph type="secondary" className="mb-0 mt-1">
              Turn off for schools that do not use department voucher codes.
              Hides the Permits → Vouchers tab and blocks voucher application at checkout.
              Department chargebacks remain available under Finance.
            </Paragraph>
          </div>
          <Switch
            checked={flags.vouchers_enabled}
            loading={saving}
            onChange={(v) => updateFlag("vouchers_enabled", v)}
          />
        </div>
      </Card>

      <Card title="Notifications">
        <div>
          <Text strong>Vehicle Request Approver Email</Text>
          <Paragraph type="secondary" className="mb-2 mt-1">
            Multi-vehicle requests from commuter students will be sent to this email
            with a one-click approve/deny link. Typically the chief or parking director.
          </Paragraph>
          <div className="flex gap-2">
            <Input
              placeholder="chief@moravian.edu"
              value={notifyEmail}
              onChange={e => setNotifyEmail(e.target.value)}
              onPressEnter={saveNotifyEmail}
              style={{ maxWidth: 320 }}
            />
            <Button
              type="primary"
              loading={saving}
              onClick={saveNotifyEmail}
            >
              Save
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
