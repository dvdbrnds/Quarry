import { useCallback, useEffect, useState } from "react";
import { Card, Progress, Spin, Tag, Empty } from "antd";
import { authHeaders } from "../auth";

interface PermitTypeStat {
  id: string;
  code: string;
  label: string;
  max_capacity: number;
  active_count: number;
  remaining: number;
  pct: number;
  is_purchasable_online: boolean;
  requires_lottery: boolean;
}

interface LotteryCycle {
  id: string;
  name: string;
  status: string;
  application_count: number;
  auto_draw_threshold: number | null;
}

interface RecentPermit {
  id: string;
  permit_number: string | null;
  name: string;
  email: string | null;
  plate: string;
  permit_type: string;
  permit_type_label: string;
  lot_assignment: string;
  created_at: string;
}

interface LiveData {
  permit_types: PermitTypeStat[];
  lottery_cycle: LotteryCycle | null;
  recent_permits: RecentPermit[];
}

function progressColor(pct: number): string {
  if (pct >= 90) return "#dc2626";
  if (pct >= 70) return "#d97706";
  return "#16a34a";
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function LiveMonitor() {
  const [data, setData] = useState<LiveData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/permits/live-status", { headers: await authHeaders() });
      if (res.ok) {
        setData(await res.json());
        setLastUpdated(new Date());
      }
    } catch { /* network error */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 10_000);
    return () => clearInterval(interval);
  }, [load]);

  if (loading && !data) {
    return <div className="flex justify-center py-20"><Spin size="large" /></div>;
  }

  if (!data) {
    return <Empty description="Unable to load live data" />;
  }

  const purchasable = data.permit_types.filter(pt => pt.is_purchasable_online && !pt.requires_lottery);
  const lotteryTiers = data.permit_types.filter(pt => pt.requires_lottery);
  const otherTypes = data.permit_types.filter(pt => !pt.is_purchasable_online && !pt.requires_lottery);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="inline-block w-2.5 h-2.5 bg-green-500 rounded-full animate-pulse" />
          <span className="text-sm font-medium text-gray-600">
            Auto-refreshing every 10s
          </span>
        </div>
        {lastUpdated && (
          <span className="text-xs text-gray-400">
            Last updated: {lastUpdated.toLocaleTimeString()}
          </span>
        )}
      </div>

      {/* Direct Purchase Permit Types */}
      {purchasable.length > 0 && (
        <Card title="Direct Purchase — Capacity" size="small">
          <div className="space-y-4">
            {purchasable.map(pt => (
              <div key={pt.id}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium">{pt.label}</span>
                  <span className="text-xs text-gray-500">
                    {pt.active_count} / {pt.max_capacity}
                    <span className="ml-2 text-gray-400">({pt.remaining} left)</span>
                  </span>
                </div>
                <Progress
                  percent={pt.pct}
                  strokeColor={progressColor(pt.pct)}
                  showInfo={false}
                  size="small"
                />
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Lottery Tiers */}
      {lotteryTiers.length > 0 && (
        <Card
          title={
            <div className="flex items-center gap-3">
              <span>Lottery Tiers — Capacity</span>
              {data.lottery_cycle && (
                <Tag color={data.lottery_cycle.status === "open" ? "green" : "default"}>
                  {data.lottery_cycle.name}: {data.lottery_cycle.status}
                  {data.lottery_cycle.status === "open" && ` (${data.lottery_cycle.application_count} apps)`}
                </Tag>
              )}
            </div>
          }
          size="small"
        >
          <div className="space-y-4">
            {lotteryTiers.map(pt => {
              const threshold = data.lottery_cycle?.auto_draw_threshold;
              const drawLine = threshold && pt.max_capacity ? Math.round(pt.max_capacity * threshold) : null;
              return (
                <div key={pt.id}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium">{pt.label}</span>
                    <span className="text-xs text-gray-500">
                      {pt.active_count} / {pt.max_capacity}
                      <span className="ml-2 text-gray-400">({pt.remaining} left)</span>
                      {drawLine && (
                        <span className="ml-2 text-purple-500">
                          auto-draw at {drawLine} apps
                        </span>
                      )}
                    </span>
                  </div>
                  <Progress
                    percent={pt.pct}
                    strokeColor={progressColor(pt.pct)}
                    showInfo={false}
                    size="small"
                  />
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* Other Types (admin-issued) */}
      {otherTypes.length > 0 && (
        <Card title="Admin-Issued — Capacity" size="small">
          <div className="space-y-4">
            {otherTypes.map(pt => (
              <div key={pt.id}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium">{pt.label}</span>
                  <span className="text-xs text-gray-500">
                    {pt.active_count} / {pt.max_capacity}
                    <span className="ml-2 text-gray-400">({pt.remaining} left)</span>
                  </span>
                </div>
                <Progress
                  percent={pt.pct}
                  strokeColor={progressColor(pt.pct)}
                  showInfo={false}
                  size="small"
                />
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Recent Permits Feed */}
      <Card
        title={
          <div className="flex items-center gap-2">
            <span>Recent Permits (last 24h)</span>
            <Tag>{data.recent_permits.length}</Tag>
          </div>
        }
        size="small"
        styles={{ body: { padding: 0 } }}
      >
        {data.recent_permits.length === 0 ? (
          <Empty description="No permits issued in the last 24 hours" className="py-8" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div className="divide-y divide-gray-50 max-h-[400px] overflow-y-auto">
            {data.recent_permits.map(p => (
              <div key={p.id} className="px-5 py-3 flex items-center gap-4 hover:bg-gray-50 transition-colors">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">{p.name}</span>
                    <span className="font-mono text-xs text-gray-500">{p.plate}</span>
                  </div>
                  <div className="text-xs text-gray-400 mt-0.5">
                    {p.permit_type_label}
                    {p.lot_assignment && <span className="ml-2">· {p.lot_assignment}</span>}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  {p.permit_number && (
                    <div className="font-mono text-xs text-gray-500">{p.permit_number}</div>
                  )}
                  <div className="text-xs text-gray-400">{timeAgo(p.created_at)}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
