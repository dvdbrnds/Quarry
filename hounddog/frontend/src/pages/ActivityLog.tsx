import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";
import { Table, Input, Select, Tag, Button, Space, Empty, Modal, Timeline, Spin, Card } from "antd";
import type { ColumnsType } from "antd/es/table";
import { UserOutlined, ClockCircleOutlined, CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined } from "@ant-design/icons";

interface AuditEntry {
  id: string; timestamp: string; user_email: string; action: string;
  resource_type: string; resource_id: string | null; endpoint: string;
  summary: string; response_status: number; ip_address: string | null;
  changes: Record<string, any> | null;
  request_body: Record<string, any> | null;
}

interface AuditListResponse { items: AuditEntry[]; total: number; page: number; page_size: number; }

const ACTION_COLORS: Record<string, string> = {
  GET: "default", POST: "green", PUT: "blue", PATCH: "gold", DELETE: "red", LOGIN: "geekblue", LOGOUT: "orange",
};

const RESOURCE_TYPES = [
  "tickets", "permits", "lots", "devices", "sync", "violation_types",
  "permit_types", "academic_calendar", "settings", "payments", "auth", "audit",
  "lottery_v2", "backup",
];

function ExpandedDetails({ entry }: { entry: AuditEntry }) {
  const body = entry.request_body;
  const prefs = body?.tier_preference_labels as string[] | undefined;
  const hasChanges = !!entry.changes && Object.keys(entry.changes).length > 0;
  const hasBody = !!body && Object.keys(body).length > 0;

  if (!hasChanges && !hasBody) {
    return <span className="text-xs text-gray-400">No details recorded</span>;
  }

  return (
    <div className="text-xs space-y-3">
      {prefs && prefs.length > 0 && (
        <div className="bg-blue-50 border border-blue-100 rounded p-3">
          <h4 className="font-bold mb-2 text-sm">Permit preferences (ranked)</h4>
          <ol className="m-0 pl-5 space-y-0.5">
            {prefs.map((label, i) => (
              <li key={`${label}-${i}`}>{label}</li>
            ))}
          </ol>
          {body?.campus && (
            <p className="mt-2 mb-0 text-gray-600">Campus: <span className="capitalize">{String(body.campus)}</span></p>
          )}
          {body?.plate && (
            <p className="mt-1 mb-0 text-gray-600">Plate: <span className="font-mono">{String(body.plate)}</span></p>
          )}
        </div>
      )}
      {hasChanges && (
        <div className="font-mono bg-gray-50 p-3 rounded">
          <h4 className="font-bold mb-2 text-sm font-sans">Changes</h4>
          {Object.entries(entry.changes!).map(([field, vals]: [string, any]) => (
            <div key={field} className="flex gap-2 mb-1">
              <span className="font-medium w-32">{field}:</span>
              <span className="text-red-500 line-through">{JSON.stringify(vals?.old)}</span>
              <span>&rarr;</span>
              <span className="text-green-600">{JSON.stringify(vals?.new)}</span>
            </div>
          ))}
        </div>
      )}
      {hasBody && !prefs?.length && (
        <div className="font-mono bg-gray-50 p-3 rounded">
          <h4 className="font-bold mb-2 text-sm font-sans">Request details</h4>
          <pre className="m-0 whitespace-pre-wrap break-all">{JSON.stringify(body, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

export default function ActivityLog() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filterUser, setFilterUser] = useState("");
  const [filterResource, setFilterResource] = useState("");
  const [filterAction, setFilterAction] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  // Student Timeline state
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [timelineEmail, setTimelineEmail] = useState("");
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelineData, setTimelineData] = useState<any | null>(null);

  async function loadTimeline(email?: string) {
    const target = (email || timelineEmail).trim();
    if (!target) return;
    setTimelineLoading(true);
    setTimelineData(null);
    try {
      const res = await fetch(`/api/audit/student-summary/${encodeURIComponent(target)}`, {
        headers: await authHeaders(),
      });
      if (res.ok) {
        setTimelineData(await res.json());
      }
    } finally {
      setTimelineLoading(false);
    }
  }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      qs.set("page", String(page));
      qs.set("page_size", "50");
      if (filterUser) qs.set("user_email", filterUser);
      if (filterResource) qs.set("resource_type", filterResource);
      if (filterAction) qs.set("action", filterAction);
      if (search) qs.set("search", search);
      const res = await fetch(`/api/audit?${qs}`, { headers: await authHeaders() });
      if (res.ok) {
        const data: AuditListResponse = await res.json();
        setEntries(data.items);
        setTotal(data.total);
      }
    } finally { setLoading(false); }
  }, [page, filterUser, filterResource, filterAction, search]);

  useEffect(() => { load(); }, [load]);

  const columns: ColumnsType<AuditEntry> = [
    { title: "Time", dataIndex: "timestamp", key: "timestamp", width: 160, render: (d) => new Date(d).toLocaleString() },
    { title: "User", dataIndex: "user_email", key: "user_email", ellipsis: true },
    { title: "Action", dataIndex: "action", key: "action", render: (a) => <Tag color={ACTION_COLORS[a] || "default"}>{a}</Tag> },
    {
      title: "Resource", key: "resource", render: (_, e) => (
        <span className="capitalize text-xs">
          {e.resource_type.replace(/_/g, " ")}
          {e.resource_id && <span className="text-ink-mute ml-1">#{e.resource_id.slice(0, 8)}</span>}
        </span>
      ),
    },
    { title: "Summary", dataIndex: "summary", key: "summary", ellipsis: true },
    {
      title: "Status", dataIndex: "response_status", key: "status", width: 70,
      render: (s) => <Tag color={s < 300 ? "green" : s < 500 ? "gold" : "red"}>{s}</Tag>,
    },
  ];

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Activity Log</h2>
      <Space className="mb-4" wrap>
        <Input.Search placeholder="Search email, action, endpoint…" value={search}
          onChange={e => { setSearch(e.target.value); setPage(1); }} style={{ width: 260 }} allowClear />
        <Input placeholder="Filter by email" value={filterUser}
          onChange={e => { setFilterUser(e.target.value); setPage(1); }} style={{ width: 180 }} allowClear />
        <Select value={filterResource || undefined} onChange={v => { setFilterResource(v || ""); setPage(1); }}
          placeholder="All Resources" allowClear style={{ width: 160 }}
          options={RESOURCE_TYPES.map(r => ({ label: r.replace(/_/g, " "), value: r }))} />
        <Select value={filterAction || undefined} onChange={v => { setFilterAction(v || ""); setPage(1); }}
          placeholder="All Actions" allowClear style={{ width: 130 }}
          options={[
            { label: "Login", value: "LOGIN" }, { label: "Logout", value: "LOGOUT" },
            { label: "View", value: "GET" }, { label: "Create", value: "POST" },
            { label: "Update", value: "PUT" }, { label: "Patch", value: "PATCH" },
            { label: "Delete", value: "DELETE" },
          ]} />
        <Button
          size="small"
          onClick={() => { setSearch("Started lottery payment"); setFilterAction("POST"); setPage(1); }}
        >
          Payment started
        </Button>
        <Button
          type="primary"
          size="small"
          icon={<UserOutlined />}
          onClick={() => {
            setTimelineEmail(filterUser || "");
            setTimelineOpen(true);
            if (filterUser) loadTimeline(filterUser);
          }}
        >
          Student Timeline
        </Button>
        {filterUser && (
          <Button
            size="small"
            type="dashed"
            onClick={() => {
              setTimelineEmail(filterUser);
              setTimelineOpen(true);
              loadTimeline(filterUser);
            }}
          >
            Summarize {filterUser}
          </Button>
        )}
        {(filterUser || filterResource || filterAction || search) && (
          <Button type="link" danger size="small"
            onClick={() => { setFilterUser(""); setFilterResource(""); setFilterAction(""); setSearch(""); setPage(1); }}>
            Clear
          </Button>
        )}
      </Space>

      <Modal
        title={<span><UserOutlined className="mr-2" />Student Activity Timeline</span>}
        open={timelineOpen}
        onCancel={() => { setTimelineOpen(false); setTimelineData(null); }}
        footer={null}
        width={700}
        styles={{ body: { maxHeight: "70vh", overflowY: "auto" } }}
      >
        <div className="mb-4">
          <Input.Search
            placeholder="Enter student email (e.g. smithj@moravian.edu)"
            value={timelineEmail}
            onChange={(e) => setTimelineEmail(e.target.value)}
            onSearch={() => loadTimeline()}
            enterButton="Load Timeline"
            loading={timelineLoading}
            size="large"
          />
        </div>

        {timelineLoading && (
          <div className="text-center py-8">
            <Spin size="large" />
            <p className="mt-2 text-gray-500">Loading student activity...</p>
          </div>
        )}

        {timelineData && !timelineLoading && (
          <div className="space-y-4">
            {/* Verdict Card */}
            <Card
              size="small"
              className={`border-l-4 ${
                timelineData.verdict.color === "green" ? "border-l-green-500 bg-green-50" :
                timelineData.verdict.color === "orange" ? "border-l-orange-500 bg-orange-50" :
                timelineData.verdict.color === "blue" ? "border-l-blue-500 bg-blue-50" :
                "border-l-red-500 bg-red-50"
              }`}
            >
              <h4 className="font-bold text-sm mb-1">Payment Verdict</h4>
              <p className="m-0 text-sm">{timelineData.verdict.summary}</p>
            </Card>

            <p className="text-xs text-gray-500">{timelineData.total_events} meaningful events found</p>

            {/* Timeline */}
            <Timeline
              items={timelineData.events.map((ev: any, i: number) => ({
                key: i,
                color: ev.success ? (ev.type === "payment" || ev.label.includes("paid") || ev.label.includes("Paid") ? "green" : "blue") : "red",
                dot: ev.success
                  ? (ev.type === "payment" || ev.label.includes("paid") ? <CheckCircleOutlined /> : <ClockCircleOutlined />)
                  : (ev.label.includes("expired") ? <ExclamationCircleOutlined /> : <CloseCircleOutlined />),
                children: (
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm">{ev.label}</span>
                      {!ev.success && ev.status_code > 0 && (
                        <Tag color="red" className="text-[10px]">{ev.status_code}</Tag>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 m-0">{ev.detail}</p>
                    <p className="text-[10px] text-gray-400 m-0">
                      {new Date(ev.timestamp).toLocaleString("en-US", {
                        month: "short", day: "numeric", year: "numeric",
                        hour: "numeric", minute: "2-digit",
                      })}
                    </p>
                  </div>
                ),
              }))}
            />

            {timelineData.events.length === 0 && (
              <Empty description="No activity found for this email" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </div>
        )}
      </Modal>

      <Table dataSource={entries} columns={columns} rowKey="id" loading={loading} size="small"
        expandable={{
          expandedRowRender: (entry) => <ExpandedDetails entry={entry} />,
          rowExpandable: (entry) =>
            !!(entry.changes && Object.keys(entry.changes).length) ||
            !!(entry.request_body && Object.keys(entry.request_body).length),
        }}
        pagination={{
          current: page, total, pageSize: 50, onChange: setPage,
          showSizeChanger: false, showTotal: t => `${t} entries`,
        }}
        locale={{ emptyText: <Empty description="No activity recorded" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />
    </div>
  );
}
