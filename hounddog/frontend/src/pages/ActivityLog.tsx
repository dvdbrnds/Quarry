import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";
import { Table, Input, Select, Tag, Button, Space, Empty } from "antd";
import type { ColumnsType } from "antd/es/table";

interface AuditEntry {
  id: string; timestamp: string; user_email: string; action: string;
  resource_type: string; resource_id: string | null; endpoint: string;
  summary: string; response_status: number; ip_address: string | null;
  changes: Record<string, any> | null;
}

interface AuditListResponse { items: AuditEntry[]; total: number; page: number; page_size: number; }

const ACTION_COLORS: Record<string, string> = {
  GET: "default", POST: "green", PUT: "blue", PATCH: "gold", DELETE: "red", LOGIN: "geekblue", LOGOUT: "orange",
};

const RESOURCE_TYPES = [
  "tickets", "permits", "lots", "devices", "sync", "violation_types",
  "permit_types", "academic_calendar", "settings", "payments", "auth", "audit",
];

export default function ActivityLog() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filterUser, setFilterUser] = useState("");
  const [filterResource, setFilterResource] = useState("");
  const [filterAction, setFilterAction] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

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
        <Input.Search placeholder="Search actions..." value={search}
          onChange={e => { setSearch(e.target.value); setPage(1); }} style={{ width: 220 }} allowClear />
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
        {(filterUser || filterResource || filterAction || search) && (
          <Button type="link" danger size="small"
            onClick={() => { setFilterUser(""); setFilterResource(""); setFilterAction(""); setSearch(""); setPage(1); }}>
            Clear
          </Button>
        )}
      </Space>

      <Table dataSource={entries} columns={columns} rowKey="id" loading={loading} size="small"
        expandable={{
          expandedRowRender: (entry) => entry.changes ? (
            <div className="text-xs font-mono bg-gray-50 p-3 rounded">
              <h4 className="font-bold mb-2 text-sm font-sans">Changes</h4>
              {Object.entries(entry.changes).map(([field, vals]: [string, any]) => (
                <div key={field} className="flex gap-2 mb-1">
                  <span className="font-medium w-32">{field}:</span>
                  <span className="text-red-500 line-through">{JSON.stringify(vals?.old)}</span>
                  <span>&rarr;</span>
                  <span className="text-green-600">{JSON.stringify(vals?.new)}</span>
                </div>
              ))}
            </div>
          ) : null,
          rowExpandable: (entry) => !!entry.changes,
        }}
        pagination={{
          current: page, total, pageSize: 50, onChange: setPage,
          showSizeChanger: false, showTotal: t => `${t} entries`,
        }}
        locale={{ emptyText: <Empty description="No activity recorded yet" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />
    </div>
  );
}
