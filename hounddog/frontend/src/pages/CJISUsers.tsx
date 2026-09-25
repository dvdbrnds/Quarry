import { useEffect, useState, useCallback } from "react";
import { Table, Button, Tag, Typography, Modal, Input, Select, DatePicker, Space, Tabs, App } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { authHeaders } from "../auth";

const { Title } = Typography;

interface JNETUser {
  id: string;
  okta_sub: string;
  email: string;
  full_name: string;
  role: string;
  jnet_authorized: boolean;
  jnet_authorized_by_email: string | null;
  jnet_authorized_at: string | null;
  jnet_background_check_date: string | null;
  jnet_training_completed_at: string | null;
  jnet_last_activity: string | null;
  jnet_last_access_review: string | null;
}

interface AccessReviewUser {
  id: string;
  email: string;
  full_name: string;
  role: string;
  jnet_last_access_review: string | null;
  jnet_last_activity: string | null;
}

export default function CJISUsers() {
  const { message, modal } = App.useApp();
  const [users, setUsers] = useState<JNETUser[]>([]);
  const [reviewDue, setReviewDue] = useState<AccessReviewUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [newOktaSub, setNewOktaSub] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newName, setNewName] = useState("");
  const [newRole, setNewRole] = useState("jnet_officer");

  const [dateModalOpen, setDateModalOpen] = useState(false);
  const [dateModalType, setDateModalType] = useState<"background_check" | "training">("background_check");
  const [dateModalUser, setDateModalUser] = useState<JNETUser | null>(null);
  const [dateValue, setDateValue] = useState<dayjs.Dayjs | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const headers = await authHeaders();
      const [usersRes, reviewRes] = await Promise.all([
        fetch("/api/cjis/users", { headers }),
        fetch("/api/cjis/users/access-review", { headers }),
      ]);
      if (usersRes.ok) setUsers((await usersRes.json()).items);
      if (reviewRes.ok) setReviewDue((await reviewRes.json()).items);
    } catch {
      message.error("Failed to load CJIS users");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleCreate() {
    if (!newOktaSub.trim() || !newEmail.trim()) {
      message.warning("Okta Sub and Email are required");
      return;
    }
    try {
      const headers = await authHeaders();
      const res = await fetch("/api/cjis/users/create", {
        method: "POST",
        headers,
        body: JSON.stringify({
          okta_sub: newOktaSub.trim(),
          email: newEmail.trim(),
          full_name: newName.trim(),
          role: newRole,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Failed");
      }
      message.success("JNET user created");
      setCreateModalOpen(false);
      setNewOktaSub(""); setNewEmail(""); setNewName(""); setNewRole("jnet_officer");
      load();
    } catch (e: any) {
      message.error(e.message || "Failed to create user");
    }
  }

  async function handleAuthorize(userId: string) {
    try {
      const headers = await authHeaders();
      const res = await fetch(`/api/cjis/users/${userId}/authorize`, { method: "POST", headers });
      if (!res.ok) throw new Error();
      message.success("Access granted");
      load();
    } catch { message.error("Failed to authorize user"); }
  }

  async function handleRevoke(userId: string) {
    modal.confirm({
      title: "Revoke JNET Access",
      content: "This will immediately revoke the user's access to JNET lookups.",
      okText: "Revoke",
      okType: "danger",
      onOk: async () => {
        try {
          const headers = await authHeaders();
          const res = await fetch(`/api/cjis/users/${userId}/revoke`, { method: "POST", headers });
          if (!res.ok) throw new Error();
          message.success("Access revoked");
          load();
        } catch { message.error("Failed to revoke access"); }
      },
    });
  }

  async function handleDateSave() {
    if (!dateModalUser || !dateValue) return;
    const endpoint = dateModalType === "background_check"
      ? `/api/cjis/users/${dateModalUser.id}/background-check`
      : `/api/cjis/users/${dateModalUser.id}/training`;
    try {
      const headers = await authHeaders();
      const res = await fetch(endpoint, {
        method: "PUT",
        headers,
        body: JSON.stringify({ date: dateValue.toISOString() }),
      });
      if (!res.ok) throw new Error();
      message.success("Date recorded");
      setDateModalOpen(false);
      setDateModalUser(null);
      setDateValue(null);
      load();
    } catch {
      message.error("Failed to record date");
    }
  }

  function trainingStatus(user: JNETUser): { label: string; color: string } {
    if (!user.jnet_training_completed_at) return { label: "Not Completed", color: "default" };
    const dt = dayjs(user.jnet_training_completed_at);
    const daysAgo = dayjs().diff(dt, "day");
    if (daysAgo > 365) return { label: "Expired", color: "red" };
    if (daysAgo > 335) return { label: "Expiring Soon", color: "orange" };
    return { label: "Current", color: "green" };
  }

  const columns: ColumnsType<JNETUser> = [
    { title: "Name", dataIndex: "full_name", width: 160 },
    { title: "Email", dataIndex: "email", width: 220 },
    {
      title: "Role",
      dataIndex: "role",
      width: 120,
      render: (v: string) => <Tag color={v === "cjis_admin" ? "purple" : "blue"}>{v}</Tag>,
    },
    {
      title: "Authorized",
      dataIndex: "jnet_authorized",
      width: 100,
      render: (v: boolean) => v ? <Tag color="green">Yes</Tag> : <Tag color="red">No</Tag>,
    },
    {
      title: "Background Check",
      dataIndex: "jnet_background_check_date",
      width: 140,
      render: (v: string | null) => v ? dayjs(v).format("YYYY-MM-DD") : <Tag color="default">None</Tag>,
    },
    {
      title: "Training",
      width: 130,
      render: (_: unknown, row: JNETUser) => {
        const s = trainingStatus(row);
        return (
          <Tag color={s.color}>
            {s.label}
            {row.jnet_training_completed_at && ` (${dayjs(row.jnet_training_completed_at).format("MM/DD/YY")})`}
          </Tag>
        );
      },
    },
    {
      title: "Last Query",
      dataIndex: "jnet_last_activity",
      width: 140,
      render: (v: string | null) => v ? dayjs(v).format("MM/DD/YY HH:mm") : "Never",
    },
    {
      title: "Actions",
      width: 240,
      render: (_: unknown, row: JNETUser) => (
        <Space size="small" wrap>
          {!row.jnet_authorized && (
            <Button size="small" type="primary" onClick={() => handleAuthorize(row.id)}>
              Authorize
            </Button>
          )}
          {row.jnet_authorized && (
            <Button size="small" danger onClick={() => handleRevoke(row.id)}>
              Revoke
            </Button>
          )}
          <Button
            size="small"
            onClick={() => {
              setDateModalType("background_check");
              setDateModalUser(row);
              setDateValue(row.jnet_background_check_date ? dayjs(row.jnet_background_check_date) : null);
              setDateModalOpen(true);
            }}
          >
            BG Check
          </Button>
          <Button
            size="small"
            onClick={() => {
              setDateModalType("training");
              setDateModalUser(row);
              setDateValue(row.jnet_training_completed_at ? dayjs(row.jnet_training_completed_at) : null);
              setDateModalOpen(true);
            }}
          >
            Training
          </Button>
        </Space>
      ),
    },
  ];

  const reviewColumns: ColumnsType<AccessReviewUser> = [
    { title: "Name", dataIndex: "full_name", width: 160 },
    { title: "Email", dataIndex: "email", width: 220 },
    { title: "Role", dataIndex: "role", width: 120 },
    {
      title: "Last Review",
      dataIndex: "jnet_last_access_review",
      render: (v: string | null) => v ? dayjs(v).format("YYYY-MM-DD") : "Never",
    },
    {
      title: "Last Activity",
      dataIndex: "jnet_last_activity",
      render: (v: string | null) => v ? dayjs(v).format("YYYY-MM-DD") : "Never",
    },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <Title level={3} className="!mb-0">JNET User Management</Title>
        <Button type="primary" onClick={() => setCreateModalOpen(true)}>
          Add JNET User
        </Button>
      </div>

      <Tabs
        defaultActiveKey="users"
        items={[
          {
            key: "users",
            label: `All Users (${users.length})`,
            children: (
              <Table
                dataSource={users}
                columns={columns}
                rowKey="id"
                loading={loading}
                size="small"
                scroll={{ x: 1300 }}
                pagination={false}
              />
            ),
          },
          {
            key: "review",
            label: (
              <span>
                Access Review
                {reviewDue.length > 0 && (
                  <Tag color="red" className="ml-2">{reviewDue.length} due</Tag>
                )}
              </span>
            ),
            children: (
              <Table
                dataSource={reviewDue}
                columns={reviewColumns}
                rowKey="id"
                loading={loading}
                size="small"
                pagination={false}
              />
            ),
          },
        ]}
      />

      {/* Create user modal */}
      <Modal
        title="Add JNET User"
        open={createModalOpen}
        onOk={handleCreate}
        onCancel={() => setCreateModalOpen(false)}
        okText="Create"
      >
        <Space direction="vertical" className="w-full" size="middle">
          <Input
            placeholder="Okta Sub (user ID)"
            value={newOktaSub}
            onChange={(e) => setNewOktaSub(e.target.value)}
          />
          <Input
            placeholder="Email"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
          />
          <Input
            placeholder="Full Name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <Select
            value={newRole}
            onChange={setNewRole}
            className="w-full"
            options={[
              { label: "JNET Officer", value: "jnet_officer" },
              { label: "CJIS Admin", value: "cjis_admin" },
            ]}
          />
        </Space>
      </Modal>

      {/* Date entry modal */}
      <Modal
        title={dateModalType === "background_check" ? "Record Background Check" : "Record Training Completion"}
        open={dateModalOpen}
        onOk={handleDateSave}
        onCancel={() => { setDateModalOpen(false); setDateModalUser(null); }}
        okText="Save"
      >
        {dateModalUser && (
          <div>
            <p className="mb-3">
              <strong>{dateModalUser.full_name || dateModalUser.email}</strong>
            </p>
            <DatePicker
              value={dateValue}
              onChange={setDateValue}
              className="w-full"
              placeholder={
                dateModalType === "background_check"
                  ? "Background check date"
                  : "Training completion date"
              }
            />
          </div>
        )}
      </Modal>
    </div>
  );
}
