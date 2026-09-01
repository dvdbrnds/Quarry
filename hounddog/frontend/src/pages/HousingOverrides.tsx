import { useCallback, useEffect, useState } from "react";
import { Button, Card, Table, App, Input, Select, Modal, Form, Popconfirm, Tag } from "antd";
import { PlusOutlined, DeleteOutlined } from "@ant-design/icons";
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
  { value: "C", label: "Commuter" },
  { value: "R", label: "Resident" },
  { value: "O", label: "Off Campus Release" },
];

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(await authHeaders()),
    ...(init?.headers as Record<string, string>),
  };
  const res = await fetch(`/api/admin/housing-overrides${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `${res.status}`);
  }
  return res.json();
}

export default function HousingOverrides() {
  const { message } = App.useApp();
  const [overrides, setOverrides] = useState<Override[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setOverrides(await apiRequest<Override[]>(""));
    } catch {
      message.error("Failed to load housing overrides");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => {
    form.resetFields();
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      await apiRequest("", { method: "POST", body: JSON.stringify(values) });
      message.success("Override created");
      setModalOpen(false);
      load();
    } catch (e: any) {
      if (e.errorFields) return;
      const msg = e.message || "Save failed";
      if (msg.includes("409")) {
        message.warning("An override already exists for this student. Delete it first to change it.");
      } else {
        message.error(msg);
      }
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (override: Override) => {
    try {
      await apiRequest(`/${override.id}`, { method: "DELETE" });
      message.success("Override removed — student will use SIS data again");
      load();
    } catch {
      message.error("Failed to delete");
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-sm text-gray-500 mt-1">
            Override a student's housing classification when the SIS feed is wrong. Overrides take
            priority — the student will see permit types matching the overridden status instead of
            what Jenzabar reports.
          </p>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          Add Override
        </Button>
      </div>

      <Card size="small">
        <Table
          dataSource={overrides}
          loading={loading}
          rowKey="id"
          pagination={false}
          size="small"
          locale={{ emptyText: "No active overrides — all students using SIS feed data" }}
          columns={[
            {
              title: "Moravian ID",
              dataIndex: "moravian_id",
              key: "moravian_id",
              width: 120,
              render: (id: string) => <code className="font-mono">{id}</code>,
            },
            {
              title: "Student",
              key: "student",
              render: (_: unknown, row: Override) => (
                <div>
                  <span className="font-medium">{row.student_name || "—"}</span>
                  {row.student_email && (
                    <span className="text-gray-400 text-xs ml-2">{row.student_email}</span>
                  )}
                </div>
              ),
            },
            {
              title: "Override To",
              dataIndex: "override_label",
              key: "override_label",
              width: 140,
              render: (label: string, row: Override) => (
                <Tag color={row.override_status === "C" ? "blue" : row.override_status === "R" ? "green" : "orange"}>
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
              width: 50,
              render: (_: unknown, row: Override) => (
                <Popconfirm
                  title="Remove this override?"
                  description="Student will revert to their SIS housing status."
                  onConfirm={() => handleDelete(row)}
                  okText="Remove"
                  okType="danger"
                >
                  <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title="Add Housing Override"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        okText="Create Override"
        width={480}
      >
        <Form form={form} layout="vertical" className="mt-4">
          <Form.Item
            name="moravian_id"
            label="Moravian ID"
            rules={[{ required: true, message: "Required" }]}
            extra="The student's numeric Jenzabar ID"
          >
            <Input placeholder="12345678" className="font-mono" />
          </Form.Item>
          <Form.Item name="student_name" label="Student name">
            <Input placeholder="Jane Smith" />
          </Form.Item>
          <Form.Item name="student_email" label="Student email">
            <Input placeholder="smithj@moravian.edu" />
          </Form.Item>
          <Form.Item
            name="override_status"
            label="Override to"
            rules={[{ required: true, message: "Required" }]}
          >
            <Select options={STATUS_OPTIONS} placeholder="Select classification" />
          </Form.Item>
          <Form.Item
            name="reason"
            label="Reason"
            extra="Brief note on why SIS data is being overridden (e.g., 'moved off campus mid-semester, SIS not updated')"
          >
            <Input.TextArea rows={2} placeholder="SIS shows resident but student moved off campus" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
