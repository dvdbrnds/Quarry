import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { api, Permit, ImportResult } from "../api";
import { authHeaders } from "../auth";
import {
  Table, Button, Input, Select, Tag, Card, Statistic, Modal, Form, DatePicker,
  Space, Tabs, Alert, App, Upload,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import LotteryManager from "./LotteryManager";

async function downloadWithAuth(url: string, filename: string) {
  const res = await fetch(url, { headers: await authHeaders() });
  if (!res.ok) return;
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

interface PermitStats {
  total: number;
  active: number;
  expired: number;
  expiring_soon: number;
  revoked: number;
}

interface PermitTypeOption { code: string; label: string; }
interface LotOption { id: string; name: string; }

function PermitForm({
  initial, permitTypes, lots, onSave, onCancel,
}: {
  initial?: Permit; permitTypes: PermitTypeOption[]; lots: LotOption[];
  onSave: () => void; onCancel: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (initial) {
      form.setFieldsValue({
        name: initial.name,
        plates: initial.plates.join(", "),
        student_id: initial.student_id,
        email: (initial as any).email ?? "",
        phone: (initial as any).phone ?? "",
        beacon_id: (initial as any).beacon_id ?? "",
        lot_assignment: initial.lot_assignment,
        permit_type: initial.permit_type,
        status: initial.status,
        start_date: initial.start_date ? dayjs(initial.start_date) : null,
        end_date: initial.end_date ? dayjs(initial.end_date) : null,
      });
    } else {
      form.resetFields();
    }
  }, [initial, form]);

  async function handleFinish(values: any) {
    setSaving(true);
    const data = {
      name: values.name,
      plates: values.plates.split(",").map((p: string) => p.trim().toUpperCase()).filter(Boolean),
      student_id: values.student_id,
      email: values.email || null,
      phone: values.phone || null,
      beacon_id: values.beacon_id || null,
      lot_assignment: values.lot_assignment,
      permit_type: values.permit_type,
      status: values.status || "active",
      start_date: values.start_date?.format("YYYY-MM-DD") || undefined,
      end_date: values.end_date?.format("YYYY-MM-DD") || null,
    };
    try {
      if (initial) {
        await api.permits.update(initial.id, data);
        message.success("Permit updated");
      } else {
        await api.permits.create(data);
        message.success("Permit created");
      }
      onSave();
    } catch {
      message.error("Failed to save permit");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="mb-6">
      <Form form={form} layout="vertical" onFinish={handleFinish}
        initialValues={{ status: "active", start_date: dayjs() }}>
        <div className="grid grid-cols-2 gap-x-4">
          <Form.Item name="name" label="Name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="plates" label="Plates (comma-separated)">
            <Input />
          </Form.Item>
          <Form.Item name="student_id" label="Student ID">
            <Input />
          </Form.Item>
          <Form.Item name="lot_assignment" label="Lot Assignment">
            <Select placeholder="— Select —" allowClear
              options={lots.map(l => ({ label: l.name, value: l.name }))} />
          </Form.Item>
          <Form.Item name="permit_type" label="Permit Type">
            <Select placeholder="— Select —" allowClear
              options={permitTypes.map(pt => ({ label: pt.label, value: pt.code }))} />
          </Form.Item>
          <Form.Item name="status" label="Status">
            <Select options={[
              { label: "Active", value: "active" },
              { label: "Expired", value: "expired" },
              { label: "Revoked", value: "revoked" },
              { label: "Suspended", value: "suspended" },
            ]} />
          </Form.Item>
          <Form.Item name="start_date" label="Start Date">
            <DatePicker className="w-full" />
          </Form.Item>
          <Form.Item name="end_date" label="End Date">
            <DatePicker className="w-full" />
          </Form.Item>
          <Form.Item name="email" label="Email">
            <Input type="email" placeholder="student@university.edu" />
          </Form.Item>
          <Form.Item name="phone" label="Phone">
            <Input placeholder="+1 (555) 123-4567" />
          </Form.Item>
          <Form.Item name="beacon_id" label="Beacon ID (SheepDog)">
            <Input placeholder="optional hangtag beacon ID" />
          </Form.Item>
        </div>
        <div className="flex justify-end gap-3">
          <Button onClick={onCancel}>Cancel</Button>
          <Button type="primary" htmlType="submit" loading={saving}>
            {initial ? "Update" : "Create"}
          </Button>
        </div>
      </Form>
    </Card>
  );
}

export default function Permits() {
  const { modal, message } = App.useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const fileRef = useRef<HTMLInputElement>(null);

  const [tab, setTab] = useState(location.hash === "#lottery" ? "lottery" : "permits");
  const [permits, setPermits] = useState<Permit[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterLot, setFilterLot] = useState("");
  const [sort, setSort] = useState("");
  const [editing, setEditing] = useState<Permit | null>(null);
  const [creating, setCreating] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [importing, setImporting] = useState(false);
  const [stats, setStats] = useState<PermitStats | null>(null);
  const [permitTypes, setPermitTypes] = useState<PermitTypeOption[]>([]);
  const [lots, setLots] = useState<LotOption[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkAction, setBulkAction] = useState("");
  const [loading, setLoading] = useState(true);
  const [duplicateGroups, setDuplicateGroups] = useState<Array<{
    shared_plate: string;
    permits: Array<{ id: string; name: string; student_id: string; lot_assignment: string; permit_type: string }>;
  }>>([]);
  const [showDuplicates, setShowDuplicates] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.permits.list({
        page, search: search || undefined, status: filterStatus || undefined,
        lot: filterLot || undefined, permit_type: filterType || undefined, sort: sort || undefined,
      });
      setPermits(data.items);
      setTotal(data.total);
    } catch {
      message.error("Failed to load permits");
    } finally {
      setLoading(false);
    }
  }, [page, search, filterStatus, filterType, filterLot, sort, message]);

  const loadMeta = useCallback(async () => {
    try {
      const [s, ptRes, lotsRes, dupRes] = await Promise.all([
        api.permits.stats(),
        fetch("/api/permit-types", { headers: await authHeaders() }).then(r => r.json()),
        api.lots.list(),
        fetch("/api/permits/duplicates", { headers: await authHeaders() }).then(r => r.ok ? r.json() : { duplicate_groups: [] }),
      ]);
      setStats(s);
      setPermitTypes(ptRes.map((pt: any) => ({ code: pt.code, label: pt.label })));
      setLots(lotsRes.map((l: any) => ({ id: l.id, name: l.name })));
      setDuplicateGroups(dupRes.duplicate_groups ?? []);
    } catch { /* silently fail */ }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadMeta(); }, [loadMeta]);

  function handleDelete(id: string) {
    modal.confirm({
      title: "Delete this permit?",
      content: "This action cannot be undone.",
      okText: "Delete",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await api.permits.delete(id);
          message.success("Permit deleted");
          load(); loadMeta();
        } catch { message.error("Failed to delete permit"); }
      },
    });
  }

  function handleBulkAction() {
    if (!bulkAction || selected.size === 0) return;
    modal.confirm({
      title: `Set ${selected.size} permits to "${bulkAction}"?`,
      onOk: async () => {
        try {
          await api.permits.bulkStatus(Array.from(selected), bulkAction);
          message.success(`${selected.size} permits updated`);
          setSelected(new Set()); setBulkAction(""); load(); loadMeta();
        } catch { message.error("Bulk action failed"); }
      },
    });
  }

  async function handleImport() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const text = await file.text();
      const lines = text.split("\n").filter(Boolean);
      if (lines.length < 2) return;
      const headers = lines[0].split(",").map(h => h.trim().toLowerCase());
      const permits = lines.slice(1).map(line => {
        const vals = line.split(",");
        const row: Record<string, string> = {};
        headers.forEach((h, i) => (row[h] = vals[i]?.trim() ?? ""));
        return {
          plate_normalized: row.plate_normalized || row.plate || "",
          owner_name: row.owner_name || row.name || "",
          permit_number: row.permit_number || row.student_id || "",
          permit_type: row.permit_type || "student",
          permit_status: row.permit_status || row.status || "active",
          lot_zone: row.lot_zone || row.lot || "",
        };
      });
      const result = await api.permits.importJson(permits);
      setImportResult(result);
      setShowImport(false);
      message.success(`Imported: ${result.inserted} new, ${result.updated} updated`);
      load(); loadMeta();
    } catch {
      message.error("Import failed");
    } finally {
      setImporting(false);
    }
  }

  const isExpiringSoon = (p: Permit) => {
    if (!p.end_date || p.status !== "active") return false;
    const diff = (new Date(p.end_date).getTime() - Date.now()) / 86_400_000;
    return diff >= 0 && diff <= 30;
  };

  const columns: ColumnsType<Permit> = [
    { title: "Name", dataIndex: "name", key: "name", sorter: true, render: (name) => <span className="font-medium">{name}</span> },
    { title: "Student ID", dataIndex: "student_id", key: "student_id", sorter: true, render: (v) => v || "—" },
    { title: "Plates", dataIndex: "plates", key: "plates", render: (plates: string[]) => <span className="font-mono text-xs">{plates.join(", ")}</span> },
    { title: "Lot", dataIndex: "lot_assignment", key: "lot_assignment", sorter: true },
    { title: "Type", dataIndex: "permit_type", key: "permit_type", sorter: true, render: (v) => <span className="capitalize">{v}</span> },
    { title: "Issued", dataIndex: "start_date", key: "start_date", sorter: true, render: (v) => v || "—" },
    {
      title: "Expires", dataIndex: "end_date", key: "end_date", sorter: true,
      render: (v, p) => v ? <span className={isExpiringSoon(p) ? "text-amber-600 font-medium" : ""}>{v}</span> : <span className="text-ink-mute">—</span>,
    },
    {
      title: "Status", dataIndex: "status", key: "status", sorter: true,
      render: (status, p) => (
        <Space>
          <Tag color={status === "active" ? "green" : status === "expired" || status === "renewed" ? "default" : "red"}>{status}</Tag>
          {isExpiringSoon(p) && <Tag color="gold">EXPIRING</Tag>}
        </Space>
      ),
    },
    {
      title: "Actions", key: "actions", width: 120,
      render: (_, p) => (
        <Space onClick={e => e.stopPropagation()}>
          <Button type="link" size="small" onClick={() => { setEditing(p); setCreating(false); }}>Edit</Button>
          <Button type="link" size="small" danger onClick={() => handleDelete(p.id)}>Del</Button>
        </Space>
      ),
    },
  ];

  const statCards = stats ? [
    { label: "Total", value: stats.total, filter: "", color: undefined as string | undefined },
    { label: "Active", value: stats.active, filter: "active", color: "#22C55E" },
    { label: "Expiring Soon", value: stats.expiring_soon, filter: "expiring_soon", color: "#F59E0B" },
    { label: "Expired", value: stats.expired, filter: "expired", color: "#EF4444" },
    { label: "Revoked", value: stats.revoked, filter: "revoked", color: undefined },
  ] : [];

  return (
    <div>
      <Tabs
        activeKey={tab}
        onChange={(key) => { setTab(key); window.location.hash = key === "lottery" ? "lottery" : ""; }}
        items={[
          {
            key: "permits",
            label: "Permits",
            children: (
              <div>
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-2xl font-bold">Permits</h2>
                  <Space>
                    <Button onClick={() => setShowImport(true)}>Import CSV</Button>
                    <Button onClick={() => downloadWithAuth("/api/permits/export/csv", "permits.csv")}>Export CSV</Button>
                    <Button type="primary" onClick={() => { setCreating(true); setEditing(null); }}>+ New Permit</Button>
                  </Space>
                </div>

                {stats && (
                  <div className="grid grid-cols-5 gap-3 mb-4">
                    {statCards.map(sc => (
                      <Card key={sc.label} size="small" hoverable
                        className={filterStatus === sc.filter ? "!border-brass !shadow-md" : ""}
                        onClick={() => { setFilterStatus(sc.filter); setPage(1); }}>
                        <Statistic title={sc.label} value={sc.value}
                          valueStyle={sc.color ? { color: sc.color, fontWeight: 700 } : { fontWeight: 700 }} />
                      </Card>
                    ))}
                  </div>
                )}

                {duplicateGroups.length > 0 && (
                  <Alert
                    type="warning"
                    className="mb-4"
                    showIcon
                    message={`${duplicateGroups.length} duplicate plate conflict${duplicateGroups.length > 1 ? "s" : ""} detected`}
                    description={showDuplicates ? (
                      <div className="mt-2 space-y-3">
                        {duplicateGroups.map(group => (
                          <Card size="small" key={group.shared_plate}>
                            <div className="text-xs font-mono font-bold text-amber-800 mb-2">Shared plate: {group.shared_plate}</div>
                            {group.permits.map(p => (
                              <div key={p.id} className="flex items-center gap-3 text-xs">
                                <span className="font-medium">{p.name}</span>
                                {p.student_id && <span className="text-ink-mute">{p.student_id}</span>}
                                <span className="text-ink-mute">{p.lot_assignment}</span>
                                <span className="text-ink-mute capitalize">{p.permit_type}</span>
                                <Button type="link" size="small" onClick={() => navigate(`/permits/${p.id}`)}>View</Button>
                              </div>
                            ))}
                          </Card>
                        ))}
                      </div>
                    ) : undefined}
                    action={<Button size="small" type="text" onClick={() => setShowDuplicates(!showDuplicates)}>{showDuplicates ? "Hide" : "Review"}</Button>}
                  />
                )}

                <Space className="mb-4" wrap>
                  <Input.Search
                    placeholder="Search name, ID, or plate..."
                    value={search}
                    onChange={e => { setSearch(e.target.value); setPage(1); }}
                    style={{ width: 280 }}
                    allowClear
                  />
                  <Select value={filterStatus || undefined} onChange={v => { setFilterStatus(v || ""); setPage(1); }}
                    placeholder="All Statuses" allowClear style={{ width: 160 }}
                    options={[
                      { label: "Active", value: "active" },
                      { label: "Expiring Soon", value: "expiring_soon" },
                      { label: "Expired", value: "expired" },
                      { label: "Revoked", value: "revoked" },
                      { label: "Suspended", value: "suspended" },
                    ]}
                  />
                  <Select value={filterType || undefined} onChange={v => { setFilterType(v || ""); setPage(1); }}
                    placeholder="All Types" allowClear style={{ width: 140 }}
                    options={permitTypes.map(pt => ({ label: pt.label, value: pt.code }))}
                  />
                  <Select value={filterLot || undefined} onChange={v => { setFilterLot(v || ""); setPage(1); }}
                    placeholder="All Lots" allowClear style={{ width: 140 }}
                    options={lots.map(l => ({ label: l.name, value: l.name }))}
                  />
                  {(filterStatus || filterType || filterLot) && (
                    <Button type="link" danger size="small"
                      onClick={() => { setFilterStatus(""); setFilterType(""); setFilterLot(""); setPage(1); }}>
                      Clear Filters
                    </Button>
                  )}
                </Space>

                {importResult && (
                  <Alert className="mb-4" type="success" closable onClose={() => setImportResult(null)}
                    message={`Imported: ${importResult.inserted} new, ${importResult.updated} updated, ${importResult.skipped} skipped`}
                  />
                )}

                {(creating || editing) && (
                  <PermitForm initial={editing ?? undefined} permitTypes={permitTypes} lots={lots}
                    onSave={() => { setCreating(false); setEditing(null); load(); loadMeta(); }}
                    onCancel={() => { setCreating(false); setEditing(null); }}
                  />
                )}

                {selected.size > 0 && (
                  <div className="flex items-center gap-3 mb-3 bg-navy/5 rounded-lg px-4 py-2">
                    <span className="text-sm font-medium">{selected.size} selected</span>
                    <Select value={bulkAction || undefined} onChange={v => setBulkAction(v || "")}
                      placeholder="— Action —" style={{ width: 140 }}
                      options={[
                        { label: "Revoke", value: "revoked" },
                        { label: "Expire", value: "expired" },
                        { label: "Suspend", value: "suspended" },
                        { label: "Reactivate", value: "active" },
                      ]}
                    />
                    <Button type="primary" size="small" disabled={!bulkAction} onClick={handleBulkAction}>Apply</Button>
                    <Button type="text" size="small" className="ml-auto" onClick={() => setSelected(new Set())}>Deselect All</Button>
                  </div>
                )}

                <Table
                  dataSource={permits}
                  columns={columns}
                  rowKey="id"
                  loading={loading}
                  rowSelection={{
                    selectedRowKeys: Array.from(selected),
                    onChange: (keys) => setSelected(new Set(keys as string[])),
                  }}
                  onRow={(p) => ({
                    onClick: () => navigate(`/permits/${p.id}`),
                    className: "cursor-pointer",
                  })}
                  onChange={(_pagination, _filters, sorter: any) => {
                    if (sorter.field) {
                      setSort(sorter.order === "descend" ? `-${sorter.field}` : sorter.order === "ascend" ? sorter.field : "");
                    }
                  }}
                  pagination={{
                    current: page, total, pageSize: 50, onChange: setPage,
                    showSizeChanger: false, showTotal: t => `${t} permits`,
                  }}
                />

                <Modal open={showImport} title="Import Permits (CSV)" onCancel={() => setShowImport(false)}
                  okText="Import" confirmLoading={importing} onOk={handleImport}>
                  <p className="text-sm text-ink-mute mb-4">
                    CSV columns: <code>plate_normalized</code>, <code>owner_name</code>, <code>permit_number</code>, <code>permit_type</code>, <code>lot_zone</code>
                  </p>
                  <input ref={fileRef} type="file" accept=".csv" />
                </Modal>
              </div>
            ),
          },
          {
            key: "lottery",
            label: "Lottery",
            children: <LotteryManager />,
          },
        ]}
      />
    </div>
  );
}
