import { useCallback, useEffect, useRef, useState } from "react";
import { authHeaders } from "../auth";

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

function typeBadge(ptype: string | null) {
  const label = TYPE_LABELS[ptype || ""] || ptype || "—";
  const bg =
    ptype === "ticket_payment"
      ? "bg-red-100 text-red-800"
      : ptype?.includes("permit")
        ? "bg-blue-100 text-blue-800"
        : ptype === "lottery_permit"
          ? "bg-purple-100 text-purple-800"
          : "bg-gray-100 text-gray-700";
  return <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${bg}`}>{label}</span>;
}

function methodBadge(method: string) {
  const label = METHOD_LABELS[method] || method;
  const bg = method.startsWith("online") ? "bg-indigo-100 text-indigo-800" : "bg-amber-100 text-amber-800";
  return <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${bg}`}>{label}</span>;
}

export default function Finance() {
  const [report, setReport] = useState<RevenueReport | null>(null);
  const [payments, setPayments] = useState<PaymentListResponse | null>(null);
  const [timeSeries, setTimeSeries] = useState<TimeSeriesPoint[]>([]);
  const [tsPeriod, setTsPeriod] = useState<"daily" | "monthly">("daily");
  const [bursarResult, setBursarResult] = useState<BursarResult | null>(null);
  const [importing, setImporting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Payment list filters
  const [listPage, setListPage] = useState(1);
  const [filterType, setFilterType] = useState("");
  const [filterMethod, setFilterMethod] = useState("");
  const [filterDateFrom, setFilterDateFrom] = useState("");
  const [filterDateTo, setFilterDateTo] = useState("");

  // GL export date range
  const [glFrom, setGlFrom] = useState("");
  const [glTo, setGlTo] = useState("");

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
      if (filterDateFrom) params.set("date_from", filterDateFrom);
      if (filterDateTo) params.set("date_to", filterDateTo);

      const res = await fetch(`/api/payments/list?${params}`, { headers: await authHeaders() });
      if (res.ok) setPayments(await res.json());
    } catch { /* ignore */ }
  }, [listPage, filterType, filterMethod, filterDateFrom, filterDateTo]);

  const loadTimeSeries = useCallback(async () => {
    try {
      const params = new URLSearchParams({ period: tsPeriod });
      const res = await fetch(`/api/payments/revenue/timeseries?${params}`, { headers: await authHeaders() });
      if (res.ok) {
        const json = await res.json();
        setTimeSeries(json.data || []);
      }
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
      const res = await fetch("/api/payments/bursar-import-csv", {
        method: "POST",
        headers: hdrs,
        body: formData,
      });
      if (res.ok) {
        const result = await res.json();
        setBursarResult(result);
        loadReport();
        loadPayments();
      }
    } finally {
      setImporting(false);
    }
  }

  function handleGlExport() {
    const params = new URLSearchParams();
    if (glFrom) params.set("since", glFrom);
    if (glTo) params.set("until", glTo);
    const qs = params.toString() ? `?${params}` : "";
    downloadWithAuth(`/api/payments/export/oracle-gl${qs}`, "gl-journal.csv");
  }

  const fmtDollars = (val: string | number) =>
    `$${Number(val).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;

  const citationRevenue = report?.by_payment_type?.ticket_payment;
  const permitRevenue = Object.entries(report?.by_payment_type || {})
    .filter(([k]) => k !== "ticket_payment" && k !== "unknown")
    .reduce((sum, [, v]) => sum + Number(v), 0);

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Finance & Reconciliation</h2>
        <div className="flex gap-3">
          <button
            onClick={() => downloadWithAuth("/api/payments/export/csv", "payments.csv")}
            className="px-4 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">
            Export CSV
          </button>
          <button
            onClick={handleGlExport}
            className="px-4 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">
            Export GL Journal
          </button>
        </div>
      </div>

      {report && (
        <>
          {/* Primary Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <StatCard label="Total Fines Issued" value={fmtDollars(report.total_fines_issued)} />
            <StatCard label="Total Collected" value={fmtDollars(report.total_collected)} color="green" />
            <StatCard label="Outstanding" value={fmtDollars(report.total_outstanding)} color="red" />
            <StatCard label="Collection Rate" value={`${report.collection_rate.toFixed(1)}%`} />
          </div>

          {/* Revenue by Category */}
          <div className="grid grid-cols-2 md:grid-cols-2 gap-4 mb-8">
            <StatCard
              label="Citation Revenue"
              value={citationRevenue ? fmtDollars(citationRevenue) : "$0.00"}
              color="red"
            />
            <StatCard
              label="Permit Revenue"
              value={fmtDollars(permitRevenue)}
              color="green"
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
            <div className="bg-white rounded-xl shadow p-5">
              <h3 className="font-semibold mb-3">Revenue by Payment Method</h3>
              {Object.entries(report.by_method).length === 0 ? (
                <p className="text-sm text-ink-mute">No payments recorded yet.</p>
              ) : (
                <div className="space-y-2">
                  {Object.entries(report.by_method).map(([method, amount]) => (
                    <div key={method} className="flex justify-between items-center">
                      <span className="capitalize text-sm">{method.replace("_", " ")}</span>
                      <span className="font-mono text-sm font-medium">{fmtDollars(amount)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="bg-white rounded-xl shadow p-5">
              <h3 className="font-semibold mb-3">Tickets by Status</h3>
              {Object.entries(report.by_status).length === 0 ? (
                <p className="text-sm text-ink-mute">No tickets recorded yet.</p>
              ) : (
                <div className="space-y-2">
                  {Object.entries(report.by_status).map(([status, count]) => (
                    <div key={status} className="flex justify-between items-center">
                      <span className="capitalize text-sm">{status.replace("_", " ")}</span>
                      <span className="font-mono text-sm font-medium">{count}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* Revenue Timeline Chart */}
      <div className="bg-white rounded-xl shadow p-6 mb-8">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold">Revenue Timeline</h3>
          <div className="flex gap-2">
            <button
              onClick={() => setTsPeriod("daily")}
              className={`px-3 py-1 rounded text-sm ${tsPeriod === "daily" ? "bg-navy text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"}`}>
              Daily
            </button>
            <button
              onClick={() => setTsPeriod("monthly")}
              className={`px-3 py-1 rounded text-sm ${tsPeriod === "monthly" ? "bg-navy text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200"}`}>
              Monthly
            </button>
          </div>
        </div>

        {timeSeries.length === 0 ? (
          <p className="text-sm text-ink-mute py-8 text-center">No revenue data yet.</p>
        ) : (
          <RevenueChart data={timeSeries} />
        )}
      </div>

      {/* Recent Payments */}
      <div className="bg-white rounded-xl shadow p-6 mb-8">
        <h3 className="font-semibold mb-4">Recent Payments</h3>

        {/* Filters */}
        <div className="flex flex-wrap gap-3 mb-4 items-end">
          <div>
            <label className="block text-xs text-ink-mute mb-1">Type</label>
            <select
              value={filterType}
              onChange={(e) => { setFilterType(e.target.value); setListPage(1); }}
              className="border border-gray-300 rounded px-2 py-1.5 text-sm">
              <option value="">All Types</option>
              <option value="ticket_payment">Citation</option>
              <option value="permit_purchase">Permit</option>
              <option value="standalone_permit_purchase">Standalone Permit</option>
              <option value="lottery_permit">Lottery</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-ink-mute mb-1">Method</label>
            <select
              value={filterMethod}
              onChange={(e) => { setFilterMethod(e.target.value); setListPage(1); }}
              className="border border-gray-300 rounded px-2 py-1.5 text-sm">
              <option value="">All Methods</option>
              <option value="online_card">Stripe</option>
              <option value="bursar">Bursar</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-ink-mute mb-1">From</label>
            <input
              type="date"
              value={filterDateFrom}
              onChange={(e) => { setFilterDateFrom(e.target.value); setListPage(1); }}
              className="border border-gray-300 rounded px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-ink-mute mb-1">To</label>
            <input
              type="date"
              value={filterDateTo}
              onChange={(e) => { setFilterDateTo(e.target.value); setListPage(1); }}
              className="border border-gray-300 rounded px-2 py-1.5 text-sm"
            />
          </div>
          {(filterType || filterMethod || filterDateFrom || filterDateTo) && (
            <button
              onClick={() => { setFilterType(""); setFilterMethod(""); setFilterDateFrom(""); setFilterDateTo(""); setListPage(1); }}
              className="text-xs text-ink-mute underline hover:text-navy self-end pb-1.5">
              Clear filters
            </button>
          )}
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-ink-mute">
                <th className="py-2 pr-3">Date</th>
                <th className="py-2 pr-3">Type</th>
                <th className="py-2 pr-3">Description</th>
                <th className="py-2 pr-3">Payer</th>
                <th className="py-2 pr-3 text-right">Amount</th>
                <th className="py-2 pr-3">Method</th>
                <th className="py-2">Stripe</th>
              </tr>
            </thead>
            <tbody>
              {(!payments || payments.items.length === 0) ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-ink-mute text-sm">
                    No payments found.
                  </td>
                </tr>
              ) : (
                payments.items.map((p) => (
                  <tr key={p.id} className="border-b border-gray-100 hover:bg-bone/50">
                    <td className="py-2.5 pr-3 whitespace-nowrap text-xs">
                      {new Date(p.paid_at).toLocaleString("en-US", {
                        month: "short", day: "numeric", year: "numeric",
                        hour: "numeric", minute: "2-digit",
                      })}
                    </td>
                    <td className="py-2.5 pr-3">{typeBadge(p.payment_type)}</td>
                    <td className="py-2.5 pr-3 max-w-[200px] truncate" title={p.description || ""}>
                      {p.description || "—"}
                    </td>
                    <td className="py-2.5 pr-3 max-w-[140px] truncate" title={p.payer_name || ""}>
                      {p.payer_name || "—"}
                    </td>
                    <td className="py-2.5 pr-3 text-right font-mono font-medium">
                      {fmtDollars(p.amount)}
                    </td>
                    <td className="py-2.5 pr-3">{methodBadge(p.method)}</td>
                    <td className="py-2.5">
                      {p.stripe_payment_id ? (
                        <a
                          href={`https://dashboard.stripe.com/payments/${p.stripe_payment_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-indigo-600 hover:text-indigo-800"
                          title="View in Stripe Dashboard">
                          <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 inline" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                          </svg>
                        </a>
                      ) : (
                        <span className="text-gray-300">—</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {payments && payments.pages > 1 && (
          <div className="flex items-center justify-between mt-4 pt-3 border-t">
            <span className="text-xs text-ink-mute">
              {payments.total} payment{payments.total !== 1 ? "s" : ""} — Page {payments.page} of {payments.pages}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => setListPage((p) => Math.max(1, p - 1))}
                disabled={listPage <= 1}
                className="px-3 py-1 rounded border text-sm disabled:opacity-30 hover:bg-gray-50">
                Prev
              </button>
              <button
                onClick={() => setListPage((p) => Math.min(payments.pages, p + 1))}
                disabled={listPage >= payments.pages}
                className="px-3 py-1 rounded border text-sm disabled:opacity-30 hover:bg-gray-50">
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {/* GL Export with Date Range */}
      <div className="bg-white rounded-xl shadow p-6 mb-8">
        <h3 className="font-semibold mb-3">Oracle GL Journal Export</h3>
        <p className="text-sm text-ink-mute mb-4">
          Export payments in Oracle General Ledger journal format. Optionally filter by date range.
        </p>
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="block text-xs text-ink-mute mb-1">From</label>
            <input
              type="date"
              value={glFrom}
              onChange={(e) => setGlFrom(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-ink-mute mb-1">To</label>
            <input
              type="date"
              value={glTo}
              onChange={(e) => setGlTo(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1.5 text-sm"
            />
          </div>
          <button
            onClick={handleGlExport}
            className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep">
            Export GL Journal
          </button>
        </div>
      </div>

      {/* Bursar Import */}
      <div className="bg-white rounded-xl shadow p-6">
        <h3 className="font-semibold mb-3">Bursar Import</h3>
        <p className="text-sm text-ink-mute mb-4">
          Upload a CSV with columns: <code>ticket_id</code> (or <code>plate</code>),
          <code>amount</code>, <code>reference</code>, <code>paid_date</code>.
          Unmatched records will be flagged for manual review.
        </p>
        <div className="flex gap-3 items-center">
          <input ref={fileRef} type="file" accept=".csv" />
          <button onClick={handleBursarImport} disabled={importing}
            className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep disabled:opacity-50">
            {importing ? "Importing..." : "Import"}
          </button>
        </div>

        {bursarResult && (
          <div className="mt-4 p-4 bg-bone rounded-lg text-sm">
            <p><strong>{bursarResult.matched}</strong> payments matched and applied</p>
            {bursarResult.unmatched > 0 && (
              <p className="text-signal-red"><strong>{bursarResult.unmatched}</strong> records unmatched</p>
            )}
            {bursarResult.errors.length > 0 && (
              <ul className="mt-2 text-xs text-ink-mute list-disc pl-4">
                {bursarResult.errors.map((err, i) => <li key={i}>{err}</li>)}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  const textColor = color === "green" ? "text-green-700" : color === "red" ? "text-red-700" : "text-navy";
  return (
    <div className="bg-white rounded-xl shadow p-4">
      <div className={`text-2xl font-bold ${textColor}`}>{value}</div>
      <div className="text-xs text-ink-mute mt-1">{label}</div>
    </div>
  );
}

function RevenueChart({ data }: { data: TimeSeriesPoint[] }) {
  const maxTotal = Math.max(...data.map((d) => Number(d.total)), 1);

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
            {/* Tooltip */}
            <div className="absolute bottom-full mb-2 hidden group-hover:block bg-navy text-white text-xs rounded px-2 py-1 whitespace-nowrap z-10 pointer-events-none">
              <div>{point.date}</div>
              <div>Citations: ${citations.toFixed(2)}</div>
              <div>Permits: ${permits.toFixed(2)}</div>
              <div className="font-bold">Total: ${total.toFixed(2)}</div>
            </div>
            <div className="w-full flex flex-col justify-end" style={{ height: "100%" }}>
              <div
                className="bg-blue-400 rounded-t-sm w-full transition-all"
                style={{ height: `${pctPermits}%`, minHeight: permits > 0 ? 2 : 0 }}
              />
              <div
                className="bg-red-400 w-full transition-all"
                style={{ height: `${pctCitations}%`, minHeight: citations > 0 ? 2 : 0 }}
              />
            </div>
            <span className="text-[9px] text-ink-mute mt-1 rotate-[-45deg] origin-top-left absolute -bottom-5 left-1/2 whitespace-nowrap">
              {point.date.length > 7 ? point.date.slice(5) : point.date}
            </span>
          </div>
        );
      })}
      {/* Legend */}
      <div className="absolute top-0 right-0 flex gap-3 text-xs">
        <span className="flex items-center gap-1"><span className="w-3 h-3 bg-red-400 rounded-sm inline-block" /> Citations</span>
        <span className="flex items-center gap-1"><span className="w-3 h-3 bg-blue-400 rounded-sm inline-block" /> Permits</span>
      </div>
    </div>
  );
}
