import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Card, DatePicker, Form, Input, InputNumber, Radio, Select, Spin, Tag, App as AntApp, Space, Alert, Modal, Checkbox } from "antd";
import dayjs from "dayjs";
import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { initAuth, isAuthenticated, login, authHeaders, authHeadersAs, getImpersonateEmail, fetchCurrentUser, loadConfig, isOfficeRole, type AuthUser } from "../auth";
import type { Lot } from "../api";
import StudentLotMap from "../components/StudentLotMap";
import { useBranding } from "../useBranding";
import BrandMark from "../components/BrandMark";

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
  list_price?: string | null;
  discount_amount?: string | null;
  discount_label?: string | null;
  max_capacity: number;
  remaining: number;
  lot_assignments: string[];
  min_class_year: number | null;
  campus: string;
  requires_lottery?: boolean;
  is_purchasable_online?: boolean;
}

function formatTierPrice(tier: Tier) {
  const price = Number(tier.price);
  const list = tier.list_price != null ? Number(tier.list_price) : null;
  if (list != null && list > price) {
    return (
      <>
        <span className="line-through text-gray-400 mr-1">${list.toFixed(0)}</span>
        <span className="text-green-700">${price.toFixed(0)}</span>
      </>
    );
  }
  return <>${price.toFixed(0)}</>;
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
  assigned_permit_type_lots: string[];
  assigned_lot: string | null;
  status: string;
  lottery_rank: number | null;
  waitlist_position: number | null;
  phone: string | null;
  offer_expires_at: string | null;
  fee_exempt?: boolean;
  is_upgrade?: boolean;
  upgrade_credit?: number | null;
  created_at: string;
}

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  pending: { text: "Entered — waiting for draw", color: "gold" },
  selected: { text: "Selected — accept your offer!", color: "green" },
  waitlisted: { text: "Waitlisted", color: "blue" },
  accepted: { text: "Permit active", color: "lime" },
  expired: { text: "Offer expired", color: "default" },
  declined: { text: "Declined", color: "default" },
  superseded: { text: "Superseded", color: "default" },
  ineligible: { text: "Ineligible", color: "red" },
};

const PLATE_STATES = ["PA","NJ","NY","CT","DE","MD","VA","MA","OH","FL","TX","CA"];

function PlateSwapForm({
  permitId,
  currentPlate,
  canSwap,
  nextSwapAvailable,
  onSwapped,
}: {
  permitId: string;
  currentPlate: string;
  canSwap: boolean;
  nextSwapAvailable: string | null;
  onSwapped: (newPlate: string) => void;
}) {
  const { message } = AntApp.useApp();
  const [open, setOpen] = useState(false);
  const [plate, setPlate] = useState("");
  const [plateState, setPlateState] = useState("PA");
  const [submitting, setSubmitting] = useState(false);

  if (!canSwap) {
    const nextDate = nextSwapAvailable
      ? new Date(nextSwapAvailable).toLocaleDateString()
      : null;
    return (
      <div className="mt-3">
        <Button size="small" type="primary" disabled>Update Vehicle</Button>
        <p className="text-xs text-gray-400 mt-1 mb-0">
          You can update your vehicle once every 7 days. Next change available {nextDate || "soon"}.
        </p>
      </div>
    );
  }

  if (!open) {
    return (
      <div className="mt-3">
        <Button size="small" type="primary" onClick={() => setOpen(true)}>Update Vehicle</Button>
        <p className="text-xs text-gray-500 mt-1 mb-0">
          Got a new car? You can update the plate on your permit once every 7 days.
        </p>
      </div>
    );
  }

  async function handleSubmit() {
    const trimmed = plate.trim().toUpperCase();
    if (!trimmed) { message.warning("Enter a license plate"); return; }
    setSubmitting(true);
    try {
      const headers = await authHeaders();
      const res = await fetch("/api/student/permits/swap-vehicle", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ permit_id: permitId, new_plate: trimmed, new_plate_state: plateState }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (res.status === 429) {
          message.warning(err.detail || "You can only change your vehicle once per week");
        } else if (res.status === 409) {
          message.error(err.detail || "That plate is already registered on another permit");
        } else {
          message.error(err.detail || "Failed to change vehicle");
        }
        return;
      }
      message.success("Vehicle updated");
      onSwapped(trimmed);
      setOpen(false);
      setPlate("");
    } catch {
      message.error("Failed to change vehicle");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50/50 p-3">
      <p className="text-sm font-medium text-gray-700 m-0 mb-1">Update Vehicle</p>
      <p className="text-xs text-gray-500 m-0 mb-3">
        Enter your new license plate below. You may only update your vehicle once every 7 days.
      </p>
      <div className="flex gap-2 items-end">
        <Input
          size="small"
          placeholder="ABC1234"
          value={plate}
          onChange={e => setPlate(e.target.value.toUpperCase())}
          onPressEnter={e => { e.preventDefault(); handleSubmit(); }}
          className="flex-1"
          style={{ fontFamily: "monospace", textTransform: "uppercase" }}
        />
        <Select
          size="small"
          value={plateState}
          onChange={setPlateState}
          options={PLATE_STATES.map(s => ({ label: s, value: s }))}
          style={{ width: 72 }}
        />
        <Button size="small" type="primary" loading={submitting} onClick={handleSubmit}>
          Save
        </Button>
        <Button size="small" onClick={() => { setOpen(false); setPlate(""); }}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

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
        if (impEmail && isOfficeRole(u?.role)) {
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

        // Office users go to the dashboard
        if (isOfficeRole(u?.role)) {
          window.location.replace("/dashboard");
          return;
        }
        // Faculty/staff go to employee parking enrollment
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
  const [upgradeApps, setUpgradeApps] = useState<Application[]>([]);
  const [joiningUpgrade, setJoiningUpgrade] = useState<string | null>(null);
  const [housingStatus, setHousingStatus] = useState<string | null>(null);

  // Overnight guest registration state
  interface GuestReg { id: string; guest_name: string; guest_plate: string | null; guest_plate_state: string; check_in: string; check_out: string; status: string; }
  const [guestRegs, setGuestRegs] = useState<GuestReg[]>([]);
  const [showGuestForm, setShowGuestForm] = useState(false);
  const [guestCampus, setGuestCampus] = useState<"north" | "south">("north");
  const [guestSubmitting, setGuestSubmitting] = useState(false);
  const [guestForm] = Form.useForm();

  const loadGuests = useCallback(async () => {
    try {
      const headers = await authHeadersAs(impersonateEmail);
      const res = await fetch("/api/student/guests", { headers });
      if (res.ok) setGuestRegs(await res.json());
    } catch { /* ignore */ }
  }, [impersonateEmail]);

  useEffect(() => { loadGuests(); }, [loadGuests]);

  async function submitGuest(values: any) {
    setGuestSubmitting(true);
    try {
      const headers = await authHeadersAs(impersonateEmail);
      const res = await fetch("/api/student/guests", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          guest_name: values.guest_name,
          guest_plate: values.guest_plate || null,
          guest_plate_state: values.guest_plate_state || "PA",
          check_in: values.dates[0].format("YYYY-MM-DD"),
          check_out: values.dates[1].format("YYYY-MM-DD"),
          roommate_consent: values.roommate_consent,
          notes: values.notes || null,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to register guest");
      }
      message.success("Guest registered successfully");
      guestForm.resetFields();
      setShowGuestForm(false);
      loadGuests();
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setGuestSubmitting(false);
    }
  }

  async function cancelGuest(id: string) {
    try {
      const headers = await authHeadersAs(impersonateEmail);
      await fetch(`/api/student/guests/${id}`, { method: "DELETE", headers });
      message.success("Guest registration cancelled");
      loadGuests();
    } catch { message.error("Failed to cancel"); }
  }

  /** All eligible path options (map + choose); ranking is intentional and separate */
  const eligibleTiers = tiers;
  const unrankedTiers = useMemo(
    () => tiers.filter((t) => !ranked.some((r) => r.id === t.id)),
    [tiers, ranked],
  );
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
    // Do not pre-rank — Premium is listed first in API order and students were
    // accidentally submitting it as #1 when they meant Guaranteed.
    setRanked([]);
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
      const [cycleRes, appRes, profileRes, lotsRes, permitsRes, upgradeRes, housingRes] = await Promise.all([
        fetch("/api/lottery-v2/cycle", { headers }),
        fetch("/api/lottery-v2/applications/me", { headers }),
        fetch("/api/auth/profile", { headers }),
        fetch("/api/lots", { headers }),
        fetch("/api/student/permits/my-permits", { headers }),
        fetch("/api/lottery-v2/applications/me/upgrades", { headers }),
        fetch("/api/student/permits/housing-status", { headers }),
      ]);

      const cycleData: Cycle | null = cycleRes.ok ? await cycleRes.json() : null;
      setCycle(cycleData);

      // Auto-route based on Jenzabar housing classification
      if (housingRes.ok) {
        const h = await housingRes.json();
        setHousingStatus(h.housing_status);
        if (h.is_commuter) setCampus("commuter");
        else if (h.is_resident) setCampus("north");
      }

      const permits = permitsRes.ok ? await permitsRes.json() : [];
      setMyPermits(permits);

      const upgradeData = upgradeRes.ok ? await upgradeRes.json() : [];
      setUpgradeApps(Array.isArray(upgradeData) ? upgradeData : []);

      const appBody = appRes.ok ? await appRes.json() : null;
      // Only lock into results if the app belongs to the cycle currently shown.
      // Superseded = dead duplicate — treat as no application so they can re-join.
      if (
        appBody &&
        cycleData &&
        appBody.cycle_id === cycleData.id &&
        appBody.status !== "superseded"
      ) {
        setApplication(appBody);
        setStep("done");
        if (appBody.plate) setPlate(appBody.plate);
        if (appBody.plate_state) setPlateState(appBody.plate_state);
        if (appBody.phone) setPhone(appBody.phone);
        if (appBody.student_name) setStudentName(appBody.student_name);
        if (appBody.class_year) setClassYear(appBody.class_year);
        if (appBody.campus) loadTiers(appBody.campus, appBody.class_year);
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
    } else if (cycle?.status === "drawn") {
      // Post-draw: buy open seats and/or join waitlists
      setStep("choose");
    } else if (cycle?.status === "open") {
      setStep("rank");
    } else {
      setStep("choose");
    }
  }

  function addTier(tier: Tier) {
    setRanked((prev) => (prev.some((t) => t.id === tier.id) ? prev : [...prev, tier]));
  }

  function removeTier(index: number) {
    setRanked((prev) => prev.filter((_, i) => i !== index));
  }

  function moveTier(index: number, direction: -1 | 1) {
    const next = [...ranked];
    const t = index + direction;
    if (t < 0 || t >= next.length) return;
    [next[index], next[t]] = [next[t], next[index]];
    setRanked(next);
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
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Purchase failed");
      }
      const data = await res.json();
      if (data.fee_exempt) {
        message.success(data.message || "Thank you — your permit has been issued at no charge.");
      } else if (data.checkout_url) {
        window.location.href = data.checkout_url;
        return;
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

  function submit() {
    if (!campus || !classYear) return;
    if (ranked.length === 0) {
      message.warning("Add at least one permit type to your ranking");
      return;
    }
    const first = ranked[0];
    const postDraw = cycle?.status === "drawn";
    modal.confirm({
      title: postDraw ? "Confirm waitlist ranking" : "Confirm your first choice",
      width: 480,
      content: (
        <div className="space-y-3">
          <p className="m-0 text-sm text-gray-600">
            {postDraw
              ? "We'll process these in order and add you to the waitlist for each."
              : "Seats are offered in your ranked order. You will be considered for "}
            {!postDraw && (
              <>
                <strong>{first.label}</strong> first
                {first.price != null ? ` ($${Number(first.price).toFixed(0)})` : ""}.
              </>
            )}
          </p>
          <ol className="m-0 pl-5 text-sm space-y-1">
            {ranked.map((t, i) => (
              <li key={t.id}>
                <strong>#{i + 1}</strong> {t.label}
                {t.lot_assignments?.length ? ` — lots ${t.lot_assignments.join(", ")}` : ""}
                {postDraw && t.remaining <= 0 ? "" : ""}
              </li>
            ))}
          </ol>
          {ranked.length === 1 && !postDraw && (
            <p className="m-0 text-sm text-amber-800">
              You only ranked one option. If it fills up, you will be waitlisted with no backup.
            </p>
          )}
        </div>
      ),
      okText: postDraw
        ? `Join waitlist — ${first.label} first`
        : `Submit — try ${first.label} first`,
      cancelText: "Edit ranking",
      onOk: () => doSubmit(),
    });
  }

  async function doSubmit(prefs?: Tier[]) {
    const useRanked = prefs && prefs.length > 0 ? prefs : ranked;
    if (!campus || !classYear || useRanked.length === 0) return;
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
          tier_preferences: useRanked.map((t) => t.id),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Submit failed");
      }
      const app = await res.json();
      setApplication(app);
      setRanked(useRanked);
      setStep("done");
      if (app.status === "selected") {
        message.success("A seat was available — accept your offer below.");
      } else if (app.status === "waitlisted") {
        message.success("You're on the waitlist. You'll be notified if a spot opens.");
      } else {
        message.success("Application submitted");
      }
    } catch (e: any) {
      message.error(e.message || "Submit failed");
    } finally {
      setSubmitting(false);
    }
  }

  function joinWaitlist(tier: Tier) {
    const soldOut = tier.remaining <= 0;
    modal.confirm({
      title: soldOut ? `Join waitlist for ${tier.label}?` : `Request ${tier.label}?`,
      content: soldOut
        ? `This permit is currently full (lots: ${tier.lot_assignments.join(", ") || "—"}). You'll be notified if a spot opens.`
        : `If a seat is still open, you'll get an offer right away. Otherwise you'll join the waitlist for ${tier.label}.`,
      okText: soldOut ? "Join waitlist" : "Request / waitlist",
      onOk: () => doSubmit([tier]),
    });
  }

  async function acceptOffer() {
    if (!application) return;
    setAccepting(true);
    try {
      const headers = await authHeadersAs(impersonateEmail);
      const res = await fetch(`/api/lottery-v2/applications/${application.id}/accept`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Accept failed");
      }
      const data = await res.json();
      if (data.fee_exempt) {
        message.success(data.message || "Thank you — your permit has been issued at no charge.");
        await load();
        return;
      }
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

  async function joinUpgradeWaitlist(tierId: string) {
    if (!application) return;
    setJoiningUpgrade(tierId);
    try {
      const headers = await authHeadersAs(impersonateEmail);
      const res = await fetch("/api/lottery-v2/applications", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          campus: application.campus,
          class_year: application.class_year,
          plate: application.plate,
          plate_state: application.plate_state,
          phone: phone || "0000000",
          tier_preferences: [tierId],
          is_upgrade: true,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to join waitlist");
      }
      message.success("Joined waitlist");
      await load();
    } catch (e: any) {
      message.error(e.message || "Failed to join waitlist");
    } finally {
      setJoiningUpgrade(null);
    }
  }

  async function acceptUpgradeOffer(upgradeApp: Application) {
    setAccepting(true);
    try {
      const headers = await authHeadersAs(impersonateEmail);
      const res = await fetch(`/api/lottery-v2/applications/${upgradeApp.id}/accept`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({}),
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
      if (data.status === "accepted") {
        message.success("Upgrade complete!");
        await load();
        return;
      }
      message.success("Upgrade issued");
      await load();
    } catch (e: any) {
      message.error(e.message || "Accept failed");
    } finally {
      setAccepting(false);
    }
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
  const doneDefaultLots =
    application?.assigned_permit_type_lots?.length
      ? application.assigned_permit_type_lots
      : application?.assigned_lot
        ? [application.assigned_lot]
        : [];

  const GUEST_LOTS_NORTH = ["X", "A", "F", "H", "M", "N", "O", "R", "S"];
  const GUEST_LOTS_SOUTH = ["U"];
  const GUEST_LOTS = guestCampus === "south" ? GUEST_LOTS_SOUTH : GUEST_LOTS_NORTH;
  // For the map, show only geographically-relevant lots per campus
  const GUEST_MAP_LOTS = GUEST_LOTS;

  const mapHighlight =
    highlightedLots.length > 0
      ? highlightedLots
      : showGuestForm
        ? GUEST_MAP_LOTS
        : step === "done" && doneDefaultLots.length > 0
          ? doneDefaultLots
          : step === "intake" && !isCommuterPath && !isSouthPath && eligibleLotNames.length > 0
            ? eligibleLotNames
            : [];

  const lotsForMap =
    showGuestForm
      ? lots.filter((l) => GUEST_MAP_LOTS.some((g) => normalizeLotKey(g) === normalizeLotKey(l.name)))
      : step === "done" && doneDefaultLots.length > 0
        ? lots.filter((l) => doneDefaultLots.some((d) => normalizeLotKey(d) === normalizeLotKey(l.name)))
        : mapLots.length > 0
          ? mapLots
          : [];

  const showMap = Boolean(mapsApiKey && lotsForMap.length > 0);
  const lotteryActive = cycle?.status === "open" || cycle?.status === "drawn";
  const buyingOpen = commuterTiers.some((t) => t.remaining > 0);
  // Closed-lottery info card only when nothing is actionable (true off-season)
  const showOffSeasonCard =
    step === "intake" && !isCommuterPath && !application && !lotteryActive && !buyingOpen;
  const showCommuterAccessColors = isCommuterPath && (step === "intake" || step === "choose");
  const showSouthAccessColors = isSouthPath && (step === "intake" || step === "rank");
  const showTierColors = !isCommuterPath && !isSouthPath && (step === "rank" || step === "choose");

  const GUEST_FULL_TIME_LOTS = guestCampus === "north" ? ["X"] : [];

  const guestLotColors: Record<string, string> = {};
  for (const lot of GUEST_MAP_LOTS) {
    const color = GUEST_FULL_TIME_LOTS.includes(lot) ? "#22C55E" : "#EAB308";
    guestLotColors[lot] = color;
    guestLotColors[`Lot ${lot}`] = color;
    guestLotColors[lot.toLowerCase()] = color;
  }

  const baseActiveLotColors = showGuestForm
    ? guestLotColors
    : showCommuterAccessColors
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
  const guestLegend = guestCampus === "south"
    ? [{ label: "Lot U — After 4 PM & weekends", color: "#EAB308" }]
    : [
        { label: "Lot X — Park anytime", color: "#22C55E" },
        { label: "Other lots — After 4 PM & weekends", color: "#EAB308" },
      ];

  const activeLegend = showGuestForm
    ? guestLegend
    : showCommuterAccessColors
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
            <BrandMark />
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
            {showOffSeasonCard && (
              <Card size="small">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="font-medium m-0">{cycle?.name || "Parking Lottery"}</p>
                    <p className="text-xs text-gray-500 m-0">
                      Status: <Tag>{cycle?.status || "closed"}</Tag>
                    </p>
                  </div>
                  <Tag>closed</Tag>
                </div>
                <p className="text-xs text-gray-500 mt-2 mb-0">
                  The residential parking lottery runs during the summer, before the start of
                  the school year. Check back when registration opens.
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

                  {application.status === "accepted" && (() => {
                    const appPlate = (application.plate || "").toUpperCase();
                    const matchingPermit = myPermits.length === 1
                      ? myPermits[0]
                      : myPermits.find(p =>
                          p.plates?.some((pl: string) => pl.toUpperCase() === appPlate)
                        ) || myPermits[0];
                    if (!matchingPermit) return null;
                    return (
                      <PlateSwapForm
                        permitId={matchingPermit.id}
                        currentPlate={matchingPermit.plates?.[0] || application.plate}
                        canSwap={matchingPermit.can_swap}
                        nextSwapAvailable={matchingPermit.next_swap_available}
                        onSwapped={(newPlate) => {
                          setApplication((prev: any) => prev ? { ...prev, plate: newPlate } : prev);
                          setMyPermits((prev) => prev.map(p =>
                            p.id === matchingPermit.id ? { ...p, plates: [newPlate], can_swap: false, next_swap_available: new Date(Date.now() + 7 * 86400000).toISOString() } : p
                          ));
                        }}
                      />
                    );
                  })()}

                  {application.status === "selected" && (
                    <div className="rounded-lg bg-green-50 border border-green-200 p-4 space-y-3">
                      <p className="m-0 font-medium text-green-900">
                        {application.assigned_permit_type_label}
                        {application.assigned_permit_type_price != null ? (
                          <span className="text-green-700"> — ${application.assigned_permit_type_price}</span>
                        ) : null}
                      </p>
                      {((application.assigned_permit_type_lots && application.assigned_permit_type_lots.length > 0)
                        || application.assigned_lot) && (
                        <p className="m-0 text-sm text-green-800">
                          Allowed lot{((application.assigned_permit_type_lots?.length || 0) > 1) ? "s" : ""}:{" "}
                          {(application.assigned_permit_type_lots && application.assigned_permit_type_lots.length > 0)
                            ? application.assigned_permit_type_lots.join(", ")
                            : application.assigned_lot}
                        </p>
                      )}
                      {application.offer_expires_at && (
                        <p className="m-0 text-xs text-green-700">
                          Offer expires {new Date(application.offer_expires_at).toLocaleDateString()}
                        </p>
                      )}

                      <Space>
                        <Button type="primary" loading={accepting} onClick={acceptOffer}>
                          Accept & Pay
                        </Button>
                        <Button onClick={declineOffer}>Decline</Button>
                      </Space>
                    </div>
                  )}

                  {application.status === "waitlisted" && (
                    <div className="rounded-lg bg-blue-50 border border-blue-200 p-4">
                      <p className="m-0 text-blue-900 font-medium">
                        You're on the waitlist
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

            {application && application.status === "waitlisted" && tiers.length > 0 && (
              <Card className="mt-4">
                <div className="space-y-4">
                  <h3 className="text-base font-semibold m-0">Join Other Waitlists</h3>
                  <p className="text-sm text-gray-600 m-0">
                    Want to try for a different permit too? Join additional waitlists below.
                    You'll be notified if a spot opens for any of them.
                  </p>
                  {(() => {
                    const currentTierId = application.tier_preferences?.[0] || application.assigned_permit_type_id;
                    const otherTiers = tiers.filter((t) => t.id !== currentTierId && t.requires_lottery);
                    if (otherTiers.length === 0) {
                      return (
                        <p className="text-sm text-gray-400 m-0">
                          No other permit types available for your campus.
                        </p>
                      );
                    }
                    return otherTiers.map((tier) => {
                      const alreadyOn = upgradeApps.some(
                        (ua) => ua.tier_preferences?.includes(tier.id)
                      );
                      const existingApp = upgradeApps.find(
                        (ua) => ua.tier_preferences?.includes(tier.id)
                      );
                      return (
                        <div
                          key={tier.id}
                          className="flex items-center justify-between rounded-lg border border-gray-200 p-3 transition-shadow hover:shadow-md cursor-pointer"
                          onMouseEnter={() => setHighlightedLots(tier.lot_assignments || [])}
                          onMouseLeave={() => setHighlightedLots([])}
                        >
                          <div>
                            <span className="font-medium">{tier.label}</span>
                            <span className="text-sm text-gray-500 ml-2">
                              ${Number(tier.price).toFixed(0)}
                              {tier.lot_assignments?.length ? ` — ${tier.lot_assignments.join(", ")}` : ""}
                            </span>
                            {existingApp?.status === "selected" && (
                              <Tag color="green" className="ml-2">Offer available!</Tag>
                            )}
                          </div>
                          <div>
                            {existingApp?.status === "selected" ? (
                              <Button
                                type="primary"
                                size="small"
                                loading={accepting}
                                onClick={() => acceptUpgradeOffer(existingApp)}
                              >
                                Accept Offer
                              </Button>
                            ) : (
                              <Button
                                size="small"
                                disabled={alreadyOn}
                                loading={joiningUpgrade === tier.id}
                                onClick={() => joinUpgradeWaitlist(tier.id)}
                              >
                                {alreadyOn ? "On Waitlist" : "Join Waitlist"}
                              </Button>
                            )}
                          </div>
                        </div>
                      );
                    });
                  })()}
                </div>
              </Card>
            )}

            {application && (application.status === "waitlisted" || application.status === "accepted") && tiers.length > 0 && (() => {
              const buyableTiers = tiers.filter((t) => !t.requires_lottery && t.is_purchasable_online && t.remaining > 0);
              if (buyableTiers.length === 0) return null;
              return (
                <Card className="mt-4">
                  <div className="space-y-4">
                    <h3 className="text-base font-semibold m-0">Buy Available Permits</h3>
                    <p className="text-sm text-gray-600 m-0">
                      These permits are available for direct purchase — no waitlist needed.
                    </p>
                    {buyableTiers.map((tier) => (
                      <div
                        key={tier.id}
                        className="flex items-center justify-between rounded-lg border border-gray-200 p-3 transition-shadow hover:shadow-md cursor-pointer"
                        onMouseEnter={() => setHighlightedLots(tier.lot_assignments || [])}
                        onMouseLeave={() => setHighlightedLots([])}
                      >
                        <div>
                          <span className="font-medium">{tier.label}</span>
                          <span className="text-sm text-gray-500 ml-2">
                            ${Number(tier.price).toFixed(0)}
                            {tier.lot_assignments?.length ? ` — ${tier.lot_assignments.join(", ")}` : ""}
                          </span>
                          
                        </div>
                        <Button
                          type="primary"
                          size="small"
                          loading={submitting}
                          onClick={() => purchaseCommuterPermit(tier)}
                        >
                          Buy
                        </Button>
                      </div>
                    ))}
                  </div>
                </Card>
              );
            })()}

            {application && application.status === "accepted" && tiers.length > 0 && (
              <Card className="mt-4">
                <div className="space-y-4">
                  <h3 className="text-base font-semibold m-0">Upgrade Waitlist</h3>
                  <p className="text-sm text-gray-600 m-0">
                    Want a higher-tier permit? Join a waitlist below. If a spot opens, you'll be
                    offered the upgrade for just the price difference.
                  </p>
                  {(() => {
                    const currentPrice = parseFloat(application.assigned_permit_type_price || "0");
                    const higherTiers = tiers.filter(
                      (t) => parseFloat(t.price) > currentPrice && t.id !== application.assigned_permit_type_id && t.requires_lottery
                    );
                    if (higherTiers.length === 0) {
                      return (
                        <p className="text-sm text-gray-400 m-0">
                          You already have the highest-tier permit available.
                        </p>
                      );
                    }
                    return higherTiers.map((tier) => {
                      const alreadyOn = upgradeApps.some(
                        (ua) => ua.tier_preferences?.includes(tier.id)
                      );
                      const upgradeApp = upgradeApps.find(
                        (ua) => ua.tier_preferences?.includes(tier.id)
                      );
                      const diff = (parseFloat(tier.price) - currentPrice).toFixed(2);
                      return (
                        <div
                          key={tier.id}
                          className="flex items-center justify-between rounded-lg border border-gray-200 p-3 transition-shadow hover:shadow-md cursor-pointer"
                          onMouseEnter={() => setHighlightedLots(tier.lot_assignments || [])}
                          onMouseLeave={() => setHighlightedLots([])}
                        >
                          <div>
                            <span className="font-medium">{tier.label}</span>
                            <span className="text-sm text-gray-500 ml-2">
                              +${diff} difference
                            </span>
                            {upgradeApp?.status === "selected" && (
                              <Tag color="green" className="ml-2">Offer available!</Tag>
                            )}
                          </div>
                          <div>
                            {upgradeApp?.status === "selected" ? (
                              <Button
                                type="primary"
                                size="small"
                                loading={accepting}
                                onClick={() => acceptUpgradeOffer(upgradeApp)}
                              >
                                Accept Upgrade (${diff})
                              </Button>
                            ) : (
                              <Button
                                size="small"
                                disabled={alreadyOn}
                                loading={joiningUpgrade === tier.id}
                                onClick={() => joinUpgradeWaitlist(tier.id)}
                              >
                                {alreadyOn ? "On Waitlist" : "Join Waitlist"}
                              </Button>
                            )}
                          </div>
                        </div>
                      );
                    });
                  })()}
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
                      <PlateSwapForm
                        permitId={permit.id}
                        currentPlate={permit.plates?.[0] || ""}
                        canSwap={permit.can_swap}
                        nextSwapAvailable={permit.next_swap_available}
                        onSwapped={(newPlate) => {
                          setMyPermits((prev) => prev.map(p =>
                            p.id === permit.id ? { ...p, plates: [newPlate], can_swap: false, next_swap_available: new Date(Date.now() + 7 * 86400000).toISOString() } : p
                          ));
                        }}
                      />
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {(step === "done" || (!application && myPermits.length > 0) || (!application && !cycle && !isCommuterPath)) && (
              <Card className="mt-4">
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-base font-semibold m-0">Overnight Guest Registration</h3>
                      <p className="text-sm text-gray-500 m-0 mt-1">
                        Guests may stay up to 2 consecutive nights within any 7-day period.
                        Roommate consent is required. Guest vehicles must be registered.
                      </p>
                    </div>
                    {!showGuestForm && (
                      <Button icon={<PlusOutlined />} onClick={() => setShowGuestForm(true)}>
                        Register a Guest
                      </Button>
                    )}
                  </div>

                  {showGuestForm && (
                    <div className="rounded-lg border border-blue-200 bg-blue-50/50 p-4">
                      <div className="flex items-center gap-2 mb-3">
                        <span className="text-sm font-medium text-gray-700">Campus:</span>
                        <Radio.Group
                          value={guestCampus}
                          onChange={(e) => setGuestCampus(e.target.value)}
                          size="small"
                          optionType="button"
                          buttonStyle="solid"
                          options={[
                            { label: "North", value: "north" },
                            { label: "South", value: "south" },
                          ]}
                        />
                      </div>
                      {guestCampus === "south" && (
                        <div className="mb-3 rounded bg-green-50 border border-green-200 px-3 py-2 text-xs text-green-800">
                          <strong>Lot U</strong> (south campus) — after 4 PM &amp; weekends only. For anytime parking, use <strong>Lot X</strong> on North campus.
                        </div>
                      )}
                      <Form form={guestForm} layout="vertical" onFinish={submitGuest}>
                        <Form.Item name="guest_name" label="Guest name" rules={[{ required: true, message: "Enter your guest's name" }]}>
                          <Input placeholder="Full name" />
                        </Form.Item>
                        <div className="grid grid-cols-3 gap-3">
                          <Form.Item name="guest_plate" label="Vehicle plate" className="col-span-2" rules={[{ required: true, message: "License plate is required" }]}>
                            <Input placeholder="License plate number" style={{ textTransform: "uppercase" }} />
                          </Form.Item>
                          <Form.Item name="guest_plate_state" label="State" initialValue="PA">
                            <Select options={["PA","NJ","NY","CT","DE","MD","VA","MA","OH"].map(s => ({ label: s, value: s }))} />
                          </Form.Item>
                        </div>
                        <Form.Item name="dates" label="Check-in / Check-out" rules={[{ required: true, message: "Select dates" }]}>
                          <DatePicker.RangePicker
                            disabledDate={(d) => d.isBefore(dayjs().startOf("day"))}
                            format="MMM D, YYYY"
                            style={{ width: "100%" }}
                          />
                        </Form.Item>
                        <Form.Item
                          name="roommate_consent"
                          valuePropName="checked"
                          rules={[{ validator: (_, v) => v ? Promise.resolve() : Promise.reject("Roommate consent is required") }]}
                        >
                          <Checkbox>
                            All roommates have given expressed consent for this overnight guest
                          </Checkbox>
                        </Form.Item>
                        <Form.Item name="notes" label="Notes (optional)">
                          <Input.TextArea rows={2} placeholder="Any additional details" />
                        </Form.Item>
                        <div className="flex gap-2">
                          <Button type="primary" htmlType="submit" loading={guestSubmitting}>
                            Register Guest
                          </Button>
                          <Button onClick={() => { setShowGuestForm(false); guestForm.resetFields(); }}>
                            Cancel
                          </Button>
                        </div>
                      </Form>

                      <div className="mt-3 text-xs text-gray-500 space-y-1">
                        <p className="m-0"><strong>Visitation hours:</strong> Weekdays 10 AM - 2 AM. Weekends: 24-hour access Friday 10 AM through Monday 2 AM (with roommate approval).</p>
                        <p className="m-0"><strong>Host responsibility:</strong> You must stay with your guest the entire time they are in the residential area.</p>
                        <p className="m-0">Questions? Contact Housing at housing@moravian.edu or your RA.</p>
                      </div>
                    </div>
                  )}

                  {guestRegs.filter(g => g.status === "active").length > 0 && (
                    <div className="space-y-2">
                      <h4 className="text-sm font-medium m-0 text-gray-700">Your registered guests</h4>
                      {guestRegs.filter(g => g.status === "active").map((g) => (
                        <div key={g.id} className="rounded-lg border border-pink-200 bg-pink-50/40 p-3">
                          <div className="flex items-center justify-between">
                            <div>
                              <span className="font-medium">{g.guest_name}</span>
                              {g.guest_plate && (
                                <span className="text-sm text-gray-500 ml-2">{g.guest_plate} ({g.guest_plate_state})</span>
                              )}
                              <span className="text-sm text-gray-500 ml-2">
                                {new Date(g.check_in + "T00:00").toLocaleDateString()} - {new Date(g.check_out + "T00:00").toLocaleDateString()}
                              </span>
                              {new Date(g.check_out) < new Date() ? (
                                <Tag className="ml-2" color="default">Completed</Tag>
                              ) : (
                                <>
                                  <Tag className="ml-2" color="green">Active</Tag>
                                  <Tag className="ml-1" color="pink">Guest Permit</Tag>
                                </>
                              )}
                            </div>
                            {new Date(g.check_out) >= new Date() && (
                              <Button size="small" danger onClick={() => cancelGuest(g.id)}>Cancel</Button>
                            )}
                          </div>
                          {new Date(g.check_out) >= new Date() && (
                            <div className="mt-2 pt-2 border-t border-pink-100">
                              <p className="text-xs font-semibold text-gray-700 m-0 mb-1">Authorized parking lots:</p>
                              <div className="flex flex-wrap gap-1">
                                <span className="inline-block rounded bg-green-100 text-green-800 text-xs font-medium px-2 py-0.5">X <span className="text-green-600 font-normal">(anytime)</span></span>
                                {["A", "F", "H", "M", "N", "O", "R", "S"].map(lot => (
                                  <span key={lot} className="inline-block rounded bg-yellow-100 text-yellow-800 text-xs font-medium px-2 py-0.5">{lot}</span>
                                ))}
                                <span className="inline-block rounded bg-yellow-100 text-yellow-800 text-xs font-medium px-2 py-0.5">U <span className="text-yellow-600 font-normal">(south)</span></span>
                              </div>
                              <div className="flex items-center gap-3 mt-1.5 text-xs text-gray-500">
                                <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-green-500"></span> Park anytime</span>
                                <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm bg-yellow-500"></span> After 4 PM &amp; weekends only</span>
                              </div>
                              <p className="text-xs text-gray-600 m-0 mt-1.5">
                                <strong>Valid:</strong> {new Date(g.check_in + "T00:00").toLocaleDateString()} – {new Date(g.check_out + "T00:00").toLocaleDateString()}
                              </p>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </Card>
            )}

            {!application && step === "intake" && (cycle || isCommuterPath) && (
              <Card title={isCommuterPath ? "Commuter Permit — Your Info" : "1. About you"}>
                <Form layout="vertical" onFinish={continueToRank}>
                  {housingStatus && (
                    <div className="mb-3 text-sm">
                      <Tag color={housingStatus === "C" ? "blue" : "green"}>
                        {housingStatus === "C" ? "Commuter Student" : "Resident Student"}
                      </Tag>
                      <span className="text-gray-500 ml-1">per university records</span>
                    </div>
                  )}
                  {cycle && !isCommuterPath && !housingStatus && (
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
                        : cycle?.status === "drawn"
                          ? "Continue — join waitlist"
                          : "Continue — available permits"}
                  </Button>
                </Form>
              </Card>
            )}

            {step === "intake" && !isCommuterPath && commuterTiers.length > 0 && housingStatus !== "R" && (
              <Card title="Commuter Permits">
                <p className="text-sm text-gray-500 mb-2">
                  Commuter parking permits are available for direct purchase — no lottery required.
                </p>
                <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4">
                  These permits are for <strong>commuters only</strong>. We verify eligibility — do not buy one if you live on campus.
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
                        <div className="font-bold text-brand-primary">{formatTierPrice(tier)}</div>
                        {tier.discount_label && (
                          <div className="text-[10px] text-green-700">{tier.discount_label}</div>
                        )}
                        {tier.remaining > 0 ? (
                          <Button
                            type="primary"
                            size="small"
                            className="mt-1"
                            onClick={() => { setCampus("commuter"); setTiers(commuterTiers); setRanked([]); setStep("intake"); }}
                          >
                            Buy Now
                          </Button>
                        ) : (
                          <Tag className="mt-1">Unavailable</Tag>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {!application && step === "choose" && (
              <Card
                title={
                  !cycle && isCommuterPath
                    ? "Commuter Permits"
                    : cycle?.status === "drawn" && !isCommuterPath
                      ? "2. Join a waitlist"
                      : "2. Choose your permit"
                }
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
                {tiers.length === 0 ? (
                  <p className="text-gray-500">No permits are available for your class year.</p>
                ) : (
                  <>
                    <p className="text-sm text-gray-500 mb-4">
                      {isCommuterPath
                        ? "Map colors: blue = full-time, amber = after 4 PM & weekends, teal = street. Hover a permit to emphasize its lots."
                        : cycle?.status === "drawn"
                          ? "Lottery is complete. Join the waitlist for any permit type below."
                          : "Join the waitlist for any permit type below."}
                    </p>
                    {isCommuterPath && (
                      <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4">
                        These permits are for <strong>commuters only</strong>. We verify eligibility — do not buy one if you live on campus.
                      </p>
                    )}
                    {cycle?.status === "drawn" && !isCommuterPath && (
                      <Alert
                        type="info"
                        showIcon
                        className="mb-4"
                        message="Waitlists are open for every resident permit type"
                        description="Join any waitlist below. You'll be notified when a spot opens."
                      />
                    )}

                    <ul className="space-y-2 list-none p-0 m-0">
                      {tiers.map((tier, i) => {
                        const colors = tierColor(tier, i);
                        const isHovered = hoveredTierId === tier.id;
                        const soldOut = tier.remaining <= 0;
                        const showWaitlist = cycle?.status === "drawn" && !isCommuterPath;
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
                                  {formatTierPrice(tier)}
                                </p>
                                {tier.discount_label && (
                                  <p className="m-0 text-[10px] text-green-700 mt-0.5">{tier.discount_label} applied</p>
                                )}
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
                              {isCommuterPath ? (
                                <Button
                                  type="primary"
                                  size="small"
                                  loading={submitting}
                                  onClick={() => purchaseCommuterPermit(tier)}
                                >
                                  Buy
                                </Button>
                              ) : (
                                <Button
                                  size="small"
                                  loading={submitting}
                                  onClick={() => joinWaitlist(tier)}
                                >
                                  Join waitlist
                                </Button>
                              )}
                            </div>
                          </li>
                        );
                      })}
                    </ul>

                    {cycle?.status === "drawn" && !isCommuterPath && (
                      <div className="mt-4 pt-4 border-t">
                        <p className="text-sm text-gray-600 mb-2">
                          Want backups? Rank several permits and we'll add you to each waitlist in order.
                        </p>
                        <Button
                          block
                          onClick={() => {
                            setRanked([]);
                            setStep("rank");
                          }}
                        >
                          Rank multiple for waitlist
                        </Button>
                      </div>
                    )}
                  </>
                )}
              </Card>
            )}

            {!application && (cycle?.status === "open" || cycle?.status === "drawn") && step === "rank" && !isCommuterPath && (
              <Card
                title={cycle?.status === "drawn" ? "2. Rank for waitlist" : "2. Rank your tiers"}
                extra={
                  <Button
                    type="link"
                    onClick={() => {
                      setStep(cycle?.status === "drawn" ? "choose" : "intake");
                      setHighlightedLots([]);
                      setHoveredTierId(null);
                      setFocusedLot(null);
                    }}
                  >
                    Back
                  </Button>
                }
              >
                {tiers.length === 0 ? (
                  <p className="text-gray-500">
                    No tiers are available for your campus and class year.
                  </p>
                ) : (
                  <>
                    <p className="text-sm text-gray-500 mb-4">
                      {cycle?.status === "drawn"
                        ? "Add permits in order. We'll add you to the waitlist for each."
                        : "Tap Add in the order you want seats tried. #1 is offered first — Premium and Guaranteed are different permits and prices. Hover a tier to see its lots on the map."}
                    </p>

                    {unrankedTiers.length > 0 && (
                      <div className="mb-5">
                        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                          Available to add
                        </p>
                        <ul className="space-y-2 list-none p-0 m-0">
                          {unrankedTiers.map((tier, i) => {
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
                                    {tier.lot_assignments.length
                                      ? ` · lots ${tier.lot_assignments.join(", ")}`
                                      : ""}
                                  </p>
                                </div>
                                <Button
                                  size="small"
                                  type="default"
                                  icon={<PlusOutlined />}
                                  onClick={() => addTier(tier)}
                                >
                                  Add
                                </Button>
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    )}

                    <div className="mb-6">
                      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                        Your ranking
                      </p>
                      {ranked.length === 0 ? (
                        <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 m-0">
                          Nothing ranked yet. Add the permit you want most first (that becomes #1).
                        </p>
                      ) : (
                        <ul className="space-y-2 list-none p-0 m-0">
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
                                    {i === 0 && (
                                      <Tag color="green" className="m-0">
                                        First choice
                                      </Tag>
                                    )}
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
                                  <Button
                                    size="small"
                                    danger
                                    icon={<DeleteOutlined />}
                                    onClick={() => removeTier(i)}
                                  />
                                </Space>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </div>

                    {ranked.length > 0 && (
                      <Alert
                        type="info"
                        showIcon
                        className="mb-4"
                        message={`First choice: ${ranked[0].label} ($${Number(ranked[0].price).toFixed(0)})`}
                        description={
                          ranked[0].lot_assignments?.length
                            ? `Allowed lots: ${ranked[0].lot_assignments.join(", ")}`
                            : undefined
                        }
                      />
                    )}

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
                    <Button
                      type="primary"
                      loading={submitting}
                      onClick={submit}
                      block
                      disabled={ranked.length === 0}
                    >
                      {ranked.length === 0
                        ? "Add a permit type to continue"
                        : cycle?.status === "drawn"
                          ? `Submit waitlist — ${ranked[0].label} first`
                          : `Submit — ${ranked[0].label} first`}
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
