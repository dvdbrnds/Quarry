import { useCallback, useEffect, useState } from "react";
import { Button, Card, Table, App, Input, Select, Modal, Form, Popconfirm, Tag, Space } from "antd";
import { PlusOutlined, DeleteOutlined, EditOutlined } from "@ant-design/icons";
import { authHeaders } from "../auth";

interface Override {
  id: string;
  moravian_id: string;
  student_name: string;
  student_email: string;
  override_status: string;
  override_label: string;
  reason: string;
  created_by: string;
  created_at: string;
}

const STATUS_OPTIONS = [
  { value: "C", label: "Student (Commuter)" },
  { value: "R", label: "Student (Resident)" },
  { value: "O", label: "Student (Off Campus)" },
  { value: "F", label: "Faculty" },
  { value: "S", label: "Staff" },
];

const STATUS_COLORS: Record<string, string> = {
  C: "blue",
  R: "green",
  O: "orange",
  F: "purple",
  S: "cyan",
};

class ApiError extends Error {
  status: number;
  constructor(status: number, body: string) {
    super(body || `${status}`);
    this.status = status;
  }
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(await authHeaders()),
    ...(init?.headers as Record<string, string>),
  };
  const res = await fetch(`/api/admin/housing-overrides${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(res.status, body);
  }
  return res.json();
}

export default function HousingOverrides() {
  const { message } = App.useApp();
  const [overrides, setOverrides] = useState<Override[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Override | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setOverrides(await apiRequest<Override[]>(""));
    } catch {
      message.error("Failed to load classification overrides");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (row: Override) => {
    setEditing(row);
    form.setFieldsValue({
      student_email: row.student_email,
      student_name: row.student_name,
      override_status: row.override_status,
      reason: row.reason,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      if (editing) {
        const result = await apiRequest<{ cancelled_applications?: number }>(`/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify({
            student_name: values.student_name,
            override_status: values.override_status,
            reason: values.reason,
          }),
        });
        const cancelled = result.cancelled_applications || 0;
        message.success(cancelled > 0
          ? `Override updated — ${cancelled} conflicting application${cancelled > 1 ? "s" : ""} cancelled`
          : "Override updated");
      } else {
        const result = await apiRequest<{ cancelled_applications?: number }>("", { method: "POST", body: JSON.stringify(values) });
        const cancelled = result.cancelled_applications || 0;
        message.success(cancelled > 0
          ? `Override created — ${cancelled} conflicting application${cancelled > 1 ? "s" : ""} cancelled`
          : "Override created");
      }
      setModalOpen(false);
      setEditing(null);
      load();
    } catch (e: any) {
      if (e.errorFields) return;
      if (e instanceof ApiError && e.status === 409) {
        message.warning("An override already exists for this person. Delete it first to change it.");
        load();
        setModalOpen(false);
      } else {
        message.error(e.message || "Save failed");
      }
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (override: Override) => {
    try {
      await apiRequest(`/${override.id}`, { method: "DELETE" });
      message.success("Override removed — will use Okta/SIS data again");
      load();
    } catch {
      message.error("Failed to delete");
    }
  };

  return (
    <div>
      <p className="text-sm text-gray-500 mb-4">
        Override a person&apos;s parking classification when Okta groups or SIS data are wrong.
        Student overrides (Commuter/Resident/Off Campus) control which student permit types they see.
        Faculty/Staff overrides give access to employee permit types regardless of Okta group membership.
      </p>

      <Card
        size="small"
        title="Active Overrides"
        extra={
          <Button type="primary" size="small" icon={<PlusOutlined />} onClick={openCreate}>
            Add Override
          </Button>
        }
      >
        <Table
          dataSource={overrides}
          loading={loading}
          rowKey="id"
          pagination={false}
          size="small"
          locale={{ emptyText: "No active overrides — everyone using Okta/SIS data" }}
          columns={[
            {
              title: "Name",
              key: "student",
              render: (_: unknown, row: Override) => (
                <div>
                  <span className="font-medium">{row.student_name || "—"}</span>
                  <span className="text-gray-400 text-xs ml-2">{row.student_email}</span>
                </div>
              ),
            },
            {
              title: "Override To",
              dataIndex: "override_label",
              key: "override_label",
              width: 180,
              render: (label: string, row: Override) => (
                <Tag color={STATUS_COLORS[row.override_status] || "default"}>
                  {label}
                </Tag>
              ),
            },
            {
              title: "Reason",
              dataIndex: "reason",
              key: "reason",
              ellipsis: true,
            },
            {
              title: "Created By",
              dataIndex: "created_by",
              key: "created_by",
              width: 180,
              render: (email: string) => <span className="text-xs text-gray-500">{email}</span>,
            },
            {
              title: "",
              key: "actions",
              width: 80,
              render: (_: unknown, row: Override) => (
                <Space size={4}>
                  <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openEdit(row)} />
                  <Popconfirm
                    title="Remove this override?"
                    description="This person will revert to their Okta/SIS classification."
                    onConfirm={() => handleDelete(row)}
                    okText="Remove"
                    okType="danger"
                  >
                    <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={editing ? "Edit Classification Override" : "Add Classification Override"}
        open={modalOpen}
        onCancel={() => { setModalOpen(false); setEditing(null); }}
        onOk={handleSave}
        confirmLoading={saving}
        okText={editing ? "Save Changes" : "Create Override"}
        width={480}
      >
        <Form form={form} layout="vertical" className="mt-4">
          <Form.Item
            name="student_email"
            label="Email"
            rules={[{ required: true, message: "Required" }, { type: "email", message: "Enter a valid email" }]}
            extra="The person's Moravian email address (used as the lookup key)"
          >
            <Input placeholder="smithj@moravian.edu" disabled={!!editing} />
          </Form.Item>
          <Form.Item name="student_name" label="Name">
            <Input placeholder="Jane Smith" />
          </Form.Item>
          <Form.Item
            name="override_status"
            label="Classify as"
            rules={[{ required: true, message: "Required" }]}
          >
            <Select options={STATUS_OPTIONS} placeholder="Select classification" />
          </Form.Item>
          <Form.Item
            name="reason"
            label="Reason"
            extra="Brief note on why this override is needed"
          >
            <Input.TextArea rows={2} placeholder="Okta groups don't include faculty group but they teach classes" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
