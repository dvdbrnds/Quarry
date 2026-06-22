import { useCallback, useEffect, useRef, useState } from "react";
import { authHeaders, getAccessToken } from "../auth";

interface Pipeline {
  issued: number;
  pending_payment: number;
  paid: number;
  appealed: number;
  escalated: number;
  voided: number;
  total: number;
}

interface WSEvent {
  type: string;
  data: {
    id: string;
    plate: string;
    lot?: string;
    status: string;
    violation_type?: string;
  };
  timestamp: string;
}

interface AuditEntry {
  id: string;
  timestamp: string;
  user_email: string;
  action: string;
  resource_type: string;
  summary: string;
  response_status: number;
}

const STATUS_COLORS: Record<string, string> = {
  issued: "bg-signal-red/15 text-red-700",
  pending_payment: "bg-orange-100 text-orange-700",
  paid: "bg-signal-green/15 text-green-700",
  appealed: "bg-yellow-100 text-yellow-700",
  escalated: "bg-purple-100 text-purple-700",
  voided: "bg-gray-100 text-gray-500",
};

const ACTION_COLORS: Record<string, string> = {
  GET: "bg-gray-100 text-gray-600",
  POST: "bg-signal-green/10 text-green-700",
  PUT: "bg-blue-50 text-blue-700",
  PATCH: "bg-amber-50 text-amber-700",
  DELETE: "bg-signal-red/10 text-red-700",
  LOGIN: "bg-blue-100 text-blue-800",
  LOGOUT: "bg-orange-100 text-orange-800",
};

export default function Dashboard() {
  const [pipeline, setPipeline] = useState<Pipeline | null>(null);
  const [recentEvents, setRecentEvents] = useState<WSEvent[]>([]);
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([]);
  const [auditError, setAuditError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const loadPipeline = useCallback(async () => {
    try {
      const res = await fetch("/api/tickets/pipeline", { headers: await authHeaders() });
      if (res.ok) setPipeline(await res.json());
    } catch {}
  }, []);

  const loadRecentAudit = useCallback(async () => {
    try {
      const headers = await authHeaders();
      const res = await fetch("/api/audit?page_size=25", { headers });
      if (res.ok) {
        const data = await res.json();
        setAuditEntries(data.items || []);
        setAuditError(null);
      } else {
        const text = await res.text();
        setAuditError(`API ${res.status}: ${text.slice(0, 200)}`);
      }
    } catch (e: any) {
      setAuditError(`Fetch error: ${e?.message || e}`);
    }
  }, []);

  useEffect(() => {
    loadPipeline();
    loadRecentAudit();
    const interval = setInterval(loadPipeline, 30000);
    return () => clearInterval(interval);
  }, [loadPipeline, loadRecentAudit]);

  useEffect(() => {
    let cancelled = false;

    const connect = async () => {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const token = await getAccessToken();
      const url = token
        ? `${proto}//${window.location.host}/ws?token=${encodeURIComponent(token)}`
        : `${proto}//${window.location.host}/ws`;

      if (cancelled) return;

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onmessage = (e) => {
        try {
          const event: WSEvent = JSON.parse(e.data);
          setRecentEvents((prev) => [event, ...prev].slice(0, 50));
          loadPipeline();
          loadRecentAudit();
        } catch {}
      };

      ws.onerror = () => {};
      ws.onclose = () => {
        if (!cancelled) {
          setTimeout(() => connect(), 3000);
        }
      };
    };

    connect();

    return () => {
      cancelled = true;
      wsRef.current?.close();
    };
  }, [loadPipeline, loadRecentAudit]);

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Enforcement Dashboard</h2>

      {pipeline && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4 mb-8">
          {Object.entries(pipeline).map(([key, value]) => (
            <div key={key} className="bg-white rounded-xl shadow p-4 text-center">
              <div className="text-2xl font-bold text-navy">{value}</div>
              <div className="text-xs text-ink-mute mt-1 capitalize">
                {key.replace("_", " ")}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Live ticket events */}
        <div className="bg-white rounded-xl shadow overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h3 className="font-semibold">Live Ticket Events</h3>
            <p className="text-xs text-ink-mute">Real-time ticket events via WebSocket</p>
          </div>
          <div className="divide-y divide-gray-50 max-h-[500px] overflow-y-auto">
            {recentEvents.length === 0 && (
              <div className="px-5 py-8 text-center text-ink-mute text-sm">
                Waiting for events... Ticket actions will appear here in real time.
              </div>
            )}
            {recentEvents.map((event, i) => (
              <div key={`${event.data.id}-${i}`} className="px-5 py-3 flex items-center gap-4">
                <div className={`w-2 h-2 rounded-full ${
                  event.type === "ticket_created" ? "bg-signal-red" : "bg-brass"
                }`} />
                <div className="flex-1 min-w-0">
                  <span className="font-mono text-sm font-medium">{event.data.plate}</span>
                  {event.data.lot && (
                    <span className="text-xs text-ink-mute ml-2">{event.data.lot}</span>
                  )}
                </div>
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  STATUS_COLORS[event.data.status] || "bg-gray-100"
                }`}>
                  {event.data.status}
                </span>
                <span className="text-xs text-ink-mute">
                  {event.type === "ticket_created" ? "Created" : "Updated"}
                </span>
                <span className="text-xs text-ink-mute">
                  {new Date(event.timestamp).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Audit trail */}
        <div className="bg-white rounded-xl shadow overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h3 className="font-semibold">Audit Trail</h3>
            <p className="text-xs text-ink-mute">Recent system activity (persistent log)</p>
          </div>
          <div className="divide-y divide-gray-50 max-h-[500px] overflow-y-auto">
            {auditError && (
              <div className="px-5 py-3 bg-red-50 text-red-700 text-xs font-mono break-all">
                {auditError}
              </div>
            )}
            {!auditError && auditEntries.length === 0 && (
              <div className="px-5 py-8 text-center text-ink-mute text-sm">
                No audit entries recorded yet.
              </div>
            )}
            {auditEntries.map((entry) => (
              <div key={entry.id} className="px-5 py-3 flex items-center gap-3">
                <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 ${
                  ACTION_COLORS[entry.action] || "bg-gray-100"
                }`}>
                  {entry.action}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm truncate">{entry.summary}</div>
                  <div className="text-xs text-ink-mute truncate">{entry.user_email}</div>
                </div>
                <span className={`text-xs font-mono shrink-0 ${
                  entry.response_status < 300 ? "text-green-600" :
                  entry.response_status < 500 ? "text-amber-600" : "text-red-600"
                }`}>
                  {entry.response_status}
                </span>
                <span className="text-xs text-ink-mute shrink-0 whitespace-nowrap">
                  {new Date(entry.timestamp).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
