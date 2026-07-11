import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { authHeaders } from "../auth";
import { api, LotteryResults, LotteryRunResult, LotteryVerification } from "../api";
import {
  Table, Button, Input, InputNumber, Select, Checkbox, Tag, Card, Form, DatePicker, Space, App, Empty, Progress, Tooltip, Drawer, Descriptions, Alert, Statistic, Tabs,
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
      await fetch(url, { method, headers: await authHeaders(), body: JSON.stringify(body) });
      message.success(initial ? "Permit type updated" : "Permit type created");
      onSave();
    } catch { message.error("Failed to save"); } finally { setSaving(false); }
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
          <Form.Item name="is_purchasable_online" valuePropName="checked" noStyle><Checkbox>Available for online purchase</Checkbox></Form.Item>
          <Form.Item name="requires_lottery" valuePropName="checked" noStyle><Checkbox>Requires lottery</Checkbox></Form.Item>
        </Space>
        {requiresLottery && (
          <>
            <h4 className="text-sm font-semibold text-navy mb-3 mt-4 pt-4 border-t">Lottery Configuration</h4>
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

export default function PermitTypes() {
  const { modal, message } = App.useApp();
  const navigate = useNavigate();
  const [types, setTypes] = useState<PermitTypeRow[]>([]);
  const [lots, setLots] = useState<LotForSelect[]>([]);
  const [editing, setEditing] = useState<PermitTypeRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [lotteryTarget, setLotteryTarget] = useState<PermitTypeRow | null>(null);

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
      content: "This will hide the permit type from students, stop new purchases, and remove it from lottery. Existing permits are not affected. You can reactivate it later.",
      okText: "Deactivate Permit Type", okButtonProps: { danger: true },
      onOk: async () => { await fetch(`/api/permit-types/${pt.id}`, { method: "DELETE", headers: await authHeaders() }); message.success("Deactivated"); load(); },
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

  function handleToggleLottery(pt: PermitTypeRow) {
    if (pt.requires_lottery) {
      modal.confirm({
        title: `Disable lottery for "${pt.label}"?`,
        content: "The permit type will stay active. Students will no longer apply through the lottery — it will become a regular permit. Existing applications are preserved.",
        okText: "Disable Lottery",
        onOk: async () => {
          await fetch(`/api/permit-types/${pt.id}`, { method: "PUT", headers: await authHeaders(), body: JSON.stringify({ requires_lottery: false }) });
          message.success("Lottery disabled"); load();
        },
      });
    } else {
      modal.confirm({
        title: `Enable lottery for "${pt.label}"?`,
        content: "Students will need to apply through the lottery to get this permit type.",
        okText: "Enable Lottery",
        onOk: async () => {
          await fetch(`/api/permit-types/${pt.id}`, { method: "PUT", headers: await authHeaders(), body: JSON.stringify({ requires_lottery: true, lottery_strategy: "seniority_timestamp" }) });
          message.success("Lottery enabled"); load();
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
    { title: "Label", dataIndex: "label", key: "label", render: v => <span className="font-medium">{v}</span> },
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
      title: "Type", key: "type",
      render: (_, pt) => pt.requires_lottery
        ? <Tag color="purple">Lottery</Tag>
        : pt.is_purchasable_online ? <Tag color="green">Online</Tag> : <Tag>Manual</Tag>,
    },
    { title: "Code", dataIndex: "code", key: "code", render: v => <span className="font-mono text-xs">{v}</span> },
    {
      title: "Actions", key: "actions", width: 200,
      render: (_, pt) => (
        <Space>
          <Button type="link" size="small" onClick={() => { setEditing(pt); setCreating(false); }}>Edit</Button>
          {pt.is_active && (
            <Button type="link" size="small" onClick={() => handleToggleLottery(pt)}
              style={pt.requires_lottery ? { color: "#9333ea" } : undefined}>
              {pt.requires_lottery ? "Disable Lottery" : "Enable Lottery"}
            </Button>
          )}
          {pt.requires_lottery && pt.is_active && <Button type="link" size="small" style={{ color: "#9333ea" }} onClick={() => setLotteryTarget(pt)}>Lottery</Button>}
          {pt.is_active
            ? <Button type="link" size="small" danger onClick={() => handleDeactivate(pt)}>Deactivate</Button>
            : <Button type="link" size="small" onClick={() => handleActivate(pt.id)}>Activate</Button>
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
      <LotteryDrawer
        permitType={lotteryTarget}
        onClose={() => { setLotteryTarget(null); load(); }}
      />
    </div>
  );
}


function LotteryDrawer({ permitType, onClose }: { permitType: PermitTypeRow | null; onClose: () => void }) {
  const { modal, message } = App.useApp();
  const [results, setResults] = useState<LotteryResults | null>(null);
  const [runResult, setRunResult] = useState<LotteryRunResult | null>(null);
  const [loadingResults, setLoadingResults] = useState(false);
  const [running, setRunning] = useState(false);
  const [verifyingSeed, setVerifyingSeed] = useState("");
  const [verification, setVerification] = useState<LotteryVerification | null>(null);
  const [verifying, setVerifying] = useState(false);

  useEffect(() => {
    if (!permitType) { setResults(null); setRunResult(null); setVerification(null); return; }
    if (permitType.lottery_run_at) {
      setLoadingResults(true);
      api.permits.lottery.results(permitType.id)
        .then(setResults)
        .catch(() => {})
        .finally(() => setLoadingResults(false));
    }
  }, [permitType]);

  function handleRun(force = false) {
    if (!permitType) return;
    const action = async () => {
      setRunning(true);
      try {
        const r = await api.permits.lottery.run(permitType.id, force);
        setRunResult(r);
        message.success(`Lottery complete: ${r.selected} selected, ${r.waitlisted} waitlisted`);
        const updatedResults = await api.permits.lottery.results(permitType.id);
        setResults(updatedResults);
      } catch (e: any) {
        message.error(e.message || "Lottery failed");
      } finally { setRunning(false); }
    };

    if (permitType.lottery_run_at && !force) {
      modal.confirm({
        title: "Re-run lottery?",
        content: "This lottery has already been run. Re-running will overwrite the previous results. This cannot be undone.",
        okText: "Re-run Lottery", okButtonProps: { danger: true },
        onOk: () => action(),
      });
    } else {
      modal.confirm({
        title: `Run lottery for "${permitType.label}"?`,
        content: `This will draw ${permitType.max_capacity} winners from all pending applications using the "${permitType.lottery_strategy}" strategy. Selected students will be notified by email.`,
        okText: "Run Lottery",
        onOk: () => action(),
      });
    }
  }

  async function handleVerify() {
    if (!permitType || !verifyingSeed.trim()) return;
    setVerifying(true);
    try {
      const v = await api.permits.lottery.verify(permitType.id, verifyingSeed.trim());
      setVerification(v);
      if (v.verified) message.success("Seed verified — draw is authentic");
      else message.error(v.error || "Verification failed");
    } catch (e: any) { message.error(e.message); }
    finally { setVerifying(false); }
  }

  const windowOpen = permitType?.application_closes_at
    ? new Date(permitType.application_closes_at) > new Date()
    : false;
  const alreadyRun = !!permitType?.lottery_run_at;

  const selected = results?.applications.filter(a => a.status === "selected") || [];
  const waitlisted = results?.applications.filter(a => a.status === "waitlisted") || [];
  const ineligible = results?.applications.filter(a => a.status === "ineligible") || [];

  const selectedCols: ColumnsType<any> = [
    { title: "#", dataIndex: "lottery_rank", key: "rank", width: 50 },
    { title: "Name", dataIndex: "student_name", key: "name" },
    { title: "Class", dataIndex: "class_year", key: "year", width: 70 },
    { title: "Lot", dataIndex: "assigned_lot", key: "lot", width: 80, render: v => v || "—" },
    { title: "Status", dataIndex: "status", key: "status", width: 100, render: v => <Tag color={v === "selected" ? "green" : v === "accepted" ? "lime" : "default"}>{v}</Tag> },
  ];
  const waitlistCols: ColumnsType<any> = [
    { title: "#", dataIndex: "waitlist_position", key: "pos", width: 50 },
    { title: "Name", dataIndex: "student_name", key: "name" },
    { title: "Class", dataIndex: "class_year", key: "year", width: 70 },
    { title: "Status", dataIndex: "status", key: "status", width: 100, render: v => <Tag color="blue">{v}</Tag> },
  ];

  return (
    <Drawer
      open={!!permitType}
      onClose={onClose}
      title={`Lottery — ${permitType?.label || ""}`}
      width={720}
      destroyOnClose
    >
      {permitType && (
        <div className="space-y-6">
          {/* Status banner */}
          {windowOpen && (
            <Alert type="warning" showIcon
              message="Application window is still open"
              description={`Closes ${new Date(permitType.application_closes_at!).toLocaleString()}. The lottery cannot be run until the window closes.`}
            />
          )}
          {alreadyRun && !runResult && (
            <Alert type="info" showIcon
              message={`Lottery was run on ${new Date(permitType.lottery_run_at!).toLocaleString()}`}
            />
          )}
          {runResult && (
            <Alert type="success" showIcon
              message={`Lottery complete — ${runResult.selected} selected, ${runResult.waitlisted} waitlisted`}
              description={runResult.warnings.length > 0 ? `Warnings: ${runResult.warnings.join("; ")}` : undefined}
            />
          )}

          {/* Action buttons */}
          <div className="flex gap-3">
            <Button
              type="primary"
              onClick={() => handleRun(alreadyRun)}
              loading={running}
              disabled={windowOpen}
            >
              {alreadyRun ? "Re-run Lottery" : "Run Lottery"}
            </Button>
          </div>

          {/* Results */}
          {(results || loadingResults) && (
            <Tabs items={[
              {
                key: "summary",
                label: "Summary",
                children: results?.audit ? (
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <Statistic title="Total Applicants" value={results.audit.total_applicants} />
                      <Statistic title="Eligible" value={results.audit.eligible_applicants} />
                      <Statistic title="Selected" value={results.audit.selected_count} valueStyle={{ color: "#16a34a" }} />
                      <Statistic title="Waitlisted" value={results.audit.waitlisted_count} valueStyle={{ color: "#2563eb" }} />
                    </div>
                    <Descriptions size="small" column={2} bordered>
                      <Descriptions.Item label="Strategy">{results.audit.strategy}</Descriptions.Item>
                      <Descriptions.Item label="Spots Available">{results.audit.spots_available}</Descriptions.Item>
                      <Descriptions.Item label="Filtered (test)">{results.audit.filtered_test_entries}</Descriptions.Item>
                      <Descriptions.Item label="Filtered (citations)">{results.audit.filtered_unpaid_citations}</Descriptions.Item>
                      <Descriptions.Item label="Run At">{new Date(results.audit.run_at).toLocaleString()}</Descriptions.Item>
                      <Descriptions.Item label="Run By">{results.audit.run_by}</Descriptions.Item>
                      <Descriptions.Item label="Seed Hash" span={2}>
                        <code className="text-xs break-all">{results.audit.seed_hash}</code>
                      </Descriptions.Item>
                    </Descriptions>
                    <p className="text-xs text-gray-500 mt-2">
                      The seed hash is a SHA-256 fingerprint of the random seed used. An admin with the original seed can verify that the draw was not tampered with.
                    </p>
                  </div>
                ) : <div className="text-center py-8 text-gray-400">Loading...</div>,
              },
              {
                key: "selected",
                label: `Selected (${selected.length})`,
                children: (
                  <Table dataSource={selected} columns={selectedCols} rowKey="id" size="small" pagination={false} />
                ),
              },
              {
                key: "waitlist",
                label: `Waitlist (${waitlisted.length})`,
                children: (
                  <Table dataSource={waitlisted} columns={waitlistCols} rowKey="id" size="small" pagination={false} />
                ),
              },
              ...(ineligible.length > 0 ? [{
                key: "ineligible",
                label: `Ineligible (${ineligible.length})`,
                children: (
                  <Table
                    dataSource={ineligible}
                    columns={[
                      { title: "Name", dataIndex: "student_name", key: "name" },
                      { title: "Plate", dataIndex: "plate", key: "plate", render: (v: string) => <span className="font-mono">{v}</span> },
                      { title: "Reason", dataIndex: "admin_notes", key: "notes", render: (v: string | null) => v || "—" },
                    ]}
                    rowKey="id" size="small" pagination={false}
                  />
                ),
              }] : []),
              {
                key: "verify",
                label: "Verify Draw",
                children: (
                  <div className="space-y-4">
                    <p className="text-sm text-gray-600">
                      Paste the original random seed to cryptographically verify that the lottery draw was authentic and unmodified.
                    </p>
                    <Space.Compact className="w-full">
                      <Input
                        placeholder="Paste seed here..."
                        value={verifyingSeed}
                        onChange={e => { setVerifyingSeed(e.target.value); setVerification(null); }}
                        className="font-mono text-xs"
                      />
                      <Button type="primary" onClick={handleVerify} loading={verifying} disabled={!verifyingSeed.trim()}>
                        Verify
                      </Button>
                    </Space.Compact>
                    {verification && (
                      <Alert
                        type={verification.verified ? "success" : "error"}
                        showIcon
                        message={verification.verified ? "Verified — seed matches the recorded draw" : verification.error || "Verification failed"}
                        description={verification.verified ? (
                          <span className="text-xs">
                            Strategy: {verification.strategy} &middot; Selected: {verification.selected_count} &middot; Waitlisted: {verification.waitlisted_count}
                          </span>
                        ) : undefined}
                      />
                    )}
                  </div>
                ),
              },
            ]} />
          )}
        </div>
      )}
    </Drawer>
  );
}
