import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, Statistic, Spin, Tag, Segmented, Empty, Progress } from "antd";
import {
  DollarOutlined,
  ExclamationCircleOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  CarOutlined,
  WarningOutlined,
  FileTextOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { authHeaders, isAdminRole } from "../auth";
import { useCurrentUser } from "../UserContext";
type Period = "today" | "week" | "month";

interface NeedsAction {
  total: number;
  appealed: number;
  escalated: number;
  overdue: number;
  past_due: number;
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

interface OutstandingBalance {
  total_unpaid: string;
  ticket_count: number;
  contactable_count: number;
  contactable_amount: string;
  uncollectable_count: number;
  uncollectable_amount: string;
}

interface EnforcementSnapshot {
  active_permits: number;
  active_tags: number;
  conduct_cases: number;
  registration_holds: number;
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
  outstanding: OutstandingBalance;
  enforcement: EnforcementSnapshot;
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
      return `${num} escalated to committee`;
    case "past_due":
      return `${num} past due — ${fine}`;
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
  escalated: "bg-purple-500",
  past_due: "bg-red-800",
  overdue: "bg-orange-500",
  voided: "bg-gray-400",
  pending_payment: "bg-orange-400",
  resolved_permit: "bg-green-400",
};

function fmtMoney(val: string | number): string {
  return Number(val).toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

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
  const isAdmin = isAdminRole(user?.role);

  return (
    <Spin spinning={loading && !data} size="large">
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-end justify-between">
          <div>
            <h2 className="text-2xl font-bold text-brand-primary">
              {getGreeting()}, {name}
            </h2>
            <p className="text-sm text-ink-mute mt-0.5">
              {formatDate()} — here&apos;s what needs attention.
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
          <>
            {/* Row 1: Key metrics */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {/* Issued */}
              <Card size="small" className="cursor-pointer hover:shadow-md transition-shadow" onClick={() => navigate("/tickets")}>
                <div className="flex items-start justify-between">
                  <Statistic
                    title={<span className="text-ink-mute">Issued {PERIOD_LABELS[period].toLowerCase()}</span>}
                    value={data.issued_count.total}
                    valueStyle={{ color: "var(--brand-primary)", fontWeight: 700 }}
                  />
                  <FileTextOutlined className="text-2xl text-brand-primary/30" />
                </div>
                <div className="text-xs text-ink-mute mt-1">
                  vs {data.issued_count.daily_avg} avg daily
                </div>
              </Card>

              {/* Revenue */}
              {isAdmin && (
                <Card size="small" className="cursor-pointer hover:shadow-md transition-shadow" onClick={() => navigate("/finance")}>
                  <div className="flex items-start justify-between">
                    <Statistic
                      title={<span className="text-ink-mute">Revenue {PERIOD_LABELS[period].toLowerCase()}</span>}
                      value={Number(data.revenue.collected)}
                      prefix="$"
                      precision={0}
                      valueStyle={{ color: "var(--brand-primary)", fontWeight: 700 }}
                    />
                    <DollarOutlined className="text-2xl text-green-500/30" />
                  </div>
                  <div className="text-xs text-ink-mute mt-1">
                    {data.revenue.pending_count} pending ({fmtMoney(data.revenue.pending_amount)})
                  </div>
                </Card>
              )}

              {/* Outstanding */}
              <Card size="small" className="!bg-amber-50 cursor-pointer hover:shadow-md transition-shadow" onClick={() => navigate("/tickets?status=past_due")}>
                <div className="flex items-start justify-between">
                  <Statistic
                    title={<span className="text-amber-700">Outstanding</span>}
                    value={Number(data.outstanding.total_unpaid)}
                    prefix="$"
                    precision={0}
                    valueStyle={{ color: "#b45309", fontWeight: 700 }}
                  />
                  <ExclamationCircleOutlined className="text-2xl text-amber-500/40" />
                </div>
                <div className="text-xs text-amber-700/70 mt-1 space-y-0.5">
                  <div>{data.outstanding.ticket_count} unpaid ticket{data.outstanding.ticket_count !== 1 ? "s" : ""}</div>
                  <div className="flex gap-3">
                    <span>{fmtMoney(data.outstanding.contactable_amount)} contactable ({data.outstanding.contactable_count})</span>
                  </div>
                  <div>
                    <span>{fmtMoney(data.outstanding.uncollectable_amount)} no contact ({data.outstanding.uncollectable_count})</span>
                  </div>
                </div>
              </Card>

              {/* Resolution rate */}
              <Card size="small" className="!bg-green-50 cursor-pointer hover:shadow-md transition-shadow" onClick={() => navigate("/tickets")}>
                <div className="flex items-start justify-between">
                  <Statistic
                    title={<span className="text-green-700">Resolution rate</span>}
                    value={data.resolution_rate.rate}
                    suffix="%"
                    valueStyle={{ color: "#15803d", fontWeight: 700 }}
                  />
                  <SafetyCertificateOutlined className="text-2xl text-green-500/30" />
                </div>
                <div className="text-xs text-green-600/70 mt-1">
                  {data.resolution_rate.resolved} of {data.resolution_rate.total} resolved
                </div>
              </Card>
            </div>

            {/* Row 2: Needs Action + Enforcement */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {/* Needs Action — detailed breakdown */}
              <Card size="small" title={<span className="text-red-700 font-semibold">Needs Action</span>}>
                <div className="space-y-3">
                  {data.needs_action.appealed > 0 && (
                    <div className="flex items-center justify-between cursor-pointer hover:bg-gray-50 -mx-3 px-3 py-1.5 rounded transition-colors" onClick={() => navigate("/tickets?status=appealed")}>
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-amber-100 flex items-center justify-center">
                          <WarningOutlined className="text-amber-600" />
                        </div>
                        <div>
                          <div className="font-medium text-sm">Appeals</div>
                          <div className="text-xs text-ink-mute">Pending review</div>
                        </div>
                      </div>
                      <span className="text-lg font-bold text-amber-600">{data.needs_action.appealed}</span>
                    </div>
                  )}

                  {data.needs_action.escalated > 0 && (
                    <div className="flex items-center justify-between cursor-pointer hover:bg-gray-50 -mx-3 px-3 py-1.5 rounded transition-colors" onClick={() => navigate("/tickets?status=escalated")}>
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-purple-100 flex items-center justify-center">
                          <TeamOutlined className="text-purple-600" />
                        </div>
                        <div>
                          <div className="font-medium text-sm">Committee Review</div>
                          <div className="text-xs text-ink-mute">Escalated appeals awaiting vote</div>
                        </div>
                      </div>
                      <span className="text-lg font-bold text-purple-600">{data.needs_action.escalated}</span>
                    </div>
                  )}

                  {data.needs_action.overdue > 0 && (
                    <div className="flex items-center justify-between cursor-pointer hover:bg-gray-50 -mx-3 px-3 py-1.5 rounded transition-colors" onClick={() => navigate("/tickets?status=overdue")}>
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-orange-100 flex items-center justify-center">
                          <ExclamationCircleOutlined className="text-orange-600" />
                        </div>
                        <div>
                          <div className="font-medium text-sm">Overdue</div>
                          <div className="text-xs text-ink-mute">Past payment deadline</div>
                        </div>
                      </div>
                      <span className="text-lg font-bold text-orange-600">{data.needs_action.overdue}</span>
                    </div>
                  )}

                  {data.needs_action.past_due > 0 && (
                    <div className="flex items-center justify-between cursor-pointer hover:bg-gray-50 -mx-3 px-3 py-1.5 rounded transition-colors" onClick={() => navigate("/tickets?status=past_due")}>
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-red-100 flex items-center justify-center">
                          <StopOutlined className="text-red-700" />
                        </div>
                        <div>
                          <div className="font-medium text-sm">Past Due</div>
                          <div className="text-xs text-ink-mute">10+ days unpaid — needs follow-up</div>
                        </div>
                      </div>
                      <span className="text-lg font-bold text-red-700">{data.needs_action.past_due}</span>
                    </div>
                  )}

                  {data.pending_vehicle_requests > 0 && (
                    <div className="flex items-center justify-between cursor-pointer hover:bg-gray-50 -mx-3 px-3 py-1.5 rounded transition-colors" onClick={() => navigate("/permits#vehicle-requests")}>
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center">
                          <CarOutlined className="text-blue-600" />
                        </div>
                        <div>
                          <div className="font-medium text-sm">Vehicle Requests</div>
                          <div className="text-xs text-ink-mute">Pending approval</div>
                        </div>
                      </div>
                      <span className="text-lg font-bold text-blue-600">{data.pending_vehicle_requests}</span>
                    </div>
                  )}

                  {data.needs_action.total === 0 && data.pending_vehicle_requests === 0 && (
                    <div className="text-center py-4 text-sm text-green-600">All clear — nothing needs attention</div>
                  )}
                </div>
              </Card>

              {/* Enforcement snapshot */}
              <Card size="small" title={<span className="font-semibold">Enforcement Snapshot</span>}>
                <div className="space-y-3">
                  <div className="flex items-center justify-between cursor-pointer hover:bg-gray-50 -mx-3 px-3 py-1.5 rounded transition-colors" onClick={() => navigate("/permits")}>
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-green-100 flex items-center justify-center">
                        <SafetyCertificateOutlined className="text-green-600" />
                      </div>
                      <div>
                        <div className="font-medium text-sm">Active Permits</div>
                        <div className="text-xs text-ink-mute">Currently valid</div>
                      </div>
                    </div>
                    <span className="text-lg font-bold text-green-700">{data.enforcement.active_permits}</span>
                  </div>

                  <div className="flex items-center justify-between cursor-pointer hover:bg-gray-50 -mx-3 px-3 py-1.5 rounded transition-colors" onClick={() => navigate("/permits#vehicle-tags")}>
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-cyan-100 flex items-center justify-center">
                        <CarOutlined className="text-cyan-600" />
                      </div>
                      <div>
                        <div className="font-medium text-sm">Vehicle Tags</div>
                        <div className="text-xs text-ink-mute">Known vehicles, no permit</div>
                      </div>
                    </div>
                    <span className="text-lg font-bold text-cyan-700">{data.enforcement.active_tags}</span>
                  </div>

                  {data.enforcement.conduct_cases > 0 && (
                    <div className="flex items-center justify-between cursor-pointer hover:bg-gray-50 -mx-3 px-3 py-1.5 rounded transition-colors" onClick={() => navigate("/conduct")}>
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-red-100 flex items-center justify-center">
                          <WarningOutlined className="text-red-600" />
                        </div>
                        <div>
                          <div className="font-medium text-sm">Conduct Cases</div>
                          <div className="text-xs text-ink-mute">Active referrals</div>
                        </div>
                      </div>
                      <span className="text-lg font-bold text-red-600">{data.enforcement.conduct_cases}</span>
                    </div>
                  )}

                  {data.enforcement.registration_holds > 0 && (
                    <div className="flex items-center justify-between cursor-pointer hover:bg-gray-50 -mx-3 px-3 py-1.5 rounded transition-colors" onClick={() => navigate("/conduct")}>
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-red-100 flex items-center justify-center">
                          <StopOutlined className="text-red-700" />
                        </div>
                        <div>
                          <div className="font-medium text-sm">Registration Holds</div>
                          <div className="text-xs text-ink-mute">Jenzabar holds active</div>
                        </div>
                      </div>
                      <span className="text-lg font-bold text-red-700">{data.enforcement.registration_holds}</span>
                    </div>
                  )}

                  {/* Collection progress bar */}
                  {Number(data.outstanding.total_unpaid) > 0 && (
                    <div className="pt-2 border-t border-gray-100">
                      <div className="flex justify-between text-xs text-ink-mute mb-1">
                        <span>Collection coverage</span>
                        <span>{data.outstanding.contactable_count} of {data.outstanding.ticket_count} contactable</span>
                      </div>
                      <Progress
                        percent={Math.round(data.outstanding.contactable_count / data.outstanding.ticket_count * 100)}
                        strokeColor="#22c55e"
                        trailColor="#fee2e2"
                        showInfo={false}
                        size="small"
                      />
                    </div>
                  )}
                </div>
              </Card>
            </div>

            {/* Row 3: Action Items + Activity */}
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
                      const borderColor =
                        item.status === "past_due" ? "border-red-600" :
                        item.status === "escalated" ? "border-purple-400" :
                        badge.label.includes("overdue") ? "border-red-400" :
                        "border-amber-400";
                      return (
                        <div key={item.id}
                          onClick={() => navigate(`/tickets?search=${item.ticket_number || item.id.slice(0, 8)}`)}
                          className={`px-5 py-3 border-l-4 ${borderColor} flex items-start gap-3 cursor-pointer hover:bg-gray-50 transition-colors`}>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-sm font-medium text-brand-primary">{item.ticket_number || `#${item.id.slice(0, 8)}`}</span>
                              <span className="text-xs text-ink-mute">{item.plate}</span>
                              {item.status === "past_due" && <Tag color="red" className="!text-[10px] !px-1 !py-0 !leading-4">PAST DUE</Tag>}
                              {item.status === "escalated" && <Tag color="purple" className="!text-[10px] !px-1 !py-0 !leading-4">COMMITTEE</Tag>}
                            </div>
                            {item.appeal_note ? (
                              <p className="text-xs text-ink-mute mt-0.5 line-clamp-2">{item.appeal_note}</p>
                            ) : (
                              <p className="text-xs text-ink-mute mt-0.5 italic">
                                {item.status === "escalated" ? "Awaiting committee vote" :
                                 item.status === "past_due" ? "Needs follow-up" :
                                 "Appeal pending"}
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

            {/* Row 4: Trend */}
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
          </>
        )}
      </div>
    </Spin>
  );
}
