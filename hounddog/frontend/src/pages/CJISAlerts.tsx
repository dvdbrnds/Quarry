import { useEffect, useState, useCallback } from "react";
import { Table, Button, Select, Space, Typography, Tag, Modal, Input, App } from "antd";
import type { ColumnsType } from "antd/es/table";
import { authHeaders } from "../auth";

const { Title, Text } = Typography;

interface AlertEntry {
  id: string;
  audit_log_id: string | null;
  alert_type: string;
  description: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  dismissed: boolean;
  dismiss_reason: string | null;
  created_at: string;
}

const ALERT_TYPE_COLORS: Record<string, string> = {
  repeated_plate_query: "orange",
  off_hours_query: "purple",
  outside_network_query: "red",
  volume_anomaly: "volcano",
};

export default function CJISAlerts() {
  const { message } = App.useApp();
  const [items, setItems] = useState<AlertEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [filterType, setFilterType] = useState<string | undefined>(undefined);
  const [filterStatus, setFilterStatus] = useState<string | undefined>("pending");
  const [lastReview, setLastReview] = useState<string | null>(null);

  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [reviewingAlert, setReviewingAlert] = useState<AlertEntry | null>(null);
  const [dismissReason, setDismissReason] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const headers = await authHeaders();
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (filterType) params.set("alert_type", filterType);
      if (filterStatus) params.set("status", filterStatus);

      const res = await fetch(`/api/cjis/audit/alerts?${params}`, { headers });
      if (!res.ok) throw new Error();
      const data = await res.json();
      setItems(data.items);
      setTotal(data.total);
      setLastReview(data.last_full_review);
    } catch {
      message.error("Failed to load alerts");
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, filterType, filterStatus]);

  useEffect(() => { load(); }, [load]);

  async function handleReview(dismissed: boolean) {
    if (!reviewingAlert) return;
    try {
      const headers = await authHeaders();
      const res = await fetch(`/api/cjis/audit/alerts/${reviewingAlert.id}/review`, {
        method: "POST",
        headers,
        body: JSON.stringify({ dismissed, dismiss_reason: dismissed ? dismissReason : null }),
      });
      if (!res.ok) throw new Error();
      message.success(dismissed ? "Alert dismissed" : "Alert marked reviewed");
      setReviewModalOpen(false);
      setReviewingAlert(null);
      setDismissReason("");
      load();
    } catch {
      message.error("Failed to update alert");
    }
  }

  const columns: ColumnsType<AlertEntry> = [
    {
      title: "Date",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString() : "",
    },
    {
      title: "Type",
      dataIndex: "alert_type",
      width: 170,
      render: (v: string) => (
        <Tag color={ALERT_TYPE_COLORS[v] || "default"}>
          {v.replace(/_/g, " ")}
        </Tag>
      ),
    },
    {
      title: "Description",
      dataIndex: "description",
      ellipsis: true,
    },
    {
      title: "Status",
      width: 110,
      render: (_: unknown, row: AlertEntry) => {
        if (row.dismissed) return <Tag color="default">Dismissed</Tag>;
        if (row.reviewed_at) return <Tag color="green">Reviewed</Tag>;
        return <Tag color="red">Pending</Tag>;
      },
    },
    {
      title: "Reviewed By",
      dataIndex: "reviewed_by",
      width: 180,
    },
    {
      title: "Actions",
      width: 120,
      render: (_: unknown, row: AlertEntry) => {
        if (row.reviewed_at || row.dismissed) return null;
        return (
          <Button
            size="small"
            type="primary"
            onClick={() => {
              setReviewingAlert(row);
              setReviewModalOpen(true);
            }}
          >
            Review
          </Button>
        );
      },
    },
  ];

  return (
    <div>
      <Title level={3}>CJIS Anomaly Alerts</Title>

      <div className="mb-4 p-3 bg-slate-50 rounded border text-sm">
        <strong>Weekly review status:</strong>{" "}
        {lastReview ? (
          <>Last full review: {new Date(lastReview).toLocaleString()}</>
        ) : (
          <Text type="danger">No reviews on record. CJIS policy requires weekly alert review.</Text>
        )}
        {" | "}{total} total alert{total !== 1 ? "s" : ""}
        {filterStatus === "pending" && ` (${total} pending)`}
      </div>

      <Space wrap className="mb-4">
        <Select
          placeholder="Alert type"
          value={filterType}
          onChange={(v) => { setFilterType(v); setPage(1); }}
          allowClear
          style={{ width: 200 }}
          options={[
            { label: "Repeated Plate Query", value: "repeated_plate_query" },
            { label: "Off-Hours Query", value: "off_hours_query" },
            { label: "Outside Network", value: "outside_network_query" },
            { label: "Volume Anomaly", value: "volume_anomaly" },
          ]}
        />
        <Select
          placeholder="Status"
          value={filterStatus}
          onChange={(v) => { setFilterStatus(v); setPage(1); }}
          allowClear
          style={{ width: 140 }}
          options={[
            { label: "Pending", value: "pending" },
            { label: "Reviewed", value: "reviewed" },
            { label: "Dismissed", value: "dismissed" },
          ]}
        />
      </Space>

      <Table
        dataSource={items}
        columns={columns}
        rowKey="id"
        loading={loading}
        size="small"
        scroll={{ x: 900 }}
        pagination={{
          current: page,
          pageSize,
          total,
          onChange: setPage,
          showTotal: (t) => `${t} alerts`,
        }}
      />

      <Modal
        title="Review Alert"
        open={reviewModalOpen}
        onCancel={() => { setReviewModalOpen(false); setReviewingAlert(null); }}
        footer={null}
      >
        {reviewingAlert && (
          <div>
            <Tag color={ALERT_TYPE_COLORS[reviewingAlert.alert_type] || "default"} className="mb-2">
              {reviewingAlert.alert_type.replace(/_/g, " ")}
            </Tag>
            <p className="mb-4">{reviewingAlert.description}</p>

            <Space>
              <Button type="primary" onClick={() => handleReview(false)}>
                Mark Reviewed
              </Button>
              <Button
                danger
                onClick={() => {
                  if (!dismissReason.trim()) {
                    message.warning("A dismiss reason is required");
                    return;
                  }
                  handleReview(true);
                }}
              >
                Dismiss
              </Button>
            </Space>
            <Input.TextArea
              placeholder="Dismiss reason (required to dismiss)"
              value={dismissReason}
              onChange={(e) => setDismissReason(e.target.value)}
              className="mt-3"
              rows={3}
            />
          </div>
        )}
      </Modal>
    </div>
  );
}
