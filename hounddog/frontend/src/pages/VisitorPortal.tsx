import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Form,
  Input,
  DatePicker,
  Radio,
  Result,
  Spin,
  Tag,
  App,
  Alert,
  type FormInstance,
} from "antd";
import dayjs from "dayjs";
import { useBranding } from "../useBranding";
import PublicPageNav from "../components/PublicPageNav";
import StudentLotMap from "../components/StudentLotMap";
import { loadConfig } from "../auth";
import type { Lot } from "../api";

type Purpose = "day_guest" | "vendor";
type Duration = "single_day" | "multi_day" | "long_term_30" | "long_term_60" | "long_term_90";
type Step = "intake" | "choose" | "details" | "done";

interface PermitOption {
  id: string;
  label: string;
  description: string;
  duration?: Duration;
  requiresApproval?: boolean;
}

interface PermitResult {
  id: string;
  permit_number: string | null;
  visitor_type: string;
  name: string;
  plate: string;
  status: string;
  start_date: string;
  end_date: string | null;
  requires_approval: boolean;
  message: string;
}

interface PublicLot {
  id: string;
  name: string;
  boundary: { latitude: number; longitude: number }[];
  total_spaces: number;
  handicap_spaces: number;
  designation_code: string;
  designation_label: string;
  lot_type: string;
  external_url: string | null;
  external_provider: string | null;
  is_closed: boolean;
  campus: string | null;
}

const VISITOR_FILL = "#2563EB";

const DAY_GUEST_OPTIONS: PermitOption[] = [
  {
    id: "day_pass",
    label: "Day pass",
    description: "Free one-day visitor parking for meetings, events, or campus visits.",
  },
];

const VENDOR_OPTIONS: PermitOption[] = [
  {
    id: "single_day",
    label: "Single day",
    description: "On campus for contracted work or a delivery today.",
    duration: "single_day",
  },
  {
    id: "multi_day",
    label: "Multiple days",
    description: "Custom date range for short projects. Requires campus sponsor approval.",
    duration: "multi_day",
    requiresApproval: true,
  },
  {
    id: "long_term_30",
    label: "Long-term — 30 days",
    description: "Ongoing project parking. Requires campus sponsor approval.",
    duration: "long_term_30",
    requiresApproval: true,
  },
  {
    id: "long_term_60",
    label: "Long-term — 60 days",
    description: "Ongoing project parking. Requires campus sponsor approval.",
    duration: "long_term_60",
    requiresApproval: true,
  },
  {
    id: "long_term_90",
    label: "Long-term — 90 days",
    description: "Ongoing project parking. Requires campus sponsor approval.",
    duration: "long_term_90",
    requiresApproval: true,
  },
];

function isVisitorLot(lot: PublicLot): boolean {
  const code = (lot.designation_code || "").toUpperCase();
  const label = (lot.designation_label || "").toLowerCase();
  return code === "VPR" || label.includes("visitor");
}

function toMapLot(lot: PublicLot): Lot {
  return {
    id: lot.id,
    name: lot.name,
    boundary: lot.boundary,
    total_spaces: lot.total_spaces,
    handicap_spaces: lot.handicap_spaces,
    designation_code: lot.designation_code,
    designation_label: lot.designation_label,
    access_schedule: [],
    is_snow_lot: false,
    is_closed: lot.is_closed,
    has_sheepdog: false,
    lot_type: lot.lot_type,
    external_url: lot.external_url,
    external_provider: lot.external_provider,
    campus: lot.campus,
    notes: null,
    created_at: "",
    updated_at: "",
    deleted_at: null,
  };
}

export default function VisitorPortal() {
  return (
    <App>
      <VisitorFlow />
    </App>
  );
}

function VisitorFlow() {
  const brand = useBranding();
  const { message } = App.useApp();
  const [step, setStep] = useState<Step>("intake");
  const [purpose, setPurpose] = useState<Purpose | null>(null);
  const [selectedOption, setSelectedOption] = useState<PermitOption | null>(null);
  const [name, setName] = useState("");
  const [plate, setPlate] = useState("");
  const [plateState, setPlateState] = useState("PA");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<PermitResult | null>(null);
  const [detailsForm] = Form.useForm();
  const [visitorLots, setVisitorLots] = useState<Lot[]>([]);
  const [mapsApiKey, setMapsApiKey] = useState("");
  const [campusCenter, setCampusCenter] = useState<{ lat: number; lng: number } | undefined>();
  const [mapLoading, setMapLoading] = useState(true);
  const [focusedLot, setFocusedLot] = useState<string | null>(null);
  const [hoveredOptionId, setHoveredOptionId] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [cfg, lotsRes] = await Promise.all([
          loadConfig(),
          fetch("/api/parking-map"),
        ]);
        setMapsApiKey(cfg.google_maps_api_key || "");
        if (cfg.campus_lat && cfg.campus_lng) {
          setCampusCenter({ lat: cfg.campus_lat, lng: cfg.campus_lng });
        }
        if (lotsRes.ok) {
          const lots: PublicLot[] = await lotsRes.json();
          setVisitorLots(lots.filter(isVisitorLot).map(toMapLot));
        }
      } catch {
        /* map optional */
      } finally {
        setMapLoading(false);
      }
    })();
  }, []);

  const availableOptions = useMemo(() => {
    if (purpose === "day_guest") return DAY_GUEST_OPTIONS;
    if (purpose === "vendor") return VENDOR_OPTIONS;
    return [];
  }, [purpose]);

  const lotColors = useMemo(() => {
    const map: Record<string, string> = {};
    for (const lot of visitorLots) {
      map[lot.name] = VISITOR_FILL;
      map[lot.name.replace(/^lot\s+/i, "").trim()] = VISITOR_FILL;
    }
    return map;
  }, [visitorLots]);

  const mapLegend = useMemo(
    () =>
      visitorLots.length > 0
        ? [{ label: "Visitor parking", color: VISITOR_FILL }]
        : [],
    [visitorLots],
  );

  const mapHighlight = useMemo(() => {
    if (focusedLot) return [focusedLot];
    if (hoveredOptionId || step === "choose" || step === "intake" || step === "details") {
      return visitorLots.map((l) => l.name);
    }
    return visitorLots.map((l) => l.name);
  }, [focusedLot, hoveredOptionId, step, visitorLots]);

  const showMap = Boolean(mapsApiKey && visitorLots.length > 0);

  const continueToChoose = useCallback(() => {
    if (!purpose || !name.trim() || !plate.trim()) {
      message.warning("Purpose, name, and license plate are required");
      return;
    }
    setSelectedOption(null);
    setStep("choose");
  }, [purpose, name, plate, message]);

  function chooseOption(opt: PermitOption) {
    setSelectedOption(opt);
    setStep("details");
  }

  async function submitDetails(values: Record<string, unknown>) {
    if (!purpose || !selectedOption) return;
    setSubmitting(true);
    try {
      const payload =
        purpose === "day_guest"
          ? {
              visitor_type: "day_guest",
              name: name.trim(),
              plate: plate.trim().toUpperCase(),
              plate_state: plateState.trim().toUpperCase(),
              email: (values.email as string) || "",
              phone: (values.phone as string) || "",
              visit_date: values.visit_date
                ? (values.visit_date as dayjs.Dayjs).format("YYYY-MM-DD")
                : undefined,
              visiting_person: (values.visiting_person as string) || "",
              visiting_event: (values.visiting_event as string) || "",
            }
          : {
              visitor_type: "vendor",
              name: name.trim(),
              plate: plate.trim().toUpperCase(),
              plate_state: plateState.trim().toUpperCase(),
              email: (values.email as string) || "",
              phone: (values.phone as string) || "",
              company_name: String(values.company_name || "").trim(),
              duration: selectedOption.duration || "single_day",
              start_date: values.start_date
                ? (values.start_date as dayjs.Dayjs).format("YYYY-MM-DD")
                : undefined,
              end_date: values.end_date
                ? (values.end_date as dayjs.Dayjs).format("YYYY-MM-DD")
                : undefined,
              sponsor_name: String(values.sponsor_name || "").trim(),
              sponsor_email: String(values.sponsor_email || "").trim(),
              sponsor_department: (values.sponsor_department as string) || "",
              work_description: (values.work_description as string) || "",
            };

      const res = await fetch("/api/visitor/permits", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = body.detail;
        throw new Error(
          typeof detail === "string"
            ? detail
            : Array.isArray(detail)
              ? detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join(", ")
              : "Failed to create permit",
        );
      }
      const data: PermitResult = await res.json();
      setResult(data);
      setStep("done");
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "Failed to create permit");
    } finally {
      setSubmitting(false);
    }
  }

  function startOver() {
    setStep("intake");
    setPurpose(null);
    setSelectedOption(null);
    setResult(null);
    setName("");
    setPlate("");
    setPlateState("PA");
    setFocusedLot(null);
    setHoveredOptionId(null);
    detailsForm.resetFields();
  }

  const mapPanel = showMap && (
    <StudentLotMap
      apiKey={mapsApiKey}
      lots={visitorLots}
      highlightedLots={mapHighlight}
      focusedLot={focusedLot}
      defaultCenter={campusCenter}
      lotColors={lotColors}
      legend={mapLegend}
    />
  );

  return (
    <div className="min-h-screen bg-gray-50">
      <PublicPageNav subtitle="Visitor Parking" />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        {mapLoading ? (
          <div className="flex justify-center py-20">
            <Spin size="large" />
          </div>
        ) : (
          <div className={`grid grid-cols-1 gap-6 ${showMap ? "lg:grid-cols-3" : ""}`}>
            {showMap && (
              <div className="lg:hidden h-[280px] rounded-xl overflow-hidden shadow">{mapPanel}</div>
            )}

            <div className={`space-y-6 ${showMap ? "lg:col-span-1" : "max-w-2xl mx-auto w-full"}`}>
              {step === "intake" && (
                <Card title="1. About you">
                  <Form layout="vertical" onFinish={continueToChoose}>
                    <Form.Item label="Why are you parking?" required>
                      <Radio.Group
                        value={purpose}
                        onChange={(e) => setPurpose(e.target.value)}
                        optionType="button"
                        buttonStyle="solid"
                        options={[
                          { label: "Day guest", value: "day_guest" },
                          { label: "Vendor / trade", value: "vendor" },
                        ]}
                      />
                    </Form.Item>
                    {purpose === "day_guest" && (
                      <Alert
                        type="info"
                        showIcon
                        className="mb-4"
                        message="Day guest"
                        description="Visiting for a meeting, event, or to see someone. Map shows visitor parking lots."
                      />
                    )}
                    {purpose === "vendor" && (
                      <Alert
                        type="info"
                        showIcon
                        className="mb-4"
                        message="Vendor / trade"
                        description="Contracted work, deliveries, or an ongoing project. Long-term options need campus sponsor approval."
                      />
                    )}
                    <Form.Item label="Full name" required>
                      <Input
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="Jane Smith"
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
                    <Button
                      type="primary"
                      htmlType="submit"
                      disabled={!purpose || !name.trim() || !plate.trim()}
                      style={{ background: brand.primaryColor }}
                      block
                    >
                      Continue — choose a permit
                    </Button>
                  </Form>
                </Card>
              )}

              {step === "choose" && (
                <Card
                  title="2. Choose your permit"
                  extra={
                    <Button
                      type="link"
                      onClick={() => {
                        setStep("intake");
                        setSelectedOption(null);
                        setHoveredOptionId(null);
                        setFocusedLot(null);
                      }}
                    >
                      Back
                    </Button>
                  }
                >
                  <p className="text-sm text-gray-500 mb-4">
                    {purpose === "day_guest"
                      ? "Based on your day guest selection, this is what’s available."
                      : "Based on your vendor/trade selection, pick the duration that fits your work."}
                  </p>
                  <ul className="space-y-2 list-none p-0 m-0">
                    {availableOptions.map((opt) => {
                      const isHovered = hoveredOptionId === opt.id;
                      return (
                        <li
                          key={opt.id}
                          className="rounded-lg border px-3 py-3 transition-shadow hover:shadow-md cursor-pointer"
                          style={{
                            borderColor: isHovered ? VISITOR_FILL : "#e5e7eb",
                            borderLeftWidth: 4,
                            borderLeftColor: VISITOR_FILL,
                            background: isHovered ? "#EFF6FF" : "#fff",
                          }}
                          onMouseEnter={() => {
                            setHoveredOptionId(opt.id);
                            if (visitorLots[0]) setFocusedLot(visitorLots[0].name);
                          }}
                          onMouseLeave={() => {
                            setHoveredOptionId(null);
                            setFocusedLot(null);
                          }}
                          onClick={() => chooseOption(opt)}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="m-0 font-medium flex items-center gap-2">
                                <span
                                  className="inline-block w-2.5 h-2.5 rounded-sm shrink-0"
                                  style={{ background: VISITOR_FILL }}
                                />
                                {opt.label}
                              </p>
                              <p className="m-0 text-xs text-gray-500 mt-1">{opt.description}</p>
                              {opt.requiresApproval && (
                                <Tag color="gold" className="mt-2 m-0">
                                  Sponsor approval required
                                </Tag>
                              )}
                            </div>
                            <Button
                              type="primary"
                              size="small"
                              style={{ background: VISITOR_FILL }}
                              onClick={(e) => {
                                e.stopPropagation();
                                chooseOption(opt);
                              }}
                            >
                              Select
                            </Button>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </Card>
              )}

              {step === "details" && selectedOption && purpose && (
                <Card
                  title={`3. ${selectedOption.label} details`}
                  extra={
                    <Button
                      type="link"
                      onClick={() => {
                        setStep("choose");
                        setFocusedLot(null);
                      }}
                    >
                      Back
                    </Button>
                  }
                >
                  {purpose === "day_guest" ? (
                    <DayGuestDetails
                      form={detailsForm}
                      onSubmit={submitDetails}
                      submitting={submitting}
                      brand={brand}
                    />
                  ) : (
                    <VendorDetails
                      form={detailsForm}
                      option={selectedOption}
                      onSubmit={submitDetails}
                      submitting={submitting}
                      brand={brand}
                    />
                  )}
                </Card>
              )}

              {step === "done" && result && (
                <ConfirmationCard result={result} onStartOver={startOver} />
              )}
            </div>

            {showMap && (
              <div className="hidden lg:block lg:col-span-2 min-w-0">
                <div className="sticky top-6 h-[calc(100vh-8rem)] rounded-xl overflow-hidden shadow-lg">
                  {mapPanel}
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function DayGuestDetails({
  form,
  onSubmit,
  submitting,
  brand,
}: {
  form: FormInstance;
  onSubmit: (values: Record<string, unknown>) => void;
  submitting: boolean;
  brand: { primaryColor: string };
}) {
  return (
    <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ visit_date: dayjs() }}>
      <Form.Item name="visit_date" label="Date of visit">
        <DatePicker className="w-full" disabledDate={(d) => d.isBefore(dayjs().startOf("day"))} />
      </Form.Item>
      <Form.Item name="visiting_person" label="Person you are visiting">
        <Input placeholder="Prof. Johnson, Admissions Office, etc." />
      </Form.Item>
      <Form.Item name="visiting_event" label="Event (if applicable)">
        <Input placeholder="Open House, Conference, etc." />
      </Form.Item>
      <Form.Item name="email" label="Email (optional — for confirmation)">
        <Input type="email" placeholder="you@example.com" />
      </Form.Item>
      <Form.Item name="phone" label="Phone (optional)">
        <Input placeholder="610-555-0123" />
      </Form.Item>
      <Button type="primary" htmlType="submit" loading={submitting} block style={{ background: brand.primaryColor }}>
        Get day pass
      </Button>
    </Form>
  );
}

function VendorDetails({
  form,
  option,
  onSubmit,
  submitting,
  brand,
}: {
  form: FormInstance;
  option: PermitOption;
  onSubmit: (values: Record<string, unknown>) => void;
  submitting: boolean;
  brand: { primaryColor: string };
}) {
  const needsEndDate = option.duration === "multi_day";
  const isLongTerm = Boolean(option.requiresApproval);

  return (
    <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ start_date: dayjs() }}>
      <Form.Item
        name="company_name"
        label="Company name"
        rules={[{ required: true, message: "Company name is required" }]}
      >
        <Input placeholder="ABC Plumbing" />
      </Form.Item>
      <Form.Item name="email" label="Your email">
        <Input type="email" placeholder="john@abcplumbing.com" />
      </Form.Item>
      <Form.Item name="phone" label="Phone">
        <Input placeholder="610-555-0123" />
      </Form.Item>
      <div className="grid grid-cols-2 gap-3">
        <Form.Item name="start_date" label="Start date">
          <DatePicker className="w-full" disabledDate={(d) => d.isBefore(dayjs().startOf("day"))} />
        </Form.Item>
        {needsEndDate && (
          <Form.Item
            name="end_date"
            label="End date"
            rules={[{ required: true, message: "End date required" }]}
          >
            <DatePicker className="w-full" disabledDate={(d) => d.isBefore(dayjs().startOf("day"))} />
          </Form.Item>
        )}
      </div>

      <div className="border-t pt-4 mt-2">
        <h4 className="text-sm font-semibold text-gray-700 mb-2">Campus sponsor</h4>
        <p className="text-xs text-gray-500 mb-4">
          {isLongTerm
            ? "Long-term permits require approval from your campus sponsor. They will receive an email to confirm."
            : "Please provide the staff or faculty member who arranged your visit."}
        </p>
        <Form.Item
          name="sponsor_name"
          label="Sponsor name"
          rules={[{ required: true, message: "Sponsor name required" }]}
        >
          <Input placeholder="Mary Johnson" />
        </Form.Item>
        <Form.Item
          name="sponsor_email"
          label="Sponsor email (moravian.edu)"
          rules={[
            { required: true, message: "Sponsor email required" },
            { type: "email", message: "Enter a valid email" },
          ]}
        >
          <Input placeholder="johnsonm@moravian.edu" />
        </Form.Item>
        <Form.Item name="sponsor_department" label="Department">
          <Input placeholder="Facilities, IT, Athletics, etc." />
        </Form.Item>
      </div>

      <Form.Item name="work_description" label="Description of work">
        <Input.TextArea rows={3} placeholder="HVAC repair in Comenius Hall, Room 204" />
      </Form.Item>

      {isLongTerm && (
        <Alert
          type="warning"
          showIcon
          className="mb-4"
          message="Sponsor approval required"
          description="Your permit will stay pending until your campus sponsor approves the request via email."
        />
      )}

      <Button type="primary" htmlType="submit" loading={submitting} block style={{ background: brand.primaryColor }}>
        {isLongTerm ? "Submit for approval" : "Get vendor pass"}
      </Button>
    </Form>
  );
}

function ConfirmationCard({
  result,
  onStartOver,
}: {
  result: PermitResult;
  onStartOver: () => void;
}) {
  const isPending = result.status === "pending_approval";

  return (
    <Card>
      <Result
        status={isPending ? "info" : "success"}
        title={isPending ? "Permit pending approval" : "Parking permit issued"}
        subTitle={result.message}
        extra={[
          <div key="details" className="text-left max-w-sm mx-auto mb-6">
            <table className="w-full text-sm">
              <tbody>
                <tr className="border-b">
                  <td className="py-2 text-gray-500">Permit #</td>
                  <td className="py-2 font-semibold text-right">{result.permit_number || "—"}</td>
                </tr>
                <tr className="border-b">
                  <td className="py-2 text-gray-500">Name</td>
                  <td className="py-2 font-semibold text-right">{result.name}</td>
                </tr>
                <tr className="border-b">
                  <td className="py-2 text-gray-500">Vehicle</td>
                  <td className="py-2 font-mono font-semibold text-right">{result.plate}</td>
                </tr>
                <tr className="border-b">
                  <td className="py-2 text-gray-500">Valid</td>
                  <td className="py-2 text-right">
                    {result.start_date}
                    {result.end_date && result.end_date !== result.start_date && ` — ${result.end_date}`}
                  </td>
                </tr>
                <tr>
                  <td className="py-2 text-gray-500">Status</td>
                  <td className="py-2 text-right">
                    <span
                      className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                        isPending ? "bg-amber-100 text-amber-800" : "bg-green-100 text-green-800"
                      }`}
                    >
                      {isPending ? "Pending approval" : "Active"}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>,
          <div key="note" className="text-center text-sm text-gray-500 mb-6">
            {!isPending && (
              <p>No physical permit is needed. Your plate has been registered in our system.</p>
            )}
          </div>,
          <Button key="again" onClick={onStartOver}>
            Register another vehicle
          </Button>,
        ]}
      />
    </Card>
  );
}
