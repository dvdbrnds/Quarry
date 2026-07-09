import { useCallback, useEffect, useRef, useState } from "react";
import { authHeaders } from "../auth";
import {
  Card, Statistic, Table, Tag, Select, Button, Space, Segmented, DatePicker, Alert, App, Empty,
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
  total_fines_issued: string;
  total_collected: string;
  total_outstanding: string;
  collection_rate: number;
  by_method: Record<string, string>;
  by_status: Record<string, number>;
  by_payment_type: Record<string, string>;
}

interface PaymentListItem {
  id: string;
  ticket_id: string | null;
  amount: string;
  method: string;
  stripe_payment_id: string | null;
  payment_type: string | null;
  payer_name: string | null;
  payer_email: string | null;
  description: string | null;
  plate: string | null;
  paid_at: string;
}

interface PaymentListResponse {
  items: PaymentListItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

interface TimeSeriesPoint {
  date: string;
  citations_amount: string;
  permits_amount: string;
  total: string;
}

interface BursarResult {
  matched: number;
  unmatched: number;
  errors: string[];
}

const TYPE_COLORS: Record<string, string> = {
  ticket_payment: "red",
  permit_purchase: "blue",
  standalone_permit_purchase: "blue",
  lottery_permit: "purple",
};

const TYPE_LABELS: Record<string, string> = {
  ticket_payment: "Citation",
  permit_purchase: "Permit",
  standalone_permit_purchase: "Permit",
  lottery_permit: "Lottery",
};

const METHOD_LABELS: Record<string, string> = {
  online_card: "Stripe",
  online_permit_purchase: "Stripe",
  bursar: "Bursar",
};

export default function Finance() {
  const { message } = App.useApp();
  const [report, setReport] = useState<RevenueReport | null>(null);
  const [payments, setPayments] = useState<PaymentListResponse | null>(null);
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

  const loadReport = useCallback(async () => {
    try {
      const res = await fetch("/api/payments/revenue", { headers: await authHeaders() });
      if (res.ok) setReport(await res.json());
    } catch { /* ignore */ }
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

  const loadTimeSeries = useCallback(async () => {
    try {
      const res = await fetch(`/api/payments/revenue/timeseries?period=${tsPeriod}`, { headers: await authHeaders() });
      if (res.ok) { const json = await res.json(); setTimeSeries(json.data || []); }
    } catch { /* ignore */ }
  }, [tsPeriod]);

  useEffect(() => { loadReport(); }, [loadReport]);
  useEffect(() => { loadPayments(); }, [loadPayments]);
  useEffect(() => { loadTimeSeries(); }, [loadTimeSeries]);

  async function handleBursarImport() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setImporting(true);
    setBursarResult(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const hdrs = await authHeaders();
      delete hdrs["Content-Type"];
      const res = await fetch("/api/payments/bursar-import-csv", { method: "POST", headers: hdrs, body: formData });
      if (res.ok) {
        const result = await res.json();
        setBursarResult(result);
        message.success(`${result.matched} payments matched`);
        loadReport(); loadPayments();
      } else {
        message.error("Import failed");
      }
    } catch { message.error("Import failed"); } finally { setImporting(false); }
  }

  function handleGlExport() {
    const params = new URLSearchParams();
    if (glFrom) params.set("since", glFrom.format("YYYY-MM-DD"));
    if (glTo) params.set("until", glTo.format("YYYY-MM-DD"));
    const qs = params.toString() ? `?${params}` : "";
    downloadWithAuth(`/api/payments/export/oracle-gl${qs}`, "gl-journal.csv");
  }

  const fmtDollars = (val: string | number) => `$${Number(val).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;

  const citationRevenue = report?.by_payment_type?.ticket_payment;
  const permitRevenue = Object.entries(report?.by_payment_type || {})
    .filter(([k]) => k !== "ticket_payment" && k !== "unknown")
    .reduce((sum, [, v]) => sum + Number(v), 0);

  const paymentColumns: ColumnsType<PaymentListItem> = [
    {
      title: "Date", dataIndex: "paid_at", key: "paid_at", width: 160,
      render: (d) => new Date(d).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }),
    },
    {
      title: "Type", dataIndex: "payment_type", key: "payment_type",
      render: (ptype) => <Tag color={TYPE_COLORS[ptype] || "default"}>{TYPE_LABELS[ptype] || ptype || "—"}</Tag>,
    },
    { title: "Description", dataIndex: "description", key: "description", ellipsis: true, render: (v) => v || "—" },
    { title: "Payer", dataIndex: "payer_name", key: "payer_name", ellipsis: true, render: (v) => v || "—" },
    {
      title: "Amount", dataIndex: "amount", key: "amount", align: "right",
      render: (v) => <span className="font-mono font-medium">{fmtDollars(v)}</span>,
    },
    {
      title: "Method", dataIndex: "method", key: "method",
      render: (m) => <Tag color={m?.startsWith("online") ? "purple" : "gold"}>{METHOD_LABELS[m] || m}</Tag>,
    },
    {
      title: "Stripe", dataIndex: "stripe_payment_id", key: "stripe", width: 60,
      render: (id) => id ? (
        <a href={`https://dashboard.stripe.com/payments/${id}`} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:text-indigo-800">View</a>
      ) : <span className="text-gray-300">—</span>,
    },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Finance & Reconciliation</h2>
        <Space>
          <Button onClick={() => downloadWithAuth("/api/payments/export/csv", "payments.csv")}>Export CSV</Button>
          <Button onClick={handleGlExport}>Export GL Journal</Button>
        </Space>
      </div>

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
              {Object.entries(report.by_method).length === 0
                ? <Empty description="No payments yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                : <div className="space-y-2">{Object.entries(report.by_method).map(([method, amount]) => (
                    <div key={method} className="flex justify-between items-center">
                      <span className="capitalize text-sm">{method.replace("_", " ")}</span>
                      <span className="font-mono text-sm font-medium">{fmtDollars(amount)}</span>
                    </div>
                  ))}</div>}
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
      } className="mb-8">
        {timeSeries.length === 0
          ? <Empty description="No revenue data yet" className="py-8" />
          : <RevenueChart data={timeSeries} />}
      </Card>

      <Card title="Recent Payments" className="mb-8">
        <Space className="mb-4" wrap>
          <Select value={filterType || undefined} onChange={v => { setFilterType(v || ""); setListPage(1); }}
            placeholder="All Types" allowClear style={{ width: 140 }}
            options={[
              { label: "Citation", value: "ticket_payment" },
              { label: "Permit", value: "permit_purchase" },
              { label: "Standalone Permit", value: "standalone_permit_purchase" },
              { label: "Lottery", value: "lottery_permit" },
            ]}
          />
          <Select value={filterMethod || undefined} onChange={v => { setFilterMethod(v || ""); setListPage(1); }}
            placeholder="All Methods" allowClear style={{ width: 130 }}
            options={[{ label: "Stripe", value: "online_card" }, { label: "Bursar", value: "bursar" }]}
          />
          <DatePicker placeholder="From" value={filterDateFrom} onChange={v => { setFilterDateFrom(v); setListPage(1); }} />
          <DatePicker placeholder="To" value={filterDateTo} onChange={v => { setFilterDateTo(v); setListPage(1); }} />
          {(filterType || filterMethod || filterDateFrom || filterDateTo) && (
            <Button type="link" danger size="small"
              onClick={() => { setFilterType(""); setFilterMethod(""); setFilterDateFrom(null); setFilterDateTo(null); setListPage(1); }}>
              Clear filters
            </Button>
          )}
        </Space>

        <Table dataSource={payments?.items || []} columns={paymentColumns} rowKey="id" size="small"
          pagination={{
            current: listPage, total: payments?.total || 0, pageSize: 15, onChange: setListPage,
            showSizeChanger: false, showTotal: t => `${t} payments`,
          }}
          locale={{ emptyText: <Empty description="No payments found" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
        />
      </Card>

      <Card title="Oracle GL Journal Export" className="mb-8">
        <p className="text-sm text-ink-mute mb-4">Export payments in Oracle General Ledger journal format. Optionally filter by date range.</p>
        <Space>
          <DatePicker placeholder="From" value={glFrom} onChange={setGlFrom} />
          <DatePicker placeholder="To" value={glTo} onChange={setGlTo} />
          <Button type="primary" onClick={handleGlExport}>Export GL Journal</Button>
        </Space>
      </Card>

      <Card title="Bursar Import">
        <p className="text-sm text-ink-mute mb-4">
          Upload a CSV with columns: <code>ticket_id</code>, <code>amount</code>, <code>reference</code>, <code>paid_date</code>.
        </p>
        <Space>
          <input ref={fileRef} type="file" accept=".csv" />
          <Button type="primary" onClick={handleBursarImport} loading={importing}>Import</Button>
        </Space>
        {bursarResult && (
          <Alert className="mt-4" type={bursarResult.unmatched > 0 ? "warning" : "success"} showIcon
            message={`${bursarResult.matched} payments matched${bursarResult.unmatched > 0 ? `, ${bursarResult.unmatched} unmatched` : ""}`}
            description={bursarResult.errors.length > 0 ? (
              <ul className="list-disc pl-4 text-xs mt-1">{bursarResult.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
            ) : undefined}
          />
        )}
      </Card>
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
            <div className="absolute bottom-full mb-2 hidden group-hover:block bg-navy text-white text-xs rounded px-2 py-1 whitespace-nowrap z-10 pointer-events-none">
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
