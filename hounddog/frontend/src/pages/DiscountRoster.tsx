import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Table, App, Tag, Space, Input, Popconfirm, Modal, Form, InputNumber } from "antd";
import { UploadOutlined, DeleteOutlined, SearchOutlined, PlusOutlined } from "@ant-design/icons";
import { authHeaders } from "../auth";

interface RosterEntry {
  id: string;
  student_id: string;
  email: string | null;
  first_name: string;
  last_name: string;
  program_name: string;
  discount_amount: number;
  academic_year: string | null;
  created_at: string;
  has_permit?: boolean;
  permit_number?: string | null;
  permit_type?: string | null;
  matched_by?: string | null;
}

type PermitFilter = "all" | "issued" | "missing";

export default function DiscountRoster() {
  const { message, modal } = App.useApp();
  const [entries, setEntries] = useState<RosterEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [search, setSearch] = useState("");
  const [permitFilter, setPermitFilter] = useState<PermitFilter>("all");
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [addForm] = Form.useForm();
  const [addingSingle, setAddingSingle] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/admin/discounts/roster", { headers: await authHeaders() });
      if (!res.ok) throw new Error("Failed to load");
      setEntries(await res.json());
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => { load(); }, [load]);

  async function handleUpload(file: File, replace: boolean) {
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("program_name", "ABSN");
      formData.append("discount_amount", "100");
      formData.append("academic_year", "2026-2027");
      formData.append("replace", replace ? "true" : "false");

      const headers = await authHeaders();
      delete (headers as any)["Content-Type"];
      const res = await fetch("/api/admin/discounts/roster/upload", {
        method: "POST",
        headers,
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Upload failed");
      }
      const result = await res.json();
      message.success(`Imported ${result.imported} students${result.skipped ? ` (${result.skipped} skipped)` : ""}`);
      if (result.errors?.length) {
        message.warning(result.errors.slice(0, 3).join("; "));
      }
      load();
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function promptUpload(file: File) {
    if (entries.length > 0) {
      modal.confirm({
        title: "Replace or append?",
        content: `There are already ${entries.length} students on the ABSN discount list. Replace them with this file, or append?`,
        okText: "Replace ABSN list",
        cancelText: "Append",
        okButtonProps: { danger: true },
        onOk: () => handleUpload(file, true),
        onCancel: () => handleUpload(file, false),
      });
    } else {
      handleUpload(file, false);
    }
  }

  async function handleDelete(id: string) {
    try {
      const res = await fetch(`/api/admin/discounts/roster/${id}`, {
        method: "DELETE",
        headers: await authHeaders(),
      });
      if (!res.ok) throw new Error("Delete failed");
      message.success("Removed");
      load();
    } catch (e: any) {
      message.error(e.message);
    }
  }

  async function handleClearAll() {
    try {
      const res = await fetch("/api/admin/discounts/roster?program_name=ABSN", {
        method: "DELETE",
        headers: await authHeaders(),
      });
      if (!res.ok) throw new Error("Clear failed");
      const data = await res.json();
      message.success(`Cleared ${data.deleted} entries`);
      load();
    } catch (e: any) {
      message.error(e.message);
    }
  }

  async function handleAddSingle(values: any) {
    setAddingSingle(true);
    try {
      const headers = await authHeaders();
      const res = await fetch("/api/admin/discounts/roster", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          student_id: values.student_id,
          email: values.email || null,
          first_name: values.first_name,
          last_name: values.last_name,
          program_name: values.program_name || "ABSN",
          discount_amount: values.discount_amount ?? 100,
          academic_year: "2026-2027",
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to add");
      }
      message.success("Person added to ABSN discount list");
      setAddModalOpen(false);
      addForm.resetFields();
      load();
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setAddingSingle(false);
    }
  }

  const issuedCount = entries.filter((e) => e.has_permit).length;
  const missingCount = entries.length - issuedCount;

  const filtered = entries.filter((e) => {
    if (permitFilter === "issued" && !e.has_permit) return false;
    if (permitFilter === "missing" && e.has_permit) return false;
    if (!search) return true;
    return `${e.first_name} ${e.last_name} ${e.student_id} ${e.email || ""} ${e.program_name} ${e.permit_number || ""}`
      .toLowerCase()
      .includes(search.toLowerCase());
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold m-0">ABSN / Program Discount</h3>
          <p className="text-sm text-gray-500 m-0">
            Students on this list automatically get $100 off at checkout — no voucher code needed.
            {entries.length > 0 && (
              <>
                {" "}· <strong>{issuedCount}</strong> issued · <strong>{missingCount}</strong> not yet
              </>
            )}
          </p>
        </div>
        <Space>
          <Input
            prefix={<SearchOutlined />}
            placeholder="Search..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: 200 }}
            allowClear
          />
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.csv"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) promptUpload(f);
            }}
          />
          <Button icon={<PlusOutlined />} onClick={() => setAddModalOpen(true)}>
            Add Person
          </Button>
          <Button
            type="primary"
            icon={<UploadOutlined />}
            loading={uploading}
            onClick={() => fileRef.current?.click()}
          >
            Upload List
          </Button>
          {entries.length > 0 && (
            <Popconfirm
              title={`Clear all ${entries.length} ABSN entries?`}
              onConfirm={handleClearAll}
              okText="Clear"
              okType="danger"
            >
              <Button danger icon={<DeleteOutlined />}>Clear All</Button>
            </Popconfirm>
          )}
        </Space>
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        {(
          [
            ["all", `All (${entries.length})`],
            ["issued", `Permit issued (${issuedCount})`],
            ["missing", `Not yet (${missingCount})`],
          ] as [PermitFilter, string][]
        ).map(([key, label]) => (
          <Tag
            key={key}
            color={permitFilter === key ? "blue" : "default"}
            className="cursor-pointer px-2 py-0.5"
            onClick={() => setPermitFilter(key)}
          >
            {label}
          </Tag>
        ))}
      </div>

      <Table
        dataSource={filtered}
        loading={loading}
        rowKey="id"
        size="small"
        pagination={{ pageSize: 25, showSizeChanger: true }}
        columns={[
          { title: "ID", dataIndex: "student_id", key: "student_id", width: 100 },
          {
            title: "Name",
            key: "name",
            render: (_, r) => `${r.first_name} ${r.last_name}`,
            sorter: (a, b) => a.last_name.localeCompare(b.last_name),
          },
          { title: "Email", dataIndex: "email", key: "email", render: (v: string | null) => v || "—" },
          {
            title: "Program",
            dataIndex: "program_name",
            key: "program_name",
            render: (v: string) => <Tag color="geekblue">{v}</Tag>,
          },
          {
            title: "Discount",
            dataIndex: "discount_amount",
            key: "discount_amount",
            width: 100,
            render: (v: number) => `$${Number(v).toFixed(0)}`,
          },
          {
            title: "Permit",
            key: "permit",
            width: 160,
            filters: [
              { text: "Issued", value: true },
              { text: "Not yet", value: false },
            ],
            onFilter: (value, record) => !!record.has_permit === value,
            render: (_, r) =>
              r.has_permit ? (
                <span title={r.matched_by ? `Matched by ${r.matched_by}` : undefined}>
                  <Tag color="green">Issued</Tag>
                  <span className="text-xs text-gray-500">
                    {r.permit_number || r.permit_type || ""}
                  </span>
                </span>
              ) : (
                <Tag>Not yet</Tag>
              ),
            sorter: (a, b) => Number(!!a.has_permit) - Number(!!b.has_permit),
          },
          {
            title: "",
            key: "actions",
            width: 60,
            render: (_, r) => (
              <Popconfirm title="Remove?" onConfirm={() => handleDelete(r.id)} okType="danger">
                <Button type="link" size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            ),
          },
        ]}
      />

      <div className="text-xs text-gray-400 mt-3">
        Upload Excel (.xlsx) or CSV with columns: Moravian ID, Last, First, Email (optional).
        Matched students see a discounted price and are charged $100 less at Stripe checkout.
      </div>

      <Modal
        title="Add Person to Discount List"
        open={addModalOpen}
        onCancel={() => { setAddModalOpen(false); addForm.resetFields(); }}
        onOk={() => addForm.submit()}
        confirmLoading={addingSingle}
        okText="Add"
      >
        <Form form={addForm} layout="vertical" onFinish={handleAddSingle}
          initialValues={{ program_name: "ABSN", discount_amount: 100 }}>
          <div className="grid grid-cols-2 gap-x-3">
            <Form.Item name="first_name" label="First Name" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="last_name" label="Last Name" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
          </div>
          <Form.Item name="student_id" label="Student / Moravian ID" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="email" label="Email">
            <Input type="email" placeholder="student@moravian.edu" />
          </Form.Item>
          <div className="grid grid-cols-2 gap-x-3">
            <Form.Item name="program_name" label="Program">
              <Input />
            </Form.Item>
            <Form.Item name="discount_amount" label="Discount ($)">
              <InputNumber min={1} max={500} className="!w-full" />
            </Form.Item>
          </div>
        </Form>
      </Modal>
    </div>
  );
}
