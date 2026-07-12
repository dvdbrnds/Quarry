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

function MapContent({
  lots,
  highlightedLots,
  defaultCenter,
}: Omit<StudentLotMapProps, "apiKey">) {
  const map = useMap();
  const polygonsRef = useRef<google.maps.Polygon[]>([]);
  const markersRef = useRef<google.maps.Marker[]>([]);
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

  // Recreate polygons + labels every time lots OR highlightedLots change
  useEffect(() => {
    if (!map) return;

    // Destroy previous
    polygonsRef.current.forEach((p) => p.setMap(null));
    polygonsRef.current = [];
    markersRef.current.forEach((m) => m.setMap(null));
    markersRef.current = [];

    const hasHighlight = highlightedLots.length > 0;

    lots.forEach((lot) => {
      if (lot.boundary.length < 3) return;

      const isHighlighted = hasHighlight && highlightedLots.includes(lot.name);

      const poly = new google.maps.Polygon({
        paths: lot.boundary.map((c) => ({ lat: c.latitude, lng: c.longitude })),
        strokeColor: !hasHighlight ? "#D1D5DB" : isHighlighted ? HIGHLIGHT_STROKE : "#6B7280",
        strokeOpacity: !hasHighlight ? 1 : isHighlighted ? 1 : 0.2,
        strokeWeight: !hasHighlight ? 2 : isHighlighted ? 4 : 0,
        fillColor: !hasHighlight ? "#9CA3AF" : isHighlighted ? HIGHLIGHT_FILL : "#000000",
        fillOpacity: !hasHighlight ? 0.25 : isHighlighted ? 0.7 : 0.01,
        zIndex: isHighlighted ? 10 : 1,
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

      polygonsRef.current.push(poly);

      // Label
      const bounds = new google.maps.LatLngBounds();
      lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));

      const showLabel = !hasHighlight || isHighlighted;
      const label = new google.maps.Marker({
        position: bounds.getCenter(),
        map,
        icon: { path: google.maps.SymbolPath.CIRCLE, scale: 0 },
        label: {
          text: lot.name,
          color: isHighlighted ? HIGHLIGHT_FILL : "white",
          fontSize: isHighlighted ? "14px" : "11px",
          fontWeight: "bold",
          className: "lot-map-label",
        },
        opacity: showLabel ? 1 : 0,
        clickable: false,
      });
      markersRef.current.push(label);
    });

    // Zoom to highlighted lots on hover (don't move on unhover)
    if (hasHighlight) {
      const highlighted = lots.filter(
        (l) => l.boundary.length >= 3 && highlightedLots.includes(l.name),
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
      markersRef.current.forEach((m) => m.setMap(null));
    };
  }, [map, lots, highlightedLots]);

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
