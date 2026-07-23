import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";
import {
  Table, Button, Input, InputNumber, Select, Checkbox, Tag, Card, Form, DatePicker, Space, App, Empty, Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

interface PermitTypeRow {
  id: string; code: string; label: string; eligible: string; price: string;
  max_capacity: number; valid_days: number; lot_assignments: string[];
  time_restriction: string | null; is_purchasable_online: boolean;
  is_active: boolean; sort_order: number; active_count: number; remaining: number;
  requires_lottery: boolean; lottery_strategy: string; min_class_year: number | null;
  application_opens_at: string | null; application_closes_at: string | null;
  offer_window_days: number; lottery_run_at: string | null;
}

interface LotForSelect {
  id: string;
  name: string;
  designation_code: string;
  total_spaces: number;
  lot_type: string;
  access_schedule: { season: string; rules: { allowed_permit_types: string[] }[] }[];
}

function getLotsForPermitCode(lots: LotForSelect[], code: string): string[] {
  return lots
    .filter(lot =>
      lot.access_schedule?.some(season =>
        season.rules?.some(rule =>
          rule.allowed_permit_types?.includes(code)
        )
      )
    )
    .map(lot => lot.name);
}

function PermitTypeForm({ initial, onSave, onCancel, lots }: { initial?: PermitTypeRow; onSave: () => void; onCancel: () => void; lots: LotForSelect[] }) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const requiresLottery = Form.useWatch("requires_lottery", form);
  const code = Form.useWatch("code", form);

  useEffect(() => {
    if (initial) {
      form.setFieldsValue({
        ...initial,
        lot_assignments: initial.lot_assignments,
        min_class_year: initial.min_class_year?.toString() ?? "",
        application_opens_at: initial.application_opens_at ? dayjs(initial.application_opens_at) : null,
        application_closes_at: initial.application_closes_at ? dayjs(initial.application_closes_at) : null,
      });
    } else { form.resetFields(); }
  }, [initial, form]);

  function autoPopulateLots() {
    if (!code) { message.warning("Enter a permit type code first"); return; }
    const matched = getLotsForPermitCode(lots, code);
    if (matched.length === 0) {
      message.info(`No lots have "${code}" in their access schedule rules`);
      return;
    }
    form.setFieldsValue({ lot_assignments: matched });
    message.success(`Found ${matched.length} lot(s) with "${code}" in access rules`);
  }

  async function handleFinish(values: any) {
    setSaving(true);
    const body: Record<string, unknown> = {
      code: values.code, label: values.label, eligible: values.eligible, price: values.price,
      max_capacity: values.max_capacity, valid_days: values.valid_days,
      lot_assignments: values.lot_assignments || [],
      is_purchasable_online: values.is_purchasable_online ?? false,
      sort_order: values.sort_order ?? 0,
      requires_lottery: values.requires_lottery ?? false,
      lottery_strategy: values.lottery_strategy ?? "seniority_timestamp",
      min_class_year: values.min_class_year ? parseInt(values.min_class_year) : null,
      offer_window_days: values.offer_window_days ?? 5,
      application_opens_at: values.application_opens_at?.toISOString() ?? null,
      application_closes_at: values.application_closes_at?.toISOString() ?? null,
    };
    try {
      const method = initial ? "PUT" : "POST";
      const url = initial ? `/api/permit-types/${initial.id}` : "/api/permit-types";
      const res = await fetch(url, { method, headers: await authHeaders(), body: JSON.stringify(body) });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as any).detail || `Failed (${res.status})`);
      }
      message.success(initial ? "Permit type updated" : "Permit type created");
      onSave();
    } catch (e: any) { message.error(e.message || "Failed to save"); } finally { setSaving(false); }
  }

  const lotOptions = lots.map(l => ({
    label: `${l.name}${l.designation_code ? ` (${l.designation_code})` : ""} — ${l.total_spaces} spaces`,
    value: l.name,
  }));

  return (
    <Card className="mb-6">
      <Form form={form} layout="vertical" onFinish={handleFinish}
        initialValues={{ price: "0.00", max_capacity: 100, valid_days: 365, sort_order: 0, lottery_strategy: "seniority_timestamp", offer_window_days: 5, lot_assignments: [] }}>
        <div className="grid grid-cols-2 gap-x-4">
          <Form.Item name="code" label="Code" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="label" label="Label" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="eligible" label="Eligible"><Input placeholder="Who can purchase" /></Form.Item>
          <Form.Item name="price" label="Price ($)"><Input type="number" step="0.01" /></Form.Item>
          <Form.Item name="max_capacity" label="Max Capacity"><InputNumber className="w-full" /></Form.Item>
          <Form.Item name="valid_days" label="Valid Days"><InputNumber className="w-full" /></Form.Item>
          <Form.Item name="lot_assignments" label={
            <span className="flex items-center gap-2">
              Lot Assignments
              <Tooltip title="Auto-fill lots whose access schedule includes this permit type code">
                <Button type="link" size="small" className="!p-0 !h-auto text-xs" onClick={autoPopulateLots}>Auto from schedule</Button>
              </Tooltip>
            </span>
          }>
            <Select
              mode="multiple"
              options={lotOptions}
              placeholder="Select lots..."
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item name="sort_order" label="Sort Order"><InputNumber className="w-full" /></Form.Item>
        </div>
        <Space className="mb-4">
          <Form.Item name="is_purchasable_online" valuePropName="checked" noStyle><Checkbox>Always available for purchase (no lottery)</Checkbox></Form.Item>
          <Form.Item name="requires_lottery" valuePropName="checked" noStyle><Checkbox>Requires lottery</Checkbox></Form.Item>
        </Space>
        {requiresLottery && (
          <>
            <h4 className="text-sm font-semibold text-brand-primary mb-3 mt-4 pt-4 border-t">Lottery Configuration</h4>
            <div className="grid grid-cols-2 gap-x-4">
              <Form.Item name="lottery_strategy" label="Strategy">
                <Select options={[
                  { label: "Seniority + Timestamp (default)", value: "seniority_timestamp" },
                  { label: "Seniority Weighted", value: "seniority_weighted" },
                  { label: "Pure Random", value: "pure_random" },
                  { label: "Class Priority", value: "class_priority" },
                ]} />
              </Form.Item>
              <Form.Item name="min_class_year" label="Min. Class Year (blank = all)">
                <Input type="number" placeholder="e.g. 2027" />
              </Form.Item>
              <Form.Item name="offer_window_days" label="Offer Window (days)"><InputNumber className="w-full" min={1} max={30} /></Form.Item>
              <Form.Item name="application_opens_at" label="Application Opens"><DatePicker showTime className="w-full" /></Form.Item>
              <Form.Item name="application_closes_at" label="Application Closes"><DatePicker showTime className="w-full" /></Form.Item>
            </div>
          </>
        )}
        <div className="flex justify-end gap-3 pt-2">
          <Button onClick={onCancel}>Cancel</Button>
          <Button type="primary" htmlType="submit" loading={saving}>{initial ? "Update" : "Create"}</Button>
        </div>
      </Form>
    </Card>
  );
}

export default function PermitTypes({ onManageLottery, editTypeId, onEditTypeHandled }: {
  onManageLottery?: (typeId: string) => void;
  editTypeId?: string | null;
  onEditTypeHandled?: () => void;
} = {}) {
  const { modal, message } = App.useApp();
  const [types, setTypes] = useState<PermitTypeRow[]>([]);
  const [lots, setLots] = useState<LotForSelect[]>([]);
  const [editing, setEditing] = useState<PermitTypeRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ptRes, lotRes] = await Promise.all([
        fetch("/api/permit-types?all=true", { headers: await authHeaders() }),
        fetch("/api/lots", { headers: await authHeaders() }),
      ]);
      if (ptRes.ok) setTypes(await ptRes.json());
      if (lotRes.ok) setLots(await lotRes.json());
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (editTypeId && types.length > 0) {
      const match = types.find(t => t.id === editTypeId);
      if (match) { setEditing(match); setCreating(false); }
      onEditTypeHandled?.();
    }
  }, [editTypeId, types, onEditTypeHandled]);

  function handleDeactivate(pt: PermitTypeRow) {
    modal.confirm({
      title: `Deactivate "${pt.label}"?`,
      content: "This will hide the permit type from students, stop new purchases, and remove it from lottery. Existing permits are not affected. You can reactivate it later.",
      okText: "Deactivate Permit Type", okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const res = await fetch(`/api/permit-types/${pt.id}`, {
            method: "PUT",
            headers: { ...(await authHeaders()), "Content-Type": "application/json" },
            body: JSON.stringify({ is_active: false }),
          });
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error((body as any).detail || `Failed (${res.status})`);
          }
          message.success("Deactivated");
          load();
        } catch (e: any) { message.error(e.message || "Failed to deactivate"); }
      },
    });
  }

  async function handleActivate(id: string) {
    try {
      await fetch(`/api/permit-types/${id}`, {
        method: "PUT",
        headers: { ...(await authHeaders()), "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: true }),
      });
      message.success("Activated");
      load();
    } catch { message.error("Failed to activate"); }
  }

  function handleDelete(pt: PermitTypeRow) {
    modal.confirm({
      title: `Permanently delete "${pt.label}"?`,
      content: "This will permanently remove this permit type and all associated lottery applications. This cannot be undone.",
      okText: "Delete Permanently",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const res = await fetch(`/api/permit-types/${pt.id}/permanent-delete`, {
            method: "POST",
            headers: await authHeaders(),
          });
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error((body as any).detail || "Failed to delete");
          }
          message.success("Permit type deleted");
          load();
        } catch (e: any) { message.error(e.message); }
      },
    });
  }

  function handleToggleLottery(pt: PermitTypeRow) {
    if (pt.requires_lottery) {
      modal.confirm({
        title: `Disable lottery for "${pt.label}"?`,
        content: "The permit type will stay active. Students will no longer apply through the lottery — it will become a regular permit. Existing applications are preserved.",
        okText: "Disable Lottery",
        onOk: async () => {
          try {
            const res = await fetch(`/api/permit-types/${pt.id}`, { method: "PUT", headers: await authHeaders(), body: JSON.stringify({ requires_lottery: false }) });
            if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error((b as any).detail || `Failed (${res.status})`); }
            message.success("Lottery disabled"); load();
          } catch (e: any) { message.error(e.message); }
        },
      });
    } else {
      modal.confirm({
        title: `Enable lottery for "${pt.label}"?`,
        content: "Students will need to apply through the lottery to get this permit type.",
        okText: "Enable Lottery",
        onOk: async () => {
          try {
            const res = await fetch(`/api/permit-types/${pt.id}`, { method: "PUT", headers: await authHeaders(), body: JSON.stringify({ requires_lottery: true, lottery_strategy: "seniority_timestamp" }) });
            if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error((b as any).detail || `Failed (${res.status})`); }
            message.success("Lottery enabled"); load();
          } catch (e: any) { message.error(e.message); }
        },
      });
    }
  }

  const COMMUTER_CODES = new Set(["commuter_undergrad", "commuter_grad"]);
  const lotLookup: Record<string, LotForSelect> = {};
  for (const l of lots) {
    const name = l.name.trim();
    lotLookup[name] = l;
    if (l.id) lotLookup[l.id] = l;
    // "Lot A" → also register "A" so short-form lot_assignments match
    const lotPrefix = name.match(/^Lot\s+(.+)$/i);
    if (lotPrefix) lotLookup[lotPrefix[1]] = l;
  }

  function calcCapacity(pt: PermitTypeRow) {
    let fullTime = 0, afterFour = 0;
    for (const rawName of pt.lot_assignments) {
      const lot = lotLookup[rawName.trim()];
      if (!lot) continue;
      const restricted = COMMUTER_CODES.has(pt.code) && (lot.designation_code === "FS" || lot.designation_code === "FSC");
      if (restricted) afterFour += lot.total_spaces;
      else fullTime += lot.total_spaces;
    }
    return { fullTime, afterFour, total: fullTime + afterFour };
  }

  const columns: ColumnsType<PermitTypeRow> = [
    { title: "Label", dataIndex: "label", key: "label", render: (v, pt) => (
      <span className={`font-medium ${!pt.is_active ? "line-through text-ink-mute" : ""}`}>{v}</span>
    )},
    { title: <Tooltip title="Orange = after 4pm only (FS/FSC) · Blue = street parking">Lots</Tooltip>, key: "lots", render: (_, pt) => {
      if (!pt.lot_assignments.length) return <span className="text-ink-mute">—</span>;
      return (
        <div className="flex flex-wrap gap-1">
          {pt.lot_assignments.map(l => {
            const lot = lotLookup[l.trim()];
            const isRestricted = lot && COMMUTER_CODES.has(pt.code) && (lot.designation_code === "FS" || lot.designation_code === "FSC");
            const isStreet = lot && lot.lot_type === "street";
            const color = isRestricted ? "orange" : isStreet ? "blue" : undefined;
            return <Tag key={l} color={color} className="!m-0 !text-[11px]">{l}{isRestricted ? " *" : ""}</Tag>;
          })}
        </div>
      );
    }},
    { title: "Price", dataIndex: "price", key: "price", render: v => Number(v) === 0 ? "Free" : `$${Number(v).toFixed(0)}` },
    { title: "Capacity", dataIndex: "max_capacity", key: "capacity" },
    { title: "Calculated Capacity", key: "calc_capacity", render: (_, pt) => {
      if (!pt.lot_assignments.length) return <span className="text-ink-mute">—</span>;
      const calc = calcCapacity(pt);
      if (calc.total === 0) return <span className="text-ink-mute">—</span>;
      return (
        <div>
          <div className="font-medium">{calc.total} spots</div>
          {calc.afterFour > 0 && (
            <div className="text-[11px] text-ink-mute">{calc.fullTime} full-time + {calc.afterFour} after 4pm</div>
          )}
        </div>
      );
    }},
    {
      title: "Usage", key: "usage",
      render: (_, pt) => (
        <Space>
          <span className="text-ink-mute">{pt.active_count}</span>
          <span>/</span>
          <span className={pt.remaining === 0 ? "text-red-600 font-medium" : "text-green-600"}>{pt.remaining} left</span>
        </Space>
      ),
    },
    {
      title: "Status", key: "type",
      render: (_, pt) => !pt.is_active
        ? <Tag color="red">Inactive</Tag>
        : pt.requires_lottery
          ? <Tag color="purple">Lottery</Tag>
          : pt.is_purchasable_online ? <Tag color="green">Always Available</Tag> : <Tag>Admin-Issued</Tag>,
    },
    { title: "Code", dataIndex: "code", key: "code", render: v => <span className="font-mono text-xs">{v}</span> },
    {
      title: "Actions", key: "actions", width: 240,
      render: (_, pt) => (
        <Space>
          <Button type="link" size="small" onClick={() => { setEditing(pt); setCreating(false); }}>Edit</Button>
          {pt.is_active && (
            <Button type="link" size="small" onClick={() => handleToggleLottery(pt)}
              style={pt.requires_lottery ? { color: "#9333ea" } : undefined}>
              {pt.requires_lottery ? "Disable Lottery" : "Enable Lottery"}
            </Button>
          )}
          {pt.requires_lottery && pt.is_active && onManageLottery && (
            <Button type="link" size="small" style={{ color: "#9333ea" }} onClick={() => onManageLottery(pt.id)}>Manage Lottery &rarr;</Button>
          )}
          {pt.is_active
            ? <Button type="link" size="small" danger onClick={() => handleDeactivate(pt)}>Deactivate</Button>
            : <>
                <Button type="link" size="small" onClick={() => handleActivate(pt.id)}>Activate</Button>
                <Button type="link" size="small" danger onClick={() => handleDelete(pt)}>Delete</Button>
              </>
          }
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Permit Types</h2>
        <Button type="primary" onClick={() => { setCreating(true); setEditing(null); }}>+ New Permit Type</Button>
      </div>
      {(creating || editing) && (
        <PermitTypeForm initial={editing ?? undefined} lots={lots}
          onSave={() => { setCreating(false); setEditing(null); load(); }}
          onCancel={() => { setCreating(false); setEditing(null); }} />
      )}
      <Table dataSource={types} columns={columns} rowKey="id" loading={loading} size="small"
        rowClassName={pt => !pt.is_active ? "opacity-50" : ""}
        pagination={false}
        locale={{ emptyText: <Empty description="No permit types configured" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />
    </div>
  );
}
