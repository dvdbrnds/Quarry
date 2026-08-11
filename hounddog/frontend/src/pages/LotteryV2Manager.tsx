import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert, Badge, Button, Card, Collapse, Divider, Drawer, Input, Modal, Segmented, Select, Space, Statistic, Table, Tag, Tooltip, App as AntApp, InputNumber,
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
  is_upgrade?: boolean;
  existing_permit_type_id?: string | null;
  upgrade_credit?: number | null;
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

function shortenTierLabel(label: string): string {
  return label
    .replace(/ Resident$/i, "")
    .replace(/Guaranteed/g, "Guar.")
    .replace(/Premium/g, "Prem.")
    .replace(/Extended/g, "Ext.")
    .replace(/\(Undergrad\)/g, "(UG)")
    .replace(/\(Grad\)/g, "(G)");
}

type DeskView = "desk" | "applications" | "queue";

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
  const [dupesReport, setDupesReport] = useState<any | null>(null);

  const [deskQuery, setDeskQuery] = useState("");
  const [deskFilter, setDeskFilter] = useState<DeskFilter>("all");
  const [deskTier, setDeskTier] = useState<string | null>(null);
  const [caseApp, setCaseApp] = useState<Application | null>(null);
  const [recoverOpen, setRecoverOpen] = useState(false);
  const [recoverEmail, setRecoverEmail] = useState("");
  const [recoverResults, setRecoverResults] = useState<Application[] | null>(null);
  const [recoverLoading, setRecoverLoading] = useState(false);

  const [addWaitlistOpen, setAddWaitlistOpen] = useState(false);
  const [addWaitlistEmail, setAddWaitlistEmail] = useState("");
  const [addWaitlistCampus, setAddWaitlistCampus] = useState("north");
  const [addWaitlistTiers, setAddWaitlistTiers] = useState<{ id: string; label: string; price: number }[]>([]);
  const [addWaitlistTierId, setAddWaitlistTierId] = useState<string | undefined>(undefined);
  const [addWaitlistLoading, setAddWaitlistLoading] = useState(false);

  const [upgradeTarget, setUpgradeTarget] = useState<Application | null>(null);
  const [upgradeTierId, setUpgradeTierId] = useState<string | undefined>(undefined);
  const [upgradeNotify, setUpgradeNotify] = useState(true);
  const [upgradeTiers, setUpgradeTiers] = useState<{ id: string; label: string; price: number }[]>([]);
  const [upgradeLoading, setUpgradeLoading] = useState(false);

  const [tierDetail, setTierDetail] = useState<any | null>(null);
  const [tierDetailLoading, setTierDetailLoading] = useState(false);
  const [deskView, setDeskView] = useState<DeskView>("desk");

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
        "Applicants will be sorted by class year then timestamp, then placed into their ranked tiers. Selected and waitlisted students will be emailed.",
      okText: "Run draw & email",
      onOk: async () => {
        const data = await postAction(`/api/lottery-v2/cycles/${active.id}/run`, {
          include_test_entries: true,
          send_notifications: true,
        });
        if (data) {
          message.success(
            `Draw complete: ${data.selected_count} selected, ${data.waitlisted_count} waitlisted`,
          );
        }
      },
    });
  }

  function confirmNotifyWaitlist() {
    if (!active) return;
    const waitCount = apps.filter((a) => a.status === "waitlisted").length;
    modal.confirm({
      title: `Email ${waitCount} waitlisted student${waitCount === 1 ? "" : "s"}?`,
      content:
        "Sends each waitlisted applicant their current waitlist position. Use this if the draw ran without notifications.",
      okText: "Send waitlist emails",
      onOk: async () => {
        const data = await postAction(`/api/lottery-v2/cycles/${active.id}/notify-waitlist`);
        if (data) {
          message.success(
            `Waitlist emails: ${data.sent} sent` +
              (data.failed ? `, ${data.failed} failed` : "") +
              (data.skipped ? `, ${data.skipped} skipped` : ""),
          );
        }
      },
    });
  }

  function confirmAdvanceWaitlist() {
    if (!active) return;
    modal.confirm({
      title: "Advance waitlist?",
      content:
        "Expires any overdue offers and promotes the next waitlisted applicant(s) into open seats. This ignores the auto-advance toggle.",
      okText: "Advance now",
      onOk: async () => {
        const data = await postAction(`/api/lottery-v2/cycles/${active.id}/advance-waitlist`);
        if (data) {
          message.success(
            `Expired ${data.expired} offer(s), advanced ${data.advanced} from waitlist`,
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

  async function recoverSearch() {
    if (!recoverEmail.trim()) return;
    setRecoverLoading(true);
    try {
      const res = await fetch(
        `/api/lottery-v2/applications/search?email=${encodeURIComponent(recoverEmail.trim())}`,
        { headers: await authHeaders() },
      );
      if (!res.ok) throw new Error("Search failed");
      const data: Application[] = await res.json();
      setRecoverResults(data);
      if (data.length === 0) message.info("No applications found for that email");
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setRecoverLoading(false);
    }
  }

  async function loadAddWaitlistTiers(campus: string) {
    try {
      const res = await fetch(`/api/lottery-v2/eligible-tiers?campus=${campus}`, { headers: await authHeaders() });
      if (res.ok) {
        const tiers = await res.json();
        setAddWaitlistTiers(tiers.map((t: any) => ({ id: t.id, label: t.label, price: Number(t.price) })));
        setAddWaitlistTierId(tiers[0]?.id);
      }
    } catch { /* ignore */ }
  }

  async function confirmAddWaitlist() {
    if (!addWaitlistEmail.trim() || !addWaitlistTierId) return;
    setAddWaitlistLoading(true);
    try {
      const res = await fetch("/api/lottery-v2/applications/admin-add", {
        method: "POST",
        headers: { ...(await authHeaders()), "Content-Type": "application/json" },
        body: JSON.stringify({
          email: addWaitlistEmail.trim(),
          permit_type_id: addWaitlistTierId,
          campus: addWaitlistCampus,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to add");
      message.success(`${data.student_name} added to waitlist at position ${data.waitlist_position}`);
      setAddWaitlistOpen(false);
      if (activeId) loadDetail(activeId);
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setAddWaitlistLoading(false);
    }
  }

  async function openUpgradeModal(app: Application) {
    setUpgradeTarget(app);
    setUpgradeNotify(true);
    setUpgradeTierId(undefined);
    try {
      const res = await fetch("/api/permit-types?all=true", { headers: await authHeaders() });
      if (res.ok) {
        const types: any[] = await res.json();
        const currentPrice = Number(app.assigned_permit_type_price || 0);
        const higher = types
          .filter((t: any) => t.is_active && Number(t.price) > currentPrice)
          .map((t: any) => ({ id: t.id, label: t.label, price: Number(t.price) }))
          .sort((a, b) => a.price - b.price);
        setUpgradeTiers(higher);
        if (higher.length) setUpgradeTierId(higher[0].id);
      }
    } catch { /* ignore */ }
  }

  async function confirmUpgrade() {
    if (!upgradeTarget || !upgradeTierId) return;
    setUpgradeLoading(true);
    try {
      const res = await fetch(`/api/lottery-v2/applications/${upgradeTarget.id}/admin-upgrade`, {
        method: "POST",
        headers: { ...(await authHeaders()), "Content-Type": "application/json" },
        body: JSON.stringify({
          permit_type_id: upgradeTierId,
          send_notification: upgradeNotify,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upgrade failed");
      if (data.status === "upgraded") {
        message.success(`${upgradeTarget.student_name} upgraded to ${data.new_type} — no charge`);
      } else {
        message.success(
          `Upgrade to ${data.new_type} initiated — $${data.charge_amount} payment link sent`,
        );
      }
      setUpgradeTarget(null);
      setCaseApp(null);
      if (activeId) loadDetail(activeId);
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setUpgradeLoading(false);
    }
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

  async function loadTierDetail(code: string) {
    setTierDetailLoading(true);
    try {
      const res = await fetch(`/api/lottery-v2/tier-detail/${code}`, {
        headers: await authHeaders(),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to load tier detail");
      }
      setTierDetail(await res.json());
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setTierDetailLoading(false);
    }
  }

  async function loadDupesReport() {
    if (!activeId) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/lottery-v2/cycles/${activeId}/duplicates-report`, {
        headers: await authHeaders(),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Duplicates report failed");
      }
      setDupesReport(await res.json());
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

  const deskFilterCounts = useMemo(() => {
    const matchesTier = (a: Application) => {
      if (!deskTier) return true;
      if (a.status === "waitlisted" || a.status === "superseded") return wantsTier(a, deskTier);
      return a.assigned_permit_type_label === deskTier;
    };
    const superseded = apps.filter((a) => a.status === "superseded" && !deskRows.some((d) => d.id === a.id));
    const all = [...deskRows, ...superseded].filter(matchesTier);
    const base = deskRows.filter(matchesTier);
    const placed = base.filter((a) => ["selected", "accepted"].includes(a.status)).length;
    const offer = base.filter((a) => a.status === "selected").length;
    const accepted = base.filter((a) => a.status === "accepted").length;
    const waitlist = base.filter((a) => a.status === "waitlisted").length;
    const sup = superseded.filter(matchesTier).length;
    const mismatch = base.filter((a) => {
      const first = a.first_choice_label || a.tier_preference_labels?.[0];
      return first && a.assigned_permit_type_label && first !== a.assigned_permit_type_label;
    }).length;
    return { all: all.length, placed, offer, accepted, waitlist, superseded: sup, mismatch } as Record<DeskFilter, number>;
  }, [apps, deskRows, deskTier]);

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
      ellipsis: true,
      render: (_: unknown, r: Application) => {
        const first = r.first_choice_label || r.tier_preference_labels?.[0] || "—";
        const mismatch =
          r.assigned_permit_type_label &&
          first !== "—" &&
          first !== r.assigned_permit_type_label;
        return (
          <Tooltip title={first !== "—" ? first : undefined}>
            <span className="whitespace-nowrap">
              {shortenTierLabel(first)}
              {mismatch && (
                <Tag color="orange" className="ml-1 m-0">
                  got other
                </Tag>
              )}
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: "Got",
      ellipsis: true,
      render: (_: unknown, r: Application) =>
        r.assigned_permit_type_label ? (
          <Tooltip title={r.assigned_permit_type_label}>
            <span className="whitespace-nowrap">
              {shortenTierLabel(r.assigned_permit_type_label)}
              {r.assigned_lot ? ` · ${r.assigned_lot}` : ""}
            </span>
          </Tooltip>
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
      render: (s: string, r: Application) => (
        <span>
          <Tag color={STATUS_COLORS[s] || "default"}>{s}</Tag>
          {r.is_upgrade && <Tag color="purple">upgrade</Tag>}
        </span>
      ),
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
      ellipsis: true,
      render: (v: string | null, r: Application) => {
        const prefs = r.tier_preference_labels || [];
        if (!v && prefs.length === 0) return "—";
        const full = v || prefs[0];
        return (
          <Tooltip title={prefs.length > 1 ? `Ranked: ${prefs.join(" → ")}` : full}>
            <span className="whitespace-nowrap">
              {shortenTierLabel(full)}
              {prefs.length > 1 && (
                <span className="text-gray-400 text-xs ml-1">(+{prefs.length - 1})</span>
              )}
            </span>
          </Tooltip>
        );
      },
    },
    { title: "Plate", dataIndex: "plate", className: "font-mono" },
    {
      title: "Status",
      dataIndex: "status",
      render: (s: string, r: Application) => (
        <span>
          <Tag color={STATUS_COLORS[s] || "default"}>{s}</Tag>
          {r.is_upgrade && <Tag color="purple">upgrade</Tag>}
        </span>
      ),
    },
    {
      title: "Assigned",
      ellipsis: true,
      render: (_: unknown, r: Application) =>
        r.assigned_permit_type_label ? (
          <Tooltip title={r.assigned_permit_type_label}>
            <span className="whitespace-nowrap">
              {shortenTierLabel(r.assigned_permit_type_label)}
              {r.assigned_lot ? ` · ${r.assigned_lot}` : ""}
            </span>
          </Tooltip>
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
              <Button type="link" size="small" disabled={busy} onClick={() => openManualSelect(r)}>
                Select
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

  const waitlistByTier = useMemo(() => {
    const waitlisted = deskRows.filter((a) => a.status === "waitlisted");
    const groups: { label: string; short: string; cap: any; students: Application[] }[] = [];
    const labels = tierChips.map((t) => t.label);
    for (const tierLabel of labels) {
      const chip = tierChips.find((t) => t.label === tierLabel);
      const students = waitlisted
        .filter((a) => wantsTier(a, tierLabel))
        .sort((a, b) => (a.waitlist_position ?? 10_000) - (b.waitlist_position ?? 10_000));
      if (students.length === 0) continue;
      groups.push({
        label: tierLabel,
        short: tierLabel.replace(/ Resident$/i, ""),
        cap: chip?.cap,
        students,
      });
    }
    return groups;
  }, [deskRows, tierChips]);

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
            <div className="flex flex-wrap items-end gap-4">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-1">Lifecycle</div>
                <Space size={4}>
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
              </div>
              <Divider type="vertical" className="h-8 self-end" />
              <div>
                <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-1">Waitlist</div>
                <Space size={4}>
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
                    Repair
                  </Button>
                  <Button
                    disabled={busy || active.status !== "drawn"}
                    onClick={confirmNotifyWaitlist}
                  >
                    Email waitlist
                  </Button>
                  <Button
                    disabled={busy || active.status !== "drawn"}
                    onClick={confirmAdvanceWaitlist}
                  >
                    Advance
                  </Button>
                </Space>
              </div>
              <Divider type="vertical" className="h-8 self-end" />
              <div>
                <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-1">Students</div>
                <Space size={4}>
                  <Button onClick={() => { setRecoverOpen(true); setRecoverResults(null); setRecoverEmail(""); }}>
                    Recover
                  </Button>
                  <Button onClick={() => { setAddWaitlistOpen(true); setAddWaitlistEmail(""); loadAddWaitlistTiers("north"); setAddWaitlistCampus("north"); }}>
                    Add to waitlist
                  </Button>
                </Space>
              </div>
              <Divider type="vertical" className="h-8 self-end" />
              <div>
                <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-1">Reports</div>
                <Space size={4}>
                  <Button disabled={busy} onClick={loadCapacityAudit}>
                    Capacity audit
                  </Button>
                  <Button disabled={busy} onClick={loadDupesReport}>
                    Duplicates
                  </Button>
                </Space>
              </div>
              <Button
                className="ml-auto"
                disabled={busy || !activeId}
                onClick={() => activeId && loadDetail(activeId)}
              >
                Refresh
              </Button>
            </div>

            {capacityAudit && (
              <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded-md text-sm space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="font-medium m-0">
                    Capacity audit
                    {capacityAudit.generated_at && (
                      <span className="font-normal text-xs text-amber-700 ml-2">
                        as of {new Date(capacityAudit.generated_at).toLocaleString()}
                      </span>
                    )}
                  </h4>
                  <div className="flex gap-2">
                    <Button size="small" onClick={() => {
                      const tiers = capacityAudit.tiers || [];
                      const yearKeys = ["Senior", "Junior", "Sophomore", "Freshman", "Other", "Unknown"];
                      const headers = ["Tier", "Capacity", "Active Permits", "Pending Payment", "Committed", "Over By", "Truly Open", "Waitlisted",
                        ...yearKeys, "Resident", "Commuter", "Off Campus", "RA/RD", "Employee", "ABSN", "Auto-advance"];
                      const rows = tiers.filter((t: any) => !t.missing).map((t: any) => [
                        t.label || t.code,
                        t.max_capacity,
                        t.active_permits,
                        t.selected_pending_payment,
                        t.committed,
                        t.over_capacity_by,
                        t.truly_open,
                        t.waitlisted_with_pref,
                        ...yearKeys.map(k => t.class_year_breakdown?.[k] || 0),
                        t.housing_breakdown?.Resident || 0,
                        t.housing_breakdown?.Commuter || 0,
                        t.housing_breakdown?.["Off Campus Release"] || 0,
                        t.res_life_staff_count || 0,
                        t.employee_count || 0,
                        t.accel_nursing_count || 0,
                        t.auto_advance_waitlist === false ? "OFF" : "ON",
                      ]);
                      const csv = [headers, ...rows].map(r => r.map((v: any) => `"${v}"`).join(",")).join("\n");
                      const blob = new Blob([csv], { type: "text/csv" });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = `capacity-audit-${new Date().toISOString().slice(0, 10)}.csv`;
                      a.click();
                      URL.revokeObjectURL(url);
                    }}>Export CSV</Button>
                    <Button type="link" size="small" onClick={() => setCapacityAudit(null)}>Dismiss</Button>
                  </div>
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
                      <tr className="text-left border-b font-medium">
                        <th className="py-1.5 pr-3">Tier</th>
                        <th className="py-1.5 pr-3 text-right">Capacity</th>
                        <th className="py-1.5 pr-3 text-right">Active permits</th>
                        <th className="py-1.5 pr-3 text-right">Pending payment</th>
                        <th className="py-1.5 pr-3 text-right">= Committed</th>
                        <th className="py-1.5 pr-3 text-right">Truly open</th>
                        <th className="py-1.5 pr-3 text-right">Waitlisted</th>
                        <th className="py-1.5 pr-3">Class year</th>
                        <th className="py-1.5 pr-3">SIS</th>
                        <th className="py-1.5 pr-3">Auto-advance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(capacityAudit.tiers || []).map((t: any) => (
                        <tr key={t.code} className={`border-b border-amber-100 ${t.over_capacity_by > 0 ? "bg-red-50" : ""}`}>
                          <td className="py-1.5 pr-3 font-medium">
                            <Button type="link" size="small" className="p-0 h-auto text-xs font-medium" onClick={() => loadTierDetail(t.code)}>
                              {t.label || t.code}
                            </Button>
                          </td>
                          <td className="py-1.5 pr-3 text-right">{t.max_capacity}</td>
                          <td className="py-1.5 pr-3 text-right">{t.active_permits}</td>
                          <td className="py-1.5 pr-3 text-right">
                            <span className="text-blue-600 font-medium">{t.selected_pending_payment}</span>
                          </td>
                          <td className="py-1.5 pr-3 text-right font-bold">
                            {t.committed}
                            {t.over_capacity_by > 0 && (
                              <span className="text-red-600 ml-1">(+{t.over_capacity_by} over)</span>
                            )}
                          </td>
                          <td className="py-1.5 pr-3 text-right">
                            {t.truly_open > 0
                              ? <span className="text-green-600 font-medium">{t.truly_open}</span>
                              : <span className="text-red-500 font-medium">0</span>}
                          </td>
                          <td className="py-1.5 pr-3 text-right">{t.waitlisted_with_pref}</td>
                          <td className="py-1.5 pr-3 text-[10px] text-gray-600 whitespace-nowrap">
                            {t.class_year_breakdown && Object.keys(t.class_year_breakdown).length > 0
                              ? ["Senior", "Junior", "Sophomore", "Freshman", "Other", "Unknown"]
                                  .filter(k => t.class_year_breakdown[k])
                                  .map(k => `${k.slice(0, 2)}: ${t.class_year_breakdown[k]}`)
                                  .join(" · ")
                              : "—"}
                          </td>
                          <td className="py-1.5 pr-3 text-[10px] text-gray-600 whitespace-nowrap">
                            {t.housing_breakdown && Object.keys(t.housing_breakdown).length > 0
                              ? [
                                  ...Object.entries(t.housing_breakdown as Record<string, number>).map(([k, v]) => `${k.slice(0, 3)}: ${v}`),
                                  ...(t.res_life_staff_count > 0 ? [`RA: ${t.res_life_staff_count}`] : []),
                                  ...(t.employee_count > 0 ? [`Emp: ${t.employee_count}`] : []),
                                  ...(t.accel_nursing_count > 0 ? [`ABSN: ${t.accel_nursing_count}`] : []),
                                ].join(" · ")
                              : "—"}
                          </td>
                          <td className="py-1.5 pr-3">
                            {t.auto_advance_waitlist === false
                              ? <Tag color="red" className="text-[10px]">OFF</Tag>
                              : <Tag color="green" className="text-[10px]">ON</Tag>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="text-[11px] text-gray-500 mt-2 m-0">
                    <strong>Committed</strong> = Active permits + Pending payment offers. <strong>Truly open</strong> = Capacity − Committed. A negative means over-committed.
                  </p>
                </div>
                {(capacityAudit.stale_count > 0) && (
                  <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded text-xs">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <strong className="text-red-700">
                          {capacityAudit.stale_count} stale entr{capacityAudit.stale_count === 1 ? "y" : "ies"} inflating committed counts:
                        </strong>
                        {capacityAudit.stale_permits?.length > 0 && (
                          <>
                            <div className="mt-1 font-semibold text-red-600">Duplicate active permits:</div>
                            <ul className="mt-0.5 mb-0 pl-4 space-y-0.5">
                              {capacityAudit.stale_permits.map((s: any) => (
                                <li key={s.email}>{s.email} — {s.active_count} active: {s.types?.join(", ")}</li>
                              ))}
                            </ul>
                          </>
                        )}
                        {capacityAudit.stale_selections?.length > 0 && (
                          <>
                            <div className="mt-1 font-semibold text-red-600">Stale &quot;selected&quot; offers (student already has permit):</div>
                            <ul className="mt-0.5 mb-0 pl-4 space-y-0.5">
                              {capacityAudit.stale_selections.map((s: any) => (
                                <li key={s.email}>{s.email} ({s.name}) — {s.tier}</li>
                              ))}
                            </ul>
                          </>
                        )}
                      </div>
                      <Button
                        danger
                        size="small"
                        disabled={busy}
                        onClick={async () => {
                          setBusy(true);
                          try {
                            const res = await fetch("/api/lottery-v2/cleanup-stale-permits", {
                              method: "POST",
                              headers: await authHeaders(),
                            });
                            const data = await res.json();
                            if (!res.ok) throw new Error(data.detail || "Cleanup failed");
                            message.success(
                              `Fixed: ${data.revoked_permits} stale permit(s), ${data.cleared_selections} stale selection(s)`
                            );
                            if (activeId) loadCapacityAudit();
                          } catch (e: any) {
                            message.error(e.message);
                          } finally {
                            setBusy(false);
                          }
                        }}
                      >
                        Fix now
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {dupesReport && (
              <div className="mt-4 p-3 bg-purple-50 border border-purple-200 rounded-md text-sm space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="font-medium m-0">Duplicates report — {dupesReport.cycle_name}</h4>
                  <Button type="link" size="small" onClick={() => setDupesReport(null)}>Dismiss</Button>
                </div>

                <div className="overflow-x-auto">
                  <h5 className="text-xs font-semibold uppercase text-gray-500 mt-2 mb-1">Per-tier capacity impact</h5>
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="text-left border-b">
                        <th className="py-1.5 pr-3">Tier</th>
                        <th className="py-1.5 pr-3 text-right">Cap</th>
                        <th className="py-1.5 pr-3 text-right">Active</th>
                        <th className="py-1.5 pr-3 text-right">Selected</th>
                        <th className="py-1.5 pr-3 text-right">Committed</th>
                        <th className="py-1.5 pr-3 text-right">Over by</th>
                        <th className="py-1.5 pr-3 text-right">Dupe emails</th>
                        <th className="py-1.5 pr-3">Already have permit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(dupesReport.tiers || []).map((t: any) => (
                        <tr key={t.code} className={`border-b ${t.over_capacity_by > 0 ? "bg-red-50" : ""}`}>
                          <td className="py-1.5 pr-3 font-medium">{t.label}</td>
                          <td className="py-1.5 pr-3 text-right">{t.max_capacity}</td>
                          <td className="py-1.5 pr-3 text-right">{t.active_permits}</td>
                          <td className="py-1.5 pr-3 text-right">{t.selected_offers}</td>
                          <td className="py-1.5 pr-3 text-right font-bold">{t.committed}</td>
                          <td className="py-1.5 pr-3 text-right">
                            {t.over_capacity_by > 0
                              ? <span className="text-red-600 font-bold">+{t.over_capacity_by}</span>
                              : <span className="text-green-600">0</span>}
                          </td>
                          <td className="py-1.5 pr-3 text-right">
                            {t.duplicate_emails_in_tier > 0
                              ? <span className="text-red-600">{t.duplicate_emails_in_tier}</span>
                              : "0"}
                          </td>
                          <td className="py-1.5 pr-3 text-xs">
                            {(t.selected_but_already_have_permit || []).length > 0
                              ? <span className="text-red-600">{t.selected_but_already_have_permit.join(", ")}</span>
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {dupesReport.duplicates?.length > 0 && (
                  <div>
                    <h5 className="text-xs font-semibold uppercase text-gray-500 mt-3 mb-1">
                      Students with multiple offers ({dupesReport.total_duplicate_students})
                    </h5>
                    <div className="max-h-64 overflow-y-auto border rounded">
                      <table className="w-full text-xs border-collapse">
                        <thead className="sticky top-0 bg-purple-50">
                          <tr className="text-left border-b">
                            <th className="py-1 px-2">Email</th>
                            <th className="py-1 px-2">Name</th>
                            <th className="py-1 px-2">Status</th>
                            <th className="py-1 px-2">Tier</th>
                            <th className="py-1 px-2">Lot</th>
                          </tr>
                        </thead>
                        <tbody>
                          {dupesReport.duplicates.map((d: any) =>
                            d.applications.map((app: any, i: number) => (
                              <tr key={app.id} className={`border-b ${i === 0 ? "border-t-2 border-t-purple-300" : ""}`}>
                                {i === 0 && (
                                  <td className="py-1 px-2 font-medium align-top" rowSpan={d.applications.length}>
                                    {d.email}
                                  </td>
                                )}
                                <td className="py-1 px-2">{app.name}</td>
                                <td className="py-1 px-2">
                                  <Tag color={app.status === "accepted" ? "green" : "blue"} className="text-[10px]">
                                    {app.status}
                                  </Tag>
                                </td>
                                <td className="py-1 px-2">{app.tier || "—"}</td>
                                <td className="py-1 px-2">{app.lot || "—"}</td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {dupesReport.duplicates?.length === 0 && (
                  <p className="text-green-700 font-medium m-0">No duplicate offers found.</p>
                )}
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
            <Segmented
              value={deskView}
              onChange={(v) => setDeskView(v as DeskView)}
              options={[
                { label: "Placement Desk", value: "desk" },
                { label: "Waitlist Queue", value: "queue" },
                { label: "All Applications", value: "applications" },
              ]}
              className="mb-4"
            />
          )}

          {showDesk && deskView === "desk" && (
            <Card
              title="Placement desk"
              size="small"
              extra={
                <span className="text-xs text-gray-500">
                  Search students · answer complaints · filter by tier
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
                  type={!deskTier ? "primary" : "default"}
                  onClick={() => setDeskTier(null)}
                >
                  All tiers
                </Button>
                {(() => {
                  const withWait = tierChips.filter((t) => t.waitCount > 0);
                  const withoutWait = tierChips.filter((t) => t.waitCount === 0);
                  return (
                    <>
                      {withWait.map(({ label, count, waitCount, cap }) => {
                        const short = label.replace(/ Resident$/i, "");
                        return (
                          <Badge key={label} count={waitCount} size="small" color="#d97706" offset={[-4, 0]}>
                            <Button
                              size="small"
                              type={deskTier === label ? "primary" : "default"}
                              danger={!!cap?.over_capacity}
                              title={`${short}: ${count} placed · ${waitCount} waitlisted`}
                              onClick={() => setDeskTier(deskTier === label ? null : label)}
                            >
                              {short}: {count}
                            </Button>
                          </Badge>
                        );
                      })}
                      {withoutWait.map(({ label, count, cap }) => {
                        const short = label.replace(/ Resident$/i, "");
                        return (
                          <Button
                            key={label}
                            size="small"
                            type={deskTier === label ? "primary" : "default"}
                            danger={!!cap?.over_capacity}
                            title={`${short}: ${count} placed · ${cap?.remaining_vs_active ?? 0} open`}
                            onClick={() => setDeskTier(deskTier === label ? null : label)}
                          >
                            {short}: {count}
                            {cap ? ` · ${cap.remaining_vs_active} open` : ""}
                          </Button>
                        );
                      })}
                    </>
                  );
                })()}
                <Tag
                  color={!deskTier && deskFilter === "waitlist" ? "blue" : "default"}
                  className="cursor-pointer px-2 py-0.5 leading-6"
                  onClick={() => {
                    setDeskTier(null);
                    setDeskFilter("waitlist");
                  }}
                >
                  All waitlists: {results?.live?.waitlisted_count ?? results?.waitlisted?.length ?? 0}
                </Tag>
              </div>

              {deskTier && (() => {
                const chip = tierChips.find((t) => t.label === deskTier);
                if (!chip) return null;
                const short = deskTier.replace(/ Resident$/i, "");
                return (
                  <div className="mb-3 px-3 py-2 bg-blue-50 border border-blue-200 rounded-md flex items-center justify-between">
                    <div className="text-sm">
                      <strong>{short}</strong>
                      <span className="text-gray-600 ml-3">
                        {chip.count} placed
                        {chip.cap ? ` · ${chip.cap.max_capacity} capacity` : ""}
                        {chip.waitCount > 0 ? ` · ${chip.waitCount} waitlisted` : ""}
                        {chip.cap && chip.cap.over_capacity && (
                          <span className="text-red-600 font-medium ml-1">(over capacity)</span>
                        )}
                      </span>
                    </div>
                    <Button type="link" size="small" onClick={() => setDeskTier(null)}>
                      Clear filter
                    </Button>
                  </div>
                );
              })()}

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
                    {label} ({deskFilterCounts[key] ?? 0})
                  </Tag>
                ))}
              </div>

              <Table
                rowKey="id"
                size="small"
                loading={loading}
                dataSource={deskFiltered}
                columns={deskColumns}
                pagination={{ defaultPageSize: 25, showSizeChanger: true }}
                locale={{
                  emptyText: deskQuery
                    ? "No students match that lookup"
                    : "No placements in this filter",
                }}
              />
            </Card>
          )}

          {showDesk && deskView === "queue" && (
            <Card title="Waitlist Queue" size="small" extra={
              <span className="text-xs text-gray-500">
                {deskRows.filter((a) => a.status === "waitlisted").length} students across {waitlistByTier.length} tiers
              </span>
            }>
              {waitlistByTier.length === 0 ? (
                <div className="text-center py-8 text-gray-400">No students are currently waitlisted.</div>
              ) : (
                <div className="space-y-4">
                  {waitlistByTier.map((group) => (
                    <div key={group.label} className="border rounded-lg overflow-hidden">
                      <div className="px-4 py-2.5 bg-gray-50 border-b flex items-center justify-between">
                        <div className="font-medium text-sm">
                          {group.short}
                          <span className="font-normal text-gray-500 ml-2">
                            {group.students.length} waiting
                            {group.cap ? ` · ${group.cap.max_capacity} capacity · ${group.cap.active_permits} active` : ""}
                          </span>
                        </div>
                        {group.cap?.over_capacity && (
                          <Tag color="red" className="m-0">Over capacity</Tag>
                        )}
                      </div>
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-xs text-gray-500 border-b bg-white">
                            <th className="py-1.5 px-4 w-16">#</th>
                            <th className="py-1.5 px-2">Student</th>
                            <th className="py-1.5 px-2 w-16">Year</th>
                            <th className="py-1.5 px-2">Wanted (#1)</th>
                            <th className="py-1.5 px-2 w-24">Plate</th>
                            <th className="py-1.5 px-2 w-40">Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {group.students.map((a, idx) => (
                            <tr key={a.id} className={`border-b border-gray-100 ${idx === 0 ? "bg-blue-50/50" : ""}`}>
                              <td className="py-2 px-4">
                                <span className={`inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold ${idx === 0 ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-600"}`}>
                                  {a.waitlist_position ?? "—"}
                                </span>
                              </td>
                              <td className="py-2 px-2">
                                <button
                                  type="button"
                                  className="text-left bg-transparent border-0 p-0 cursor-pointer text-brand-primary hover:underline"
                                  onClick={() => setCaseApp(a)}
                                >
                                  <div className="font-medium text-gray-900">{a.student_name}</div>
                                  <div className="text-xs text-gray-500">{a.student_email}</div>
                                </button>
                              </td>
                              <td className="py-2 px-2 text-gray-600">{a.class_year}</td>
                              <td className="py-2 px-2">
                                <Tooltip title={a.first_choice_label || a.tier_preference_labels?.[0]}>
                                  <span className="text-gray-700">
                                    {shortenTierLabel(a.first_choice_label || a.tier_preference_labels?.[0] || "—")}
                                  </span>
                                </Tooltip>
                              </td>
                              <td className="py-2 px-2 font-mono text-gray-600">{a.plate || "—"}</td>
                              <td className="py-2 px-2">
                                <Space size={0}>
                                  <Button type="link" size="small" className="px-1" onClick={() => setCaseApp(a)}>
                                    Case
                                  </Button>
                                  <Button type="link" size="small" className="px-1" disabled={busy} onClick={() => confirmBump(a)}>
                                    Top
                                  </Button>
                                  <Button type="link" size="small" className="px-1" disabled={busy} onClick={() => openManualSelect(a)}>
                                    Select
                                  </Button>
                                </Space>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}

          {(!showDesk || deskView === "applications") && (
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
                pagination={{ defaultPageSize: 20, showSizeChanger: true }}
              />
            </Card>
          )}
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
                {caseApp.is_upgrade && <Tag color="purple">Upgrade</Tag>}
                {caseApp.lottery_rank != null && <span>Rank #{caseApp.lottery_rank}</span>}
                {caseApp.waitlist_position != null && (
                  <span>Waitlist #{caseApp.waitlist_position}</span>
                )}
              </div>
              {caseApp.is_upgrade && caseApp.upgrade_credit != null && (
                <div className="text-sm text-purple-700 mb-1">
                  Upgrading from existing permit · Credit: ${Number(caseApp.upgrade_credit).toFixed(2)}
                </div>
              )}
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
                <ul className="m-0 pl-5 space-y-1.5">
                  {caseSiblings.map((s) => (
                    <li key={s.id} className="flex items-center gap-2">
                      <Tag color={STATUS_COLORS[s.status] || "default"}>{s.status}</Tag>
                      <span className="flex-1">
                        {s.assigned_permit_type_label || s.first_choice_label || "—"}
                        {s.id === caseApp.id ? " (this case)" : ""}
                      </span>
                      {s.status !== "superseded" && (
                        <Button
                          type="link"
                          danger
                          size="small"
                          className="p-0 h-auto text-[11px]"
                          disabled={busy}
                          onClick={async () => {
                            setBusy(true);
                            try {
                              const res = await fetch(`/api/lottery-v2/applications/${s.id}/remove`, {
                                method: "POST",
                                headers: await authHeaders(),
                              });
                              if (!res.ok) {
                                const err = await res.json().catch(() => ({}));
                                throw new Error(err.detail || "Delete failed");
                              }
                              message.success(`Deleted ${s.assigned_permit_type_label || "application"}`);
                              if (s.id === caseApp.id) setCaseApp(null);
                              if (activeId) loadDetail(activeId);
                            } catch (e: any) {
                              message.error(e.message);
                            } finally {
                              setBusy(false);
                            }
                          }}
                        >
                          Delete
                        </Button>
                      )}
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
            {caseApp.status === "selected" && (
              <Space>
                <Button type="primary" disabled={busy} onClick={() => openManualSelect(caseApp)}>
                  Reassign permit type
                </Button>
              </Space>
            )}
            {caseApp.status === "superseded" && (
              <Space>
                <Button type="primary" disabled={busy} onClick={() => openManualSelect(caseApp)}>
                  Select & offer
                </Button>
                <Button disabled={busy} onClick={() => confirmRestore(caseApp)}>
                  Restore to waitlist
                </Button>
              </Space>
            )}
            {caseApp.status === "accepted" && (
              <Space>
                <Button type="primary" disabled={busy} onClick={() => openUpgradeModal(caseApp)}>
                  Upgrade permit
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

      <Modal
        title="Recover student"
        open={recoverOpen}
        onCancel={() => setRecoverOpen(false)}
        footer={null}
        destroyOnClose
        width={640}
      >
        <div className="space-y-3">
          <p className="text-sm text-gray-600 m-0">
            Search for a student by email to find their application(s) across all cycles — including superseded, expired, or declined entries.
          </p>
          <div className="flex gap-2">
            <Input
              placeholder="student@moravian.edu"
              value={recoverEmail}
              onChange={(e) => setRecoverEmail(e.target.value)}
              onPressEnter={recoverSearch}
            />
            <Button type="primary" onClick={recoverSearch} loading={recoverLoading}>
              Search
            </Button>
          </div>
          {recoverResults && recoverResults.length > 0 && (
            <div className="border rounded overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Name</th>
                    <th className="px-3 py-2 text-left font-medium">Status</th>
                    <th className="px-3 py-2 text-left font-medium">Assigned</th>
                    <th className="px-3 py-2 text-left font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {recoverResults.map((app) => (
                    <tr key={app.id} className="border-t">
                      <td className="px-3 py-2">{app.student_name}</td>
                      <td className="px-3 py-2">
                        <Tag color={
                          app.status === "selected" ? "blue" :
                          app.status === "accepted" ? "green" :
                          app.status === "waitlisted" ? "orange" :
                          app.status === "superseded" ? "purple" :
                          "default"
                        }>{app.status}</Tag>
                      </td>
                      <td className="px-3 py-2">{app.assigned_permit_type_label || "—"}</td>
                      <td className="px-3 py-2">
                        <Space size={4}>
                          {["superseded", "expired", "declined"].includes(app.status) && (
                            <Button
                              type="link"
                              size="small"
                              disabled={busy}
                              onClick={() => { setRecoverOpen(false); openManualSelect(app); }}
                            >
                              Select & offer
                            </Button>
                          )}
                          {app.status === "waitlisted" && (
                            <Button
                              type="link"
                              size="small"
                              disabled={busy}
                              onClick={() => { setRecoverOpen(false); openManualSelect(app); }}
                            >
                              Select
                            </Button>
                          )}
                        </Space>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Modal>

      <Modal
        title="Add student to waitlist"
        open={addWaitlistOpen}
        onCancel={() => setAddWaitlistOpen(false)}
        onOk={confirmAddWaitlist}
        okText="Add"
        confirmLoading={addWaitlistLoading}
        okButtonProps={{ disabled: !addWaitlistEmail.trim() || !addWaitlistTierId }}
        destroyOnClose
      >
        <div className="space-y-3">
          <p className="text-sm text-gray-600 m-0">
            Create a new waitlist entry for a student. Their identity will be resolved automatically.
          </p>
          <div>
            <div className="text-sm font-medium mb-1">Student email</div>
            <Input
              placeholder="student@moravian.edu"
              value={addWaitlistEmail}
              onChange={(e) => setAddWaitlistEmail(e.target.value)}
            />
          </div>
          <div>
            <div className="text-sm font-medium mb-1">Campus</div>
            <Select
              className="w-full"
              value={addWaitlistCampus}
              onChange={(v) => { setAddWaitlistCampus(v); loadAddWaitlistTiers(v); }}
              options={[
                { value: "north", label: "North" },
                { value: "south", label: "South" },
                { value: "commuter", label: "Commuter" },
              ]}
            />
          </div>
          <div>
            <div className="text-sm font-medium mb-1">Permit type</div>
            <Select
              className="w-full"
              value={addWaitlistTierId}
              onChange={setAddWaitlistTierId}
              options={addWaitlistTiers.map((t) => ({
                value: t.id,
                label: `${t.label} — $${t.price}`,
              }))}
            />
          </div>
        </div>
      </Modal>

      <Modal
        title={upgradeTarget ? `Upgrade permit — ${upgradeTarget.student_name}` : "Upgrade permit"}
        open={!!upgradeTarget}
        onCancel={() => setUpgradeTarget(null)}
        onOk={confirmUpgrade}
        okText="Send upgrade & payment link"
        confirmLoading={upgradeLoading}
        okButtonProps={{ disabled: !upgradeTierId }}
        destroyOnClose
      >
        {upgradeTarget && (() => {
          const currentPrice = Number(upgradeTarget.assigned_permit_type_price || 0);
          const selected = upgradeTiers.find((t) => t.id === upgradeTierId);
          const diff = selected ? selected.price - currentPrice : 0;
          return (
            <div className="space-y-4">
              <p className="text-sm text-gray-600 m-0">
                Upgrade this student to a higher-priced permit. They will be emailed a payment link
                for only the price difference. Their old permit will be revoked once they pay.
              </p>
              <div className="p-3 bg-gray-50 rounded-lg">
                <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Current permit</div>
                <div className="font-semibold">
                  {upgradeTarget.assigned_permit_type_label} — ${currentPrice.toFixed(0)}
                </div>
              </div>
              <div>
                <div className="text-sm font-medium mb-1">Upgrade to</div>
                <Select
                  className="w-full"
                  value={upgradeTierId}
                  onChange={setUpgradeTierId}
                  options={upgradeTiers.map((t) => ({
                    value: t.id,
                    label: `${t.label} — $${t.price.toFixed(0)}`,
                  }))}
                />
              </div>
              {selected && (
                <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg">
                  <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Amount to charge</div>
                  <div className="text-xl font-bold text-blue-700">
                    ${diff.toFixed(2)}
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    ${selected.price.toFixed(0)} (new) − ${currentPrice.toFixed(0)} (current)
                  </div>
                </div>
              )}
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={upgradeNotify}
                  onChange={(e) => setUpgradeNotify(e.target.checked)}
                />
                Email the student the payment link
              </label>
            </div>
          );
        })()}
      </Modal>

      <Drawer
        title={tierDetail ? `${tierDetail.permit_type?.label}` : "Tier detail"}
        open={!!tierDetail}
        onClose={() => setTierDetail(null)}
        width={720}
        destroyOnClose
        extra={tierDetail && (
          <div className="flex gap-2">
            <Button size="small" onClick={() => {
              const d = tierDetail;
              const headers = ["Name", "Email", "Year", "Housing", "RA/RD", "Employee", "ABSN", "Applied", "Plate", "Permit #"];
              const csvRows = (d.active_permits || []).map((p: any) => [
                p.name, p.email, p.class_code || "", p.housing_label || "",
                p.res_life_staff ? "Yes" : "", p.employee ? "Yes" : "", p.accel_nursing ? "Yes" : "",
                p.applied_at ? new Date(p.applied_at).toLocaleString() : "",
                p.plate, p.permit_number,
              ]);
              if (d.pending_offers?.length) {
                csvRows.push([]); // blank row
                csvRows.push(["--- Pending Payment ---"]);
                for (const s of d.pending_offers) {
                  csvRows.push([s.name, s.email, s.class_year || "", "", "", "", "", s.applied_at ? new Date(s.applied_at).toLocaleString() : "", s.plate, s.is_upgrade ? "Upgrade" : ""]);
                }
              }
              const csv = [headers, ...csvRows].map(r => r.map((v: any) => `"${v ?? ""}"`).join(",")).join("\n");
              const blob = new Blob([csv], { type: "text/csv" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `${(d.permit_type?.label || "tier").replace(/\s+/g, "-")}-${new Date().toISOString().slice(0, 10)}.csv`;
              a.click();
              URL.revokeObjectURL(url);
            }}>
              Export CSV
            </Button>
            <Button size="small" onClick={() => {
              const d = tierDetail;
              const w = window.open("", "_blank");
              if (!w) return;
              const rows = (list: any[], cols: string[], keys: string[]) =>
                list.map((r: any) =>
                  `<tr>${keys.map(k => `<td style="padding:4px 10px;border-bottom:1px solid #eee;">${r[k] ?? ""}</td>`).join("")}</tr>`
                ).join("");
              w.document.write(`<!DOCTYPE html><html><head><title>${d.permit_type.label} Report</title>
                <style>body{font-family:system-ui,sans-serif;padding:24px;font-size:13px;color:#222;}
                h1{font-size:20px;margin:0 0 4px;}h2{font-size:15px;margin:24px 0 6px;border-bottom:2px solid #333;padding-bottom:4px;}
                .meta{color:#666;font-size:12px;margin-bottom:16px;}
                table{border-collapse:collapse;width:100%;}th{text-align:left;padding:4px 10px;border-bottom:2px solid #333;font-size:11px;text-transform:uppercase;color:#666;}
                @media print{body{padding:0;}}</style></head><body>
                <h1>${d.permit_type.label}</h1>
                <div class="meta">Price: $${d.permit_type.price} · Capacity: ${d.permit_type.max_capacity} · Active permits: ${d.summary.active_permit_count} · Pending: ${d.summary.pending_count} · Printed: ${new Date().toLocaleString()}</div>
                <h2>Active Permits (${d.active_permits.length})</h2>
                <table><thead><tr><th>Name</th><th>Email</th><th>Year</th><th>Housing</th><th>RA/RD</th><th>Plate</th><th>Permit #</th></tr></thead>
                <tbody>${d.active_permits.map((p: any) => `<tr>
                  <td style="padding:4px 10px;border-bottom:1px solid #eee;">${p.name ?? ""}</td>
                  <td style="padding:4px 10px;border-bottom:1px solid #eee;">${p.email ?? ""}</td>
                  <td style="padding:4px 10px;border-bottom:1px solid #eee;">${p.class_code ?? ""}</td>
                  <td style="padding:4px 10px;border-bottom:1px solid #eee;">${p.housing_label ?? ""}</td>
                  <td style="padding:4px 10px;border-bottom:1px solid #eee;">${p.res_life_staff ? "RA/RD" : ""}${p.employee ? " Emp" : ""}${p.accel_nursing ? " ABSN" : ""}</td>
                  <td style="padding:4px 10px;border-bottom:1px solid #eee;">${p.plate ?? ""}</td>
                  <td style="padding:4px 10px;border-bottom:1px solid #eee;">${p.permit_number ?? ""}</td>
                </tr>`).join("")}</tbody></table>
                ${d.pending_offers?.length ? `<h2>Pending Payment (${d.pending_offers.length})</h2>
                <table><thead><tr><th>Name</th><th>Email</th><th>Plate</th><th>Upgrade</th></tr></thead>
                <tbody>${rows(d.pending_offers, [], ["name","email","plate","is_upgrade"])}</tbody></table>` : ""}
                </body></html>`);
              w.document.close();
              w.print();
            }}>
              Print report
            </Button>
          </div>
        )}
      >
        {tierDetail && (
          <div className="space-y-5 text-sm">
            <div className="flex gap-3 flex-wrap">
              <div className="p-3 bg-gray-50 rounded flex-1 min-w-[100px]">
                <div className="text-[10px] text-gray-500 uppercase">Capacity</div>
                <div className="text-xl font-bold">{tierDetail.permit_type?.max_capacity}</div>
              </div>
              <div className="p-3 bg-gray-50 rounded flex-1 min-w-[100px]">
                <div className="text-[10px] text-gray-500 uppercase">Active permits</div>
                <div className="text-xl font-bold">{tierDetail.summary?.active_permit_count}</div>
              </div>
              <div className="p-3 bg-gray-50 rounded flex-1 min-w-[100px]">
                <div className="text-[10px] text-gray-500 uppercase">Pending payment</div>
                <div className="text-xl font-bold text-blue-600">{tierDetail.summary?.pending_count}</div>
              </div>
              <div className={`p-3 rounded flex-1 min-w-[100px] ${tierDetail.summary?.over_by > 0 ? "bg-red-50" : "bg-green-50"}`}>
                <div className="text-[10px] text-gray-500 uppercase">Committed</div>
                <div className="text-xl font-bold">
                  {tierDetail.summary?.committed}
                  {tierDetail.summary?.over_by > 0 && (
                    <span className="text-red-600 text-sm ml-1">(+{tierDetail.summary.over_by} over)</span>
                  )}
                </div>
              </div>
              <div className="p-3 bg-gray-50 rounded flex-1 min-w-[100px]">
                <div className="text-[10px] text-gray-500 uppercase">Unique people</div>
                <div className="text-xl font-bold">{tierDetail.summary?.unique_people}</div>
              </div>
            </div>

            {(tierDetail.summary?.housing_breakdown && Object.keys(tierDetail.summary.housing_breakdown).length > 0) && (
              <div className="p-3 bg-indigo-50 border border-indigo-100 rounded">
                <div className="text-[10px] text-indigo-500 uppercase font-medium mb-2">SIS Classification</div>
                <div className="flex gap-4 flex-wrap text-xs">
                  {Object.entries(tierDetail.summary.housing_breakdown).map(([label, count]: [string, any]) => (
                    <span key={label}><span className="font-medium">{count}</span> {label}</span>
                  ))}
                  {tierDetail.summary.res_life_staff_count > 0 && (
                    <span><span className="font-medium">{tierDetail.summary.res_life_staff_count}</span> RA/RD</span>
                  )}
                  {tierDetail.summary.employee_count > 0 && (
                    <span><span className="font-medium">{tierDetail.summary.employee_count}</span> Employee</span>
                  )}
                  {tierDetail.summary.accel_nursing_count > 0 && (
                    <span><span className="font-medium">{tierDetail.summary.accel_nursing_count}</span> ABSN</span>
                  )}
                </div>
              </div>
            )}

            <Collapse
              defaultActiveKey={["permits"]}
              items={[
                {
                  key: "permits",
                  label: `Active Permits (${tierDetail.active_permits?.length || 0})`,
                  children: (
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs border-collapse">
                        <thead>
                          <tr className="text-left border-b font-medium">
                            <th className="py-1 pr-2">Name</th>
                            <th className="py-1 pr-2">Email</th>
                            <th className="py-1 pr-2">Year</th>
                            <th className="py-1 pr-2">Housing</th>
                            <th className="py-1 pr-2">RA/RD</th>
                            <th className="py-1 pr-2">Applied</th>
                            <th className="py-1 pr-2">Plate</th>
                            <th className="py-1 pr-2">Permit #</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(tierDetail.active_permits || []).map((p: any, i: number) => {
                            const yearLabel = p.class_code || (() => {
                              const cy = p.class_year;
                              const now = new Date();
                              const acadStart = now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear() - 1;
                              const diff = cy ? cy - acadStart : null;
                              return diff === null ? "—" : diff <= 1 ? "Sr" : diff === 2 ? "Jr" : diff === 3 ? "So" : "Fr";
                            })();
                            return (
                              <tr key={i} className="border-b border-gray-100">
                                <td className="py-1 pr-2">{p.name}</td>
                                <td className="py-1 pr-2 text-gray-600">{p.email}</td>
                                <td className="py-1 pr-2">{yearLabel}</td>
                                <td className="py-1 pr-2">{p.housing_label || "—"}</td>
                                <td className="py-1 pr-2">
                                  {p.res_life_staff && <Tag color="green" className="text-[10px]">RA/RD</Tag>}
                                  {p.employee && <Tag color="blue" className="text-[10px]">Employee</Tag>}
                                  {p.accel_nursing && <Tag color="purple" className="text-[10px]">ABSN</Tag>}
                                </td>
                                <td className="py-1 pr-2 text-gray-500 whitespace-nowrap">{p.applied_at ? new Date(p.applied_at).toLocaleString() : "—"}</td>
                                <td className="py-1 pr-2 font-mono">{p.plate}</td>
                                <td className="py-1 pr-2 font-mono">{p.permit_number}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  ),
                },
                ...(tierDetail.pending_offers?.length > 0 ? [{
                  key: "pending",
                  label: `Pending Payment (${tierDetail.pending_offers.length})`,
                  children: (
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs border-collapse">
                        <thead>
                          <tr className="text-left border-b font-medium">
                            <th className="py-1 pr-2">Name</th>
                            <th className="py-1 pr-2">Email</th>
                            <th className="py-1 pr-2">Year</th>
                            <th className="py-1 pr-2">Applied</th>
                            <th className="py-1 pr-2">Plate</th>
                            <th className="py-1 pr-2">Upgrade</th>
                          </tr>
                        </thead>
                        <tbody>
                          {tierDetail.pending_offers.map((s: any, i: number) => {
                            const cy = s.class_year;
                            const now = new Date();
                            const acadStart = now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear() - 1;
                            const diff = cy ? cy - acadStart : null;
                            const yearLabel = diff === null ? "—" : diff <= 1 ? "Sr" : diff === 2 ? "Jr" : diff === 3 ? "So" : "Fr";
                            return (
                              <tr key={i} className="border-b border-gray-100">
                                <td className="py-1 pr-2">{s.name}</td>
                                <td className="py-1 pr-2 text-gray-600">{s.email}</td>
                                <td className="py-1 pr-2">{yearLabel}</td>
                                <td className="py-1 pr-2 text-gray-500 whitespace-nowrap">{s.applied_at ? new Date(s.applied_at).toLocaleString() : "—"}</td>
                                <td className="py-1 pr-2 font-mono">{s.plate}</td>
                                <td className="py-1 pr-2">{s.is_upgrade ? <Tag color="purple" className="text-[10px]">Upgrade</Tag> : ""}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  ),
                }] : []),
              ]}
            />

            {(tierDetail.issues?.accepted_no_permit?.length > 0 || tierDetail.issues?.permits_no_app?.length > 0) && (
              <div className="p-2 bg-amber-50 border border-amber-200 rounded text-xs space-y-2">
                <strong className="text-amber-700">Data issues</strong>
                {tierDetail.issues.accepted_no_permit?.length > 0 && (
                  <div>
                    <div className="font-medium text-amber-700">Accepted apps with no active permit ({tierDetail.issues.accepted_no_permit.length}):</div>
                    <ul className="mt-0.5 mb-0 pl-4">
                      {tierDetail.issues.accepted_no_permit.map((a: any, i: number) => (
                        <li key={i}>{a.name} — {a.email}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {tierDetail.issues.permits_no_app?.length > 0 && (
                  <div>
                    <div className="font-medium text-amber-700">Permits with no lottery application ({tierDetail.issues.permits_no_app.length}):</div>
                    <ul className="mt-0.5 mb-0 pl-4">
                      {tierDetail.issues.permits_no_app.map((p: any, i: number) => (
                        <li key={i}>{p.name} — {p.email} (#{p.permit_number})</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </Drawer>
    </div>
  );
}
