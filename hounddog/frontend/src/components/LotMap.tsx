import {
  APIProvider,
  Map,
  useMap,
} from "@vis.gl/react-google-maps";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Coordinate, Lot } from "../api";

const DEFAULT_CENTER = { lat: 40.6265, lng: -75.3707 };
const BRASS = "#C5A55A";
const LOT_OPEN = "#22C55E";
const LOT_CLOSED = "#EF4444";

interface LotMapProps {
  apiKey: string;
  lots: Lot[];
  selectedLotId: string | null;
  onSelectLot: (id: string | null) => void;
  editingBoundary: Coordinate[] | null;
  onBoundaryChange: (coords: Coordinate[]) => void;
  defaultCenter?: { lat: number; lng: number };
}

function lotFillColor(lot: Lot): string {
  return lot.is_closed ? LOT_CLOSED : LOT_OPEN;
}

function MapContent({
  lots,
  selectedLotId,
  onSelectLot,
  editingBoundary,
  onBoundaryChange,
  defaultCenter,
}: Omit<LotMapProps, "apiKey">) {
  const map = useMap();
  const polygonsRef = useRef<google.maps.Polygon[]>([]);
  const labelMarkersRef = useRef<google.maps.Marker[]>([]);
  const editPolygonRef = useRef<google.maps.Polygon | null>(null);
  const markersRef = useRef<google.maps.Marker[]>([]);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const [drawingActive, setDrawingActive] = useState(false);

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
    if (!map) return;

    polygonsRef.current.forEach((p) => p.setMap(null));
    polygonsRef.current = [];
    labelMarkersRef.current.forEach((m) => m.setMap(null));
    labelMarkersRef.current = [];

    lots.forEach((lot, idx) => {
      if (lot.boundary.length < 3) return;
      if (editingBoundary !== null && lot.id === selectedLotId) return;

      const fill = lotFillColor(lot);
      const isSelected = lot.id === selectedLotId;

      const poly = new google.maps.Polygon({
        paths: lot.boundary.map((c) => ({ lat: c.latitude, lng: c.longitude })),
        strokeColor: isSelected ? BRASS : fill,
        strokeOpacity: 1,
        strokeWeight: isSelected ? 3 : 2,
        fillColor: fill,
        fillOpacity: isSelected ? 0.4 : 0.3,
        map,
        clickable: true,
      });

      poly.addListener("click", () => onSelectLot(lot.id));

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

      // Center label so lots are identifiable without hovering
      const bounds = new google.maps.LatLngBounds();
      lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));
      const center = bounds.getCenter();

      const label = new google.maps.Marker({
        position: center,
        map,
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 0,
        },
        label: {
          text: lot.name,
          color: "white",
          fontSize: "11px",
          fontWeight: "bold",
          className: "lot-map-label",
        },
        clickable: false,
      });
      labelMarkersRef.current.push(label);
    });

    return () => {
      polygonsRef.current.forEach((p) => p.setMap(null));
      labelMarkersRef.current.forEach((m) => m.setMap(null));
    };
  }, [map, lots, selectedLotId, editingBoundary, onSelectLot]);

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

  // Render vertex markers for the points being placed
  useEffect(() => {
    markersRef.current.forEach((m) => m.setMap(null));
    markersRef.current = [];

    if (!map || !editingBoundary || !drawingActive) return;

    editingBoundary.forEach((c, i) => {
      const marker = new google.maps.Marker({
        position: { lat: c.latitude, lng: c.longitude },
        map,
        label: { text: String(i + 1), color: "white", fontSize: "11px", fontWeight: "bold" },
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 10,
          fillColor: BRASS,
          fillOpacity: 1,
          strokeColor: "white",
          strokeWeight: 2,
        },
      });
      markersRef.current.push(marker);
    });

    return () => {
      markersRef.current.forEach((m) => m.setMap(null));
    };
  }, [map, editingBoundary, drawingActive]);

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
      strokeColor: BRASS,
      strokeWeight: 3,
      fillColor: BRASS,
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
    // Close the loop visually if we have 3+ points
    if (editingBoundary.length >= 3) {
      path.push(path[0]);
    }

    const line = new google.maps.Polyline({
      path,
      strokeColor: BRASS,
      strokeWeight: 3,
      strokeOpacity: 0.8,
      map,
    });

    previewPolyRef.current = line;
    return () => { line.setMap(null); };
  }, [map, drawingActive, editingBoundary]);

  // Click-to-place handler during drawing mode
  useEffect(() => {
    if (!map || !drawingActive) return;

    const listener = map.addListener("click", (e: google.maps.MapMouseEvent) => {
      if (!e.latLng) return;
      const newPoint: Coordinate = {
        latitude: e.latLng.lat(),
        longitude: e.latLng.lng(),
      };
      onBoundaryChange([...(editingBoundary ?? []), newPoint]);
    });

    return () => {
      google.maps.event.removeListener(listener);
    };
  }, [map, drawingActive, editingBoundary, onBoundaryChange]);

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
                  className="px-3 py-1.5 rounded-lg text-xs font-medium shadow-lg bg-white text-navy hover:bg-gray-50 transition-colors disabled:opacity-30"
                >
                  Undo Point
                </button>
                <button
                  onClick={finishDrawing}
                  disabled={!editingBoundary || editingBoundary.length < 3}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium shadow-lg bg-brass text-navy-deep hover:bg-brass-deep transition-colors disabled:opacity-30"
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
                  className="px-3 py-1.5 rounded-lg text-xs font-medium shadow-lg bg-white text-navy hover:bg-gray-50 transition-colors"
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
        <div className="absolute top-3 left-3 z-10 bg-white/90 backdrop-blur rounded-lg shadow-lg px-3 py-2 text-xs text-navy max-w-[200px]">
          Click on the map to place boundary points. Place at least 3 points, then click <strong>Done</strong>.
        </div>
      )}
      {editingBoundary !== null && !drawingActive && editingBoundary.length >= 3 && (
        <div className="absolute top-3 left-3 z-10 bg-white/90 backdrop-blur rounded-lg shadow-lg px-3 py-2 text-xs text-navy max-w-[220px]">
          Drag the <strong>white squares</strong> on the boundary to adjust points. Drag midpoints to add new vertices.
        </div>
      )}
      <Map
        defaultCenter={defaultCenter ?? DEFAULT_CENTER}
        defaultZoom={16}
        mapTypeId="satellite"
        gestureHandling="greedy"
        disableDefaultUI={false}
        mapTypeControl={true}
        streetViewControl={false}
        fullscreenControl={true}
        zoomControl={true}
        style={{ width: "100%", height: "100%" }}
        onClick={() => {
          if (!drawingActive) onSelectLot(null);
        }}
      />
      <div
        ref={tooltipRef}
        style={{ display: "none" }}
        className="absolute z-20 pointer-events-none px-2 py-1 rounded bg-navy/90 text-white text-xs font-medium whitespace-nowrap shadow"
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
            Set <code className="bg-gray-200 px-1 rounded">QUARRY_GOOGLE_MAPS_API_KEY</code> to enable the map.
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
