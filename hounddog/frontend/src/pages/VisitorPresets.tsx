import { useCallback, useEffect, useState } from "react";
import { Button, Card, Table, App, Input, Select, Switch, Modal, Form, InputNumber, Popconfirm } from "antd";
import { PlusOutlined, EditOutlined, DeleteOutlined } from "@ant-design/icons";
import { authHeaders, getAccessToken } from "../auth";

interface Preset {
  id: string;
  label: string;
  company_name: string;
  sponsor_name: string;
  sponsor_email: string;
  sponsor_department: string;
  default_duration: string;
  permit_type_code: string | null;
  active: boolean;
  sort_order: number;
}

interface PermitTypeOption {
  code: string;
  label: string;
}

const DURATION_OPTIONS = [
  { value: "multi_day", label: "Multi-day" },
  { value: "semester", label: "Semester" },
  { value: "yearly", label: "Yearly" },
];

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`/api/visitor/permits${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `${res.status}`);
  }
  return res.json();
}

export default function VisitorPresets() {
  const { message } = App.useApp();
  const [presets, setPresets] = useState<Preset[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Preset | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const [permitTypes, setPermitTypes] = useState<PermitTypeOption[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const headers = await authHeaders();
        const res = await fetch("/api/permit-types", { headers });
        if (res.ok) {
          const data = await res.json();
          setPermitTypes(data.map((pt: any) => ({ code: pt.code, label: pt.label })));
        }
      } catch { /* ignore */ }
    })();
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiRequest<Preset[]>("/presets/all");
      setPresets(data);
    } catch {
      message.error("Failed to load presets");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ default_duration: "semester", sort_order: 0 });
    setModalOpen(true);
  };

  const openEdit = (preset: Preset) => {
    setEditing(preset);
    form.setFieldsValue(preset);
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      if (editing) {
        await apiRequest(`/presets/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify(values),
        });
        message.success("Preset updated");
      } else {
        await apiRequest("/presets", {
          method: "POST",
          body: JSON.stringify(values),
        });
        message.success("Preset created");
      }
      setModalOpen(false);
      load();
    } catch (e: any) {
      if (e.errorFields) return;
      message.error(e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (preset: Preset, active: boolean) => {
    try {
      await apiRequest(`/presets/${preset.id}`, {
        method: "PUT",
        body: JSON.stringify({ active }),
      });
      setPresets((prev) =>
        prev.map((p) => (p.id === preset.id ? { ...p, active } : p)),
      );
    } catch {
      message.error("Failed to update");
    }
  };

  const handleDelete = async (preset: Preset) => {
    try {
      await apiRequest(`/presets/${preset.id}/remove`, { method: "POST" });
      message.success("Preset deleted");
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
            Presets let recurring visitors (e.g., Sodexo employees) skip the sponsor fields — the system fills in the sponsor automatically.
          </p>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          Add preset
        </Button>
      </div>

      <Card size="small">
        <Table
          dataSource={presets}
          loading={loading}
          rowKey="id"
          pagination={false}
          size="small"
          columns={[
            {
              title: "Label",
              dataIndex: "label",
              key: "label",
              render: (text: string) => <span className="font-medium">{text}</span>,
            },
            {
              title: "Company",
              dataIndex: "company_name",
              key: "company_name",
            },
            {
              title: "Sponsor",
              key: "sponsor",
              render: (_: unknown, row: Preset) => (
                <span>
                  {row.sponsor_name}
                  <span className="text-gray-400 text-xs ml-1">({row.sponsor_email})</span>
                </span>
              ),
            },
            {
              title: "Department",
              dataIndex: "sponsor_department",
              key: "dept",
            },
            {
              title: "Duration",
              dataIndex: "default_duration",
              key: "duration",
              width: 100,
              render: (d: string) => d === "semester" ? "Semester" : d === "yearly" ? "Yearly" : "Multi-day",
            },
            {
              title: "Permit Type",
              dataIndex: "permit_type_code",
              key: "permit_type",
              width: 160,
              render: (code: string | null) => {
                if (!code) return <span className="text-gray-400">Default</span>;
                const pt = permitTypes.find((t) => t.code === code);
                return pt ? pt.label : code;
              },
            },
            {
              title: "Active",
              dataIndex: "active",
              key: "active",
              width: 80,
              render: (active: boolean, row: Preset) => (
                <Switch
                  checked={active}
                  size="small"
                  onChange={(v) => handleToggle(row, v)}
                />
              ),
            },
            {
              title: "",
              key: "actions",
              width: 80,
              render: (_: unknown, row: Preset) => (
                <div className="flex gap-1">
                  <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openEdit(row)} />
                  <Popconfirm title="Delete this preset?" onConfirm={() => handleDelete(row)} okText="Delete" okType="danger">
                    <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </div>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={editing ? "Edit Preset" : "New Visitor Preset"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        okText={editing ? "Save" : "Create"}
        width={520}
      >
        <Form form={form} layout="vertical" className="mt-4">
          <Form.Item
            name="label"
            label="Dropdown label"
            rules={[{ required: true, message: "Required" }]}
            extra="What visitors see in the dropdown, e.g. 'Sodexo employee'"
          >
            <Input placeholder="Sodexo employee" />
          </Form.Item>
          <Form.Item
            name="company_name"
            label="Company / organization"
            rules={[{ required: true, message: "Required" }]}
          >
            <Input placeholder="Sodexo" />
          </Form.Item>
          <div className="border-t pt-3 mt-1 mb-3">
            <p className="text-xs text-gray-500 mb-3">
              Campus sponsor — the person who receives and approves all requests for this organization.
            </p>
          </div>
          <Form.Item
            name="sponsor_name"
            label="Sponsor name"
            rules={[{ required: true, message: "Required" }]}
          >
            <Input placeholder="Stacey Cesanek" />
          </Form.Item>
          <Form.Item
            name="sponsor_email"
            label="Sponsor email"
            rules={[
              { required: true, message: "Required" },
              { type: "email", message: "Enter a valid email" },
            ]}
          >
            <Input placeholder="cesaneks@moravian.edu" />
          </Form.Item>
          <Form.Item name="sponsor_department" label="Department">
            <Input placeholder="Food Services" />
          </Form.Item>
          <div className="grid grid-cols-2 gap-3">
            <Form.Item name="default_duration" label="Default duration">
              <Select options={DURATION_OPTIONS} />
            </Form.Item>
            <Form.Item name="sort_order" label="Sort order">
              <InputNumber min={0} className="w-full" />
            </Form.Item>
          </div>
          <Form.Item
            name="permit_type_code"
            label="Permit type"
            extra="Assign a specific permit type (and its lots) instead of the default visitor permit"
          >
            <Select
              allowClear
              placeholder="Default (Visitor)"
              options={permitTypes.map((pt) => ({ value: pt.code, label: pt.label }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
