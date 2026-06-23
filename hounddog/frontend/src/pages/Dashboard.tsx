import { useCallback, useEffect, useRef, useState } from "react";
import { authHeaders, getAccessToken } from "../auth";
import { useCurrentUser } from "../UserContext";

type Period = "today" | "week" | "month";

interface NeedsAction {
  total: number;
  appealed: number;
  escalated: number;
}

interface IssuedCount {
  total: number;
  daily_avg: number;
}

interface Revenue {
  collected: string;
  pending_count: number;
  pending_amount: string;
}

interface ResolutionRate {
  rate: number;
  resolved: number;
  total: number;
}

interface ActionItem {
  id: string;
  plate: string;
  lot: string;
  status: string;
  appeal_note: string | null;
  issued_at: string;
  created_at: string;
}

interface ActivityEvent {
  id: string;
  plate: string;
  lot: string;
  status: string;
  violation_type: string;
  fine_amount: string;
  issued_at: string;
  updated_at: string;
}

interface TrendDay {
  date: string;
  day: string;
  count: number;
}

interface DashboardData {
  needs_action: NeedsAction;
  issued_count: IssuedCount;
  revenue: Revenue;
  resolution_rate: ResolutionRate;
  action_items: ActionItem[];
  activity: ActivityEvent[];
  trend: TrendDay[];
}

const PERIOD_LABELS: Record<Period, string> = {
  today: "Today",
  week: "This week",
  month: "This month",
};

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function extractName(email: string): string {
  const local = email.split("@")[0];
  return local
    .split(/[._-]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function formatDate(): string {
  return new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

function ageBadge(issuedAt: string): { label: string; color: string } {
  const days = Math.floor(
    (Date.now() - new Date(issuedAt).getTime()) / 86_400_000
  );
  if (days > 3) return { label: `${days}d overdue`, color: "bg-red-100 text-red-700" };
  if (days >= 1) return { label: "review", color: "bg-amber-100 text-amber-700" };
  return { label: "new", color: "bg-blue-100 text-blue-700" };
}

function eventDescription(e: ActivityEvent): string {
  const num = e.id.slice(0, 8);
  const fine = `$${Number(e.fine_amount).toFixed(2)}`;
  switch (e.status) {
    case "issued":
      return `Ticket #${num} issued — ${e.lot || "Unknown lot"}, ${e.violation_type.replace(/_/g, " ")}`;
    case "paid":
      return `Ticket #${num} paid — ${fine}`;
    case "appealed":
      return `Appeal filed on #${num}`;
    case "escalated":
      return `Ticket #${num} escalated`;
    case "voided":
      return `Ticket #${num} voided`;
    case "pending_payment":
      return `Ticket #${num} pending payment — ${fine}`;
    case "resolved_permit":
      return `Ticket #${num} resolved via permit`;
    default:
      return `Ticket #${num} — ${e.status}`;
  }
}

const STATUS_DOTS: Record<string, string> = {
  issued: "bg-red-500",
  paid: "bg-green-500",
  appealed: "bg-amber-500",
  escalated: "bg-amber-500",
  voided: "bg-gray-400",
  pending_payment: "bg-orange-400",
  resolved_permit: "bg-green-400",
};

export default function Dashboard() {
  const user = useCurrentUser();
  const [data, setData] = useState<DashboardData | null>(null);
  const [period, setPeriod] = useState<Period>("today");
  const wsRef = useRef<WebSocket | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/tickets/dashboard?period=${period}`, {
        headers: await authHeaders(),
      });
      if (res.ok) setData(await res.json());
    } catch {}
  }, [period]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, [load]);

  // WebSocket for live refresh
  useEffect(() => {
    let cancelled = false;
    const connect = async () => {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const token = await getAccessToken();
      const url = token
        ? `${proto}//${window.location.host}/ws?token=${encodeURIComponent(token)}`
        : `${proto}//${window.location.host}/ws`;
      if (cancelled) return;
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onmessage = () => load();
      ws.onerror = () => {};
      ws.onclose = () => {
        if (!cancelled) setTimeout(connect, 3000);
      };
    };
    connect();
    return () => {
      cancelled = true;
      wsRef.current?.close();
    };
  }, [load]);

  const name = user ? extractName(user.email) : "";
  const maxTrend = data ? Math.max(...data.trend.map((d) => d.count), 1) : 1;
  const todayStr = new Date().toISOString().slice(0, 10);

  return (
    <div className="space-y-6">
      {/* ── Header row ── */}
      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-bold text-navy">
            {getGreeting()}, {name}
          </h2>
          <p className="text-sm text-ink-mute mt-0.5">
            {formatDate()} — here's what needs attention.
          </p>
        </div>
        <div className="flex gap-1 bg-bone rounded-full p-1">
          {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                period === p
                  ? "bg-brass text-navy-deep shadow-sm"
                  : "text-ink-mute hover:text-navy"
              }`}
            >
              {PERIOD_LABELS[p]}
            </button>
          ))}
        </div>
      </div>

      {/* ── Metric cards ── */}
      {data && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Needs action */}
          <div className="bg-red-50 rounded-xl shadow p-4">
            <div className="text-xs font-medium text-red-700 uppercase tracking-wide">
              Needs action
            </div>
            <div className="text-3xl font-bold text-red-700 mt-1">
              {data.needs_action.total}
            </div>
            <div className="text-xs text-red-600/70 mt-1">
              {data.needs_action.appealed} appeal
              {data.needs_action.appealed !== 1 ? "s" : ""}
              , {data.needs_action.escalated} escalation
              {data.needs_action.escalated !== 1 ? "s" : ""}
            </div>
          </div>

          {/* Issued */}
          <div className="bg-white rounded-xl shadow p-4">
            <div className="text-xs font-medium text-ink-mute uppercase tracking-wide">
              Issued {PERIOD_LABELS[period].toLowerCase()}
            </div>
            <div className="text-3xl font-bold text-navy mt-1">
              {data.issued_count.total}
            </div>
            <div className="text-xs text-ink-mute mt-1">
              vs {data.issued_count.daily_avg} avg daily
            </div>
          </div>

          {/* Revenue */}
          <div className="bg-white rounded-xl shadow p-4">
            <div className="text-xs font-medium text-ink-mute uppercase tracking-wide">
              Revenue {PERIOD_LABELS[period].toLowerCase()}
            </div>
            <div className="text-3xl font-bold text-navy mt-1">
              ${Number(data.revenue.collected).toFixed(0)}
            </div>
            <div className="text-xs text-ink-mute mt-1">
              {data.revenue.pending_count} pending ($
              {Number(data.revenue.pending_amount).toFixed(0)})
            </div>
          </div>

          {/* Resolution rate */}
          <div className="bg-green-50 rounded-xl shadow p-4">
            <div className="text-xs font-medium text-green-700 uppercase tracking-wide">
              Resolution rate
            </div>
            <div className="text-3xl font-bold text-green-700 mt-1">
              {data.resolution_rate.rate}%
            </div>
            <div className="text-xs text-green-600/70 mt-1">
              {data.resolution_rate.resolved} of {data.resolution_rate.total}{" "}
              resolved
            </div>
          </div>
        </div>
      )}

      {/* ── Two-column panels ── */}
      {data && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Action items */}
          <div className="bg-white rounded-xl shadow overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-100">
              <h3 className="font-semibold text-navy">Action items</h3>
              <p className="text-xs text-ink-mute">
                Appeals & escalations needing review
              </p>
            </div>
            <div className="divide-y divide-gray-50 max-h-[420px] overflow-y-auto">
              {data.action_items.length === 0 && (
                <div className="px-5 py-12 text-center text-ink-mute text-sm">
                  No pending items
                </div>
              )}
              {data.action_items.map((item) => {
                const badge = ageBadge(item.issued_at);
                const borderColor =
                  badge.label.includes("overdue")
                    ? "border-red-400"
                    : "border-amber-400";
                return (
                  <div
                    key={item.id}
                    className={`px-5 py-3 border-l-4 ${borderColor} flex items-start gap-3`}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-medium text-navy">
                          #{item.id.slice(0, 8)}
                        </span>
                        <span className="text-xs text-ink-mute">
                          {item.plate}
                        </span>
                      </div>
                      {item.appeal_note && (
                        <p className="text-xs text-ink-mute mt-0.5 line-clamp-2">
                          {item.appeal_note}
                        </p>
                      )}
                      {!item.appeal_note && (
                        <p className="text-xs text-ink-mute mt-0.5 italic">
                          {item.status === "escalated"
                            ? "Escalated for review"
                            : "Appeal pending"}
                        </p>
                      )}
                    </div>
                    <span
                      className={`shrink-0 text-[11px] font-medium px-2 py-0.5 rounded-full ${badge.color}`}
                    >
                      {badge.label}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Activity feed */}
          <div className="bg-white rounded-xl shadow overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-100">
              <h3 className="font-semibold text-navy">
                {PERIOD_LABELS[period]}'s activity
              </h3>
              <p className="text-xs text-ink-mute">
                Ticket lifecycle events
              </p>
            </div>
            <div className="divide-y divide-gray-50 max-h-[420px] overflow-y-auto">
              {data.activity.length === 0 && (
                <div className="px-5 py-12 text-center text-ink-mute text-sm">
                  No activity yet
                </div>
              )}
              {data.activity.map((ev) => (
                <div
                  key={`${ev.id}-${ev.updated_at}`}
                  className="px-5 py-3 flex items-start gap-3"
                >
                  <div
                    className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                      STATUS_DOTS[ev.status] || "bg-gray-300"
                    }`}
                  />
                  <div className="flex-1 min-w-0 text-sm text-ink">
                    {eventDescription(ev)}
                  </div>
                  <span className="text-xs text-ink-mute shrink-0 whitespace-nowrap">
                    {new Date(ev.updated_at).toLocaleTimeString([], {
                      hour: "numeric",
                      minute: "2-digit",
                    })}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── 7-day trend ── */}
      {data && (
        <div className="bg-white rounded-xl shadow p-5">
          <h3 className="font-semibold text-navy text-sm mb-3">
            Tickets issued — last 7 days
          </h3>
          <div className="flex items-end justify-between gap-2" style={{ height: 80 }}>
            {data.trend.map((d) => {
              const pct = maxTrend > 0 ? (d.count / maxTrend) * 100 : 0;
              const isToday = d.date === todayStr;
              return (
                <div
                  key={d.date}
                  className="flex-1 flex flex-col items-center gap-1"
                >
                  <span className="text-xs font-medium text-navy">
                    {d.count}
                  </span>
                  <div
                    className={`w-full rounded-t ${
                      isToday ? "bg-blue-600" : "bg-blue-300"
                    }`}
                    style={{
                      height: `${Math.max(pct, 4)}%`,
                      minHeight: 4,
                      transition: "height 0.3s ease",
                    }}
                  />
                  <span className="text-[11px] text-ink-mute">{d.day}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
