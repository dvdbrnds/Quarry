import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Card, Checkbox, Tag, Empty, Form, Input, InputNumber, Spin, Space, App, Tooltip, Modal } from "antd";
import { initAuth, isAuthenticated, login, authHeaders, logout, fetchCurrentUser, loadConfig, type AuthUser } from "../auth";
import type { Lot } from "../api";
import StudentLotMap from "../components/StudentLotMap";
import { useBranding } from "../useBranding";

const CAMPUS_LAT_THRESHOLD = 40.623;

interface LotDetail {
  name: string;
  designation_code: string;
  is_time_restricted: boolean;
  restriction_label: string;
}

interface AvailablePermit {
  id: string; code: string; label: string; eligible: string; price: string;
  max_capacity: number; remaining: number; lot_assignments: string[];
  lot_details: LotDetail[];
  valid_days: number; min_class_year: number | null;
  allow_multiple: boolean;
  application_closes_at: string | null; requires_lottery: boolean;
}

interface MyApplication {
  id: string; student_name: string; class_year: number; plate: string; plate_state: string;
  status: string; permit_type_label: string; permit_type_code: string;
  permit_type_price: string; lot_assignments: string[];
  lot_details: LotDetail[];
  lot_preferences: string[]; assigned_lot: string | null;
  waitlist_position: number | null; offer_expires_at: string | null; created_at: string;
  permit_id: string | null; current_plate: string | null;
  last_plate_change: string | null; next_swap_available: string | null; can_swap: boolean;
}

interface OktaProfile {
  display_name: string; given_name: string; family_name: string;
  email: string; class_year: number | null;
}

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  pending: { text: "Entered in lottery", color: "gold" },
  selected: { text: "Selected — accept your offer!", color: "green" },
  waitlisted: { text: "Waitlisted", color: "blue" },
  accepted: { text: "Permit active", color: "lime" },
  expired: { text: "Offer expired", color: "default" },
  declined: { text: "Declined", color: "default" },
};

export default function LotteryApply() {
  const [authState, setAuthState] = useState<"loading" | "ready" | "error">("loading");
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    (async () => {
      try {
        await initAuth();
        const authed = await isAuthenticated();
        if (!authed) { sessionStorage.setItem("quarry_return_path", "/parking"); await login(); return; }
        const u = await fetchCurrentUser();
        // Faculty/staff (not Quarry admins) go to employee parking enrollment
        if (u?.role === "staff") {
          window.location.replace("/employee-parking");
          return;
        }
        setUser(u);
        setAuthState(u ? "ready" : "error");
      } catch { setAuthState("error"); }
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
          <p className="text-gray-500 mb-4">We couldn't verify your identity. Make sure you're using your university account.</p>
          <Button onClick={() => window.location.reload()}>Try Again</Button>
        </Card>
      </div>
    );
  }

  return (
    <App>
      <LotteryPage user={user} />
    </App>
  );
}

function CampusToggle({ active, onChange }: { active: "north" | "south" | null; onChange: (c: "north" | "south") => void }) {
  return (
    <div className="flex gap-1 mt-2">
      {([["north", "North Campus"], ["south", "South Campus"]] as const).map(([key, label]) => (
        <button
          key={key}
          onClick={(e) => { e.stopPropagation(); onChange(key); }}
          className={`text-[11px] px-2.5 py-1 rounded-full transition-colors font-medium ${
            active === key
              ? "bg-blue-600 text-white"
              : "bg-gray-100 text-gray-500 hover:bg-gray-200"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function LotTags({ details }: { details: LotDetail[] }) {
  if (!details?.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {details.map(d => (
        d.is_time_restricted ? (
          <Tooltip key={d.name} title={d.restriction_label}>
            <Tag color="gold" className="!text-xs">Lot {d.name} *</Tag>
          </Tooltip>
        ) : (
          <Tag key={d.name} color="blue" className="!text-xs">Lot {d.name}</Tag>
        )
      ))}
    </span>
  );
}

function LotteryPage({ user }: { user: AuthUser }) {
  const brand = useBranding();
  const { modal, message } = App.useApp();
  const [available, setAvailable] = useState<AvailablePermit[]>([]);
  const [applications, setApplications] = useState<MyApplication[]>([]);
  const [applying, setApplying] = useState<AvailablePermit | null>(null);
  const [buying, setBuying] = useState<AvailablePermit | null>(null);
  const [loading, setLoading] = useState(true);
  const [lots, setLots] = useState<Lot[]>([]);
  const [highlightedLots, setHighlightedLots] = useState<string[]>([]);
  const [campusFilter, setCampusFilter] = useState<"north" | "south" | null>(null);
  const [focusedLot, setFocusedLot] = useState<string | null>(null);
  const [mapsApiKey, setMapsApiKey] = useState("");
  const [campusCenter, setCampusCenter] = useState<{ lat: number; lng: number } | undefined>();
  const [swapping, setSwapping] = useState<MyApplication | null>(null);
  const [swapPlate, setSwapPlate] = useState("");
  const [swapState, setSwapState] = useState("");
  const [swapLoading, setSwapLoading] = useState(false);

  /** Map lot name → campus ("north" | "south") using centroid latitude */
  const lotCampusMap = useMemo(() => {
    const m: Record<string, "north" | "south"> = {};
    for (const lot of lots) {
      if (lot.boundary.length < 3) continue;
      const avgLat = lot.boundary.reduce((s, c) => s + c.latitude, 0) / lot.boundary.length;
      const normalized = lot.name.replace(/^lot\s+/i, "").trim().toLowerCase();
      m[normalized] = avgLat >= CAMPUS_LAT_THRESHOLD ? "north" : "south";
    }
    return m;
  }, [lots]);

  /** Check if a set of lot assignments spans both campuses */
  function spansBothCampuses(lotAssignments: string[]): boolean {
    let hasNorth = false, hasSouth = false;
    for (const name of lotAssignments) {
      const campus = lotCampusMap[name.replace(/^lot\s+/i, "").trim().toLowerCase()];
      if (campus === "north") hasNorth = true;
      if (campus === "south") hasSouth = true;
      if (hasNorth && hasSouth) return true;
    }
    return false;
  }

  /** Filter lot assignments to a single campus */
  function filterLotsByCampus(lotAssignments: string[], campus: "north" | "south"): string[] {
    return lotAssignments.filter(name => {
      const c = lotCampusMap[name.replace(/^lot\s+/i, "").trim().toLowerCase()];
      return c === campus;
    });
  }

  /** The actual highlighted lots sent to the map (filtered if campus toggle active) */

  const load = useCallback(async () => {
    try {
      const headers = await authHeaders();
      const [avRes, myRes, lotsRes] = await Promise.all([
        fetch("/api/student/permits/available", { headers }),
        fetch("/api/student/permits/my-applications", { headers }),
        fetch("/api/lots", { headers }),
      ]);
      if (avRes.ok) setAvailable(await avRes.json());
      if (myRes.ok) setApplications(await myRes.json());
      if (lotsRes.ok) setLots(await lotsRes.json());
    } catch { message.error("Failed to load permit data"); } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    load();
    loadConfig().then(cfg => {
      setMapsApiKey(cfg.google_maps_api_key || "");
      if (cfg.campus_lat && cfg.campus_lng) setCampusCenter({ lat: cfg.campus_lat, lng: cfg.campus_lng });
    });
  }, [load]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("accepted")) {
      message.success("Payment received — your permit is now active!");
      window.history.replaceState({}, "", "/parking");
      load();
    }
    if (params.get("purchased")) {
      message.success("Payment received — your permit is now active!");
      window.history.replaceState({}, "", "/parking");
      load();
    }
  }, [load]);

  async function handleAccept(appId: string) {
    try {
      const res = await fetch(`/api/student/permits/${appId}/accept`, { method: "POST", headers: await authHeaders() });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Accept failed"); }
      const { checkout_url } = await res.json();
      window.location.href = checkout_url;
    } catch (e: any) { message.error(e.message); }
  }

  function handleDecline(appId: string) {
    modal.confirm({
      title: "Decline this offer?",
      content: "Your spot will go to the next person on the waitlist. This cannot be undone.",
      okText: "Decline Offer", okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const res = await fetch(`/api/student/permits/${appId}/decline`, { method: "POST", headers: await authHeaders() });
          if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Decline failed"); }
          message.success("Offer declined"); load();
        } catch (e: any) { message.error(e.message); }
      },
    });
  }

  async function handleSwapVehicle() {
    if (!swapping?.permit_id || !swapPlate.trim()) return;
    setSwapLoading(true);
    try {
      const res = await fetch("/api/student/permits/swap-vehicle", {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({
          permit_id: swapping.permit_id,
          new_plate: swapPlate.trim(),
          new_plate_state: swapState.trim(),
        }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new Error((b as any).detail || `Failed (${res.status})`);
      }
      message.success(`Vehicle updated to ${swapPlate.trim().toUpperCase()}`);
      setSwapping(null);
      setSwapPlate("");
      setSwapState("");
      load();
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setSwapLoading(false);
    }
  }

  const appliedTypeIds = new Set(applications.filter(a => !["expired", "declined"].includes(a.status)).map(a => a.permit_type_code));

  // Keep lots highlighted while applying/buying
  const activeHighlightedLots = useMemo(() => {
    if (applying) return applying.lot_assignments;
    if (buying) return buying.lot_assignments;
    return highlightedLots;
  }, [applying, buying, highlightedLots]);

  const activeEffectiveHighlightedLots = useMemo(() => {
    if (!campusFilter || activeHighlightedLots.length === 0) return activeHighlightedLots;
    return filterLotsByCampus(activeHighlightedLots, campusFilter);
  }, [activeHighlightedLots, campusFilter, lotCampusMap]);

  return (
    <div className="min-h-screen bg-gray-50">
      <nav style={{ background: brand.primaryColor }} className="text-white/90 px-6 py-4 shadow-md">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            {brand.logoUrl && <img src={brand.logoUrl} alt={brand.brandName} className="h-8 w-auto" />}
            <div>
              <h1 style={{ color: brand.accentColor }} className="text-lg font-bold">{brand.brandName}</h1>
              <span className="text-xs text-white/50">Parking Permits</span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm text-white/70">{user.email}</span>
            <button onClick={() => logout()} className="text-xs text-white/40 hover:text-white transition-colors">Sign out</button>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-6 py-10">
        {loading ? (
          <div className="flex justify-center py-20"><Spin size="large" /></div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Mobile map (shown above cards on small screens) */}
            {mapsApiKey && lots.length > 0 && (
              <div className="lg:hidden h-[300px] rounded-xl overflow-hidden shadow">
                <StudentLotMap apiKey={mapsApiKey} lots={lots} highlightedLots={activeEffectiveHighlightedLots} focusedLot={focusedLot} defaultCenter={campusCenter} />
              </div>
            )}

            {/* Permit cards column */}
            <div className="lg:col-span-1 space-y-8">
              {/* Inline apply/buy form (replaces cards while open) */}
              {applying && (
                <ApplyPanel permit={applying} onClose={() => { setApplying(null); setFocusedLot(null); }}
                  onSuccess={() => { setApplying(null); setFocusedLot(null); message.success("Application submitted! You're entered in the lottery."); load(); }}
                  onError={msg => { message.error(msg); setApplying(null); setFocusedLot(null); }}
                  onLotHover={setFocusedLot} />
              )}
              {buying && (
                <BuyPanel permit={buying} onClose={() => setBuying(null)}
                  onError={msg => { message.error(msg); setBuying(null); }} />
              )}

              {!applying && !buying && (
              <>
              <div>
                <h2 className="text-2xl font-bold text-brand-primary">Parking Permits</h2>
                <p className="text-gray-500 mt-1">Purchase a permit or apply for a lottery below. Hover over a permit to see its lots on the map.</p>
              </div>

              {applications.length > 0 && (
                <div>
                  <h3 className="text-lg font-semibold text-brand-primary mb-3">Your Applications</h3>
                  <div className="space-y-3">
                    {applications.map(app => {
                      const st = STATUS_LABELS[app.status] || { text: app.status, color: "default" };
                      const isDone = ["expired", "declined"].includes(app.status);
                      return (
                        <Card
                          key={app.id}
                          className={`transition-shadow ${isDone ? "opacity-50" : "hover:shadow-md"}`}
                          onMouseEnter={() => { if (!isDone) { setHighlightedLots(app.lot_assignments); setCampusFilter(spansBothCampuses(app.lot_assignments) ? "north" : null); } }}
                          onMouseLeave={() => { setHighlightedLots([]); setCampusFilter(null); }}
                        >
                          <div className="flex items-start justify-between gap-4">
                            <div>
                              <div className="font-semibold text-brand-primary">{app.permit_type_label}</div>
                              <div className="text-xs text-gray-500 mt-1">
                                Plate: <span className="font-mono font-medium">{app.status === "accepted" && app.current_plate ? app.current_plate : app.plate}</span>{app.plate_state && <span className="text-gray-400"> ({app.plate_state})</span>}{app.class_year > 0 && <> &middot; Class of {app.class_year}</>}
                              </div>
                              <div className="text-xs text-gray-500 mt-1">
                                {app.lot_details?.length ? <LotTags details={app.lot_details} /> : <>Lots: {app.lot_assignments.join(", ")}</>}
                              </div>
                              {!isDone && spansBothCampuses(app.lot_assignments) && highlightedLots.length > 0 && (
                                <CampusToggle active={campusFilter} onChange={setCampusFilter} />
                              )}
                              {app.assigned_lot && <div className="text-xs text-green-700 font-medium mt-1">Assigned: Lot {app.assigned_lot}</div>}
                              {app.status === "waitlisted" && app.waitlist_position != null && (
                                <div className="text-xs text-blue-600 mt-1">Waitlist position #{app.waitlist_position}</div>
                              )}
                              {app.status === "selected" && app.offer_expires_at && (
                                <div className="text-sm text-green-700 font-medium mt-2">
                                  Accept by {new Date(app.offer_expires_at).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
                                </div>
                              )}
                            </div>
                            <div className="flex flex-col items-end gap-2">
                              <Tag color={st.color}>{st.text}</Tag>
                              {app.status === "selected" && (
                                <Space>
                                  <Button type="primary" size="small" onClick={() => handleAccept(app.id)}>Accept &amp; Pay ${Number(app.permit_type_price).toFixed(0)}</Button>
                                  <Button size="small" danger onClick={() => handleDecline(app.id)}>Decline</Button>
                                </Space>
                              )}
                              {app.status === "accepted" && app.permit_id && (
                                <div className="flex flex-col items-end gap-1">
                                  {app.can_swap ? (
                                    <Button size="small" onClick={() => { setSwapping(app); setSwapPlate(""); setSwapState(""); }}>
                                      Change Vehicle
                                    </Button>
                                  ) : app.next_swap_available ? (
                                    <Tooltip title={`Next change available ${new Date(app.next_swap_available).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`}>
                                      <Button size="small" disabled>Change Vehicle</Button>
                                    </Tooltip>
                                  ) : null}
                                </div>
                              )}
                            </div>
                          </div>
                        </Card>
                      );
                    })}
                  </div>
                </div>
              )}

              {available.length > 0 && (
                <div>
                  <h3 className="text-lg font-semibold text-brand-primary mb-3">Open Permits</h3>
                  <div className="space-y-4">
                    {available.map(pt => {
                      const alreadyApplied = appliedTypeIds.has(pt.code);
                      return (
                        <Card
                          key={pt.id}
                          className="transition-shadow hover:shadow-md"
                          onMouseEnter={() => { setHighlightedLots(pt.lot_assignments); setCampusFilter(spansBothCampuses(pt.lot_assignments) ? "north" : null); }}
                          onMouseLeave={() => { setHighlightedLots([]); setCampusFilter(null); }}
                        >
                          <div className="flex items-start justify-between">
                            <div className="flex-1">
                              <div className="flex items-center gap-2">
                                <span className="font-semibold text-brand-primary text-lg">{pt.label}</span>
                                {pt.requires_lottery ? <Tag color="purple">Lottery</Tag> : <Tag color="green">Available Now</Tag>}
                              </div>
                              <p className="text-sm text-gray-500 mt-1">{pt.eligible}</p>
                              <div className="text-sm text-gray-500 mt-2">
                                <div className="flex items-center flex-wrap gap-1">
                                  <span>Lots:</span>
                                  {pt.lot_details?.length ? <LotTags details={pt.lot_details} /> : <span className="font-medium">{pt.lot_assignments.join(", ")}</span>}
                                </div>
                                <div className="mt-1">Valid {pt.valid_days} days</div>
                                {pt.lot_details?.some(d => d.is_time_restricted) && (
                                  <div className="text-xs text-amber-700 mt-1">* Evening & weekend access only (after 4 PM weekdays, all day Sat/Sun)</div>
                                )}
                              </div>
                              {spansBothCampuses(pt.lot_assignments) && highlightedLots.length > 0 && (
                                <CampusToggle active={campusFilter} onChange={setCampusFilter} />
                              )}
                              <div className="flex items-center gap-4 mt-2">
                                {pt.application_closes_at && (
                                  <span className="text-xs text-amber-700 font-medium">
                                    Deadline: {new Date(pt.application_closes_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" })}
                                  </span>
                                )}
                              </div>
                              {pt.min_class_year && <div className="text-xs text-gray-400 mt-1">Eligibility: Class of {pt.min_class_year} or earlier</div>}
                            </div>
                            <div className="text-right ml-6">
                              <div className="text-2xl font-bold text-brand-primary">${Number(pt.price).toFixed(0)}</div>
                              <div className="mt-3">
                                {alreadyApplied ? (
                                  <Tag color="blue">Applied</Tag>
                                ) : pt.remaining <= 0 ? (
                                  <Tag color="red">Full</Tag>
                                ) : pt.requires_lottery ? (
                                  <Button type="primary" onClick={() => setApplying(pt)} style={{ background: brand.primaryColor }}>Apply Now</Button>
                                ) : (
                                  <Button type="primary" onClick={() => setBuying(pt)} style={{ background: brand.primaryColor }}>Buy Now</Button>
                                )}
                              </div>
                            </div>
                          </div>
                        </Card>
                      );
                    })}
                  </div>
                </div>
              )}

              {available.length === 0 && applications.length === 0 && (
                <Card className="text-center py-12">
                  <Empty description={<span className="text-gray-500">No permits are currently available. Check back later.</span>} />
                </Card>
              )}

              <div className="text-center text-xs text-gray-400 pt-4 border-t">
                {brand.schoolName || "Campus"} {brand.departmentName} — {brand.brandName}
              </div>
              </>
              )}
            </div>

            {/* Desktop map (sticky on the right) */}
            {mapsApiKey && lots.length > 0 && (
              <div className="hidden lg:block lg:col-span-2 min-w-0">
                <div className="sticky top-6 h-[calc(100vh-8rem)] rounded-xl overflow-hidden shadow-lg">
                  <StudentLotMap apiKey={mapsApiKey} lots={lots} highlightedLots={activeEffectiveHighlightedLots} focusedLot={focusedLot} defaultCenter={campusCenter} />
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      <Modal
        title="Change Vehicle"
        open={!!swapping}
        onCancel={() => { setSwapping(null); setSwapPlate(""); setSwapState(""); }}
        onOk={handleSwapVehicle}
        okText="Update Vehicle"
        okButtonProps={{ loading: swapLoading, disabled: !swapPlate.trim() }}
        cancelButtonProps={{ disabled: swapLoading }}
      >
        {swapping && (
          <div className="space-y-4 py-2">
            <p className="text-sm text-gray-600">
              Current plate: <span className="font-mono font-bold">{swapping.current_plate || swapping.plate}</span>
            </p>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">New License Plate</label>
              <Input
                value={swapPlate}
                onChange={e => setSwapPlate(e.target.value.toUpperCase())}
                placeholder="ABC1234"
                className="font-mono"
                maxLength={12}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">State (optional)</label>
              <Input
                value={swapState}
                onChange={e => setSwapState(e.target.value.toUpperCase())}
                placeholder="PA"
                className="font-mono"
                maxLength={2}
              />
            </div>
            <p className="text-xs text-gray-400">
              You can change your vehicle once per week. After this change, the next swap will be available in 7 days.
            </p>
          </div>
        )}
      </Modal>
    </div>
  );
}

function ApplyPanel({ permit, onClose, onSuccess, onError, onLotHover }: {
  permit: AvailablePermit | null; onClose: () => void; onSuccess: () => void; onError: (msg: string) => void;
  onLotHover?: (lot: string | null) => void;
}) {
  const brand = useBranding();
  const [form] = Form.useForm();
  const [lotPreferences, setLotPreferences] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [profile, setProfile] = useState<OktaProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);

  useEffect(() => {
    if (permit) {
      form.resetFields();
      setLotPreferences(permit.lot_assignments);
      setProfileLoading(true);
      (async () => {
        try {
          const res = await fetch("/api/auth/profile", { headers: await authHeaders() });
          if (res.ok) {
            const p: OktaProfile = await res.json();
            setProfile(p);
            const prefill: Record<string, unknown> = {};
            if (p.display_name) prefill.name = p.display_name;
            if (p.class_year) prefill.class_year = p.class_year;
            form.setFieldsValue(prefill);
          }
        } catch { /* manual entry fallback */ }
        finally { setProfileLoading(false); }
      })();
    }
  }, [permit, form]);

  function moveLot(index: number, direction: -1 | 1) {
    const n = [...lotPreferences];
    const t = index + direction;
    if (t < 0 || t >= n.length) return;
    [n[index], n[t]] = [n[t], n[index]];
    setLotPreferences(n);
  }

  async function handleFinish(values: any) {
    if (!permit) return;
    setSubmitting(true);
    try {
      const res = await fetch("/api/student/permits/apply", {
        method: "POST", headers: await authHeaders(),
        body: JSON.stringify({
          permit_type_id: permit.id, student_name: values.name,
          plate: values.plate.toUpperCase().trim(), plate_state: (values.plate_state || "").toUpperCase().trim(),
          class_year: values.class_year || 0, phone: values.phone || null, lot_preferences: lotPreferences,
          sms_opt_in: !!values.sms_opt_in,
        }),
      });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Application failed"); }
      onSuccess();
    } catch (e: any) { onError(e.message); onClose(); } finally { setSubmitting(false); }
  }

  const nameFromOkta = !!profile?.display_name;
  const classYearFromOkta = !!profile?.class_year;

  return (
    <Card className="shadow-md border-2 border-brand-primary/20">
      {permit && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-lg font-bold text-brand-primary">Apply for {permit.label}</h3>
            <Button type="text" size="small" onClick={onClose}>✕</Button>
          </div>
          <div className="flex items-center justify-between mb-4 pb-3 border-b">
            <span className="text-gray-500">{permit.eligible}</span>
            <span className="text-lg font-bold text-brand-primary">${Number(permit.price).toFixed(0)}</span>
          </div>
          <div className="text-xs text-gray-500 mb-4">
            <div className="flex items-center gap-1 flex-wrap">
              <span className="font-medium">Lots highlighted on map:</span>
              {permit.lot_details?.length ? <LotTags details={permit.lot_details} /> : <span>{permit.lot_assignments.join(", ")}</span>}
            </div>
          </div>
          {profileLoading ? <div className="flex justify-center py-4"><Spin size="small" /></div> : (
            <Form form={form} layout="vertical" onFinish={handleFinish} size="small">
              <Form.Item name="name" label="Full Name" rules={[{ required: true }]} tooltip={nameFromOkta ? "From your university account" : undefined}>
                <Input disabled={nameFromOkta} className={nameFromOkta ? "bg-gray-50" : ""} />
              </Form.Item>
              <div className="grid grid-cols-3 gap-3">
                <Form.Item name="plate" label="License Plate" rules={[{ required: true }]} className="col-span-2">
                  <Input placeholder="ABC1234" className="font-mono" />
                </Form.Item>
                <Form.Item name="plate_state" label="State" rules={[{ required: true, message: "State required" }]}>
                  <Input placeholder="PA" maxLength={2} className="font-mono uppercase" />
                </Form.Item>
              </div>
              {!permit.allow_multiple && (
                <Form.Item name="class_year" label="Graduation Year" rules={[{ required: !permit.allow_multiple }]} tooltip={classYearFromOkta ? "From your university account" : undefined}>
                  <InputNumber min={2024} max={2035} placeholder="2027" className="w-full" disabled={classYearFromOkta} />
                </Form.Item>
              )}
              <Form.Item name="phone" label="Mobile Phone" rules={[{ required: true, message: "Cell phone is required" }]}>
                <Input placeholder="610-555-0123" />
              </Form.Item>
              <Form.Item name="sms_opt_in" valuePropName="checked" initialValue={true}>
                <Checkbox>
                  <span className="text-xs text-gray-600">
                    Send me text messages about my permit, lot closures, weather alerts, and campus emergency notifications
                  </span>
                </Checkbox>
              </Form.Item>
              {permit.lot_assignments.length > 1 && (
                <Form.Item label="Lot Preference (reorder — #1 is top choice)">
                  <div className="space-y-1.5">
                    {lotPreferences.map((lot, idx) => {
                      const detail = permit.lot_details?.find(d => d.name === lot);
                      return (
                        <div key={lot}
                          className={`flex items-center gap-2 rounded-lg px-3 py-2 cursor-pointer transition-colors ${detail?.is_time_restricted ? "bg-amber-50 border border-amber-200 hover:bg-amber-100" : "bg-gray-50 hover:bg-blue-50 hover:border-blue-200 border border-transparent"}`}
                          onMouseEnter={() => onLotHover?.(lot)}
                          onMouseLeave={() => onLotHover?.(null)}
                        >
                          <span className="text-xs font-bold text-gray-400 w-5">{idx + 1}.</span>
                          <div className="flex-1">
                            <span className="text-sm font-medium">Lot {lot}</span>
                            {detail?.is_time_restricted && (
                              <div className="text-[11px] text-amber-700">Evening & weekends only</div>
                            )}
                          </div>
                          <Button type="text" size="small" disabled={idx === 0} onClick={() => moveLot(idx, -1)}>▲</Button>
                          <Button type="text" size="small" disabled={idx === lotPreferences.length - 1} onClick={() => moveLot(idx, 1)}>▼</Button>
                        </div>
                      );
                    })}
                  </div>
                </Form.Item>
              )}
              <div className="flex justify-end gap-3 pt-4 border-t mt-4">
                <Button onClick={onClose}>Cancel</Button>
                <Button type="primary" htmlType="submit" loading={submitting} style={{ background: brand.primaryColor }}>Submit Application</Button>
              </div>
            </Form>
          )}
        </div>
      )}
    </Card>
  );
}

function BuyPanel({ permit, onClose, onError }: {
  permit: AvailablePermit | null; onClose: () => void; onError: (msg: string) => void;
}) {
  const brand = useBranding();
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [profile, setProfile] = useState<OktaProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);

  useEffect(() => {
    if (permit) {
      form.resetFields();
      setProfileLoading(true);
      (async () => {
        try {
          const res = await fetch("/api/auth/profile", { headers: await authHeaders() });
          if (res.ok) {
            const p: OktaProfile = await res.json();
            setProfile(p);
            const prefill: Record<string, unknown> = {};
            if (p.display_name) prefill.name = p.display_name;
            if (p.class_year) prefill.class_year = p.class_year;
            form.setFieldsValue(prefill);
          }
        } catch { /* manual entry fallback */ }
        finally { setProfileLoading(false); }
      })();
    }
  }, [permit, form]);

  async function handleFinish(values: any) {
    if (!permit) return;
    setSubmitting(true);
    try {
      const res = await fetch("/api/student/permits/purchase", {
        method: "POST", headers: await authHeaders(),
        body: JSON.stringify({
          permit_type_id: permit.id,
          student_name: values.name,
          plate: values.plate.toUpperCase().trim(),
          plate_state: (values.plate_state || "").toUpperCase().trim(),
          class_year: values.class_year || 0,
          phone: values.phone || null,
          sms_opt_in: !!values.sms_opt_in,
        }),
      });
      if (!res.ok) { const b = await res.json(); throw new Error(b.detail || "Purchase failed"); }
      const { checkout_url } = await res.json();
      window.location.href = checkout_url;
    } catch (e: any) { onError(e.message); onClose(); } finally { setSubmitting(false); }
  }

  const nameFromOkta = !!profile?.display_name;
  const classYearFromOkta = !!profile?.class_year;

  return (
    <Card className="shadow-md border-2 border-brand-primary/20">
      {permit && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-lg font-bold text-brand-primary">Buy {permit.label}</h3>
            <Button type="text" size="small" onClick={onClose}>✕</Button>
          </div>
          <div className="flex items-center justify-between mb-4 pb-3 border-b">
            <span className="text-gray-500">{permit.eligible}</span>
            <span className="text-lg font-bold text-brand-primary">${Number(permit.price).toFixed(0)}</span>
          </div>
          <div className="text-xs text-gray-500 mb-4">
            <div>Valid for {permit.valid_days} days</div>
            <div className="flex items-center gap-1 mt-1 flex-wrap">
              <span className="font-medium">Lots highlighted on map:</span>
              {permit.lot_details?.length > 0 ? <LotTags details={permit.lot_details} /> : <span>{permit.lot_assignments.join(", ")}</span>}
            </div>
          </div>
          {profileLoading ? <div className="flex justify-center py-4"><Spin size="small" /></div> : (
            <Form form={form} layout="vertical" onFinish={handleFinish} size="small">
              <Form.Item name="name" label="Full Name" rules={[{ required: true }]} tooltip={nameFromOkta ? "From your university account" : undefined}>
                <Input disabled={nameFromOkta} className={nameFromOkta ? "bg-gray-50" : ""} />
              </Form.Item>
              <div className="grid grid-cols-3 gap-3">
                <Form.Item name="plate" label="License Plate" rules={[{ required: true }]} className="col-span-2">
                  <Input placeholder="ABC1234" className="font-mono" />
                </Form.Item>
                <Form.Item name="plate_state" label="State" rules={[{ required: true, message: "State required" }]}>
                  <Input placeholder="PA" maxLength={2} className="font-mono uppercase" />
                </Form.Item>
              </div>
              {!permit.allow_multiple && (
                <Form.Item name="class_year" label="Graduation Year" rules={[{ required: !permit.allow_multiple }]} tooltip={classYearFromOkta ? "From your university account" : undefined}>
                  <InputNumber min={2024} max={2035} placeholder="2027" className="w-full" disabled={classYearFromOkta} />
                </Form.Item>
              )}
              <Form.Item name="phone" label="Mobile Phone" rules={[{ required: true, message: "Cell phone is required" }]}>
                <Input placeholder="610-555-0123" />
              </Form.Item>
              <Form.Item name="sms_opt_in" valuePropName="checked" initialValue={true}>
                <Checkbox>
                  <span className="text-xs text-gray-600">
                    Send me text messages about my permit, lot closures, weather alerts, and campus emergency notifications
                  </span>
                </Checkbox>
              </Form.Item>
              <div className="flex justify-end gap-3 pt-4 border-t mt-4">
                <Button onClick={onClose}>Cancel</Button>
                <Button type="primary" htmlType="submit" loading={submitting} style={{ background: brand.primaryColor }}>
                  Proceed to Payment — ${Number(permit.price).toFixed(0)}
                </Button>
              </div>
            </Form>
          )}
        </div>
      )}
    </Card>
  );
}
