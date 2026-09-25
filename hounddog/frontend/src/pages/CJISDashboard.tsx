import { useEffect, useState } from "react";
import { Card, Statistic, Row, Col, Spin, Alert, Typography, List, Tag, App, Input, Button, Descriptions, Divider } from "antd";
import { Link } from "react-router-dom";
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

interface LookupResult {
  vehicle?: {
    plate_number: string;
    plate_state: string;
    vin?: string;
    year?: number;
    make?: string;
    model?: string;
    color?: string;
    body_style?: string;
    registration_status?: string;
    registration_expiry?: string;
  };
  owner?: {
    first_name?: string;
    last_name?: string;
    middle_name?: string;
    address_line1?: string;
    city?: string;
    state?: string;
    zip_code?: string;
    date_of_birth?: string;
    drivers_license?: string;
  };
  cjis_notice: string;
}

export default function CJISDashboard() {
  const { message } = App.useApp();
  const [stats, setStats] = useState<Stats | null>(null);
  const [status, setStatus] = useState<JNETStatus | null>(null);
  const [loading, setLoading] = useState(true);

  // Plate lookup state
  const [plate, setPlate] = useState("");
  const [plateState, setPlateState] = useState("PA");
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupResult, setLookupResult] = useState<LookupResult | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);

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

  async function handleLookup() {
    if (!plate.trim()) return;
    setLookupLoading(true);
    setLookupResult(null);
    setLookupError(null);
    try {
      const headers = await authHeaders();
      const res = await fetch("/api/jnet/plate-lookup", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ plate_number: plate.trim(), state: plateState }),
      });
      if (res.ok) {
        setLookupResult(await res.json());
      } else {
        const data = await res.json().catch(() => null);
        setLookupError(data?.detail || `Lookup failed (${res.status})`);
      }
    } catch {
      setLookupError("Network error — could not reach server.");
    } finally {
      setLookupLoading(false);
    }
  }

  function clearResult() {
    setLookupResult(null);
    setLookupError(null);
    setPlate("");
  }

  if (loading) return <Spin size="large" className="block mx-auto mt-24" />;

  return (
    <div>
      <Title level={3}>CJIS Administration</Title>
      <Text type="secondary" className="block mb-4">
        FBI CJIS Security Policy v6.1 — JNET integration management
      </Text>
      <div className="flex gap-2 mb-6 text-sm">
        <Link to="/cjis/audit"><Button size="small">Audit Log</Button></Link>
        <Link to="/cjis/alerts"><Button size="small">Alerts</Button></Link>
        <Link to="/cjis/users"><Button size="small">Users</Button></Link>
        <Link to="/cjis/settings"><Button size="small">Settings</Button></Link>
      </div>

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

      <Card title="JNET Plate Lookup" className="mb-6">
        <div className="flex gap-2 items-end mb-4">
          <div>
            <Text type="secondary" className="block text-xs mb-1">Plate Number</Text>
            <Input
              placeholder="ABC1234"
              value={plate}
              onChange={(e) => setPlate(e.target.value.toUpperCase())}
              onPressEnter={handleLookup}
              style={{ width: 160, fontFamily: "monospace", fontSize: 16 }}
              maxLength={8}
              disabled={lookupLoading}
            />
          </div>
          <div>
            <Text type="secondary" className="block text-xs mb-1">State</Text>
            <Input
              value={plateState}
              onChange={(e) => setPlateState(e.target.value.toUpperCase())}
              style={{ width: 60 }}
              maxLength={2}
              disabled={lookupLoading}
            />
          </div>
          <Button type="primary" onClick={handleLookup} loading={lookupLoading} disabled={!plate.trim()}>
            Look Up
          </Button>
          {(lookupResult || lookupError) && (
            <Button onClick={clearResult}>Clear</Button>
          )}
        </div>

        {lookupError && (
          <Alert type="error" message={lookupError} className="mb-4" />
        )}

        {lookupResult && (
          <div>
            {lookupResult.cjis_notice && (
              <Alert
                type="warning"
                message="CJIS Notice"
                description={lookupResult.cjis_notice}
                className="mb-4"
              />
            )}

            {lookupResult.vehicle && (
              <>
                <Text strong className="block mb-2">Vehicle</Text>
                <Descriptions bordered size="small" column={2} className="mb-4">
                  <Descriptions.Item label="Plate">{lookupResult.vehicle.plate_number} ({lookupResult.vehicle.plate_state})</Descriptions.Item>
                  <Descriptions.Item label="VIN">{lookupResult.vehicle.vin || "—"}</Descriptions.Item>
                  <Descriptions.Item label="Year/Make/Model">
                    {[lookupResult.vehicle.year, lookupResult.vehicle.make, lookupResult.vehicle.model].filter(Boolean).join(" ") || "—"}
                  </Descriptions.Item>
                  <Descriptions.Item label="Color">{lookupResult.vehicle.color || "—"}</Descriptions.Item>
                  <Descriptions.Item label="Registration">{lookupResult.vehicle.registration_status || "—"}</Descriptions.Item>
                  <Descriptions.Item label="Expires">{lookupResult.vehicle.registration_expiry || "—"}</Descriptions.Item>
                </Descriptions>
              </>
            )}

            {lookupResult.owner && (
              <>
                <Text strong className="block mb-2">Registered Owner</Text>
                <Descriptions bordered size="small" column={2}>
                  <Descriptions.Item label="Name">
                    {[lookupResult.owner.first_name, lookupResult.owner.middle_name, lookupResult.owner.last_name].filter(Boolean).join(" ") || "—"}
                  </Descriptions.Item>
                  <Descriptions.Item label="DOB">{lookupResult.owner.date_of_birth || "—"}</Descriptions.Item>
                  <Descriptions.Item label="Address">
                    {lookupResult.owner.address_line1 || "—"}
                  </Descriptions.Item>
                  <Descriptions.Item label="City/State/Zip">
                    {[lookupResult.owner.city, lookupResult.owner.state, lookupResult.owner.zip_code].filter(Boolean).join(", ") || "—"}
                  </Descriptions.Item>
                  <Descriptions.Item label="DL#">{lookupResult.owner.drivers_license || "—"}</Descriptions.Item>
                </Descriptions>
              </>
            )}
          </div>
        )}

        {!lookupResult && !lookupError && (
          <Text type="secondary" className="text-xs">
            Enter a plate number to query JNET. Results are display-only and are not stored.
            {!status?.enabled && " (Currently running in mock mode — results are simulated.)"}
          </Text>
        )}
      </Card>

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
