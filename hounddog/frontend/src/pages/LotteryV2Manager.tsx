import { useCallback, useEffect, useState } from "react";
import {
  Alert, Button, Card, Collapse, Modal, Select, Space, Statistic, Table, Tag, App as AntApp, InputNumber,
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
  tier_preferences: string[];
  first_choice_label: string | null;
  tier_preference_labels: string[];
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
  const [autoThreshold, setAutoThreshold] = useState<number | null>(100);
  const [autoDays, setAutoDays] = useState<number | null>(3);
  const [selectTarget, setSelectTarget] = useState<Application | null>(null);
  const [selectPermitId, setSelectPermitId] = useState<string | undefined>(undefined);
  const [selectNotify, setSelectNotify] = useState(true);
  const [capacityAudit, setCapacityAudit] = useState<any | null>(null);

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

  function confirmBump(app: Application) {
    modal.confirm({
      title: `Move ${app.student_name} to #1 on the waitlist?`,
      content: "They will be offered next when a spot opens or when you manually select them.",
      okText: "Move to top",
      onOk: async () => {
        const data = await postAction(`/api/lottery-v2/applications/${app.id}/bump-waitlist`);
        if (data) message.success(`${app.student_name} is now #1 on the waitlist`);
      },
    });
  }

  function openManualSelect(app: Application) {
    const prefs = app.tier_preferences || [];
    setSelectTarget(app);
    setSelectPermitId(prefs[0]);
    setSelectNotify(true);
  }

  async function confirmManualSelect() {
    if (!selectTarget) return;
    const data = await postAction(`/api/lottery-v2/applications/${selectTarget.id}/manual-select`, {
      permit_type_id: selectPermitId || null,
      send_notification: selectNotify,
    });
    if (data) {
      message.success(
        `${selectTarget.student_name} selected` +
          (data.assigned_permit_type_label ? `: ${data.assigned_permit_type_label}` : ""),
      );
      setSelectTarget(null);
    }
  }

  async function loadCapacityAudit() {
    if (!activeId) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/lottery-v2/cycles/${activeId}/capacity-audit`, {
        headers: await authHeaders(),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Capacity audit failed");
      }
      setCapacityAudit(await res.json());
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setBusy(false);
    }
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
    {
      title: "1st Choice",
      dataIndex: "first_choice_label",
      render: (v: string | null, r: Application) => {
        const prefs = r.tier_preference_labels || [];
        if (!v && prefs.length === 0) return "—";
        return (
          <span title={prefs.length > 1 ? `Ranked: ${prefs.join(" → ")}` : undefined}>
            {v || prefs[0]}
            {prefs.length > 1 && (
              <span className="text-gray-400 text-xs ml-1">(+{prefs.length - 1})</span>
            )}
          </span>
        );
      },
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
    {
      title: "Actions",
      key: "actions",
      width: 200,
      render: (_: unknown, r: Application) => {
        if (r.status === "waitlisted") {
          return (
            <Space size={0} wrap>
              <Button type="link" size="small" disabled={busy} onClick={() => confirmBump(r)}>
                Top of waitlist
              </Button>
              <Button type="link" size="small" disabled={busy} onClick={() => openManualSelect(r)}>
                Select
              </Button>
            </Space>
          );
        }
        if (r.status === "pending") {
          return (
            <Button type="link" size="small" disabled={busy} onClick={() => openManualSelect(r)}>
              Select
            </Button>
          );
        }
        return null;
      },
    },
  ];

  const firstChoiceDemand = Object.entries(
    apps.reduce<Record<string, number>>((acc, a) => {
      const key = a.first_choice_label || "Unknown";
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {}),
  ).sort((a, b) => b[1] - a[1]);

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
              <Button disabled={busy} onClick={loadCapacityAudit}>
                Capacity audit
              </Button>
            </Space>

            {capacityAudit && (
              <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-md text-sm space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="font-medium m-0">Capacity audit</h4>
                  <Button type="link" size="small" onClick={() => setCapacityAudit(null)}>Dismiss</Button>
                </div>
                <p className="m-0 text-gray-600">
                  Active on lot Q: <strong>{capacityAudit.lot_active_permits?.Q ?? "—"}</strong>
                  {" · "}
                  Active on lot U: <strong>{capacityAudit.lot_active_permits?.U ?? "—"}</strong>
                  {" · "}
                  Duplicate emails: <strong>{capacityAudit.duplicates?.emails_with_multiple_apps ?? 0}</strong>
                  {" "}(+{capacityAudit.duplicates?.extra_app_rows ?? 0} extra rows)
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="text-left border-b">
                        <th className="py-1 pr-2">Tier</th>
                        <th className="py-1 pr-2">Max</th>
                        <th className="py-1 pr-2">Active</th>
                        <th className="py-1 pr-2">Remaining</th>
                        <th className="py-1 pr-2">1st choice</th>
                        <th className="py-1 pr-2">Any pref</th>
                        <th className="py-1 pr-2">Selected</th>
                        <th className="py-1 pr-2">WL w/ pref</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(capacityAudit.tiers || []).map((t: any) => (
                        <tr key={t.code} className="border-b border-amber-100">
                          <td className="py-1 pr-2">{t.label || t.code}</td>
                          <td className="py-1 pr-2">{t.max_capacity}</td>
                          <td className="py-1 pr-2">{t.active_permits}</td>
                          <td className="py-1 pr-2">{t.remaining_formula}</td>
                          <td className="py-1 pr-2">{t.apps_first_choice}</td>
                          <td className="py-1 pr-2">{t.apps_with_any_pref}</td>
                          <td className="py-1 pr-2">
                            {t.selected_or_accepted}
                            {t.duplicate_emails_in_selected > 0 && (
                              <span className="text-red-600"> (−{t.duplicate_emails_in_selected} dup)</span>
                            )}
                          </td>
                          <td className="py-1 pr-2">{t.waitlisted_with_pref}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <strong>South / U</strong>
                    <ul className="m-0 mt-1 pl-4 text-gray-700">
                      <li>Apps: {capacityAudit.south?.total_apps} ({capacityAudit.south?.unique_emails} unique emails)</li>
                      <li>With U in prefs: {capacityAudit.south?.with_u_in_prefs}</li>
                      <li>Selected to U: {capacityAudit.south?.selected_to_u}</li>
                      <li>Selected elsewhere: {capacityAudit.south?.selected_to_other}</li>
                      <li>Waitlisted with U in prefs: {capacityAudit.south?.waitlisted_with_u_in_prefs}</li>
                    </ul>
                  </div>
                  <div>
                    <strong>North / Q</strong>
                    <ul className="m-0 mt-1 pl-4 text-gray-700">
                      <li>With Q in prefs: {capacityAudit.north_q?.with_q_in_prefs}</li>
                      <li>Ranked Q first: {capacityAudit.north_q?.ranked_q_first}</li>
                      <li>Selected to Q: {capacityAudit.north_q?.selected_to_q}</li>
                      <li>Waitlisted with Q in prefs: {capacityAudit.north_q?.waitlisted_with_q_in_prefs}</li>
                    </ul>
                  </div>
                </div>
              </div>
            )}

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
                        <li key={a.id} className="flex flex-wrap items-center gap-2 py-0.5">
                          <span>
                            #{a.waitlist_position} {a.student_name} ({a.class_year})
                            {a.first_choice_label ? ` · ${a.first_choice_label}` : ""}
                          </span>
                          <Button type="link" size="small" className="px-0" disabled={busy} onClick={() => confirmBump(a)}>
                            Top
                          </Button>
                          <Button type="link" size="small" className="px-0" disabled={busy} onClick={() => openManualSelect(a)}>
                            Select
                          </Button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </Card>
          )}

          <Card title="All applications" size="small">
            {firstChoiceDemand.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-3">
                {firstChoiceDemand.map(([label, count]) => (
                  <Tag key={label} color="blue">
                    {label}: {count} first-choice
                  </Tag>
                ))}
              </div>
            )}
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

      <Modal
        title={selectTarget ? `Manually select ${selectTarget.student_name}` : "Manual select"}
        open={!!selectTarget}
        onCancel={() => setSelectTarget(null)}
        onOk={confirmManualSelect}
        okText="Select & offer"
        confirmLoading={busy}
        destroyOnClose
      >
        {selectTarget && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600 m-0">
              Places them into remaining capacity from their ranked preferences and starts the offer window.
            </p>
            <div>
              <div className="text-sm font-medium mb-1">Permit type</div>
              <Select
                className="w-full"
                value={selectPermitId}
                onChange={setSelectPermitId}
                options={(selectTarget.tier_preferences || []).map((id, i) => ({
                  value: id,
                  label: `${i + 1}. ${selectTarget.tier_preference_labels?.[i] || id}`,
                }))}
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={selectNotify}
                onChange={(e) => setSelectNotify(e.target.checked)}
              />
              Email the student their offer
            </label>
          </div>
        )}
      </Modal>
    </div>
  );
}
