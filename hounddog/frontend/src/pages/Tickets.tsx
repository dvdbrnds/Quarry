import React, { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fmtDateTimeCompact, fmtDateTime } from "../dateUtils";
import { Table, Input, Select, Tag, Button, Modal, Descriptions, Space, App, Image, Empty, Popconfirm, Tabs, Card, Statistic, Progress, Spin, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import { authHeaders, isAdminRole, isOfficeRole } from "../auth";
import { useCurrentUser } from "../UserContext";
import EnforcementSettings from "./EnforcementSettings";
import Devices from "./Devices";

interface Ticket {
  id: string;
  ticket_number: string | null;
  plate: string;
  lot: string;
  zone: string | null;
  violation_type: string;
  additional_violations: { code: string; label: string; fine: string }[] | null;
  fine_amount: string;
  photo_url: string | null;
  additional_photo_count: number;
  officer_id: string;
  officer_name: string | null;
  officer_email: string | null;
  owner_name: string | null;
  permit_number: string | null;
  permit_type_label: string | null;
  permit_lot_zone: string | null;
  issued_at: string;
  status: string;
  ticket_category: string;
  location_text: string | null;
  location_lat: number | null;
  location_lng: number | null;
  vehicle_description: string | null;
  driver_name: string | null;
  driver_license: string | null;
  officer_notes: string | null;
  appeal_note: string | null;
  appeal_decision: string | null;
  appeal_decided_by: string | null;
  appeal_decision_reason: string | null;
  void_reason: string | null;
  committee_status: string | null;
  committee_decision: string | null;
  committee_decided_at: string | null;
  committee_notes: string | null;
  escalated_by: string | null;
  escalated_at: string | null;
  dispute_name: string | null;
  dispute_email: string | null;
  dispute_phone: string | null;
  ocr_original_plate: string | null;
  created_at: string;
  updated_at: string;
  mailed_at: string | null;
  mailed_address: string | null;
}

const STATUS_COLORS: Record<string, string> = {
  issued: "red",
  warning: "orange",
  overdue: "volcano",
  pending_payment: "orange",
  paid: "green",
  appealed: "gold",
  escalated: "purple",
  voided: "default",
};

const STATUS_BAR_COLORS: Record<string, string> = {
  issued: "#ef4444", warning: "#f97316", paid: "#22c55e",
  voided: "#9ca3af", appealed: "#eab308", escalated: "#a855f7",
  overdue: "#dc2626", pending_payment: "#f97316",
};

interface FullStatsData {
  this_week: number;
  this_month: number;
  all_time: number;
  global_share: number;
  total_all: number;
  by_violation: { violation_type: string; label: string; count: number }[];
  by_status: { status: string; count: number }[];
  daily_activity: { date: string; count: number }[];
  by_lot: { lot: string; count: number }[];
  by_hour: { hour: number; count: number }[];
  appeal_void_rate: { voided: number; appealed: number; void_rate: number; appeal_rate: number };
  revenue: { total_fines: number; paid_fines: number };
}

function HBarChart({ items, colorFn, maxItems, scrollHeight }: {
  items: { label: string; value: number; tag?: boolean }[];
  colorFn?: (label: string) => string;
  maxItems?: number;
  scrollHeight?: number;
}) {
  const max = Math.max(...items.map(i => i.value), 1);
  const visible = maxItems ? items.slice(0, maxItems) : items;
  const hasMore = maxItems && items.length > maxItems;
  const [expanded, setExpanded] = useState(false);
  const display = expanded ? items : visible;

  const content = (
    <div className="space-y-2">
      {display.map(item => (
        <div key={item.label}>
          <div className="flex justify-between text-xs mb-0.5">
            {item.tag ? <Tag color={STATUS_COLORS[item.label] || "default"} className="mr-0">{item.label}</Tag>
              : <span className="text-gray-600 truncate mr-2">{item.label}</span>}
            <span className="font-semibold text-gray-800 shrink-0">{item.value}</span>
          </div>
          <div className="h-4 bg-gray-100 rounded overflow-hidden">
            <div className="h-full rounded transition-all" style={{
              width: `${(item.value / max) * 100}%`,
              backgroundColor: colorFn ? colorFn(item.label) : "#3b82f6",
            }} />
          </div>
        </div>
      ))}
      {hasMore && (
        <button
          className="text-xs text-blue-500 hover:text-blue-700 mt-1"
          onClick={() => setExpanded(e => !e)}
        >
          {expanded ? "Show less" : `Show all ${items.length}`}
        </button>
      )}
    </div>
  );

  if (scrollHeight && (expanded || !maxItems)) {
    return <div style={{ maxHeight: scrollHeight, overflowY: "auto" }}>{content}</div>;
  }
  return content;
}

function fmtShortDate(iso: string) {
  const d = new Date(iso + "T00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function fmtWeekday(iso: string) {
  const d = new Date(iso + "T00:00");
  return d.toLocaleDateString("en-US", { weekday: "short" });
}

function DailyTimeline({ data, height = 140, color = "#3b82f6" }: { data: { date: string; count: number }[]; height?: number; color?: string }) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const max = Math.max(...data.map(d => d.count), 1);
  const total = data.reduce((s, d) => s + d.count, 0);
  const points = data.map((d, i) => {
    const x = (i / (data.length - 1)) * 100;
    const y = 100 - (d.count / max) * 100;
    return { x, y, ...d };
  });
  const polyline = points.map(p => `${p.x},${p.y}`).join(" ");
  const areaPath = `M ${points[0].x},100 ` + points.map(p => `L ${p.x},${p.y}`).join(" ") + ` L ${points[points.length - 1].x},100 Z`;

  const labelInterval = data.length <= 14 ? 2 : data.length <= 21 ? 3 : 5;

  return (
    <div style={{ height: height + 28 }} className="relative">
      <div style={{ height }} className="relative"
        onMouseLeave={() => setHoverIdx(null)}
      >
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full">
          <path d={areaPath} fill={color} opacity="0.15" />
          <polyline points={polyline} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
          {points.map((p, i) => (
            <circle key={i} cx={p.x} cy={p.y} r={hoverIdx === i ? "2.5" : "1.2"} fill={color} vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
        {/* Invisible hover zones */}
        <div className="absolute inset-0 flex">
          {points.map((p, i) => (
            <div key={i} className="flex-1 h-full" onMouseEnter={() => setHoverIdx(i)} />
          ))}
        </div>
        {/* Hover tooltip */}
        {hoverIdx !== null && points[hoverIdx] && (
          <div
            className="absolute z-10 bg-gray-800 text-white text-xs rounded px-2 py-1.5 pointer-events-none whitespace-nowrap shadow-lg"
            style={{ left: `${points[hoverIdx].x}%`, bottom: `${100 - points[hoverIdx].y + 8}%`, transform: "translateX(-50%)" }}
          >
            <div className="font-semibold">{fmtWeekday(points[hoverIdx].date)}, {fmtShortDate(points[hoverIdx].date)}</div>
            <div>{points[hoverIdx].count} citation{points[hoverIdx].count !== 1 ? "s" : ""}</div>
          </div>
        )}
      </div>
      {/* Date labels along bottom */}
      <div className="relative h-5 mt-1">
        {data.map((d, i) => (
          i % labelInterval === 0 || i === data.length - 1 ? (
            <span
              key={i}
              className="absolute text-[9px] text-gray-400 -translate-x-1/2"
              style={{ left: `${(i / (data.length - 1)) * 100}%` }}
            >
              {fmtShortDate(d.date)}
            </span>
          ) : null
        ))}
      </div>
      <div className="text-[10px] text-gray-400 text-right mt-0.5">{total} total over 30 days</div>
    </div>
  );
}

function fmtHour(h: number) {
  if (h === 0) return "12a";
  if (h < 12) return `${h}a`;
  if (h === 12) return "12p";
  return `${h - 12}p`;
}

function HourChart({ data, color = "#3b82f6", height = 220 }: { data: { hour: number; count: number }[]; color?: string; height?: number }) {
  const max = Math.max(...data.map(d => d.count), 1);
  return (
    <div>
      <div className="flex items-end gap-1" style={{ height }}>
        {data.map(d => {
          const pct = (d.count / max) * 100;
          return (
            <Tooltip key={d.hour} title={`${fmtHour(d.hour)} (${d.hour}:00) — ${d.count} citation${d.count !== 1 ? "s" : ""}`}>
              <div className="flex-1 flex flex-col items-center justify-end h-full min-w-0">
                {d.count > 0 && <span className="text-[9px] font-semibold text-gray-600 mb-0.5">{d.count}</span>}
                <div
                  className="w-full rounded-t transition-all"
                  style={{ height: `${pct}%`, minHeight: d.count > 0 ? 4 : 0, backgroundColor: color }}
                />
              </div>
            </Tooltip>
          );
        })}
      </div>
      <div className="flex gap-1 mt-1">
        {data.map(d => (
          <div key={d.hour} className="flex-1 text-center text-[8px] text-gray-500 leading-tight min-w-0">
            {fmtHour(d.hour)}
          </div>
        ))}
      </div>
    </div>
  );
}

function OfficerStats() {
  const [stats, setStats] = useState<FullStatsData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/tickets/my-stats", { headers: await authHeaders() });
        if (res.ok) setStats(await res.json());
      } catch { /* ignore */ }
      finally { setLoading(false); }
    })();
  }, []);

  if (loading) return <div className="text-center py-8"><Spin /></div>;
  if (!stats) return null;

  const qualityScore = Math.round((1 - stats.appeal_void_rate.void_rate / 100) * 100);
  const qualityColor = qualityScore >= 85 ? "#22c55e" : qualityScore >= 70 ? "#eab308" : "#ef4444";

  return (
    <div className="mb-6 space-y-4">
      {/* Row 1 — stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Card size="small" className="shadow-sm"><Statistic title="This Week" value={stats.this_week} /></Card>
        <Card size="small" className="shadow-sm"><Statistic title="This Month" value={stats.this_month} /></Card>
        <Card size="small" className="shadow-sm"><Statistic title="All Time" value={stats.all_time} /></Card>
        <Card size="small" className="shadow-sm">
          <div className="flex items-center gap-3">
            <Progress type="circle" percent={stats.global_share} size={48} format={p => `${p}%`} />
            <div>
              <div className="text-xs text-gray-500">Share</div>
              <Tooltip title={`${stats.all_time} of ${stats.total_all} total`}>
                <div className="text-xs font-semibold cursor-help">{stats.all_time}/{stats.total_all}</div>
              </Tooltip>
            </div>
          </div>
        </Card>
        <Card size="small" className="shadow-sm">
          <Statistic title="Revenue" value={stats.revenue.total_fines} prefix="$" precision={0} />
          <div className="text-[10px] text-gray-400 mt-0.5">${stats.revenue.paid_fines.toFixed(0)} collected</div>
        </Card>
        <Card size="small" className="shadow-sm">
          <div className="flex items-center gap-3">
            <Progress type="circle" percent={qualityScore} size={48} strokeColor={qualityColor} format={p => `${p}%`} />
            <div>
              <div className="text-xs text-gray-500">Quality</div>
              <Tooltip title={`${stats.appeal_void_rate.voided} voided, ${stats.appeal_void_rate.appealed} appealed`}>
                <div className="text-[10px] text-gray-400 cursor-help">{stats.appeal_void_rate.void_rate}% void</div>
              </Tooltip>
            </div>
          </div>
        </Card>
      </div>

      {/* Row 2 — 30-day timeline */}
      <Card size="small" title="30-Day Activity" className="shadow-sm">
        {stats.daily_activity.length > 0 ? <DailyTimeline data={stats.daily_activity} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" />}
      </Card>

      {/* Row 3 — three columns */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card size="small" title="By Violation" className="shadow-sm">
          {stats.by_violation.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" className="py-4" />
            : <HBarChart items={stats.by_violation.map(v => ({ label: v.label, value: v.count }))} />}
        </Card>
        <Card size="small" title={`By Lot (${stats.by_lot.length})`} className="shadow-sm">
          {stats.by_lot.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" className="py-4" />
            : <HBarChart items={stats.by_lot.map(l => ({ label: l.lot, value: l.count }))} colorFn={() => "#8b5cf6"} maxItems={10} scrollHeight={400} />}
        </Card>
        <Card size="small" title="By Hour of Day" className="shadow-sm">
          <HourChart data={stats.by_hour} />
        </Card>
      </div>

      {/* Row 4 — status */}
      <Card size="small" title="By Status" className="shadow-sm" style={{ maxWidth: 500 }}>
        {stats.by_status.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" className="py-4" />
          : <HBarChart items={stats.by_status.map(s => ({ label: s.status, value: s.count, tag: true }))} colorFn={l => STATUS_BAR_COLORS[l] || "#6b7280"} />}
      </Card>
    </div>
  );
}

interface OfficerRow extends FullStatsData {
  officer_email: string;
  officer_name: string | null;
  global_share: number;
}

interface ViolationDetail {
  violation_type: string;
  label: string;
  count: number;
  officers: { officer_email: string; officer_name: string; count: number }[];
}

interface ReportData {
  total_all: number;
  team_this_week: number;
  team_this_month: number;
  team_revenue: { total_fines: number; paid_fines: number };
  avg_void_rate: number;
  daily_total: { date: string; count: number }[];
  by_lot_total: { lot: string; count: number }[];
  by_hour_total: { hour: number; count: number }[];
  by_violation_total: ViolationDetail[];
  officers: OfficerRow[];
}

function CompareGroupedBars({ label, compared, accessor, colors, displayName }: {
  label: string;
  compared: OfficerRow[];
  accessor: (o: OfficerRow) => { key: string; label?: string; count: number }[];
  colors: string[];
  displayName: (o: OfficerRow) => string;
}) {
  const allKeys = new Map<string, string>();
  compared.forEach(o => accessor(o).forEach(v => allKeys.set(v.key, v.label || v.key)));
  const maxV = Math.max(...compared.flatMap(o => accessor(o).map(v => v.count)), 1);
  return (
    <div className="mb-4">
      <h4 className="text-sm font-semibold text-gray-700 mb-3">{label}</h4>
      {Array.from(allKeys.entries()).map(([key, lbl]) => (
        <div key={key} className="mb-3">
          <div className="text-xs text-gray-600 mb-1">{lbl}</div>
          {compared.map((o, i) => {
            const found = accessor(o).find(v => v.key === key);
            const cnt = found?.count || 0;
            return (
              <div key={o.officer_email} className="flex items-center gap-2 mb-0.5">
                <div className="w-20 text-[10px] text-right truncate" style={{ color: colors[i % colors.length] }}>{displayName(o)}</div>
                <div className="flex-1 h-4 bg-gray-100 rounded overflow-hidden">
                  <div className="h-full rounded transition-all" style={{ width: `${(cnt / maxV) * 100}%`, backgroundColor: colors[i % colors.length] }} />
                </div>
                <div className="w-8 text-xs font-semibold text-right">{cnt}</div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function OfficerReport() {
  const [data, setData] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [compareKeys, setCompareKeys] = useState<string[]>([]);
  const [selectedOfficer, setSelectedOfficer] = useState<OfficerRow | null>(null);
  const [selectedViolation, setSelectedViolation] = useState<ViolationDetail | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/tickets/officer-report", { headers: await authHeaders() });
        if (res.ok) setData(await res.json());
      } catch { /* ignore */ }
      finally { setLoading(false); }
    })();
  }, []);

  if (loading) return <div className="text-center py-12"><Spin size="large" /><p className="mt-3 text-gray-500">Loading officer data...</p></div>;
  if (!data || data.officers.length === 0) return <Empty description="No officer data available" className="py-12" />;

  const officers = data.officers;
  const maxAllTime = Math.max(...officers.map(o => o.all_time), 1);
  const compared = officers.filter(o => compareKeys.includes(o.officer_email));

  const toggleCompare = (email: string) => {
    setCompareKeys(prev => prev.includes(email) ? prev.filter(e => e !== email) : [...prev, email]);
  };

  const displayName = (o: OfficerRow) => o.officer_name || o.officer_email.split("@")[0];
  const COMPARE_COLORS = ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold mb-1">Officer Performance Report</h2>
        <p className="text-sm text-gray-500">{officers.length} officer{officers.length !== 1 ? "s" : ""} &middot; {data.total_all} total citations</p>
      </div>

      {/* Section 1 — Team overview cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <Card size="small" className="shadow-sm"><Statistic title="Total Citations" value={data.total_all} /></Card>
        <Card size="small" className="shadow-sm"><Statistic title="This Week" value={data.team_this_week} /></Card>
        <Card size="small" className="shadow-sm"><Statistic title="This Month" value={data.team_this_month} /></Card>
        <Card size="small" className="shadow-sm">
          <Statistic title="Total Revenue" value={data.team_revenue.total_fines} prefix="$" precision={0} />
          <div className="text-[10px] text-gray-400 mt-0.5">${data.team_revenue.paid_fines.toFixed(0)} collected</div>
        </Card>
        <Card size="small" className="shadow-sm">
          <div className="flex items-center gap-3">
            <Progress type="circle" percent={Math.round(100 - data.avg_void_rate)} size={48}
              strokeColor={data.avg_void_rate <= 15 ? "#22c55e" : data.avg_void_rate <= 30 ? "#eab308" : "#ef4444"}
              format={p => `${p}%`} />
            <div>
              <div className="text-xs text-gray-500">Team Quality</div>
              <div className="text-[10px] text-gray-400">{data.avg_void_rate}% void rate</div>
            </div>
          </div>
        </Card>
      </div>

      {/* Section 2 — 30-day team timeline */}
      <Card size="small" title="30-Day Team Activity" className="shadow-sm">
        <DailyTimeline data={data.daily_total} height={140} />
      </Card>

      {/* Section 3 & 4 — Lot Coverage and Peak Hours */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card size="small" title={`Citations by Lot (${data.by_lot_total.length})`} className="shadow-sm">
          {data.by_lot_total.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" />
            : <HBarChart items={data.by_lot_total.map(l => ({ label: l.lot, value: l.count }))} colorFn={() => "#8b5cf6"} maxItems={10} scrollHeight={400} />}
        </Card>
        <Card size="small" title="Peak Enforcement Hours" className="shadow-sm">
          <HourChart data={data.by_hour_total} color="#f59e0b" />
        </Card>
      </div>

      {/* Section 5 — Citations by Type */}
      <Card size="small" title={`Citations by Type (${data.by_violation_total.length})`} className="shadow-sm">
        {data.by_violation_total.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" /> : (
          <div className="space-y-2">
            {data.by_violation_total.slice(0, 15).map(v => {
              const maxV = data.by_violation_total[0]?.count || 1;
              return (
                <div key={v.violation_type} className="cursor-pointer hover:bg-gray-50 rounded px-1 py-0.5 -mx-1 transition-colors" onClick={() => setSelectedViolation(v)}>
                  <div className="flex justify-between text-xs mb-0.5">
                    <span className="text-gray-600 truncate mr-2">{v.label}</span>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-[10px] text-gray-400">{v.officers.length} officer{v.officers.length !== 1 ? "s" : ""}</span>
                      <span className="font-semibold text-gray-800">{v.count}</span>
                    </div>
                  </div>
                  <div className="h-4 bg-gray-100 rounded overflow-hidden">
                    <div className="h-full bg-blue-500 rounded transition-all" style={{ width: `${(v.count / maxV) * 100}%` }} />
                  </div>
                </div>
              );
            })}
            {data.by_violation_total.length > 15 && (
              <div className="text-xs text-gray-400 text-center pt-1">+ {data.by_violation_total.length - 15} more types</div>
            )}
          </div>
        )}
      </Card>

      {/* Violation type detail modal */}
      <Modal
        open={!!selectedViolation}
        onCancel={() => setSelectedViolation(null)}
        footer={null}
        title={null}
        width={700}
      >
        {selectedViolation && (() => {
          const v = selectedViolation;
          const maxO = v.officers[0]?.count || 1;
          const pctOfTotal = data.total_all ? ((v.count / data.total_all) * 100).toFixed(1) : "0";
          return (
            <div className="space-y-5">
              <div>
                <h2 className="text-xl font-bold text-gray-800">{v.label}</h2>
                <p className="text-sm text-gray-500">{v.count} total citations &middot; {pctOfTotal}% of all citations &middot; {v.officers.length} officer{v.officers.length !== 1 ? "s" : ""}</p>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <Card size="small" className="shadow-sm"><Statistic title="Total" value={v.count} /></Card>
                <Card size="small" className="shadow-sm"><Statistic title="% of All" value={pctOfTotal} suffix="%" /></Card>
                <Card size="small" className="shadow-sm"><Statistic title="Officers" value={v.officers.length} /></Card>
              </div>

              <Card size="small" title="By Officer" className="shadow-sm">
                <div className="space-y-2">
                  {v.officers.map((o, i) => (
                    <div key={o.officer_email}>
                      <div className="flex justify-between text-xs mb-0.5">
                        <span className="text-gray-700">
                          <span className="font-semibold text-gray-400 mr-1.5">#{i + 1}</span>
                          {o.officer_name}
                        </span>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className="text-[10px] text-gray-400">{v.count ? ((o.count / v.count) * 100).toFixed(0) : 0}%</span>
                          <span className="font-semibold text-gray-800">{o.count}</span>
                        </div>
                      </div>
                      <div className="h-4 bg-gray-100 rounded overflow-hidden">
                        <div className="h-full bg-blue-500 rounded transition-all" style={{ width: `${(o.count / maxO) * 100}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          );
        })()}
      </Modal>

      {/* Section 6 — Leaderboard */}
      <Card size="small" title="Officer Leaderboard" className="shadow-sm">
        <div className="space-y-3">
          {officers.map((o, i) => {
            const qs = Math.round((1 - (o.appeal_void_rate?.void_rate || 0) / 100) * 100);
            const qColor = qs >= 85 ? "#22c55e" : qs >= 70 ? "#eab308" : "#ef4444";
            return (
              <div key={o.officer_email} className="flex items-center gap-3 hover:bg-gray-50 rounded-lg px-2 py-1 -mx-2 cursor-pointer transition-colors" onClick={() => setSelectedOfficer(o)}>
                <div className="w-6 text-right text-sm font-bold text-gray-400">#{i + 1}</div>
                <Tooltip title={compareKeys.includes(o.officer_email) ? "Remove from comparison" : "Add to comparison"}>
                  <Button
                    size="small"
                    type={compareKeys.includes(o.officer_email) ? "primary" : "default"}
                    onClick={(e) => { e.stopPropagation(); toggleCompare(o.officer_email); }}
                    className="shrink-0"
                    style={compareKeys.includes(o.officer_email) ? { background: COMPARE_COLORS[compareKeys.indexOf(o.officer_email) % COMPARE_COLORS.length] } : {}}
                  >
                    {compareKeys.includes(o.officer_email) ? "✓" : "Compare"}
                  </Button>
                </Tooltip>
                <div className="w-32 shrink-0">
                  <div className="font-semibold text-sm truncate">{displayName(o)}</div>
                  <div className="text-[10px] text-gray-400 truncate">{o.officer_email}</div>
                </div>
                <div className="flex-1">
                  <div className="h-6 bg-gray-100 rounded overflow-hidden relative">
                    <div className="h-full bg-blue-500 rounded transition-all" style={{ width: `${(o.all_time / maxAllTime) * 100}%` }} />
                    <span className="absolute inset-0 flex items-center px-2 text-xs font-semibold" style={{ color: o.all_time > maxAllTime * 0.3 ? "#fff" : "#333" }}>
                      {o.all_time}
                    </span>
                  </div>
                </div>
                <div className="text-right shrink-0 w-20">
                  <div className="text-xs text-gray-500">Wk: <span className="font-semibold text-gray-800">{o.this_week}</span></div>
                  <div className="text-xs text-gray-500">Mo: <span className="font-semibold text-gray-800">{o.this_month}</span></div>
                </div>
                <Tooltip title={`$${(o.revenue?.total_fines || 0).toFixed(0)} total / $${(o.revenue?.paid_fines || 0).toFixed(0)} collected`}>
                  <div className="shrink-0 w-16 text-right text-xs font-semibold text-green-700">${(o.revenue?.total_fines || 0).toFixed(0)}</div>
                </Tooltip>
                <Tooltip title={`Quality: ${qs}% (${o.appeal_void_rate?.void_rate || 0}% voided)`}>
                  <div className="shrink-0"><Progress type="circle" percent={qs} size={32} strokeColor={qColor} format={p => `${p}`} /></div>
                </Tooltip>
                <div className="shrink-0 w-12">
                  <Progress type="circle" percent={o.global_share} size={32} format={p => `${p}%`} />
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {/* Section 6 — Side-by-side comparison */}
      {compared.length >= 2 && (
        <Card
          size="small"
          title={`Side-by-Side: ${compared.map(displayName).join(" vs ")}`}
          extra={<Button size="small" onClick={() => setCompareKeys([])}>Clear</Button>}
          className="shadow-sm"
        >
          {/* Summary table */}
          <div className="overflow-x-auto mb-6">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 pr-4 text-gray-500 font-medium">Metric</th>
                  {compared.map((o, i) => (
                    <th key={o.officer_email} className="text-right py-2 px-3 font-semibold" style={{ color: COMPARE_COLORS[i % COMPARE_COLORS.length] }}>
                      {displayName(o)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    { key: "this_week", label: "This Week", get: (o: OfficerRow) => o.this_week, fmt: (v: number) => String(v) },
                    { key: "this_month", label: "This Month", get: (o: OfficerRow) => o.this_month, fmt: (v: number) => String(v) },
                    { key: "all_time", label: "All Time", get: (o: OfficerRow) => o.all_time, fmt: (v: number) => String(v) },
                    { key: "global_share", label: "Global Share", get: (o: OfficerRow) => o.global_share, fmt: (v: number) => `${v}%` },
                    { key: "revenue", label: "Revenue", get: (o: OfficerRow) => o.revenue?.total_fines || 0, fmt: (v: number) => `$${v.toFixed(0)}` },
                    { key: "paid", label: "Collected", get: (o: OfficerRow) => o.revenue?.paid_fines || 0, fmt: (v: number) => `$${v.toFixed(0)}` },
                    { key: "quality", label: "Quality Score", get: (o: OfficerRow) => Math.round((1 - (o.appeal_void_rate?.void_rate || 0) / 100) * 100), fmt: (v: number) => `${v}%` },
                    { key: "void_rate", label: "Void Rate", get: (o: OfficerRow) => o.appeal_void_rate?.void_rate || 0, fmt: (v: number) => `${v}%` },
                  ] as const
                ).map(metric => {
                  const vals = compared.map(o => metric.get(o));
                  const maxVal = Math.max(...vals);
                  return (
                    <tr key={metric.key} className="border-b border-gray-50">
                      <td className="py-2 pr-4 text-gray-600">{metric.label}</td>
                      {compared.map((o, i) => {
                        const val = metric.get(o);
                        const isMax = val === maxVal && vals.filter(v => v === val).length === 1;
                        return (
                          <td key={o.officer_email} className={`text-right py-2 px-3 ${isMax ? "font-bold" : ""}`}
                            style={isMax ? { color: COMPARE_COLORS[i % COMPARE_COLORS.length] } : {}}>
                            {metric.fmt(val)}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* 30-day timeline overlay */}
          <div className="mb-6">
            <h4 className="text-sm font-semibold text-gray-700 mb-2">30-Day Activity</h4>
            <div style={{ height: 120 }} className="relative">
              <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full">
                {compared.map((o, ci) => {
                  const maxD = Math.max(...o.daily_activity.map(d => d.count), 1);
                  const pts = o.daily_activity.map((d, i) => ({
                    x: (i / (o.daily_activity.length - 1)) * 100,
                    y: 100 - (d.count / maxD) * 100,
                  }));
                  const polyline = pts.map(p => `${p.x},${p.y}`).join(" ");
                  return <polyline key={o.officer_email} points={polyline} fill="none" stroke={COMPARE_COLORS[ci % COMPARE_COLORS.length]} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />;
                })}
              </svg>
              <div className="flex gap-3 mt-1">
                {compared.map((o, i) => (
                  <span key={o.officer_email} className="text-[10px] flex items-center gap-1">
                    <span className="w-3 h-0.5 inline-block rounded" style={{ backgroundColor: COMPARE_COLORS[i % COMPARE_COLORS.length] }} />
                    {displayName(o)}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* Violation comparison */}
          <CompareGroupedBars
            label="Violations by Type"
            compared={compared}
            accessor={o => o.by_violation.map(v => ({ key: v.violation_type, label: v.label, count: v.count }))}
            colors={COMPARE_COLORS}
            displayName={displayName}
          />

          {/* Lot comparison */}
          <CompareGroupedBars
            label="By Lot"
            compared={compared}
            accessor={o => o.by_lot.map(l => ({ key: l.lot, label: l.lot, count: l.count }))}
            colors={COMPARE_COLORS}
            displayName={displayName}
          />

          {/* Hour comparison */}
          <div className="mb-4">
            <h4 className="text-sm font-semibold text-gray-700 mb-2">By Hour of Day</h4>
            <div className="flex items-end gap-px h-24">
              {Array.from({ length: 24 }, (_, h) => {
                const maxH = Math.max(...compared.flatMap(o => o.by_hour.map(b => b.count)), 1);
                return (
                  <Tooltip key={h} title={`${h}:00 — ${compared.map(o => `${displayName(o)}: ${o.by_hour[h]?.count || 0}`).join(", ")}`}>
                    <div className="flex-1 flex flex-col items-center justify-end h-full gap-px">
                      {compared.map((o, ci) => {
                        const cnt = o.by_hour[h]?.count || 0;
                        return <div key={o.officer_email} className="w-full rounded-sm" style={{ height: `${(cnt / maxH) * 100}%`, minHeight: cnt > 0 ? 1 : 0, backgroundColor: COMPARE_COLORS[ci % COMPARE_COLORS.length] }} />;
                      })}
                      {h % 4 === 0 && <span className="text-[7px] text-gray-400">{h}</span>}
                    </div>
                  </Tooltip>
                );
              })}
            </div>
          </div>

          {/* Status comparison */}
          <CompareGroupedBars
            label="By Status"
            compared={compared}
            accessor={o => o.by_status.map(s => ({ key: s.status, count: s.count }))}
            colors={COMPARE_COLORS}
            displayName={displayName}
          />
        </Card>
      )}

      {compared.length === 1 && (
        <Card size="small" className="shadow-sm bg-blue-50 border-blue-200">
          <p className="text-sm text-blue-700">Select at least one more officer to see a side-by-side comparison.</p>
        </Card>
      )}

      {/* Officer detail drilldown */}
      <Modal
        open={!!selectedOfficer}
        onCancel={() => setSelectedOfficer(null)}
        footer={null}
        title={null}
        width={900}
        styles={{ body: { maxHeight: "80vh", overflow: "auto" } }}
      >
        {selectedOfficer && <OfficerDetail officer={selectedOfficer} totalAll={data.total_all} />}
      </Modal>
    </div>
  );
}

function OfficerDetail({ officer: o, totalAll }: { officer: OfficerRow; totalAll: number }) {
  const qualityScore = Math.round((1 - (o.appeal_void_rate?.void_rate || 0) / 100) * 100);
  const qualityColor = qualityScore >= 85 ? "#22c55e" : qualityScore >= 70 ? "#eab308" : "#ef4444";
  const name = o.officer_name || o.officer_email.split("@")[0];

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold text-gray-800">{name}</h2>
        <p className="text-sm text-gray-500">{o.officer_email}</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Card size="small" className="shadow-sm"><Statistic title="This Week" value={o.this_week} /></Card>
        <Card size="small" className="shadow-sm"><Statistic title="This Month" value={o.this_month} /></Card>
        <Card size="small" className="shadow-sm"><Statistic title="All Time" value={o.all_time} /></Card>
        <Card size="small" className="shadow-sm">
          <div className="flex items-center gap-2">
            <Progress type="circle" percent={o.global_share} size={44} format={p => `${p}%`} />
            <div>
              <div className="text-xs text-gray-500">Share</div>
              <div className="text-[10px] text-gray-400">{o.all_time}/{totalAll}</div>
            </div>
          </div>
        </Card>
        <Card size="small" className="shadow-sm">
          <Statistic title="Revenue" value={o.revenue?.total_fines || 0} prefix="$" precision={0} />
          <div className="text-[10px] text-gray-400 mt-0.5">${(o.revenue?.paid_fines || 0).toFixed(0)} collected</div>
        </Card>
        <Card size="small" className="shadow-sm">
          <div className="flex items-center gap-2">
            <Progress type="circle" percent={qualityScore} size={44} strokeColor={qualityColor} format={p => `${p}%`} />
            <div>
              <div className="text-xs text-gray-500">Quality</div>
              <div className="text-[10px] text-gray-400">{o.appeal_void_rate?.void_rate || 0}% void</div>
            </div>
          </div>
        </Card>
      </div>

      {/* 30-day timeline */}
      <Card size="small" title="30-Day Activity" className="shadow-sm">
        {o.daily_activity?.length ? <DailyTimeline data={o.daily_activity} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" />}
      </Card>

      {/* Three columns: violation, lot, hour */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card size="small" title="By Violation" className="shadow-sm">
          {o.by_violation?.length ? <HBarChart items={o.by_violation.map(v => ({ label: v.label, value: v.count }))} />
            : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" className="py-4" />}
        </Card>
        <Card size="small" title={`By Lot (${o.by_lot?.length || 0})`} className="shadow-sm">
          {o.by_lot?.length ? <HBarChart items={o.by_lot.map(l => ({ label: l.lot, value: l.count }))} colorFn={() => "#8b5cf6"} maxItems={10} scrollHeight={400} />
            : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" className="py-4" />}
        </Card>
        <Card size="small" title="By Hour of Day" className="shadow-sm">
          {o.by_hour?.length ? <HourChart data={o.by_hour} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" className="py-4" />}
        </Card>
      </div>

      {/* Status + appeal/void breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card size="small" title="By Status" className="shadow-sm">
          {o.by_status?.length ? <HBarChart items={o.by_status.map(s => ({ label: s.status, value: s.count, tag: true }))} colorFn={l => STATUS_BAR_COLORS[l] || "#6b7280"} />
            : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No data" className="py-4" />}
        </Card>
        <Card size="small" title="Quality Breakdown" className="shadow-sm">
          <div className="space-y-4 py-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">Total Citations</span>
              <span className="text-lg font-bold">{o.all_time}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">Voided</span>
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-gray-500">{o.appeal_void_rate?.voided || 0}</span>
                <Tag color="default">{o.appeal_void_rate?.void_rate || 0}%</Tag>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">Appealed</span>
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-yellow-600">{o.appeal_void_rate?.appealed || 0}</span>
                <Tag color="gold">{o.appeal_void_rate?.appeal_rate || 0}%</Tag>
              </div>
            </div>
            <div className="pt-2 border-t">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-700">Quality Score</span>
                <Progress type="circle" percent={qualityScore} size={52} strokeColor={qualityColor} format={p => `${p}%`} />
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function TicketsList({ officerEmail }: { officerEmail?: string } = {}) {
  const { modal, message } = App.useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const user = useCurrentUser();
  const isAdmin = isAdminRole(user?.role);
  const isOffice = isOfficeRole(user?.role);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState(searchParams.get("search") ?? "");
  const [statusFilter, setStatusFilter] = useState(searchParams.get("status") ?? "");
  const [categoryFilter, setCategoryFilter] = useState(searchParams.get("category") ?? "");
  const [selected, setSelected] = useState<Ticket | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [bulkVoiding, setBulkVoiding] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (statusFilter) params.set("status", statusFilter);
    if (categoryFilter) params.set("category", categoryFilter);
    setSearchParams(params, { replace: true });
  }, [search, statusFilter, categoryFilter, setSearchParams]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      qs.set("page", String(page));
      if (search) qs.set("search", search);
      if (statusFilter) qs.set("status", statusFilter);
      if (categoryFilter) qs.set("category", categoryFilter);
      if (officerEmail) qs.set("officer_email", officerEmail);
      const res = await fetch(`/api/tickets?${qs}`, { headers: await authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setTickets(data.items);
        setTotal(data.total);
      }
    } catch {
      message.error("Failed to load tickets");
    } finally {
      setLoading(false);
    }
  }, [page, search, statusFilter, categoryFilter, officerEmail, message]);

  useEffect(() => { load(); }, [load]);

  function handlePrintTicket(ticket: Ticket) {
    const photoUrl = ticket.photo_url ? `${window.location.origin}${ticket.photo_url}` : null;
    const gpsLink = ticket.location_lat && ticket.location_lng
      ? `https://maps.google.com/?q=${ticket.location_lat},${ticket.location_lng}`
      : null;

    const printWindow = window.open("", "_blank", "width=800,height=900");
    if (!printWindow) return;

    printWindow.document.write(`<!DOCTYPE html>
<html>
<head>
  <title>${ticket.ticket_number || "Ticket"} — Case Report</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 40px; color: #1a1a1a; }
    .header { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #1e3a5f; padding-bottom: 16px; margin-bottom: 24px; }
    .header h1 { font-size: 22px; color: #1e3a5f; }
    .header .meta { text-align: right; font-size: 12px; color: #555; }
    .section { margin-bottom: 20px; }
    .section-title { font-size: 13px; font-weight: 600; text-transform: uppercase; color: #1e3a5f; margin-bottom: 8px; letter-spacing: 0.5px; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    td { padding: 8px 12px; border: 1px solid #ddd; }
    td.label { font-weight: 600; background: #f5f7fa; width: 140px; }
    .photo { max-width: 100%; max-height: 300px; border-radius: 6px; border: 1px solid #ddd; margin-top: 8px; }
    .status { display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 600; text-transform: uppercase; }
    .status-issued { background: #fee2e2; color: #991b1b; }
    .status-warning { background: #fff7ed; color: #9a3412; }
    .status-paid { background: #dcfce7; color: #166534; }
    .status-voided { background: #f3f4f6; color: #6b7280; }
    .status-appealed { background: #fef9c3; color: #854d0e; }
    .status-escalated { background: #f3e8ff; color: #6b21a8; }
    .footer { margin-top: 32px; padding-top: 16px; border-top: 1px solid #ddd; font-size: 11px; color: #777; text-align: center; }
    @media print { body { padding: 20px; } }
  </style>
</head>
<body>
  <div class="header">
    <div>
      <h1>Parking Citation Case Report</h1>
      <div style="font-size:14px; margin-top:4px; color:#333;">${ticket.ticket_number || ""}</div>
    </div>
    <div class="meta">
      <div>Printed: ${fmtDateTime(new Date())}</div>
      <div>Moravian University Parking Services</div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Citation Details</div>
    <table>
      <tr><td class="label">Ticket #</td><td>${ticket.ticket_number || "—"}</td><td class="label">Status</td><td><span class="status status-${ticket.status}">${ticket.status}</span></td></tr>
      <tr><td class="label">Plate</td><td style="font-family:monospace;font-size:15px;font-weight:600;">${ticket.plate}${ticket.ocr_original_plate ? ` <span style="font-size:11px;color:#c2410c;">(corrected from ${ticket.ocr_original_plate})</span>` : ""}</td><td class="label">Fine</td><td>$${Number(ticket.fine_amount).toFixed(2)}</td></tr>
      <tr><td class="label">Violation</td><td>${ticket.violation_type.replace(/_/g, " ")}${ticket.additional_violations?.length ? ", " + ticket.additional_violations.map(v => (v.label || v.code).replace(/_/g, " ")).join(", ") : ""}</td><td class="label">${ticket.ticket_category === "moving" ? "Location" : "Lot"}</td><td>${ticket.ticket_category === "moving" ? (ticket.location_text || "—") : ticket.lot}</td></tr>
      <tr><td class="label">Issued</td><td>${fmtDateTime(ticket.issued_at)}</td><td class="label">Officer</td><td>${ticket.officer_name || ticket.officer_id}</td></tr>
      ${ticket.owner_name ? `<tr><td class="label">Owner</td><td>${ticket.owner_name}</td><td class="label">Permit #</td><td>${ticket.permit_number || "—"}</td></tr>` : ""}
      ${ticket.permit_type_label ? `<tr><td class="label">Permit Type</td><td>${ticket.permit_type_label}</td><td class="label">Permit Lot</td><td>${ticket.permit_lot_zone || "—"}</td></tr>` : ""}
      ${gpsLink ? `<tr><td class="label">GPS</td><td colspan="3"><a href="${gpsLink}" style="font-family:monospace;font-size:12px;">${ticket.location_lat!.toFixed(6)}, ${ticket.location_lng!.toFixed(6)}</a></td></tr>` : ""}
    </table>
  </div>

  ${ticket.ticket_category === "moving" ? `
  <div class="section">
    <div class="section-title">Driver & Vehicle</div>
    <table>
      ${ticket.driver_name ? `<tr><td class="label">Driver</td><td>${ticket.driver_name}</td></tr>` : ""}
      ${ticket.driver_license ? `<tr><td class="label">License</td><td style="font-family:monospace;">${ticket.driver_license}</td></tr>` : ""}
      ${ticket.vehicle_description ? `<tr><td class="label">Vehicle</td><td>${ticket.vehicle_description}</td></tr>` : ""}
      ${ticket.officer_notes ? `<tr><td class="label">Notes</td><td>${ticket.officer_notes}</td></tr>` : ""}
    </table>
  </div>` : ""}

  ${ticket.appeal_note ? `
  <div class="section">
    <div class="section-title">Appeal</div>
    <table>
      <tr><td class="label">Note</td><td>${ticket.appeal_note}</td></tr>
      <tr><td class="label">Decision</td><td>${ticket.appeal_decision || "Pending"}</td></tr>
      ${ticket.appeal_decided_by ? `<tr><td class="label">Decided By</td><td>${ticket.appeal_decided_by}</td></tr>` : ""}
      ${ticket.appeal_decision_reason ? `<tr><td class="label">Reason</td><td>${ticket.appeal_decision_reason}</td></tr>` : ""}
    </table>
  </div>` : ""}

  ${ticket.void_reason ? `
  <div class="section">
    <div class="section-title">Void Reason</div>
    <p>${ticket.void_reason}</p>
  </div>` : ""}

  ${photoUrl ? `
  <div class="section">
    <div class="section-title">Evidence Photo${ticket.additional_photo_count > 0 ? "s" : ""}</div>
    <img src="${photoUrl}" class="photo" />
    ${ticket.additional_photo_count > 0 ? Array.from({ length: ticket.additional_photo_count }).map((_, i) => `<img src="${window.location.origin}/api/tickets/${ticket.id}/photos/${i}" class="photo" style="margin-top:8px" />`).join("") : ""}
  </div>` : ""}

  <div class="footer">
    This document was generated from the Quarry Parking Management System. Citation ID: ${ticket.id}
  </div>

  <script>
    ${photoUrl ? `
    const img = document.querySelector('.photo');
    if (img) {
      img.onload = () => { window.print(); };
      img.onerror = () => { window.print(); };
      setTimeout(() => { window.print(); }, 3000);
    } else { window.print(); }
    ` : "window.print();"}
  </script>
</body>
</html>`);
    printWindow.document.close();
  }

  async function handleVoid(id: string) {
    if (!isAdmin) return;
    let voidReason = "";
    modal.confirm({
      title: "Void this ticket?",
      content: (
        <div>
          <p style={{ marginBottom: 8 }}>This action will void the ticket and cannot be easily reversed.</p>
          <Input.TextArea
            placeholder="Reason for voiding (optional)"
            rows={3}
            onChange={(e) => { voidReason = e.target.value; }}
          />
        </div>
      ),
      okText: "Void Ticket",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const res = await fetch(`/api/tickets/${id}/void`, {
            method: "POST",
            headers: await authHeaders(),
            body: JSON.stringify({ reason: voidReason }),
          });
          message.success("Ticket voided");
          load();
          if (res.ok && selected?.id === id) {
            setSelected({ ...selected, status: "voided", void_reason: voidReason || null });
          }
        } catch {
          message.error("Failed to void ticket");
        }
      },
    });
  }

  async function handleBulkVoid() {
    if (selectedRowKeys.length === 0) return;
    setBulkVoiding(true);
    try {
      const res = await fetch("/api/tickets/bulk-void", {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({ ids: selectedRowKeys }),
      });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Bulk void failed"); }
      const { voided, skipped } = await res.json();
      message.success(`${voided} ticket(s) voided${skipped > 0 ? `, ${skipped} skipped (already paid/voided)` : ""}`);
      setSelectedRowKeys([]);
      load();
    } catch (e: any) { message.error(e.message); }
    finally { setBulkVoiding(false); }
  }

  async function handleAppealDecision(id: string, decision: string) {
    if (!isAdmin) return;
    const decided_by = user?.email || "admin";
    let appealReason = "";
    modal.confirm({
      title: `${decision === "approved" ? "Approve" : "Deny"} this appeal?`,
      content: (
        <div>
          <p style={{ marginBottom: 8 }}>
            {decision === "approved"
              ? "The ticket will be voided."
              : "The ticket will return to pending payment."}
          </p>
          <Input.TextArea
            placeholder="Explanation / reason (optional)"
            rows={3}
            onChange={(e) => { appealReason = e.target.value; }}
          />
        </div>
      ),
      okText: decision === "approved" ? "Approve" : "Deny",
      okButtonProps: decision === "denied" ? { danger: true } : {},
      onOk: async () => {
        try {
          await fetch(`/api/tickets/${id}/appeal/decide`, {
            method: "POST",
            headers: await authHeaders(),
            body: JSON.stringify({ decision, decided_by, reason: appealReason }),
          });
          message.success(`Appeal ${decision}`);
          load();
          setSelected(null);
        } catch {
          message.error("Failed to process appeal decision");
        }
      },
    });
  }

  async function handleEscalateToCommittee(id: string) {
    if (!isAdmin) return;
    let notes = "";
    modal.confirm({
      title: "Escalate to Appeals Committee?",
      content: (
        <div>
          <p style={{ marginBottom: 8 }}>
            This will send the case to the parking appeals committee for review and voting.
          </p>
          <Input.TextArea
            placeholder="Notes for the committee (optional)"
            rows={3}
            onChange={(e) => { notes = e.target.value; }}
          />
        </div>
      ),
      okText: "Escalate",
      onOk: async () => {
        try {
          await fetch(`/api/appeal-committee/escalate/${id}`, {
            method: "POST",
            headers: await authHeaders(),
            body: JSON.stringify({ notes }),
          });
          message.success("Escalated to appeals committee");
          load();
          setSelected(null);
        } catch {
          message.error("Failed to escalate");
        }
      },
    });
  }

  const columns: ColumnsType<Ticket> = [
    {
      title: "Ticket #",
      dataIndex: "ticket_number",
      key: "ticket_number",
      width: 120,
      render: (num: string | null) => <span className="font-mono text-brand-primary font-medium">{num || "—"}</span>,
    },
    {
      title: "Plate",
      dataIndex: "plate",
      key: "plate",
      render: (plate: string, t: Ticket) => (
        <span>
          <span className="font-mono">{plate}</span>
          {t.ocr_original_plate && (
            <Tag color="volcano" className="ml-1" style={{ fontSize: 10, lineHeight: "16px", padding: "0 4px" }}>corrected</Tag>
          )}
        </span>
      ),
    },
    {
      title: "Name",
      dataIndex: "owner_name",
      key: "owner_name",
      ellipsis: true,
      render: (name: string | null) => name || <span className="text-gray-400">—</span>,
    },
    {
      title: "Location",
      key: "location",
      render: (_, t) => t.ticket_category === "moving" ? (t.location_text || "—") : t.lot,
    },
    {
      title: "Violation",
      key: "violation",
      render: (_, t) => (
        <Space wrap>
          <span className="capitalize">{t.violation_type.replace(/_/g, " ")}</span>
          {t.additional_violations?.map((v, i) => (
            <Tag key={i} color="blue" className="capitalize" style={{ margin: 0 }}>{v.label || v.code.replace(/_/g, " ")}</Tag>
          ))}
          {t.ticket_category === "moving" && <Tag color="red">MOVING</Tag>}
        </Space>
      ),
    },
    {
      title: "Fine",
      dataIndex: "fine_amount",
      key: "fine",
      render: (amt: string) => `$${Number(amt).toFixed(2)}`,
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string) => (
        <Tag color={STATUS_COLORS[status] || "default"}>
          {status.replace("_", " ")}
        </Tag>
      ),
    },
    {
      title: "Officer",
      key: "officer",
      width: 140,
      render: (_: unknown, t: Ticket) => (
        <span className="text-xs text-gray-500">{t.officer_name || t.officer_email || t.officer_id || "—"}</span>
      ),
    },
    {
      title: "Issued",
      dataIndex: "issued_at",
      key: "issued_at",
      render: (d: string) => fmtDateTimeCompact(d),
    },
    ...(isAdmin ? [{
      title: "Actions",
      key: "actions",
      width: 100,
      render: (_: unknown, t: Ticket) =>
        !["paid", "voided"].includes(t.status) ? (
          <Button type="link" danger size="small" onClick={(e) => { e.stopPropagation(); handleVoid(t.id); }}>
            Void
          </Button>
        ) : null,
    }] : []),
  ];

  const [mailNoticesOpen, setMailNoticesOpen] = useState(false);
  const [pendingNotices, setPendingNotices] = useState<any[]>([]);
  const [noticesLoading, setNoticesLoading] = useState(false);
  const [markingMailed, setMarkingMailed] = useState(false);
  const printRef = useRef<HTMLDivElement>(null);

  async function loadPendingNotices() {
    setNoticesLoading(true);
    try {
      const res = await fetch("/api/tickets/mail-notices/pending", { headers: await authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setPendingNotices(data.tickets);
      }
    } catch { message.error("Failed to load pending notices"); }
    finally { setNoticesLoading(false); }
  }

  async function handleMarkMailed() {
    if (pendingNotices.length === 0) return;
    setMarkingMailed(true);
    try {
      const res = await fetch("/api/tickets/mail-notices/mark-mailed", {
        method: "POST", headers: await authHeaders(),
        body: JSON.stringify({ ticket_ids: pendingNotices.map(t => t.id) }),
      });
      if (res.ok) {
        const data = await res.json();
        message.success(`${data.marked} notice(s) marked as mailed`);
        setPendingNotices([]);
        setMailNoticesOpen(false);
      }
    } catch { message.error("Failed to mark notices"); }
    finally { setMarkingMailed(false); }
  }

  function handlePrintNotices() {
    const printWindow = window.open("", "_blank");
    if (!printWindow) return;
    printWindow.document.write(`
      <html><head><title>Mail Notices - Unpaid Citations</title>
      <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 0; margin: 0; }
        .notice { page-break-after: always; padding: 48px; max-width: 8.5in; margin: 0 auto; }
        .notice:last-child { page-break-after: auto; }
        .header { text-align: center; border-bottom: 2px solid #1a2744; padding-bottom: 16px; margin-bottom: 24px; }
        .header h1 { margin: 0; font-size: 18px; color: #1a2744; }
        .header p { margin: 4px 0 0; font-size: 12px; color: #666; }
        .details { border: 1px solid #ddd; border-radius: 4px; padding: 16px; margin: 16px 0; }
        .details table { width: 100%; border-collapse: collapse; }
        .details td { padding: 6px 8px; font-size: 13px; }
        .details td:first-child { color: #666; width: 140px; }
        .details td:last-child { font-weight: 600; }
        .warning { background: #fef2f2; border: 1px solid #fecaca; border-radius: 4px; padding: 12px 16px; margin: 20px 0; font-size: 12px; color: #991b1b; }
        .payment { text-align: center; margin: 24px 0; padding: 16px; background: #f8f9fa; border-radius: 4px; }
        .payment p { margin: 0 0 8px; font-size: 13px; }
        .payment .url { font-family: monospace; font-size: 11px; color: #1a2744; word-break: break-all; }
        .footer { text-align: center; font-size: 11px; color: #999; margin-top: 32px; border-top: 1px solid #eee; padding-top: 16px; }
        @media print { body { margin: 0; } .notice { padding: 0.5in; } }
      </style></head><body>`);
    for (const t of pendingNotices) {
      printWindow.document.write(`
        <div class="notice">
          <div class="header">
            <h1>MORAVIAN UNIVERSITY POLICE DEPARTMENT</h1>
            <p>Unpaid Parking Citation Notice</p>
          </div>
          <p style="font-size:13px;color:#333;">A parking citation was issued to a vehicle registered to this address. The citation remains unpaid and is now overdue. Failure to pay or appeal within 10 days of this notice may result in a state citation being issued through the local Magisterial District Court, which carries additional court costs and fees.</p>
          <div class="details"><table>
            <tr><td>Citation #</td><td>${t.ticket_number || t.id.slice(0, 8).toUpperCase()}</td></tr>
            <tr><td>License Plate</td><td style="font-family:monospace;letter-spacing:1px;">${t.plate}</td></tr>
            <tr><td>Violation</td><td>${(t.violation_type || "").replace(/_/g, " ")}</td></tr>
            <tr><td>Location</td><td>${t.lot || "—"}</td></tr>
            <tr><td>Date Issued</td><td>${t.issued_at ? fmtDateTime(t.issued_at) : "—"}</td></tr>
            <tr><td>Fine Amount</td><td style="color:#dc2626;font-size:16px;">$${Number(t.fine_amount).toFixed(2)}</td></tr>
            <tr><td>Status</td><td>${t.status.toUpperCase()}</td></tr>
            ${t.vehicle_description ? `<tr><td>Vehicle</td><td>${t.vehicle_description}</td></tr>` : ""}
          </table></div>
          <div class="warning">
            <strong>NOTICE:</strong> If this citation is not paid or appealed within 10 days of the date on this notice, a state citation will be issued through the local Magisterial District Court, carrying mandatory court costs and fees — often totaling more than $100 on top of the fine itself.
          </div>
          <div class="payment">
            <p><strong>Pay Online:</strong></p>
            <p class="url">${t.payment_url}</p>
            <p style="margin-top:12px;font-size:11px;color:#666;">Or mail payment (check/money order) to:<br/>Moravian University Police Department<br/>119 West Greenwich Street, Bethlehem, PA 18018</p>
          </div>
          <div class="footer">
            <p>Moravian University Police Department &middot; 119 West Greenwich Street &middot; Bethlehem, PA 18018</p>
            <p>Questions? Contact us at campuspolice@moravian.edu</p>
          </div>
        </div>`);
    }
    printWindow.document.write("</body></html>");
    printWindow.document.close();
    printWindow.print();
  }

  return (
    <div>
      {officerEmail && <OfficerStats />}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Tickets</h2>
        <Space>
          {isAdmin && selectedRowKeys.length > 0 && (
            <Popconfirm
              title={`Void ${selectedRowKeys.length} ticket(s)?`}
              description="This will void all selected tickets. Paid and already-voided tickets will be skipped."
              onConfirm={handleBulkVoid}
              okText="Void All"
              okButtonProps={{ danger: true, loading: bulkVoiding }}
            >
              <Button danger loading={bulkVoiding}>
                Void Selected ({selectedRowKeys.length})
              </Button>
            </Popconfirm>
          )}
          {isOffice && (
            <Button onClick={() => { setMailNoticesOpen(true); loadPendingNotices(); }}>
              Mail Notices
            </Button>
          )}
        </Space>
      </div>

      <Space className="mb-4" wrap>
        <Input.Search
          placeholder="Search by ticket #, plate, name, or location..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          onSearch={() => setPage(1)}
          style={{ width: 300 }}
          allowClear
        />
        <Select
          value={statusFilter || undefined}
          onChange={(val) => { setStatusFilter(val || ""); setPage(1); }}
          placeholder="All Statuses"
          allowClear
          style={{ width: 170 }}
          options={[
            { label: "Issued", value: "issued" },
            { label: "Overdue", value: "overdue" },
            { label: "Pending Payment", value: "pending_payment" },
            { label: "Paid", value: "paid" },
            { label: "Appealed", value: "appealed" },
            { label: "Escalated", value: "escalated" },
            { label: "Voided", value: "voided" },
          ]}
        />
        <Select
          value={categoryFilter || undefined}
          onChange={(val) => { setCategoryFilter(val || ""); setPage(1); }}
          placeholder="All Types"
          allowClear
          style={{ width: 140 }}
          options={[
            { label: "Parking", value: "parking" },
            { label: "Moving", value: "moving" },
          ]}
        />
      </Space>

      <Table
        dataSource={tickets}
        columns={columns}
        rowKey="id"
        loading={loading}
        rowSelection={isAdmin ? {
          selectedRowKeys,
          onChange: setSelectedRowKeys,
          getCheckboxProps: (t) => ({
            disabled: ["paid", "voided"].includes(t.status),
          }),
        } : undefined}
        onRow={(t) => ({ onClick: () => setSelected(t), className: "cursor-pointer" })}
        pagination={{
          current: page,
          total,
          pageSize: 50,
          onChange: setPage,
          showSizeChanger: false,
          showTotal: (t) => `${t} tickets`,
        }}
        locale={{ emptyText: <Empty description="No tickets found" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />

      <Modal
        open={!!selected}
        onCancel={() => setSelected(null)}
        title={
          <Space>
            {selected?.ticket_number || (selected?.ticket_category === "moving" ? "Citation Detail" : "Ticket Detail")}
            {selected?.ticket_category === "moving" && <Tag color="red">Moving Violation</Tag>}
          </Space>
        }
        footer={
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => setSelected(null)}>Close</Button>
            {selected && (
              <Button onClick={() => handlePrintTicket(selected)}>Print</Button>
            )}
            <div className="flex-1" />
            {isAdmin && selected?.appeal_decision === "pending" && (
              <>
                <Button size="small" type="primary" style={{ background: "#22C55E" }} onClick={() => handleAppealDecision(selected!.id, "approved")}>
                  Approve
                </Button>
                <Button size="small" danger onClick={() => handleAppealDecision(selected!.id, "denied")}>
                  Deny
                </Button>
                <Button size="small" style={{ background: "#a855f7", color: "#fff", borderColor: "#a855f7" }} onClick={() => handleEscalateToCommittee(selected!.id)}>
                  Escalate
                </Button>
              </>
            )}
            {isAdmin && selected && !["paid", "voided"].includes(selected.status) && (
              <Button size="small" danger type="primary" onClick={() => handleVoid(selected.id)}>Void</Button>
            )}
          </div>
        }
        width={720}
      >
        {selected && (
          <div className="space-y-4">
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="Plate">
                <span className="font-mono">{selected.plate}</span>
                {selected.ocr_original_plate && (
                  <Tag color="volcano" className="ml-2" style={{ fontSize: 11 }}>
                    OCR read: {selected.ocr_original_plate}
                  </Tag>
                )}
              </Descriptions.Item>
              <Descriptions.Item label={selected.ticket_category === "moving" ? "Location" : "Lot"}>
                {selected.ticket_category === "moving" ? (selected.location_text || "—") : selected.lot}
              </Descriptions.Item>
              <Descriptions.Item label="Violation">
                <span className="capitalize">{selected.violation_type.replace(/_/g, " ")}</span>
                {selected.additional_violations?.map((v, i) => (
                  <Tag key={i} color="blue" className="ml-1 capitalize">{v.label || v.code.replace(/_/g, " ")}</Tag>
                ))}
              </Descriptions.Item>
              <Descriptions.Item label="Fine">${Number(selected.fine_amount).toFixed(2)}</Descriptions.Item>
              <Descriptions.Item label="Status"><Tag color={STATUS_COLORS[selected.status]}>{selected.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="Officer">
                <div>{selected.officer_name || selected.officer_id}</div>
                {selected.officer_email && <div className="text-xs text-gray-400">{selected.officer_email}</div>}
              </Descriptions.Item>
              {selected.owner_name && <Descriptions.Item label="Owner">{selected.owner_name}</Descriptions.Item>}
              {selected.permit_number && <Descriptions.Item label="Permit #">{selected.permit_number}</Descriptions.Item>}
              {selected.permit_type_label && <Descriptions.Item label="Permit Type">{selected.permit_type_label}</Descriptions.Item>}
              {selected.permit_lot_zone && <Descriptions.Item label="Permit Lot">{selected.permit_lot_zone}</Descriptions.Item>}
              <Descriptions.Item label="Issued" span={2}>{fmtDateTime(selected.issued_at)}</Descriptions.Item>
              {selected.location_lat && selected.location_lng && (
                <Descriptions.Item label="GPS" span={2}>
                  <a
                    href={`https://maps.google.com/?q=${selected.location_lat},${selected.location_lng}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline font-mono text-xs"
                  >
                    {selected.location_lat.toFixed(6)}, {selected.location_lng.toFixed(6)}
                  </a>
                </Descriptions.Item>
              )}
            </Descriptions>

            <div className="bg-gray-50 rounded-lg px-3 py-2 text-xs text-gray-500 space-y-1">
              <div className="font-medium text-gray-600 mb-1">Audit Trail</div>
              <div>Created: {fmtDateTime(selected.created_at)}</div>
              <div>Last updated: {fmtDateTime(selected.updated_at)}</div>
              {selected.mailed_at && <div>Mailed: {fmtDateTime(selected.mailed_at)}{selected.mailed_address ? ` — ${selected.mailed_address}` : ""}</div>}
              <div className="font-mono text-[10px] text-gray-400 select-all">ID: {selected.id}</div>
            </div>

            {selected.ticket_category === "moving" && (
              <div className="bg-red-50 border border-red-100 rounded-lg p-3 text-sm">
                <div className="font-medium text-red-800 mb-2">Driver & Vehicle</div>
                <Descriptions size="small" column={2}>
                  {selected.driver_name && <Descriptions.Item label="Driver">{selected.driver_name}</Descriptions.Item>}
                  {selected.driver_license && <Descriptions.Item label="License"><span className="font-mono">{selected.driver_license}</span></Descriptions.Item>}
                  {selected.vehicle_description && <Descriptions.Item label="Vehicle" span={2}>{selected.vehicle_description}</Descriptions.Item>}
                  {selected.officer_notes && <Descriptions.Item label="Notes" span={2}>{selected.officer_notes}</Descriptions.Item>}
                </Descriptions>
              </div>
            )}

            {selected.photo_url && (
              <div>
                <Image src={selected.photo_url} alt="Violation photo" className="rounded-lg max-h-48 object-cover" />
                {selected.additional_photo_count > 0 && (
                  <div className="flex gap-2 mt-2 flex-wrap">
                    {Array.from({ length: selected.additional_photo_count }).map((_, i) => (
                      <Image key={i} src={`/api/tickets/${selected.id}/photos/${i}`} alt={`Additional photo ${i + 1}`} className="rounded-lg max-h-32 object-cover" />
                    ))}
                  </div>
                )}
              </div>
            )}

            {selected.appeal_note && (
              <div className="bg-yellow-50 rounded-lg p-3 text-sm">
                <div className="font-medium text-yellow-800 mb-1">Appeal Note</div>
                <p>{selected.appeal_note}</p>
                {(selected.dispute_name || selected.dispute_email || selected.dispute_phone) && (
                  <div className="mt-2 pt-2 border-t border-yellow-200 text-xs text-ink-mute space-y-0.5">
                    {selected.dispute_name && <div>Name: <span className="text-ink">{selected.dispute_name}</span></div>}
                    {selected.dispute_email && (
                      <div>Email: <a href={`mailto:${selected.dispute_email}`} className="text-brand-primary hover:underline">{selected.dispute_email}</a></div>
                    )}
                    {selected.dispute_phone && <div>Phone: <span className="text-ink">{selected.dispute_phone}</span></div>}
                  </div>
                )}
                {selected.appeal_decision && (
                  <div className="mt-2 text-xs text-ink-mute">
                    Decision: <strong>{selected.appeal_decision}</strong>
                    {selected.appeal_decided_by && ` by ${selected.appeal_decided_by}`}
                    {selected.appeal_decision_reason && (
                      <div className="mt-1">Reason: {selected.appeal_decision_reason}</div>
                    )}
                  </div>
                )}
              </div>
            )}

            {selected.committee_status && (
              <div className="bg-purple-50 rounded-lg p-3 text-sm">
                <div className="font-medium text-purple-800 mb-1">Appeals Committee</div>
                <div className="text-xs space-y-1">
                  <div>Status: <Tag color={selected.committee_status === "voting" ? "processing" : "success"}>{selected.committee_status}</Tag></div>
                  {selected.escalated_by && <div>Escalated by {selected.escalated_by}</div>}
                  {selected.committee_notes && <div>Notes: {selected.committee_notes}</div>}
                  {selected.committee_decision && (
                    <div>Decision: <Tag color={selected.committee_decision === "upheld" ? "green" : "red"}>{selected.committee_decision}</Tag></div>
                  )}
                </div>
              </div>
            )}

            {selected.void_reason && (
              <div className="bg-gray-50 rounded-lg p-3 text-sm">
                <div className="font-medium text-gray-700 mb-1">Void Reason</div>
                <p>{selected.void_reason}</p>
              </div>
            )}
          </div>
        )}
      </Modal>

      <Modal
        open={mailNoticesOpen}
        onCancel={() => setMailNoticesOpen(false)}
        title="Mail Notices — Unpaid Guest/Visitor Citations"
        width={700}
        footer={
          <Space>
            <Button onClick={() => setMailNoticesOpen(false)}>Close</Button>
            {pendingNotices.length > 0 && (
              <>
                <Button onClick={handlePrintNotices}>Print Notices ({pendingNotices.length})</Button>
                <Button type="primary" loading={markingMailed} onClick={handleMarkMailed}>
                  Mark All as Mailed ({pendingNotices.length})
                </Button>
              </>
            )}
          </Space>
        }
      >
        <p className="text-sm text-ink-mute mb-4">
          Overdue citations for unregistered vehicles (guests/visitors) that have not yet received a mailed notice.
          Print these notices and mail them to the registered vehicle owner via DMV records.
        </p>
        {noticesLoading ? (
          <div className="text-center py-8 text-ink-mute">Loading...</div>
        ) : pendingNotices.length === 0 ? (
          <Empty description="No pending mail notices" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div ref={printRef}>
            <Table
              dataSource={pendingNotices}
              rowKey="id"
              size="small"
              pagination={false}
              scroll={{ y: 400 }}
              columns={[
                { title: "Ticket #", dataIndex: "ticket_number", width: 100, render: (v: string) => <span className="font-mono text-xs">{v || "—"}</span> },
                { title: "Plate", dataIndex: "plate", width: 100, render: (v: string) => <span className="font-mono">{v}</span> },
                { title: "Violation", dataIndex: "violation_type", render: (v: string) => <span className="capitalize text-xs">{(v || "").replace(/_/g, " ")}</span> },
                { title: "Lot", dataIndex: "lot", width: 60 },
                { title: "Fine", dataIndex: "fine_amount", width: 80, render: (v: string) => `$${Number(v).toFixed(2)}` },
                { title: "Issued", dataIndex: "issued_at", width: 160, render: (v: string) => v ? fmtDateTimeCompact(v) : "—" },
                { title: "Status", dataIndex: "status", width: 90, render: (v: string) => <Tag color={STATUS_COLORS[v] || "default"}>{v}</Tag> },
              ]}
            />
          </div>
        )}
      </Modal>
    </div>
  );
}

export default function Tickets() {
  const user = useCurrentUser();
  const isAdmin = isAdminRole(user?.role);
  const isOffice = isOfficeRole(user?.role);
  const [activeTab, setActiveTab] = useState("tickets");

  const tabItems = [
    { key: "tickets", label: "Tickets", children: <TicketsList /> },
    ...(user?.email ? [{ key: "my-tickets", label: "My Ticket History", children: <TicketsList officerEmail={user.email} /> }] : []),
    ...(isAdmin ? [{ key: "officer-report", label: "Reporting", children: <OfficerReport /> }] : []),
    ...(isOffice ? [{ key: "enforcement", label: "Enforcement", children: <EnforcementSettings /> }] : []),
    { key: "devices", label: "Enforcement Devices", children: <Devices /> },
  ];

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Tickets & Enforcement</h2>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        destroyInactiveTabPane
        items={tabItems}
      />
    </div>
  );
}
