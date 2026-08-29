import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, Statistic, Spin, Tag, Segmented, Empty } from "antd";
import { authHeaders, isAdminRole } from "../auth";
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
  ticket_number: string | null;
  plate: string;
  lot: string;
  status: string;
  appeal_note: string | null;
  issued_at: string;
  created_at: string;
}

interface ActivityEvent {
  id: string;
  ticket_number: string | null;
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
  pending_vehicle_requests: number;
}

const PERIOD_LABELS: Record<Period, string> = {
  today: "Today",
  week: "Last 7 days",
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

function ageBadge(issuedAt: string): { label: string; color: "red" | "gold" | "blue" } {
  const days = Math.floor(
    (Date.now() - new Date(issuedAt).getTime()) / 86_400_000
  );
  if (days > 3) return { label: `${days}d overdue`, color: "red" };
  if (days >= 1) return { label: "review", color: "gold" };
  return { label: "new", color: "blue" };
}

function eventDescription(e: ActivityEvent): string {
  const num = e.ticket_number || e.id.slice(0, 8);
  const fine = `$${Number(e.fine_amount).toFixed(2)}`;
  switch (e.status) {
    case "issued":
      return `${num} issued — ${e.lot || "Unknown lot"}, ${e.violation_type.replace(/_/g, " ")}`;
    case "paid":
      return `${num} paid — ${fine}`;
    case "appealed":
      return `Appeal filed on ${num}`;
    case "escalated":
      return `${num} escalated`;
    case "voided":
      return `${num} voided`;
    case "pending_payment":
      return `${num} pending payment — ${fine}`;
    case "resolved_permit":
      return `${num} resolved via permit`;
    default:
      return `${num} — ${e.status}`;
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
  const navigate = useNavigate();
  const user = useCurrentUser();
  const [data, setData] = useState<DashboardData | null>(null);
  const [period, setPeriod] = useState<Period>("today");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/tickets/dashboard?period=${period}`, {
        headers: await authHeaders(),
      });
      if (res.ok) setData(await res.json());
    } catch {
      /* network error */
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    setLoading(true);
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, [load]);


  const name = user ? extractName(user.email) : "";
  const maxTrend = data ? Math.max(...data.trend.map((d) => d.count), 1) : 1;
  const todayStr = new Date().toISOString().slice(0, 10);

  return (
    <Spin spinning={loading && !data} size="large">
      <div className="space-y-6">
        <div className="flex items-end justify-between">
          <div>
            <h2 className="text-2xl font-bold text-brand-primary">
              {getGreeting()}, {name}
            </h2>
            <p className="text-sm text-ink-mute mt-0.5">
              {formatDate()} — here's what needs attention.
            </p>
          </div>
          <Segmented
            value={period}
            onChange={(val) => setPeriod(val as Period)}
            options={[
              { label: "Today", value: "today" },
              { label: "Last 7 days", value: "week" },
              { label: "This month", value: "month" },
            ]}
          />
        </div>

        {data && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <Card size="small" className="!bg-red-50 cursor-pointer hover:shadow-md transition-shadow" onClick={() => navigate("/tickets?status=appealed")}>
              <Statistic
                title={<span className="text-red-700">Needs action</span>}
                value={data.needs_action.total + (data.pending_vehicle_requests || 0)}
                valueStyle={{ color: "#b91c1c", fontWeight: 700 }}
              />
              <div className="text-xs text-red-600/70 mt-1">
                {data.needs_action.appealed} appeal{data.needs_action.appealed !== 1 ? "s" : ""},
                {" "}{data.needs_action.escalated} escalation{data.needs_action.escalated !== 1 ? "s" : ""}
                {data.pending_vehicle_requests > 0 && (
                  <span className="ml-1 cursor-pointer underline" onClick={(e) => { e.stopPropagation(); navigate("/permits#vehicle-requests"); }}>
                    , {data.pending_vehicle_requests} vehicle request{data.pending_vehicle_requests !== 1 ? "s" : ""}
                  </span>
                )}
              </div>
            </Card>

            <Card size="small" className="cursor-pointer hover:shadow-md transition-shadow" onClick={() => navigate("/tickets")}>
              <Statistic
                title={`Issued ${PERIOD_LABELS[period].toLowerCase()}`}
                value={data.issued_count.total}
                valueStyle={{ color: "var(--brand-primary)", fontWeight: 700 }}
              />
              <div className="text-xs text-ink-mute mt-1">
                vs {data.issued_count.daily_avg} avg daily
              </div>
            </Card>

            {isAdminRole(user?.role) && (
            <Card size="small" className="cursor-pointer hover:shadow-md transition-shadow" onClick={() => navigate("/finance")}>
              <Statistic
                title={`Revenue ${PERIOD_LABELS[period].toLowerCase()}`}
                value={Number(data.revenue.collected)}
                prefix="$"
                precision={0}
                valueStyle={{ color: "var(--brand-primary)", fontWeight: 700 }}
              />
              <div className="text-xs text-ink-mute mt-1">
                {data.revenue.pending_count} pending (${Number(data.revenue.pending_amount).toFixed(0)})
              </div>
            </Card>
            )}

            <Card size="small" className="!bg-green-50 cursor-pointer hover:shadow-md transition-shadow" onClick={() => navigate("/tickets")}>
              <Statistic
                title={<span className="text-green-700">Resolution rate</span>}
                value={data.resolution_rate.rate}
                suffix="%"
                valueStyle={{ color: "#15803d", fontWeight: 700 }}
              />
              <div className="text-xs text-green-600/70 mt-1">
                {data.resolution_rate.resolved} of {data.resolution_rate.total} resolved
              </div>
            </Card>
          </div>
        )}

        {data && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card
              title="Action items"
              extra={<a className="text-xs" onClick={() => navigate("/tickets?status=appealed")}>View all</a>}
              styles={{ body: { padding: 0 } }}
            >
              {data.action_items.length === 0 ? (
                <Empty description="No pending items" className="py-8" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                <div className="divide-y divide-gray-50 max-h-[420px] overflow-y-auto">
                  {data.action_items.map((item) => {
                    const badge = ageBadge(item.issued_at);
                    const borderColor = badge.label.includes("overdue") ? "border-red-400" : "border-amber-400";
                    return (
                      <div key={item.id}
                        onClick={() => navigate(`/tickets?search=${item.ticket_number || item.id.slice(0, 8)}`)}
                        className={`px-5 py-3 border-l-4 ${borderColor} flex items-start gap-3 cursor-pointer hover:bg-gray-50 transition-colors`}>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm font-medium text-brand-primary">{item.ticket_number || `#${item.id.slice(0, 8)}`}</span>
                            <span className="text-xs text-ink-mute">{item.plate}</span>
                          </div>
                          {item.appeal_note ? (
                            <p className="text-xs text-ink-mute mt-0.5 line-clamp-2">{item.appeal_note}</p>
                          ) : (
                            <p className="text-xs text-ink-mute mt-0.5 italic">
                              {item.status === "escalated" ? "Escalated for review" : "Appeal pending"}
                            </p>
                          )}
                        </div>
                        <Tag color={badge.color}>{badge.label}</Tag>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>

            <Card
              title={`${PERIOD_LABELS[period]}'s activity`}
              extra={<a className="text-xs" onClick={() => navigate("/tickets")}>View all</a>}
              styles={{ body: { padding: 0 } }}
            >
              {data.activity.length === 0 ? (
                <Empty description="No activity yet" className="py-8" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                <div className="divide-y divide-gray-50 max-h-[420px] overflow-y-auto">
                  {data.activity.map((ev) => (
                    <div key={`${ev.id}-${ev.updated_at}`}
                      onClick={() => navigate(`/tickets?search=${ev.ticket_number || ev.id.slice(0, 8)}`)}
                      className="px-5 py-3 flex items-start gap-3 cursor-pointer hover:bg-gray-50 transition-colors">
                      <div className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${STATUS_DOTS[ev.status] || "bg-gray-300"}`} />
                      <div className="flex-1 min-w-0 text-sm text-ink">{eventDescription(ev)}</div>
                      <span className="text-xs text-ink-mute shrink-0 whitespace-nowrap">
                        {period === "today"
                          ? new Date(ev.updated_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
                          : new Date(ev.updated_at).toLocaleDateString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        )}

        {data && (
          <Card title="Tickets issued — last 7 days" size="small">
            <div className="flex items-end justify-between gap-2" style={{ height: 80 }}>
              {data.trend.map((d) => {
                const pct = maxTrend > 0 ? (d.count / maxTrend) * 100 : 0;
                const isToday = d.date === todayStr;
                return (
                  <div key={d.date} className="flex-1 flex flex-col items-center gap-1">
                    <span className="text-xs font-medium text-brand-primary">{d.count}</span>
                    <div
                      className={`w-full rounded-t ${isToday ? "bg-blue-600" : "bg-blue-300"}`}
                      style={{ height: `${Math.max(pct, 4)}%`, minHeight: 4, transition: "height 0.3s ease" }}
                    />
                    <span className="text-[11px] text-ink-mute">{d.day}</span>
                  </div>
                );
              })}
            </div>
          </Card>
        )}
      </div>
    </Spin>
  );
}
