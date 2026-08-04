import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Card, Form, Input, InputNumber, Radio, Spin, Tag, App as AntApp, Space, Alert, Modal, Checkbox } from "antd";
import { ArrowDownOutlined, ArrowUpOutlined } from "@ant-design/icons";
import { initAuth, isAuthenticated, login, authHeaders, authHeadersAs, getImpersonateEmail, fetchCurrentUser, loadConfig, type AuthUser } from "../auth";
import type { Lot } from "../api";
import StudentLotMap from "../components/StudentLotMap";
import { useBranding } from "../useBranding";

/** Stable colors per permit-type code — cards and map lots share these */
const TIER_COLORS: Record<string, { fill: string; soft: string; border: string }> = {
  north_premium_resident: { fill: "#D97706", soft: "#FFFBEB", border: "#B45309" },
  south_premium_resident: { fill: "#D97706", soft: "#FFFBEB", border: "#B45309" },
  north_guaranteed_resident: { fill: "#2563EB", soft: "#EFF6FF", border: "#1D4ED8" },
  south_guaranteed_resident: { fill: "#2563EB", soft: "#EFF6FF", border: "#1D4ED8" },
  steel_field_resident: { fill: "#0D9488", soft: "#F0FDFA", border: "#0F766E" },
  premium_commuter: { fill: "#D97706", soft: "#FFFBEB", border: "#B45309" },
  commuter_undergrad: { fill: "#2563EB", soft: "#EFF6FF", border: "#1D4ED8" },
  commuter_grad: { fill: "#0D9488", soft: "#F0FDFA", border: "#0F766E" },
};

const FALLBACK_TIER_COLORS = [
  { fill: "#D97706", soft: "#FFFBEB", border: "#B45309" },
  { fill: "#2563EB", soft: "#EFF6FF", border: "#1D4ED8" },
  { fill: "#0D9488", soft: "#F0FDFA", border: "#0F766E" },
  { fill: "#DB2777", soft: "#FDF2F8", border: "#BE185D" },
  { fill: "#7C3AED", soft: "#F5F3FF", border: "#6D28D9" },
];

function tierColor(tier: { code: string }, index: number) {
  return TIER_COLORS[tier.code] || FALLBACK_TIER_COLORS[index % FALLBACK_TIER_COLORS.length];
}

/** Commuter map access types — matches Permit Types admin legend convention */
const COMMUTER_ACCESS = {
  fullTime: { fill: "#2563EB", label: "Full-time" },
  afterHours: { fill: "#D97706", label: "After 4 PM & weekends" },
  street: { fill: "#0D9488", label: "Street parking" },
} as const;

function commuterLotAccess(lot: Lot): keyof typeof COMMUTER_ACCESS {
  if (lot.lot_type === "street") return "street";
  if (lot.designation_code === "FS" || lot.designation_code === "FSC") return "afterHours";
  return "fullTime";
}

/** South Campus City of Bethlehem street permits */
const EXTERNAL_LOT_STYLE = {
  fill: "#F59E0B",
  soft: "#FFFBEB",
  border: "#D97706",
  label: "Third-party — City of Bethlehem",
};

const UNIVERSITY_LOT_FILL = "#FFD700";

function normalizeLotKey(name: string) {
  return name
    .replace(/^lot\s+/i, "")
    .replace(/\./g, "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

function isExternalLot(lot: Lot) {
  return lot.lot_type === "external";
}

interface Cycle {
  id: string;
  name: string;
  status: string;
  opens_at: string | null;
  closes_at: string | null;
  application_count: number;
}

interface Tier {
  id: string;
  code: string;
  label: string;
  price: string;
  max_capacity: number;
  remaining: number;
  lot_assignments: string[];
  min_class_year: number | null;
  campus: string;
  requires_lottery?: boolean;
  is_purchasable_online?: boolean;
}

interface Application {
  id: string;
  cycle_id: string;
  student_name: string;
  class_year: number;
  campus: string;
  plate: string;
  plate_state: string;
  tier_preferences: string[];
  assigned_permit_type_id: string | null;
  assigned_permit_type_label: string | null;
  assigned_permit_type_price: string | null;
  assigned_permit_type_code: string | null;
  assigned_lot: string | null;
  status: string;
  lottery_rank: number | null;
  waitlist_position: number | null;
  offer_expires_at: string | null;
  created_at: string;
}

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  pending: { text: "Entered — waiting for draw", color: "gold" },
  selected: { text: "Selected — accept your offer!", color: "green" },
  waitlisted: { text: "Waitlisted", color: "blue" },
  accepted: { text: "Permit active", color: "lime" },
  expired: { text: "Offer expired", color: "default" },
  declined: { text: "Declined", color: "default" },
  ineligible: { text: "Ineligible", color: "red" },
};

export default function LotteryApplyV2() {
  const [authState, setAuthState] = useState<"loading" | "ready" | "error">("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [impersonateEmail, setImpersonateEmail] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        await initAuth();
        const authed = await isAuthenticated();
        if (!authed) {
          sessionStorage.setItem("quarry_return_path", "/parking");
          await login();
          return;
        }
        const u = await fetchCurrentUser();

        // Check for impersonation param (admin only)
        const impEmail = getImpersonateEmail();
        if (impEmail && u?.role === "admin") {
          setImpersonateEmail(impEmail);
          // Fetch the impersonated user's identity
          const headers = await authHeaders();
          const lookupRes = await fetch(
            `/api/admin/impersonate-lookup?email=${encodeURIComponent(impEmail)}`,
            { headers },
          );
          if (lookupRes.ok) {
            const target = await lookupRes.json();
            // Staff/faculty → redirect to employee parking (preserving impersonation)
            if (target.role === "staff") {
              window.location.replace(`/employee-parking?impersonate=${encodeURIComponent(impEmail)}`);
              return;
            }
            setUser({
              sub: target.sub,
              email: target.email,
              role: target.role,
              groups: target.groups || [],
            });
          } else {
            // Fallback: show as that user with minimal info
            setUser({ sub: `impersonated:${impEmail}`, email: impEmail, role: "student", groups: [] });
          }
          setAuthState("ready");
          return;
        }

        // Faculty/staff (not Quarry admins) go to employee parking enrollment
        if (u?.role === "staff") {
          window.location.replace("/employee-parking");
          return;
        }
        setUser(u);
        setAuthState(u ? "ready" : "error");
      } catch {
        setAuthState("error");
      }
    })();
  }, []);

  if (authState === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <Spin size="large" />
          <p className="mt-4 text-gray-500">Signing you in...</p>
        </div>
      </div>
    );
  }

  if (authState === "error" || !user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Card className="max-w-md text-center">
          <h2 className="text-xl font-bold text-red-600 mb-2">Sign-In Error</h2>
          <p className="text-gray-500 mb-4">We couldn't verify your identity.</p>
          <Button onClick={() => window.location.reload()}>Try Again</Button>
        </Card>
      </div>
    );
  }

  return (
    <AntApp>
      <LotteryV2Page user={user} impersonateEmail={impersonateEmail} />
    </AntApp>
  );
}

function LotteryV2Page({ user, impersonateEmail }: { user: AuthUser; impersonateEmail?: string | null }) {
  const brand = useBranding();
  const { message, modal } = AntApp.useApp();
  const [loading, setLoading] = useState(true);
  const [cycle, setCycle] = useState<Cycle | null>(null);
  const [application, setApplication] = useState<Application | null>(null);
  const [step, setStep] = useState<"intake" | "rank" | "choose" | "done">("intake");
  const [campus, setCampus] = useState<"north" | "south" | "commuter" | null>("north");
  const [classYear, setClassYear] = useState<number | null>(null);
  const [plate, setPlate] = useState("");
  const [plateState, setPlateState] = useState("PA");
  const [phone, setPhone] = useState("");
  const [smsOptIn, setSmsOptIn] = useState(false);
  const [studentName, setStudentName] = useState(user.email || "");
  const [tiers, setTiers] = useState<Tier[]>([]);
  const [ranked, setRanked] = useState<Tier[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [lots, setLots] = useState<Lot[]>([]);
  const [myPermits, setMyPermits] = useState<any[]>([]);
  const [highlightedLots, setHighlightedLots] = useState<string[]>([]);
  const [hoveredTierId, setHoveredTierId] = useState<string | null>(null);
  const [focusedLot, setFocusedLot] = useState<string | null>(null);
  const [mapsApiKey, setMapsApiKey] = useState("");
  const [campusCenter, setCampusCenter] = useState<{ lat: number; lng: number } | undefined>();
  const [externalLot, setExternalLot] = useState<Lot | null>(null);
  const [commuterTiers, setCommuterTiers] = useState<Tier[]>([]);
  const [voucherCode, setVoucherCode] = useState("");
  const [voucherValid, setVoucherValid] = useState<{ discount_type: string; discount_value: number; message: string } | null>(null);
  const [voucherError, setVoucherError] = useState("");
  const [validatingVoucher, setValidatingVoucher] = useState(false);

  /** Lots belonging to the eligible path options only */
  const eligibleTiers = ranked.length > 0 ? ranked : tiers;
  const isCommuterPath = campus === "commuter";
  const isSouthPath = campus === "south";

  const eligibleLotNames = useMemo(() => {
    const names = new Set<string>();
    for (const tier of eligibleTiers) {
      for (const lot of tier.lot_assignments) names.add(lot);
    }
    return [...names];
  }, [eligibleTiers]);

  /** South Campus City of Bethlehem lots (Lehigh St. / Spring St.) */
  const southExternalLots = useMemo(
    () => lots.filter((l) => l.campus === "south" && isExternalLot(l)),
    [lots],
  );

  const mapLots = useMemo(() => {
    const byId = new Map<string, Lot>();
    if (eligibleLotNames.length > 0) {
      const allowed = new Set(eligibleLotNames.map(normalizeLotKey));
      for (const lot of lots) {
        if (allowed.has(normalizeLotKey(lot.name))) byId.set(lot.id, lot);
      }
    }
    // Always include south third-party lots when on the south path (name punctuation can diverge)
    if (isSouthPath) {
      for (const lot of southExternalLots) byId.set(lot.id, lot);
    }
    // Include commuter lots so hover highlighting works from the standalone card
    if (commuterTiers.length > 0 && !isCommuterPath) {
      const commuterLotNames = new Set(
        commuterTiers.flatMap((t) => t.lot_assignments).map(normalizeLotKey)
      );
      for (const lot of lots) {
        if (commuterLotNames.has(normalizeLotKey(lot.name))) byId.set(lot.id, lot);
      }
    }
    return [...byId.values()];
  }, [lots, eligibleLotNames, isSouthPath, southExternalLots, commuterTiers, isCommuterPath]);

  /** Lot assignment name → tier fill color (for resident rank map); external lots stay amber */
  const lotColors = useMemo(() => {
    const map: Record<string, string> = {};
    eligibleTiers.forEach((tier, i) => {
      const color = tierColor(tier, i).fill;
      for (const lot of tier.lot_assignments) {
        if (!map[lot]) map[lot] = color;
      }
    });
    for (const lot of mapLots) {
      if (isExternalLot(lot)) {
        map[lot.name] = EXTERNAL_LOT_STYLE.fill;
        map[lot.name.replace(/^lot\s+/i, "").trim()] = EXTERNAL_LOT_STYLE.fill;
      }
    }
    return map;
  }, [eligibleTiers, mapLots]);

  const mapLegend = useMemo(() => {
    const items = eligibleTiers.map((tier, i) => ({
      label: tier.label
        .replace(/\s+Resident$/i, "")
        .replace(/^Regular Commuter\s*/i, "")
        .replace(/^Extended Premium Commuter$/i, "Premium Commuter"),
      color: tierColor(tier, i).fill,
    }));
    if (mapLots.some(isExternalLot)) {
      items.push({ label: EXTERNAL_LOT_STYLE.label, color: EXTERNAL_LOT_STYLE.fill });
    }
    return items;
  }, [eligibleTiers, mapLots]);

  /** South intake: university yellow + third-party amber */
  const southIntakeColors = useMemo(() => {
    const map: Record<string, string> = {};
    for (const lot of mapLots) {
      const fill = isExternalLot(lot) ? EXTERNAL_LOT_STYLE.fill : UNIVERSITY_LOT_FILL;
      map[lot.name] = fill;
      map[lot.name.replace(/^lot\s+/i, "").trim()] = fill;
    }
    return map;
  }, [mapLots]);

  const southIntakeLegend = useMemo(() => {
    const items: { label: string; color: string }[] = [];
    if (mapLots.some((l) => !isExternalLot(l))) {
      items.push({ label: "University lots", color: UNIVERSITY_LOT_FILL });
    }
    if (mapLots.some(isExternalLot)) {
      items.push({ label: EXTERNAL_LOT_STYLE.label, color: EXTERNAL_LOT_STYLE.fill });
    }
    return items;
  }, [mapLots]);

  /** Commuter path: color by access (full-time / after-hours FS-FSC / street) */
  const commuterAccessColors = useMemo(() => {
    const map: Record<string, string> = {};
    for (const lot of mapLots) {
      const key = lot.name.replace(/^lot\s+/i, "").trim();
      map[key] = COMMUTER_ACCESS[commuterLotAccess(lot)].fill;
      map[lot.name] = COMMUTER_ACCESS[commuterLotAccess(lot)].fill;
    }
    return map;
  }, [mapLots]);

  const commuterAccessLegend = useMemo(() => {
    const present = new Set(mapLots.map(commuterLotAccess));
    return (["fullTime", "afterHours", "street"] as const)
      .filter((k) => present.has(k))
      .map((k) => ({ label: COMMUTER_ACCESS[k].label, color: COMMUTER_ACCESS[k].fill }));
  }, [mapLots]);

  async function loadTiers(c: "north" | "south" | "commuter", year?: number | null) {
    const headers = await authHeadersAs(impersonateEmail);
    const qs = new URLSearchParams({ campus: c });
    if (year != null) qs.set("class_year", String(year));
    const res = await fetch(`/api/lottery-v2/eligible-tiers?${qs}`, { headers });
    if (!res.ok) {
      message.error("Could not load available permits");
      return;
    }
    const data: Tier[] = await res.json();
    setTiers(data);
    setRanked(data);
  }

  async function selectCampus(c: "north" | "south" | "commuter") {
    setCampus(c);
    setFocusedLot(null);
    setHighlightedLots([]);
    setHoveredTierId(null);
    await loadTiers(c, classYear);
  }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const headers = await authHeadersAs(impersonateEmail);
      const [cycleRes, appRes, profileRes, lotsRes, permitsRes] = await Promise.all([
        fetch("/api/lottery-v2/cycle", { headers }),
        fetch("/api/lottery-v2/applications/me", { headers }),
        fetch("/api/auth/profile", { headers }),
        fetch("/api/lots", { headers }),
        fetch("/api/student/permits/my-permits", { headers }),
      ]);

      const cycleData: Cycle | null = cycleRes.ok ? await cycleRes.json() : null;
      setCycle(cycleData);

      const permits = permitsRes.ok ? await permitsRes.json() : [];
      setMyPermits(permits);

      const appBody = appRes.ok ? await appRes.json() : null;
      // Only lock into results if the app belongs to the cycle currently shown
      if (appBody && cycleData && appBody.cycle_id === cycleData.id) {
        setApplication(appBody);
        setStep("done");
      } else {
        setApplication(null);
        setStep("intake");
      }

      if (profileRes.ok) {
        const p = await profileRes.json();
        if (p.display_name) setStudentName(p.display_name);
        if (p.class_year) setClassYear(p.class_year);
      }
      if (lotsRes.ok) setLots(await lotsRes.json());
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    loadTiers("north");
    // Load commuter tiers independently for standalone display
    (async () => {
      try {
        const headers = await authHeadersAs(impersonateEmail);
        const res = await fetch("/api/lottery-v2/eligible-tiers?campus=commuter", { headers });
        if (res.ok) setCommuterTiers(await res.json());
      } catch { /* ignore */ }
    })();
    loadConfig().then((cfg) => {
      setMapsApiKey(cfg.google_maps_api_key || "");
      if (cfg.campus_lat && cfg.campus_lng) {
        setCampusCenter({ lat: cfg.campus_lat, lng: cfg.campus_lng });
      }
    });
  }, [load]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("accepted") || params.get("purchased")) {
      const sessionId = params.get("session_id");
      if (sessionId) {
        fetch(`/api/payments/verify-session?session_id=${encodeURIComponent(sessionId)}`)
          .then((r) => r.json())
          .then((data) => {
            if (data.permit_fulfilled) {
              message.success("Payment confirmed — your permit has been issued!");
            } else if (data.payment_status === "paid") {
              message.success("Payment received — your permit is being issued.");
            } else {
              message.info("Payment is processing. Your permit will appear shortly.");
            }
            load();
          })
          .catch(() => {
            message.success("Payment received — your permit is being issued.");
            load();
          });
      } else {
        message.success("Payment received — your permit is being issued.");
        load();
      }
    }
  }, [load, message]);

  // Refresh eligible options when class year changes after a path is chosen
  useEffect(() => {
    if (campus && classYear && (step === "intake" || step === "choose")) {
      loadTiers(campus, classYear);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classYear]);

  async function continueToRank() {
    if (!campus || !classYear || !plate.trim() || !phone.trim()) {
      message.warning("Campus, class year, plate, and phone are required");
      return;
    }
    await loadTiers(campus, classYear);
    if (campus === "commuter") {
      setStep("choose");
    } else if (cycle?.status !== "open") {
      // Post-draw: if tiers are purchasable (undersubscribed), offer direct purchase
      setStep("choose");
    } else {
      setStep("rank");
    }
  }

  function moveTier(index: number, direction: -1 | 1) {
    const next = [...ranked];
    const t = index + direction;
    if (t < 0 || t >= next.length) return;
    [next[index], next[t]] = [next[t], next[index]];
    setRanked(next);
  }

  async function validateVoucher(permitTypeCode: string) {
    if (!voucherCode.trim()) return;
    setValidatingVoucher(true);
    setVoucherError("");
    setVoucherValid(null);
    try {
      const headers = await authHeadersAs(impersonateEmail);
      const res = await fetch("/api/vouchers/validate", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ code: voucherCode.trim(), permit_type_code: permitTypeCode }),
      });
      const data = await res.json();
      if (data.valid) {
        setVoucherValid({ discount_type: data.discount_type, discount_value: data.discount_value, message: data.message });
        setVoucherError("");
      } else {
        setVoucherValid(null);
        setVoucherError(data.message || "Invalid voucher code.");
      }
    } catch {
      setVoucherError("Failed to validate voucher.");
    } finally {
      setValidatingVoucher(false);
    }
  }

  function clearVoucher() {
    setVoucherCode("");
    setVoucherValid(null);
    setVoucherError("");
  }

  async function purchaseCommuterPermit(tier: Tier) {
    if (!classYear || !plate.trim() || !phone.trim()) return;
    setSubmitting(true);
    try {
      const headers = await authHeadersAs(impersonateEmail);
      const res = await fetch("/api/student/permits/purchase", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          permit_type_id: tier.id,
          student_name: studentName,
          plate: plate.trim().toUpperCase(),
          plate_state: plateState.trim().toUpperCase(),
          class_year: classYear,
          phone: phone.trim(),
          sms_opt_in: smsOptIn,
          voucher_code: voucherValid ? voucherCode.trim() : undefined,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Purchase failed");
      }
      const data = await res.json();
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
        return;
      }
      if (data.fee_exempt) {
        message.success("Your permit has been issued — no charge (fee exempt).");
      } else if (data.voucher) {
        message.success("Your permit has been issued — voucher applied, no charge.");
      } else {
        message.success("Permit purchased");
      }
      setStep("done");
    } catch (e: any) {
      message.error(e.message || "Purchase failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function submit() {
    if (!campus || !classYear || ranked.length === 0) return;
    setSubmitting(true);
    try {
      const headers = await authHeadersAs(impersonateEmail);
      const res = await fetch("/api/lottery-v2/applications", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          campus,
          class_year: classYear,
          plate: plate.trim().toUpperCase(),
          plate_state: plateState.trim().toUpperCase(),
          phone: phone.trim(),
          sms_opt_in: smsOptIn,
          student_name: studentName,
          tier_preferences: ranked.map((t) => t.id),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Submit failed");
      }
      const app = await res.json();
      setApplication(app);
      setStep("done");
      message.success("Application submitted");
    } catch (e: any) {
      message.error(e.message || "Submit failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function acceptOffer() {
    if (!application) return;
    setAccepting(true);
    try {
      const headers = await authHeadersAs(impersonateEmail);
      const res = await fetch(`/api/lottery-v2/applications/${application.id}/accept`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(voucherValid ? { voucher_code: voucherCode.trim() } : {}),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Accept failed");
      }
      const data = await res.json();
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
        return;
      }
      message.success("Permit issued");
      await load();
    } catch (e: any) {
      message.error(e.message || "Accept failed");
    } finally {
      setAccepting(false);
    }
  }

  function declineOffer() {
    if (!application) return;
    modal.confirm({
      title: "Decline this offer?",
      content: "Your spot may be offered to the next person on the waitlist.",
      okText: "Decline",
      okButtonProps: { danger: true },
      onOk: async () => {
        const headers = await authHeadersAs(impersonateEmail);
        const res = await fetch(`/api/lottery-v2/applications/${application.id}/decline`, {
          method: "POST",
          headers,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          message.error(err.detail || "Decline failed");
          return;
        }
        message.info("Offer declined");
        await load();
      },
    });
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Spin size="large" />
      </div>
    );
  }

  const statusMeta = application
    ? STATUS_LABELS[application.status] || { text: application.status, color: "default" }
    : null;

  // Intake residents: uniform yellow. South: university + third-party colors. Commuter: access. Rank: tiers (+ external amber).
  const mapHighlight =
    highlightedLots.length > 0
      ? highlightedLots
      : application?.assigned_lot && step === "done"
        ? [application.assigned_lot]
        : step === "intake" && !isCommuterPath && !isSouthPath && eligibleLotNames.length > 0
          ? eligibleLotNames
          : [];

  const lotsForMap =
    step === "done" && application?.assigned_lot
      ? lots.filter((l) => normalizeLotKey(l.name) === normalizeLotKey(application.assigned_lot!))
      : mapLots.length > 0
        ? mapLots
        : [];

  const showMap = Boolean(mapsApiKey && lotsForMap.length > 0);
  const showCommuterAccessColors = isCommuterPath && (step === "intake" || step === "choose");
  const showSouthAccessColors = isSouthPath && (step === "intake" || step === "rank");
  const showTierColors = !isCommuterPath && !isSouthPath && (step === "rank" || step === "choose");
  const baseActiveLotColors = showCommuterAccessColors
    ? commuterAccessColors
    : showSouthAccessColors && step === "intake"
      ? southIntakeColors
      : showSouthAccessColors && step === "rank"
        ? lotColors
        : showTierColors
          ? lotColors
          : undefined;
  // When actively hovering a card, drop lot colors so the map uses the high-contrast
  // single-highlight mode (bright yellow highlighted lots, near-invisible others).
  const activeLotColors = highlightedLots.length > 0 ? undefined : baseActiveLotColors;
  const activeLegend = showCommuterAccessColors
    ? commuterAccessLegend
    : showSouthAccessColors && step === "intake"
      ? southIntakeLegend
      : showSouthAccessColors && step === "rank"
        ? mapLegend
        : showTierColors
          ? mapLegend
          : undefined;

  const schoolName = brand.schoolName || "Moravian University";

  function handleLotClick(lot: Lot) {
    if (isExternalLot(lot) && lot.external_url) {
      setExternalLot(lot);
    }
  }

  function openExternalPermit(lot: Lot | null) {
    if (lot?.external_url) {
      window.open(lot.external_url, "_blank", "noopener,noreferrer");
    }
    setExternalLot(null);
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header
        style={{ background: brand.primaryColor }}
        className="text-white px-6 py-4 shadow"
      >
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            {brand.logoUrl && <img src={brand.logoUrl} alt={brand.brandName} className="h-8 w-auto" />}
            <h1 style={{ color: brand.accentColor }} className="text-xl font-bold m-0">
              Parking Permits
            </h1>
          </div>
          <span className="text-xs opacity-70">{user.email}</span>
        </div>
      </header>

      {impersonateEmail && (
        <div style={{ background: "#FEF3C7", borderBottom: "2px solid #F59E0B", padding: "8px 24px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontWeight: 600, color: "#92400E" }}>
            Viewing as: {impersonateEmail} ({user.role})
          </span>
          <Button
            size="small"
            onClick={() => {
              const url = new URL(window.location.href);
              url.searchParams.delete("impersonate");
              window.location.href = url.toString();
            }}
          >
            Exit Impersonation
          </Button>
        </div>
      )}

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        <div className={`grid grid-cols-1 gap-6 ${showMap ? "lg:grid-cols-3" : ""}`}>
          {showMap && lotsForMap.length > 0 && (
            <div className="lg:hidden h-[280px] rounded-xl overflow-hidden shadow">
              <StudentLotMap
                apiKey={mapsApiKey}
                lots={lotsForMap}
                highlightedLots={mapHighlight}
                focusedLot={focusedLot}
                defaultCenter={campusCenter}
                lotColors={activeLotColors}
                legend={activeLegend}
                onLotClick={handleLotClick}
              />
            </div>
          )}

          <div className={`space-y-6 ${showMap ? "lg:col-span-1" : "max-w-2xl mx-auto w-full"}`}>
            {!cycle && step === "intake" && !isCommuterPath && (
              <Card>
                <p className="text-gray-500 m-0">
                  No lottery cycle is available right now. The residential parking lottery runs
                  during the summer, before the start of the school year. Check back when
                  registration opens.
                </p>
              </Card>
            )}

            {step === "intake" && !isCommuterPath && commuterTiers.length > 0 && (
              <Card title="Commuter Permits">
                <p className="text-sm text-gray-500 mb-4">
                  Commuter parking permits are available for direct purchase — no lottery required.
                </p>
                <div className="space-y-3">
                  {commuterTiers.map((tier) => (
                    <div
                      key={tier.id}
                      className="flex items-center justify-between border rounded-lg px-4 py-3 transition-shadow hover:shadow-md cursor-pointer"
                      onMouseEnter={() => setHighlightedLots(tier.lot_assignments)}
                      onMouseLeave={() => setHighlightedLots([])}
                    >
                      <div>
                        <div className="font-medium">{tier.label}</div>
                      </div>
                      <div className="text-right">
                        <div className="font-bold text-brand-primary">${Number(tier.price).toFixed(0)}</div>
                        {tier.remaining > 0 ? (
                          <Button
                            type="primary"
                            size="small"
                            className="mt-1"
                            onClick={() => { setCampus("commuter"); setTiers(commuterTiers); setRanked(commuterTiers); setStep("intake"); }}
                          >
                            Buy Now
                          </Button>
                        ) : (
                          <Tag color="red" className="mt-1">Full</Tag>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {cycle && !isCommuterPath && (
              <Card size="small">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="font-medium m-0">{cycle.name}</p>
                    <p className="text-xs text-gray-500 m-0">
                      Status: <Tag>{cycle.status}</Tag>
                    </p>
                  </div>
                  <Tag color={cycle.status === "open" ? "green" : "default"}>
                    {cycle.status === "open" ? "Accepting applications" : cycle.status}
                  </Tag>
                </div>
                <p className="text-xs text-gray-500 mt-2 mb-0">
                  The residential parking lottery runs during the summer, before the start of
                  the school year.{cycle.status !== "open" ? " Check back when registration opens." : ""}
                </p>
              </Card>
            )}

            {application && step === "done" && statusMeta && (
              <Card>
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h2 className="text-lg font-semibold m-0">Your application</h2>
                    <Tag color={statusMeta.color}>{statusMeta.text}</Tag>
                  </div>
                  <dl className="grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <dt className="text-gray-500">Name</dt>
                      <dd className="font-medium m-0">{application.student_name}</dd>
                    </div>
                    <div>
                      <dt className="text-gray-500">Class year</dt>
                      <dd className="font-medium m-0">{application.class_year}</dd>
                    </div>
                    <div>
                      <dt className="text-gray-500">Campus</dt>
                      <dd className="font-medium m-0 capitalize">{application.campus}</dd>
                    </div>
                    <div>
                      <dt className="text-gray-500">Vehicle</dt>
                      <dd className="font-mono font-medium m-0">
                        {application.plate}
                        {application.plate_state ? ` (${application.plate_state})` : ""}
                      </dd>
                    </div>
                  </dl>

                  {application.status === "selected" && (
                    <div className="rounded-lg bg-green-50 border border-green-200 p-4 space-y-3">
                      <p className="m-0 font-medium text-green-900">
                        {application.assigned_permit_type_label}
                        {application.assigned_permit_type_price != null && (
                          <span className="text-green-700"> — ${application.assigned_permit_type_price}</span>
                        )}
                      </p>
                      {application.assigned_lot && (
                        <p className="m-0 text-sm text-green-800">Lot: {application.assigned_lot}</p>
                      )}
                      {application.offer_expires_at && (
                        <p className="m-0 text-xs text-green-700">
                          Offer expires {new Date(application.offer_expires_at).toLocaleDateString()}
                        </p>
                      )}

                      {/* Voucher code input for lottery accept */}
                      <div className="p-2 bg-white rounded border border-dashed border-gray-300">
                        <p className="text-xs font-medium text-gray-600 mb-0.5">Program discount</p>
                        <p className="text-xs text-gray-500 mb-2">Some specialty programs subsidize parking. Your program director will have provided you with a code if applicable.</p>
                        <div className="flex gap-2">
                          <input
                            type="text"
                            className="flex-1 px-2 py-1 border rounded text-sm uppercase"
                            placeholder="Enter code"
                            value={voucherCode}
                            onChange={(e) => { setVoucherCode(e.target.value); setVoucherValid(null); setVoucherError(""); }}
                            disabled={!!voucherValid}
                          />
                          {voucherValid ? (
                            <button className="px-2 py-1 text-xs bg-gray-200 rounded" onClick={clearVoucher}>Clear</button>
                          ) : (
                            <button
                              className="px-2 py-1 text-xs bg-brand-primary text-white rounded disabled:opacity-50"
                              onClick={() => application.assigned_permit_type_code && validateVoucher(application.assigned_permit_type_code)}
                              disabled={!voucherCode.trim() || validatingVoucher}
                            >
                              {validatingVoucher ? "..." : "Apply"}
                            </button>
                          )}
                        </div>
                        {voucherValid && <p className="text-xs text-green-600 mt-1 mb-0">{voucherValid.message}</p>}
                        {voucherError && <p className="text-xs text-red-500 mt-1 mb-0">{voucherError}</p>}
                      </div>

                      <Space>
                        <Button type="primary" loading={accepting} onClick={acceptOffer}>
                          Accept &amp; Pay
                        </Button>
                        <Button onClick={declineOffer}>Decline</Button>
                      </Space>
                    </div>
                  )}

                  {application.status === "waitlisted" && (
                    <div className="rounded-lg bg-blue-50 border border-blue-200 p-4">
                      <p className="m-0 text-blue-900">
                        Waitlist position: <strong>#{application.waitlist_position}</strong>
                      </p>
                      <p className="m-0 mt-1 text-sm text-blue-800">
                        No action needed. You'll be notified if a spot opens.
                      </p>
                    </div>
                  )}

                  {application.status === "pending" && (
                    <p className="text-sm text-gray-500 m-0">
                      You're entered. Results appear here after the draw runs.
                    </p>
                  )}
                </div>
              </Card>
            )}

            {!application && myPermits.length > 0 && (
              <Card>
                <div className="space-y-4">
                  <h2 className="text-lg font-semibold m-0">Your Parking Permit{myPermits.length > 1 ? "s" : ""}</h2>
                  {myPermits.map((permit) => (
                    <div key={permit.id} className="rounded-lg bg-green-50 border border-green-200 p-4">
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-semibold text-green-900">{permit.permit_type_label || permit.permit_type}</span>
                        <Tag color="green">Active</Tag>
                      </div>
                      <dl className="grid grid-cols-2 gap-2 text-sm m-0">
                        {permit.permit_number && (
                          <div>
                            <dt className="text-gray-500">Permit #</dt>
                            <dd className="font-mono font-medium m-0">{permit.permit_number}</dd>
                          </div>
                        )}
                        <div>
                          <dt className="text-gray-500">Vehicle</dt>
                          <dd className="font-mono font-medium m-0">{permit.plates?.join(", ") || "—"}</dd>
                        </div>
                        {permit.lot_assignment && (
                          <div>
                            <dt className="text-gray-500">Lot(s)</dt>
                            <dd className="font-medium m-0">{permit.lot_assignment}</dd>
                          </div>
                        )}
                        <div>
                          <dt className="text-gray-500">Valid through</dt>
                          <dd className="font-medium m-0">
                            {permit.end_date ? new Date(permit.end_date).toLocaleDateString() : "—"}
                          </dd>
                        </div>
                      </dl>
                      {permit.can_swap && (
                        <p className="text-xs text-gray-500 mt-2 mb-0">
                          Need to change your vehicle? Contact parking services.
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {!application && step === "intake" && (cycle || isCommuterPath) && (
              <Card title={isCommuterPath ? "Commuter Permit — Your Info" : "1. About you"}>
                <Form layout="vertical" onFinish={continueToRank}>
                  {cycle && !isCommuterPath && (
                  <Form.Item label="Where do you park?" required>
                    <Radio.Group
                      value={campus}
                      onChange={(e) => selectCampus(e.target.value)}
                      optionType="button"
                      buttonStyle="solid"
                      options={[
                        { label: "North Campus", value: "north" },
                        { label: "South Campus", value: "south" },
                      ]}
                    />
                  </Form.Item>
                  )}
                  {isSouthPath && southExternalLots.length > 0 && (
                    <Alert
                      type="warning"
                      showIcon
                      className="mb-4"
                      message="Third-party street parking"
                      description={
                        <div className="space-y-2 text-sm">
                          <p className="m-0">
                            Lehigh St. and Spring St. are operated by the{" "}
                            <strong>City of Bethlehem</strong>, not {schoolName}. Permits,
                            enforcement, and policies for those streets are handled by the city.
                          </p>
                          <p className="m-0">
                            Amber areas on the map are third-party. Click a lot for details, or{" "}
                            <Button
                              type="link"
                              className="p-0 h-auto"
                              onClick={() => setExternalLot(southExternalLots[0])}
                            >
                              continue to {southExternalLots[0].external_provider || "their site"}
                            </Button>
                            .
                          </p>
                        </div>
                      }
                    />
                  )}
                  <Form.Item label="Name">
                    <Input value={studentName} onChange={(e) => setStudentName(e.target.value)} />
                  </Form.Item>
                  <Form.Item label="Class year" required>
                    <InputNumber
                      className="w-full"
                      min={2020}
                      max={2040}
                      value={classYear ?? undefined}
                      onChange={(v) => setClassYear(typeof v === "number" ? v : null)}
                    />
                  </Form.Item>
                  <Form.Item label="License plate" required>
                    <Input
                      value={plate}
                      onChange={(e) => setPlate(e.target.value.toUpperCase())}
                      className="font-mono"
                      maxLength={12}
                      placeholder="ABC1234"
                    />
                  </Form.Item>
                  <Form.Item label="State">
                    <Input
                      value={plateState}
                      onChange={(e) => setPlateState(e.target.value.toUpperCase())}
                      className="font-mono"
                      maxLength={2}
                      placeholder="PA"
                    />
                  </Form.Item>
                  <Form.Item label="Mobile phone" required>
                    <Input
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      placeholder="610-555-0123"
                      inputMode="tel"
                    />
                  </Form.Item>
                  <Form.Item className="mb-4">
                    <Checkbox checked={smsOptIn} onChange={(e) => setSmsOptIn(e.target.checked)}>
                      <span className="text-sm text-gray-600">
                        Text me emergency alerts and important messages about my vehicle (e.g., tow warnings, permit expiration, lot closures, lot flooding)
                      </span>
                    </Checkbox>
                  </Form.Item>
                  {!isCommuterPath && cycle?.status !== "open" && cycle?.status !== "drawn" && campus && (
                    <p className="text-sm text-amber-700 mb-3">
                      The resident lottery is not open right now. Check back when registration opens.
                      Commuter permits can be purchased separately below.
                    </p>
                  )}
                  <Button
                    type="primary"
                    htmlType="submit"
                    disabled={
                      !campus ||
                      !classYear ||
                      !plate ||
                      !phone.trim() ||
                      (!isCommuterPath && cycle?.status !== "open" && cycle?.status !== "drawn")
                    }
                  >
                    {isCommuterPath
                      ? "Continue — choose a permit"
                      : cycle?.status === "open"
                        ? "Continue — rank tiers"
                        : "Continue — available permits"}
                  </Button>
                </Form>
              </Card>
            )}

            {!application && step === "choose" && (
              <Card
                title={!cycle && isCommuterPath ? "Commuter Permits" : "2. Choose your permit"}
                extra={
                  <Button
                    type="link"
                    onClick={() => {
                      if (!cycle) {
                        setStep("intake");
                        setCampus("north");
                      } else {
                        setStep("intake");
                      }
                      setHighlightedLots([]);
                      setHoveredTierId(null);
                      setFocusedLot(null);
                    }}
                  >
                    Back
                  </Button>
                }
              >
                {ranked.length === 0 ? (
                  <p className="text-gray-500">No permits are available for your class year.</p>
                ) : (
                  <>
                    <p className="text-sm text-gray-500 mb-4">
                      {isCommuterPath
                        ? "Map colors: blue = full-time, amber = after 4 PM & weekends, teal = street. Hover a permit to emphasize its lots."
                        : "Spots remaining after the lottery draw. Purchase directly — first come, first served."}
                    </p>

                    {/* Voucher code input */}
                    <div className="mb-4 p-3 bg-gray-50 rounded-lg border border-dashed border-gray-300">
                      <p className="text-sm font-medium text-gray-600 mb-0.5">Program discount</p>
                      <p className="text-xs text-gray-500 mb-3">Some specialty programs subsidize parking. Your program director will have provided you with a code if applicable.</p>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          className="flex-1 px-3 py-1.5 border rounded text-sm uppercase"
                          placeholder="Enter code"
                          value={voucherCode}
                          onChange={(e) => { setVoucherCode(e.target.value); setVoucherValid(null); setVoucherError(""); }}
                          disabled={!!voucherValid}
                        />
                        {voucherValid ? (
                          <button
                            className="px-3 py-1.5 text-sm bg-gray-200 rounded hover:bg-gray-300"
                            onClick={clearVoucher}
                          >
                            Clear
                          </button>
                        ) : (
                          <button
                            className="px-3 py-1.5 text-sm bg-brand-primary text-white rounded disabled:opacity-50"
                            onClick={() => ranked.length > 0 && validateVoucher(ranked[0].code)}
                            disabled={!voucherCode.trim() || validatingVoucher}
                          >
                            {validatingVoucher ? "..." : "Apply"}
                          </button>
                        )}
                      </div>
                      {voucherValid && (
                        <p className="text-xs text-green-600 mt-1 mb-0">{voucherValid.message}</p>
                      )}
                      {voucherError && (
                        <p className="text-xs text-red-500 mt-1 mb-0">{voucherError}</p>
                      )}
                    </div>

                    <ul className="space-y-2 list-none p-0 m-0">
                      {ranked.map((tier, i) => {
                        const colors = tierColor(tier, i);
                        const isHovered = hoveredTierId === tier.id;
                        const soldOut = tier.remaining <= 0;
                        return (
                          <li
                            key={tier.id}
                            className="rounded-lg border px-3 py-3 transition-shadow hover:shadow-md"
                            style={{
                              borderColor: colors.border,
                              borderLeftWidth: 4,
                              background: isHovered ? colors.soft : "#fff",
                            }}
                            onMouseEnter={() => {
                              setHoveredTierId(tier.id);
                              setHighlightedLots(tier.lot_assignments);
                              setFocusedLot(null);
                            }}
                            onMouseLeave={() => {
                              setHoveredTierId(null);
                              setHighlightedLots([]);
                              setFocusedLot(null);
                            }}
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="m-0 font-medium flex items-center gap-2">
                                  <span
                                    className="inline-block w-2.5 h-2.5 rounded-sm shrink-0"
                                    style={{ background: colors.fill }}
                                  />
                                  {tier.label}
                                </p>
                                <p className="m-0 text-xs text-gray-500 mt-1">
                                  {voucherValid ? (
                                    <>
                                      <span className="line-through">${tier.price}</span>{" "}
                                      <span className="text-green-600 font-medium">
                                        {voucherValid.discount_type === "full"
                                          ? "FREE"
                                          : voucherValid.discount_type === "percent"
                                            ? `$${(Number(tier.price) * (100 - voucherValid.discount_value) / 100).toFixed(0)}`
                                            : `$${Math.max(0, Number(tier.price) - voucherValid.discount_value).toFixed(0)}`}
                                      </span>
                                    </>
                                  ) : (
                                    <>${tier.price}</>
                                  )}
                                </p>
                                <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-gray-500">
                                  <span>Lots:</span>
                                  {tier.lot_assignments.slice(0, 8).map((lotName) => {
                                    const lot = mapLots.find(
                                      (l) =>
                                        normalizeLotKey(l.name) === normalizeLotKey(lotName),
                                    );
                                    const access = lot
                                      ? COMMUTER_ACCESS[commuterLotAccess(lot)]
                                      : COMMUTER_ACCESS.fullTime;
                                    return (
                                      <Tag
                                        key={lotName}
                                        className="m-0"
                                        title={access.label}
                                        style={{
                                          color: access.fill,
                                          background: `${access.fill}18`,
                                          borderColor: access.fill,
                                        }}
                                      >
                                        {lotName}
                                      </Tag>
                                    );
                                  })}
                                  {tier.lot_assignments.length > 8 && (
                                    <span>+{tier.lot_assignments.length - 8} more</span>
                                  )}
                                </div>
                              </div>
                              <Button
                                type="primary"
                                size="small"
                                loading={submitting}
                                disabled={soldOut}
                                onClick={() => purchaseCommuterPermit(tier)}
                                style={{ background: soldOut ? undefined : colors.fill }}
                              >
                                {soldOut ? "Full" : "Buy"}
                              </Button>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  </>
                )}
              </Card>
            )}

            {!application && cycle?.status === "open" && step === "rank" && (
              <Card
                title="2. Rank your tiers"
                extra={
                  <Button
                    type="link"
                    onClick={() => {
                      setStep("intake");
                      setHighlightedLots([]);
                      setHoveredTierId(null);
                      setFocusedLot(null);
                    }}
                  >
                    Back
                  </Button>
                }
              >
                {ranked.length === 0 ? (
                  <p className="text-gray-500">
                    No tiers are available for your campus and class year.
                  </p>
                ) : (
                  <>
                    <p className="text-sm text-gray-500 mb-4">
                      Rank with the arrows. Each color matches its lots on the map — hover a tier
                      to zoom and emphasize it. #1 is your first choice.
                    </p>
                    <ul className="space-y-2 list-none p-0 m-0 mb-6">
                      {ranked.map((tier, i) => {
                        const colors = tierColor(tier, i);
                        const isHovered = hoveredTierId === tier.id;
                        return (
                        <li
                          key={tier.id}
                          className="flex items-center gap-3 rounded-lg border px-3 py-3 transition-shadow hover:shadow-md"
                          style={{
                            borderColor: colors.border,
                            borderLeftWidth: 4,
                            background: isHovered ? colors.soft : "#fff",
                          }}
                          onMouseEnter={() => {
                            setHoveredTierId(tier.id);
                            setHighlightedLots(tier.lot_assignments);
                            setFocusedLot(null);
                          }}
                          onMouseLeave={() => {
                            setHoveredTierId(null);
                            setHighlightedLots([]);
                            setFocusedLot(null);
                          }}
                        >
                          <span
                            className="text-sm font-bold w-6"
                            style={{ color: colors.fill }}
                          >
                            #{i + 1}
                          </span>
                          <div className="flex-1 min-w-0">
                            <p className="m-0 font-medium flex items-center gap-2">
                              <span
                                className="inline-block w-2.5 h-2.5 rounded-sm shrink-0"
                                style={{ background: colors.fill }}
                              />
                              {tier.label}
                            </p>
                            <p className="m-0 text-xs text-gray-500">
                              ${tier.price}
                            </p>
                            <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-gray-500">
                              <span>Lots:</span>
                              {tier.lot_assignments.length ? (
                                tier.lot_assignments.map((lotName) => {
                                  const lot = mapLots.find(
                                    (l) => normalizeLotKey(l.name) === normalizeLotKey(lotName),
                                  );
                                  const external = lot && isExternalLot(lot);
                                  const tagColor = external
                                    ? EXTERNAL_LOT_STYLE
                                    : { fill: colors.fill, soft: colors.soft, border: colors.border };
                                  return (
                                    <Tag
                                      key={lotName}
                                      className="m-0 cursor-default"
                                      title={
                                        external
                                          ? `${EXTERNAL_LOT_STYLE.label}${lot?.external_provider ? ` (${lot.external_provider})` : ""}`
                                          : undefined
                                      }
                                      style={{
                                        color: tagColor.border,
                                        background: tagColor.soft,
                                        borderColor: tagColor.fill,
                                      }}
                                      onClick={() => {
                                        if (external && lot) setExternalLot(lot);
                                      }}
                                      onMouseEnter={(e) => {
                                        e.stopPropagation();
                                        setFocusedLot(lotName);
                                        setHighlightedLots(tier.lot_assignments);
                                        setHoveredTierId(tier.id);
                                      }}
                                      onMouseLeave={(e) => {
                                        e.stopPropagation();
                                        setFocusedLot(null);
                                      }}
                                    >
                                      {lotName}
                                      {external ? " · 3rd party" : ""}
                                    </Tag>
                                  );
                                })
                              ) : (
                                <span>—</span>
                              )}
                            </div>
                          </div>
                          <Space size={4}>
                            <Button
                              size="small"
                              icon={<ArrowUpOutlined />}
                              disabled={i === 0}
                              onClick={() => moveTier(i, -1)}
                            />
                            <Button
                              size="small"
                              icon={<ArrowDownOutlined />}
                              disabled={i === ranked.length - 1}
                              onClick={() => moveTier(i, 1)}
                            />
                          </Space>
                        </li>
                        );
                      })}
                    </ul>
                    {isSouthPath && southExternalLots.length > 0 && (
                      <Alert
                        type="warning"
                        showIcon
                        className="mb-4"
                        message="Third-party option (not part of the lottery)"
                        description={
                          <div className="space-y-2 text-sm">
                            <p className="m-0">
                              {southExternalLots.map((l) => l.name).join(" and ")} are City of
                              Bethlehem residential parking. {schoolName} does not sell or enforce
                              permits there.
                            </p>
                            <Button size="small" onClick={() => setExternalLot(southExternalLots[0])}>
                              Get a City of Bethlehem permit
                            </Button>
                          </div>
                        }
                      />
                    )}
                    <Button type="primary" loading={submitting} onClick={submit} block>
                      Submit application
                    </Button>
                  </>
                )}
              </Card>
            )}

            {!application && !isCommuterPath && step === "rank" && cycle && cycle.status !== "open" && cycle.status !== "drawn" && (
              <Card>
                <p className="text-gray-500 m-0">
                  Resident lottery applications are not open ({cycle.status}).
                </p>
              </Card>
            )}
          </div>

          {showMap && (
            <div className="hidden lg:block lg:col-span-2 min-w-0">
              <div className="sticky top-6 h-[calc(100vh-8rem)] rounded-xl overflow-hidden shadow-lg">
                <StudentLotMap
                  apiKey={mapsApiKey}
                  lots={lotsForMap}
                  highlightedLots={mapHighlight}
                  focusedLot={focusedLot}
                  defaultCenter={campusCenter}
                  lotColors={activeLotColors}
                  legend={activeLegend}
                  onLotClick={handleLotClick}
                />
              </div>
            </div>
          )}
        </div>
      </main>

      <Modal
        open={!!externalLot}
        title={`You are leaving ${schoolName} Parking`}
        onCancel={() => setExternalLot(null)}
        centered
        okText={`Continue to ${externalLot?.external_provider || "external site"}`}
        cancelText="Cancel"
        onOk={() => openExternalPermit(externalLot)}
      >
        {externalLot && (
          <div className="space-y-4">
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
              <p className="text-amber-800 text-sm font-medium mb-1">External Parking Facility</p>
              <p className="text-amber-700 text-sm m-0">
                <strong>{externalLot.name}</strong> is operated by{" "}
                <strong>{externalLot.external_provider || "a third party"}</strong>.
              </p>
            </div>
            <p className="text-gray-600 text-sm m-0">
              {schoolName} is not responsible for permits, enforcement, or policies at this location.
              You will be redirected to their website to purchase a permit or view availability.
            </p>
            <p className="text-gray-500 text-xs m-0">
              A new tab will open at:{" "}
              <span className="font-mono text-xs break-all">{externalLot.external_url}</span>
            </p>
          </div>
        )}
      </Modal>
    </div>
  );
}
