import { useEffect, useState } from "react";
import { authHeaders } from "../auth";
import {
  Card, Table, Tag, Button, Statistic, Space, Alert, App, Popconfirm, Tooltip, Progress,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

interface PerStudent {
  email: string;
  total_tickets: number;
  sent: number;
  unsent: number;
  first_ticket: string | null;
  last_ticket: string | null;
}

interface UnsentTicket {
  id: string;
  ticket_number: string | null;
  plate: string;
  email: string;
  violation_type: string;
  fine_amount: string;
  status: string;
  issued_at: string | null;
}

interface AuditData {
  bug_window: { start: string; end: string };
  total_tickets: number;
  emails_intended: number;
  emails_confirmed_sent: number;
  emails_unsent: number;
  no_email_on_file: number;
  unique_students_affected: number;
  per_student: PerStudent[];
  unsent_tickets: UnsentTicket[];
}

export default function EmailAudit() {
  const [data, setData] = useState<AuditData | null>(null);
  const [loading, setLoading] = useState(true);
  const [resending, setResending] = useState<Set<string>>(new Set());
  const [resendingAll, setResendingAll] = useState(false);
  const { message } = App.useApp();

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/sync/email-audit", { headers: await authHeaders() });
      if (res.ok) setData(await res.json());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const resendOne = async (ticketId: string) => {
    setResending((s) => new Set(s).add(ticketId));
    try {
      const res = await fetch(`/api/sync/email-resend/${ticketId}`, {
        method: "POST",
        headers: await authHeaders(),
      });
      const result = await res.json();
      if (res.ok && result.status === "sent") {
        message.success(`Email sent to ${result.email}`);
        load();
      } else {
        message.error(`Failed: ${result.detail || result.status || "unknown error"}`);
      }
    } catch (e: any) {
      message.error(`Error: ${e.message}`);
    } finally {
      setResending((s) => { const n = new Set(s); n.delete(ticketId); return n; });
    }
  };

  const resendAll = async () => {
    setResendingAll(true);
    try {
      const res = await fetch("/api/sync/email-resend-all", {
        method: "POST",
        headers: await authHeaders(),
      });
      const result = await res.json();
      if (res.ok) {
        message.success(`Sent: ${result.sent}, Failed: ${result.failed}`);
        load();
      } else {
        message.error(`Failed: ${result.detail || "unknown error"}`);
      }
    } catch (e: any) {
      message.error(`Error: ${e.message}`);
    } finally {
      setResendingAll(false);
    }
  };

  if (loading || !data) {
    return <div className="p-6"><Card loading /></div>;
  }

  const sentPct = data.emails_intended > 0
    ? Math.round((data.emails_confirmed_sent / data.emails_intended) * 100)
    : 100;
  const unsentPct = 100 - sentPct;

  const studentColumns: ColumnsType<PerStudent> = [
    {
      title: "Student Email", dataIndex: "email", key: "email",
      sorter: (a, b) => a.email.localeCompare(b.email),
    },
    {
      title: "Tickets", dataIndex: "total_tickets", key: "total",
      sorter: (a, b) => a.total_tickets - b.total_tickets,
    },
    {
      title: "Emails Sent", dataIndex: "sent", key: "sent",
      render: (v: number) => <Tag color={v > 0 ? "green" : "default"}>{v}</Tag>,
    },
    {
      title: "Emails Unsent", dataIndex: "unsent", key: "unsent",
      render: (v: number) => v > 0 ? <Tag color="red">{v}</Tag> : <Tag color="green">0</Tag>,
      sorter: (a, b) => a.unsent - b.unsent,
      defaultSortOrder: "descend",
    },
    {
      title: "Date Range", key: "range",
      render: (_: unknown, r: PerStudent) => (
        <span className="text-xs text-gray-500">
          {r.first_ticket ? dayjs(r.first_ticket).format("MMM D") : "?"} — {r.last_ticket ? dayjs(r.last_ticket).format("MMM D") : "?"}
        </span>
      ),
    },
  ];

  const ticketColumns: ColumnsType<UnsentTicket> = [
    {
      title: "Ticket #", dataIndex: "ticket_number", key: "num",
      render: (v: string | null, r: UnsentTicket) => v || r.id.slice(0, 8),
    },
    { title: "Plate", dataIndex: "plate", key: "plate" },
    { title: "Student Email", dataIndex: "email", key: "email" },
    { title: "Violation", dataIndex: "violation_type", key: "vt" },
    {
      title: "Fine", dataIndex: "fine_amount", key: "fine",
      render: (v: string) => `$${v}`,
    },
    {
      title: "Status", dataIndex: "status", key: "status",
      render: (v: string) => {
        const colors: Record<string, string> = {
          issued: "orange", paid: "green", appealed: "blue",
          escalated: "red", past_due: "volcano",
        };
        return <Tag color={colors[v] || "default"}>{v}</Tag>;
      },
    },
    {
      title: "Issued", dataIndex: "issued_at", key: "issued",
      render: (v: string | null) => v ? dayjs(v).format("MMM D, YYYY h:mm A") : "—",
    },
    {
      title: "Action", key: "action",
      render: (_: unknown, r: UnsentTicket) => (
        <Button
          size="small"
          type="primary"
          loading={resending.has(r.id)}
          onClick={() => resendOne(r.id)}
        >
          Resend
        </Button>
      ),
    },
  ];

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Citation Email Audit</h2>
        {data.unsent_tickets.length > 0 && (
          <Popconfirm
            title={`Resend ${data.unsent_tickets.length} citation emails?`}
            description="This will email every student who missed a citation notification."
            onConfirm={resendAll}
            okText="Resend All"
            okType="danger"
          >
            <Button type="primary" danger loading={resendingAll}>
              Resend All Unsent ({data.unsent_tickets.length})
            </Button>
          </Popconfirm>
        )}
      </div>

      <Alert
        type="warning"
        showIcon
        className="mb-6"
        message="Email Delivery Bug — Sep 18 to Oct 15, 2026"
        description={
          <span>
            A background task bug caused some citation emails to be silently dropped.
            Emails were queued but the task reference wasn't retained, so Python's garbage
            collector could cancel them before delivery. This page shows which emails were
            confirmed sent vs. which need to be resent.
          </span>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <Card size="small"><Statistic title="Total Tickets" value={data.total_tickets} /></Card>
        <Card size="small"><Statistic title="Emails Intended" value={data.emails_intended} /></Card>
        <Card size="small">
          <Statistic title="Confirmed Sent" value={data.emails_confirmed_sent} valueStyle={{ color: "#3f8600" }} />
        </Card>
        <Card size="small">
          <Statistic title="Unsent" value={data.emails_unsent} valueStyle={data.emails_unsent > 0 ? { color: "#cf1322" } : {}} />
        </Card>
        <Card size="small"><Statistic title="No Email on File" value={data.no_email_on_file} /></Card>
      </div>

      <Card size="small" className="mb-6">
        <div className="flex items-center gap-4">
          <span className="text-sm font-medium w-28">Delivery Rate</span>
          <Progress
            percent={sentPct}
            success={{ percent: sentPct }}
            format={() => `${sentPct}% sent`}
            style={{ flex: 1 }}
          />
          {unsentPct > 0 && (
            <Tooltip title={`${data.emails_unsent} emails need to be resent`}>
              <Tag color="red">{unsentPct}% missed</Tag>
            </Tooltip>
          )}
        </div>
      </Card>

      <Card title="By Student" size="small" className="mb-6">
        <Table
          dataSource={data.per_student}
          columns={studentColumns}
          rowKey="email"
          size="small"
          pagination={{ pageSize: 20 }}
        />
      </Card>

      <Card
        title={<Space>Unsent Tickets <Tag color="red">{data.unsent_tickets.length}</Tag></Space>}
        size="small"
      >
        {data.unsent_tickets.length === 0 ? (
          <Alert type="success" message="All citation emails have been sent!" showIcon />
        ) : (
          <Table
            dataSource={data.unsent_tickets}
            columns={ticketColumns}
            rowKey="id"
            size="small"
            pagination={{ pageSize: 50 }}
          />
        )}
      </Card>
    </div>
  );
}
