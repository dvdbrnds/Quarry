import { useCallback, useEffect, useState } from "react";
import { Button, Card, Form, Input, InputNumber, Radio, Spin, Tag, App as AntApp, Space } from "antd";
import { ArrowDownOutlined, ArrowUpOutlined } from "@ant-design/icons";
import { initAuth, isAuthenticated, login, authHeaders, fetchCurrentUser, loadConfig, type AuthUser } from "../auth";
import type { Lot } from "../api";
import StudentLotMap from "../components/StudentLotMap";
import { useBranding } from "../useBranding";

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

  useEffect(() => {
    (async () => {
      try {
        await initAuth();
        const authed = await isAuthenticated();
        if (!authed) {
          sessionStorage.setItem("quarry_return_path", "/parking/lottery-v2");
          await login();
          return;
        }
        const u = await fetchCurrentUser();
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
      <LotteryV2Page user={user} />
    </AntApp>
  );
}

function LotteryV2Page({ user }: { user: AuthUser }) {
  const brand = useBranding();
  const { message, modal } = AntApp.useApp();
  const [loading, setLoading] = useState(true);
  const [cycle, setCycle] = useState<Cycle | null>(null);
  const [application, setApplication] = useState<Application | null>(null);
  const [step, setStep] = useState<"intake" | "rank" | "done">("intake");
  const [campus, setCampus] = useState<"north" | "south" | null>(null);
  const [classYear, setClassYear] = useState<number | null>(null);
  const [plate, setPlate] = useState("");
  const [plateState, setPlateState] = useState("PA");
  const [studentName, setStudentName] = useState(user.email || "");
  const [tiers, setTiers] = useState<Tier[]>([]);
  const [ranked, setRanked] = useState<Tier[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [lots, setLots] = useState<Lot[]>([]);
  const [highlightedLots, setHighlightedLots] = useState<string[]>([]);
  const [focusedLot, setFocusedLot] = useState<string | null>(null);
  const [mapsApiKey, setMapsApiKey] = useState("");
  const [campusCenter, setCampusCenter] = useState<{ lat: number; lng: number } | undefined>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const headers = await authHeaders();
      const [cycleRes, appRes, profileRes, lotsRes] = await Promise.all([
        fetch("/api/lottery-v2/cycle", { headers }),
        fetch("/api/lottery-v2/applications/me", { headers }),
        fetch("/api/auth/profile", { headers }),
        fetch("/api/lots", { headers }),
      ]);
      if (cycleRes.ok) setCycle(await cycleRes.json());
      else setCycle(null);

      if (appRes.ok) {
        const body = await appRes.json();
        if (body) {
          setApplication(body);
          setStep("done");
        }
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
    loadConfig().then((cfg) => {
      setMapsApiKey(cfg.google_maps_api_key || "");
      if (cfg.campus_lat && cfg.campus_lng) {
        setCampusCenter({ lat: cfg.campus_lat, lng: cfg.campus_lng });
      }
    });
  }, [load]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("accepted")) {
      message.success("Payment received — your permit is being issued.");
      load();
    }
  }, [load, message]);

  async function loadTiers(c: "north" | "south", year: number) {
    const headers = await authHeaders();
    const res = await fetch(
      `/api/lottery-v2/eligible-tiers?campus=${c}&class_year=${year}`,
      { headers },
    );
    if (!res.ok) {
      message.error("Could not load eligible tiers");
      return;
    }
    const data: Tier[] = await res.json();
    setTiers(data);
    setRanked(data);
  }

  async function continueToRank() {
    if (!campus || !classYear || !plate.trim()) {
      message.warning("Campus, class year, and plate are required");
      return;
    }
    await loadTiers(campus, classYear);
    setStep("rank");
  }

  function moveTier(index: number, direction: -1 | 1) {
    const next = [...ranked];
    const t = index + direction;
    if (t < 0 || t >= next.length) return;
    [next[index], next[t]] = [next[t], next[index]];
    setRanked(next);
  }

  async function submit() {
    if (!campus || !classYear || ranked.length === 0) return;
    setSubmitting(true);
    try {
      const headers = await authHeaders();
      const res = await fetch("/api/lottery-v2/applications", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          campus,
          class_year: classYear,
          plate: plate.trim().toUpperCase(),
          plate_state: plateState.trim().toUpperCase(),
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
      const headers = await authHeaders();
      const res = await fetch(`/api/lottery-v2/applications/${application.id}/accept`, {
        method: "POST",
        headers,
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
        const headers = await authHeaders();
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

  const showMap = Boolean(mapsApiKey && lots.length > 0);
  const mapHighlight =
    application?.assigned_lot && step === "done"
      ? [application.assigned_lot]
      : highlightedLots;

  return (
    <div className="min-h-screen bg-gray-50">
      <header
        style={{ background: brand.primaryColor }}
        className="text-white px-6 py-4 shadow"
      >
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <p className="text-xs uppercase tracking-wider opacity-70">Staging</p>
            <h1 style={{ color: brand.accentColor }} className="text-xl font-bold m-0">
              Parking Lottery V2
            </h1>
          </div>
          <span className="text-xs opacity-70">{user.email}</span>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        <div className={`grid grid-cols-1 gap-6 ${showMap ? "lg:grid-cols-3" : ""}`}>
          {showMap && (
            <div className="lg:hidden h-[280px] rounded-xl overflow-hidden shadow">
              <StudentLotMap
                apiKey={mapsApiKey}
                lots={lots}
                highlightedLots={mapHighlight}
                focusedLot={focusedLot}
                defaultCenter={campusCenter}
              />
            </div>
          )}

          <div className={`space-y-6 ${showMap ? "lg:col-span-1" : "max-w-2xl mx-auto w-full"}`}>
            {!cycle && (
              <Card>
                <p className="text-gray-500 m-0">
                  No lottery cycle is available right now. Check back when registration opens.
                </p>
              </Card>
            )}

            {cycle && (
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

            {!application && cycle?.status === "open" && step === "intake" && (
              <Card title="1. About you">
                <Form layout="vertical" onFinish={continueToRank}>
                  <Form.Item label="Campus residence" required>
                    <Radio.Group
                      value={campus}
                      onChange={(e) => setCampus(e.target.value)}
                      optionType="button"
                      buttonStyle="solid"
                      options={[
                        { label: "North Campus", value: "north" },
                        { label: "South Campus", value: "south" },
                      ]}
                    />
                  </Form.Item>
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
                  <Button type="primary" htmlType="submit" disabled={!campus || !classYear || !plate}>
                    Continue — rank tiers
                  </Button>
                </Form>
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
                      Rank with the arrows. Hover a tier to highlight its lots on the map.
                      #1 is your first choice — you'll get one placement if capacity allows.
                    </p>
                    <ul className="space-y-2 list-none p-0 m-0 mb-6">
                      {ranked.map((tier, i) => (
                        <li
                          key={tier.id}
                          className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-3 py-3 transition-shadow hover:shadow-md"
                          onMouseEnter={() => {
                            setHighlightedLots(tier.lot_assignments);
                            setFocusedLot(null);
                          }}
                          onMouseLeave={() => {
                            setHighlightedLots([]);
                            setFocusedLot(null);
                          }}
                        >
                          <span className="text-sm font-bold text-gray-400 w-6">#{i + 1}</span>
                          <div className="flex-1 min-w-0">
                            <p className="m-0 font-medium">{tier.label}</p>
                            <p className="m-0 text-xs text-gray-500">
                              ${tier.price} · {tier.remaining} spots left
                            </p>
                            <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-gray-500">
                              <span>Lots:</span>
                              {tier.lot_assignments.length ? (
                                tier.lot_assignments.map((lot) => (
                                  <Tag
                                    key={lot}
                                    className="m-0 cursor-default"
                                    onMouseEnter={(e) => {
                                      e.stopPropagation();
                                      setFocusedLot(lot);
                                      setHighlightedLots(tier.lot_assignments);
                                    }}
                                    onMouseLeave={(e) => {
                                      e.stopPropagation();
                                      setFocusedLot(null);
                                    }}
                                  >
                                    {lot}
                                  </Tag>
                                ))
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
                      ))}
                    </ul>
                    <Button type="primary" loading={submitting} onClick={submit} block>
                      Submit application
                    </Button>
                  </>
                )}
              </Card>
            )}

            {!application && cycle && cycle.status !== "open" && (
              <Card>
                <p className="text-gray-500 m-0">
                  Applications are not open for this cycle ({cycle.status}).
                </p>
              </Card>
            )}
          </div>

          {showMap && (
            <div className="hidden lg:block lg:col-span-2 min-w-0">
              <div className="sticky top-6 h-[calc(100vh-8rem)] rounded-xl overflow-hidden shadow-lg">
                <StudentLotMap
                  apiKey={mapsApiKey}
                  lots={lots}
                  highlightedLots={mapHighlight}
                  focusedLot={focusedLot}
                  defaultCenter={campusCenter}
                />
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
