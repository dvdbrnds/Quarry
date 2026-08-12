import { useCallback, useEffect, useState } from "react";
import { Card, Switch, App, Spin, Typography } from "antd";
import { authHeaders } from "../auth";

const { Text, Paragraph } = Typography;

interface FeatureFlags {
  vouchers_enabled: boolean;
}

export default function FeatureSettings() {
  const { message } = App.useApp();
  const [flags, setFlags] = useState<FeatureFlags | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/branding/features", { headers: await authHeaders() });
      if (res.ok) setFlags(await res.json());
    } catch {
      message.error("Failed to load feature settings");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => { load(); }, [load]);

  async function updateFlag(key: keyof FeatureFlags, value: boolean) {
    if (!flags) return;
    const next = { ...flags, [key]: value };
    setFlags(next);
    setSaving(true);
    try {
      const res = await fetch("/api/branding/features", {
        method: "PUT",
        headers: { ...(await authHeaders()), "Content-Type": "application/json" },
        body: JSON.stringify(next),
      });
      if (!res.ok) {
        message.error("Failed to save feature settings");
        setFlags(flags);
        return;
      }
      message.success(value ? "Vouchers enabled" : "Vouchers disabled");
      // Reload so branding context / nav picks up the change
      setTimeout(() => window.location.reload(), 400);
    } catch {
      message.error("Failed to save feature settings");
      setFlags(flags);
    } finally {
      setSaving(false);
    }
  }

  if (loading || !flags) {
    return <div className="py-12 text-center"><Spin /></div>;
  }

  return (
    <div className="max-w-2xl">
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
    </div>
  );
}
