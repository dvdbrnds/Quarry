import { useCallback, useEffect, useRef, useState } from "react";
import { authHeaders } from "../auth";
import {
  Table, Button, Input, InputNumber, Select, Checkbox, Tag, Card, Form, DatePicker, Space, App, Empty, Tooltip, Progress, Spin,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

/** External City lots — sold off-platform; never Quarry online purchase. */
const NO_ONLINE_PURCHASE_CODES = new Set([
  "south_standalone",
]);

interface WaitlistEntry {
  id: string;
  student_name: string;
  student_email: string;
  plate: string;
  waitlist_position: number | null;
  status: string;
  created_at: string;
  assigned_permit_type_id?: string | null;
  tier_preferences?: string[];
}

function progressColor(pct: number): string {
  if (pct >= 90) return "#dc2626";
  if (pct >= 70) return "#d97706";
  return "#16a34a";
}

interface PermitTypeRow {
  id: string; code: string; label: string; eligible: string; price: string;
  max_capacity: number; reserved_pct: number; reserved_spots: number; valid_days: number; lot_assignments: string[];
  time_restriction: string | null; is_purchasable_online: boolean;
  is_active: boolean; sort_order: number; active_count: number; remaining: number;
  requires_lottery: boolean; lottery_strategy: string; min_class_year: number | null;
  allow_freshmen: boolean; eligible_groups: string[]; allow_multiple: boolean;
  auto_advance_waitlist: boolean;
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
  const isPurchasableOnline = Form.useWatch("is_purchasable_online", form);
  const code = Form.useWatch("code", form);
  const blockOnlinePurchase = NO_ONLINE_PURCHASE_CODES.has(code || initial?.code || "");

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
      max_capacity: values.max_capacity, reserved_pct: values.reserved_pct ?? 0, reserved_spots: values.reserved_spots ?? 0, valid_days: values.valid_days,
      lot_assignments: values.lot_assignments || [],
      is_purchasable_online: NO_ONLINE_PURCHASE_CODES.has(values.code)
        ? false
        : (values.is_purchasable_online ?? false),
      sort_order: values.sort_order ?? 0,
      eligible_groups: values.eligible_groups || [],
      allow_multiple: values.allow_multiple ?? false,
      requires_lottery: values.requires_lottery ?? false,
      auto_advance_waitlist: values.auto_advance_waitlist ?? true,
      min_class_year: values.min_class_year ? parseInt(values.min_class_year) : null,
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
        initialValues={{ price: "0.00", max_capacity: 100, reserved_pct: 0, reserved_spots: 0, valid_days: 365, sort_order: 0, lot_assignments: [] }}>
        <div className="grid grid-cols-2 gap-x-4">
          <Form.Item name="code" label="Code" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="label" label="Label" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="eligible" label="Eligible"><Input placeholder="Who can purchase" /></Form.Item>
          <Form.Item name="price" label="Price ($)"><Input type="number" step="0.01" /></Form.Item>
          <Form.Item name="max_capacity" label="Max Capacity"><InputNumber className="w-full" /></Form.Item>
          <Form.Item name="reserved_pct" label={
            <Tooltip title="Percentage of capacity held back from lottery/sales for admin discretionary assignment">Reserved %</Tooltip>
          }><InputNumber className="w-full" min={0} max={100} addonAfter="%" /></Form.Item>
          <Form.Item name="reserved_spots" label={
            <Tooltip title="Fixed number of spots held back. The larger of this and the percentage is used.">Reserved (fixed)</Tooltip>
          }><InputNumber className="w-full" min={0} /></Form.Item>
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
          <Form.Item name="min_class_year" label="Min. Class Year (blank = all)">
            <Input type="number" placeholder="e.g. 2027" />
          </Form.Item>
          <Form.Item name="eligible_groups" label={
            <span className="flex items-center gap-2">
              Restrict to Groups
              <Tooltip title="Only users in these Okta groups can see this permit. Leave empty for all users.">
                <span className="text-xs text-ink-mute">ⓘ</span>
              </Tooltip>
            </span>
          }>
            <Select
              mode="tags"
              placeholder="e.g. Quarry-Staff (leave empty for everyone)"
              tokenSeparators={[","]}
            />
          </Form.Item>
        </div>
        <Space className="mb-4" wrap>
          {!blockOnlinePurchase && (
            <Form.Item name="is_purchasable_online" valuePropName="checked" noStyle>
              <Checkbox>Available for online purchase</Checkbox>
            </Form.Item>
          )}
          {blockOnlinePurchase && (
            <span className="text-sm text-ink-mute">Third-party lots are sold off-platform — online purchase disabled.</span>
          )}
          <Form.Item name="requires_lottery" valuePropName="checked" noStyle>
            <Checkbox>Requires lottery</Checkbox>
          </Form.Item>
          <Form.Item name="allow_multiple" valuePropName="checked" noStyle>
            <Checkbox>
              <Tooltip title="When enabled, a person can register multiple permits of this type (e.g. faculty with multiple vehicles). When disabled, each person is limited to one permit.">
                Allow multiple permits per person
              </Tooltip>
            </Checkbox>
          </Form.Item>
          <Form.Item name="auto_advance_waitlist" valuePropName="checked" noStyle>
            <Checkbox>
              <Tooltip title="When enabled, waitlisted applicants are automatically promoted when a spot opens (offer declined/expired). Disable to freeze the waitlist and advance manually.">
                Auto-advance waitlist
              </Tooltip>
            </Checkbox>
          </Form.Item>
        </Space>
        {isPurchasableOnline && !blockOnlinePurchase && (
          <>
            <h4 className="text-sm font-semibold text-brand-primary mb-3 mt-4 pt-4 border-t">
              Purchasing Schedule
            </h4>
            <div className="grid grid-cols-2 gap-x-4">
              <Form.Item name="application_opens_at" label="Purchasing Opens">
                <DatePicker showTime className="w-full" />
              </Form.Item>
              <Form.Item name="application_closes_at" label="Purchasing Closes">
                <DatePicker showTime className="w-full" />
              </Form.Item>
            </div>
            <p className="text-xs text-ink-mute -mt-2 mb-2">Leave blank to make available immediately with no end date.</p>
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

export default function PermitTypes({ readOnly = false }: { readOnly?: boolean }) {
  const { modal, message } = App.useApp();
  const [types, setTypes] = useState<PermitTypeRow[]>([]);
  const [lots, setLots] = useState<LotForSelect[]>([]);
  const [editing, setEditing] = useState<PermitTypeRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const formRef = useRef<HTMLDivElement>(null);
  const [expandedRowKeys, setExpandedRowKeys] = useState<string[]>([]);
  const [waitlistCache, setWaitlistCache] = useState<Record<string, WaitlistEntry[]>>({});
  const [waitlistLoading, setWaitlistLoading] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if ((editing || creating) && formRef.current) {
      formRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [editing, creating]);

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

  function handleDeactivate(pt: PermitTypeRow) {
    modal.confirm({
      title: `Deactivate "${pt.label}"?`,
      content: "This will hide the permit type from students and stop new purchases. Existing permits are not affected. You can reactivate it later.",
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

  async function handleTogglePurchasing(pt: PermitTypeRow) {
    const enable = !pt.is_purchasable_online;
    try {
      const res = await fetch(`/api/permit-types/${pt.id}`, {
        method: "PUT", headers: await authHeaders(),
        body: JSON.stringify({ is_purchasable_online: enable }),
      });
      if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error((b as any).detail || `Failed (${res.status})`); }
      message.success(enable ? "Purchasing enabled" : "Purchasing disabled");
      load();
    } catch (e: any) { message.error(e.message); }
  }

  async function fetchWaitlist(pt: PermitTypeRow) {
    if (waitlistCache[pt.id]) return;
    setWaitlistLoading(prev => ({ ...prev, [pt.id]: true }));
    try {
      let waitlisted: WaitlistEntry[] = [];

      // Check old-style lottery applications
      const res = await fetch(`/api/permit-types/${pt.id}/applications`, { headers: await authHeaders() });
      if (res.ok) {
        const apps: WaitlistEntry[] = await res.json();
        waitlisted = apps.filter(a => a.status === "waitlisted");
      }

      // Also check lottery v2 — waitlist persists even after draw completes
      const cyclesRes = await fetch("/api/lottery-v2/cycles", { headers: await authHeaders() });
      if (cyclesRes.ok) {
        const cycles = await cyclesRes.json();
        const activeCycle = cycles.find((c: any) => c.status === "drawn" || c.status === "closed");
        if (activeCycle) {
          const appsRes = await fetch(`/api/lottery-v2/cycles/${activeCycle.id}/applications`, { headers: await authHeaders() });
          if (appsRes.ok) {
            const apps: WaitlistEntry[] = await appsRes.json();
            const v2Waitlisted = apps.filter(a =>
              a.status === "waitlisted" && (
                a.assigned_permit_type_id === pt.id ||
                (a.tier_preferences && a.tier_preferences[0] === pt.id)
              )
            );
            // Merge, deduplicating by id
            const existingIds = new Set(waitlisted.map(w => w.id));
            for (const entry of v2Waitlisted) {
              if (!existingIds.has(entry.id)) {
                waitlisted.push(entry);
              }
            }
          }
        }
      }

      waitlisted.sort((a, b) => (a.waitlist_position ?? 999) - (b.waitlist_position ?? 999));
      setWaitlistCache(prev => ({ ...prev, [pt.id]: waitlisted }));
    } catch {
      setWaitlistCache(prev => ({ ...prev, [pt.id]: [] }));
    } finally {
      setWaitlistLoading(prev => ({ ...prev, [pt.id]: false }));
    }
  }

  function handleExpand(expanded: boolean, pt: PermitTypeRow) {
    if (expanded) {
      setExpandedRowKeys(prev => [...prev, pt.id]);
      fetchWaitlist(pt);
    } else {
      setExpandedRowKeys(prev => prev.filter(k => k !== pt.id));
    }
  }

  function renderExpandedRow(pt: PermitTypeRow) {
    const pct = pt.max_capacity > 0 ? Math.round((pt.active_count / pt.max_capacity) * 100) : 0;
    const waitlist = waitlistCache[pt.id];
    const isLoading = waitlistLoading[pt.id];

    const waitlistColumns: ColumnsType<WaitlistEntry> = [
      { title: "#", key: "pos", width: 50, render: (_, r) => (
        <span className="font-semibold">{r.waitlist_position ?? "—"}</span>
      )},
      { title: "Name", dataIndex: "student_name", key: "name" },
      { title: "Email", dataIndex: "student_email", key: "email", render: v => (
        <span className="text-xs">{v}</span>
      )},
      { title: "Plate", dataIndex: "plate", key: "plate", render: v => (
        <span className="font-mono text-xs">{v}</span>
      )},
      { title: "Applied", dataIndex: "created_at", key: "date", render: v => (
        <span className="text-xs text-gray-500">
          {new Date(v).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
        </span>
      )},
    ];

    return (
      <div className="px-4 py-3 bg-gray-50">
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm font-medium">Capacity</span>
            <span className="text-xs text-gray-500">
              {pt.active_count} / {pt.max_capacity}
              <span className="ml-2 text-gray-400">({pt.remaining} remaining)</span>
            </span>
          </div>
          <Progress
            percent={pct}
            strokeColor={progressColor(pct)}
            showInfo={false}
            size="small"
          />
        </div>

        {isLoading ? (
          <div className="flex items-center gap-2 py-4 text-gray-500">
            <Spin size="small" /> Loading waitlist...
          </div>
        ) : waitlist && waitlist.length > 0 ? (
          <div>
            <div className="text-sm font-medium mb-2">
              Waitlisted <Tag className="ml-1">{waitlist.length}</Tag>
            </div>
            <Table
              dataSource={waitlist}
              columns={waitlistColumns}
              rowKey="id"
              size="small"
              pagination={waitlist.length > 10 ? { pageSize: 10, size: "small" } : false}
            />
          </div>
        ) : (
          <div className="text-sm text-gray-400 py-2">No one on the waitlist</div>
        )}
      </div>
    );
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
    { title: "Capacity", key: "capacity", render: (_, pt) => {
      const fromPct = Math.floor(pt.max_capacity * (pt.reserved_pct || 0) / 100);
      const reserved = Math.max(pt.reserved_spots || 0, fromPct);
      return (
        <div>
          <span>{pt.max_capacity}</span>
          {reserved > 0 && (
            <div className="text-[11px] text-ink-mute">{reserved} reserved</div>
          )}
        </div>
      );
    }},
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
      render: (_, pt) => {
        const reserved = Math.max(pt.reserved_spots || 0, Math.floor(pt.max_capacity * (pt.reserved_pct || 0) / 100));
        const reservedAvail = (pt as any).reserved_available || 0;
        const publicAvail = pt.remaining - reservedAvail;
        return (
          <Space direction="vertical" size={0}>
            <span className="text-ink-mute">{pt.active_count} / {pt.max_capacity}</span>
            {pt.remaining === 0 ? (
              <span className="text-red-600 font-medium text-xs">Full</span>
            ) : reserved > 0 ? (
              <>
                <span className="text-green-600 text-xs">{publicAvail} open</span>
                <span className="text-orange-500 text-xs">{reservedAvail} in reserve</span>
              </>
            ) : (
              <span className="text-green-600 text-xs">{pt.remaining} open</span>
            )}
          </Space>
        );
      },
    },
    {
      title: "Status", key: "type",
      render: (_, pt) => {
        if (!pt.is_active) return <Tag color="red">Inactive</Tag>;

        if (pt.requires_lottery) {
          return (
            <div>
              <Tag color="purple">Lottery tier</Tag>
              <div className="text-[10px] text-ink-mute mt-0.5">Managed on Lottery tab</div>
            </div>
          );
        }
        if (pt.code === "south_standalone") {
          return (
            <div>
              <Tag color="orange">Third party</Tag>
              <div className="text-[10px] text-ink-mute mt-0.5">Sold off-platform</div>
            </div>
          );
        }

        const now = new Date();
        const opens = pt.application_opens_at ? new Date(pt.application_opens_at) : null;
        const closes = pt.application_closes_at ? new Date(pt.application_closes_at) : null;
        const notYetOpen = opens && opens > now;
        const closed = closes && closes < now;

        if (pt.is_purchasable_online) {
          if (notYetOpen) return (
            <div>
              <Tag color="blue">Scheduled</Tag>
              <div className="text-[10px] text-ink-mute mt-0.5">Opens {opens!.toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</div>
            </div>
          );
          if (closed) return (
            <div>
              <Tag color="default">Purchasing Closed</Tag>
              <div className="text-[10px] text-ink-mute mt-0.5">Ended {closes!.toLocaleDateString("en-US", { month: "short", day: "numeric" })}</div>
            </div>
          );
          if (closes) return (
            <div>
              <Tag color="green">Available Now</Tag>
              <div className="text-[10px] text-ink-mute mt-0.5">Until {closes.toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</div>
            </div>
          );
          return <Tag color="green">Always Available</Tag>;
        }
        return <Tag>Admin-Issued</Tag>;
      },
    },
    { title: "Code", dataIndex: "code", key: "code", render: v => <span className="font-mono text-xs">{v}</span> },
    ...(!readOnly ? [{
      title: "Actions", key: "actions", width: 280,
      render: (_: unknown, pt: PermitTypeRow) => (
        <Space>
          <Button type="link" size="small" onClick={() => { setEditing(pt); setCreating(false); }}>Edit</Button>
          {pt.is_active && !NO_ONLINE_PURCHASE_CODES.has(pt.code) && (
            <Button type="link" size="small" onClick={() => handleTogglePurchasing(pt)}
              style={pt.is_purchasable_online ? undefined : { color: "#16a34a" }}>
              {pt.is_purchasable_online ? "Disable Purchasing" : "Enable Purchasing"}
            </Button>
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
    }] : []),
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Permit Types</h2>
        {!readOnly && <Button type="primary" onClick={() => { setCreating(true); setEditing(null); }}>+ New Permit Type</Button>}
      </div>
      {!readOnly && (creating || editing) && (
        <div ref={formRef}>
          <PermitTypeForm key={editing?.id ?? "new"} initial={editing ?? undefined} lots={lots}
            onSave={() => { setCreating(false); setEditing(null); load(); }}
            onCancel={() => { setCreating(false); setEditing(null); }} />
        </div>
      )}
      <Table dataSource={types} columns={columns} rowKey="id" loading={loading} size="small"
        rowClassName={pt => !pt.is_active ? "opacity-50" : "cursor-pointer"}
        pagination={false}
        expandable={{
          expandedRowKeys,
          onExpand: handleExpand,
          expandedRowRender: renderExpandedRow,
          expandRowByClick: true,
        }}
        locale={{ emptyText: <Empty description="No permit types configured" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />
    </div>
  );
}
