import { useState } from "react";
import { Button, Card, Form, Input, DatePicker, Select, Steps, Result, Spin, App } from "antd";
import { useBranding } from "../useBranding";
import PublicPageNav from "../components/PublicPageNav";
import dayjs from "dayjs";

type VisitorType = "day_guest" | "vendor" | null;
type Duration = "single_day" | "multi_day" | "long_term_30" | "long_term_60" | "long_term_90";

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

export default function VisitorPortal() {
  return (
    <App>
      <VisitorWizard />
    </App>
  );
}

function VisitorWizard() {
  const brand = useBranding();
  const { message } = App.useApp();
  const [visitorType, setVisitorType] = useState<VisitorType>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<PermitResult | null>(null);
  const [guestForm] = Form.useForm();
  const [vendorForm] = Form.useForm();

  function handleTypeSelect(type: VisitorType) {
    setVisitorType(type);
    setCurrentStep(1);
  }

  function handleBack() {
    if (currentStep === 1) {
      setVisitorType(null);
      setCurrentStep(0);
    }
  }

  async function handleGuestSubmit(values: any) {
    setSubmitting(true);
    try {
      const payload = {
        visitor_type: "day_guest",
        name: values.name.trim(),
        plate: values.plate.trim().toUpperCase(),
        plate_state: (values.plate_state || "").trim().toUpperCase(),
        email: values.email || "",
        phone: values.phone || "",
        visit_date: values.visit_date ? values.visit_date.format("YYYY-MM-DD") : undefined,
        visiting_person: values.visiting_person || "",
        visiting_event: values.visiting_event || "",
      };
      const res = await fetch("/api/visitor/permits", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Failed to create permit");
      }
      const data: PermitResult = await res.json();
      setResult(data);
      setCurrentStep(2);
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVendorSubmit(values: any) {
    setSubmitting(true);
    try {
      const payload = {
        visitor_type: "vendor",
        name: values.name.trim(),
        plate: values.plate.trim().toUpperCase(),
        plate_state: (values.plate_state || "").trim().toUpperCase(),
        email: values.email || "",
        phone: values.phone || "",
        company_name: values.company_name.trim(),
        duration: values.duration,
        start_date: values.start_date ? values.start_date.format("YYYY-MM-DD") : undefined,
        end_date: values.end_date ? values.end_date.format("YYYY-MM-DD") : undefined,
        sponsor_name: values.sponsor_name.trim(),
        sponsor_email: values.sponsor_email.trim(),
        sponsor_department: values.sponsor_department || "",
        work_description: values.work_description || "",
      };
      const res = await fetch("/api/visitor/permits", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Failed to create permit");
      }
      const data: PermitResult = await res.json();
      setResult(data);
      setCurrentStep(2);
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  function handleStartOver() {
    setVisitorType(null);
    setCurrentStep(0);
    setResult(null);
    guestForm.resetFields();
    vendorForm.resetFields();
  }

  const stepItems = [
    { title: "Type" },
    { title: "Details" },
    { title: "Confirmation" },
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      <PublicPageNav subtitle="Visitor Parking" />

      <main className="max-w-2xl mx-auto px-6 py-10">
        <Steps current={currentStep} items={stepItems} className="mb-8" />

        {currentStep === 0 && (
          <TypeSelection onSelect={handleTypeSelect} brand={brand} />
        )}

        {currentStep === 1 && visitorType === "day_guest" && (
          <DayGuestForm
            form={guestForm}
            onSubmit={handleGuestSubmit}
            onBack={handleBack}
            submitting={submitting}
            brand={brand}
          />
        )}

        {currentStep === 1 && visitorType === "vendor" && (
          <VendorForm
            form={vendorForm}
            onSubmit={handleVendorSubmit}
            onBack={handleBack}
            submitting={submitting}
            brand={brand}
          />
        )}

        {currentStep === 2 && result && (
          <ConfirmationStep result={result} onStartOver={handleStartOver} brand={brand} />
        )}
      </main>
    </div>
  );
}

function TypeSelection({ onSelect, brand }: { onSelect: (type: VisitorType) => void; brand: any }) {
  return (
    <div className="space-y-6">
      <div className="text-center mb-8">
        <h2 className="text-2xl font-bold text-gray-800">Welcome to Visitor Parking</h2>
        <p className="text-gray-500 mt-2">Select the type of parking permit you need.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card
          hoverable
          className="text-center cursor-pointer transition-all hover:shadow-lg border-2 hover:border-blue-300"
          onClick={() => onSelect("day_guest")}
        >
          <div className="py-4">
            <div className="text-4xl mb-4">🎫</div>
            <h3 className="text-lg font-semibold text-gray-800">Day Guest</h3>
            <p className="text-sm text-gray-500 mt-2">
              Visiting campus for an event, meeting, or to see someone? Get a free day pass.
            </p>
            <div className="mt-4 text-xs text-gray-400">Valid for one day</div>
          </div>
        </Card>

        <Card
          hoverable
          className="text-center cursor-pointer transition-all hover:shadow-lg border-2 hover:border-blue-300"
          onClick={() => onSelect("vendor")}
        >
          <div className="py-4">
            <div className="text-4xl mb-4">🔧</div>
            <h3 className="text-lg font-semibold text-gray-800">Vendor / Trade</h3>
            <p className="text-sm text-gray-500 mt-2">
              On campus for contracted work, deliveries, or an ongoing project? Register here.
            </p>
            <div className="mt-4 text-xs text-gray-400">Single-day or long-term available</div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function DayGuestForm({ form, onSubmit, onBack, submitting, brand }: {
  form: any; onSubmit: (values: any) => void; onBack: () => void; submitting: boolean; brand: any;
}) {
  return (
    <Card className="shadow-sm">
      <h3 className="text-lg font-semibold text-gray-800 mb-6">Day Guest Information</h3>
      <Form form={form} layout="vertical" onFinish={onSubmit}>
        <Form.Item name="name" label="Your Full Name" rules={[{ required: true, message: "Name is required" }]}>
          <Input placeholder="Jane Smith" />
        </Form.Item>

        <div className="grid grid-cols-3 gap-3">
          <Form.Item name="plate" label="License Plate" rules={[{ required: true, message: "Plate is required" }]} className="col-span-2">
            <Input placeholder="ABC1234" className="font-mono" />
          </Form.Item>
          <Form.Item name="plate_state" label="State">
            <Input placeholder="PA" maxLength={2} className="font-mono uppercase" />
          </Form.Item>
        </div>

        <Form.Item name="visit_date" label="Date of Visit" initialValue={dayjs()}>
          <DatePicker className="w-full" disabledDate={(d) => d.isBefore(dayjs().startOf("day"))} />
        </Form.Item>

        <Form.Item name="visiting_person" label="Person You Are Visiting">
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

        <div className="flex justify-between pt-4 border-t mt-4">
          <Button onClick={onBack}>Back</Button>
          <Button
            type="primary"
            htmlType="submit"
            loading={submitting}
            style={{ background: brand.primaryColor }}
          >
            Get Day Pass
          </Button>
        </div>
      </Form>
    </Card>
  );
}

function VendorForm({ form, onSubmit, onBack, submitting, brand }: {
  form: any; onSubmit: (values: any) => void; onBack: () => void; submitting: boolean; brand: any;
}) {
  const [duration, setDuration] = useState<Duration>("single_day");
  const isLongTerm = duration !== "single_day";

  return (
    <Card className="shadow-sm">
      <h3 className="text-lg font-semibold text-gray-800 mb-6">Vendor / Trade Information</h3>
      <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ duration: "single_day" }}>
        <Form.Item name="company_name" label="Company Name" rules={[{ required: true, message: "Company name is required" }]}>
          <Input placeholder="ABC Plumbing" />
        </Form.Item>

        <Form.Item name="name" label="Contact Name" rules={[{ required: true, message: "Name is required" }]}>
          <Input placeholder="John Doe" />
        </Form.Item>

        <div className="grid grid-cols-3 gap-3">
          <Form.Item name="plate" label="License Plate" rules={[{ required: true, message: "Plate is required" }]} className="col-span-2">
            <Input placeholder="ABC1234" className="font-mono" />
          </Form.Item>
          <Form.Item name="plate_state" label="State">
            <Input placeholder="PA" maxLength={2} className="font-mono uppercase" />
          </Form.Item>
        </div>

        <Form.Item name="email" label="Your Email">
          <Input type="email" placeholder="john@abcplumbing.com" />
        </Form.Item>

        <Form.Item name="phone" label="Phone">
          <Input placeholder="610-555-0123" />
        </Form.Item>

        <Form.Item name="duration" label="Permit Duration" rules={[{ required: true }]}>
          <Select onChange={(val) => setDuration(val)} options={[
            { value: "single_day", label: "Single Day" },
            { value: "multi_day", label: "Multiple Days (custom range)" },
            { value: "long_term_30", label: "Long-Term — 30 Days" },
            { value: "long_term_60", label: "Long-Term — 60 Days" },
            { value: "long_term_90", label: "Long-Term — 90 Days" },
          ]} />
        </Form.Item>

        <div className="grid grid-cols-2 gap-3">
          <Form.Item name="start_date" label="Start Date" initialValue={dayjs()}>
            <DatePicker className="w-full" disabledDate={(d) => d.isBefore(dayjs().startOf("day"))} />
          </Form.Item>
          {duration === "multi_day" && (
            <Form.Item name="end_date" label="End Date" rules={[{ required: true, message: "End date required" }]}>
              <DatePicker className="w-full" disabledDate={(d) => d.isBefore(dayjs().startOf("day"))} />
            </Form.Item>
          )}
        </div>

        <div className="border-t pt-4 mt-4">
          <h4 className="text-sm font-semibold text-gray-700 mb-3">Campus Sponsor</h4>
          <p className="text-xs text-gray-500 mb-4">
            {isLongTerm
              ? "Long-term permits require approval from your campus sponsor. They will receive an email to confirm."
              : "Please provide the staff or faculty member who arranged your visit."}
          </p>

          <Form.Item name="sponsor_name" label="Sponsor Name" rules={[{ required: true, message: "Sponsor name required" }]}>
            <Input placeholder="Mary Johnson" />
          </Form.Item>

          <Form.Item
            name="sponsor_email"
            label="Sponsor Email (moravian.edu)"
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

        <Form.Item name="work_description" label="Description of Work">
          <Input.TextArea rows={3} placeholder="HVAC repair in Comenius Hall, Room 204" />
        </Form.Item>

        {isLongTerm && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-4">
            <p className="text-sm text-amber-800">
              Long-term permits require sponsor confirmation. Your permit will be pending until
              your campus sponsor approves the request via email.
            </p>
          </div>
        )}

        <div className="flex justify-between pt-4 border-t mt-4">
          <Button onClick={onBack}>Back</Button>
          <Button
            type="primary"
            htmlType="submit"
            loading={submitting}
            style={{ background: brand.primaryColor }}
          >
            {isLongTerm ? "Submit for Approval" : "Get Vendor Pass"}
          </Button>
        </div>
      </Form>
    </Card>
  );
}

function ConfirmationStep({ result, onStartOver, brand }: {
  result: PermitResult; onStartOver: () => void; brand: any;
}) {
  const isPending = result.status === "pending_approval";

  return (
    <Card className="shadow-sm">
      <Result
        status={isPending ? "info" : "success"}
        title={isPending ? "Permit Pending Approval" : "Parking Permit Issued"}
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
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                      isPending ? "bg-amber-100 text-amber-800" : "bg-green-100 text-green-800"
                    }`}>
                      {isPending ? "Pending Approval" : "Active"}
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
          <Button key="again" onClick={onStartOver}>Register Another Vehicle</Button>,
        ]}
      />
    </Card>
  );
}
