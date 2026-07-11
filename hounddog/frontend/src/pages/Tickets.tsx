import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Table, Input, Select, Tag, Button, Modal, Descriptions, Space, App, Image, Empty } from "antd";
import type { ColumnsType } from "antd/es/table";
import { authHeaders } from "../auth";
import { useCurrentUser } from "../UserContext";

interface Ticket {
  id: string;
  ticket_number: string | null;
  plate: string;
  lot: string;
  zone: string | null;
  violation_type: string;
  fine_amount: string;
  photo_url: string | null;
  officer_id: string;
  officer_name: string | null;
  officer_email: string | null;
  owner_name: string | null;
  permit_number: string | null;
  issued_at: string;
  status: string;
  ticket_category: string;
  location_text: string | null;
  vehicle_description: string | null;
  driver_name: string | null;
  driver_license: string | null;
  officer_notes: string | null;
  appeal_note: string | null;
  appeal_decision: string | null;
  appeal_decided_by: string | null;
  dispute_name: string | null;
  dispute_email: string | null;
  dispute_phone: string | null;
}

const STATUS_COLORS: Record<string, string> = {
  issued: "red",
  pending_payment: "orange",
  paid: "green",
  appealed: "gold",
  escalated: "purple",
  voided: "default",
};

export default function Tickets() {
  const { modal, message } = App.useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const user = useCurrentUser();
  const isAdmin = user?.role === "admin";
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState(searchParams.get("search") ?? "");
  const [statusFilter, setStatusFilter] = useState(searchParams.get("status") ?? "");
  const [categoryFilter, setCategoryFilter] = useState(searchParams.get("category") ?? "");
  const [selected, setSelected] = useState<Ticket | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (statusFilter) params.set("status", statusFilter);
    if (categoryFilter) params.set("category", categoryFilter);
    setSearchParams(params, { replace: true });
  }, [search, statusFilter, categoryFilter, setSearchParams]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      qs.set("page", String(page));
      if (search) qs.set("search", search);
      if (statusFilter) qs.set("status", statusFilter);
      if (categoryFilter) qs.set("category", categoryFilter);
      const res = await fetch(`/api/tickets?${qs}`, { headers: await authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setTickets(data.items);
        setTotal(data.total);
      }
    } catch {
      message.error("Failed to load tickets");
    } finally {
      setLoading(false);
    }
  }, [page, search, statusFilter, categoryFilter, message]);

  useEffect(() => { load(); }, [load]);

  async function handleVoid(id: string) {
    if (!isAdmin) return;
    modal.confirm({
      title: "Void this ticket?",
      content: "This action will void the ticket and cannot be easily reversed.",
      okText: "Void Ticket",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await fetch(`/api/tickets/${id}/void`, { method: "POST", headers: await authHeaders() });
          message.success("Ticket voided");
          load();
          setSelected(null);
        } catch {
          message.error("Failed to void ticket");
        }
      },
    });
  }

  async function handleAppealDecision(id: string, decision: string) {
    if (!isAdmin) return;
    const decided_by = user?.email || "admin";
    try {
      await fetch(`/api/tickets/${id}/appeal/decide`, {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({ decision, decided_by }),
      });
      message.success(`Appeal ${decision}`);
      load();
      setSelected(null);
    } catch {
      message.error("Failed to process appeal decision");
    }
  }

  const columns: ColumnsType<Ticket> = [
    {
      title: "Ticket #",
      dataIndex: "ticket_number",
      key: "ticket_number",
      width: 120,
      render: (num: string | null) => <span className="font-mono text-navy font-medium">{num || "—"}</span>,
    },
    {
      title: "Plate",
      dataIndex: "plate",
      key: "plate",
      render: (plate: string) => <span className="font-mono">{plate}</span>,
    },
    {
      title: "Location",
      key: "location",
      render: (_, t) => t.ticket_category === "moving" ? (t.location_text || "—") : t.lot,
    },
    {
      title: "Violation",
      key: "violation",
      render: (_, t) => (
        <Space>
          <span className="capitalize">{t.violation_type.replace(/_/g, " ")}</span>
          {t.ticket_category === "moving" && <Tag color="red">MOVING</Tag>}
        </Space>
      ),
    },
    {
      title: "Fine",
      dataIndex: "fine_amount",
      key: "fine",
      render: (amt: string) => `$${Number(amt).toFixed(2)}`,
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string) => (
        <Tag color={STATUS_COLORS[status] || "default"}>
          {status.replace("_", " ")}
        </Tag>
      ),
    },
    {
      title: "Issued",
      dataIndex: "issued_at",
      key: "issued_at",
      render: (d: string) => new Date(d).toLocaleDateString(),
    },
    {
      title: "Actions",
      key: "actions",
      width: 100,
      render: (_, t) =>
        isAdmin && !["paid", "voided"].includes(t.status) ? (
          <Button type="link" danger size="small" onClick={(e) => { e.stopPropagation(); handleVoid(t.id); }}>
            Void
          </Button>
        ) : null,
    },
  ];

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Tickets</h2>

      <Space className="mb-4" wrap>
        <Input.Search
          placeholder="Search by ticket #, plate, or officer..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          onSearch={() => setPage(1)}
          style={{ width: 300 }}
          allowClear
        />
        <Select
          value={statusFilter || undefined}
          onChange={(val) => { setStatusFilter(val || ""); setPage(1); }}
          placeholder="All Statuses"
          allowClear
          style={{ width: 170 }}
          options={[
            { label: "Issued", value: "issued" },
            { label: "Pending Payment", value: "pending_payment" },
            { label: "Paid", value: "paid" },
            { label: "Appealed", value: "appealed" },
            { label: "Escalated", value: "escalated" },
            { label: "Voided", value: "voided" },
          ]}
        />
        <Select
          value={categoryFilter || undefined}
          onChange={(val) => { setCategoryFilter(val || ""); setPage(1); }}
          placeholder="All Types"
          allowClear
          style={{ width: 140 }}
          options={[
            { label: "Parking", value: "parking" },
            { label: "Moving", value: "moving" },
          ]}
        />
      </Space>

      <Table
        dataSource={tickets}
        columns={columns}
        rowKey="id"
        loading={loading}
        onRow={(t) => ({ onClick: () => setSelected(t), className: "cursor-pointer" })}
        pagination={{
          current: page,
          total,
          pageSize: 50,
          onChange: setPage,
          showSizeChanger: false,
          showTotal: (t) => `${t} tickets`,
        }}
        locale={{ emptyText: <Empty description="No tickets found" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />

      <Modal
        open={!!selected}
        onCancel={() => setSelected(null)}
        title={
          <Space>
            {selected?.ticket_number || (selected?.ticket_category === "moving" ? "Citation Detail" : "Ticket Detail")}
            {selected?.ticket_category === "moving" && <Tag color="red">Moving Violation</Tag>}
          </Space>
        }
        footer={
          <Space>
            <Button onClick={() => setSelected(null)}>Close</Button>
            {isAdmin && selected?.appeal_decision === "pending" && (
              <>
                <Button type="primary" style={{ background: "#22C55E" }} onClick={() => handleAppealDecision(selected!.id, "approved")}>
                  Approve Appeal
                </Button>
                <Button danger onClick={() => handleAppealDecision(selected!.id, "denied")}>
                  Deny Appeal
                </Button>
              </>
            )}
            {isAdmin && selected && !["paid", "voided"].includes(selected.status) && (
              <Button danger type="primary" onClick={() => handleVoid(selected.id)}>Void Ticket</Button>
            )}
          </Space>
        }
        width={560}
      >
        {selected && (
          <div className="space-y-4">
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="Plate"><span className="font-mono">{selected.plate}</span></Descriptions.Item>
              <Descriptions.Item label={selected.ticket_category === "moving" ? "Location" : "Lot"}>
                {selected.ticket_category === "moving" ? (selected.location_text || "—") : selected.lot}
              </Descriptions.Item>
              <Descriptions.Item label="Violation">{selected.violation_type.replace(/_/g, " ")}</Descriptions.Item>
              <Descriptions.Item label="Fine">${Number(selected.fine_amount).toFixed(2)}</Descriptions.Item>
              <Descriptions.Item label="Status"><Tag color={STATUS_COLORS[selected.status]}>{selected.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="Officer">{selected.officer_name || selected.officer_id}</Descriptions.Item>
              {selected.owner_name && <Descriptions.Item label="Owner">{selected.owner_name}</Descriptions.Item>}
              {selected.permit_number && <Descriptions.Item label="Permit #">{selected.permit_number}</Descriptions.Item>}
              <Descriptions.Item label="Issued" span={2}>{new Date(selected.issued_at).toLocaleString()}</Descriptions.Item>
            </Descriptions>

            {selected.ticket_category === "moving" && (
              <div className="bg-red-50 border border-red-100 rounded-lg p-3 text-sm">
                <div className="font-medium text-red-800 mb-2">Driver & Vehicle</div>
                <Descriptions size="small" column={2}>
                  {selected.driver_name && <Descriptions.Item label="Driver">{selected.driver_name}</Descriptions.Item>}
                  {selected.driver_license && <Descriptions.Item label="License"><span className="font-mono">{selected.driver_license}</span></Descriptions.Item>}
                  {selected.vehicle_description && <Descriptions.Item label="Vehicle" span={2}>{selected.vehicle_description}</Descriptions.Item>}
                  {selected.officer_notes && <Descriptions.Item label="Notes" span={2}>{selected.officer_notes}</Descriptions.Item>}
                </Descriptions>
              </div>
            )}

            {selected.photo_url && (
              <Image src={selected.photo_url} alt="Violation photo" className="rounded-lg max-h-48 object-cover" />
            )}

            {selected.appeal_note && (
              <div className="bg-yellow-50 rounded-lg p-3 text-sm">
                <div className="font-medium text-yellow-800 mb-1">Appeal Note</div>
                <p>{selected.appeal_note}</p>
                {(selected.dispute_name || selected.dispute_email || selected.dispute_phone) && (
                  <div className="mt-2 pt-2 border-t border-yellow-200 text-xs text-ink-mute space-y-0.5">
                    {selected.dispute_name && <div>Name: <span className="text-ink">{selected.dispute_name}</span></div>}
                    {selected.dispute_email && (
                      <div>Email: <a href={`mailto:${selected.dispute_email}`} className="text-brass hover:underline">{selected.dispute_email}</a></div>
                    )}
                    {selected.dispute_phone && <div>Phone: <span className="text-ink">{selected.dispute_phone}</span></div>}
                  </div>
                )}
                {selected.appeal_decision && (
                  <div className="mt-2 text-xs text-ink-mute">
                    Decision: <strong>{selected.appeal_decision}</strong>
                    {selected.appeal_decided_by && ` by ${selected.appeal_decided_by}`}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
