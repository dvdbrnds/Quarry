import { useCallback, useEffect, useRef, useState } from "react";

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

const STATUS_COLORS: Record<string, string> = {
  issued: "bg-signal-red/15 text-red-700",
  pending_payment: "bg-orange-100 text-orange-700",
  paid: "bg-signal-green/15 text-green-700",
  appealed: "bg-yellow-100 text-yellow-700",
  escalated: "bg-purple-100 text-purple-700",
  voided: "bg-gray-100 text-gray-500",
};

export default function Dashboard() {
  const [pipeline, setPipeline] = useState<Pipeline | null>(null);
  const [recentEvents, setRecentEvents] = useState<WSEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  const loadPipeline = useCallback(async () => {
    try {
      const res = await fetch("/api/tickets/pipeline");
      if (res.ok) setPipeline(await res.json());
    } catch {}
  }, []);

  useEffect(() => {
    loadPipeline();
    const interval = setInterval(loadPipeline, 30000);
    return () => clearInterval(interval);
  }, [loadPipeline]);

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/ws`);
    wsRef.current = ws;

    ws.onmessage = (e) => {
      try {
        const event: WSEvent = JSON.parse(e.data);
        setRecentEvents((prev) => [event, ...prev].slice(0, 50));
        loadPipeline();
      } catch {}
    };

    ws.onerror = () => {};
    ws.onclose = () => {
      setTimeout(() => {
        const newWs = new WebSocket(`${proto}//${window.location.host}/ws`);
        wsRef.current = newWs;
      }, 3000);
    };

    return () => ws.close();
  }, [loadPipeline]);

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

      <div className="bg-white rounded-xl shadow overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100">
          <h3 className="font-semibold">Live Activity</h3>
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
    </div>
  );
}
