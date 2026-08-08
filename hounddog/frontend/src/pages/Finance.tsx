import { useCallback, useEffect, useRef, useState } from "react";
import { authHeaders } from "../auth";
import {
  Card, Statistic, Table, Tag, Select, Button, Space, Segmented, DatePicker, Alert, App, Empty, Spin, Tabs, Descriptions, Tooltip,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

async function downloadWithAuth(url: string, filename: string) {
  const res = await fetch(url, { headers: await authHeaders() });
  if (!res.ok) return;
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

interface RevenueReport {
  total_fines_issued: string; total_collected: string; total_outstanding: string;
  collection_rate: number; by_method: Record<string, string>;
  by_status: Record<string, number>; by_payment_type: Record<string, string>;
}

interface PaymentListItem {
  id: string; ticket_id: string | null; amount: string; method: string;
  stripe_payment_id: string | null; payment_type: string | null;
  payer_name: string | null; payer_email: string | null;
  description: string | null; plate: string | null; paid_at: string;
}

interface PaymentListResponse {
  items: PaymentListItem[]; total: number; page: number; page_size: number; pages: number;
}

interface TimeSeriesPoint { date: string; citations_amount: string; permits_amount: string; total: string; }
interface BursarResult { matched: number; unmatched: number; errors: string[]; }

interface StripeTransaction {
  id: string; source: string; amount: string; amount_refunded: string; net: string; fee: string;
  currency: string; status: string; description: string | null;
  customer_email: string | null; customer_name: string | null;
  receipt_url: string | null; payment_method_type: string | null;
  payment_method_last4: string | null; payment_method_brand: string | null;
  metadata: Record<string, string>; created: string; livemode: boolean;
}

interface StripeOverview {
  total_volume: string; total_fees: string; total_net: string;
  total_refunded: string; successful_count: number;
  refunded_count: number; failed_count: number;
}

interface StripeTransactionsResponse {
  overview: StripeOverview; transactions: StripeTransaction[]; has_more: boolean;
  errors?: string[];
}

const TYPE_COLORS: Record<string, string> = {
  ticket_payment: "red", permit_purchase: "blue", standalone_permit_purchase: "blue", lottery_permit: "purple",
};
const TYPE_LABELS: Record<string, string> = {
  ticket_payment: "Citation", permit_purchase: "Permit", standalone_permit_purchase: "Permit", lottery_permit: "Lottery",
};
const METHOD_LABELS: Record<string, string> = {
  online_card: "Stripe", online_permit_purchase: "Stripe", bursar: "Bursar",
};

const fmtDollars = (val: string | number) => `$${Number(val).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;

function exportStripeGl(transactions: StripeTransaction[]) {
  const batchDate = dayjs().format("YYYY-MM-DD");
  const batchName = `QUARRY-${batchDate}`;
  const LEDGER = "Moravian Primary Ledger";
  const SOURCE = "QUARRY";
  const CATEGORY = "Revenue";

  const rows: string[][] = [];
  rows.push([
    "LedgerName", "AccountingDate", "UserJeSource", "UserJeCategory",
    "CurrencyCode", "JeBatchName", "JeHeaderName", "JeLineName",
    "Segment1", "Segment2", "Segment3", "Segment4", "Segment5", "Segment6",
    "AccountCombination", "EnteredDrAmount", "EnteredCrAmount",
    "LineDescription", "Reference1", "Reference2", "Reference3",
    "Reference4", "Reference5",
  ]);

  for (const t of transactions) {
    if (t.status !== "succeeded") continue;

    const m = t.metadata || {};
    const acctDate = dayjs(t.created).format("YYYY-MM-DD");
    const headerName = `${SOURCE}-${acctDate}`;
    const refId = t.id.slice(0, 16);
    const gross = Number(t.amount);
    const fee = Number(t.fee);
    const net = Number(t.net) || (gross - fee);

    const glString = m.gl_string || "";
    const glFund = m.gl_fund || "1110000";
    const glOrg = m.gl_org || "3006";
    const glAccount = m.gl_account || "43002";
    const glActivity = m.gl_activity || "1068";
    const seg5 = "0000000";
    const seg6 = "00000";

    const ptype = m.type || "";
    const isPermit = ptype.includes("permit");
    const description = isPermit
      ? `Parking permit — ${m.permit_type_label || m.permit_type_code || "permit"} ${m.plate || ""}`.trim()
      : `Citation #${m.ticket_ref || t.id.slice(0, 8).toUpperCase()} — ${m.plate || ""}`.trim();

    const ticketRef = m.ticket_ref || "";
    const lineMethod = ptype || "";

    // Net cash account
    const netCashFund = glFund;
    const netCashOrg = "0000";
    const netCashAcct = "10005";
    const netCashActivity = "0000";
    const netCashString = [netCashFund, netCashOrg, netCashAcct, netCashActivity, seg5, seg6].join("-");

    // Stripe fee account
    const feeOrg = glOrg;
    const feeAcct = "60164";
    const feeActivity = "0000";
    const feeString = [glFund, feeOrg, feeAcct, feeActivity, seg5, seg6].join("-");

    // Revenue account
    const revString = glString || [glFund, glOrg, glAccount, glActivity, seg5, seg6].join("-");

    // Line 1: Debit — Net cash
    rows.push([
      LEDGER, acctDate, SOURCE, CATEGORY, "USD", batchName, headerName,
      `DR-CASH-${refId.slice(0, 8)}`,
      netCashFund, netCashOrg, netCashAcct, netCashActivity, seg5, seg6,
      netCashString, net.toFixed(2), "",
      description, refId, ticketRef, lineMethod, t.id, "",
    ]);

    // Line 2: Debit — Stripe fee (if any)
    if (fee > 0) {
      rows.push([
        LEDGER, acctDate, SOURCE, CATEGORY, "USD", batchName, headerName,
        `DR-FEE-${refId.slice(0, 8)}`,
        glFund, feeOrg, feeAcct, feeActivity, seg5, seg6,
        feeString, fee.toFixed(2), "",
        `Stripe fee - ${description}`, refId, ticketRef, lineMethod, t.id, "",
      ]);
    }

    // Line 3: Credit — Revenue (full gross)
    rows.push([
      LEDGER, acctDate, SOURCE, CATEGORY, "USD", batchName, headerName,
      `CR-REV-${refId.slice(0, 8)}`,
      glFund, glOrg, glAccount, glActivity, seg5, seg6,
      revString, "", gross.toFixed(2),
      description, refId, ticketRef, lineMethod, t.id, "",
    ]);
  }

  // Generate and download CSV
  const csv = rows.map(r => r.map(c => `"${(c || "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `quarry_gl_journal_${batchDate}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export default function Finance() {
  const { message } = App.useApp();
  const [report, setReport] = useState<RevenueReport | null>(null);
  const [payments, setPayments] = useState<PaymentListResponse | null>(null);
  const [stripe, setStripe] = useState<StripeTransactionsResponse | null>(null);
  const [stripeLoading, setStripeLoading] = useState(true);
  const [stripeError, setStripeError] = useState<string | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [stripeDebug, setStripeDebug] = useState<any>(null);
  const [debugLoading, setDebugLoading] = useState(false);
  const [timeSeries, setTimeSeries] = useState<TimeSeriesPoint[]>([]);
  const [tsPeriod, setTsPeriod] = useState<"daily" | "monthly">("daily");
  const [bursarResult, setBursarResult] = useState<BursarResult | null>(null);
  const [importing, setImporting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const [listPage, setListPage] = useState(1);
  const [filterType, setFilterType] = useState("");
  const [filterMethod, setFilterMethod] = useState("");
  const [filterDateFrom, setFilterDateFrom] = useState<dayjs.Dayjs | null>(null);
  const [filterDateTo, setFilterDateTo] = useState<dayjs.Dayjs | null>(null);
  const [glFrom, setGlFrom] = useState<dayjs.Dayjs | null>(null);
  const [glTo, setGlTo] = useState<dayjs.Dayjs | null>(null);
  const [backfillRunning, setBackfillRunning] = useState(false);
  const [backfillResult, setBackfillResult] = useState<{ updated: number; already_set: number; skipped_no_email: number; errors: string[]; details: { id: string; email: string; source: string }[] } | null>(null);
  const [payBackfillRunning, setPayBackfillRunning] = useState(false);
  const [payBackfillResult, setPayBackfillResult] = useState<{ created: number; skipped_existing: number; errors: string[] } | null>(null);

  const loadReport = useCallback(async () => {
    try { const res = await fetch("/api/payments/revenue", { headers: await authHeaders() }); if (res.ok) setReport(await res.json()); }
    catch { /* ignore */ }
  }, []);

  const loadPayments = useCallback(async () => {
    try {
      const params = new URLSearchParams({ page: String(listPage), page_size: "15" });
      if (filterType) params.set("payment_type", filterType);
      if (filterMethod) params.set("method", filterMethod);
      if (filterDateFrom) params.set("date_from", filterDateFrom.format("YYYY-MM-DD"));
      if (filterDateTo) params.set("date_to", filterDateTo.format("YYYY-MM-DD"));
      const res = await fetch(`/api/payments/list?${params}`, { headers: await authHeaders() });
      if (res.ok) setPayments(await res.json());
    } catch { /* ignore */ }
  }, [listPage, filterType, filterMethod, filterDateFrom, filterDateTo]);

  const loadStripe = useCallback(async (refresh = false) => {
    setStripeLoading(true);
    setStripeError(null);
    try {
      const url = refresh
        ? "/api/payments/stripe-transactions?refresh=true"
        : "/api/payments/stripe-transactions";
      const res = await fetch(url, { headers: await authHeaders() });
      if (res.ok) {
        setStripe(await res.json());
      } else {
        const body = await res.text();
        let detail = `HTTP ${res.status}`;
        try { const j = JSON.parse(body); detail = j.detail || detail; } catch { if (body) detail += `: ${body.slice(0, 200)}`; }
        setStripeError(detail);
        setStripe(null);
      }
    } catch (err) {
      setStripeError(`Network error: ${err instanceof Error ? err.message : String(err)}`);
      setStripe(null);
    } finally { setStripeLoading(false); }
  }, []);

  const loadTimeSeries = useCallback(async () => {
    try {
      const res = await fetch(`/api/payments/revenue/timeseries?period=${tsPeriod}`, { headers: await authHeaders() });
      if (res.ok) { const json = await res.json(); setTimeSeries(json.data || []); }
    } catch { /* ignore */ }
  }, [tsPeriod]);

  async function runStripeDebug() {
    setDebugLoading(true);
    try {
      const res = await fetch("/api/payments/stripe-debug", { headers: await authHeaders() });
      setStripeDebug(await res.json());
    } catch (err) { setStripeDebug({ error: String(err) }); }
    finally { setDebugLoading(false); }
  }

  useEffect(() => { loadReport(); }, [loadReport]);
  useEffect(() => { loadPayments(); }, [loadPayments]);
  useEffect(() => { loadStripe(); }, [loadStripe]);
  useEffect(() => { loadTimeSeries(); }, [loadTimeSeries]);

  async function handleBackfillEmails() {
    setBackfillRunning(true);
    setBackfillResult(null);
    try {
      const res = await fetch("/api/payments/stripe-backfill-emails", { method: "POST", headers: await authHeaders() });
      if (res.ok) {
        const result = await res.json();
        setBackfillResult(result);
        if (result.updated > 0) {
          message.success(`Updated ${result.updated} PaymentIntent(s) with email addresses`);
          loadStripe();
        } else {
          message.info("No PaymentIntents needed updating");
        }
      } else {
        const body = await res.text();
        let detail = `HTTP ${res.status}`;
        try { const j = JSON.parse(body); detail = j.detail || detail; } catch { if (body) detail += `: ${body.slice(0, 200)}`; }
        message.error(detail);
      }
    } catch (err) {
      message.error(`Failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally { setBackfillRunning(false); }
  }

  async function handleBursarImport() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setImporting(true); setBursarResult(null);
    try {
      const formData = new FormData(); formData.append("file", file);
      const hdrs = await authHeaders(); delete hdrs["Content-Type"];
      const res = await fetch("/api/payments/bursar-import-csv", { method: "POST", headers: hdrs, body: formData });
      if (res.ok) { const result = await res.json(); setBursarResult(result); message.success(`${result.matched} payments matched`); loadReport(); loadPayments(); }
      else message.error("Import failed");
    } catch { message.error("Import failed"); } finally { setImporting(false); }
  }

  function handleGlExport() {
    if (!stripe?.transactions?.length) {
      message.warning("No Stripe data loaded to export");
      return;
    }
    // Filter by date range if set
    let txns = stripe.transactions;
    if (glFrom) {
      const from = glFrom.startOf("day").toISOString();
      txns = txns.filter(t => t.created >= from);
    }
    if (glTo) {
      const to = glTo.endOf("day").toISOString();
      txns = txns.filter(t => t.created <= to);
    }
    if (!txns.length) {
      message.warning("No transactions in the selected date range");
      return;
    }
    exportStripeGl(txns);
  }

  const citationRevenue = report?.by_payment_type?.ticket_payment;
  const permitRevenue = Object.entries(report?.by_payment_type || {})
    .filter(([k]) => k !== "ticket_payment" && k !== "unknown")
    .reduce((sum, [, v]) => sum + Number(v), 0);

  const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
    charge: { label: "Charge", color: "blue" },
    payment_intent: { label: "PaymentIntent", color: "purple" },
    checkout_session: { label: "Checkout", color: "cyan" },
  };

  function stripeDashboardUrl(t: StripeTransaction) {
    const base = `https://dashboard.stripe.com/${t.livemode ? "" : "test/"}`;
    if (t.source === "checkout_session") return `${base}checkout/sessions/${t.id}`;
    return `${base}payments/${t.id}`;
  }

  const stripeColumns: ColumnsType<StripeTransaction> = [
    {
      title: "Date", dataIndex: "created", key: "created", width: 160,
      render: d => new Date(d).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }),
    },
    {
      title: "Type", key: "type", width: 100,
      render: (_, t) => {
        const ptype = t.metadata?.type || "";
        const label = TYPE_LABELS[ptype];
        const color = TYPE_COLORS[ptype];
        return label ? <Tag color={color}>{label}</Tag> : <span className="text-xs text-ink-mute">{ptype || "—"}</span>;
      },
    },
    {
      title: "Status", dataIndex: "status", key: "status", width: 100,
      render: s => <Tag color={s === "succeeded" ? "green" : s === "failed" ? "red" : s === "pending" ? "gold" : s === "canceled" ? "default" : "default"}>{s}</Tag>,
    },
    {
      title: "Description", key: "desc", ellipsis: true,
      render: (_, t) => {
        const ptype = t.metadata?.type || "";
        const plate = t.metadata?.plate;
        const permitLabel = t.metadata?.permit_type_label;
        const ticketRef = t.metadata?.ticket_ref;
        if (ptype === "ticket_payment") {
          return <span>{ticketRef ? `Citation #${ticketRef}` : "Citation"}{plate ? <span className="text-ink-mute"> — {plate}</span> : ""}</span>;
        }
        if (ptype === "permit_purchase" || ptype === "standalone_permit_purchase" || ptype === "lottery_permit") {
          return <span>{permitLabel || "Permit"}{plate ? <span className="text-ink-mute"> — {plate}</span> : ""}</span>;
        }
        return t.description || "—";
      },
    },
    { title: "Customer", key: "customer", ellipsis: true, render: (_, t) => t.customer_name || t.customer_email || t.metadata?.student_name || t.metadata?.student_email || "—" },
    {
      title: "Plate", key: "plate", width: 100,
      render: (_, t) => t.metadata?.plate ? <span className="font-mono text-xs font-semibold">{t.metadata.plate}</span> : <span className="text-ink-mute">—</span>,
    },
    {
      title: "Amount", dataIndex: "amount", key: "amount", align: "right",
      render: v => <span className="font-mono font-medium">{fmtDollars(v)}</span>,
    },
    {
      title: <Tooltip title="Stripe charges 2.9% + $0.30 per successful card transaction"><span className="cursor-help border-b border-dotted border-gray-400">Fee</span></Tooltip>,
      dataIndex: "fee", key: "fee", align: "right", width: 80,
      render: (v: string, t: StripeTransaction) => {
        if (Number(v) <= 0) return "—";
        const gross = Number(t.amount);
        const pct = gross > 0 ? ((Number(v) / gross) * 100).toFixed(1) : "—";
        return (
          <Tooltip title={`${pct}% of ${fmtDollars(gross)} — Stripe's standard rate is 2.9% + $0.30 per transaction`}>
            <span className="text-ink-mute text-xs cursor-help">{fmtDollars(v)}</span>
          </Tooltip>
        );
      },
    },
    {
      title: "Net", dataIndex: "net", key: "net", align: "right", width: 100,
      render: v => Number(v) > 0 ? <span className="font-mono font-medium text-green-700">{fmtDollars(v)}</span> : "—",
    },
    {
      title: "Card", key: "card", width: 110,
      render: (_, t) => t.payment_method_last4
        ? <span className="text-xs">{(t.payment_method_brand || "").toUpperCase()} ···· {t.payment_method_last4}</span>
        : <span className="text-xs text-ink-mute">{t.payment_method_type || "—"}</span>,
    },
    {
      title: "", key: "actions", width: 100,
      render: (_, t) => (
        <Space size="small">
          {t.receipt_url && <a href={t.receipt_url} target="_blank" rel="noopener noreferrer" className="text-xs text-indigo-600">Receipt</a>}
          <a href={stripeDashboardUrl(t)} target="_blank" rel="noopener noreferrer" className="text-xs text-indigo-600">Stripe</a>
        </Space>
      ),
    },
  ];

  const paymentColumns: ColumnsType<PaymentListItem> = [
    {
      title: "Date", dataIndex: "paid_at", key: "paid_at", width: 160,
      render: d => new Date(d).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }),
    },
    {
      title: "Type", dataIndex: "payment_type", key: "payment_type",
      render: ptype => <Tag color={TYPE_COLORS[ptype] || "default"}>{TYPE_LABELS[ptype] || ptype || "—"}</Tag>,
    },
    { title: "Description", dataIndex: "description", key: "description", ellipsis: true, render: v => v || "—" },
    { title: "Payer", dataIndex: "payer_name", key: "payer_name", ellipsis: true, render: v => v || "—" },
    {
      title: "Amount", dataIndex: "amount", key: "amount", align: "right",
      render: v => <span className="font-mono font-medium">{fmtDollars(v)}</span>,
    },
    {
      title: "Method", dataIndex: "method", key: "method",
      render: m => <Tag color={m?.startsWith("online") ? "purple" : "gold"}>{METHOD_LABELS[m] || m}</Tag>,
    },
    {
      title: "Stripe", dataIndex: "stripe_payment_id", key: "stripe", width: 60,
      render: id => id ? <a href={`https://dashboard.stripe.com/payments/${id}`} target="_blank" rel="noopener noreferrer" className="text-indigo-600">View</a> : <span className="text-gray-300">—</span>,
    },
  ];

  const ov = stripe?.overview;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Finance & Reconciliation</h2>
        <Space>
          <Button onClick={() => downloadWithAuth("/api/payments/export/csv", "payments.csv")}>Export CSV</Button>
          <DatePicker placeholder="From" value={glFrom} onChange={setGlFrom} size="small" />
          <DatePicker placeholder="To" value={glTo} onChange={setGlTo} size="small" />
          <Button type="primary" onClick={handleGlExport} disabled={!stripe?.transactions?.length}>Export GL Journal</Button>
        </Space>
      </div>

      {/* Stripe Overview — always visible, pulled live from Stripe */}
      {stripeLoading ? (
        <div className="flex justify-center py-8"><Spin /></div>
      ) : ov ? (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 mb-6">
          <Card size="small"><Statistic title="Stripe Volume" value={fmtDollars(ov.total_volume)} valueStyle={{ color: "#15803d", fontWeight: 700, whiteSpace: "nowrap", fontSize: 18 }} /></Card>
          <Tooltip title="Stripe charges 2.9% + $0.30 per successful card transaction. These fees are deducted before funds reach your account."><Card size="small"><Statistic title="Stripe Fees" value={fmtDollars(ov.total_fees)} valueStyle={{ color: "#b91c1c", whiteSpace: "nowrap", fontSize: 18 }} /></Card></Tooltip>
          <Card size="small"><Statistic title="Net Revenue" value={fmtDollars(ov.total_net)} valueStyle={{ color: "#15803d", whiteSpace: "nowrap", fontSize: 18 }} /></Card>
          <Card size="small"><Statistic title="Refunded" value={fmtDollars(ov.total_refunded)} valueStyle={{ whiteSpace: "nowrap", fontSize: 18 }} /></Card>
          <Card size="small"><Statistic title="Successful" value={ov.successful_count} valueStyle={{ color: "#15803d" }} /></Card>
          <Card size="small"><Statistic title="Refunded" value={ov.refunded_count} /></Card>
          <Card size="small"><Statistic title="Failed" value={ov.failed_count} valueStyle={ov.failed_count > 0 ? { color: "#b91c1c" } : {}} /></Card>
        </div>
      ) : stripeError ? (
        <Alert type="error" message="Stripe API Error" description={stripeError} className="mb-6" showIcon />
      ) : (
        <Alert type="warning" message="Stripe not configured" description="Set STRIPE_SECRET_KEY to see live Stripe data." className="mb-6" showIcon />
      )}

      <Tabs defaultActiveKey="stripe" items={[
        {
          key: "stripe", label: `Stripe Transactions${stripe ? ` (${stripe.transactions.length})` : ""}`,
          children: (
            <div className="space-y-4">
              <Card>
                <div className="flex justify-between items-center mb-4">
                  <span className="text-sm text-ink-mute">Live data from Stripe API — no webhook dependency</span>
                  <Space>
                    <Button size="small" onClick={handleBackfillEmails} loading={backfillRunning}>Backfill Emails</Button>
                    <Button size="small" onClick={runStripeDebug} loading={debugLoading}>Diagnose Connection</Button>
                    <Button size="small" onClick={() => loadStripe(false)} loading={stripeLoading}>Refresh</Button>
                    <Button size="small" onClick={() => loadStripe(true)} loading={stripeLoading}>Full Sync</Button>
                  </Space>
                </div>
                {stripeDebug && (
                  <Alert type="info" className="mb-4" showIcon closable onClose={() => setStripeDebug(null)}
                    message="Stripe Diagnostic Results"
                    description={
                      <pre className="text-xs font-mono whitespace-pre-wrap mt-2 max-h-64 overflow-auto">{JSON.stringify(stripeDebug, null, 2)}</pre>
                    }
                  />
                )}
                {backfillResult && (
                  <Alert type={backfillResult.updated > 0 ? "success" : "info"} className="mb-4" showIcon closable onClose={() => setBackfillResult(null)}
                    message={`Email Backfill: ${backfillResult.updated} updated, ${backfillResult.already_set} already had email, ${backfillResult.skipped_no_email} no email found`}
                    description={backfillResult.details.length > 0 ? (
                      <div className="text-xs font-mono mt-2 max-h-48 overflow-auto">
                        {backfillResult.details.map(d => <div key={d.id}>{d.id} → {d.email} <span className="text-gray-400">({d.source})</span></div>)}
                        {backfillResult.errors.length > 0 && <div className="text-red-600 mt-2">{backfillResult.errors.join("\n")}</div>}
                      </div>
                    ) : backfillResult.errors.length > 0 ? (
                      <pre className="text-xs font-mono whitespace-pre-wrap mt-2 text-red-600">{backfillResult.errors.join("\n")}</pre>
                    ) : undefined}
                  />
                )}
                {stripe?.errors && stripe.errors.length > 0 && (
                  <Alert type="error" className="mb-4" showIcon
                    message={`${stripe.errors.length} error(s) processing Stripe data`}
                    description={
                      <pre className="text-xs font-mono whitespace-pre-wrap mt-2 max-h-64 overflow-auto">{stripe.errors.join("\n\n")}</pre>
                    }
                  />
                )}
                <Table dataSource={stripe?.transactions || []} columns={stripeColumns} rowKey="id" size="small"
                  pagination={{ defaultPageSize: 25, showSizeChanger: true, showTotal: t => `${t} transactions` }}
                  locale={{ emptyText: <Empty description="No Stripe transactions found" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                  expandable={{
                    expandedRowRender: t => {
                      const m = t.metadata || {};
                      const ptype = m.type || "";
                      const isCitation = ptype === "ticket_payment";
                      const isPermit = ptype === "permit_purchase" || ptype === "standalone_permit_purchase" || ptype === "lottery_permit";
                      const knownKeys = new Set(["type", "ticket_id", "ticket_ref", "plate", "violation_code", "violation_category",
                        "offense_number", "fine_amount", "lot", "zone", "issued_at", "officer_id", "payer_name",
                        "permit_type_id", "permit_type_code", "permit_type_label", "student_name", "student_email",
                        "email", "valid_days", "lot_assignments", "institution",
                        "revenue_category", "department", "gl_string", "gl_fund", "gl_org", "gl_account", "gl_activity"]);
                      const extraMeta = Object.entries(m).filter(([k]) => !knownKeys.has(k));
                      return (
                        <Descriptions size="small" column={3} bordered>
                          <Descriptions.Item label="Stripe ID"><span className="font-mono text-xs">{t.id}</span></Descriptions.Item>
                          <Descriptions.Item label="Source"><Tag color={SOURCE_LABELS[t.source]?.color || "default"}>{SOURCE_LABELS[t.source]?.label || t.source}</Tag></Descriptions.Item>
                          <Descriptions.Item label="Mode"><Tag color={t.livemode ? "green" : "orange"}>{t.livemode ? "Live" : "Test"}</Tag></Descriptions.Item>
                          <Descriptions.Item label="Email">{t.customer_email || m.email || m.student_email || "—"}</Descriptions.Item>
                          <Descriptions.Item label="Name">{t.customer_name || m.student_name || m.payer_name || "—"}</Descriptions.Item>
                          <Descriptions.Item label="Refunded">{Number(t.amount_refunded) > 0 ? fmtDollars(t.amount_refunded) : "None"}</Descriptions.Item>
                          {isCitation && (<>
                            <Descriptions.Item label="Citation #">{m.ticket_ref || m.ticket_id || "—"}</Descriptions.Item>
                            <Descriptions.Item label="Violation">{m.violation_code || "—"}{m.violation_category ? ` (${m.violation_category})` : ""}</Descriptions.Item>
                            <Descriptions.Item label="Offense #">{m.offense_number || "—"}</Descriptions.Item>
                            <Descriptions.Item label="Lot">{m.lot || "—"}</Descriptions.Item>
                            <Descriptions.Item label="Zone">{m.zone || "—"}</Descriptions.Item>
                            <Descriptions.Item label="Issued">{m.issued_at ? new Date(m.issued_at).toLocaleString() : "—"}</Descriptions.Item>
                          </>)}
                          {isPermit && (<>
                            <Descriptions.Item label="Permit Type">{m.permit_type_label || m.permit_type_code || "—"}</Descriptions.Item>
                            <Descriptions.Item label="Valid Days">{m.valid_days || "—"}</Descriptions.Item>
                            <Descriptions.Item label="Lots">{m.lot_assignments || "—"}</Descriptions.Item>
                          </>)}
                          {m.gl_string && (
                            <Descriptions.Item label="GL String" span={3}><span className="font-mono text-xs">{m.gl_string}</span></Descriptions.Item>
                          )}
                          {extraMeta.length > 0 && (
                            <Descriptions.Item label="Other Metadata" span={3}>
                              <div className="text-xs font-mono">{extraMeta.map(([k, v]) => <div key={k}><strong>{k}:</strong> {v}</div>)}</div>
                            </Descriptions.Item>
                          )}
                        </Descriptions>
                      );
                    },
                  }}
                />
              </Card>
            </div>
          ),
        },
        {
          key: "quarry", label: "Quarry Payments (DB)",
          children: (
            <Card>
              <Space className="mb-4" wrap>
                <Select value={filterType || undefined} onChange={v => { setFilterType(v || ""); setListPage(1); }}
                  placeholder="All Types" allowClear style={{ width: 140 }}
                  options={[
                    { label: "Citation", value: "ticket_payment" }, { label: "Permit", value: "permit_purchase" },
                    { label: "Standalone Permit", value: "standalone_permit_purchase" }, { label: "Lottery", value: "lottery_permit" },
                  ]} />
                <Select value={filterMethod || undefined} onChange={v => { setFilterMethod(v || ""); setListPage(1); }}
                  placeholder="All Methods" allowClear style={{ width: 130 }}
                  options={[{ label: "Stripe", value: "online_card" }, { label: "Bursar", value: "bursar" }]} />
                <DatePicker placeholder="From" value={filterDateFrom} onChange={v => { setFilterDateFrom(v); setListPage(1); }} />
                <DatePicker placeholder="To" value={filterDateTo} onChange={v => { setFilterDateTo(v); setListPage(1); }} />
                {(filterType || filterMethod || filterDateFrom || filterDateTo) && (
                  <Button type="link" danger size="small"
                    onClick={() => { setFilterType(""); setFilterMethod(""); setFilterDateFrom(null); setFilterDateTo(null); setListPage(1); }}>Clear filters</Button>
                )}
              </Space>
              <Table dataSource={payments?.items || []} columns={paymentColumns} rowKey="id" size="small"
                pagination={{ current: listPage, total: payments?.total || 0, pageSize: 15, onChange: setListPage, showSizeChanger: false, showTotal: t => `${t} payments` }}
                locale={{ emptyText: <Empty description="No payments found" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }} />
            </Card>
          ),
        },
        {
          key: "overview", label: "Revenue Overview",
          children: (
            <>
              {report && (
                <>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                    <Card size="small"><Statistic title="Total Fines Issued" value={Number(report.total_fines_issued)} prefix="$" precision={2} /></Card>
                    <Card size="small"><Statistic title="Total Collected" value={Number(report.total_collected)} prefix="$" precision={2} valueStyle={{ color: "#15803d" }} /></Card>
                    <Card size="small"><Statistic title="Outstanding" value={Number(report.total_outstanding)} prefix="$" precision={2} valueStyle={{ color: "#b91c1c" }} /></Card>
                    <Card size="small"><Statistic title="Collection Rate" value={report.collection_rate} suffix="%" precision={1} /></Card>
                  </div>
                  <div className="grid grid-cols-2 gap-4 mb-8">
                    <Card size="small"><Statistic title="Citation Revenue" value={Number(citationRevenue || 0)} prefix="$" precision={2} valueStyle={{ color: "#b91c1c" }} /></Card>
                    <Card size="small"><Statistic title="Permit Revenue" value={permitRevenue} prefix="$" precision={2} valueStyle={{ color: "#15803d" }} /></Card>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
                    <Card title="Revenue by Payment Method">
                      {(() => {
                        const txns = stripe?.transactions || [];
                        const byBrand: Record<string, number> = {};
                        for (const t of txns) {
                          if (t.status !== "succeeded") continue;
                          const brand = t.payment_method_type === "link" ? "Link"
                            : t.payment_method_type === "cashapp" ? "Cash App"
                            : t.payment_method_brand ? t.payment_method_brand.charAt(0).toUpperCase() + t.payment_method_brand.slice(1)
                            : t.payment_method_type || "Other";
                          byBrand[brand] = (byBrand[brand] || 0) + Number(t.amount);
                        }
                        const sorted = Object.entries(byBrand).sort((a, b) => b[1] - a[1]);
                        if (sorted.length === 0) return <Empty description="No Stripe data" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
                        return <div className="space-y-2">{sorted.map(([brand, amount]) => (
                          <div key={brand} className="flex justify-between items-center">
                            <span className="text-sm">{brand}</span>
                            <span className="font-mono text-sm font-medium">{fmtDollars(amount)}</span>
                          </div>
                        ))}</div>;
                      })()}
                    </Card>
                    <Card title="Tickets by Status">
                      {Object.entries(report.by_status).length === 0
                        ? <Empty description="No tickets yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                        : <div className="space-y-2">{Object.entries(report.by_status).map(([status, count]) => (
                            <div key={status} className="flex justify-between items-center">
                              <span className="capitalize text-sm">{status.replace("_", " ")}</span>
                              <span className="font-mono text-sm font-medium">{count}</span>
                            </div>
                          ))}</div>}
                    </Card>
                  </div>
                </>
              )}
              <Card title="Revenue Timeline" extra={
                <Segmented value={tsPeriod} onChange={v => setTsPeriod(v as "daily" | "monthly")}
                  options={[{ label: "Daily", value: "daily" }, { label: "Monthly", value: "monthly" }]} />
              }>
                {timeSeries.length === 0 ? <Empty description="No revenue data yet" className="py-8" /> : <RevenueChart data={timeSeries} />}
              </Card>
            </>
          ),
        },
        {
          key: "tools", label: "Import / Export",
          children: (
            <div className="space-y-6">
              <Card title="Oracle GL Journal Export">
                <p className="text-sm text-ink-mute mb-4">
                  Exports the live Stripe transactions as a balanced Oracle GL journal. Use the date pickers in the page header to filter by date range.
                </p>
                <Button type="primary" onClick={handleGlExport} disabled={!stripe?.transactions?.length}>Export GL Journal</Button>
              </Card>
              <Card title="Stripe Payment Backfill">
                <p className="text-sm text-ink-mute mb-4">Pull all succeeded PaymentIntents from Stripe into the local payments table. Skips any already imported.</p>
                <Button type="primary" loading={payBackfillRunning} onClick={async () => {
                  setPayBackfillRunning(true);
                  setPayBackfillResult(null);
                  try {
                    const res = await fetch("/api/payments/stripe-backfill-payments", { method: "POST", headers: await authHeaders() });
                    if (res.ok) { const r = await res.json(); setPayBackfillResult(r); message.success(`${r.created} payments imported`); loadReport(); loadPayments(); }
                    else message.error("Backfill failed");
                  } catch { message.error("Backfill failed"); } finally { setPayBackfillRunning(false); }
                }}>Backfill from Stripe</Button>
                {payBackfillResult && (
                  <Alert className="mt-4" type={payBackfillResult.errors.length > 0 ? "warning" : "success"} showIcon
                    message={`${payBackfillResult.created} created, ${payBackfillResult.skipped_existing} already existed`}
                    description={payBackfillResult.errors.length > 0 ? (
                      <ul className="list-disc pl-4 text-xs mt-1">{payBackfillResult.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
                    ) : undefined} />
                )}
              </Card>
              <Card title="Bursar Import">
                <p className="text-sm text-ink-mute mb-4">Upload a CSV with columns: <code>ticket_id</code>, <code>amount</code>, <code>reference</code>, <code>paid_date</code>.</p>
                <Space>
                  <input ref={fileRef} type="file" accept=".csv" />
                  <Button type="primary" onClick={handleBursarImport} loading={importing}>Import</Button>
                </Space>
                {bursarResult && (
                  <Alert className="mt-4" type={bursarResult.unmatched > 0 ? "warning" : "success"} showIcon
                    message={`${bursarResult.matched} payments matched${bursarResult.unmatched > 0 ? `, ${bursarResult.unmatched} unmatched` : ""}`}
                    description={bursarResult.errors.length > 0 ? (
                      <ul className="list-disc pl-4 text-xs mt-1">{bursarResult.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
                    ) : undefined} />
                )}
              </Card>
            </div>
          ),
        },
      ]} />
    </div>
  );
}

function RevenueChart({ data }: { data: TimeSeriesPoint[] }) {
  const maxTotal = Math.max(...data.map(d => Number(d.total)), 1);
  return (
    <div className="flex items-end gap-1 h-48 overflow-x-auto pb-6 relative">
      {data.map((point, i) => {
        const citations = Number(point.citations_amount);
        const permits = Number(point.permits_amount);
        const total = citations + permits;
        const pctCitations = total > 0 ? (citations / maxTotal) * 100 : 0;
        const pctPermits = total > 0 ? (permits / maxTotal) * 100 : 0;
        return (
          <div key={i} className="flex flex-col items-center flex-1 min-w-[28px] group relative">
            <div className="absolute bottom-full mb-2 hidden group-hover:block bg-brand-primary text-white text-xs rounded px-2 py-1 whitespace-nowrap z-10 pointer-events-none">
              <div>{point.date}</div>
              <div>Citations: ${citations.toFixed(2)}</div>
              <div>Permits: ${permits.toFixed(2)}</div>
              <div className="font-bold">Total: ${total.toFixed(2)}</div>
            </div>
            <div className="w-full flex flex-col justify-end" style={{ height: "100%" }}>
              <div className="bg-blue-400 rounded-t-sm w-full" style={{ height: `${pctPermits}%`, minHeight: permits > 0 ? 2 : 0 }} />
              <div className="bg-red-400 w-full" style={{ height: `${pctCitations}%`, minHeight: citations > 0 ? 2 : 0 }} />
            </div>
            <span className="text-[9px] text-ink-mute mt-1 rotate-[-45deg] origin-top-left absolute -bottom-5 left-1/2 whitespace-nowrap">
              {point.date.length > 7 ? point.date.slice(5) : point.date}
            </span>
          </div>
        );
      })}
      <div className="absolute top-0 right-0 flex gap-3 text-xs">
        <span className="flex items-center gap-1"><span className="w-3 h-3 bg-red-400 rounded-sm inline-block" /> Citations</span>
        <span className="flex items-center gap-1"><span className="w-3 h-3 bg-blue-400 rounded-sm inline-block" /> Permits</span>
      </div>
    </div>
  );
}
