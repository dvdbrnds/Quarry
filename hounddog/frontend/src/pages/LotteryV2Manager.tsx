import { useCallback, useEffect, useState } from "react";
import {
  Alert, Button, Card, Collapse, Space, Statistic, Table, Tag, App as AntApp, InputNumber,
} from "antd";
import { authHeaders } from "../auth";

interface Cycle {
  id: string;
  name: string;
  status: string;
  opens_at: string | null;
  closes_at: string | null;
  offer_window_days: number;
  drawn_at: string | null;
  drawn_by: string | null;
  auto_draw_threshold: number | null;
  auto_draw_at: string | null;
  application_count: number;
}

interface Application {
  id: string;
  student_name: string;
  student_email: string;
  class_year: number;
  campus: string;
  plate: string;
  status: string;
  lottery_rank: number | null;
  waitlist_position: number | null;
  assigned_permit_type_label: string | null;
  assigned_lot: string | null;
  is_test_entry: boolean;
  created_at: string;
}

interface Results {
  cycle: Cycle;
  audit: {
    strategy: string | null;
    total_applicants: number;
    eligible_applicants: number;
    selected_count: number;
    waitlisted_count: number;
    run_at: string | null;
    run_by: string | null;
    warnings: string | null;
  } | null;
  by_tier: Record<string, Application[]>;
  waitlisted: Application[];
  applications: Application[];
}

const STATUS_COLORS: Record<string, string> = {
  pending: "gold",
  selected: "green",
  waitlisted: "blue",
  accepted: "lime",
  declined: "default",
  expired: "default",
  ineligible: "red",
};

export default function LotteryV2Manager() {
  const { message, modal } = AntApp.useApp();
  const [cycles, setCycles] = useState<Cycle[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [apps, setApps] = useState<Application[]>([]);
  const [results, setResults] = useState<Results | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [autoThreshold, setAutoThreshold] = useState<number | null>(110);
  const [autoDays, setAutoDays] = useState<number | null>(5);

  const active = cycles.find((c) => c.id === activeId) || null;
  const studentUrl = `${window.location.origin}/parking`;

  const loadCycles = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/lottery-v2/cycles", { headers: await authHeaders() });
      if (!res.ok) throw new Error("Failed to load cycles");
      const data: Cycle[] = await res.json();
      setCycles(data);
      if (!activeId && data.length) setActiveId(data[0].id);
      if (activeId && !data.find((c) => c.id === activeId) && data.length) {
        setActiveId(data[0].id);
      }
    } catch (e: any) {
      message.error(e.message || "Load failed");
    } finally {
      setLoading(false);
    }
  }, [activeId, message]);

  const loadDetail = useCallback(async (cycleId: string) => {
    try {
      const headers = await authHeaders();
      const [appsRes, resultsRes] = await Promise.all([
        fetch(`/api/lottery-v2/cycles/${cycleId}/applications`, { headers }),
        fetch(`/api/lottery-v2/cycles/${cycleId}/results`, { headers }),
      ]);
      if (appsRes.ok) setApps(await appsRes.json());
      if (resultsRes.ok) setResults(await resultsRes.json());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    loadCycles();
  }, [loadCycles]);

  useEffect(() => {
    if (activeId) loadDetail(activeId);
  }, [activeId, loadDetail]);

  async function createCycle() {
    setBusy(true);
    try {
      const res = await fetch("/api/lottery-v2/cycles", {
        method: "POST",
        headers: { ...(await authHeaders()), "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Parking Lottery" }),
      });
      if (!res.ok) throw new Error("Create failed");
      const cycle = await res.json();
      message.success("Cycle created");
      setActiveId(cycle.id);
      await loadCycles();
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function postAction(path: string, body?: object) {
    setBusy(true);
    try {
      const res = await fetch(path, {
        method: "POST",
        headers: {
          ...(await authHeaders()),
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Action failed");
      }
      const data = await res.json();
      await loadCycles();
      if (activeId) await loadDetail(activeId);
      return data;
    } catch (e: any) {
      message.error(e.message);
      return null;
    } finally {
      setBusy(false);
    }
  }

  function confirmRun() {
    if (!active) return;
    modal.confirm({
      title: `Run waterfall draw for "${active.name}"?`,
      content:
        "Applicants will be sorted by class year then timestamp, then placed into their ranked tiers. Notifications are off by default for staging.",
      okText: "Run draw",
      onOk: async () => {
        const data = await postAction(`/api/lottery-v2/cycles/${active.id}/run`, {
          include_test_entries: true,
          send_notifications: false,
        });
        if (data) {
          message.success(
            `Draw complete: ${data.selected_count} selected, ${data.waitlisted_count} waitlisted`,
          );
        }
      },
    });
  }

  const columns = [
    {
      title: "Rank",
      dataIndex: "lottery_rank",
      width: 70,
      render: (v: number | null) => (v != null ? `#${v}` : "—"),
    },
    {
      title: "Name",
      dataIndex: "student_name",
      render: (v: string, r: Application) => (
        <span>
          {v}{" "}
          {r.is_test_entry && <Tag color="purple">test</Tag>}
        </span>
      ),
    },
    { title: "Year", dataIndex: "class_year", width: 80 },
    {
      title: "Campus",
      dataIndex: "campus",
      width: 90,
      render: (v: string) => <span className="capitalize">{v}</span>,
    },
    { title: "Plate", dataIndex: "plate", className: "font-mono" },
    {
      title: "Status",
      dataIndex: "status",
      render: (s: string) => <Tag color={STATUS_COLORS[s] || "default"}>{s}</Tag>,
    },
    {
      title: "Assigned",
      render: (_: unknown, r: Application) =>
        r.assigned_permit_type_label ? (
          <span>
            {r.assigned_permit_type_label}
            {r.assigned_lot ? ` · ${r.assigned_lot}` : ""}
          </span>
        ) : r.waitlist_position != null ? (
          <span>Waitlist #{r.waitlist_position}</span>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <div className="space-y-6">
      <Alert
        type="info"
        showIcon
        message="Student parking lottery"
        description={
          <p className="m-0">
            Single-entry waterfall lottery for resident students. Student portal:{" "}
            <a href={studentUrl} target="_blank" rel="noreferrer">
              {studentUrl}
            </a>
            . Commuters purchase directly from the same page.
          </p>
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <Button type="primary" onClick={createCycle} loading={busy}>
          New cycle
        </Button>
        {cycles.length > 0 && (
          <select
            className="border rounded px-3 py-1.5 text-sm"
            value={activeId || ""}
            onChange={(e) => setActiveId(e.target.value)}
          >
            {cycles.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.status}) — {c.application_count} apps
              </option>
            ))}
          </select>
        )}
      </div>

      {active && (
        <>
          <Card size="small">
            <div className="flex flex-wrap gap-6 mb-4">
              <Statistic title="Status" value={active.status} />
              <Statistic title="Applications" value={active.application_count} />
              {active.drawn_at && (
                <Statistic
                  title="Drawn"
                  value={new Date(active.drawn_at).toLocaleString()}
                />
              )}
              {results?.audit && (
                <>
                  <Statistic title="Selected" value={results.audit.selected_count} />
                  <Statistic title="Waitlisted" value={results.audit.waitlisted_count} />
                </>
              )}
            </div>
            <Space wrap>
              <Button
                disabled={busy || active.status === "open" || active.status === "drawn"}
                onClick={() =>
                  postAction(`/api/lottery-v2/cycles/${active.id}/open`, {
                    auto_draw_threshold: autoThreshold ? autoThreshold / 100 : null,
                    auto_draw_days: autoDays || null,
                  })
                }
              >
                Open applications
              </Button>
              <Button
                disabled={busy || active.status !== "open"}
                onClick={() => postAction(`/api/lottery-v2/cycles/${active.id}/close`)}
              >
                Close window
              </Button>
              <Button
                type="primary"
                disabled={busy || active.status === "drawn" || active.application_count === 0}
                onClick={confirmRun}
              >
                Run draw
              </Button>
            </Space>

            {active.status !== "open" && active.status !== "drawn" && (
              <div className="mt-4 p-3 bg-gray-50 rounded-md">
                <h4 className="text-sm font-medium mb-2">Auto-draw (fires whichever comes first)</h4>
                <div className="flex flex-wrap items-center gap-4">
                  <label className="flex items-center gap-2 text-sm">
                    <span>Capacity threshold:</span>
                    <InputNumber
                      min={100}
                      max={300}
                      step={5}
                      value={autoThreshold}
                      onChange={(v) => setAutoThreshold(v)}
                      addonAfter="%"
                      className="w-28"
                    />
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <span>Deadline:</span>
                    <InputNumber
                      min={1}
                      max={30}
                      value={autoDays}
                      onChange={(v) => setAutoDays(v)}
                      addonAfter="days"
                      className="w-28"
                    />
                  </label>
                </div>
                <p className="text-xs text-gray-500 mt-2 mb-0">
                  Draw runs automatically when any single tier's first-choice applications reach the threshold, OR the deadline passes — whichever is first.
                  Set to blank to disable either trigger.
                </p>
              </div>
            )}

            {active.status === "open" && (active.auto_draw_threshold || active.auto_draw_at) && (
              <div className="mt-4 p-3 bg-blue-50 rounded-md text-sm">
                <strong>Auto-draw active:</strong>{" "}
                {active.auto_draw_threshold && (
                  <span>triggers at {Math.round(active.auto_draw_threshold * 100)}% capacity</span>
                )}
                {active.auto_draw_threshold && active.auto_draw_at && <span> or </span>}
                {active.auto_draw_at && (
                  <span>deadline {new Date(active.auto_draw_at).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
                )}
              </div>
            )}

            <Collapse
              className="mt-4"
              items={[
                {
                  key: "test",
                  label: "Test tools",
                  children: (
                    <Space wrap>
                      <Button
                        disabled={busy || active.status === "drawn"}
                        onClick={async () => {
                          const data = await postAction(`/api/lottery-v2/cycles/${active.id}/seed`);
                          if (data) message.success(`Seeded ${data.seeded} test applicants`);
                        }}
                      >
                        Seed test data
                      </Button>
                      <Button
                        danger
                        disabled={busy}
                        onClick={() => {
                          modal.confirm({
                            title: "Remove all test data?",
                            content: "This will permanently delete all test entries from this cycle.",
                            okText: "Remove",
                            okButtonProps: { danger: true },
                            onOk: async () => {
                              const data = await postAction(`/api/lottery-v2/cycles/${active.id}/purge-test`);
                              if (data) message.success(`Removed ${data.purged} test entries`);
                            },
                          });
                        }}
                      >
                        Remove test data
                      </Button>
                      <Button
                        danger
                        disabled={busy || active.status !== "drawn"}
                        onClick={() => {
                          modal.confirm({
                            title: "Reset draw results?",
                            content: "Non-accepted applications return to pending so you can re-run.",
                            onOk: () => postAction(`/api/lottery-v2/cycles/${active.id}/reset`),
                          });
                        }}
                      >
                        Reset draw
                      </Button>
                    </Space>
                  ),
                },
              ]}
            />
          </Card>

          {results?.audit?.warnings && (
            <Alert type="warning" message={results.audit.warnings} showIcon />
          )}

          {results && Object.keys(results.by_tier).length > 0 && (
            <Card title="Placements by tier" size="small">
              <div className="space-y-4">
                {Object.entries(results.by_tier).map(([tier, list]) => (
                  <div key={tier}>
                    <h4 className="font-medium m-0 mb-2">
                      {tier}{" "}
                      <Tag>{list.length}</Tag>
                    </h4>
                    <ul className="text-sm text-gray-600 m-0 pl-5">
                      {list.map((a) => (
                        <li key={a.id}>
                          #{a.lottery_rank} {a.student_name} ({a.class_year}) → {a.assigned_lot || "—"}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
                {results.waitlisted.length > 0 && (
                  <div>
                    <h4 className="font-medium m-0 mb-2">
                      Waitlist <Tag color="blue">{results.waitlisted.length}</Tag>
                    </h4>
                    <ul className="text-sm text-gray-600 m-0 pl-5">
                      {results.waitlisted.map((a) => (
                        <li key={a.id}>
                          #{a.waitlist_position} {a.student_name} ({a.class_year})
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </Card>
          )}

          <Card title="All applications" size="small">
            <Table
              rowKey="id"
              size="small"
              loading={loading}
              dataSource={apps}
              columns={columns}
              pagination={{ pageSize: 20 }}
            />
          </Card>
        </>
      )}

      {!loading && cycles.length === 0 && (
        <Card>
          <p className="text-gray-500 mb-4">
            No staging cycles yet. Create one, open it, seed test data, then run the draw.
          </p>
          <Button type="primary" onClick={createCycle}>
            Create first cycle
          </Button>
        </Card>
      )}
    </div>
  );
}
