import { useEffect, useState } from "react";
import { Card, Switch, Spin, Alert, Typography, Descriptions, Tag, Button, App } from "antd";
import { Link } from "react-router-dom";
import { authHeaders } from "../auth";

const { Title, Text } = Typography;

interface JNETSettingsData {
  jnet_enabled: boolean;
  env_enabled: boolean;
  mock_mode: boolean;
  jnet_base_url_configured: boolean;
  client_cert_configured: boolean;
  ori_configured: boolean;
  authorized_user_count: number;
  status: string;
}

const STATUS_COLORS: Record<string, string> = {
  disabled: "default",
  mock_mode: "orange",
  misconfigured: "red",
  ready: "blue",
  live: "green",
};

const STATUS_LABELS: Record<string, string> = {
  disabled: "Disabled",
  mock_mode: "Mock Mode",
  misconfigured: "Misconfigured",
  ready: "Ready",
  live: "Live",
};

export default function JNETSettings() {
  const { message } = App.useApp();
  const [data, setData] = useState<JNETSettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const headers = await authHeaders();
      const res = await fetch("/api/settings/jnet", { headers });
      if (res.ok) setData(await res.json());
      else message.error("Failed to load JNET settings");
    } catch {
      message.error("Failed to load JNET settings");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function handleToggle(enabled: boolean) {
    setToggling(true);
    try {
      const headers = await authHeaders();
      const res = await fetch("/api/settings/jnet", {
        method: "PUT",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ jnet_enabled: enabled }),
      });
      if (res.ok) {
        message.success(`JNET system ${enabled ? "enabled" : "disabled"}`);
        await load();
      } else {
        message.error("Failed to toggle JNET system");
      }
    } catch {
      message.error("Failed to toggle JNET system");
    } finally {
      setToggling(false);
    }
  }

  if (loading) return <Spin size="large" style={{ display: "block", margin: "80px auto" }} />;
  if (!data) return <Alert type="error" message="Unable to load JNET settings" />;

  return (
    <div style={{ maxWidth: 800 }}>
      <Title level={3}>JNET System Settings</Title>
      <Text type="secondary" style={{ display: "block", marginBottom: 24 }}>
        Control panel for the JNET/CJIS integration. Both the environment variable and this toggle
        must be enabled for JNET to be active.
      </Text>

      <Card title="System Status" style={{ marginBottom: 24 }}>
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="Overall Status">
            <Tag color={STATUS_COLORS[data.status] || "default"}>
              {STATUS_LABELS[data.status] || data.status}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Environment Variable (JNET_ENABLED)">
            <Tag color={data.env_enabled ? "green" : "default"}>
              {data.env_enabled ? "Enabled" : "Disabled"}
            </Tag>
            <Text type="secondary" style={{ marginLeft: 8 }}>Set in Coolify — requires redeploy</Text>
          </Descriptions.Item>
          <Descriptions.Item label="Database Toggle">
            <Switch
              checked={data.jnet_enabled}
              onChange={handleToggle}
              loading={toggling}
              checkedChildren="ON"
              unCheckedChildren="OFF"
            />
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {!data.env_enabled && (
        <Alert
          type="warning"
          message="Environment variable JNET_ENABLED is false"
          description="JNET is fully disabled at the infrastructure level. The database toggle has no effect until JNET_ENABLED=true is set in your deployment environment."
          style={{ marginBottom: 24 }}
        />
      )}

      <Card title="Configuration" style={{ marginBottom: 24 }}>
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="JNET Base URL">
            <Tag color={data.jnet_base_url_configured ? "green" : "orange"}>
              {data.jnet_base_url_configured ? "Configured" : "Not Set (Mock Mode)"}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Client Certificate (mTLS)">
            <Tag color={data.client_cert_configured ? "green" : "red"}>
              {data.client_cert_configured ? "Configured" : "Not Configured"}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="ORI (Originating Agency Identifier)">
            <Tag color={data.ori_configured ? "green" : "red"}>
              {data.ori_configured ? "Configured" : "Not Configured"}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Authorized Users">
            <Text strong>{data.authorized_user_count}</Text>
            <Link to="/cjis/users" style={{ marginLeft: 12 }}>
              <Button type="link" size="small">Manage Users →</Button>
            </Link>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {data.mock_mode && (
        <Alert
          type="info"
          message="Running in Mock Mode"
          description="JNET Base URL is not configured. All lookups return simulated data. This is safe for testing the full flow without real JNET connectivity."
          style={{ marginBottom: 24 }}
        />
      )}
    </div>
  );
}
