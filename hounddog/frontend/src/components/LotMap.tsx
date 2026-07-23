import {
  APIProvider,
  Map,
  useMap,
  useMapsLibrary,
} from "@vis.gl/react-google-maps";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Coordinate, Lot, ParkingSpot } from "../api";

const DEFAULT_CENTER = { lat: 40.6265, lng: -75.3707 };
const HIGHLIGHT = getComputedStyle(document.documentElement).getPropertyValue("--brand-primary").trim() || "#0A1628";

function spotScale(zoom: number, selected: boolean): { iconScale: number; fontSize: string } {
  const base = selected ? 14 : 11;
  const refZoom = 19;
  const ratio = Math.pow(2, zoom - refZoom);
  const clamped = Math.max(0.25, Math.min(1, ratio));
  return {
    iconScale: Math.round(base * clamped),
    fontSize: `${Math.max(6, Math.round(10 * clamped))}px`,
  };
}
const LOT_OPEN = "#22C55E";
const LOT_CLOSED = "#EF4444";
const STREET_COLOR = "#3B82F6";
const EXTERNAL_COLOR = "#F59E0B";

const SPOT_TYPE_COLORS: Record<string, string> = {
  standard: "#3B82F6",
  ev: "#22C55E",
  handicap: "#6366F1",
  reserved: "#D97706",
  loading: "#6B7280",
};

interface LotMapProps {
  apiKey: string;
  lots: Lot[];
  selectedLotId: string | null;
  onSelectLot: (id: string | null) => void;
  editingBoundary: Coordinate[] | null;
  onBoundaryChange: (coords: Coordinate[]) => void;
  defaultCenter?: { lat: number; lng: number };
  spots?: ParkingSpot[];
  selectedSpotId?: string | null;
  onSelectSpot?: (id: string | null) => void;
  placingSpot?: boolean;
  onPlaceSpot?: (lat: number, lng: number) => void;
}

function lotFillColor(lot: Lot): string {
  if (lot.lot_type === "external") return EXTERNAL_COLOR;
  if (lot.lot_type === "street") return STREET_COLOR;
  return lot.is_closed ? LOT_CLOSED : LOT_OPEN;
}

/** Create an HTML element for a text-only map label */
function createLabelElement(text: string): HTMLDivElement {
  const el = document.createElement("div");
  el.className = "lot-map-label";
  el.style.color = "white";
  el.style.fontSize = "11px";
  el.style.fontWeight = "bold";
  el.style.whiteSpace = "nowrap";
  el.style.textShadow = "0 1px 3px rgba(0,0,0,0.8)";
  el.textContent = text;
  return el;
}

/** Create an HTML element for a circular spot marker */
function createSpotElement(
  number: number,
  color: string,
  strokeColor: string,
  strokeWeight: number,
  scale: number,
  fontSize: string,
): HTMLDivElement {
  const size = scale * 2;
  const el = document.createElement("div");
  el.style.width = `${size}px`;
  el.style.height = `${size}px`;
  el.style.borderRadius = "50%";
  el.style.backgroundColor = color;
  el.style.border = `${strokeWeight}px solid ${strokeColor}`;
  el.style.display = "flex";
  el.style.alignItems = "center";
  el.style.justifyContent = "center";
  el.style.color = "white";
  el.style.fontSize = fontSize;
  el.style.fontWeight = "bold";
  el.style.lineHeight = "1";
  el.style.cursor = "pointer";
  el.textContent = String(number);
  return el;
}

/** Update an existing spot element's appearance */
function updateSpotElement(
  el: HTMLDivElement,
  color: string,
  strokeColor: string,
  strokeWeight: number,
  scale: number,
  fontSize: string,
  visible: boolean,
): void {
  const size = scale * 2;
  el.style.width = `${size}px`;
  el.style.height = `${size}px`;
  el.style.backgroundColor = color;
  el.style.border = `${strokeWeight}px solid ${strokeColor}`;
  el.style.fontSize = fontSize;
  el.style.display = visible ? "flex" : "none";
}

/** Create an HTML element for a vertex marker (boundary drawing) */
function createVertexElement(index: number): HTMLDivElement {
  const size = 20;
  const el = document.createElement("div");
  el.style.width = `${size}px`;
  el.style.height = `${size}px`;
  el.style.borderRadius = "50%";
  el.style.backgroundColor = HIGHLIGHT;
  el.style.border = "2px solid white";
  el.style.display = "flex";
  el.style.alignItems = "center";
  el.style.justifyContent = "center";
  el.style.color = "white";
  el.style.fontSize = "11px";
  el.style.fontWeight = "bold";
  el.style.lineHeight = "1";
  el.textContent = String(index + 1);
  return el;
}

function MapContent({
  lots,
  selectedLotId,
  onSelectLot,
  editingBoundary,
  onBoundaryChange,
  defaultCenter,
  spots = [],
  selectedSpotId,
  onSelectSpot,
  placingSpot = false,
  onPlaceSpot,
}: Omit<LotMapProps, "apiKey">) {
  const map = useMap();
  const markerLib = useMapsLibrary("marker");
  const polygonsRef = useRef<google.maps.Polygon[]>([]);
  const labelMarkersRef = useRef<google.maps.marker.AdvancedMarkerElement[]>([]);
  const editPolygonRef = useRef<google.maps.Polygon | null>(null);
  const markersRef = useRef<google.maps.marker.AdvancedMarkerElement[]>([]);
  const spotMarkersRef = useRef<google.maps.marker.AdvancedMarkerElement[]>([]);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const [drawingActive, setDrawingActive] = useState(false);

  // Refs so Google Maps event listeners always see the latest values
  const placingRef = useRef(placingSpot);
  useEffect(() => { placingRef.current = placingSpot; }, [placingSpot]);
  const placeSpotRef = useRef(onPlaceSpot);
  useEffect(() => { placeSpotRef.current = onPlaceSpot; }, [onPlaceSpot]);

  const syncEditPolygon = useCallback(() => {
    const poly = editPolygonRef.current;
    if (!poly) return;
    const path = poly.getPath();
    const coords: Coordinate[] = [];
    for (let i = 0; i < path.getLength(); i++) {
      const pt = path.getAt(i);
      coords.push({ latitude: pt.lat(), longitude: pt.lng() });
    }
    onBoundaryChange(coords);
  }, [onBoundaryChange]);

  // Render existing lot polygons
  useEffect(() => {
    if (!map || !markerLib) return;

    polygonsRef.current.forEach((p) => p.setMap(null));
    polygonsRef.current = [];
    labelMarkersRef.current.forEach((m) => { m.map = null; });
    labelMarkersRef.current = [];

    lots.forEach((lot) => {
      if (lot.boundary.length < 3) return;
      if (editingBoundary !== null && lot.id === selectedLotId) return;

      const fill = lotFillColor(lot);
      const isSelected = lot.id === selectedLotId;

      const poly = new google.maps.Polygon({
        paths: lot.boundary.map((c) => ({ lat: c.latitude, lng: c.longitude })),
        strokeColor: isSelected ? HIGHLIGHT : fill,
        strokeOpacity: 1,
        strokeWeight: isSelected ? 3 : 2,
        fillColor: fill,
        fillOpacity: isSelected ? 0.4 : 0.3,
        map,
        clickable: true,
      });

      poly.addListener("click", (e: google.maps.MapMouseEvent) => {
        if (placingRef.current && placeSpotRef.current && e.latLng) {
          placeSpotRef.current(e.latLng.lat(), e.latLng.lng());
          return;
        }
        if (!isSelected) {
          onSelectLot(lot.id);
        }
      });

      poly.addListener("mouseover", () => {
        if (tooltipRef.current) {
          const closed = lot.is_closed ? ' · <span style="color:#EF4444">CLOSED</span>' : "";
          tooltipRef.current.innerHTML = `<strong>${lot.name}</strong>${closed}`;
          tooltipRef.current.style.display = "block";
        }
        if (!isSelected) {
          poly.setOptions({ fillOpacity: 0.45, strokeWeight: 3 });
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
        if (!isSelected) {
          poly.setOptions({ fillOpacity: 0.3, strokeWeight: 2 });
        }
      });

      polygonsRef.current.push(poly);

      const bounds = new google.maps.LatLngBounds();
      lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));
      const center = bounds.getCenter();

      const label = new markerLib.AdvancedMarkerElement({
        position: center,
        map,
        content: createLabelElement(lot.name),
      });
      labelMarkersRef.current.push(label);
    });

    return () => {
      polygonsRef.current.forEach((p) => p.setMap(null));
      labelMarkersRef.current.forEach((m) => { m.map = null; });
    };
  }, [map, markerLib, lots, selectedLotId, editingBoundary, onSelectLot]);

  // Render spot markers for the selected lot (zoom-aware)
  useEffect(() => {
    spotMarkersRef.current.forEach((m) => { m.map = null; });
    spotMarkersRef.current = [];

    if (!map || !markerLib || !selectedLotId || spots.length === 0) return;

    const currentZoom = map.getZoom() ?? 19;

    spots.forEach((spot) => {
      if (spot.latitude == null || spot.longitude == null) return;

      const isSelected = spot.id === selectedSpotId;
      const color = SPOT_TYPE_COLORS[spot.spot_type] ?? SPOT_TYPE_COLORS.standard;
      const { iconScale, fontSize } = spotScale(currentZoom, isSelected);

      const content = createSpotElement(
        spot.number,
        color,
        isSelected ? HIGHLIGHT : "white",
        isSelected ? 3 : 2,
        iconScale,
        fontSize,
      );

      if (iconScale < 3) content.style.display = "none";

      const marker = new markerLib.AdvancedMarkerElement({
        position: { lat: spot.latitude, lng: spot.longitude },
        map,
        content,
        title: `#${spot.number}${spot.label ? ` — ${spot.label}` : ""}${spot.sensor_id ? ` [${spot.sensor_id}]` : ""}`,
        zIndex: isSelected ? 100 : 10,
      });

      marker.addListener("gmp-click", () => {
        onSelectSpot?.(spot.id);
      });

      spotMarkersRef.current.push(marker);
    });

    const zoomListener = map.addListener("zoom_changed", () => {
      const z = map.getZoom() ?? 19;
      const filteredSpots = spots.filter(s => s.latitude != null && s.longitude != null);
      spotMarkersRef.current.forEach((marker, i) => {
        const spot = filteredSpots[i];
        if (!spot) return;
        const isSelected = spot.id === selectedSpotId;
        const color = SPOT_TYPE_COLORS[spot.spot_type] ?? SPOT_TYPE_COLORS.standard;
        const { iconScale, fontSize } = spotScale(z, isSelected);
        const el = marker.content as HTMLDivElement;
        if (el) {
          updateSpotElement(
            el,
            color,
            isSelected ? HIGHLIGHT : "white",
            isSelected ? 3 : 2,
            iconScale,
            fontSize,
            iconScale >= 3,
          );
        }
      });
    });

    return () => {
      google.maps.event.removeListener(zoomListener);
      spotMarkersRef.current.forEach((m) => { m.map = null; });
    };
  }, [map, markerLib, selectedLotId, spots, selectedSpotId, onSelectSpot]);

  // Fit map to all lots on initial load / when no lot is selected
  useEffect(() => {
    if (!map || selectedLotId) return;
    const lotsWithBounds = lots.filter((l) => l.boundary.length >= 3);
    if (lotsWithBounds.length === 0) return;

    const timer = setTimeout(() => {
      const bounds = new google.maps.LatLngBounds();
      lotsWithBounds.forEach((lot) => {
        lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));
      });
      map.fitBounds(bounds, 60);
    }, 100);

    return () => clearTimeout(timer);
  }, [map, lots, selectedLotId]);

  // Center map on selected lot
  useEffect(() => {
    if (!map || !selectedLotId) return;
    const lot = lots.find((l) => l.id === selectedLotId);
    if (!lot || lot.boundary.length < 3) return;

    const timer = setTimeout(() => {
      const bounds = new google.maps.LatLngBounds();
      lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));
      map.fitBounds(bounds, 80);
    }, 100);

    return () => clearTimeout(timer);
  }, [map, selectedLotId, lots]);

  // Render vertex markers for the points being placed (boundary drawing)
  useEffect(() => {
    markersRef.current.forEach((m) => { m.map = null; });
    markersRef.current = [];

    if (!map || !markerLib || !editingBoundary || !drawingActive) return;

    editingBoundary.forEach((c, i) => {
      const marker = new markerLib.AdvancedMarkerElement({
        position: { lat: c.latitude, lng: c.longitude },
        map,
        content: createVertexElement(i),
      });
      markersRef.current.push(marker);
    });

    return () => {
      markersRef.current.forEach((m) => { m.map = null; });
    };
  }, [map, markerLib, editingBoundary, drawingActive]);

  // Render editable polygon for the boundary being edited (not in drawing mode)
  useEffect(() => {
    if (!map) return;

    if (editPolygonRef.current) {
      editPolygonRef.current.setMap(null);
      editPolygonRef.current = null;
    }

    if (!editingBoundary || editingBoundary.length < 3 || drawingActive) return;

    const poly = new google.maps.Polygon({
      paths: editingBoundary.map((c) => ({ lat: c.latitude, lng: c.longitude })),
      strokeColor: HIGHLIGHT,
      strokeWeight: 3,
      fillColor: HIGHLIGHT,
      fillOpacity: 0.25,
      editable: true,
      draggable: false,
      map,
    });

    const path = poly.getPath();
    google.maps.event.addListener(path, "set_at", () => syncEditPolygon());
    google.maps.event.addListener(path, "insert_at", () => syncEditPolygon());
    google.maps.event.addListener(path, "remove_at", () => syncEditPolygon());

    editPolygonRef.current = poly;

    const bounds = new google.maps.LatLngBounds();
    editingBoundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));
    map.fitBounds(bounds, 80);

    return () => {
      poly.setMap(null);
    };
  }, [map, editingBoundary, drawingActive, syncEditPolygon]);

  // Drawing-mode preview polygon (connects placed points)
  const previewPolyRef = useRef<google.maps.Polyline | null>(null);
  useEffect(() => {
    if (previewPolyRef.current) {
      previewPolyRef.current.setMap(null);
      previewPolyRef.current = null;
    }

    if (!map || !drawingActive || !editingBoundary || editingBoundary.length < 2) return;

    const path = editingBoundary.map((c) => ({ lat: c.latitude, lng: c.longitude }));
    if (editingBoundary.length >= 3) {
      path.push(path[0]);
    }

    const line = new google.maps.Polyline({
      path,
      strokeColor: HIGHLIGHT,
      strokeWeight: 3,
      strokeOpacity: 0.8,
      map,
    });

    previewPolyRef.current = line;
    return () => { line.setMap(null); };
  }, [map, drawingActive, editingBoundary]);

  // Click-to-place handler: boundary drawing OR spot placement
  useEffect(() => {
    if (!map) return;
    if (!drawingActive && !placingSpot) return;

    const listener = map.addListener("click", (e: google.maps.MapMouseEvent) => {
      if (!e.latLng) return;

      if (placingRef.current && placeSpotRef.current) {
        placeSpotRef.current(e.latLng.lat(), e.latLng.lng());
        return;
      }

      if (drawingActive) {
        const newPoint: Coordinate = {
          latitude: e.latLng.lat(),
          longitude: e.latLng.lng(),
        };
        onBoundaryChange([...(editingBoundary ?? []), newPoint]);
      }
    });

    return () => {
      google.maps.event.removeListener(listener);
    };
  }, [map, drawingActive, placingSpot, editingBoundary, onBoundaryChange, onPlaceSpot]);

  const startDrawing = useCallback(() => {
    onBoundaryChange([]);
    setDrawingActive(true);
  }, [onBoundaryChange]);

  const finishDrawing = useCallback(() => {
    setDrawingActive(false);
  }, []);

  const undoLastPoint = useCallback(() => {
    if (!editingBoundary || editingBoundary.length === 0) return;
    onBoundaryChange(editingBoundary.slice(0, -1));
  }, [editingBoundary, onBoundaryChange]);

  const clearBoundary = useCallback(() => {
    onBoundaryChange([]);
    setDrawingActive(false);
    if (editPolygonRef.current) {
      editPolygonRef.current.setMap(null);
      editPolygonRef.current = null;
    }
  }, [onBoundaryChange]);

  return (
    <>
      <div className="absolute top-3 right-3 z-10 flex gap-2">
        {editingBoundary !== null && (
          <>
            {drawingActive ? (
              <>
                <button
                  onClick={undoLastPoint}
                  disabled={!editingBoundary || editingBoundary.length === 0}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium shadow-lg bg-white text-brand-primary hover:bg-gray-50 transition-colors disabled:opacity-30"
                >
                  Undo Point
                </button>
                <button
                  onClick={finishDrawing}
                  disabled={!editingBoundary || editingBoundary.length < 3}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium shadow-lg bg-brand-primary text-white hover:opacity-90 transition-colors disabled:opacity-30"
                >
                  Done ({editingBoundary?.length ?? 0} pts)
                </button>
                <button
                  onClick={clearBoundary}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium shadow-lg bg-signal-red text-white transition-colors"
                >
                  Cancel
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={startDrawing}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium shadow-lg bg-white text-brand-primary hover:bg-gray-50 transition-colors"
                >
                  {editingBoundary.length > 0 ? "Redraw Boundary" : "Draw Boundary"}
                </button>
                {editingBoundary.length > 0 && (
                  <button
                    onClick={clearBoundary}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium shadow-lg bg-white text-signal-red hover:bg-red-50 transition-colors"
                  >
                    Clear
                  </button>
                )}
              </>
            )}
          </>
        )}
      </div>
      {drawingActive && (
        <div className="absolute top-3 left-3 z-10 bg-white/90 backdrop-blur rounded-lg shadow-lg px-3 py-2 text-xs text-brand-primary max-w-[200px]">
          Click on the map to place boundary points. Place at least 3 points, then click <strong>Done</strong>.
        </div>
      )}
      {editingBoundary !== null && !drawingActive && editingBoundary.length >= 3 && (
        <div className="absolute top-3 left-3 z-10 bg-white/90 backdrop-blur rounded-lg shadow-lg px-3 py-2 text-xs text-brand-primary max-w-[220px]">
          Drag the <strong>white squares</strong> on the boundary to adjust points. Drag midpoints to add new vertices.
        </div>
      )}
      {placingSpot && (
        <div className="absolute top-3 left-3 z-10 bg-amber-50/95 backdrop-blur rounded-lg shadow-lg px-3 py-2 text-xs text-amber-800 max-w-[220px] border border-amber-300">
          Click on the map to place the spot's puck location.
        </div>
      )}
      <Map
        defaultCenter={defaultCenter ?? DEFAULT_CENTER}
        defaultZoom={16}
        mapId="DEMO_MAP_ID"
        mapTypeId="satellite"
        gestureHandling="greedy"
        disableDefaultUI={false}
        mapTypeControl={true}
        streetViewControl={false}
        fullscreenControl={true}
        zoomControl={true}
        style={{ width: "100%", height: "100%" }}
        onClick={() => {
          if (!drawingActive && !placingSpot) {
            onSelectLot(null);
            onSelectSpot?.(null);
          }
        }}
      />
      <div
        ref={tooltipRef}
        style={{ display: "none" }}
        className="absolute z-20 pointer-events-none px-2 py-1 rounded bg-brand-primary/90 text-white text-xs font-medium whitespace-nowrap shadow"
      />
    </>
  );
}

export default function LotMap(props: LotMapProps) {
  if (!props.apiKey) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-gray-100 rounded-xl">
        <div className="text-center p-6">
          <p className="text-ink-mute text-sm mb-2">Google Maps API key not configured.</p>
          <p className="text-xs text-ink-mute">
            Set <code className="bg-gray-200 px-1 rounded">GOOGLE_MAPS_API_KEY</code> to enable the map.
          </p>
        </div>
      </div>
    );
  }

  return (
    <APIProvider apiKey={props.apiKey}>
      <div className="w-full h-full relative rounded-xl overflow-hidden">
        <MapContent {...props} />
      </div>
    </APIProvider>
  );
}
