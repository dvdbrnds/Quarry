import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert, Button, Card, Collapse, Drawer, Input, Modal, Select, Space, Statistic, Table, Tag, App as AntApp, InputNumber,
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
  assigned_permit_type_price?: string | number | null;
  assigned_permit_type_lots?: string[];
  assigned_lot: string | null;
  offer_expires_at?: string | null;
  admin_notes?: string | null;
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
  live?: {
    selected_count: number;
    waitlisted_count: number;
    accepted_count: number;
    tier_capacity: Record<
      string,
      {
        max_capacity: number;
        active_permits: number;
        remaining_vs_active: number;
        unique_placed: number;
        over_capacity: boolean;
      }
    >;
  };
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
  superseded: "default",
};

type DeskFilter = "all" | "placed" | "accepted" | "offer" | "waitlist" | "mismatch" | "superseded";

function emailKey(app: Application): string {
  return (app.student_email || "").trim().toLowerCase() || app.id;
}

/** True if this application ranked (or was assigned) the given permit-type label. */
function wantsTier(app: Application, tierLabel: string): boolean {
  if (!tierLabel) return false;
  if (app.assigned_permit_type_label === tierLabel) return true;
  if (app.first_choice_label === tierLabel) return true;
  return (app.tier_preference_labels || []).includes(tierLabel);
}

function buildComplaintSummary(app: Application, siblings: Application[]): string {
  const prefs = app.tier_preference_labels || [];
  const first = prefs[0] || app.first_choice_label || "—";
  const ranked = prefs.length ? prefs.map((p, i) => `${i + 1}. ${p}`).join(" → ") : "—";
  const assigned = app.assigned_permit_type_label;
  const lots = (app.assigned_permit_type_lots || []).join(", ");
  const price =
    app.assigned_permit_type_price != null ? `$${Number(app.assigned_permit_type_price).toFixed(0)}` : null;

  let outcome: string;
  if (app.status === "accepted" && assigned) {
    outcome = `Accepted / active permit: ${assigned}${app.assigned_lot ? ` (lot ${app.assigned_lot})` : ""}${price ? ` · ${price}` : ""}`;
  } else if (app.status === "selected" && assigned) {
    outcome = `Offer outstanding: ${assigned}${app.assigned_lot ? ` (lot ${app.assigned_lot})` : ""}${price ? ` · ${price}` : ""}`;
    if (app.offer_expires_at) {
      outcome += ` · expires ${new Date(app.offer_expires_at).toLocaleDateString()}`;
    }
  } else if (app.status === "waitlisted") {
    outcome = `Waitlisted${app.waitlist_position != null ? ` #${app.waitlist_position}` : ""} — no seat offered yet`;
  } else if (app.status === "superseded") {
    outcome = "Superseded duplicate application (another row for this student holds the real offer)";
  } else {
    outcome = `Status: ${app.status}`;
  }

  let explanation: string;
  if (assigned && first === assigned) {
    explanation = `Their #1 choice was ${first}, which matches what they received.`;
  } else if (assigned && prefs.includes(assigned)) {
    const idx = prefs.indexOf(assigned) + 1;
    explanation =
      `Their #1 choice was ${first}. They received ${assigned} (#${idx} in their ranking). ` +
      `The lottery tries choices in order — a higher-ranked tier is offered when a seat remains.`;
  } else if (app.status === "waitlisted") {
    explanation =
      `They are on the waitlist. First choice was ${first}. A seat will be offered if capacity opens (decline/expiry) or an admin selects them.`;
  } else {
    explanation = `First choice was ${first}. Current outcome: ${outcome}.`;
  }

  if (assigned && lots) {
    explanation += ` Allowed lots for this permit: ${lots}.`;
  }

  const dupeNote =
    siblings.length > 1
      ? `\nDuplicate rows for this email: ${siblings.length} (statuses: ${siblings.map((s) => s.status).join(", ")}).`
      : "";

  return [
    `Student: ${app.student_name} <${app.student_email}>`,
    `Class of ${app.class_year} · ${app.campus} campus · plate ${app.plate || "—"}`,
    `Ranked preferences: ${ranked}`,
    `Outcome: ${outcome}`,
    `Explanation: ${explanation}${dupeNote}`,
  ].join("\n");
}

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
  const [selectForceCapacity, setSelectForceCapacity] = useState(false);
  const [capacityAudit, setCapacityAudit] = useState<any | null>(null);

  const [deskQuery, setDeskQuery] = useState("");
  const [deskFilter, setDeskFilter] = useState<DeskFilter>("all");
  const [deskTier, setDeskTier] = useState<string | null>(null);
  const [caseApp, setCaseApp] = useState<Application | null>(null);

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

  function confirmRestore(app: Application) {
    modal.confirm({
      title: `Restore ${app.student_name} to the waitlist?`,
      content:
        "Their application was marked superseded (inactive duplicate). This puts them back on the waitlist so they can receive an offer.",
      okText: "Restore to waitlist",
      onOk: async () => {
        const data = await postAction(`/api/lottery-v2/applications/${app.id}/restore-waitlist`);
        if (data) {
          message.success(
            `${app.student_name} restored — waitlist #${data.waitlist_position ?? "?"}`,
          );
        }
      },
    });
  }

  function openManualSelect(app: Application) {
    const prefs = app.tier_preferences || [];
    setSelectTarget(app);
    setSelectPermitId(prefs[0]);
    setSelectNotify(true);
    setSelectForceCapacity(false);
  }

  async function confirmManualSelect() {
    if (!selectTarget) return;
    const data = await postAction(`/api/lottery-v2/applications/${selectTarget.id}/manual-select`, {
      permit_type_id: selectPermitId || null,
      send_notification: selectNotify,
      allow_any_type: true,
      force_capacity: selectForceCapacity,
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

  const appsByEmail = useMemo(() => {
    const map = new Map<string, Application[]>();
    for (const a of apps) {
      const k = emailKey(a);
      const list = map.get(k) || [];
      list.push(a);
      map.set(k, list);
    }
    return map;
  }, [apps]);

  const winnerEmails = useMemo(() => {
    const set = new Set<string>();
    for (const a of apps) {
      if (a.status === "selected" || a.status === "accepted") set.add(emailKey(a));
    }
    return set;
  }, [apps]);

  /** Unique placed + true waitlist for the desk (hides phantom dupes). */
  const deskRows = useMemo(() => {
    const placed: Application[] = [];
    const seen = new Set<string>();
    for (const a of apps) {
      if (a.status !== "selected" && a.status !== "accepted") continue;
      const k = emailKey(a);
      if (seen.has(k)) continue;
      seen.add(k);
      placed.push(a);
    }
    const waitlisted = apps.filter(
      (a) => a.status === "waitlisted" && !winnerEmails.has(emailKey(a)),
    );
    return [...placed, ...waitlisted];
  }, [apps, winnerEmails]);

  const deskFiltered = useMemo(() => {
    const q = deskQuery.trim().toLowerCase();
    // Superseded rows are hidden unless searching or filtering for them
    const base =
      deskFilter === "superseded" || q
        ? [
            ...deskRows,
            ...apps.filter(
              (a) =>
                a.status === "superseded" &&
                !deskRows.some((d) => d.id === a.id),
            ),
          ]
        : deskRows;

    const rows = base.filter((a) => {
      if (deskTier) {
        if (a.status === "waitlisted" || a.status === "superseded") {
          if (!wantsTier(a, deskTier)) return false;
        } else if (a.assigned_permit_type_label !== deskTier) {
          return false;
        }
      }
      if (deskFilter === "placed" && !["selected", "accepted"].includes(a.status)) return false;
      if (deskFilter === "accepted" && a.status !== "accepted") return false;
      if (deskFilter === "offer" && a.status !== "selected") return false;
      if (deskFilter === "waitlist" && a.status !== "waitlisted") return false;
      if (deskFilter === "superseded" && a.status !== "superseded") return false;
      if (deskFilter === "mismatch") {
        const first = a.first_choice_label || a.tier_preference_labels?.[0];
        if (!first || !a.assigned_permit_type_label || first === a.assigned_permit_type_label) {
          return false;
        }
      }
      if (!q) return true;
      return (
        a.student_name.toLowerCase().includes(q) ||
        (a.student_email || "").toLowerCase().includes(q) ||
        (a.plate || "").toLowerCase().includes(q)
      );
    });

    if (deskFilter === "waitlist") {
      return [...rows].sort((a, b) => {
        const pa = a.waitlist_position ?? 10_000;
        const pb = b.waitlist_position ?? 10_000;
        return pa - pb;
      });
    }
    return rows;
  }, [deskRows, deskQuery, deskFilter, deskTier, apps]);

  const caseSiblings = useMemo(() => {
    if (!caseApp) return [];
    return appsByEmail.get(emailKey(caseApp)) || [caseApp];
  }, [caseApp, appsByEmail]);

  const tierChips = useMemo(() => {
    const caps = results?.live?.tier_capacity || {};
    const labels = Object.keys(caps).length
      ? Object.keys(caps)
      : Object.keys(results?.by_tier || {});
    const waitlisted = deskRows.filter((a) => a.status === "waitlisted");
    return labels.map((label) => {
      const cap = caps[label];
      const count =
        cap?.unique_placed ??
        (results?.by_tier?.[label]?.length ?? 0);
      const waitCount = waitlisted.filter((a) => wantsTier(a, label)).length;
      return { label, count, waitCount, cap };
    });
  }, [results, deskRows]);

  async function copyCaseSummary(app: Application) {
    const siblings = appsByEmail.get(emailKey(app)) || [app];
    const text = buildComplaintSummary(app, siblings);
    try {
      await navigator.clipboard.writeText(text);
      message.success("Complaint summary copied");
    } catch {
      modal.info({ title: "Complaint summary", content: <pre className="text-xs whitespace-pre-wrap m-0">{text}</pre> });
    }
  }

  const deskColumns = [
    {
      title: "#",
      width: 56,
      render: (_: unknown, r: Application) =>
        r.status === "waitlisted"
          ? r.waitlist_position != null
            ? `W${r.waitlist_position}`
            : "W"
          : r.lottery_rank != null
            ? `#${r.lottery_rank}`
            : "—",
    },
    {
      title: "Student",
      render: (_: unknown, r: Application) => (
        <button
          type="button"
          className="text-left bg-transparent border-0 p-0 cursor-pointer text-brand-primary hover:underline"
          onClick={() => setCaseApp(r)}
        >
          <div className="font-medium text-gray-900">{r.student_name}</div>
          <div className="text-xs text-gray-500">{r.student_email}</div>
        </button>
      ),
    },
    { title: "Year", dataIndex: "class_year", width: 72 },
    {
      title: "Wanted (#1)",
      render: (_: unknown, r: Application) => {
        const first = r.first_choice_label || r.tier_preference_labels?.[0] || "—";
        const mismatch =
          r.assigned_permit_type_label &&
          first !== "—" &&
          first !== r.assigned_permit_type_label;
        return (
          <span>
            {first}
            {mismatch && (
              <Tag color="orange" className="ml-1 m-0">
                got other
              </Tag>
            )}
          </span>
        );
      },
    },
    {
      title: "Got",
      render: (_: unknown, r: Application) =>
        r.assigned_permit_type_label ? (
          <span>
            {r.assigned_permit_type_label}
            {r.assigned_lot ? ` · ${r.assigned_lot}` : ""}
          </span>
        ) : r.status === "waitlisted" ? (
          <span className="text-gray-500">Waitlist</span>
        ) : (
          "—"
        ),
    },
    {
      title: "Status",
      dataIndex: "status",
      width: 110,
      render: (s: string) => <Tag color={STATUS_COLORS[s] || "default"}>{s}</Tag>,
    },
    {
      title: "",
      width: 150,
      render: (_: unknown, r: Application) => (
        <Space size={0} wrap>
          <Button type="link" size="small" className="px-1" onClick={() => setCaseApp(r)}>
            Case
          </Button>
          <Button type="link" size="small" className="px-1" onClick={() => copyCaseSummary(r)}>
            Copy
          </Button>
          {r.status === "waitlisted" && (
            <Button type="link" size="small" className="px-1" disabled={busy} onClick={() => openManualSelect(r)}>
              Select
            </Button>
          )}
          {r.status === "superseded" && (
            <Button type="link" size="small" className="px-1" disabled={busy} onClick={() => confirmRestore(r)}>
              Restore
            </Button>
          )}
        </Space>
      ),
    },
  ];

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
      width: 220,
      render: (_: unknown, r: Application) => {
        if (r.status === "waitlisted") {
          return (
            <Space size={0} wrap>
              <Button type="link" size="small" onClick={() => setCaseApp(r)}>
                Case
              </Button>
              <Button type="link" size="small" disabled={busy} onClick={() => confirmBump(r)}>
                Top
              </Button>
              <Button type="link" size="small" disabled={busy} onClick={() => openManualSelect(r)}>
                Select
              </Button>
            </Space>
          );
        }
        if (r.status === "superseded") {
          return (
            <Space size={0} wrap>
              <Button type="link" size="small" onClick={() => setCaseApp(r)}>
                Case
              </Button>
              <Button type="link" size="small" disabled={busy} onClick={() => confirmRestore(r)}>
                Restore
              </Button>
            </Space>
          );
        }
        if (r.status === "pending") {
          return (
            <Space size={0}>
              <Button type="link" size="small" onClick={() => setCaseApp(r)}>
                Case
              </Button>
              <Button type="link" size="small" disabled={busy} onClick={() => openManualSelect(r)}>
                Select
              </Button>
            </Space>
          );
        }
        return (
          <Button type="link" size="small" onClick={() => setCaseApp(r)}>
            Case
          </Button>
        );
      },
    },
  ];

  const firstChoiceDemand = Object.entries(
    apps.reduce<Record<string, number>>((acc, a) => {
      if (a.status === "superseded") return acc;
      const key = a.first_choice_label || "Unknown";
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {}),
  ).sort((a, b) => b[1] - a[1]);

  const showDesk = active && (active.status === "drawn" || (results && Object.keys(results.by_tier || {}).length > 0));

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
              {results?.live ? (
                <>
                  <Statistic title="Placed (unique)" value={results.live.selected_count} />
                  <Statistic title="Accepted" value={results.live.accepted_count} />
                  <Statistic title="True waitlist" value={results.live.waitlisted_count} />
                </>
              ) : results?.audit ? (
                <>
                  <Statistic title="Selected" value={results.audit.selected_count} />
                  <Statistic title="Waitlisted" value={results.audit.waitlisted_count} />
                </>
              ) : null}
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
              <Button
                disabled={busy || active.status !== "drawn"}
                onClick={() => {
                  if (!active) return;
                  modal.confirm({
                    title: `Repair placements for "${active.name}"?`,
                    content:
                      "Removes duplicate offers, clears phantom waitlist rows for people who already won, demotes excess selected offers over capacity (re-places into lower prefs when possible), then fills remaining open seats. Emails newly selected students by default. Does not revoke accepted/paid permits.",
                    okText: "Repair now",
                    onOk: async () => {
                      const data = await postAction(
                        `/api/lottery-v2/cycles/${active.id}/repair`,
                        { send_notifications: true },
                      );
                      if (data) {
                        message.success(
                          `Repair: ${data.newly_selected} newly selected, ${data.capacity_demoted ?? 0} over-cap demoted, ${data.superseded_waitlist ?? data.duplicates_demoted} duplicates cleared, ${data.remaining_waitlisted} still waitlisted`,
                        );
                      }
                    },
                  });
                }}
              >
                Repair waitlist
              </Button>
              <Button disabled={busy} onClick={loadCapacityAudit}>
                Capacity audit
              </Button>
              <Button
                disabled={busy || !activeId}
                onClick={() => activeId && loadDetail(activeId)}
              >
                Refresh
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

          {showDesk && (
            <Card
              title="Placement desk"
              size="small"
              extra={
                <span className="text-xs text-gray-500">
                  Search students · answer complaints · filter by seat
                </span>
              }
            >
              <Input.Search
                allowClear
                size="large"
                placeholder="Look up by name, email, or plate…"
                value={deskQuery}
                onChange={(e) => setDeskQuery(e.target.value)}
                className="mb-4 max-w-xl"
              />

              <div className="flex flex-wrap gap-2 mb-3">
                <Button
                  size="small"
                  type={!deskTier && deskFilter !== "waitlist" ? "primary" : "default"}
                  onClick={() => {
                    setDeskTier(null);
                    setDeskFilter("all");
                  }}
                >
                  All tiers
                </Button>
                {tierChips.map(({ label, count, waitCount, cap }) => {
                  const short = label.replace(/ Resident$/i, "");
                  const activeChip = deskTier === label && deskFilter === "waitlist";
                  return (
                    <Button
                      key={label}
                      size="small"
                      type={activeChip ? "primary" : "default"}
                      danger={!!cap?.over_capacity}
                      title={`Click to view the waitlist for ${short}`}
                      onClick={() => {
                        if (activeChip) {
                          setDeskTier(null);
                          setDeskFilter("all");
                        } else {
                          setDeskTier(label);
                          setDeskFilter("waitlist");
                        }
                      }}
                    >
                      {short}: {count} placed
                      {waitCount > 0 ? ` · ${waitCount} wait` : ""}
                      {cap && waitCount === 0 ? ` · ${cap.remaining_vs_active} open` : ""}
                    </Button>
                  );
                })}
                <Button
                  size="small"
                  type={!deskTier && deskFilter === "waitlist" ? "primary" : "default"}
                  onClick={() => {
                    setDeskTier(null);
                    setDeskFilter("waitlist");
                  }}
                >
                  All waitlists: {results?.live?.waitlisted_count ?? results?.waitlisted?.length ?? 0}
                </Button>
              </div>

              {deskFilter === "waitlist" && deskTier && (
                <Alert
                  type="info"
                  showIcon
                  className="mb-3"
                  message={`Waitlist for ${deskTier.replace(/ Resident$/i, "")}`}
                  description="Students still waiting who ranked this permit type (any preference). Ordered by waitlist position. Click the tier again to clear."
                />
              )}

              <div className="flex flex-wrap gap-2 mb-4">
                {(
                  [
                    ["all", "All"],
                    ["placed", "Placed"],
                    ["offer", "Open offers"],
                    ["accepted", "Accepted"],
                    ["waitlist", "Waitlist"],
                    ["superseded", "Superseded"],
                    ["mismatch", "Got ≠ #1"],
                  ] as [DeskFilter, string][]
                ).map(([key, label]) => (
                  <Tag
                    key={key}
                    color={deskFilter === key ? "blue" : "default"}
                    className="cursor-pointer px-2 py-0.5"
                    onClick={() => setDeskFilter(key)}
                  >
                    {label}
                  </Tag>
                ))}
              </div>

              <Table
                rowKey="id"
                size="small"
                loading={loading}
                dataSource={deskFiltered}
                columns={deskColumns}
                pagination={{ pageSize: 25, showSizeChanger: true }}
                locale={{
                  emptyText: deskQuery
                    ? "No students match that lookup"
                    : "No placements in this filter",
                }}
              />
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

      <Drawer
        title={caseApp ? caseApp.student_name : "Student case"}
        open={!!caseApp}
        onClose={() => setCaseApp(null)}
        width={440}
        extra={
          caseApp && (
            <Button type="primary" size="small" onClick={() => copyCaseSummary(caseApp)}>
              Copy reply
            </Button>
          )
        }
      >
        {caseApp && (
          <div className="space-y-4 text-sm">
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">Contact</div>
              <div>{caseApp.student_email}</div>
              <div className="text-gray-600">
                Class of {caseApp.class_year} · {caseApp.campus} · plate{" "}
                <span className="font-mono">{caseApp.plate || "—"}</span>
              </div>
            </div>

            <div>
              <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">Ranked preferences</div>
              <ol className="m-0 pl-5 space-y-1">
                {(caseApp.tier_preference_labels || []).map((label, i) => (
                  <li key={`${label}-${i}`}>
                    <strong>#{i + 1}</strong> {label}
                    {i === 0 && <Tag className="ml-1 m-0">first choice</Tag>}
                    {caseApp.assigned_permit_type_label === label && (
                      <Tag color="green" className="ml-1 m-0">
                        received
                      </Tag>
                    )}
                  </li>
                ))}
                {(caseApp.tier_preference_labels || []).length === 0 && <li>—</li>}
              </ol>
            </div>

            <div>
              <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">Outcome</div>
              <div className="flex flex-wrap items-center gap-2 mb-1">
                <Tag color={STATUS_COLORS[caseApp.status] || "default"}>{caseApp.status}</Tag>
                {caseApp.lottery_rank != null && <span>Rank #{caseApp.lottery_rank}</span>}
                {caseApp.waitlist_position != null && (
                  <span>Waitlist #{caseApp.waitlist_position}</span>
                )}
              </div>
              {caseApp.assigned_permit_type_label ? (
                <div>
                  <div className="font-medium">{caseApp.assigned_permit_type_label}</div>
                  <div className="text-gray-600">
                    Lot {caseApp.assigned_lot || "—"}
                    {caseApp.assigned_permit_type_price != null &&
                      ` · $${Number(caseApp.assigned_permit_type_price).toFixed(0)}`}
                  </div>
                  {(caseApp.assigned_permit_type_lots || []).length > 0 && (
                    <div className="text-gray-500 text-xs mt-1">
                      Allowed lots: {caseApp.assigned_permit_type_lots!.join(", ")}
                    </div>
                  )}
                  {caseApp.offer_expires_at && caseApp.status === "selected" && (
                    <div className="text-amber-700 text-xs mt-1">
                      Offer expires {new Date(caseApp.offer_expires_at).toLocaleString()}
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-gray-600">No permit assigned</div>
              )}
            </div>

            <div className="p-3 bg-gray-50 border rounded-md">
              <div className="text-xs uppercase tracking-wide text-gray-500 mb-2">Reply draft</div>
              <pre className="text-xs whitespace-pre-wrap m-0 font-sans text-gray-800">
                {buildComplaintSummary(caseApp, caseSiblings)}
              </pre>
            </div>

            {caseSiblings.length > 1 && (
              <div>
                <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">
                  All rows for this email ({caseSiblings.length})
                </div>
                <ul className="m-0 pl-5 space-y-1">
                  {caseSiblings.map((s) => (
                    <li key={s.id}>
                      <Tag color={STATUS_COLORS[s.status] || "default"}>{s.status}</Tag>{" "}
                      {s.assigned_permit_type_label || s.first_choice_label || "—"}
                      {s.id === caseApp.id ? " (this case)" : ""}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {caseApp.admin_notes && (
              <div>
                <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">Admin notes</div>
                <pre className="text-xs whitespace-pre-wrap m-0 text-gray-700 bg-amber-50 border border-amber-100 rounded p-2">
                  {caseApp.admin_notes}
                </pre>
              </div>
            )}

            {caseApp.status === "waitlisted" && (
              <Space>
                <Button disabled={busy} onClick={() => confirmBump(caseApp)}>
                  Top of waitlist
                </Button>
                <Button type="primary" disabled={busy} onClick={() => openManualSelect(caseApp)}>
                  Manual select
                </Button>
              </Space>
            )}
            {caseApp.status === "superseded" && (
              <Space>
                <Button type="primary" disabled={busy} onClick={() => confirmRestore(caseApp)}>
                  Restore to waitlist
                </Button>
              </Space>
            )}
          </div>
        )}
      </Drawer>

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
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={selectForceCapacity}
                onChange={(e) => setSelectForceCapacity(e.target.checked)}
              />
              <span>
                Force capacity
                <span className="block text-xs text-gray-500">
                  Offer even if this tier has no open seats left
                </span>
              </span>
            </label>
          </div>
        )}
      </Modal>
    </div>
  );
}
