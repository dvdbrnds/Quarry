import { useState } from "react";
import { api } from "../api";
import { Button, Card, Input, Form, Checkbox, Result, Alert, App } from "antd";
import { useBranding } from "../useBranding";

const CATEGORIES = [
  { id: "emergency", label: "Emergency Alerts", description: "Critical safety and security notifications" },
  { id: "weather", label: "Weather Alerts", description: "Severe weather warnings and closures" },
  { id: "campus_closing", label: "Campus Closings", description: "Unplanned campus or building closures" },
  { id: "parking", label: "Parking Notices", description: "Lot closures, snow bans, and enforcement changes" },
  { id: "general", label: "General Notices", description: "Other campus-wide announcements" },
];

export default function AlertSubscribe() {
  const { message } = App.useApp();
  const brand = useBranding();
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);

  async function handleFinish(values: any) {
    if (!values.email && !values.phone) {
      message.error("Please provide at least an email address or phone number.");
      return;
    }
    setSubmitting(true);
    try {
      await api.alerts.subscribe({
        name: values.name, email: values.email || undefined, phone: values.phone || undefined,
        categories: values.categories || [],
      });
      setSuccess(true);
    } catch (err: any) {
      const msg = err.message || "Something went wrong";
      message.error(msg.includes("409") ? "This email is already subscribed." : msg);
    } finally { setSubmitting(false); }
  }

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4" style={{ background: `linear-gradient(to bottom, ${brand.primaryColor}, ${brand.primaryColor}dd)` }}>
        <Card className="max-w-md w-full text-center">
          <Result status="success" title="You're Subscribed" subTitle="You will receive alerts at the contact information you provided. Every message includes an unsubscribe link." />
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-12" style={{ background: `linear-gradient(to bottom, ${brand.primaryColor}, ${brand.primaryColor}dd)` }}>
      <Card className="max-w-lg w-full">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-bold text-brand-primary">Campus Alerts</h1>
          <p className="text-ink-mute text-sm mt-1">Subscribe to receive emergency and campus notifications via email and SMS.</p>
        </div>
        <Form form={form} layout="vertical" onFinish={handleFinish}
          initialValues={{ categories: CATEGORIES.map(c => c.id) }}>
          <Form.Item name="name" label="Name" rules={[{ required: true }]}><Input placeholder="Your full name" /></Form.Item>
          <Form.Item name="email" label="Email Address"><Input type="email" placeholder="you@example.edu" /></Form.Item>
          <Form.Item name="phone" label="Phone Number (for SMS)">
            <Input placeholder="+1 (555) 123-4567" />
          </Form.Item>
          <p className="text-xs text-ink-mute -mt-4 mb-4">At least one of email or phone is required.</p>
          <Form.Item name="categories" label="Alert Categories">
            <Checkbox.Group className="flex flex-col gap-2">
              {CATEGORIES.map(c => (
                <Checkbox key={c.id} value={c.id}>
                  <span className="text-sm font-medium">{c.label}</span>
                  <p className="text-xs text-ink-mute">{c.description}</p>
                </Checkbox>
              ))}
            </Checkbox.Group>
          </Form.Item>
          <Button type="primary" htmlType="submit" block size="large" loading={submitting} style={{ background: brand.primaryColor }}>Subscribe to Alerts</Button>
          <p className="text-xs text-ink-mute text-center mt-3">You can unsubscribe at any time using the link in any alert message.</p>
        </Form>
      </Card>
    </div>
  );
}
