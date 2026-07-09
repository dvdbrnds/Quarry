import { useCallback, useEffect, useRef, useState } from "react";
import { authHeaders } from "../auth";
import {
  Table, Button, Input, InputNumber, Select, Tag, Card, Statistic, Space, App, Spin, Empty, Alert, DatePicker, Progress,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

interface PermitTypeRow {
  id: string; code: string; label: string; eligible: string; price: string;
  max_capacity: number; valid_days: number; lot_assignments: string[];
  is_active: boolean; active_count: number; remaining: number;
  requires_lottery: boolean; lottery_strategy: string; min_class_year: number | null;
  application_opens_at: string | null; application_closes_at: string | null;
  offer_window_days: number; lottery_run_at: string | null;
}

interface Application {
  id: string; student_email: string; student_name: string; class_year: number;
  plate: string; phone: string | null; lot_preferences: string[];
  assigned_lot: string | null; status: string; lottery_rank: number | null;
  waitlist_position: number | null; offer_expires_at: string | null;
  created_at: string; updated_at: string;
}

interface SimulationResult {
  selected: SimulatedApp[]; waitlisted: SimulatedApp[];
  total_applicants: number; spots_available: number; strategy_used: string;
}

interface SimulatedApp {
  id: string; student_name: string; student_email: string; class_year: number;
  plate: string; lot_preferences: string[]; assigned_lot: string | null; rank: number;
}

interface ActivityEvent { id: string; student_name: string; old_status: string; new_status: string; timestamp: string; }

const STRATEGY_LABELS: Record<string, string> = {
  seniority_weighted: "Seniority Weighted", pure_random: "Pure Random",
  class_priority: "Class Priority", seniority_timestamp: "Seniority + Timestamp",
};

const STATUS_COLORS: Record<string, string> = {
  pending: "gold", selected: "green", waitlisted: "blue",
  accepted: "lime", expired: "default", declined: "default",
};

type View = "overview" | "manage" | "simulate" | "live";

export default function LotteryManager() {
  const [types, setTypes] = useState<PermitTypeRow[]>([]);
  const [selected, setSelected] = useState<PermitTypeRow | null>(null);
  const [view, setView] = useState<View>("overview");

  const load = useCallback(async () => {
    const res = await fetch("/api/permit-types?all=true", { headers: await authHeaders() });
    if (res.ok) { const all: PermitTypeRow[] = await res.json(); setTypes(all.filter(t => t.is_active)); }
  }, []);

  useEffect(() => { load(); }, [load]);

  function openManage(pt: PermitTypeRow) { setSelected(pt); setView("manage"); }
  function goBack() { if (view === "simulate" || view === "live") setView("manage"); else { setSelected(null); setView("overview"); load(); } }

  const reloadSelected = useCallback(async () => {
    await load();
    if (selected) {
      const res = await fetch("/api/permit-types?all=true", { headers: await authHeaders() });
      if (res.ok) { const all: PermitTypeRow[] = await res.json(); const u = all.find(t => t.id === selected.id); if (u) setSelected(u); }
    }
  }, [load, selected]);

  if (view === "overview" || !selected) return <OverviewGrid types={types} onSelect={openManage} onReload={load} />;
  if (view === "simulate") return <SimulationView permitType={selected} onBack={goBack} />;
  if (view === "live") return <LiveDashboard permitType={selected} onBack={goBack} />;
  return <ManageView permitType={selected} onBack={goBack} onSimulate={() => setView("simulate")} onGoLive={() => setView("live")} onReload={reloadSelected} />;
}

function OverviewGrid({ types, onSelect, onReload }: { types: PermitTypeRow[]; onSelect: (pt: PermitTypeRow) => void; onReload: () => void }) {
  const { modal, message } = App.useApp();
  const now = new Date();
  const [toggling, setToggling] = useState<string | null>(null);
  const lotteryTypes = types.filter(t => t.requires_lottery);
  const otherTypes = types.filter(t => !t.requires_lottery);

  function getStatus(pt: PermitTypeRow) {
    if (pt.lottery_run_at) return { label: "Completed", color: "green" as const };
    if (pt.application_closes_at && new Date(pt.application_closes_at) < now) return { label: "Ready to run", color: "gold" as const };
    if (pt.application_opens_at && new Date(pt.application_opens_at) < now) return { label: "Accepting applications", color: "blue" as const };
    if (pt.application_opens_at) return { label: "Scheduled", color: "default" as const };
    return { label: "Not configured", color: "default" as const };
  }

  async function enableLottery(pt: PermitTypeRow) {
    setToggling(pt.id);
    try {
      await fetch(`/api/permit-types/${pt.id}`, { method: "PUT", headers: await authHeaders(), body: JSON.stringify({ requires_lottery: true, lottery_strategy: "seniority_timestamp" }) });
      message.success("Lottery enabled"); onReload();
    } finally { setToggling(null); }
  }

  function disableLottery(pt: PermitTypeRow) {
    modal.confirm({
      title: `Disable lottery for "${pt.label}"?`, content: "Existing applications will be preserved.",
      okText: "Disable", okButtonProps: { danger: true },
      onOk: async () => {
        setToggling(pt.id);
        try { await fetch(`/api/permit-types/${pt.id}`, { method: "PUT", headers: await authHeaders(), body: JSON.stringify({ requires_lottery: false }) }); message.success("Lottery disabled"); onReload(); }
        finally { setToggling(null); }
      },
    });
  }

  const otherColumns: ColumnsType<PermitTypeRow> = [
    { title: "Permit Type", key: "label", render: (_, pt) => <><div className="font-medium">{pt.label}</div><div className="text-xs text-ink-mute">{pt.code}</div></> },
    { title: "Capacity", dataIndex: "max_capacity", key: "capacity" },
    { title: "Price", dataIndex: "price", key: "price", render: v => Number(v) === 0 ? "Free" : `$${Number(v).toFixed(0)}` },
    { title: "Lots", key: "lots", render: (_, pt) => pt.lot_assignments.join(", ") || "—" },
    { title: "", key: "action", render: (_, pt) => <Button size="small" loading={toggling === pt.id} onClick={() => enableLottery(pt)} style={{ borderColor: "#9333ea", color: "#7e22ce" }}>Enable Lottery</Button> },
  ];

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-navy">Lottery Management</h2>
        <p className="text-sm text-ink-mute mt-1">Manage lotteries, run simulations, and monitor live draws.</p>
      </div>
      {lotteryTypes.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
          {lotteryTypes.map(pt => {
            const status = getStatus(pt);
            return (
              <Card key={pt.id} hoverable>
                <div className="flex items-start justify-between mb-2">
                  <h3 className="font-semibold text-navy">{pt.label}</h3>
                  <Tag color={status.color}>{status.label}</Tag>
                </div>
                <div className="text-xs text-ink-mute space-y-1 mb-4">
                  <div>Strategy: {STRATEGY_LABELS[pt.lottery_strategy] || pt.lottery_strategy}</div>
                  <div>Capacity: {pt.max_capacity} &middot; {pt.remaining} remaining</div>
                  <div>Lots: {pt.lot_assignments.join(", ") || "None"}</div>
                  {pt.application_closes_at && <div>Closes: {new Date(pt.application_closes_at).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</div>}
                  {pt.lottery_run_at && <div className="text-green-700">Ran: {new Date(pt.lottery_run_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</div>}
                </div>
                <Space>
                  <Button type="primary" size="small" onClick={() => onSelect(pt)}>Manage</Button>
                  <Button type="text" size="small" danger loading={toggling === pt.id} onClick={() => disableLottery(pt)}>Disable</Button>
                </Space>
              </Card>
            );
          })}
        </div>
      ) : (
        <Empty className="mb-8" description="No permit types have lottery enabled yet. Enable lottery on a type below." />
      )}
      {otherTypes.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-ink-mute uppercase tracking-wide mb-3">Available Permit Types</h3>
          <Table dataSource={otherTypes} columns={otherColumns} rowKey="id" size="small" pagination={false} />
        </div>
      )}
    </div>
  );
}

function ManageView({ permitType, onBack, onSimulate, onGoLive, onReload }: {
  permitType: PermitTypeRow; onBack: () => void; onSimulate: () => void; onGoLive: () => void; onReload: () => Promise<void>;
}) {
  const { modal, message: msg } = App.useApp();
  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [advancing, setAdvancing] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [showConfig, setShowConfig] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [strategy, setStrategy] = useState(permitType.lottery_strategy);
  const [minClassYear, setMinClassYear] = useState(permitType.min_class_year?.toString() ?? "");
  const [offerDays, setOfferDays] = useState(permitType.offer_window_days);
  const [opensAt, setOpensAt] = useState<dayjs.Dayjs | null>(permitType.application_opens_at ? dayjs(permitType.application_opens_at) : null);
  const [closesAt, setClosesAt] = useState<dayjs.Dayjs | null>(permitType.application_closes_at ? dayjs(permitType.application_closes_at) : null);

  const load = useCallback(async () => {
    setLoading(true);
    try { const res = await fetch(`/api/permit-types/${permitType.id}/applications`, { headers: await authHeaders() }); if (res.ok) setApplications(await res.json()); }
    finally { setLoading(false); }
  }, [permitType.id]);

  useEffect(() => { load(); }, [load]);

  const now = new Date();
  const windowClosed = permitType.application_closes_at ? new Date(permitType.application_closes_at) < now : true;
  const lotteryAlreadyRun = !!permitType.lottery_run_at;
  const pendingCount = applications.filter(a => a.status === "pending").length;
  const selectedCount = applications.filter(a => a.status === "selected").length;
  const waitlistedCount = applications.filter(a => a.status === "waitlisted").length;
  const acceptedCount = applications.filter(a => a.status === "accepted").length;
  const expiredCount = applications.filter(a => a.status === "expired").length;

  function handleRunLottery() {
    modal.confirm({
      title: `Run the lottery for ${permitType.label}?`,
      content: `This will select winners from ${pendingCount} pending applications.`,
      okText: "Run Lottery",
      onOk: async () => {
        setRunning(true);
        try {
          const res = await fetch(`/api/permit-types/${permitType.id}/run-lottery`, { method: "POST", headers: await authHeaders() });
          if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Failed"); }
          const result = await res.json();
          msg.success(`Lottery complete: ${result.selected} selected, ${result.waitlisted} waitlisted`);
          load();
        } catch (e: any) { msg.error(e.message); } finally { setRunning(false); }
      },
    });
  }

  async function handleAdvanceWaitlist() {
    setAdvancing(true);
    try {
      const res = await fetch(`/api/permit-types/${permitType.id}/advance-waitlist`, { method: "POST", headers: await authHeaders() });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Failed"); }
      const result = await res.json();
      msg.success(`Expired ${result.expired} offers, advanced ${result.advanced} from waitlist`);
      load();
    } catch (e: any) { msg.error(e.message); } finally { setAdvancing(false); }
  }

  function handleResetLottery() {
    const nonPending = applications.filter(a => a.status !== "pending" && a.status !== "declined").length;
    modal.confirm({
      title: `Reset lottery for ${permitType.label}?`,
      content: `This will move ${nonPending} application(s) back to "pending" status and clear rankings. No applications will be deleted.`,
      okText: "Reset Lottery", okButtonProps: { danger: true },
      onOk: async () => {
        setResetting(true);
        try {
          const res = await fetch(`/api/permit-types/${permitType.id}/reset-lottery`, { method: "POST", headers: await authHeaders() });
          if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Failed"); }
          const result = await res.json();
          msg.success(`Reset ${result.reset} applications to pending — ready to re-run`);
          load(); await onReload();
        } catch (e: any) { msg.error(e.message); } finally { setResetting(false); }
      },
    });
  }

  async function saveConfig() {
    setConfigSaving(true);
    try {
      await fetch(`/api/permit-types/${permitType.id}`, { method: "PUT", headers: await authHeaders(), body: JSON.stringify({
        lottery_strategy: strategy, min_class_year: minClassYear ? parseInt(minClassYear) : null,
        offer_window_days: offerDays, application_opens_at: opensAt?.toISOString() ?? null, application_closes_at: closesAt?.toISOString() ?? null,
      })});
      msg.success("Configuration saved");
    } catch { msg.error("Failed to save config"); } finally { setConfigSaving(false); }
  }

  const appColumns: ColumnsType<Application> = [
    { title: "Name", dataIndex: "student_name", key: "name", render: v => <span className="font-medium">{v}</span> },
    { title: "Email", dataIndex: "student_email", key: "email", ellipsis: true },
    { title: "Class", dataIndex: "class_year", key: "class" },
    { title: "Plate", dataIndex: "plate", key: "plate", render: v => <span className="font-mono text-xs">{v}</span> },
    { title: "Status", dataIndex: "status", key: "status", render: s => <Tag color={STATUS_COLORS[s] || "default"}>{s}</Tag> },
    {
      title: "Rank", key: "rank",
      render: (_, a) => <>
        {a.lottery_rank ? `#${a.lottery_rank}` : ""}
        {a.waitlist_position ? `WL #${a.waitlist_position}` : ""}
        {a.offer_expires_at && a.status === "selected" && <span className="ml-1 text-amber-700">(exp {new Date(a.offer_expires_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })})</span>}
      </>,
    },
    { title: "Lot Prefs", key: "prefs", render: (_, a) => a.lot_preferences?.length > 0 ? a.lot_preferences.join(" > ") : "—" },
    { title: "Assigned", dataIndex: "assigned_lot", key: "assigned", render: v => v ? <span className="text-green-700 font-medium">{v}</span> : "—" },
    { title: "Applied", dataIndex: "created_at", key: "applied", render: d => new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric" }) },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <Space>
          <Button type="text" onClick={onBack}>&larr; Back</Button>
          <div>
            <h2 className="text-2xl font-bold text-navy">{permitType.label}</h2>
            <p className="text-xs text-ink-mute">{STRATEGY_LABELS[permitType.lottery_strategy] || permitType.lottery_strategy}{permitType.min_class_year ? ` · Min class year: ${permitType.min_class_year}` : ""}</p>
          </div>
        </Space>
        <Space>
          <Button onClick={() => setShowConfig(!showConfig)} type={showConfig ? "primary" : "default"} ghost={showConfig}>Configure</Button>
          <Button onClick={onSimulate} style={{ borderColor: "#9333ea", color: "#7e22ce" }}>Simulate</Button>
          <Button onClick={onGoLive} disabled={!lotteryAlreadyRun} style={{ borderColor: "#16a34a", color: "#15803d" }}>Go Live</Button>
        </Space>
      </div>

      {showConfig && (
        <Card className="mb-5" title="Lottery Configuration" size="small">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div><label className="block text-xs font-medium text-ink-mute mb-1">Strategy</label>
              <Select value={strategy} onChange={setStrategy} className="w-full" options={Object.entries(STRATEGY_LABELS).map(([v, l]) => ({ label: l, value: v }))} /></div>
            <div><label className="block text-xs font-medium text-ink-mute mb-1">Min Class Year</label>
              <Input value={minClassYear} onChange={e => setMinClassYear(e.target.value)} type="number" placeholder="None" /></div>
            <div><label className="block text-xs font-medium text-ink-mute mb-1">Offer Window (days)</label>
              <InputNumber value={offerDays} onChange={v => setOfferDays(v ?? 5)} min={1} max={30} className="w-full" /></div>
            <div><label className="block text-xs font-medium text-ink-mute mb-1">Opens</label>
              <DatePicker showTime value={opensAt} onChange={setOpensAt} className="w-full" /></div>
            <div><label className="block text-xs font-medium text-ink-mute mb-1">Closes</label>
              <DatePicker showTime value={closesAt} onChange={setClosesAt} className="w-full" /></div>
          </div>
          <div className="flex justify-end mt-3"><Button type="primary" onClick={saveConfig} loading={configSaving}>Save Configuration</Button></div>
        </Card>
      )}

      <div className="grid grid-cols-6 gap-3 mb-5">
        {[
          { label: "Total", value: applications.length, color: undefined },
          { label: "Pending", value: pendingCount, color: "#ca8a04" },
          { label: "Selected", value: selectedCount, color: "#15803d" },
          { label: "Waitlisted", value: waitlistedCount, color: "#1d4ed8" },
          { label: "Accepted", value: acceptedCount, color: "#15803d" },
          { label: "Expired", value: expiredCount, color: undefined },
        ].map(s => (
          <Card key={s.label} size="small" className="text-center">
            <Statistic title={s.label} value={s.value} valueStyle={s.color ? { color: s.color, fontWeight: 700 } : { fontWeight: 700 }} />
          </Card>
        ))}
      </div>

      <Space className="mb-5">
        <Button type="primary" onClick={handleRunLottery} loading={running} disabled={pendingCount === 0 || !windowClosed}>Run Lottery</Button>
        <Button onClick={handleAdvanceWaitlist} loading={advancing} disabled={selectedCount === 0 && waitlistedCount === 0}>Advance Waitlist</Button>
        {lotteryAlreadyRun && <Button danger onClick={handleResetLottery} loading={resetting}>Reset Lottery</Button>}
        {!windowClosed && <span className="text-xs text-amber-700">Window open until {new Date(permitType.application_closes_at!).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>}
      </Space>

      <Table dataSource={applications} columns={appColumns} rowKey="id" loading={loading} size="small"
        pagination={{ pageSize: 50 }}
        locale={{ emptyText: <Empty description="No applications yet" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />
    </div>
  );
}

function SimulationView({ permitType, onBack }: { permitType: PermitTypeRow; onBack: () => void }) {
  const { message: msg } = App.useApp();
  const [strategy, setStrategy] = useState(permitType.lottery_strategy);
  const [capacityOverride, setCapacityOverride] = useState<number | null>(null);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewIdx, setPreviewIdx] = useState(0);

  async function runSimulation() {
    setLoading(true); setResult(null);
    try {
      const body: Record<string, unknown> = { strategy };
      if (capacityOverride) body.capacity_override = capacityOverride;
      const res = await fetch(`/api/permit-types/${permitType.id}/simulate-lottery`, { method: "POST", headers: await authHeaders(), body: JSON.stringify(body) });
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Failed"); }
      setResult(await res.json());
    } catch (e: any) { msg.error(e.message); } finally { setLoading(false); }
  }

  useEffect(() => { runSimulation(); }, [permitType.id]);

  const previewStudent = result?.selected[previewIdx] || null;

  const simColumns: ColumnsType<SimulatedApp> = [
    { title: "#", dataIndex: "rank", key: "rank", width: 50 },
    { title: "Name", dataIndex: "student_name", key: "name", render: v => <span className="font-medium">{v}</span> },
    { title: "Class", dataIndex: "class_year", key: "class" },
    { title: "Lot", dataIndex: "assigned_lot", key: "lot", render: v => v ? <span className="text-green-700 font-medium">{v}</span> : "—" },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <Space>
          <Button type="text" onClick={onBack}>&larr; Back</Button>
          <div><h2 className="text-2xl font-bold text-navy">Simulation: {permitType.label}</h2><p className="text-xs text-ink-mute">Dry run — no data is saved</p></div>
        </Space>
        <Tag color="purple">Simulation Mode</Tag>
      </div>

      <Card className="mb-5" size="small">
        <Space>
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Strategy</label>
            <Select value={strategy} onChange={setStrategy} style={{ width: 220 }} options={Object.entries(STRATEGY_LABELS).map(([v, l]) => ({ label: l, value: v }))} /></div>
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Capacity Override</label>
            <InputNumber value={capacityOverride} onChange={v => setCapacityOverride(v)} placeholder={`${permitType.max_capacity}`} style={{ width: 140 }} /></div>
          <div className="self-end"><Button onClick={runSimulation} loading={loading} style={{ background: "#9333ea", borderColor: "#9333ea", color: "white" }}>Re-run Simulation</Button></div>
        </Space>
      </Card>

      {result && (
        <div className="grid grid-cols-3 gap-5">
          <div className="col-span-2">
            <Card title={<Space><span>Projected Results</span><span className="text-xs text-ink-mute font-normal">{result.selected.length} selected / {result.waitlisted.length} waitlisted / {result.spots_available} spots</span></Space>} styles={{ body: { padding: 0 } }}>
              <Table dataSource={[...result.selected.map(a => ({ ...a, _type: "selected" })), ...result.waitlisted.map(a => ({ ...a, _type: "waitlisted" }))]} rowKey="id" size="small" pagination={false} scroll={{ y: 500 }}
                columns={[
                  ...simColumns,
                  { title: "Outcome", key: "outcome", render: (_, r: any) => <Tag color={r._type === "selected" ? "green" : "blue"}>{r._type}</Tag> },
                ]}
                onRow={(_, i) => ({ onClick: () => i !== undefined && setPreviewIdx(i), className: i === previewIdx ? "bg-brass/10" : "cursor-pointer" })}
              />
            </Card>
          </div>
          <Card title="Student Preview">
            {previewStudent ? (
              <div className="space-y-4">
                <Alert type="success" message={`Congratulations, ${previewStudent.student_name.split(" ")[0]}!`}
                  description={<>You've been selected for <strong>{permitType.label}</strong>.{previewStudent.assigned_lot && <> Assigned lot: <strong>{previewStudent.assigned_lot}</strong></>} You have {permitType.offer_window_days} days to accept and pay ${Number(permitType.price).toFixed(0)}.</>} />
                <div className="text-xs space-y-1 text-ink-mute">
                  <div><strong>Rank:</strong> #{previewStudent.rank} of {result.selected.length}</div>
                  <div><strong>Email:</strong> {previewStudent.student_email}</div>
                  <div><strong>Class:</strong> {previewStudent.class_year}</div>
                  <div><strong>Plate:</strong> {previewStudent.plate}</div>
                  <div><strong>Lot Prefs:</strong> {previewStudent.lot_preferences.length > 0 ? previewStudent.lot_preferences.join(" > ") : "None"}</div>
                </div>
              </div>
            ) : <p className="text-xs text-ink-mute">Click a student to preview their experience.</p>}
          </Card>
        </div>
      )}
    </div>
  );
}

function LiveDashboard({ permitType, onBack }: { permitType: PermitTypeRow; onBack: () => void }) {
  const [applications, setApplications] = useState<Application[]>([]);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [isLive, setIsLive] = useState(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [lastUpdate, setLastUpdate] = useState(new Date());

  const fetchData = useCallback(async () => {
    try {
      const [ar, ac] = await Promise.all([
        fetch(`/api/permit-types/${permitType.id}/applications`, { headers: await authHeaders() }),
        fetch(`/api/permit-types/${permitType.id}/lottery-activity`, { headers: await authHeaders() }),
      ]);
      if (ar.ok) setApplications(await ar.json());
      if (ac.ok) setActivity(await ac.json());
      setLastUpdate(new Date());
    } catch { /* silent */ }
  }, [permitType.id]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => { if (isLive) intervalRef.current = setInterval(fetchData, 4000); return () => { if (intervalRef.current) clearInterval(intervalRef.current); }; }, [isLive, fetchData]);

  const pendingCount = applications.filter(a => a.status === "pending").length;
  const selectedCount = applications.filter(a => a.status === "selected").length;
  const waitlistedCount = applications.filter(a => a.status === "waitlisted").length;
  const acceptedCount = applications.filter(a => a.status === "accepted").length;
  const expiredCount = applications.filter(a => a.status === "expired").length;
  const declinedCount = applications.filter(a => a.status === "declined").length;
  const totalOffered = selectedCount + acceptedCount + expiredCount + declinedCount;
  const acceptRate = totalOffered > 0 ? Math.round((acceptedCount / totalOffered) * 100) : 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <Space>
          <Button type="text" onClick={onBack}>&larr; Back</Button>
          <div><h2 className="text-2xl font-bold text-navy">Live: {permitType.label}</h2>
            <p className="text-xs text-ink-mute">Last updated: {lastUpdate.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" })}</p>
          </div>
        </Space>
        <Button onClick={() => setIsLive(!isLive)} type={isLive ? "primary" : "default"} style={isLive ? { background: "#16a34a" } : {}}>
          <span className={`w-2 h-2 rounded-full inline-block mr-1.5 ${isLive ? "bg-white animate-pulse" : "bg-gray-400"}`} />
          {isLive ? "Live" : "Paused"}
        </Button>
      </div>

      <div className="grid grid-cols-6 gap-3 mb-6">
        {[
          { label: "Pending", value: pendingCount, color: "#ca8a04" },
          { label: "Awaiting", value: selectedCount, color: "#15803d" },
          { label: "Accepted", value: acceptedCount, color: "#166534" },
          { label: "Waitlisted", value: waitlistedCount, color: "#1d4ed8" },
          { label: "Expired", value: expiredCount, color: undefined },
          { label: "Declined", value: declinedCount, color: undefined },
        ].map(s => (
          <Card key={s.label} size="small" className="text-center">
            <Statistic title={s.label} value={s.value} valueStyle={s.color ? { color: s.color, fontWeight: 700, fontSize: 28 } : { fontWeight: 700, fontSize: 28 }} />
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-5">
        <div className="col-span-2 space-y-5">
          <Card title="Acceptance Progress" extra={<span className="text-xs text-ink-mute">{acceptRate}% rate</span>}>
            <div className="w-full bg-gray-100 rounded-full h-4 overflow-hidden">
              <div className="h-full flex">
                <div className="bg-green-500 transition-all duration-700" style={{ width: `${totalOffered > 0 ? (acceptedCount / totalOffered) * 100 : 0}%` }} />
                <div className="bg-yellow-400 transition-all duration-700" style={{ width: `${totalOffered > 0 ? (selectedCount / totalOffered) * 100 : 0}%` }} />
                <div className="bg-gray-300 transition-all duration-700" style={{ width: `${totalOffered > 0 ? ((expiredCount + declinedCount) / totalOffered) * 100 : 0}%` }} />
              </div>
            </div>
            <div className="flex gap-4 mt-2 text-[10px] text-ink-mute">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500" />Accepted ({acceptedCount})</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-yellow-400" />Awaiting ({selectedCount})</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gray-300" />Lost ({expiredCount + declinedCount})</span>
            </div>
          </Card>
          <Card title="Capacity Fill" extra={`${permitType.max_capacity - permitType.remaining} / ${permitType.max_capacity}`}>
            <Progress percent={Math.round(((permitType.max_capacity - permitType.remaining) / permitType.max_capacity) * 100)} strokeColor="#0A1628" />
          </Card>
        </div>

        <Card title="Recent Activity">
          {activity.length === 0 ? <Empty description="No recent activity" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
            <div className="space-y-2 max-h-[360px] overflow-y-auto">
              {activity.map(evt => (
                <div key={evt.id} className="flex items-start gap-2 text-xs border-b border-gray-50 pb-2">
                  <span className={`w-2 h-2 rounded-full mt-1 flex-shrink-0 ${
                    evt.new_status === "accepted" ? "bg-green-500" : evt.new_status === "selected" ? "bg-yellow-500" :
                    evt.new_status === "expired" ? "bg-gray-400" : evt.new_status === "waitlisted" ? "bg-blue-500" : "bg-gray-300"
                  }`} />
                  <div className="flex-1 min-w-0">
                    <span className="font-medium">{evt.student_name}</span> <span className="text-ink-mute">{evt.old_status} &rarr; {evt.new_status}</span>
                    <div className="text-[10px] text-ink-mute mt-0.5">{new Date(evt.timestamp).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
