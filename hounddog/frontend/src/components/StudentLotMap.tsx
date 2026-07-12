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

  // Create polygons and labels once when lots data loads
  useEffect(() => {
    if (!map) return;

    entriesRef.current.forEach((e) => { e.polygon.setMap(null); e.label.setMap(null); });
    entriesRef.current = [];

    lots.forEach((lot) => {
      if (lot.boundary.length < 3) return;

      const poly = new google.maps.Polygon({
        paths: lot.boundary.map((c) => ({ lat: c.latitude, lng: c.longitude })),
        strokeColor: "#9CA3AF",
        strokeOpacity: 0.8,
        strokeWeight: 1,
        fillColor: "#9CA3AF",
        fillOpacity: 0.2,
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
          fontSize: "12px",
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

  // Update polygon styles + pan/zoom when highlightedLots changes
  useEffect(() => {
    if (!map) return;
    const hasHighlight = highlightedLots.length > 0;

    entriesRef.current.forEach(({ polygon, label, lotName }) => {
      const isHighlighted = hasHighlight && highlightedLots.includes(lotName);

      if (!hasHighlight) {
        polygon.setOptions({
          fillColor: "#9CA3AF",
          fillOpacity: 0.2,
          strokeColor: "#9CA3AF",
          strokeOpacity: 0.8,
          strokeWeight: 1,
        });
        label.setOpacity(1);
      } else if (isHighlighted) {
        polygon.setOptions({
          fillColor: HIGHLIGHT_FILL,
          fillOpacity: 0.7,
          strokeColor: HIGHLIGHT_STROKE,
          strokeOpacity: 1,
          strokeWeight: 4,
        });
        label.setOpacity(1);
      } else {
        polygon.setOptions({
          fillColor: "#000000",
          fillOpacity: 0.02,
          strokeColor: "#6B7280",
          strokeOpacity: 0.2,
          strokeWeight: 1,
        });
        label.setOpacity(0.15);
      }
    });

    if (hasHighlight) {
      const highlighted = lots.filter(
        (l) => l.boundary.length >= 3 && highlightedLots.includes(l.name),
      );
      if (highlighted.length > 0) {
        const bounds = new google.maps.LatLngBounds();
        highlighted.forEach((lot) => {
          lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));
        });
        map.fitBounds(bounds, 80);
      }
    } else {
      const center = defaultCenter ?? DEFAULT_CENTER;
      map.panTo(center);
      map.setZoom(DEFAULT_ZOOM);
    }
  }, [map, lots, highlightedLots, defaultCenter]);

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
