import {
  APIProvider,
  Map,
  useMap,
} from "@vis.gl/react-google-maps";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Coordinate, Lot } from "../api";

const MORAVIAN_CENTER = { lat: 40.6265, lng: -75.3707 };

interface LotMapProps {
  apiKey: string;
  lots: Lot[];
  selectedLotId: string | null;
  onSelectLot: (id: string | null) => void;
  editingBoundary: Coordinate[] | null;
  onBoundaryChange: (coords: Coordinate[]) => void;
}

function lotColor(index: number): string {
  const palette = [
    "#1e3a5f", "#b8860b", "#2e7d32", "#c62828",
    "#6a1b9a", "#00838f", "#ef6c00", "#4527a0",
  ];
  return palette[index % palette.length];
}

function MapContent({
  lots,
  selectedLotId,
  onSelectLot,
  editingBoundary,
  onBoundaryChange,
}: Omit<LotMapProps, "apiKey">) {
  const map = useMap();
  const polygonsRef = useRef<google.maps.Polygon[]>([]);
  const editPolygonRef = useRef<google.maps.Polygon | null>(null);
  const markersRef = useRef<google.maps.Marker[]>([]);
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

    lots.forEach((lot, idx) => {
      if (lot.boundary.length < 3) return;
      if (editingBoundary !== null && lot.id === selectedLotId) return;

      const color = lotColor(idx);
      const isSelected = lot.id === selectedLotId;

      const poly = new google.maps.Polygon({
        paths: lot.boundary.map((c) => ({ lat: c.latitude, lng: c.longitude })),
        strokeColor: isSelected ? "#4ade80" : color,
        strokeOpacity: isSelected ? 1 : 0.7,
        strokeWeight: isSelected ? 3 : 2,
        fillColor: isSelected ? "#4ade80" : color,
        fillOpacity: isSelected ? 0.25 : 0.15,
        map,
        clickable: true,
      });

      poly.addListener("click", () => onSelectLot(lot.id));

      const infoWindow = new google.maps.InfoWindow({
        content: `<div style="font-family:system-ui;padding:2px"><strong>${lot.name}</strong></div>`,
      });
      poly.addListener("mouseover", (e: google.maps.MapMouseEvent) => {
        if (e.latLng) infoWindow.setPosition(e.latLng);
        infoWindow.open(map);
      });
      poly.addListener("mouseout", () => infoWindow.close());

      polygonsRef.current.push(poly);

      if (isSelected) {
        const bounds = new google.maps.LatLngBounds();
        lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));
        map.fitBounds(bounds, 80);
      }
    });

    return () => {
      polygonsRef.current.forEach((p) => p.setMap(null));
    };
  }, [map, lots, selectedLotId, editingBoundary, onSelectLot]);

  // Center map on selected lot
  useEffect(() => {
    if (!map || !selectedLotId) return;
    const lot = lots.find((l) => l.id === selectedLotId);
    if (!lot || lot.boundary.length < 3) return;
    const bounds = new google.maps.LatLngBounds();
    lot.boundary.forEach((c) => bounds.extend({ lat: c.latitude, lng: c.longitude }));
    map.fitBounds(bounds, 80);
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
          fillColor: "#b8860b",
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
      strokeColor: "#4ade80",
      strokeWeight: 3,
      fillColor: "#4ade80",
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
      strokeColor: "#b8860b",
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
        defaultCenter={MORAVIAN_CENTER}
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
