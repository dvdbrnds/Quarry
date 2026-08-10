import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "../auth";
import {
  Card, Button, Input, Checkbox, Table, Form, DatePicker, Tag, Space, App, Empty,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

interface AcademicSeason {
  id: string; code: string; label: string; start_date: string; end_date: string; is_default: boolean;
}

export default function AcademicCalendar() {
  const { modal, message } = App.useApp();
  const [seasons, setSeasons] = useState<AcademicSeason[]>([]);
  const [newSeason, setNewSeason] = useState(false);
  const [seasonForm] = Form.useForm();
  const [editingSeason, setEditingSeason] = useState<AcademicSeason | null>(null);
  const [editForm] = Form.useForm();

  const load = useCallback(async () => {
    const res = await fetch("/api/academic-calendar", { headers: await authHeaders() });
    if (res.ok) setSeasons(await res.json());
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleAddSeason(values: any) {
    await fetch("/api/academic-calendar", { method: "POST", headers: await authHeaders(), body: JSON.stringify({
      ...values, start_date: values.start_date.format("YYYY-MM-DD"), end_date: values.end_date.format("YYYY-MM-DD"),
    })});
    message.success("Season added");
    setNewSeason(false); seasonForm.resetFields(); load();
  }

  function handleDeleteSeason(id: string) {
    modal.confirm({
      title: "Delete this season?", okText: "Delete", okButtonProps: { danger: true },
      onOk: async () => {
        const headers = await authHeaders();
        headers["X-HTTP-Method-Override"] = "DELETE";
        await fetch(`/api/academic-calendar/${id}`, { method: "POST", headers });
        message.success("Season deleted"); load();
      },
    });
  }

  function startEditSeason(s: AcademicSeason) {
    setEditingSeason(s);
    editForm.setFieldsValue({ code: s.code, label: s.label, start_date: dayjs(s.start_date), end_date: dayjs(s.end_date), is_default: s.is_default });
  }

  async function handleUpdateSeason(values: any) {
    if (!editingSeason) return;
    await fetch(`/api/academic-calendar/${editingSeason.id}`, { method: "PUT", headers: await authHeaders(), body: JSON.stringify({
      ...values, start_date: values.start_date.format("YYYY-MM-DD"), end_date: values.end_date.format("YYYY-MM-DD"),
    })});
    message.success("Season updated");
    setEditingSeason(null); load();
  }

  const seasonColumns: ColumnsType<AcademicSeason> = [
    { title: "Code", dataIndex: "code", key: "code", render: v => <span className="font-mono text-xs">{v}</span> },
    { title: "Label", dataIndex: "label", key: "label" },
    { title: "Start", dataIndex: "start_date", key: "start" },
    { title: "End", dataIndex: "end_date", key: "end" },
    { title: "Default", dataIndex: "is_default", key: "default", render: v => v ? <Tag color="blue">Yes</Tag> : null },
    {
      title: "Actions", key: "actions", width: 120,
      render: (_, s) => (
        <Space>
          <Button type="link" size="small" onClick={() => startEditSeason(s)}>Edit</Button>
          <Button type="link" size="small" danger onClick={() => handleDeleteSeason(s.id)}>Delete</Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-xl font-bold">Academic Calendar</h3>
        <Button type="primary" onClick={() => setNewSeason(true)}>+ Add Season</Button>
      </div>

      {newSeason && (
        <Card className="mb-4" title="New Season">
          <Form form={seasonForm} layout="vertical" onFinish={handleAddSeason}>
            <div className="grid grid-cols-2 gap-x-4">
              <Form.Item name="code" label="Code" rules={[{ required: true }]}><Input placeholder="fall_spring" /></Form.Item>
              <Form.Item name="label" label="Label" rules={[{ required: true }]}><Input placeholder="Fall/Spring 2025-2026" /></Form.Item>
              <Form.Item name="start_date" label="Start Date" rules={[{ required: true }]}><DatePicker className="w-full" /></Form.Item>
              <Form.Item name="end_date" label="End Date" rules={[{ required: true }]}><DatePicker className="w-full" /></Form.Item>
            </div>
            <Form.Item name="is_default" valuePropName="checked"><Checkbox>Default fallback season</Checkbox></Form.Item>
            <Space>
              <Button onClick={() => setNewSeason(false)}>Cancel</Button>
              <Button type="primary" htmlType="submit">Add Season</Button>
            </Space>
          </Form>
        </Card>
      )}

      {editingSeason && (
        <Card className="mb-4" title={`Edit Season: ${editingSeason.label}`}>
          <Form form={editForm} layout="vertical" onFinish={handleUpdateSeason}>
            <div className="grid grid-cols-2 gap-x-4">
              <Form.Item name="code" label="Code"><Input /></Form.Item>
              <Form.Item name="label" label="Label"><Input /></Form.Item>
              <Form.Item name="start_date" label="Start Date"><DatePicker className="w-full" /></Form.Item>
              <Form.Item name="end_date" label="End Date"><DatePicker className="w-full" /></Form.Item>
            </div>
            <Form.Item name="is_default" valuePropName="checked"><Checkbox>Default</Checkbox></Form.Item>
            <Space>
              <Button onClick={() => setEditingSeason(null)}>Cancel</Button>
              <Button type="primary" htmlType="submit">Save</Button>
            </Space>
          </Form>
        </Card>
      )}

      <Table dataSource={seasons} columns={seasonColumns} rowKey="id" size="small" pagination={false}
        locale={{ emptyText: <Empty description="No seasons configured" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }} />
    </div>
  );
}
