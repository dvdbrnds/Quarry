import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

interface PlaylistSlide {
  type: "image" | "html" | "iframe";
  url: string;
  duration: number;
}

interface AlertOverride {
  id: string;
  category: string;
  subject: string;
  body_text: string;
  sent_at: string;
}

const CATEGORY_COLORS: Record<string, string> = {
  emergency: "#dc2626",
  weather: "#0284c7",
  campus_closing: "#d97706",
  parking: "#4f46e5",
  general: "#4b5563",
};

export default function SignagePlayer() {
  const { screenId } = useParams<{ screenId: string }>();
  const [playlist, setPlaylist] = useState<PlaylistSlide[]>([]);
  const [currentSlide, setCurrentSlide] = useState(0);
  const [alert, setAlert] = useState<AlertOverride | null>(null);
  const [connected, setConnected] = useState(false);
  const retryRef = useRef(1);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!screenId) return;

    let es: EventSource | null = null;
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      es = new EventSource(`/api/signage/player/${screenId}`);

      es.onopen = () => {
        setConnected(true);
        retryRef.current = 1;
      };

      es.addEventListener("playlist", (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.playlist) {
            setPlaylist(data.playlist);
            setCurrentSlide(0);
          }
        } catch {}
      });

      es.addEventListener("alert_override", (e) => {
        try {
          setAlert(JSON.parse(e.data));
        } catch {}
      });

      es.addEventListener("alert_clear", () => {
        setAlert(null);
      });

      es.onerror = () => {
        setConnected(false);
        es?.close();
        const delay = Math.min(30000, 1000 * retryRef.current);
        retryRef.current = Math.min(retryRef.current * 2, 30);
        setTimeout(connect, delay);
      };
    }

    connect();

    const heartbeat = setInterval(() => {
      fetch(`/api/signage/heartbeat/${screenId}`, { method: "POST" }).catch(() => {});
    }, 30_000);

    return () => {
      cancelled = true;
      es?.close();
      clearInterval(heartbeat);
    };
  }, [screenId]);

  useEffect(() => {
    if (alert || playlist.length === 0) {
      if (timerRef.current) clearTimeout(timerRef.current);
      return;
    }

    const slide = playlist[currentSlide];
    const duration = (slide?.duration ?? 10) * 1000;

    timerRef.current = window.setTimeout(() => {
      setCurrentSlide((prev) => (prev + 1) % playlist.length);
    }, duration);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [currentSlide, playlist, alert]);

  if (alert) {
    const bg = CATEGORY_COLORS[alert.category] ?? CATEGORY_COLORS.general;
    return (
      <div
        className="fixed inset-0 flex flex-col items-center justify-center text-white p-12"
        style={{ backgroundColor: bg, animation: alert.category === "emergency" ? "pulse 2s infinite" : undefined }}
      >
        <style>{`
          @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.85; }
          }
        `}</style>
        <p className="text-2xl font-bold uppercase tracking-widest mb-4 opacity-80">
          {alert.category.replace("_", " ")} Alert
        </p>
        <h1 className="text-5xl md:text-7xl font-black text-center mb-8 leading-tight">
          {alert.subject}
        </h1>
        {alert.body_text && (
          <p className="text-xl md:text-2xl text-center max-w-4xl leading-relaxed opacity-90 whitespace-pre-wrap">
            {alert.body_text}
          </p>
        )}
        <p className="absolute bottom-8 text-sm opacity-60">
          {new Date(alert.sent_at).toLocaleString()}
        </p>
      </div>
    );
  }

  if (playlist.length === 0) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-gray-900 text-white">
        <div className="text-center">
          <p className="text-lg opacity-60">
            {connected ? "No playlist content configured" : "Connecting..."}
          </p>
          <div className={`w-3 h-3 rounded-full mt-4 mx-auto ${connected ? "bg-green-500" : "bg-red-500 animate-pulse"}`} />
        </div>
      </div>
    );
  }

  const slide = playlist[currentSlide];

  return (
    <div className="fixed inset-0 bg-black">
      {slide.type === "image" && (
        <img
          src={slide.url}
          alt=""
          className="w-full h-full object-cover"
        />
      )}
      {slide.type === "html" && (
        <div
          className="w-full h-full flex items-center justify-center bg-white text-black p-12"
          dangerouslySetInnerHTML={{ __html: slide.url }}
        />
      )}
      {slide.type === "iframe" && (
        <iframe
          src={slide.url}
          className="w-full h-full border-0"
          title="Signage content"
          sandbox="allow-scripts allow-same-origin"
        />
      )}
    </div>
  );
}
