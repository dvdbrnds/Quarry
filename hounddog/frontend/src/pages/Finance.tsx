import { useCallback, useEffect, useRef, useState } from "react";
import { authHeaders } from "../auth";

interface RevenueReport {
  total_fines_issued: string;
  total_collected: string;
  total_outstanding: string;
  collection_rate: number;
  by_method: Record<string, string>;
  by_status: Record<string, number>;
}

interface BursarResult {
  matched: number;
  unmatched: number;
  errors: string[];
}

export default function Finance() {
  const [report, setReport] = useState<RevenueReport | null>(null);
  const [bursarResult, setBursarResult] = useState<BursarResult | null>(null);
  const [importing, setImporting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadReport = useCallback(async () => {
    try {
      const res = await fetch("/api/payments/revenue", { headers: await authHeaders() });
      if (res.ok) setReport(await res.json());
    } catch {}
  }, []);

  useEffect(() => { loadReport(); }, [loadReport]);

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
      }
    } finally {
      setImporting(false);
    }
  }

  const fmtDollars = (val: string) => `$${Number(val).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Finance & Reconciliation</h2>
        <div className="flex gap-3">
          <a href="/api/payments/export/csv" target="_blank"
            className="px-4 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">
            Export CSV
          </a>
        </div>
      </div>

      {report && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <StatCard label="Total Fines Issued" value={fmtDollars(report.total_fines_issued)} />
            <StatCard label="Total Collected" value={fmtDollars(report.total_collected)} color="green" />
            <StatCard label="Outstanding" value={fmtDollars(report.total_outstanding)} color="red" />
            <StatCard label="Collection Rate" value={`${report.collection_rate.toFixed(1)}%`} />
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
