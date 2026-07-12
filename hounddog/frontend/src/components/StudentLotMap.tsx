import { APIProvider, Map, useMap } from "@vis.gl/react-google-maps";
import { useEffect, useRef } from "react";
import type { Coordinate, Lot } from "../api";

const DEFAULT_CENTER = { lat: 40.6265, lng: -75.3707 };
const BRASS = "#C5A55A";
const DIM_COLOR = "#94A3B8";
const STREET_COLOR = "#3B82F6";

interface StudentLotMapProps {
  apiKey: string;
  lots: Lot[];
  highlightedLots: string[];
  defaultCenter?: { lat: number; lng: number };
}

function lotBaseColor(lot: Lot): string {
  if (lot.lot_type === "street") return STREET_COLOR;
  return DIM_COLOR;
}

function MapContent({
  lots,
  highlightedLots,
  defaultCenter,
}: Omit<StudentLotMapProps, "apiKey">) {
  const map = useMap();
  const polygonsRef = useRef<google.maps.Polygon[]>([]);
  const labelMarkersRef = useRef<google.maps.Marker[]>([]);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const highlightedRef = useRef(highlightedLots);
  useEffect(() => { highlightedRef.current = highlightedLots; }, [highlightedLots]);

  // Fit map to all lots on initial load
  useEffect(() => {
    if (!map) return;
    const lotsWithBounds = lots.filter((l) => l.boundary.length >= 3);
    if (lotsWithBounds.length === 0) return;

    const timer = setTimeout(() => {
      const bounds = new google.maps.LatLngBounds();
      lotsWithBounds.forEach((lot) => {
        lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));
      });
      map.fitBounds(bounds, 40);
    }, 100);

    return () => clearTimeout(timer);
  }, [map, lots]);

  // Render lot polygons with highlight support
  useEffect(() => {
    if (!map) return;

    polygonsRef.current.forEach((p) => p.setMap(null));
    polygonsRef.current = [];
    labelMarkersRef.current.forEach((m) => m.setMap(null));
    labelMarkersRef.current = [];

    const hasHighlight = highlightedLots.length > 0;

    lots.forEach((lot) => {
      if (lot.boundary.length < 3) return;

      const isHighlighted = hasHighlight && highlightedLots.includes(lot.name);
      const baseColor = lotBaseColor(lot);

      let fillColor: string;
      let fillOpacity: number;
      let strokeColor: string;
      let strokeWeight: number;

      if (!hasHighlight) {
        fillColor = baseColor;
        fillOpacity = 0.2;
        strokeColor = baseColor;
        strokeWeight = 1;
      } else if (isHighlighted) {
        fillColor = BRASS;
        fillOpacity = 0.5;
        strokeColor = BRASS;
        strokeWeight = 3;
      } else {
        fillColor = baseColor;
        fillOpacity = 0.08;
        strokeColor = baseColor;
        strokeWeight = 1;
      }

      const poly = new google.maps.Polygon({
        paths: lot.boundary.map((c) => ({ lat: c.latitude, lng: c.longitude })),
        strokeColor,
        strokeOpacity: 1,
        strokeWeight,
        fillColor,
        fillOpacity,
        map,
        clickable: true,
      });

      poly.addListener("mouseover", () => {
        if (tooltipRef.current) {
          tooltipRef.current.innerHTML = `<strong>Lot ${lot.name}</strong>`;
          tooltipRef.current.style.display = "block";
        }
        const hl = highlightedRef.current;
        const active = hl.length > 0 && hl.includes(lot.name);
        if (!active) {
          poly.setOptions({ fillOpacity: 0.35, strokeWeight: 2 });
        }
      });
      poly.addListener("mousemove", (e: google.maps.MapMouseEvent) => {
        if (tooltipRef.current && e.domEvent instanceof MouseEvent) {
          tooltipRef.current.style.left = `${e.domEvent.offsetX + 12}px`;
          tooltipRef.current.style.top = `${e.domEvent.offsetY + 12}px`;
        }
      });
      poly.addListener("mouseout", () => {
        if (tooltipRef.current) {
          tooltipRef.current.style.display = "none";
        }
        const hl = highlightedRef.current;
        const hasHl = hl.length > 0;
        const active = hasHl && hl.includes(lot.name);
        if (active) {
          poly.setOptions({ fillOpacity: 0.5, strokeWeight: 3 });
        } else if (hasHl) {
          poly.setOptions({ fillOpacity: 0.08, strokeWeight: 1 });
        } else {
          poly.setOptions({ fillOpacity: 0.2, strokeWeight: 1 });
        }
      });

      polygonsRef.current.push(poly);

      const bounds = new google.maps.LatLngBounds();
      lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));
      const center = bounds.getCenter();

      const labelOpacity = !hasHighlight || isHighlighted;
      const label = new google.maps.Marker({
        position: center,
        map,
        icon: { path: google.maps.SymbolPath.CIRCLE, scale: 0 },
        label: {
          text: lot.name,
          color: "white",
          fontSize: "11px",
          fontWeight: "bold",
          className: "lot-map-label",
        },
        opacity: labelOpacity ? 1 : 0.3,
        clickable: false,
      });
      labelMarkersRef.current.push(label);
    });

    return () => {
      polygonsRef.current.forEach((p) => p.setMap(null));
      labelMarkersRef.current.forEach((m) => m.setMap(null));
    };
  }, [map, lots, highlightedLots]);

  return (
    <>
      <Map
        defaultCenter={defaultCenter ?? DEFAULT_CENTER}
        defaultZoom={16}
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
