import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Table, App, Tag, Space, Input, Popconfirm, Modal, Form } from "antd";
import { UploadOutlined, DeleteOutlined, SearchOutlined, PlusOutlined } from "@ant-design/icons";
import { authHeaders } from "../auth";

interface RosterEntry {
  id: string;
  student_id: string;
  email: string | null;
  first_name: string;
  last_name: string;
  reason: string;
  building: string | null;
  room: string | null;
  academic_year: string | null;
  created_at: string;
  has_permit?: boolean;
  permit_number?: string | null;
  permit_type?: string | null;
  matched_by?: string | null;
}

type PermitFilter = "all" | "issued" | "missing";

export default function FeeExemptRoster() {
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
      const res = await fetch("/api/admin/fee-exempt/roster", { headers: await authHeaders() });
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
      formData.append("reason", "RA");
      formData.append("academic_year", "2026-2027");
      formData.append("replace", replace ? "true" : "false");

      const headers = await authHeaders();
      delete (headers as any)["Content-Type"];
      const res = await fetch("/api/admin/fee-exempt/roster/upload", {
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
        content: `There are already ${entries.length} students on the roster. Do you want to replace them with this file, or add to the existing list?`,
        okText: "Replace all",
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
      const res = await fetch(`/api/admin/fee-exempt/roster/${id}`, {
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
      const res = await fetch("/api/admin/fee-exempt/roster", {
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
      const res = await fetch("/api/admin/fee-exempt/roster", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          student_id: values.student_id,
          email: values.email || null,
          first_name: values.first_name,
          last_name: values.last_name,
          reason: values.reason || "Res Life Staff",
          building: values.building || null,
          room: values.room || null,
          academic_year: "2026-2027",
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to add");
      }
      message.success("Person added to exempt roster");
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
    return `${e.first_name} ${e.last_name} ${e.student_id} ${e.email || ""} ${e.permit_number || ""}`
      .toLowerCase()
      .includes(search.toLowerCase());
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold m-0">RA Roster (50% Discount)</h3>
          <p className="text-sm text-gray-500 m-0">
            Students on this list receive their permit at no charge (RAs, RDs, etc.)
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
          <Button
            icon={<PlusOutlined />}
            onClick={() => setAddModalOpen(true)}
          >
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
              title={`Clear all ${entries.length} entries?`}
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
          { title: "Building", dataIndex: "building", key: "building", render: (v: string | null) => v || "—" },
          { title: "Room", dataIndex: "room", key: "room", width: 80, render: (v: string | null) => v || "—" },
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
            title: "Reason",
            dataIndex: "reason",
            key: "reason",
            render: (v: string) => <Tag color="blue">{v}</Tag>,
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
        Upload an Excel (.xlsx) or CSV file with columns: Moravian ID, Last, First, Building, Room.
        Students on this list get permits at $0 automatically — lottery accept and
        direct purchase both skip Stripe and show a thank-you confirmation.
      </div>

      <Modal
        title="Add Person to RA Roster"
        open={addModalOpen}
        onCancel={() => { setAddModalOpen(false); addForm.resetFields(); }}
        onOk={() => addForm.submit()}
        confirmLoading={addingSingle}
        okText="Add"
      >
        <Form form={addForm} layout="vertical" onFinish={handleAddSingle}>
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
            <Form.Item name="building" label="Building">
              <Input />
            </Form.Item>
            <Form.Item name="room" label="Room">
              <Input />
            </Form.Item>
          </div>
          <Form.Item name="reason" label="Reason" initialValue="RA">
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
