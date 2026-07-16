import { useCallback, useEffect, useState } from "react";
import { api, AcademicSeason, Lot, LotClosure } from "../api";
import { authHeaders } from "../auth";
import { Button, Select, Modal, Input, Tag, Space, App, Descriptions, DatePicker, Empty } from "antd";
import dayjs from "dayjs";

interface LotteryPermitType {
  id: string; code: string; label: string;
  requires_lottery: boolean;
  application_opens_at: string | null;
  application_closes_at: string | null;
  lottery_run_at: string | null;
}

interface LotteryEvent {
  id: string;
  label: string;
  type: "opens" | "closes" | "drawing";
  date: Date;
}

const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
const WEEKDAYS = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];

function getDaysInMonth(y: number, m: number) { return new Date(y, m + 1, 0).getDate(); }
function getFirstDayOfWeek(y: number, m: number) { return new Date(y, m, 1).getDay(); }
function sameDay(a: Date, b: Date) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
function dayInRange(day: Date, start: Date, end: Date | null) {
  const d = day.getTime();
  const s = new Date(start.getFullYear(), start.getMonth(), start.getDate()).getTime();
  if (!end) return d >= s;
  return d >= s && d <= new Date(end.getFullYear(), end.getMonth(), end.getDate()).getTime();
}

const STATUS_COLORS: Record<string, { tw: string; antd: string }> = {
  active: { tw: "bg-signal-red/20 text-signal-red border-signal-red/40", antd: "red" },
  scheduled: { tw: "bg-amber-100 text-amber-800 border-amber-300", antd: "gold" },
  completed: { tw: "bg-emerald-100 text-emerald-700 border-emerald-300", antd: "green" },
  cancelled: { tw: "bg-gray-100 text-gray-400 border-gray-200 line-through", antd: "default" },
};

const SEASON_PALETTE = [
  { bg: "bg-indigo-50", border: "border-l-indigo-400", banner: "bg-indigo-100 text-indigo-800", dot: "bg-indigo-400" },
  { bg: "bg-teal-50", border: "border-l-teal-400", banner: "bg-teal-100 text-teal-800", dot: "bg-teal-400" },
  { bg: "bg-rose-50", border: "border-l-rose-400", banner: "bg-rose-100 text-rose-800", dot: "bg-rose-400" },
  { bg: "bg-amber-50", border: "border-l-amber-400", banner: "bg-amber-100 text-amber-800", dot: "bg-amber-400" },
  { bg: "bg-violet-50", border: "border-l-violet-400", banner: "bg-violet-100 text-violet-800", dot: "bg-violet-400" },
  { bg: "bg-cyan-50", border: "border-l-cyan-400", banner: "bg-cyan-100 text-cyan-800", dot: "bg-cyan-400" },
];

function dateInSeason(d: Date, s: AcademicSeason) { return d >= new Date(s.start_date + "T00:00:00") && d <= new Date(s.end_date + "T23:59:59"); }
function seasonOverlapsMonth(s: AcademicSeason, y: number, m: number) {
  return new Date(s.start_date + "T00:00:00") <= new Date(y, m + 1, 0, 23, 59, 59) && new Date(s.end_date + "T23:59:59") >= new Date(y, m, 1);
}
function formatSeasonDate(iso: string) { return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }); }

export default function OperationsCalendar() {
  const { message } = App.useApp();
  const [lots, setLots] = useState<Lot[]>([]);
  const [closures, setClosures] = useState<LotClosure[]>([]);
  const [seasons, setSeasons] = useState<AcademicSeason[]>([]);
  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(new Date().getMonth());
  const [scheduling, setScheduling] = useState(false);
  const [selectedClosure, setSelectedClosure] = useState<LotClosure | null>(null);
  const [editingClosure, setEditingClosure] = useState<LotClosure | null>(null);
  const [filterLotId, setFilterLotId] = useState<string>("");

  // Schedule form state
  const [schedLotId, setSchedLotId] = useState("");
  const [schedReason, setSchedReason] = useState("");
  const [schedClosesAt, setSchedClosesAt] = useState<dayjs.Dayjs | null>(null);
  const [schedReopensAt, setSchedReopensAt] = useState<dayjs.Dayjs | null>(null);
  const [schedSubmitting, setSchedSubmitting] = useState(false);

  // Edit form state
  const [editReason, setEditReason] = useState("");
  const [editClosesAt, setEditClosesAt] = useState<dayjs.Dayjs | null>(null);
  const [editReopensAt, setEditReopensAt] = useState<dayjs.Dayjs | null>(null);
  const [editSaving, setEditSaving] = useState(false);

  const [lotteryEvents, setLotteryEvents] = useState<LotteryEvent[]>([]);

  const load = useCallback(async () => {
    const [l, c, s, ptRes] = await Promise.all([
      api.lots.list(),
      api.lots.closures.listAll(),
      api.academicCalendar.list(),
      fetch("/api/permit-types?all=true", { headers: await authHeaders() }),
    ]);
    setLots(l); setClosures(c); setSeasons(s);

    if (ptRes.ok) {
      const pts: LotteryPermitType[] = await ptRes.json();
      const events: LotteryEvent[] = [];
      for (const pt of pts) {
        if (!pt.requires_lottery) continue;
        if (pt.application_opens_at) events.push({ id: `${pt.id}-opens`, label: pt.label, type: "opens", date: new Date(pt.application_opens_at) });
        if (pt.application_closes_at) events.push({ id: `${pt.id}-closes`, label: pt.label, type: "closes", date: new Date(pt.application_closes_at) });
        if (pt.lottery_run_at) events.push({ id: `${pt.id}-drawing`, label: pt.label, type: "drawing", date: new Date(pt.lottery_run_at) });
      }
      setLotteryEvents(events);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function prevMonth() { if (month === 0) { setMonth(11); setYear(year - 1); } else setMonth(month - 1); }
  function nextMonth() { if (month === 11) { setMonth(0); setYear(year + 1); } else setMonth(month + 1); }

  async function handleCancelClosure(id: string) {
    await api.lots.closures.cancel(id);
    message.success("Closure cancelled");
    setSelectedClosure(null); load();
  }

  async function handleSchedule() {
    if (!schedClosesAt) return;
    setSchedSubmitting(true);
    try {
      await api.lots.closures.schedule({
        lot_id: schedLotId, reason: schedReason,
        closes_at: schedClosesAt.toISOString(),
        reopens_at: schedReopensAt ? schedReopensAt.toISOString() : undefined,
      });
      message.success("Closure scheduled");
      setScheduling(false); setSchedReason(""); setSchedClosesAt(null); setSchedReopensAt(null); load();
    } catch { message.error("Failed to schedule"); }
    finally { setSchedSubmitting(false); }
  }

  async function handleEditSave() {
    if (!editingClosure || !editClosesAt) return;
    setEditSaving(true);
    try {
      await api.lots.closures.update(editingClosure.id, {
        reason: editReason || undefined,
        closes_at: editClosesAt.toISOString(),
        reopens_at: editReopensAt ? editReopensAt.toISOString() : undefined,
      });
      message.success("Closure updated");
      setEditingClosure(null); setSelectedClosure(null); load();
    } catch { message.error("Failed to update"); }
    finally { setEditSaving(false); }
  }

  function openEditModal(c: LotClosure) {
    setEditingClosure(c);
    setEditReason(c.reason ?? "");
    setEditClosesAt(dayjs(c.closes_at));
    setEditReopensAt(c.reopens_at ? dayjs(c.reopens_at) : null);
  }

  const daysInMonth = getDaysInMonth(year, month);
  const firstDay = getFirstDayOfWeek(year, month);
  const today = new Date();
  const filtered = filterLotId ? closures.filter(c => c.lot_id === filterLotId) : closures;

  function getClosuresForDay(d: number) {
    const day = new Date(year, month, d);
    return filtered.filter(c => dayInRange(day, new Date(c.closes_at), c.reopens_at ? new Date(c.reopens_at) : null));
  }

  function getLotteryEventsForDay(d: number) {
    return lotteryEvents.filter(e => e.date.getFullYear() === year && e.date.getMonth() === month && e.date.getDate() === d);
  }

  const LOTTERY_STYLES: Record<string, string> = {
    opens: "bg-purple-100 text-purple-800 border-purple-300",
    closes: "bg-purple-200 text-purple-900 border-purple-400",
    drawing: "bg-purple-500 text-white border-purple-600",
  };
  const LOTTERY_LABELS: Record<string, string> = { opens: "Opens", closes: "Closes", drawing: "Drawing" };

  const cells: (number | null)[] = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  const seasonColorMap = new Map<string, (typeof SEASON_PALETTE)[number]>();
  seasons.forEach((s, i) => seasonColorMap.set(s.id, SEASON_PALETTE[i % SEASON_PALETTE.length]));
  const visibleSeasons = seasons.filter(s => seasonOverlapsMonth(s, year, month));

  function getSeasonForDay(d: number) { const dt = new Date(year, month, d); return seasons.find(s => dateInSeason(dt, s)) ?? null; }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Operations Calendar</h1>
        <Button type="primary" onClick={() => { setScheduling(true); setSchedLotId(lots[0]?.id ?? ""); }}>+ Schedule Closure</Button>
      </div>

      <div className="flex items-center gap-4">
        <Button onClick={prevMonth}>&lt;</Button>
        <h2 className="text-lg font-semibold min-w-[200px] text-center">{MONTHS[month]} {year}</h2>
        <Button onClick={nextMonth}>&gt;</Button>
        <Select value={filterLotId || undefined} onChange={v => setFilterLotId(v || "")} placeholder="All Lots" allowClear className="ml-auto" style={{ width: 180 }}
          options={lots.map(l => ({ label: l.name, value: l.id }))} />
      </div>

      <div className="flex flex-wrap gap-2">
        {visibleSeasons.length > 0 ? visibleSeasons.map(s => {
          const colors = seasonColorMap.get(s.id) ?? SEASON_PALETTE[0];
          return (
            <div key={s.id} className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium ${colors.banner}`}>
              <span className={`w-2 h-2 rounded-full ${colors.dot}`} />
              <span>{s.label}</span>
              <span className="opacity-60 font-normal">{formatSeasonDate(s.start_date)} &ndash; {formatSeasonDate(s.end_date)}</span>
            </div>
          );
        }) : <div className="px-3 py-2 rounded-lg text-sm text-ink-mute bg-gray-100">No academic season covers this month</div>}
        {lotteryEvents.length > 0 && (
          <div className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm bg-purple-50 text-purple-800">
            <span className="font-medium">Lotteries:</span>
            <span className="inline-block w-2.5 h-2.5 rounded bg-purple-100 border border-purple-300" /> Opens
            <span className="inline-block w-2.5 h-2.5 rounded bg-purple-200 border border-purple-400" /> Closes
            <span className="inline-block w-2.5 h-2.5 rounded bg-purple-500 border border-purple-600" /> Drawing
          </div>
        )}
      </div>

      <div className="bg-white rounded-xl shadow overflow-hidden">
        <div className="grid grid-cols-7">
          {WEEKDAYS.map(d => <div key={d} className="text-center text-xs font-bold text-ink-mute uppercase tracking-wider py-3 border-b border-gray-200 bg-gray-50">{d}</div>)}
        </div>
        <div className="grid grid-cols-7">
          {cells.map((dayNum, idx) => {
            if (dayNum === null) return <div key={`e-${idx}`} className="min-h-[100px] border-b border-r border-gray-100 bg-gray-50/50" />;
            const dayClosures = getClosuresForDay(dayNum);
            const dayLotteries = getLotteryEventsForDay(dayNum);
            const isToday = sameDay(new Date(year, month, dayNum), today);
            const daySeason = getSeasonForDay(dayNum);
            const sc = daySeason ? seasonColorMap.get(daySeason.id) : null;
            return (
              <div key={dayNum} className={`min-h-[100px] border-b border-r border-gray-100 p-1.5 ${sc ? `${sc.bg} border-l-2 ${sc.border}` : ""} ${isToday ? "!bg-brand-primary/10" : ""}`}>
                <div className="flex items-center gap-1">
                  <span className={`text-xs font-medium ${isToday ? "text-brand-primary font-bold" : "text-ink-mute"}`}>{dayNum}</span>
                  {daySeason && <span className="text-[8px] text-ink-mute/60 truncate leading-none">{daySeason.code}</span>}
                </div>
                <div className="space-y-0.5 mt-0.5">
                  {dayLotteries.map(ev => (
                    <div key={ev.id}
                      className={`w-full text-left text-[10px] leading-tight px-1 py-0.5 rounded border truncate ${LOTTERY_STYLES[ev.type]}`}
                      title={`${ev.label} — Lottery ${LOTTERY_LABELS[ev.type]}`}>
                      🎟 {LOTTERY_LABELS[ev.type]}: {ev.label}
                    </div>
                  ))}
                  {dayClosures.slice(0, 3).map(c => (
                    <button key={c.id} onClick={() => setSelectedClosure(c)}
                      className={`w-full text-left text-[10px] leading-tight px-1 py-0.5 rounded border truncate ${STATUS_COLORS[c.status]?.tw || "bg-gray-100 text-gray-500 border-gray-200"}`}
                      title={`${c.lot_name}: ${c.reason || c.status}`}>
                      {c.lot_name}
                    </button>
                  ))}
                  {dayClosures.length > 3 && <div className="text-[10px] text-ink-mute pl-1">+{dayClosures.length - 3} more</div>}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="bg-white rounded-xl shadow p-6">
        <h3 className="text-sm font-bold uppercase text-ink-mute tracking-wide mb-4">All Closures</h3>
        {filtered.length === 0 ? <Empty description="No closures scheduled" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
          <div className="space-y-2">
            {filtered.map(c => (
              <button key={c.id} onClick={() => setSelectedClosure(c)} className="w-full flex items-center gap-3 p-3 rounded-lg hover:bg-gray-50 transition-colors text-left">
                <Tag color={STATUS_COLORS[c.status]?.antd || "default"}>{c.status}</Tag>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{c.lot_name}</div>
                  <div className="text-xs text-ink-mute truncate">{c.reason || "No reason"}</div>
                </div>
                <div className="text-xs text-ink-mute text-right flex-shrink-0">
                  <div>{new Date(c.closes_at).toLocaleDateString()}</div>
                  <div>{c.reopens_at ? `until ${new Date(c.reopens_at).toLocaleDateString()}` : "open-ended"}</div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Schedule Modal */}
      <Modal open={scheduling} title="Schedule Lot Closure" okText="Schedule Closure" confirmLoading={schedSubmitting}
        onOk={handleSchedule} onCancel={() => setScheduling(false)} okButtonProps={{ disabled: !schedClosesAt }}>
        <div className="space-y-3">
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Lot</label>
            <Select value={schedLotId || undefined} onChange={setSchedLotId} className="w-full" options={lots.map(l => ({ label: l.name, value: l.id }))} /></div>
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Reason</label>
            <Input value={schedReason} onChange={e => setSchedReason(e.target.value)} placeholder="Snow removal, event..." /></div>
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Closes At</label>
            <DatePicker showTime value={schedClosesAt} onChange={setSchedClosesAt} className="w-full" /></div>
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Reopens At (optional)</label>
            <DatePicker showTime value={schedReopensAt} onChange={setSchedReopensAt} className="w-full" /></div>
        </div>
      </Modal>

      {/* Detail Modal */}
      <Modal open={!!selectedClosure && !editingClosure} onCancel={() => setSelectedClosure(null)}
        title={<Space>{selectedClosure?.lot_name || "Closure"}<Tag color={STATUS_COLORS[selectedClosure?.status ?? ""]?.antd}>{selectedClosure?.status}</Tag></Space>}
        footer={
          <Space>
            <Button onClick={() => setSelectedClosure(null)}>Close</Button>
            {selectedClosure && ["scheduled", "active"].includes(selectedClosure.status) && (
              <>
                <Button onClick={() => openEditModal(selectedClosure!)}>Edit</Button>
                <Button danger onClick={() => handleCancelClosure(selectedClosure!.id)}>Cancel Closure</Button>
              </>
            )}
          </Space>
        }>
        {selectedClosure && (
          <Descriptions column={1} size="small">
            <Descriptions.Item label="Reason">{selectedClosure.reason || "—"}</Descriptions.Item>
            <Descriptions.Item label="Closes">{new Date(selectedClosure.closes_at).toLocaleString()}</Descriptions.Item>
            <Descriptions.Item label="Reopens">{selectedClosure.reopens_at ? new Date(selectedClosure.reopens_at).toLocaleString() : "Manual reopen"}</Descriptions.Item>
            <Descriptions.Item label="Created by">{selectedClosure.created_by}</Descriptions.Item>
            <Descriptions.Item label="Notification">{selectedClosure.notification_sent ? "Yes" : "No"}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>

      {/* Edit Modal */}
      <Modal open={!!editingClosure} title="Edit Closure" okText="Save Changes" confirmLoading={editSaving}
        onOk={handleEditSave} onCancel={() => setEditingClosure(null)}>
        <div className="space-y-3">
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Reason</label>
            <Input value={editReason} onChange={e => setEditReason(e.target.value)} /></div>
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Closes At</label>
            <DatePicker showTime value={editClosesAt} onChange={setEditClosesAt} className="w-full" /></div>
          <div><label className="block text-xs font-medium text-ink-mute mb-1">Reopens At</label>
            <DatePicker showTime value={editReopensAt} onChange={setEditReopensAt} className="w-full" /></div>
        </div>
      </Modal>
    </div>
  );
}
