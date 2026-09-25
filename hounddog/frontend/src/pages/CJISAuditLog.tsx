import { useEffect, useState, useCallback } from "react";
import { Table, Input, DatePicker, Select, Button, Space, Typography, App } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { authHeaders } from "../auth";

const { Title } = Typography;
const { RangePicker } = DatePicker;

interface AuditEntry {
  id: string;
  timestamp: string;
  user_email: string;
  user_full_name: string;
  action: string;
  query_plate: string;
  query_state: string;
  ori: string;
  source_ip: string;
  device_id: string | null;
  success: boolean;
  error_message: string | null;
  response_time_ms: number;
}

export default function CJISAuditLog() {
  const { message } = App.useApp();
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [filterEmail, setFilterEmail] = useState("");
  const [filterPlate, setFilterPlate] = useState("");
  const [filterSuccess, setFilterSuccess] = useState<string | undefined>(undefined);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const headers = await authHeaders();
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (filterEmail) params.set("user_email", filterEmail);
      if (filterPlate) params.set("plate", filterPlate);
      if (filterSuccess === "true") params.set("success", "true");
      if (filterSuccess === "false") params.set("success", "false");
      if (dateRange?.[0]) params.set("date_from", dateRange[0].toISOString());
      if (dateRange?.[1]) params.set("date_to", dateRange[1].toISOString());

      const res = await fetch(`/api/cjis/audit/logs?${params}`, { headers });
      if (!res.ok) throw new Error();
      const data = await res.json();
      setItems(data.items);
      setTotal(data.total);
    } catch {
      message.error("Failed to load audit logs");
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, filterEmail, filterPlate, filterSuccess, dateRange]);

  useEffect(() => { load(); }, [load]);

  async function handleExport() {
    try {
      const headers = await authHeaders();
      const params = new URLSearchParams();
      if (dateRange?.[0]) params.set("date_from", dateRange[0].toISOString());
      if (dateRange?.[1]) params.set("date_to", dateRange[1].toISOString());
      const res = await fetch(`/api/cjis/audit/logs/export?${params}`, { headers });
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "cjis_audit_log.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      message.error("Failed to export audit logs");
    }
  }

  const columns: ColumnsType<AuditEntry> = [
    {
      title: "Timestamp",
      dataIndex: "timestamp",
      width: 180,
      render: (v: string) => v ? new Date(v).toLocaleString() : "",
    },
    { title: "Officer", dataIndex: "user_full_name", width: 160 },
    { title: "Email", dataIndex: "user_email", width: 200 },
    { title: "Plate", dataIndex: "query_plate", width: 100 },
    { title: "State", dataIndex: "query_state", width: 60 },
    { title: "Action", dataIndex: "action", width: 120 },
    {
      title: "Success",
      dataIndex: "success",
      width: 80,
      render: (v: boolean) => (
        <span className={v ? "text-green-600" : "text-red-600"}>
          {v ? "Yes" : "No"}
        </span>
      ),
    },
    {
      title: "Time (ms)",
      dataIndex: "response_time_ms",
      width: 90,
      align: "right",
    },
    { title: "Source IP", dataIndex: "source_ip", width: 130 },
    { title: "Error", dataIndex: "error_message", ellipsis: true },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <Title level={3} className="!mb-0">CJIS Audit Log</Title>
        <Button icon={<DownloadOutlined />} onClick={handleExport}>
          Export CSV
        </Button>
      </div>

      <Space wrap className="mb-4">
        <Input
          placeholder="Filter by officer email"
          value={filterEmail}
          onChange={(e) => { setFilterEmail(e.target.value); setPage(1); }}
          allowClear
          style={{ width: 220 }}
        />
        <Input
          placeholder="Filter by plate"
          value={filterPlate}
          onChange={(e) => { setFilterPlate(e.target.value.toUpperCase()); setPage(1); }}
          allowClear
          style={{ width: 140 }}
        />
        <Select
          placeholder="Success"
          value={filterSuccess}
          onChange={(v) => { setFilterSuccess(v); setPage(1); }}
          allowClear
          style={{ width: 120 }}
          options={[
            { label: "Success", value: "true" },
            { label: "Failed", value: "false" },
          ]}
        />
        <RangePicker
          onChange={(dates) => {
            setDateRange(dates as [dayjs.Dayjs | null, dayjs.Dayjs | null] | null);
            setPage(1);
          }}
        />
      </Space>

      <Table
        dataSource={items}
        columns={columns}
        rowKey="id"
        loading={loading}
        size="small"
        scroll={{ x: 1200 }}
        pagination={{
          current: page,
          pageSize,
          total,
          onChange: setPage,
          showTotal: (t) => `${t} entries`,
        }}
      />
    </div>
  );
}
