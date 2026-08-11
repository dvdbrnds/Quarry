import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Form,
  Input,
  DatePicker,
  Result,
  Spin,
  App,
  Alert,
  Select,
  type FormInstance,
} from "antd";
import dayjs from "dayjs";
import { useBranding } from "../useBranding";
import PublicPageNav from "../components/PublicPageNav";
import StudentLotMap from "../components/StudentLotMap";
import { loadConfig } from "../auth";
import type { Lot } from "../api";

type Step = "intake" | "details" | "done";

interface VisitorPreset {
  id: string;
  label: string;
  company_name: string;
  sponsor_name: string;
  sponsor_email: string;
  sponsor_department: string;
  default_duration: string;
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
  const [presets, setPresets] = useState<VisitorPreset[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const [cfg, lotsRes, presetsRes] = await Promise.all([
          loadConfig(),
          fetch("/api/parking-map"),
          fetch("/api/visitor/permits/presets"),
        ]);
        setMapsApiKey(cfg.google_maps_api_key || "");
        if (cfg.campus_lat && cfg.campus_lng) {
          setCampusCenter({ lat: cfg.campus_lat, lng: cfg.campus_lng });
        }
        if (lotsRes.ok) {
          const lots: PublicLot[] = await lotsRes.json();
          setVisitorLots(lots.filter(isVisitorLot).map(toMapLot));
        }
        if (presetsRes.ok) {
          setPresets(await presetsRes.json());
        }
      } catch {
        /* map optional */
      } finally {
        setMapLoading(false);
      }
    })();
  }, []);

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
    return visitorLots.map((l) => l.name);
  }, [focusedLot, visitorLots]);

  const showMap = Boolean(mapsApiKey && visitorLots.length > 0);

  const continueToDetails = useCallback(() => {
    if (!name.trim() || !plate.trim()) {
      message.warning("Name and license plate are required");
      return;
    }
    setStep("details");
  }, [name, plate, message]);

  async function submitDetails(values: Record<string, unknown>) {
    setSubmitting(true);
    try {
      const presetId = values._preset_id as string | undefined;
      const payload = {
        visitor_type: "visitor",
        name: name.trim(),
        plate: plate.trim().toUpperCase(),
        plate_state: plateState.trim().toUpperCase(),
        email: (values.email as string) || "",
        phone: (values.phone as string) || "",
        company_name: String(values.company_name || "").trim() || "Visitor",
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
        ...(presetId ? { preset_id: presetId } : {}),
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
    setResult(null);
    setName("");
    setPlate("");
    setPlateState("PA");
    setFocusedLot(null);
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
                  <Form layout="vertical" onFinish={continueToDetails}>
                    <Alert
                      type="info"
                      showIcon
                      className="mb-4"
                      message="Visitor parking requires a campus sponsor"
                      description="All visitors \u2014 guests, vendors, and contractors \u2014 need a Moravian staff or faculty sponsor to approve their parking request."
                    />
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
                      disabled={!name.trim() || !plate.trim()}
                      style={{ background: brand.primaryColor }}
                      block
                    >
                      Continue
                    </Button>
                  </Form>
                </Card>
              )}

              {step === "details" && (
                <Card
                  title="2. Visit details"
                  extra={
                    <Button
                      type="link"
                      onClick={() => {
                        setStep("intake");
                        setFocusedLot(null);
                      }}
                    >
                      Back
                    </Button>
                  }
                >
                  <VisitorDetails
                    form={detailsForm}
                    onSubmit={submitDetails}
                    submitting={submitting}
                    brand={brand}
                    presets={presets}
                  />
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

function VisitorDetails({
  form,
  onSubmit,
  submitting,
  brand,
  presets,
}: {
  form: FormInstance;
  onSubmit: (values: Record<string, unknown>) => void;
  submitting: boolean;
  brand: { primaryColor: string };
  presets: VisitorPreset[];
}) {
  const [selectedPreset, setSelectedPreset] = useState<string | null>(null);
  const usingPreset = selectedPreset !== null && selectedPreset !== "__other__";

  const handlePresetChange = (value: string) => {
    setSelectedPreset(value);
    if (value === "__other__") {
      form.setFieldsValue({ _preset_id: undefined, company_name: "", work_description: "" });
    } else {
      const p = presets.find((pr) => pr.id === value);
      if (p) {
        form.setFieldsValue({
          _preset_id: p.id,
          company_name: p.company_name,
          work_description: p.label,
        });
      }
    }
  };

  return (
    <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ start_date: dayjs(), end_date: dayjs() }}>
      <Form.Item name="_preset_id" hidden><Input /></Form.Item>

      {presets.length > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
          <Form.Item
            label={<span className="text-base font-semibold">Who are you with?</span>}
            className="mb-0"
            extra="If your organization is listed, select it to speed up approval."
          >
            <Select
              size="large"
              placeholder="Select your organization or choose Other"
              value={selectedPreset ?? undefined}
              onChange={handlePresetChange}
              allowClear
              onClear={() => { setSelectedPreset(null); form.setFieldsValue({ _preset_id: undefined, company_name: "" }); }}
              options={[
                ...presets.map((p) => ({ value: p.id, label: p.label })),
                { value: "__other__", label: "Other / not listed" },
              ]}
            />
          </Form.Item>
        </div>
      )}

      {usingPreset && (
        <Alert
          type="info"
          showIcon
          className="mb-4"
          message="Your campus sponsor will be notified automatically"
          description="Once you submit, an approval email will be sent to your organization's campus contact. No additional sponsor information is needed."
        />
      )}

      {!usingPreset && (
        <Alert
          type="warning"
          showIcon
          className="mb-4"
          message="Campus sponsor required"
          description="A Moravian staff or faculty member must approve your parking request. They will receive an email to confirm."
        />
      )}

      {!usingPreset && (
        <Form.Item name="company_name" label="Company or organization (optional)">
          <Input placeholder="ABC Plumbing, Sodexo, or leave blank if visiting as a guest" />
        </Form.Item>
      )}

      <Form.Item name="email" label="Your email">
        <Input type="email" placeholder="you@example.com" />
      </Form.Item>
      <Form.Item name="phone" label="Phone">
        <Input placeholder="610-555-0123" />
      </Form.Item>
      <div className="grid grid-cols-2 gap-3">
        <Form.Item name="start_date" label="Start date">
          <DatePicker className="w-full" disabledDate={(d) => d.isBefore(dayjs().startOf("day"))} />
        </Form.Item>
        <Form.Item name="end_date" label="End date">
          <DatePicker className="w-full" disabledDate={(d) => d.isBefore(dayjs().startOf("day"))} />
        </Form.Item>
      </div>

      {!usingPreset && (
        <div className="border-t pt-4 mt-2">
          <h4 className="text-sm font-semibold text-gray-700 mb-2">Campus sponsor</h4>
          <p className="text-xs text-gray-500 mb-4">
            Enter the Moravian staff or faculty member who can approve your parking. They will
            receive an email to confirm.
          </p>
          <Form.Item
            name="sponsor_name"
            label="Sponsor name"
            rules={[{ required: !usingPreset, message: "Sponsor name required" }]}
          >
            <Input placeholder="Mary Johnson" />
          </Form.Item>
          <Form.Item
            name="sponsor_email"
            label="Sponsor email (moravian.edu)"
            rules={[
              { required: !usingPreset, message: "Sponsor email required" },
              { type: "email", message: "Enter a valid email" },
            ]}
          >
            <Input placeholder="johnsonm@moravian.edu" />
          </Form.Item>
          <Form.Item name="sponsor_department" label="Department">
            <Input placeholder="Facilities, IT, Athletics, etc." />
          </Form.Item>
        </div>
      )}

      {!usingPreset && (
        <Form.Item name="work_description" label="Reason for visit">
          <Input.TextArea
            rows={3}
            placeholder="Guest visit, delivery, vendor work, conference, etc."
          />
        </Form.Item>
      )}

      <Button type="primary" htmlType="submit" loading={submitting} block style={{ background: brand.primaryColor }}>
        Submit for sponsor approval
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
                  <td className="py-2 font-semibold text-right">{result.permit_number || "\u2014"}</td>
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
                    {result.end_date && result.end_date !== result.start_date && ` \u2014 ${result.end_date}`}
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
