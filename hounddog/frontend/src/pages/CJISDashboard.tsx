import { useEffect, useState } from "react";
import { Card, Statistic, Row, Col, Spin, Alert, Typography, List, Tag, App } from "antd";
import { authHeaders } from "../auth";

const { Title, Text } = Typography;

interface Stats {
  queries_today: number;
  queries_this_week: number;
  queries_this_month: number;
  pending_alerts: number;
  officer_counts: { email: string; name: string; count: number }[];
  hourly_distribution: { hour: number; count: number }[];
}

interface JNETStatus {
  enabled: boolean;
  last_successful_query: string | null;
}

export default function CJISDashboard() {
  const { message } = App.useApp();
  const [stats, setStats] = useState<Stats | null>(null);
  const [status, setStatus] = useState<JNETStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const headers = await authHeaders();
        const [statsRes, statusRes] = await Promise.all([
          fetch("/api/cjis/audit/stats", { headers }),
          fetch("/api/jnet/status", { headers }),
        ]);
        if (statsRes.ok) setStats(await statsRes.json());
        if (statusRes.ok) setStatus(await statusRes.json());
      } catch {
        message.error("Failed to load CJIS dashboard data");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) return <Spin size="large" className="block mx-auto mt-24" />;

  return (
    <div>
      <Title level={3}>CJIS Administration</Title>
      <Text type="secondary" className="block mb-6">
        FBI CJIS Security Policy v6.1 — JNET integration management
      </Text>

      {status && !status.enabled && (
        <Alert
          type="warning"
          message="JNET integration is currently disabled"
          description="Set JNET_ENABLED=true in the environment to activate."
          className="mb-6"
          showIcon
        />
      )}

      {status && status.enabled && (
        <Alert
          type="success"
          message="JNET integration is active"
          description={
            status.last_successful_query
              ? `Last successful query: ${new Date(status.last_successful_query).toLocaleString()}`
              : "No queries recorded yet."
          }
          className="mb-6"
          showIcon
        />
      )}

      <Row gutter={[16, 16]} className="mb-6">
        <Col xs={12} sm={6}>
          <Card>
            <Statistic title="Queries Today" value={stats?.queries_today ?? 0} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic title="Queries This Week" value={stats?.queries_this_week ?? 0} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic title="Queries This Month" value={stats?.queries_this_month ?? 0} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title="Pending Alerts"
              value={stats?.pending_alerts ?? 0}
              valueStyle={stats?.pending_alerts ? { color: "#cf1322" } : undefined}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <Card title="Top Officers (Last 30 Days)">
            {stats?.officer_counts?.length ? (
              <List
                dataSource={stats.officer_counts.slice(0, 10)}
                renderItem={(item) => (
                  <List.Item>
                    <List.Item.Meta
                      title={item.name || item.email}
                      description={item.email}
                    />
                    <Tag color="blue">{item.count} queries</Tag>
                  </List.Item>
                )}
              />
            ) : (
              <Text type="secondary">No query data available.</Text>
            )}
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card title="Hourly Distribution (Last 30 Days)">
            {stats?.hourly_distribution?.length ? (
              <div className="space-y-1">
                {stats.hourly_distribution.map((h) => {
                  const max = Math.max(...stats.hourly_distribution.map((x) => x.count), 1);
                  const pct = (h.count / max) * 100;
                  return (
                    <div key={h.hour} className="flex items-center gap-2 text-xs">
                      <span className="w-12 text-right text-slate-500">
                        {h.hour.toString().padStart(2, "0")}:00
                      </span>
                      <div className="flex-1 bg-slate-100 rounded h-4 overflow-hidden">
                        <div
                          className="bg-blue-500 h-full rounded"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="w-8 text-slate-500">{h.count}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <Text type="secondary">No query data available.</Text>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
