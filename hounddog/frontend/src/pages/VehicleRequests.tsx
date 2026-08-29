import { useCallback, useEffect, useState } from "react";
import { Table, Button, Tag, Modal, Input, Space, Empty, App } from "antd";
import type { ColumnsType } from "antd/es/table";
import { CheckOutlined, CloseOutlined } from "@ant-design/icons";
import { authHeaders } from "../auth";

interface VehicleRequest {
  id: string;
  permit_id: string;
  student_sub: string;
  student_email: string;
  student_name: string;
  plate: string;
  plate_state: string;
  reason: string;
  status: string;
  decided_by: string | null;
  decision_note: string | null;
  created_at: string | null;
  decided_at: string | null;
  permit_number: string | null;
  current_plates: string[];
  permit_type: string | null;
}

export default function VehicleRequests() {
  const { message, modal } = App.useApp();
  const [requests, setRequests] = useState<VehicleRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("pending");
  const [denyModalOpen, setDenyModalOpen] = useState(false);
  const [denyTarget, setDenyTarget] = useState<VehicleRequest | null>(null);
  const [denyNote, setDenyNote] = useState("");
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const headers = await authHeaders();
      const url = statusFilter
        ? `/api/admin/vehicle-requests?status=${statusFilter}`
        : "/api/admin/vehicle-requests";
      const res = await fetch(url, { headers });
      if (res.ok) setRequests(await res.json());
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);

  async function handleApprove(req: VehicleRequest) {
    modal.confirm({
      title: "Approve Multi-Vehicle Request",
      content: (
        <div>
          <p>This will add plate <strong>{req.plate}</strong> to {req.student_name}'s permit (#{req.permit_number}).</p>
          <p>Current plates: {req.current_plates.join(", ") || "None"}</p>
        </div>
      ),
      okText: "Approve",
      okType: "primary",
      onOk: async () => {
        setActionLoading(req.id);
        try {
          const headers = await authHeaders();
          const res = await fetch(`/api/admin/vehicle-requests/${req.id}/approve`, {
            method: "POST",
            headers,
          });
          if (res.ok) {
            message.success(`Plate ${req.plate} added to permit`);
            load();
          } else {
            const err = await res.json().catch(() => ({}));
            message.error(err.detail || "Failed to approve");
          }
        } finally {
          setActionLoading(null);
        }
      },
    });
  }

  function handleDeny(req: VehicleRequest) {
    setDenyTarget(req);
    setDenyNote("");
    setDenyModalOpen(true);
  }

  async function confirmDeny() {
    if (!denyTarget) return;
    setActionLoading(denyTarget.id);
    try {
      const headers = await authHeaders();
      const res = await fetch(`/api/admin/vehicle-requests/${denyTarget.id}/deny`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ note: denyNote }),
      });
      if (res.ok) {
        message.success("Request denied");
        setDenyModalOpen(false);
        setDenyTarget(null);
        load();
      } else {
        const err = await res.json().catch(() => ({}));
        message.error(err.detail || "Failed to deny");
      }
    } finally {
      setActionLoading(null);
    }
  }

  const columns: ColumnsType<VehicleRequest> = [
    {
      title: "Student",
      dataIndex: "student_name",
      render: (name, r) => (
        <div>
          <div className="font-medium">{name}</div>
          <div className="text-xs text-gray-500">{r.student_email}</div>
        </div>
      ),
    },
    {
      title: "Permit #",
      dataIndex: "permit_number",
      width: 100,
      render: (num) => <span className="font-mono text-xs">{num || "—"}</span>,
    },
    {
      title: "Current Plate(s)",
      dataIndex: "current_plates",
      width: 130,
      render: (plates: string[]) => <span className="font-mono text-xs">{plates?.join(", ") || "—"}</span>,
    },
    {
      title: "Requested Plate",
      dataIndex: "plate",
      width: 130,
      render: (plate, r) => (
        <span className="font-mono text-xs font-semibold">
          {plate}{r.plate_state ? ` (${r.plate_state})` : ""}
        </span>
      ),
    },
    {
      title: "Reason",
      dataIndex: "reason",
      ellipsis: true,
      render: (reason) => <span className="text-xs">{reason || "—"}</span>,
    },
    {
      title: "Submitted",
      dataIndex: "created_at",
      width: 110,
      render: (d) => d ? new Date(d).toLocaleDateString() : "—",
    },
    {
      title: "Status",
      dataIndex: "status",
      width: 100,
      render: (status) => {
        const colorMap: Record<string, string> = { pending: "gold", approved: "green", denied: "red" };
        return <Tag color={colorMap[status] || "default"}>{status}</Tag>;
      },
    },
    {
      title: "Actions",
      width: 160,
      render: (_, r) => r.status === "pending" ? (
        <Space size="small">
          <Button
            size="small"
            type="primary"
            icon={<CheckOutlined />}
            loading={actionLoading === r.id}
            onClick={() => handleApprove(r)}
          >
            Approve
          </Button>
          <Button
            size="small"
            danger
            icon={<CloseOutlined />}
            loading={actionLoading === r.id}
            onClick={() => handleDeny(r)}
          >
            Deny
          </Button>
        </Space>
      ) : (
        <span className="text-xs text-gray-500">
          {r.decided_by && `by ${r.decided_by.split("@")[0]}`}
        </span>
      ),
    },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold m-0">Multi-Vehicle Requests</h3>
        <Space>
          <Button size="small" type={statusFilter === "pending" ? "primary" : "default"} onClick={() => setStatusFilter("pending")}>Pending</Button>
          <Button size="small" type={statusFilter === "" ? "primary" : "default"} onClick={() => setStatusFilter("")}>All</Button>
          <Button size="small" type={statusFilter === "approved" ? "primary" : "default"} onClick={() => setStatusFilter("approved")}>Approved</Button>
          <Button size="small" type={statusFilter === "denied" ? "primary" : "default"} onClick={() => setStatusFilter("denied")}>Denied</Button>
        </Space>
      </div>

      {requests.length === 0 && !loading ? (
        <Empty description={statusFilter === "pending" ? "No pending requests" : "No requests found"} />
      ) : (
        <Table
          dataSource={requests}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          size="small"
        />
      )}

      <Modal
        title="Deny Vehicle Request"
        open={denyModalOpen}
        onCancel={() => { setDenyModalOpen(false); setDenyTarget(null); }}
        onOk={confirmDeny}
        okText="Deny Request"
        okButtonProps={{ danger: true, loading: actionLoading === denyTarget?.id }}
      >
        {denyTarget && (
          <div className="mb-4">
            <p>Denying request from <strong>{denyTarget.student_name}</strong> for plate <strong>{denyTarget.plate}</strong>.</p>
          </div>
        )}
        <Input.TextArea
          placeholder="Reason for denial (optional, will be shown to student)"
          value={denyNote}
          onChange={e => setDenyNote(e.target.value)}
          rows={3}
          maxLength={500}
        />
      </Modal>
    </div>
  );
}
