import { useCallback, useEffect, useState } from "react";
import { api, AcademicSeason, Lot, LotClosure } from "../api";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function getDaysInMonth(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate();
}

function getFirstDayOfWeek(year: number, month: number) {
  return new Date(year, month, 1).getDay();
}

function sameDay(a: Date, b: Date) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function dayInRange(day: Date, start: Date, end: Date | null) {
  const d = day.getTime();
  const s = new Date(start.getFullYear(), start.getMonth(), start.getDate()).getTime();
  if (!end) return d >= s;
  const e = new Date(end.getFullYear(), end.getMonth(), end.getDate()).getTime();
  return d >= s && d <= e;
}

const STATUS_COLORS: Record<string, string> = {
  active: "bg-signal-red/20 text-signal-red border-signal-red/40",
  scheduled: "bg-amber-100 text-amber-800 border-amber-300",
  completed: "bg-emerald-100 text-emerald-700 border-emerald-300",
  cancelled: "bg-gray-100 text-gray-400 border-gray-200 line-through",
};

const SEASON_PALETTE = [
  { bg: "bg-indigo-50", border: "border-l-indigo-400", banner: "bg-indigo-100 text-indigo-800", dot: "bg-indigo-400" },
  { bg: "bg-teal-50", border: "border-l-teal-400", banner: "bg-teal-100 text-teal-800", dot: "bg-teal-400" },
  { bg: "bg-rose-50", border: "border-l-rose-400", banner: "bg-rose-100 text-rose-800", dot: "bg-rose-400" },
  { bg: "bg-amber-50", border: "border-l-amber-400", banner: "bg-amber-100 text-amber-800", dot: "bg-amber-400" },
  { bg: "bg-violet-50", border: "border-l-violet-400", banner: "bg-violet-100 text-violet-800", dot: "bg-violet-400" },
  { bg: "bg-cyan-50", border: "border-l-cyan-400", banner: "bg-cyan-100 text-cyan-800", dot: "bg-cyan-400" },
];

function dateInSeason(d: Date, season: AcademicSeason): boolean {
  const start = new Date(season.start_date + "T00:00:00");
  const end = new Date(season.end_date + "T23:59:59");
  return d >= start && d <= end;
}

function seasonOverlapsMonth(season: AcademicSeason, year: number, month: number): boolean {
  const monthStart = new Date(year, month, 1);
  const monthEnd = new Date(year, month + 1, 0, 23, 59, 59);
  const sStart = new Date(season.start_date + "T00:00:00");
  const sEnd = new Date(season.end_date + "T23:59:59");
  return sStart <= monthEnd && sEnd >= monthStart;
}

function formatSeasonDate(isoDate: string): string {
  const d = new Date(isoDate + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function ScheduleClosureModal({
  lots,
  onClose,
  onDone,
}: {
  lots: Lot[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [lotId, setLotId] = useState(lots[0]?.id ?? "");
  const [reason, setReason] = useState("");
  const [closesAt, setClosesAt] = useState("");
  const [reopensAt, setReopensAt] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!closesAt) return;
    setSubmitting(true);
    try {
      await api.lots.closures.schedule({
        lot_id: lotId,
        reason,
        closes_at: new Date(closesAt).toISOString(),
        reopens_at: reopensAt ? new Date(reopensAt).toISOString() : undefined,
      });
      onDone();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4"
      >
        <h3 className="text-lg font-bold">Schedule Lot Closure</h3>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Lot</label>
          <select
            value={lotId}
            onChange={(e) => setLotId(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
          >
            {lots.map((l) => (
              <option key={l.id} value={l.id}>{l.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Reason</label>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Snow removal, event, maintenance..."
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Closes At</label>
          <input
            type="datetime-local"
            value={closesAt}
            onChange={(e) => setClosesAt(e.target.value)}
            required
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Reopens At (optional)</label>
          <input
            type="datetime-local"
            value={reopensAt}
            onChange={(e) => setReopensAt(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
          />
        </div>
        <div className="flex gap-2 pt-2">
          <button
            type="submit"
            disabled={submitting || !closesAt}
            className="flex-1 px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors disabled:opacity-50"
          >
            {submitting ? "Scheduling..." : "Schedule Closure"}
          </button>
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-ink-mute hover:text-ink">
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}

function toLocalDatetimeValue(iso: string) {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function EditClosureModal({
  closure,
  onClose,
  onSaved,
}: {
  closure: LotClosure;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [reason, setReason] = useState(closure.reason ?? "");
  const [closesAt, setClosesAt] = useState(toLocalDatetimeValue(closure.closes_at));
  const [reopensAt, setReopensAt] = useState(closure.reopens_at ? toLocalDatetimeValue(closure.reopens_at) : "");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.lots.closures.update(closure.id, {
        reason: reason || undefined,
        closes_at: new Date(closesAt).toISOString(),
        reopens_at: reopensAt ? new Date(reopensAt).toISOString() : undefined,
      });
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <h3 className="text-lg font-bold">Edit Closure</h3>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Reason</label>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Snow removal, event, maintenance..."
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Closes At</label>
          <input
            type="datetime-local"
            value={closesAt}
            onChange={(e) => setClosesAt(e.target.value)}
            required
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Reopens At (optional)</label>
          <input
            type="datetime-local"
            value={reopensAt}
            onChange={(e) => setReopensAt(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
          />
        </div>
        <div className="flex gap-2 pt-2">
          <button
            type="submit"
            disabled={saving}
            className="flex-1 px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save Changes"}
          </button>
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-ink-mute hover:text-ink">
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}

function ClosureDetailModal({
  closure,
  onClose,
  onCancel,
  onEdit,
}: {
  closure: LotClosure;
  onClose: () => void;
  onCancel: (id: string) => void;
  onEdit: (closure: LotClosure) => void;
}) {
  const closes = new Date(closure.closes_at);
  const reopens = closure.reopens_at ? new Date(closure.reopens_at) : null;

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-bold">{closure.lot_name || "Lot Closure"}</h3>
          <span
            className={`text-[10px] px-2 py-0.5 rounded-full font-bold uppercase ${
              STATUS_COLORS[closure.status] || "bg-gray-100 text-gray-500"
            }`}
          >
            {closure.status}
          </span>
        </div>
        <div className="text-sm space-y-1">
          <p><span className="text-ink-mute">Reason:</span> {closure.reason || "—"}</p>
          <p><span className="text-ink-mute">Closes:</span> {closes.toLocaleString()}</p>
          <p>
            <span className="text-ink-mute">Reopens:</span>{" "}
            {reopens ? reopens.toLocaleString() : "Manual reopen"}
          </p>
          <p><span className="text-ink-mute">Created by:</span> {closure.created_by}</p>
          <p>
            <span className="text-ink-mute">Notification sent:</span>{" "}
            {closure.notification_sent ? "Yes" : "No"}
          </p>
        </div>
        <div className="flex gap-2 pt-3">
          {(closure.status === "scheduled" || closure.status === "active") && (
            <>
              <button
                onClick={() => onEdit(closure)}
                className="px-4 py-2 bg-brass/10 text-brass-deep font-medium rounded-lg text-sm hover:bg-brass/20 transition-colors"
              >
                Edit
              </button>
              <button
                onClick={() => onCancel(closure.id)}
                className="px-4 py-2 bg-signal-red/10 text-signal-red font-medium rounded-lg text-sm hover:bg-signal-red/20 transition-colors"
              >
                Cancel Closure
              </button>
            </>
          )}
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-ink-mute hover:text-ink ml-auto"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export default function OperationsCalendar() {
  const [lots, setLots] = useState<Lot[]>([]);
  const [closures, setClosures] = useState<LotClosure[]>([]);
  const [seasons, setSeasons] = useState<AcademicSeason[]>([]);
  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(new Date().getMonth());
  const [scheduling, setScheduling] = useState(false);
  const [selectedClosure, setSelectedClosure] = useState<LotClosure | null>(null);
  const [editingClosure, setEditingClosure] = useState<LotClosure | null>(null);
  const [filterLotId, setFilterLotId] = useState<string>("");

  const load = useCallback(async () => {
    const [lotsData, closuresData, seasonsData] = await Promise.all([
      api.lots.list(),
      api.lots.closures.listAll(),
      api.academicCalendar.list(),
    ]);
    setLots(lotsData);
    setClosures(closuresData);
    setSeasons(seasonsData);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function prevMonth() {
    if (month === 0) {
      setMonth(11);
      setYear(year - 1);
    } else {
      setMonth(month - 1);
    }
  }

  function nextMonth() {
    if (month === 11) {
      setMonth(0);
      setYear(year + 1);
    } else {
      setMonth(month + 1);
    }
  }

  async function handleCancelClosure(closureId: string) {
    await api.lots.closures.cancel(closureId);
    setSelectedClosure(null);
    load();
  }

  const daysInMonth = getDaysInMonth(year, month);
  const firstDay = getFirstDayOfWeek(year, month);
  const today = new Date();

  const filteredClosures = filterLotId
    ? closures.filter((c) => c.lot_id === filterLotId)
    : closures;

  function getClosuresForDay(dayNum: number) {
    const day = new Date(year, month, dayNum);
    return filteredClosures.filter((c) => {
      const start = new Date(c.closes_at);
      const end = c.reopens_at ? new Date(c.reopens_at) : null;
      return dayInRange(day, start, end);
    });
  }

  const cells: (number | null)[] = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  const seasonColorMap = new Map<string, (typeof SEASON_PALETTE)[number]>();
  seasons.forEach((s, i) => {
    seasonColorMap.set(s.id, SEASON_PALETTE[i % SEASON_PALETTE.length]);
  });

  const visibleSeasons = seasons.filter((s) => seasonOverlapsMonth(s, year, month));

  function getSeasonForDay(dayNum: number) {
    const d = new Date(year, month, dayNum);
    return seasons.find((s) => dateInSeason(d, s)) ?? null;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Operations Calendar</h1>
        <button
          onClick={() => setScheduling(true)}
          className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors"
        >
          + Schedule Closure
        </button>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-4">
        <button onClick={prevMonth} className="p-2 hover:bg-gray-100 rounded-lg text-lg">&lt;</button>
        <h2 className="text-lg font-semibold min-w-[200px] text-center">
          {MONTHS[month]} {year}
        </h2>
        <button onClick={nextMonth} className="p-2 hover:bg-gray-100 rounded-lg text-lg">&gt;</button>

        <select
          value={filterLotId}
          onChange={(e) => setFilterLotId(e.target.value)}
          className="ml-auto border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
        >
          <option value="">All Lots</option>
          {lots.map((l) => (
            <option key={l.id} value={l.id}>{l.name}</option>
          ))}
        </select>
      </div>

      {/* Academic season banner */}
      <div className="flex flex-wrap gap-2">
        {visibleSeasons.length > 0 ? (
          visibleSeasons.map((s) => {
            const colors = seasonColorMap.get(s.id) ?? SEASON_PALETTE[0];
            return (
              <div
                key={s.id}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium ${colors.banner}`}
              >
                <span className={`w-2 h-2 rounded-full ${colors.dot}`} />
                <span>{s.label}</span>
                <span className="opacity-60 font-normal">
                  {formatSeasonDate(s.start_date)} &ndash; {formatSeasonDate(s.end_date)}
                </span>
              </div>
            );
          })
        ) : (
          <div className="px-3 py-2 rounded-lg text-sm text-ink-mute bg-gray-100">
            No academic season covers this month
          </div>
        )}
      </div>

      {/* Calendar grid */}
      <div className="bg-white rounded-xl shadow overflow-hidden">
        <div className="grid grid-cols-7">
          {WEEKDAYS.map((d) => (
            <div key={d} className="text-center text-xs font-bold text-ink-mute uppercase tracking-wider py-3 border-b border-gray-200 bg-gray-50">
              {d}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7">
          {cells.map((dayNum, idx) => {
            if (dayNum === null) {
              return <div key={`empty-${idx}`} className="min-h-[100px] border-b border-r border-gray-100 bg-gray-50/50" />;
            }
            const dayClosure = getClosuresForDay(dayNum);
            const isToday = sameDay(new Date(year, month, dayNum), today);
            const daySeason = getSeasonForDay(dayNum);
            const seasonColors = daySeason ? seasonColorMap.get(daySeason.id) : null;

            return (
              <div
                key={dayNum}
                className={`min-h-[100px] border-b border-r border-gray-100 p-1.5 ${
                  seasonColors ? `${seasonColors.bg} border-l-2 ${seasonColors.border}` : ""
                } ${isToday ? "!bg-brass/10" : ""}`}
              >
                <div className="flex items-center gap-1">
                  <span className={`text-xs font-medium ${isToday ? "text-brass font-bold" : "text-ink-mute"}`}>
                    {dayNum}
                  </span>
                  {daySeason && (
                    <span className="text-[8px] text-ink-mute/60 truncate leading-none">
                      {daySeason.code}
                    </span>
                  )}
                </div>
                <div className="space-y-0.5 mt-0.5">
                  {dayClosure.slice(0, 3).map((c) => (
                    <button
                      key={c.id}
                      onClick={() => setSelectedClosure(c)}
                      className={`w-full text-left text-[10px] leading-tight px-1 py-0.5 rounded border truncate ${
                        STATUS_COLORS[c.status] || "bg-gray-100 text-gray-500 border-gray-200"
                      }`}
                      title={`${c.lot_name}: ${c.reason || c.status}`}
                    >
                      {c.lot_name}
                    </button>
                  ))}
                  {dayClosure.length > 3 && (
                    <div className="text-[10px] text-ink-mute pl-1">+{dayClosure.length - 3} more</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Upcoming closures list */}
      <div className="bg-white rounded-xl shadow p-6">
        <h3 className="text-sm font-bold uppercase text-ink-mute tracking-wide mb-4">
          All Closures
        </h3>
        {filteredClosures.length === 0 && (
          <p className="text-sm text-ink-mute">No closures scheduled.</p>
        )}
        <div className="space-y-2">
          {filteredClosures.map((c) => {
            const closes = new Date(c.closes_at);
            const reopens = c.reopens_at ? new Date(c.reopens_at) : null;
            return (
              <button
                key={c.id}
                onClick={() => setSelectedClosure(c)}
                className="w-full flex items-center gap-3 p-3 rounded-lg hover:bg-gray-50 transition-colors text-left"
              >
                <span
                  className={`text-[10px] px-2 py-0.5 rounded-full font-bold uppercase flex-shrink-0 ${
                    STATUS_COLORS[c.status] || "bg-gray-100 text-gray-500"
                  }`}
                >
                  {c.status}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{c.lot_name}</div>
                  <div className="text-xs text-ink-mute truncate">{c.reason || "No reason"}</div>
                </div>
                <div className="text-xs text-ink-mute text-right flex-shrink-0">
                  <div>{closes.toLocaleDateString()}</div>
                  <div>{reopens ? `until ${reopens.toLocaleDateString()}` : "open-ended"}</div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {scheduling && (
        <ScheduleClosureModal
          lots={lots}
          onClose={() => setScheduling(false)}
          onDone={() => {
            setScheduling(false);
            load();
          }}
        />
      )}

      {selectedClosure && !editingClosure && (
        <ClosureDetailModal
          closure={selectedClosure}
          onClose={() => setSelectedClosure(null)}
          onCancel={handleCancelClosure}
          onEdit={(c) => setEditingClosure(c)}
        />
      )}

      {editingClosure && (
        <EditClosureModal
          closure={editingClosure}
          onClose={() => setEditingClosure(null)}
          onSaved={() => {
            setEditingClosure(null);
            setSelectedClosure(null);
            load();
          }}
        />
      )}
    </div>
  );
}
