import { useEffect, useState, useCallback } from "react";
import {
  Table, Button, Modal, Form, Input, Select, Tag, Space, App, Card, Typography,
  Tooltip, Popconfirm,
} from "antd";
import {
  PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined, CarOutlined,
} from "@ant-design/icons";
import { api } from "../api";
import type { VehicleTag, VehicleTagCreate } from "../api";

const { Title, Text } = Typography;
const { TextArea } = Input;

const TAG_SOURCES = [
  { value: "JNET", label: "JNET" },
  { value: "CLEAN", label: "CLEAN" },
  { value: "manual", label: "Manual Entry" },
  { value: "other", label: "Other" },
];

export default function VehicleTags() {
  const { message } = App.useApp();
  const [tags, setTags] = useState<VehicleTag[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<VehicleTag | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const fetchTags = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.vehicleTags.list({ search: search || undefined, page, page_size: 50 });
      setTags(res.items);
      setTotal(res.total);
    } catch {
      message.error("Failed to load vehicle tags");
    } finally {
      setLoading(false);
    }
  }, [search, page, message]);

  useEffect(() => { fetchTags(); }, [fetchTags]);

  function openCreate() {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ plates: "", tag_source: "manual" });
    setModalOpen(true);
  }

  function openEdit(tag: VehicleTag) {
    setEditing(tag);
    form.setFieldsValue({
      name: tag.name,
      plates: tag.plates.join(", "),
      email: tag.email || "",
      phone: tag.phone || "",
      vehicle_year: tag.vehicle_year || "",
      vehicle_make: tag.vehicle_make || "",
      vehicle_model: tag.vehicle_model || "",
      vehicle_color: tag.vehicle_color || "",
      tag_source: tag.tag_source || "manual",
      tag_notes: tag.tag_notes || "",
    });
    setModalOpen(true);
  }

  async function handleSave() {
    try {
      const values = await form.validateFields();
      setSaving(true);

      const plates = (values.plates as string)
        .split(/[,\n]/)
        .map((p: string) => p.trim())
        .filter(Boolean);

      const payload: VehicleTagCreate = {
        name: values.name,
        plates,
        email: values.email || null,
        phone: values.phone || "",
        vehicle_year: values.vehicle_year || null,
        vehicle_make: values.vehicle_make || null,
        vehicle_model: values.vehicle_model || null,
        vehicle_color: values.vehicle_color || null,
        tag_source: values.tag_source || null,
        tag_notes: values.tag_notes || null,
      };

      if (editing) {
        await api.vehicleTags.update(editing.id, payload);
        message.success("Vehicle tag updated");
      } else {
        await api.vehicleTags.create(payload);
        message.success("Vehicle tag created");
      }

      setModalOpen(false);
      fetchTags();
    } catch (err: any) {
      if (err?.errorFields) return;
      message.error(err?.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await api.vehicleTags.delete(id);
      message.success("Vehicle tag deleted");
      fetchTags();
    } catch {
      message.error("Failed to delete");
    }
  }

  const columns = [
    {
      title: "Plate(s)",
      dataIndex: "plates",
      key: "plates",
      render: (plates: string[]) => (
        <Space size={4} wrap>
          {plates.map((p) => (
            <Tag key={p} color="blue" className="font-mono">{p}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: "Owner",
      dataIndex: "name",
      key: "name",
      render: (name: string, record: VehicleTag) => (
        <div>
          <div className="font-medium">{name}</div>
          {record.email && <div className="text-xs text-gray-500">{record.email}</div>}
        </div>
      ),
    },
    {
      title: "Vehicle",
      key: "vehicle",
      render: (_: any, record: VehicleTag) => {
        const parts = [record.vehicle_year, record.vehicle_color, record.vehicle_make, record.vehicle_model]
          .filter(Boolean);
        return parts.length > 0 ? parts.join(" ") : <Text type="secondary">—</Text>;
      },
    },
    {
      title: "Source",
      dataIndex: "tag_source",
      key: "tag_source",
      render: (src: string | null) => src ? <Tag>{src}</Tag> : "—",
    },
    {
      title: "Notes",
      dataIndex: "tag_notes",
      key: "tag_notes",
      ellipsis: true,
      render: (notes: string | null) => notes || "—",
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string) => (
        <Tag color={status === "active" ? "green" : "default"}>{status}</Tag>
      ),
    },
    {
      title: "Created",
      dataIndex: "created_at",
      key: "created_at",
      render: (d: string) => new Date(d).toLocaleDateString(),
    },
    {
      title: "",
      key: "actions",
      width: 100,
      render: (_: any, record: VehicleTag) => (
        <Space>
          <Tooltip title="Edit">
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          </Tooltip>
          <Popconfirm title="Delete this tag?" onConfirm={() => handleDelete(record.id)}>
            <Tooltip title="Delete">
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <Title level={3} className="!mb-0">
            <CarOutlined className="mr-2" />
            Vehicle Tags
          </Title>
          <Text type="secondary">
            Known vehicles without permits — registered via JNET/CLEAN or manual entry
          </Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          Add Vehicle Tag
        </Button>
      </div>

      <Card size="small">
        <Input
          placeholder="Search by name, plate, vehicle, or notes…"
          prefix={<SearchOutlined />}
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          allowClear
          className="max-w-md"
        />
      </Card>

      <Table
        columns={columns}
        dataSource={tags}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          total,
          pageSize: 50,
          onChange: (p) => setPage(p),
          showTotal: (t) => `${t} vehicle tag${t === 1 ? "" : "s"}`,
        }}
        size="small"
      />

      <Modal
        title={editing ? "Edit Vehicle Tag" : "Add Vehicle Tag"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        width={560}
        okText={editing ? "Save" : "Create Tag"}
      >
        <Form form={form} layout="vertical" className="mt-4">
          <Form.Item
            name="name"
            label="Owner Name"
            rules={[{ required: true, message: "Name is required" }]}
          >
            <Input placeholder="John Doe" />
          </Form.Item>

          <Form.Item
            name="plates"
            label="License Plate(s)"
            rules={[{ required: true, message: "At least one plate is required" }]}
            help="Separate multiple plates with commas"
          >
            <Input placeholder="ABC1234, XYZ5678" className="font-mono" />
          </Form.Item>

          <div className="grid grid-cols-2 gap-4">
            <Form.Item name="email" label="Email">
              <Input placeholder="owner@example.com" />
            </Form.Item>
            <Form.Item name="phone" label="Phone">
              <Input placeholder="(555) 123-4567" />
            </Form.Item>
          </div>

          <div className="grid grid-cols-4 gap-3">
            <Form.Item name="vehicle_year" label="Year">
              <Input placeholder="2024" maxLength={4} />
            </Form.Item>
            <Form.Item name="vehicle_make" label="Make">
              <Input placeholder="Toyota" />
            </Form.Item>
            <Form.Item name="vehicle_model" label="Model">
              <Input placeholder="Camry" />
            </Form.Item>
            <Form.Item name="vehicle_color" label="Color">
              <Input placeholder="White" />
            </Form.Item>
          </div>

          <Form.Item name="tag_source" label="Source">
            <Select options={TAG_SOURCES} placeholder="How was this vehicle identified?" />
          </Form.Item>

          <Form.Item name="tag_notes" label="Notes">
            <TextArea
              rows={3}
              placeholder="JNET/CLEAN lookup results, officer observations, reason for tagging…"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
