import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Card, Table, App, Input, Select, Switch, Modal, Form, InputNumber, Popconfirm, Upload, DatePicker } from "antd";
import { PlusOutlined, EditOutlined, DeleteOutlined, CopyOutlined, UploadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { authHeaders, getAccessToken } from "../auth";
import { api, Lot } from "../api";

interface Preset {
  id: string;
  label: string;
  slug: string;
  direct_link: string;
  company_name: string;
  sponsor_name: string;
  sponsor_email: string;
  sponsor_department: string;
  default_duration: string;
  custom_start_date: string | null;
  custom_end_date: string | null;
  permit_type_code: string | null;
  allowed_lots: string[];
  require_student_name: boolean;
  student_name_label: string;
  require_instructor_name: boolean;
  instructor_name_label: string;
  logo_url: string;
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
  { value: "custom", label: "Custom range" },
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
  const [lots, setLots] = useState<{ value: string; label: string }[]>([]);
  const [logoPreview, setLogoPreview] = useState<string>("");
  const [uploadingLogo, setUploadingLogo] = useState(false);

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
      try {
        const lotData = await api.lots.list();
        setLots(lotData.map((l: Lot) => ({ value: l.name, label: l.name })));
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
    setLogoPreview("");
    form.resetFields();
    form.setFieldsValue({ default_duration: "semester", sort_order: 0, allowed_lots: [], require_student_name: false, student_name_label: "Student name", require_instructor_name: false, instructor_name_label: "Instructor/Ensemble" });
    setModalOpen(true);
  };

  const openEdit = (preset: Preset) => {
    setEditing(preset);
    setLogoPreview(preset.logo_url || "");
    form.setFieldsValue({
      ...preset,
      custom_start_date: preset.custom_start_date ? dayjs(preset.custom_start_date) : null,
      custom_end_date: preset.custom_end_date ? dayjs(preset.custom_end_date) : null,
    });
    setModalOpen(true);
  };

  const handleLogoUpload = async (file: File) => {
    if (!editing) {
      message.info("Save the preset first, then upload a logo.");
      return;
    }
    setUploadingLogo(true);
    try {
      const token = await getAccessToken();
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`/api/visitor/permits/presets/${editing.id}/logo`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: fd,
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setLogoPreview(data.logo_url);
      message.success("Logo uploaded");
      load();
    } catch (e: any) {
      message.error(e.message || "Upload failed");
    } finally {
      setUploadingLogo(false);
    }
  };

  const handleLogoDelete = async () => {
    if (!editing) return;
    try {
      const token = await getAccessToken();
      await fetch(`/api/visitor/permits/presets/${editing.id}/logo`, {
        method: "DELETE",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      setLogoPreview("");
      message.success("Logo removed");
      load();
    } catch {
      message.error("Failed to remove logo");
    }
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      const payload = {
        ...values,
        custom_start_date: values.custom_start_date ? dayjs(values.custom_start_date).format("YYYY-MM-DD") : null,
        custom_end_date: values.custom_end_date ? dayjs(values.custom_end_date).format("YYYY-MM-DD") : null,
      };
      setSaving(true);
      if (editing) {
        await apiRequest(`/presets/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        message.success("Preset updated");
      } else {
        await apiRequest("/presets", {
          method: "POST",
          body: JSON.stringify(payload),
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
              render: (d: string, row: Preset) => {
                if (d === "custom" && row.custom_start_date && row.custom_end_date) {
                  return <span className="text-xs">{row.custom_start_date} → {row.custom_end_date}</span>;
                }
                return d === "semester" ? "Semester" : d === "yearly" ? "Yearly" : d === "custom" ? "Custom" : "Multi-day";
              },
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
              title: "Allowed Lots",
              dataIndex: "allowed_lots",
              key: "allowed_lots",
              width: 180,
              render: (lots: string[]) => {
                if (!lots || lots.length === 0) return <span className="text-gray-400">—</span>;
                return <span className="text-xs">{lots.join(", ")}</span>;
              },
            },
            {
              title: "Direct Link",
              key: "direct_link",
              width: 200,
              render: (_: unknown, row: Preset) => (
                <div className="flex items-center gap-1">
                  <code className="text-xs bg-gray-100 px-1.5 py-0.5 rounded truncate max-w-[120px]" title={row.direct_link}>
                    ?preset={row.slug}
                  </code>
                  <Button
                    size="small"
                    type="text"
                    icon={<CopyOutlined />}
                    title="Copy direct link"
                    onClick={() => {
                      navigator.clipboard.writeText(row.direct_link);
                      message.success("Link copied!");
                    }}
                  />
                </div>
              ),
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
          {editing?.direct_link && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <span className="text-xs font-medium text-blue-700 block mb-1">Direct link for this program</span>
                  <code className="text-xs text-blue-900 break-all">{editing.direct_link}</code>
                </div>
                <Button
                  size="small"
                  icon={<CopyOutlined />}
                  onClick={() => {
                    navigator.clipboard.writeText(editing.direct_link);
                    message.success("Link copied!");
                  }}
                >
                  Copy
                </Button>
              </div>
            </div>
          )}
          {editing && (
            <div className="mb-4">
              <label className="block text-sm font-medium mb-2">Program logo</label>
              <div className="flex items-center gap-3">
                {logoPreview ? (
                  <img src={logoPreview} alt="Preset logo" className="h-12 w-auto rounded border bg-white p-1" />
                ) : (
                  <div className="h-12 w-12 rounded border border-dashed border-gray-300 flex items-center justify-center text-gray-400 text-xs">
                    None
                  </div>
                )}
                <Upload
                  accept="image/*"
                  showUploadList={false}
                  beforeUpload={(file) => { handleLogoUpload(file); return false; }}
                >
                  <Button size="small" icon={<UploadOutlined />} loading={uploadingLogo}>
                    {logoPreview ? "Replace" : "Upload"}
                  </Button>
                </Upload>
                {logoPreview && (
                  <Button size="small" danger onClick={handleLogoDelete}>Remove</Button>
                )}
              </div>
              <p className="text-xs text-gray-400 mt-1">Shown on the vanity landing page above the form.</p>
            </div>
          )}
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
          <Form.Item noStyle dependencies={["default_duration"]}>
            {() =>
              form.getFieldValue("default_duration") === "custom" ? (
                <div className="grid grid-cols-2 gap-3">
                  <Form.Item name="custom_start_date" label="Start date" rules={[{ required: true, message: "Required" }]}>
                    <DatePicker className="w-full" format="YYYY-MM-DD" />
                  </Form.Item>
                  <Form.Item name="custom_end_date" label="End date" rules={[{ required: true, message: "Required" }]}>
                    <DatePicker className="w-full" format="YYYY-MM-DD" />
                  </Form.Item>
                </div>
              ) : null
            }
          </Form.Item>
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
          <Form.Item
            name="allowed_lots"
            label="Allowed lots"
            extra="Directly assign lot access without needing a permit type (e.g., partnership arrangements)"
          >
            <Select
              mode="multiple"
              allowClear
              placeholder="No specific lots (uses permit type)"
              options={lots}
            />
          </Form.Item>
          <div className="border-t pt-3 mt-1 mb-3">
            <p className="text-xs text-gray-500 mb-3">
              If visitors are parents or guardians dropping off a student (e.g., music lessons), enable this to collect the student's name on the form.
            </p>
          </div>
          <Form.Item name="require_student_name" valuePropName="checked" label="Require student/attendee name">
            <Switch />
          </Form.Item>
          <Form.Item noStyle dependencies={["require_student_name"]}>
            {() =>
              form.getFieldValue("require_student_name") ? (
                <Form.Item
                  name="student_name_label"
                  label="Field label"
                  extra={'Customize the label visitors see, e.g. "Student name", "Child\'s name", "Attendee name"'}
                >
                  <Input placeholder="Student name" />
                </Form.Item>
              ) : null
            }
          </Form.Item>
          <Form.Item name="require_instructor_name" valuePropName="checked" label="Require Instructor/Ensemble">
            <Switch />
          </Form.Item>
          <Form.Item noStyle dependencies={["require_instructor_name"]}>
            {() =>
              form.getFieldValue("require_instructor_name") ? (
                <Form.Item
                  name="instructor_name_label"
                  label="Instructor field label"
                  extra={'Customize the label, e.g. "Instructor/Ensemble", "Teacher name"'}
                >
                  <Input placeholder="Instructor/Ensemble" />
                </Form.Item>
              ) : null
            }
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
