import { useEffect, useRef, useState } from "react";
import { APIProvider, Map, useMap, useMapsLibrary } from "@vis.gl/react-google-maps";
import { Modal, Spin } from "antd";
import { loadConfig, initAuth, isAuthenticated, login } from "../auth";
import type { AppConfig } from "../auth";
import PublicPageNav from "../components/PublicPageNav";
import PublicFooter from "../components/PublicFooter";

interface PublicLot {
  id: string;
  name: string;
  boundary: { latitude: number; longitude: number }[];
  total_spaces: number;
  handicap_spaces: number;
  designation_code: string;
  designation_label: string;
  lot_type: string;
  external_url: string | null;
  external_provider: string | null;
  is_closed: boolean;
  campus: string | null;
}

const DEFAULT_CENTER = { lat: 40.6265, lng: -75.3707 };

const COLOR_OPEN = "#22C55E";
const COLOR_CLOSED = "#EF4444";
const COLOR_STREET = "#3B82F6";
const COLOR_EXTERNAL = "#F59E0B";

function getLotColor(lot: PublicLot): string {
  if (lot.is_closed) return COLOR_CLOSED;
  if (lot.lot_type === "external") return COLOR_EXTERNAL;
  if (lot.lot_type === "street") return COLOR_STREET;
  return COLOR_OPEN;
}

function MapContent({
  lots,
  center,
  onLotClick,
}: {
  lots: PublicLot[];
  center: { lat: number; lng: number };
  onLotClick: (lot: PublicLot) => void;
}) {
  const map = useMap();
  const markerLib = useMapsLibrary("marker");
  const polygonsRef = useRef<google.maps.Polygon[]>([]);
  const labelsRef = useRef<google.maps.marker.AdvancedMarkerElement[]>([]);
  const tooltipRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!map || !markerLib) return;

    polygonsRef.current.forEach((p) => p.setMap(null));
    polygonsRef.current = [];
    labelsRef.current.forEach((m) => { m.map = null; });
    labelsRef.current = [];

    lots.forEach((lot) => {
      if (lot.boundary.length < 3) return;

      const fill = getLotColor(lot);

      const poly = new google.maps.Polygon({
        paths: lot.boundary.map((c) => ({ lat: c.latitude, lng: c.longitude })),
        strokeColor: fill,
        strokeOpacity: 1,
        strokeWeight: 2,
        fillColor: fill,
        fillOpacity: 0.35,
        map,
        clickable: true,
      });

      poly.addListener("click", () => onLotClick(lot));

      poly.addListener("mouseover", () => {
        poly.setOptions({ fillOpacity: 0.55, strokeWeight: 3 });
        if (tooltipRef.current) {
          const typeLabel = lot.lot_type === "external" ? " (External)" : "";
          const closed = lot.is_closed ? ' · <span style="color:#EF4444">CLOSED</span>' : "";
          tooltipRef.current.innerHTML = `<strong>${lot.name}</strong>${typeLabel}${closed}`;
          tooltipRef.current.style.display = "block";
        }
      });
      poly.addListener("mousemove", (e: google.maps.MapMouseEvent) => {
        if (tooltipRef.current && e.domEvent instanceof MouseEvent) {
          tooltipRef.current.style.left = `${e.domEvent.offsetX + 12}px`;
          tooltipRef.current.style.top = `${e.domEvent.offsetY + 12}px`;
        }
      });
      poly.addListener("mouseout", () => {
        poly.setOptions({ fillOpacity: 0.35, strokeWeight: 2 });
        if (tooltipRef.current) tooltipRef.current.style.display = "none";
      });

      polygonsRef.current.push(poly);

      const bounds = new google.maps.LatLngBounds();
      lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));

      const labelEl = document.createElement("div");
      labelEl.className = "lot-map-label";
      labelEl.style.color = "white";
      labelEl.style.fontSize = "11px";
      labelEl.style.fontWeight = "bold";
      labelEl.style.whiteSpace = "nowrap";
      labelEl.style.textShadow = "0 1px 3px rgba(0,0,0,0.8)";
      labelEl.textContent = lot.name;

      const label = new markerLib.AdvancedMarkerElement({
        position: bounds.getCenter(),
        map,
        content: labelEl,
      });
      labelsRef.current.push(label);
    });

    // Fit to all lots
    const lotsWithBounds = lots.filter((l) => l.boundary.length >= 3);
    if (lotsWithBounds.length > 0) {
      const allBounds = new google.maps.LatLngBounds();
      lotsWithBounds.forEach((lot) => {
        lot.boundary.forEach((c) => allBounds.extend({ lat: c.latitude, lng: c.longitude }));
      });
      setTimeout(() => map.fitBounds(allBounds, 50), 100);
    }

    return () => {
      polygonsRef.current.forEach((p) => p.setMap(null));
      labelsRef.current.forEach((m) => { m.map = null; });
    };
  }, [map, markerLib, lots, onLotClick]);

  return (
    <>
      <Map
        defaultCenter={center}
        defaultZoom={16}
        mapId="DEMO_MAP_ID"
        mapTypeId="satellite"
        gestureHandling="greedy"
        disableDefaultUI={false}
        mapTypeControl
        streetViewControl={false}
        fullscreenControl
        zoomControl
        style={{ width: "100%", height: "100%" }}
      />
      <div
        ref={tooltipRef}
        style={{ display: "none" }}
        className="absolute z-20 pointer-events-none px-2 py-1 rounded bg-gray-900/90 text-white text-xs font-medium whitespace-nowrap shadow"
      />
    </>
  );
}

function Legend() {
  const items = [
    { color: COLOR_OPEN, label: "Open" },
    { color: COLOR_CLOSED, label: "Closed" },
    { color: COLOR_STREET, label: "Street Parking" },
    { color: COLOR_EXTERNAL, label: "External (Third-Party)" },
  ];

  return (
    <div className="absolute bottom-4 left-4 z-10 bg-white/95 backdrop-blur rounded-lg shadow-lg px-4 py-3">
      <p className="text-xs font-bold text-gray-700 mb-2 uppercase tracking-wide">Legend</p>
      <div className="space-y-1.5">
        {items.map((item) => (
          <div key={item.label} className="flex items-center gap-2">
            <div className="w-4 h-3 rounded-sm" style={{ backgroundColor: item.color, opacity: 0.8 }} />
            <span className="text-xs text-gray-600">{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ParkingMap() {
  const [lots, setLots] = useState<PublicLot[]>([]);
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [selectedLot, setSelectedLot] = useState<PublicLot | null>(null);
  const [externalLot, setExternalLot] = useState<PublicLot | null>(null);

  useEffect(() => {
    (async () => {
      const cfg = await loadConfig();
      setConfig(cfg);

      if (cfg.public_map_requires_auth) {
        await initAuth();
        const authed = await isAuthenticated();
        if (!authed) {
          login();
          return;
        }
      }
      setAuthChecked(true);

      try {
        const res = await fetch("/api/parking-map");
        if (res.ok) setLots(await res.json());
      } catch { /* silent */ }
      setLoading(false);
    })();
  }, []);

  function handleLotClick(lot: PublicLot) {
    if (lot.lot_type === "external") {
      setExternalLot(lot);
    } else {
      setSelectedLot(lot);
    }
  }

  if (!authChecked && config?.public_map_requires_auth) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Spin size="large" />
      </div>
    );
  }

  const schoolName = config?.school_name || "the university";

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      <PublicPageNav subtitle="Parking Map" />

      <div className="flex-1 relative">
        {loading ? (
          <div className="flex items-center justify-center h-full min-h-[60vh]">
            <Spin size="large" />
          </div>
        ) : config?.google_maps_api_key ? (
          <APIProvider apiKey={config.google_maps_api_key}>
            <div className="w-full h-[calc(100vh-64px)] relative">
              <MapContent
                lots={lots}
                center={{ lat: config.campus_lat, lng: config.campus_lng }}
                onLotClick={handleLotClick}
              />
              <Legend />
            </div>
          </APIProvider>
        ) : (
          <div className="flex items-center justify-center h-full min-h-[60vh]">
            <p className="text-gray-400">Map unavailable. Please try again later.</p>
          </div>
        )}
      </div>

      {/* Internal lot info popup */}
      <Modal
        open={!!selectedLot}
        title={selectedLot?.name}
        onCancel={() => setSelectedLot(null)}
        footer={null}
        centered
      >
        {selectedLot && (
          <div className="space-y-3">
            {selectedLot.is_closed && (
              <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-red-700 text-sm font-medium">
                This lot is currently closed.
              </div>
            )}
            <div className="grid grid-cols-2 gap-3 text-sm">
              {selectedLot.designation_label && (
                <div>
                  <span className="text-gray-500 block text-xs">Designation</span>
                  <span className="font-medium">{selectedLot.designation_label}</span>
                </div>
              )}
              {selectedLot.handicap_spaces > 0 && (
                <div>
                  <span className="text-gray-500 block text-xs">Accessible Spaces</span>
                  <span className="font-medium">{selectedLot.handicap_spaces}</span>
                </div>
              )}
              {selectedLot.campus && (
                <div>
                  <span className="text-gray-500 block text-xs">Campus</span>
                  <span className="font-medium capitalize">{selectedLot.campus}</span>
                </div>
              )}
            </div>
            {selectedLot.lot_type === "lot" && (
              <div className="pt-2 border-t border-gray-100">
                <a
                  href="/parking"
                  className="text-sm font-medium text-blue-600 hover:text-blue-800"
                >
                  Purchase a Parking Permit &rarr;
                </a>
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* External lot disclaimer modal */}
      <Modal
        open={!!externalLot}
        title={`You are leaving ${schoolName} Parking`}
        onCancel={() => setExternalLot(null)}
        centered
        okText={`Continue to ${externalLot?.external_provider || "external site"}`}
        cancelText="Cancel"
        onOk={() => {
          if (externalLot?.external_url) {
            window.open(externalLot.external_url, "_blank", "noopener,noreferrer");
          }
          setExternalLot(null);
        }}
        okButtonProps={{ type: "primary", danger: false }}
      >
        {externalLot && (
          <div className="space-y-4">
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
              <p className="text-amber-800 text-sm font-medium mb-1">External Parking Facility</p>
              <p className="text-amber-700 text-sm">
                <strong>{externalLot.name}</strong> is operated by{" "}
                <strong>{externalLot.external_provider || "a third party"}</strong>.
              </p>
            </div>
            <p className="text-gray-600 text-sm">
              {schoolName} is not responsible for permits, enforcement, or policies at this location.
              You will be redirected to their website to purchase a permit or view availability.
            </p>
            <p className="text-gray-500 text-xs">
              A new tab will open at:{" "}
              <span className="font-mono text-xs break-all">{externalLot.external_url}</span>
            </p>
          </div>
        )}
      </Modal>
      <PublicFooter />
    </div>
  );
}
