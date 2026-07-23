import { APIProvider, Map, useMap, useMapsLibrary } from "@vis.gl/react-google-maps";
import { useEffect, useRef, useState } from "react";
import type { Lot } from "../api";

const DEFAULT_CENTER = { lat: 40.6265, lng: -75.3707 };
const DEFAULT_ZOOM = 17;

const CAMPUS_VIEWS: Record<string, { center: { lat: number; lng: number }; zoom: number }> = {
  north: { center: { lat: 40.6265, lng: -75.3707 }, zoom: 17 },
  south: { center: { lat: 40.6195, lng: -75.3755 }, zoom: 17 },
};
const HIGHLIGHT_FILL = "#FFD700";
const HIGHLIGHT_STROKE = "#FFFFFF";

interface StudentLotMapProps {
  apiKey: string;
  lots: Lot[];
  highlightedLots: string[];
  defaultCenter?: { lat: number; lng: number };
}

/**
 * Normalize a lot name for comparison: strip "Lot " prefix, lowercase, trim.
 * Handles mismatches between lot_assignments (e.g. "A") and lot.name (e.g. "Lot A").
 */
function normalizeLotName(name: string): string {
  return name.replace(/^lot\s+/i, "").trim().toLowerCase();
}

function isLotHighlighted(lotName: string, highlightedLots: string[]): boolean {
  const normalized = normalizeLotName(lotName);
  return highlightedLots.some((hl) => normalizeLotName(hl) === normalized);
}

/** Create an HTML element for a text-only map label */
function createLabelElement(
  text: string,
  color: string,
  fontSize: string,
  opacity: number,
): HTMLDivElement {
  const el = document.createElement("div");
  el.className = "lot-map-label";
  el.style.color = color;
  el.style.fontSize = fontSize;
  el.style.fontWeight = "bold";
  el.style.whiteSpace = "nowrap";
  el.style.textShadow = "0 1px 3px rgba(0,0,0,0.8)";
  el.style.opacity = String(opacity);
  el.textContent = text;
  return el;
}

function CampusToggle({ onSelect }: { onSelect: (campus: string) => void }) {
  const [active, setActive] = useState<string | null>(null);
  return (
    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 flex bg-[#1a2744]/90 backdrop-blur rounded-lg shadow-lg overflow-hidden text-xs font-medium">
      {[{ key: "north", label: "North Campus" }, { key: "south", label: "South Campus" }].map(c => (
        <button
          key={c.key}
          onClick={() => { setActive(c.key); onSelect(c.key); }}
          className={`px-4 py-2 transition-colors ${active === c.key ? "bg-white/20 text-white" : "text-white/60 hover:text-white hover:bg-white/10"}`}
        >
          {c.label}
        </button>
      ))}
    </div>
  );
}

function MapContent({
  lots,
  highlightedLots,
  defaultCenter,
}: Omit<StudentLotMapProps, "apiKey">) {
  const map = useMap();
  const markerLib = useMapsLibrary("marker");
  const polygonsRef = useRef<google.maps.Polygon[]>([]);
  const markersRef = useRef<google.maps.marker.AdvancedMarkerElement[]>([]);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const initialFitDoneRef = useRef(false);

  // Fit to all lots once on initial load
  useEffect(() => {
    if (!map || initialFitDoneRef.current) return;
    const lotsWithBounds = lots.filter((l) => l.boundary.length >= 3);
    if (lotsWithBounds.length === 0) return;

    initialFitDoneRef.current = true;
    const allBounds = new google.maps.LatLngBounds();
    lotsWithBounds.forEach((lot) => {
      lot.boundary.forEach((c) => allBounds.extend({ lat: c.latitude, lng: c.longitude }));
    });
    setTimeout(() => map.fitBounds(allBounds, 40), 150);
  }, [map, lots]);

  // Recreate polygons + labels with correct styles when highlight changes
  useEffect(() => {
    if (!map || !markerLib) return;

    polygonsRef.current.forEach((p) => p.setMap(null));
    polygonsRef.current = [];
    markersRef.current.forEach((m) => { m.map = null; });
    markersRef.current = [];

    const hasHighlight = highlightedLots.length > 0;

    lots.forEach((lot) => {
      if (lot.boundary.length < 3) return;

      const isHighlighted = hasHighlight && isLotHighlighted(lot.name, highlightedLots);

      const poly = new google.maps.Polygon({
        paths: lot.boundary.map((c) => ({ lat: c.latitude, lng: c.longitude })),
        strokeColor: !hasHighlight ? "#D1D5DB" : isHighlighted ? HIGHLIGHT_STROKE : "#6B7280",
        strokeOpacity: !hasHighlight ? 1 : isHighlighted ? 1 : 0.3,
        strokeWeight: !hasHighlight ? 2 : isHighlighted ? 4 : 1,
        fillColor: !hasHighlight ? "#9CA3AF" : isHighlighted ? HIGHLIGHT_FILL : "#374151",
        fillOpacity: !hasHighlight ? 0.25 : isHighlighted ? 0.7 : 0.1,
        zIndex: isHighlighted ? 10 : 1,
        map,
        clickable: true,
      });

      poly.addListener("mouseover", () => {
        if (tooltipRef.current) {
          tooltipRef.current.innerHTML = `<strong>${lot.name}</strong>`;
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
        if (tooltipRef.current) tooltipRef.current.style.display = "none";
      });

      polygonsRef.current.push(poly);

      // Label
      const bounds = new google.maps.LatLngBounds();
      lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));

      const showLabel = !hasHighlight || isHighlighted;
      const label = new markerLib.AdvancedMarkerElement({
        position: bounds.getCenter(),
        map,
        content: createLabelElement(
          lot.name,
          isHighlighted ? HIGHLIGHT_FILL : "white",
          isHighlighted ? "14px" : "11px",
          showLabel ? 1 : 0.25,
        ),
      });
      markersRef.current.push(label);
    });

    // Zoom to highlighted lots on hover
    if (hasHighlight) {
      const highlighted = lots.filter(
        (l) => l.boundary.length >= 3 && isLotHighlighted(l.name, highlightedLots),
      );
      if (highlighted.length > 0) {
        const bounds = new google.maps.LatLngBounds();
        highlighted.forEach((lot) => {
          lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));
        });
        map.fitBounds(bounds, 60);
      }
    }

    return () => {
      polygonsRef.current.forEach((p) => p.setMap(null));
      markersRef.current.forEach((m) => { m.map = null; });
    };
  }, [map, markerLib, lots, highlightedLots]);

  function handleCampusSelect(campus: string) {
    if (!map) return;
    const view = CAMPUS_VIEWS[campus];
    if (!view) return;
    map.panTo(view.center);
    map.setZoom(view.zoom);
  }

  return (
    <>
      <Map
        defaultCenter={defaultCenter ?? DEFAULT_CENTER}
        defaultZoom={DEFAULT_ZOOM}
        mapId="DEMO_MAP_ID"
        mapTypeId="satellite"
        gestureHandling="cooperative"
        disableDefaultUI
        zoomControl
        style={{ width: "100%", height: "100%" }}
      />
      <div
        ref={tooltipRef}
        style={{ display: "none" }}
        className="absolute z-20 pointer-events-none px-2 py-1 rounded bg-[#1a2744]/90 text-white text-xs font-medium whitespace-nowrap shadow"
      />
      {highlightedLots.length > 0 && (
        <div className="absolute top-3 left-3 z-10 bg-[#1a2744]/90 backdrop-blur rounded-lg px-3 py-2 text-white text-xs font-medium shadow-lg">
          Showing: {highlightedLots.map((n) => `Lot ${n}`).join(", ")}
        </div>
      )}
      <CampusToggle onSelect={handleCampusSelect} />
    </>
  );
}

export default function StudentLotMap(props: StudentLotMapProps) {
  if (!props.apiKey) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-gray-100 rounded-xl">
        <p className="text-gray-400 text-sm">Map unavailable</p>
      </div>
    );
  }

  return (
    <APIProvider apiKey={props.apiKey}>
      <div className="w-full h-full relative rounded-xl overflow-hidden">
        <MapContent
          lots={props.lots}
          highlightedLots={props.highlightedLots}
          defaultCenter={props.defaultCenter}
        />
      </div>
    </APIProvider>
  );
}
