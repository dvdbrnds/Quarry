import { APIProvider, Map, useMap, useMapsLibrary } from "@vis.gl/react-google-maps";
import { useEffect, useRef } from "react";
import type { Lot } from "../api";

const DEFAULT_CENTER = { lat: 40.6265, lng: -75.3707 };
const DEFAULT_ZOOM = 17;
const HIGHLIGHT_FILL = "#FFD700";
const HIGHLIGHT_STROKE = "#FFFFFF";
const FOCUS_FILL = "#FF6B00";
const FOCUS_STROKE = "#FFFFFF";

export interface MapLegendItem {
  label: string;
  color: string;
}

interface StudentLotMapProps {
  apiKey: string;
  lots: Lot[];
  highlightedLots: string[];
  focusedLot?: string | null;
  defaultCenter?: { lat: number; lng: number };
  /** Optional per-lot fill colors (keyed by lot name or assignment code). Enables multi-tier color coding. */
  lotColors?: Record<string, string>;
  /** Optional legend chips shown instead of the "Showing: Lot …" list */
  legend?: MapLegendItem[];
  /** Called when a lot polygon is clicked */
  onLotClick?: (lot: Lot) => void;
}

/**
 * Normalize a lot name for comparison: strip "Lot " prefix, periods, lowercase, trim.
 * Handles mismatches between lot_assignments (e.g. "Lehigh St") and lot.name (e.g. "Lehigh St.").
 */
function normalizeLotName(name: string): string {
  return name
    .replace(/^lot\s+/i, "")
    .replace(/\./g, "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

function isLotHighlighted(lotName: string, highlightedLots: string[]): boolean {
  const normalized = normalizeLotName(lotName);
  return highlightedLots.some((hl) => normalizeLotName(hl) === normalized);
}

function lookupLotColor(
  lotName: string,
  lotColors?: Record<string, string>,
): string | null {
  if (!lotColors) return null;
  const key = normalizeLotName(lotName);
  for (const [name, color] of Object.entries(lotColors)) {
    if (normalizeLotName(name) === key) return color;
  }
  return null;
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

/** fitBounds, then pull back 2 zoom levels when only one small lot is in view */
function fitMapToLots(
  map: google.maps.Map,
  bounds: google.maps.LatLngBounds,
  padding: number,
  lotCount: number,
) {
  map.fitBounds(bounds, padding);
  if (lotCount !== 1) return;
  google.maps.event.addListenerOnce(map, "idle", () => {
    const z = map.getZoom();
    if (z == null) return;
    map.setZoom(Math.max(z - 2, 15));
  });
}

function MapContent({
  lots,
  highlightedLots,
  focusedLot,
  defaultCenter,
  lotColors,
  legend,
  onLotClick,
}: Omit<StudentLotMapProps, "apiKey">) {
  const map = useMap();
  const markerLib = useMapsLibrary("marker");
  const polygonsRef = useRef<google.maps.Polygon[]>([]);
  const markersRef = useRef<google.maps.marker.AdvancedMarkerElement[]>([]);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const initialFitDoneRef = useRef(false);
  const colorMode = Boolean(lotColors && Object.keys(lotColors).length > 0);

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
    setTimeout(() => fitMapToLots(map, allBounds, 40, lotsWithBounds.length), 150);
  }, [map, lots]);

  // Recreate polygons + labels with correct styles when highlight changes
  useEffect(() => {
    if (!map || !markerLib) return;

    polygonsRef.current.forEach((p) => p.setMap(null));
    polygonsRef.current = [];
    markersRef.current.forEach((m) => { m.map = null; });
    markersRef.current = [];

    const hasEmphasize = highlightedLots.length > 0;

    lots.forEach((lot) => {
      if (lot.boundary.length < 3) return;

      const tierColor = lookupLotColor(lot.name, lotColors);
      const isEmphasized = hasEmphasize && isLotHighlighted(lot.name, highlightedLots);
      const isFocused = !!focusedLot && normalizeLotName(lot.name) === normalizeLotName(focusedLot);
      const isColored = Boolean(tierColor);

      let strokeColor: string;
      let strokeOpacity: number;
      let strokeWeight: number;
      let fillColor: string;
      let fillOpacity: number;
      let zIndex: number;
      let labelColor: string;
      let labelSize: string;
      let labelOpacity: number;

      if (colorMode && isColored && tierColor) {
        // Multi-tier color coding: keep all tier lots visible in their colors
        if (isFocused) {
          fillColor = tierColor;
          fillOpacity = 0.9;
          strokeColor = FOCUS_STROKE;
          strokeOpacity = 1;
          strokeWeight = 5;
          zIndex = 30;
          labelColor = tierColor;
          labelSize = "16px";
          labelOpacity = 1;
        } else if (!hasEmphasize || isEmphasized) {
          fillColor = tierColor;
          fillOpacity = hasEmphasize && isEmphasized ? 0.75 : 0.5;
          strokeColor = "#FFFFFF";
          strokeOpacity = 1;
          strokeWeight = hasEmphasize && isEmphasized ? 4 : 3;
          zIndex = hasEmphasize && isEmphasized ? 20 : 10;
          labelColor = tierColor;
          labelSize = hasEmphasize && isEmphasized ? "14px" : "12px";
          labelOpacity = 1;
        } else {
          // Other tiers while hovering one — keep color but mute
          fillColor = tierColor;
          fillOpacity = 0.18;
          strokeColor = tierColor;
          strokeOpacity = 0.45;
          strokeWeight = 2;
          zIndex = 2;
          labelColor = tierColor;
          labelSize = "11px";
          labelOpacity = 0.45;
        }
      } else {
        // Legacy single-highlight mode (live /parking)
        const isHighlighted = hasEmphasize && isLotHighlighted(lot.name, highlightedLots);
        strokeColor = !hasEmphasize ? "#D1D5DB" : isFocused ? FOCUS_STROKE : isHighlighted ? HIGHLIGHT_STROKE : "#6B7280";
        strokeOpacity = !hasEmphasize ? 1 : (isFocused || isHighlighted) ? 1 : 0.3;
        strokeWeight = !hasEmphasize ? 2 : isFocused ? 5 : isHighlighted ? 4 : 1;
        fillColor = !hasEmphasize ? "#9CA3AF" : isFocused ? FOCUS_FILL : isHighlighted ? HIGHLIGHT_FILL : "#374151";
        fillOpacity = !hasEmphasize ? 0.25 : isFocused ? 0.85 : isHighlighted ? 0.55 : 0.1;
        zIndex = isFocused ? 20 : isHighlighted ? 10 : 1;
        labelColor = isFocused ? FOCUS_FILL : isHighlighted ? HIGHLIGHT_FILL : "white";
        labelSize = isFocused ? "16px" : isHighlighted ? "14px" : "11px";
        labelOpacity = !hasEmphasize || isHighlighted || isFocused ? 1 : 0.25;
      }

      const poly = new google.maps.Polygon({
        paths: lot.boundary.map((c) => ({ lat: c.latitude, lng: c.longitude })),
        strokeColor,
        strokeOpacity,
        strokeWeight,
        fillColor,
        fillOpacity,
        zIndex,
        map,
        clickable: true,
      });

      poly.addListener("click", () => onLotClick?.(lot));

      poly.addListener("mouseover", () => {
        if (tooltipRef.current) {
          const accessNote =
            lot.lot_type === "external"
              ? `Third-party · ${lot.external_provider || "External"}`
              : lot.lot_type === "street"
                ? "Street parking"
                : lot.designation_code === "FS" || lot.designation_code === "FSC"
                  ? "After 4 PM &amp; weekends"
                  : null;
          tooltipRef.current.innerHTML = accessNote
            ? `<strong>${lot.name}</strong><br/><span style="opacity:0.9">${accessNote}</span>`
            : `<strong>${lot.name}</strong>`;
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

      const bounds = new google.maps.LatLngBounds();
      lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));

      const label = new markerLib.AdvancedMarkerElement({
        position: bounds.getCenter(),
        map,
        content: createLabelElement(lot.name, labelColor, labelSize, labelOpacity),
      });
      markersRef.current.push(label);
    });

    // Zoom: emphasize subset on hover, otherwise fit all colored/highlighted lots
    const zoomTargets = hasEmphasize
      ? lots.filter((l) => l.boundary.length >= 3 && isLotHighlighted(l.name, highlightedLots))
      : colorMode
        ? lots.filter((l) => l.boundary.length >= 3 && lookupLotColor(l.name, lotColors))
        : [];

    if (zoomTargets.length > 0 && (hasEmphasize || colorMode)) {
      const bounds = new google.maps.LatLngBounds();
      zoomTargets.forEach((lot) => {
        lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));
      });
      fitMapToLots(map, bounds, 60, zoomTargets.length);
    }

    return () => {
      polygonsRef.current.forEach((p) => p.setMap(null));
      markersRef.current.forEach((m) => { m.map = null; });
    };
  }, [map, markerLib, lots, highlightedLots, focusedLot, lotColors, colorMode, onLotClick]);

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
      {legend && legend.length > 0 ? (
        <div className="absolute top-3 left-3 z-10 bg-[#1a2744]/95 backdrop-blur-sm rounded-lg px-4 py-3 text-white text-sm font-semibold shadow-xl space-y-2 border border-white/20">
          {legend.map((item) => (
            <div key={item.label} className="flex items-center gap-2.5">
              <span
                className="inline-block w-4 h-4 rounded shrink-0 border-2 border-white/70"
                style={{ background: item.color }}
              />
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      ) : (
        highlightedLots.length > 0 && (
          <div className="absolute top-3 left-3 z-10 bg-[#1a2744]/90 backdrop-blur rounded-lg px-3 py-2 text-white text-xs font-medium shadow-lg">
            Showing: {highlightedLots.map((n) => `Lot ${n}`).join(", ")}
          </div>
        )
      )}
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
          focusedLot={props.focusedLot}
          defaultCenter={props.defaultCenter}
          lotColors={props.lotColors}
          legend={props.legend}
          onLotClick={props.onLotClick}
        />
      </div>
    </APIProvider>
  );
}
