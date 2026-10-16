import { useEffect, useState } from "react";
import { authHeaders } from "../auth";
import {
  Card, Table, Tag, Button, Statistic, Space, Alert, App, Popconfirm, Tooltip, Progress, Input,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

interface PerStudent {
  email: string;
  total_tickets: number;
  sent: number;
  unsent: number;
  unsent_resolved: number;
  unsent_unpaid: number;
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
  emails_unsent_but_resolved: number;
  emails_unsent_and_unpaid: number;
  no_email_on_file: number;
  unique_students_affected: number;
  per_student: PerStudent[];
  unsent_tickets: UnsentTicket[];
}

interface ResendJob {
  running: boolean;
  total?: number; sent?: number; failed?: number; skipped?: number;
  error?: string | null;
}

export default function EmailAudit() {
  const [data, setData] = useState<AuditData | null>(null);
  const [loading, setLoading] = useState(true);
  const [resending, setResending] = useState<Set<string>>(new Set());
  const [resendingAll, setResendingAll] = useState(false);
  const [resendJob, setResendJob] = useState<ResendJob | null>(null);
  const [markingAll, setMarkingAll] = useState(false);
  const [pasteIds, setPasteIds] = useState("");
  const [markingPaste, setMarkingPaste] = useState(false);
  const [generatingScript, setGeneratingScript] = useState(false);
  const { message, modal } = App.useApp();

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

  const pollResend = async () => {
    setResendingAll(true);
    try {
      for (;;) {
        await new Promise((r) => setTimeout(r, 2000));
        const res = await fetch("/api/sync/email-resend-all/status", { headers: await authHeaders() });
        if (!res.ok) continue;
        const job: ResendJob = await res.json();
        setResendJob(job);
        if (!job.running) {
          if (job.error) message.error(`Resend stopped: ${job.error}`);
          else message.success(`Done. Sent ${job.sent}, failed ${job.failed}, skipped ${job.skipped}`);
          load();
          return;
        }
      }
    } finally {
      setResendingAll(false);
    }
  };

  const testSmtp = async () => {
    const res = await fetch("/api/sync/smtp-check", { headers: await authHeaders() });
    const result = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    modal[result.ok ? "success" : "error"]({
      title: result.ok ? "Mail server login works" : "Mail server check failed",
      width: 640,
      content: <pre className="text-xs whitespace-pre-wrap">{JSON.stringify(result, null, 2)}</pre>,
    });
  };

  const resendAll = async () => {
    setResendingAll(true);
    try {
      const res = await fetch("/api/sync/email-resend-all", {
        method: "POST",
        headers: await authHeaders(),
      });
      const result = await res.json();
      if (!res.ok) {
        message.error(`Failed: ${result.detail || "unknown error"}`);
        setResendingAll(false);
        return;
      }
      setResendJob(result);
      pollResend();
    } catch (e: any) {
      message.error(`Error: ${e.message}`);
      setResendingAll(false);
    }
  };

  useEffect(() => {
    (async () => {
      const res = await fetch("/api/sync/email-resend-all/status", { headers: await authHeaders() });
      if (!res.ok) return;
      const job: ResendJob = await res.json();
      if (job.running) { setResendJob(job); pollResend(); }
    })();
  }, []);

  const markAllSent = async () => {
    setMarkingAll(true);
    try {
      const res = await fetch("/api/sync/email-mark-sent", {
        method: "POST",
        headers: { ...await authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ mark_all: true }),
      });
      const result = await res.json();
      if (res.ok) {
        message.success(`Marked ${result.marked} tickets as sent`);
        load();
      } else {
        message.error(`Failed: ${result.detail || "unknown error"}`);
      }
    } catch (e: any) {
      message.error(`Error: ${e.message}`);
    } finally {
      setMarkingAll(false);
    }
  };

  const markPastedIds = async () => {
    const uuidRegex = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
    const ids = pasteIds.match(uuidRegex) || [];
    if (ids.length === 0) {
      message.error("No Citation IDs (UUIDs) found in pasted text");
      return;
    }
    setMarkingPaste(true);
    try {
      const res = await fetch("/api/sync/email-mark-sent", {
        method: "POST",
        headers: { ...await authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      });
      const result = await res.json();
      if (res.ok) {
        message.success(`Marked ${result.marked} of ${ids.length} tickets as sent`);
        setPasteIds("");
        load();
      } else {
        message.error(`Failed: ${result.detail || "unknown error"}`);
      }
    } catch (e: any) {
      message.error(`Error: ${e.message}`);
    } finally {
      setMarkingPaste(false);
    }
  };

  const generateScript = async () => {
    setGeneratingScript(true);
    try {
      const res = await fetch("/api/sync/email-reconcile-script", { headers: await authHeaders() });
      if (!res.ok) { message.error("Failed to generate script"); return; }
      const result = await res.json();
      modal.info({
        title: "Gmail Reconciliation — Google Apps Script",
        width: 720,
        content: (
          <div>
            <p className="mb-2">This script searches the parking mailbox's Sent folder for citation emails and tells Quarry which ones were actually delivered.</p>
            <ol className="list-decimal ml-5 mb-3 text-sm space-y-1">
              <li>Open <a href="https://script.google.com" target="_blank" rel="noreferrer" className="text-blue-600 underline">script.google.com</a> while logged in as the parking email account</li>
              <li>Click <strong>New Project</strong></li>
              <li>Delete the default code and paste the script below</li>
              <li>Click <strong>Run</strong> → authorize when prompted</li>
              <li>Check the <strong>Execution Log</strong> for results</li>
              <li>Come back here and refresh — the numbers will update</li>
            </ol>
            <p className="text-xs text-amber-600 mb-2">⏱ Token expires in {result.expires_in_minutes} minutes</p>
            <Input.TextArea
              rows={12}
              value={result.script}
              readOnly
              className="font-mono text-xs"
              onClick={(e) => (e.target as HTMLTextAreaElement).select()}
            />
            <Button
              className="mt-2"
              size="small"
              onClick={() => { navigator.clipboard.writeText(result.script); message.success("Script copied to clipboard"); }}
            >
              Copy to Clipboard
            </Button>
          </div>
        ),
      });
    } catch (e: any) {
      message.error(`Error: ${e.message}`);
    } finally {
      setGeneratingScript(false);
    }
  };

  if (loading || !data) {
    return <div className="p-6"><Card loading /></div>;
  }

  const sentPct = data.emails_intended > 0
    ? Math.round((data.emails_confirmed_sent / data.emails_intended) * 100)
    : 100;

  const needsReconciliation = data.emails_unsent === data.emails_intended && data.emails_intended > 0;

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
      title: "Unsent (Paid)", dataIndex: "unsent_resolved", key: "resolved",
      render: (v: number) => v > 0 ? <Tag color="orange">{v}</Tag> : <Tag>0</Tag>,
      sorter: (a, b) => (a.unsent_resolved || 0) - (b.unsent_resolved || 0),
    },
    {
      title: "Unsent (Unpaid)", dataIndex: "unsent_unpaid", key: "unpaid",
      render: (v: number) => v > 0 ? <Tag color="red">{v}</Tag> : <Tag color="green">0</Tag>,
      sorter: (a, b) => (a.unsent_unpaid || 0) - (b.unsent_unpaid || 0),
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
    {
      title: "Citation ID", dataIndex: "id", key: "id",
      render: (v: string) => <span className="text-xs font-mono text-gray-400">{v.slice(0, 13)}…</span>,
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
        <Space>
          <Button onClick={testSmtp}>Test Mail Server</Button>
          {!needsReconciliation && data.unsent_tickets.length > 0 && (
            <Button
              onClick={() => {
                const emails = [...new Set(data.unsent_tickets.map(t => t.email))].sort();
                const csv = "email,plate,ticket_number,violation_type,fine_amount,status,issued_at\n" +
                  data.unsent_tickets.map(t =>
                    `${t.email},${t.plate},${t.ticket_number || ""},${t.violation_type},${t.fine_amount},${t.status},${t.issued_at || ""}`
                  ).join("\n");
                const blob = new Blob([csv], { type: "text/csv" });
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = "unsent_citations_contact_list.csv";
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(a.href);
              }}
            >
              Export Contact List ({[...new Set(data.unsent_tickets.map(t => t.email))].length} people)
            </Button>
          )}
          {!needsReconciliation && data.unsent_tickets.length > 0 && (
            <Button
              onClick={() => {
                const emails = [...new Set(data.unsent_tickets.map(t => t.email))].sort();
                navigator.clipboard.writeText(emails.join("\n"));
                message.success(`${emails.length} email addresses copied to clipboard`);
              }}
            >
              Copy Emails
            </Button>
          )}
          {data.unsent_tickets.length > 0 && !needsReconciliation && (
            <Popconfirm
              title={`Resend ${data.unsent_tickets.length} citation emails?`}
              description="Only unpaid/unresolved tickets — students who already paid won't be emailed."
              onConfirm={resendAll}
              okText="Resend All"
              okType="danger"
            >
              <Button type="primary" danger loading={resendingAll}>
                Resend All Unpaid ({data.unsent_tickets.length})
              </Button>
            </Popconfirm>
          )}
        </Space>
      </div>

      {resendJob && (resendJob.running || resendingAll) && (
        <Card size="small" className="mb-6">
          <div className="text-sm font-medium mb-2">
            Resending citation emails: {(resendJob.sent ?? 0) + (resendJob.failed ?? 0) + (resendJob.skipped ?? 0)} of {resendJob.total ?? 0}
            {" "}(sent {resendJob.sent ?? 0}, failed {resendJob.failed ?? 0}, skipped {resendJob.skipped ?? 0})
          </div>
          <Progress percent={resendJob.total ? Math.round((((resendJob.sent ?? 0) + (resendJob.failed ?? 0) + (resendJob.skipped ?? 0)) / resendJob.total) * 100) : 0} />
          <div className="text-xs text-gray-500 mt-1">This runs on the server. You can leave this page; it keeps going.</div>
        </Card>
      )}

      <Alert
        type="warning"
        showIcon
        className="mb-6"
        message="Email Delivery Bug — Sep 18 to Oct 15, 2026"
        description="A background task bug caused some citation emails to be silently dropped. 628 of 942 intended emails were confirmed sent via Gmail. The remaining 314 were never delivered."
      />

      {needsReconciliation && (
        <Alert
          type="error"
          showIcon
          className="mb-6"
          message="Reconciliation Required"
          description={
            <div>
              <p className="mb-3">
                All {data.emails_intended} emails show as "unsent" because the tracking column was just added.
                Run the Gmail reconciliation to automatically match which emails were actually delivered.
              </p>

              <Space direction="vertical" className="w-full" size="middle">
                <div>
                  <p className="text-sm font-medium mb-2">Option A — Automatic (recommended):</p>
                  <Button
                    type="primary"
                    size="large"
                    loading={generatingScript}
                    onClick={generateScript}
                  >
                    🔍 Run Gmail Reconciliation
                  </Button>
                  <p className="text-xs text-gray-500 mt-1">
                    Generates a Google Apps Script that scans the parking mailbox's Sent folder,
                    extracts all Citation IDs, and marks them as sent — fully automated.
                  </p>
                </div>

                <div>
                  <p className="text-sm font-medium mb-1">Option B — Paste Citation IDs manually:</p>
                  <Space.Compact className="w-full">
                    <Input.TextArea
                      rows={2}
                      placeholder="Paste email subjects or text containing Citation IDs (UUIDs)..."
                      value={pasteIds}
                      onChange={(e) => setPasteIds(e.target.value)}
                    />
                  </Space.Compact>
                  {pasteIds && (
                    <Button
                      className="mt-2"
                      type="primary"
                      loading={markingPaste}
                      onClick={markPastedIds}
                    >
                      Mark Matched as Sent ({(pasteIds.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi) || []).length} UUIDs found)
                    </Button>
                  )}
                </div>

                <div>
                  <p className="text-sm font-medium mb-1">Option C — Mark all as sent:</p>
                  <Popconfirm
                    title={`Mark all ${data.emails_intended} as sent?`}
                    description="Only use this if you've confirmed via Gmail that most emails were delivered."
                    onConfirm={markAllSent}
                    okText="Mark All Sent"
                  >
                    <Button loading={markingAll} size="small">Mark All as Sent</Button>
                  </Popconfirm>
                </div>
              </Space>
            </div>
          }
        />
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <Card size="small"><Statistic title="Emails Intended" value={data.emails_intended} /></Card>
        <Card size="small">
          <Statistic title="Confirmed Sent" value={data.emails_confirmed_sent} valueStyle={data.emails_confirmed_sent > 0 ? { color: "#3f8600" } : {}} />
        </Card>
        <Card size="small">
          <Tooltip title="Didn't get the email, but already paid/voided/resolved — no action needed">
            <Statistic title="Unsent but Resolved" value={data.emails_unsent_but_resolved || 0} valueStyle={{ color: "#d4880f" }} />
          </Tooltip>
        </Card>
        <Card size="small">
          <Tooltip title="Never got the email AND ticket is still unpaid — these need resending">
            <Statistic title="Need Resend" value={data.emails_unsent_and_unpaid || 0} valueStyle={(data.emails_unsent_and_unpaid || 0) > 0 ? { color: "#cf1322" } : {}} />
          </Tooltip>
        </Card>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <Card size="small"><Statistic title="Total Tickets" value={data.total_tickets} /></Card>
        <Card size="small"><Statistic title="No Email on File" value={data.no_email_on_file} /></Card>
        <Card size="small"><Statistic title="Students Affected" value={data.unique_students_affected} /></Card>
      </div>

      {!needsReconciliation && (
        <Card size="small" className="mb-6">
          <div className="flex items-center gap-4">
            <span className="text-sm font-medium w-28">Delivery Rate</span>
            <Progress
              percent={sentPct}
              success={{ percent: sentPct }}
              format={() => `${sentPct}% sent`}
              style={{ flex: 1 }}
            />
            {data.emails_unsent > 0 && (
              <Tooltip title={`${data.emails_unsent} emails need to be resent`}>
                <Tag color="red">{data.emails_unsent} missed</Tag>
              </Tooltip>
            )}
          </div>
        </Card>
      )}

      <Card title="By Student" size="small" className="mb-6">
        <Table
          dataSource={data.per_student}
          columns={studentColumns}
          rowKey="email"
          size="small"
          pagination={{ pageSize: 20 }}
        />
      </Card>

      {!needsReconciliation && (
        <Card
          title={<Space>Unsent & Unpaid — Need Resend <Tag color="red">{data.unsent_tickets.length}</Tag></Space>}
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
      )}
    </div>
  );
}
