import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Table,
  App,
  Tag,
  Space,
  Modal,
  Form,
  Input,
  InputNumber,
  Select,
  Radio,
  DatePicker,
  Switch,
  Popconfirm,
} from "antd";
import { PlusOutlined, EditOutlined, DeleteOutlined } from "@ant-design/icons";
import { authHeaders } from "../auth";
import dayjs from "dayjs";

interface Coupon {
  id: string;
  code: string;
  program_name: string;
  discount_type: "percent" | "flat" | "full";
  discount_value: number;
  applicable_permit_codes: string[];
  max_uses: number | null;
  current_uses: number;
  is_active: boolean;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}

interface PermitType {
  id: string;
  code: string;
  label: string;
  is_active: boolean;
}

export default function CouponManager() {
  const { message } = App.useApp();
  const [coupons, setCoupons] = useState<Coupon[]>([]);
  const [permitTypes, setPermitTypes] = useState<PermitType[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Coupon | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cRes, ptRes] = await Promise.all([
        fetch("/api/coupons", { headers: await authHeaders() }),
        fetch("/api/permit-types?all=true", { headers: await authHeaders() }),
      ]);
      if (cRes.ok) setCoupons(await cRes.json());
      if (ptRes.ok) setPermitTypes(await ptRes.json());
    } catch (e: any) {
      message.error(e.message || "Failed to load coupons");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => { load(); }, [load]);

  function openCreate() {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ discount_type: "full", is_active: true });
    setModalOpen(true);
  }

  function openEdit(coupon: Coupon) {
    setEditing(coupon);
    form.setFieldsValue({
      code: coupon.code,
      program_name: coupon.program_name,
      discount_type: coupon.discount_type,
      discount_value: coupon.discount_value,
      applicable_permit_codes: coupon.applicable_permit_codes,
      max_uses: coupon.max_uses,
      is_active: coupon.is_active,
      expires_at: coupon.expires_at ? dayjs(coupon.expires_at) : null,
    });
    setModalOpen(true);
  }

  async function handleSave() {
    try {
      const values = await form.validateFields();
      setSaving(true);

      const payload = {
        code: values.code?.toUpperCase().trim(),
        program_name: values.program_name?.trim() || "",
        discount_type: values.discount_type,
        discount_value: values.discount_type === "full" ? 0 : values.discount_value || 0,
        applicable_permit_codes: values.applicable_permit_codes || [],
        max_uses: values.max_uses || null,
        is_active: values.is_active ?? true,
        expires_at: values.expires_at ? values.expires_at.toISOString() : null,
      };

      const url = editing ? `/api/coupons/${editing.id}` : "/api/coupons";
      const method = editing ? "PUT" : "POST";

      const res = await fetch(url, {
        method,
        headers: await authHeaders(),
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as any).detail || `Failed (${res.status})`);
      }

      message.success(editing ? "Coupon updated" : "Coupon created");
      setModalOpen(false);
      load();
    } catch (e: any) {
      if (e.errorFields) return;
      message.error(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(coupon: Coupon) {
    try {
      const res = await fetch(`/api/coupons/${coupon.id}`, {
        method: "DELETE",
        headers: await authHeaders(),
      });
      if (!res.ok) throw new Error("Failed to delete");
      message.success("Coupon deleted");
      load();
    } catch (e: any) {
      message.error(e.message);
    }
  }

  async function toggleActive(coupon: Coupon) {
    try {
      const res = await fetch(`/api/coupons/${coupon.id}`, {
        method: "PUT",
        headers: await authHeaders(),
        body: JSON.stringify({ is_active: !coupon.is_active }),
      });
      if (!res.ok) throw new Error("Failed to update");
      load();
    } catch (e: any) {
      message.error(e.message);
    }
  }

  const discountType = Form.useWatch("discount_type", form);

  const columns = [
    {
      title: "Code",
      dataIndex: "code",
      key: "code",
      render: (code: string) => <code className="font-bold">{code}</code>,
    },
    {
      title: "Program",
      dataIndex: "program_name",
      key: "program_name",
    },
    {
      title: "Discount",
      key: "discount",
      render: (_: unknown, r: Coupon) => {
        if (r.discount_type === "full") return <Tag color="green">100% off</Tag>;
        if (r.discount_type === "percent") return <Tag color="blue">{r.discount_value}% off</Tag>;
        return <Tag color="purple">${r.discount_value} off</Tag>;
      },
    },
    {
      title: "Applicable Permits",
      dataIndex: "applicable_permit_codes",
      key: "permits",
      render: (codes: string[]) =>
        codes.length === 0 ? (
          <span className="text-gray-400">All</span>
        ) : (
          <span className="text-xs">{codes.join(", ")}</span>
        ),
    },
    {
      title: "Usage",
      key: "usage",
      render: (_: unknown, r: Coupon) =>
        r.max_uses ? `${r.current_uses} / ${r.max_uses}` : `${r.current_uses} / ∞`,
    },
    {
      title: "Status",
      key: "status",
      render: (_: unknown, r: Coupon) => {
        if (!r.is_active) return <Tag>Inactive</Tag>;
        if (r.expires_at && new Date(r.expires_at) < new Date()) return <Tag color="red">Expired</Tag>;
        if (r.max_uses && r.current_uses >= r.max_uses) return <Tag color="orange">Maxed</Tag>;
        return <Tag color="green">Active</Tag>;
      },
    },
    {
      title: "Expires",
      dataIndex: "expires_at",
      key: "expires_at",
      render: (v: string | null) => (v ? dayjs(v).format("MMM D, YYYY") : "—"),
    },
    {
      title: "",
      key: "actions",
      render: (_: unknown, r: Coupon) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
          <Button size="small" onClick={() => toggleActive(r)}>
            {r.is_active ? "Disable" : "Enable"}
          </Button>
          <Popconfirm title="Delete this coupon?" onConfirm={() => handleDelete(r)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold m-0">Coupons</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          Create Coupon
        </Button>
      </div>

      <Table
        dataSource={coupons}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
        size="small"
      />

      <Modal
        title={editing ? "Edit Coupon" : "Create Coupon"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical" className="mt-4">
          <Form.Item name="code" label="Coupon Code" rules={[{ required: true, message: "Required" }]}>
            <Input
              placeholder="e.g., NURSING2026"
              style={{ textTransform: "uppercase" }}
            />
          </Form.Item>

          <Form.Item name="program_name" label="Academic Program" rules={[{ required: true, message: "Required" }]}>
            <Input placeholder="e.g., MSN Accelerated Nursing" />
          </Form.Item>

          <Form.Item name="discount_type" label="Discount Type" rules={[{ required: true }]}>
            <Radio.Group>
              <Radio.Button value="full">Full Waiver (100%)</Radio.Button>
              <Radio.Button value="percent">Percentage</Radio.Button>
              <Radio.Button value="flat">Flat Amount</Radio.Button>
            </Radio.Group>
          </Form.Item>

          {discountType === "percent" && (
            <Form.Item
              name="discount_value"
              label="Percentage Off"
              rules={[{ required: true, message: "Required" }]}
            >
              <InputNumber min={1} max={100} addonAfter="%" style={{ width: "100%" }} />
            </Form.Item>
          )}

          {discountType === "flat" && (
            <Form.Item
              name="discount_value"
              label="Dollar Amount Off"
              rules={[{ required: true, message: "Required" }]}
            >
              <InputNumber min={1} addonBefore="$" style={{ width: "100%" }} />
            </Form.Item>
          )}

          <Form.Item name="applicable_permit_codes" label="Applicable Permit Types">
            <Select
              mode="multiple"
              placeholder="All permit types (leave empty for all)"
              allowClear
              options={permitTypes.map((pt) => ({ label: pt.label, value: pt.code }))}
            />
          </Form.Item>

          <Form.Item name="max_uses" label="Max Uses">
            <InputNumber min={1} placeholder="Unlimited" style={{ width: "100%" }} />
          </Form.Item>

          <Form.Item name="expires_at" label="Expires At">
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>

          <Form.Item name="is_active" label="Active" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
