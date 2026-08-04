import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";
import { Table, Button, Tag, Form, Input, InputNumber, Select, Card, Space, App, Empty } from "antd";
import type { ColumnsType } from "antd/es/table";

interface ViolationType {
  id: string; code: string; label: string; category: string;
  fine_first: string; fine_second: string | null; fine_third_plus: string | null;
  is_active: boolean; sort_order: number;
}

function ViolationTypeForm({ initial, onSave, onCancel }: {
  initial?: ViolationType; onSave: () => void; onCancel: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (initial) {
      form.setFieldsValue({
        code: initial.code, label: initial.label, category: initial.category,
        fine_first: Number(initial.fine_first),
        fine_second: initial.fine_second != null && initial.fine_second !== "" ? Number(initial.fine_second) : undefined,
        fine_third_plus: initial.fine_third_plus != null && initial.fine_third_plus !== "" ? Number(initial.fine_third_plus) : undefined,
        sort_order: initial.sort_order,
      });
    } else { form.resetFields(); }
  }, [initial, form]);

  async function handleFinish(values: any) {
    setSaving(true);
    try {
      const method = initial ? "PUT" : "POST";
      const url = initial ? `/api/violation-types/${initial.id}` : "/api/violation-types";
      const toFine = (v: unknown) =>
        v === undefined || v === null || v === "" ? null : Number(v);
      await fetch(url, { method, headers: await authHeaders(), body: JSON.stringify({
        ...values,
        fine_first: Number(values.fine_first),
        fine_second: toFine(values.fine_second),
        fine_third_plus: toFine(values.fine_third_plus),
      })});
      message.success(initial ? "Violation type updated" : "Violation type created");
      onSave();
    } catch { message.error("Failed to save"); } finally { setSaving(false); }
  }

  return (
    <Card className="mb-6">
      <Form form={form} layout="vertical" onFinish={handleFinish}
        initialValues={{ category: "parking", fine_first: 35, sort_order: 0 }}>
        <div className="grid grid-cols-2 gap-x-4">
          <Form.Item name="code" label="Code" rules={[{ required: true }]}>
            <Input placeholder="e.g. no_permit" />
          </Form.Item>
          <Form.Item name="label" label="Label" rules={[{ required: true }]}>
            <Input placeholder="e.g. No Valid Permit" />
          </Form.Item>
          <Form.Item name="category" label="Category">
            <Select options={[{ label: "Parking", value: "parking" }, { label: "Moving", value: "moving" }]} />
          </Form.Item>
          <Form.Item name="sort_order" label="Sort Order">
            <InputNumber className="w-full" />
          </Form.Item>
          <Form.Item
            name="fine_first"
            label="Fine (1st Offense)"
            extra="Use $0 for a warning (no fine)."
            rules={[
              {
                validator: (_, value) => {
                  if (value === undefined || value === null || value === "") {
                    return Promise.reject(new Error("Please enter Fine (1st Offense)"));
                  }
                  if (Number(value) < 0) {
                    return Promise.reject(new Error("Fine cannot be negative"));
                  }
                  return Promise.resolve();
                },
              },
            ]}
          >
            <InputNumber className="w-full" min={0} step={0.01} prefix="$" placeholder="0 for warning" />
          </Form.Item>
          <Form.Item name="fine_second" label="Fine (2nd Offense)">
            <InputNumber className="w-full" min={0} step={0.01} prefix="$" placeholder="Leave blank if no escalation" />
          </Form.Item>
          <Form.Item name="fine_third_plus" label="Fine (3rd+ Offense)">
            <InputNumber className="w-full" min={0} step={0.01} prefix="$" placeholder="Leave blank if no escalation" />
          </Form.Item>
        </div>
        <Space>
          <Button onClick={onCancel}>Cancel</Button>
          <Button type="primary" htmlType="submit" loading={saving}>{initial ? "Update" : "Create"}</Button>
        </Space>
      </Form>
    </Card>
  );
}

export default function ViolationTypes() {
  const { modal, message } = App.useApp();
  const [types, setTypes] = useState<ViolationType[]>([]);
  const [editing, setEditing] = useState<ViolationType | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/violation-types?all=true", { headers: await authHeaders() });
      if (res.ok) setTypes(await res.json());
    } catch { message.error("Failed to load violation types"); }
    finally { setLoading(false); }
  }, [message]);

  useEffect(() => { load(); }, [load]);

  function handleDeactivate(id: string) {
    modal.confirm({
      title: "Deactivate this violation type?", okText: "Deactivate", okButtonProps: { danger: true },
      onOk: async () => {
        const headers = await authHeaders();
        const res = await fetch(`/api/violation-types/${id}`, {
          method: "PUT",
          headers,
          body: JSON.stringify({ is_active: false }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          message.error((err as any).detail || "Failed to deactivate");
          throw new Error("Deactivate failed");
        }
        message.success("Violation type deactivated");
        await load();
      },
    });
  }

  function handleDelete(id: string, label: string, force = false) {
    modal.confirm({
      title: force ? `FORCE delete "${label}" and orphan its tickets?` : `Permanently delete "${label}"?`,
      content: force
        ? "This will delete the violation type even though tickets reference it. Those tickets will keep their violation code as text but the type definition will be gone."
        : "This cannot be undone. Only delete violation types that have never been used on a ticket.",
      okText: force ? "Force Delete" : "Delete Forever",
      okButtonProps: { danger: true },
      onOk: async () => {
        const headers = await authHeaders();
        headers["X-HTTP-Method-Override"] = "DELETE";
        const url = `/api/violation-types/${id}${force ? "?force=true" : ""}`;
        const res = await fetch(url, { method: "POST", headers });
        if (!res.ok && res.status !== 204) {
          const err = await res.json().catch(() => ({}));
          const detail = (err as any).detail || "Failed to delete";
          if (!force && detail.includes("existing tickets")) {
            message.warning(detail);
            handleDelete(id, label, true);
            return;
          }
          message.error(detail);
          throw new Error("Delete failed");
        }
        message.success("Violation type deleted");
        await load();
      },
    });
  }

  const columns: ColumnsType<ViolationType> = [
    { title: "#", dataIndex: "sort_order", key: "sort_order", width: 50 },
    { title: "Code", dataIndex: "code", key: "code", render: (v) => <span className="font-mono text-xs">{v}</span> },
    { title: "Label", dataIndex: "label", key: "label" },
    { title: "Category", dataIndex: "category", key: "category", render: (v) => <Tag color={v === "moving" ? "red" : "gold"}>{v === "moving" ? "Moving" : "Parking"}</Tag> },
    { title: "1st", dataIndex: "fine_first", key: "fine_first", render: (v) => `$${Number(v).toFixed(0)}` },
    { title: "2nd", dataIndex: "fine_second", key: "fine_second", render: (v) => v ? `$${Number(v).toFixed(0)}` : "—" },
    { title: "3rd+", dataIndex: "fine_third_plus", key: "fine_third_plus", render: (v) => v ? `$${Number(v).toFixed(0)}` : "—" },
    { title: "Status", dataIndex: "is_active", key: "is_active", render: (v) => <Tag color={v ? "green" : "default"}>{v ? "Active" : "Inactive"}</Tag> },
    {
      title: "Actions", key: "actions", width: 140,
      render: (_, vt) => (
        <Space>
          <Button type="link" size="small" onClick={() => { setEditing(vt); setCreating(false); }}>Edit</Button>
          {vt.is_active && <Button type="link" size="small" danger onClick={() => handleDeactivate(vt.id)}>Deactivate</Button>}
          {!vt.is_active && <Button type="link" size="small" danger onClick={() => handleDelete(vt.id, vt.label)}>Delete</Button>}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Violation Types</h2>
        <Button type="primary" onClick={() => { setCreating(true); setEditing(null); }}>+ New Violation Type</Button>
      </div>
      {(creating || editing) && (
        <ViolationTypeForm initial={editing ?? undefined}
          onSave={() => { setCreating(false); setEditing(null); load(); }}
          onCancel={() => { setCreating(false); setEditing(null); }} />
      )}
      <Table dataSource={types} columns={columns} rowKey="id" loading={loading} size="small"
        rowClassName={(vt) => !vt.is_active ? "opacity-50" : ""}
        pagination={false}
        locale={{ emptyText: <Empty description="No violation types configured" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />
    </div>
  );
}
