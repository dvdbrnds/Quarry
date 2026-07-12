import { APIProvider, Map, useMap } from "@vis.gl/react-google-maps";
import { useEffect, useRef } from "react";
import type { Lot } from "../api";

const DEFAULT_CENTER = { lat: 40.6265, lng: -75.3707 };
const DEFAULT_ZOOM = 17;
const HIGHLIGHT_FILL = "#FFD700";
const HIGHLIGHT_STROKE = "#FFFFFF";

interface StudentLotMapProps {
  apiKey: string;
  lots: Lot[];
  highlightedLots: string[];
  defaultCenter?: { lat: number; lng: number };
}

interface PolyEntry {
  polygon: google.maps.Polygon;
  label: google.maps.Marker;
  lotName: string;
}

function MapContent({
  lots,
  highlightedLots,
  defaultCenter,
}: Omit<StudentLotMapProps, "apiKey">) {
  const map = useMap();
  const entriesRef = useRef<PolyEntry[]>([]);
  const tooltipRef = useRef<HTMLDivElement | null>(null);

  // Create polygons + labels once when lots data loads (NOT on highlight changes)
  useEffect(() => {
    if (!map) return;

    entriesRef.current.forEach((e) => { e.polygon.setMap(null); e.label.setMap(null); });
    entriesRef.current = [];

    lots.forEach((lot) => {
      if (lot.boundary.length < 3) return;

      const poly = new google.maps.Polygon({
        paths: lot.boundary.map((c) => ({ lat: c.latitude, lng: c.longitude })),
        strokeColor: "#D1D5DB",
        strokeOpacity: 1,
        strokeWeight: 2,
        fillColor: "#9CA3AF",
        fillOpacity: 0.25,
        zIndex: 1,
        map,
        clickable: true,
      });

      poly.addListener("mouseover", () => {
        if (tooltipRef.current) {
          tooltipRef.current.innerHTML = `<strong>Lot ${lot.name}</strong>`;
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

      const bounds = new google.maps.LatLngBounds();
      lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));

      const label = new google.maps.Marker({
        position: bounds.getCenter(),
        map,
        icon: { path: google.maps.SymbolPath.CIRCLE, scale: 0 },
        label: {
          text: lot.name,
          color: "white",
          fontSize: "11px",
          fontWeight: "bold",
          className: "lot-map-label",
        },
        clickable: false,
      });

      entriesRef.current.push({ polygon: poly, label, lotName: lot.name });
    });

    return () => {
      entriesRef.current.forEach((e) => { e.polygon.setMap(null); e.label.setMap(null); });
    };
  }, [map, lots]);

  // Update polygon styles in-place when highlight changes -- NO map movement
  useEffect(() => {
    const hasHighlight = highlightedLots.length > 0;

    entriesRef.current.forEach(({ polygon, label, lotName }) => {
      const isHighlighted = hasHighlight && highlightedLots.includes(lotName);

      if (!hasHighlight) {
        polygon.setOptions({
          fillColor: "#9CA3AF",
          fillOpacity: 0.25,
          strokeColor: "#D1D5DB",
          strokeWeight: 2,
          zIndex: 1,
        });
        label.setOptions({
          opacity: 1,
          label: { text: lotName, color: "white", fontSize: "11px", fontWeight: "bold", className: "lot-map-label" },
        });
      } else if (isHighlighted) {
        polygon.setOptions({
          fillColor: HIGHLIGHT_FILL,
          fillOpacity: 0.7,
          strokeColor: HIGHLIGHT_STROKE,
          strokeWeight: 4,
          zIndex: 10,
        });
        label.setOptions({
          opacity: 1,
          label: { text: lotName, color: HIGHLIGHT_FILL, fontSize: "14px", fontWeight: "bold", className: "lot-map-label" },
        });
      } else {
        polygon.setOptions({
          fillColor: "#000000",
          fillOpacity: 0.01,
          strokeColor: "#6B7280",
          strokeWeight: 0,
          zIndex: 0,
        });
        label.setOptions({ opacity: 0 });
      }
    });
  }, [highlightedLots]);

  return (
    <>
      <Map
        defaultCenter={defaultCenter ?? DEFAULT_CENTER}
        defaultZoom={DEFAULT_ZOOM}
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
