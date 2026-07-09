import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Button, Card, Tag, Table, Tabs, Statistic, Spin, Empty, Alert, Descriptions, Space, App, Timeline } from "antd";
import type { ColumnsType } from "antd/es/table";

interface PermitHistory {
  permit: any; has_hold: boolean; unpaid_amount: string;
  tickets: any[]; payments: any[]; audit_log: any[]; prior_permits: any[]; duplicates: any[];
}

export default function PermitDetail() {
  const { modal, message } = App.useApp();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<PermitHistory | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try { setData(await api.permits.history(id)); } catch { navigate("/permits"); } finally { setLoading(false); }
  }, [id, navigate]);

  useEffect(() => { load(); }, [load]);

  function handleRenew() {
    if (!id) return;
    modal.confirm({
      title: "Renew this permit?", content: "A new permit will be created with fresh dates.",
      okText: "Renew",
      onOk: async () => { await api.permits.renew(id); message.success("Permit renewed"); load(); },
    });
  }

  if (loading || !data) return <div className="flex justify-center py-12"><Spin size="large" /></div>;

  const p = data.permit;

  const ticketCols: ColumnsType<any> = [
    { title: "Date", dataIndex: "issued_at", key: "date", render: v => v ? new Date(v).toLocaleDateString() : "—" },
    { title: "Violation", dataIndex: "violation_type", key: "type", render: v => <span className="capitalize">{v?.replace(/_/g, " ")}</span> },
    { title: "Lot", dataIndex: "lot", key: "lot" },
    { title: "Fine", dataIndex: "fine_amount", key: "fine", render: v => `$${v}` },
    { title: "Status", dataIndex: "status", key: "status", render: s => <Tag color={s === "paid" ? "green" : s === "voided" ? "default" : "red"}>{s}</Tag> },
  ];

  const paymentCols: ColumnsType<any> = [
    { title: "Date", dataIndex: "created_at", key: "date", render: v => v ? new Date(v).toLocaleDateString() : "—" },
    { title: "Amount", dataIndex: "amount", key: "amount", render: v => `$${v}` },
    { title: "Status", dataIndex: "status", key: "status", render: v => <span className="capitalize">{v}</span> },
  ];

  const relatedCols: ColumnsType<any> = [
    { title: "Name", dataIndex: "name", key: "name" },
    { title: "Type", dataIndex: "permit_type", key: "type", render: v => <span className="capitalize">{v}</span> },
    { title: "Status", dataIndex: "status", key: "status", render: v => <span className="capitalize">{v}</span> },
    { title: "Dates", key: "dates", render: (_, r) => `${r.start_date} — ${r.end_date || "∞"}` },
  ];

  const tabItems = [
    {
      key: "overview", label: "Overview",
      children: (
        <div className="space-y-4">
          <h3 className="font-semibold">Summary</h3>
          <div className="grid grid-cols-3 gap-4">
            <Card size="small"><Statistic title="Total Tickets" value={data.tickets.length} /></Card>
            <Card size="small"><Statistic title="Payments" value={data.payments.length} /></Card>
            <Card size="small"><Statistic title="Unpaid Balance" value={data.has_hold ? `$${data.unpaid_amount}` : "$0"} valueStyle={data.has_hold ? { color: "#ef4444" } : {}} /></Card>
          </div>
          {data.duplicates.length > 0 && (
            <Alert type="warning" message="Duplicate Plate Warning" description={data.duplicates.map((d: any) => (
              <div key={d.permit_id}>{d.name} — {d.overlapping_plates.join(", ")} — {d.permit_type} ({d.lot_assignment})</div>
            ))} />
          )}
        </div>
      ),
    },
    {
      key: "tickets", label: <>Tickets{data.tickets.length > 0 && <Tag className="ml-1">{data.tickets.length}</Tag>}</>,
      children: <Table dataSource={data.tickets} columns={ticketCols} rowKey="id" size="small" pagination={false}
        locale={{ emptyText: <Empty description="No tickets issued" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }} />,
    },
    {
      key: "payments", label: "Payments",
      children: <Table dataSource={data.payments} columns={paymentCols} rowKey="id" size="small" pagination={false}
        locale={{ emptyText: <Empty description="No payments recorded" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }} />,
    },
    {
      key: "timeline", label: "Timeline",
      children: data.audit_log.length === 0
        ? <Empty description="No activity recorded" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        : <Timeline items={data.audit_log.map((entry: any) => ({
            children: (
              <div className="flex gap-3 items-start">
                <div className="flex-1"><div className="text-sm">{entry.summary}</div><div className="text-xs text-ink-mute">{new Date(entry.timestamp).toLocaleString()} by {entry.user_email}</div></div>
                <Tag color={entry.action === "POST" ? "green" : entry.action === "DELETE" ? "red" : "blue"}>{entry.action}</Tag>
              </div>
            ),
          }))} />,
    },
    {
      key: "related", label: "Related",
      children: (
        <div>
          <h3 className="font-semibold mb-3">Prior / Related Permits</h3>
          <Table dataSource={data.prior_permits} columns={relatedCols} rowKey="id" size="small" pagination={false}
            onRow={r => ({ onClick: () => navigate(`/permits/${r.id}`), className: "cursor-pointer" })}
            locale={{ emptyText: <Empty description="No related permits" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }} />
        </div>
      ),
    },
  ];

  return (
    <div>
      <Button type="link" onClick={() => navigate("/permits")} className="mb-4 px-0">&larr; Back to Permits</Button>

      <Card className="mb-6">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-2xl font-bold">{p.name}</h2>
            <Descriptions size="small" className="mt-2" column={4}>
              <Descriptions.Item label="ID">{p.student_id || "N/A"}</Descriptions.Item>
              <Descriptions.Item label="Plates"><span className="font-mono">{p.plates?.join(", ")}</span></Descriptions.Item>
              <Descriptions.Item label="Lot">{p.lot_assignment}</Descriptions.Item>
              <Descriptions.Item label="Type"><span className="capitalize">{p.permit_type}</span></Descriptions.Item>
              {p.email && <Descriptions.Item label="Email">{p.email}</Descriptions.Item>}
              {p.phone && <Descriptions.Item label="Phone">{p.phone}</Descriptions.Item>}
              <Descriptions.Item label="SMS">{p.sms_opt_in ? <Tag color="green">Opted In</Tag> : <Tag>Not opted in</Tag>}</Descriptions.Item>
            </Descriptions>
            <Space className="mt-3">
              <Tag color={p.status === "active" ? "green" : p.status === "expired" || p.status === "renewed" ? "default" : "red"}>{p.status}</Tag>
              {data.has_hold && <Tag color="red">HOLD — ${data.unpaid_amount} unpaid</Tag>}
              {data.duplicates.length > 0 && <Tag color="orange">DUPLICATE PLATE</Tag>}
            </Space>
            <div className="mt-4 flex gap-4 text-sm"><span>Start: {p.start_date || "—"}</span><span>End: {p.end_date || "No expiry"}</span></div>
          </div>
          {(p.status === "expired" || p.status === "active") && <Button type="primary" onClick={handleRenew}>Renew</Button>}
        </div>
      </Card>

      <Card styles={{ body: { padding: 0 } }}><Tabs items={tabItems} className="px-4" /></Card>
    </div>
  );
}
