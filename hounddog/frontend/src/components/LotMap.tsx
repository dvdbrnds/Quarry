import {
  APIProvider,
  Map,
  useMap,
  useMapsLibrary,
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
  const drawingLib = useMapsLibrary("drawing");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const drawingManagerRef = useRef<any>(null);
  const polygonsRef = useRef<google.maps.Polygon[]>([]);
  const editPolygonRef = useRef<google.maps.Polygon | null>(null);
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
        strokeColor: color,
        strokeOpacity: isSelected ? 1 : 0.7,
        strokeWeight: isSelected ? 3 : 2,
        fillColor: color,
        fillOpacity: isSelected ? 0.35 : 0.15,
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
    });

    return () => {
      polygonsRef.current.forEach((p) => p.setMap(null));
    };
  }, [map, lots, selectedLotId, editingBoundary, onSelectLot]);

  // Render editable polygon for the boundary being created/edited
  useEffect(() => {
    if (!map) return;

    if (editPolygonRef.current) {
      editPolygonRef.current.setMap(null);
      editPolygonRef.current = null;
    }

    if (!editingBoundary || editingBoundary.length < 3) return;

    const poly = new google.maps.Polygon({
      paths: editingBoundary.map((c) => ({ lat: c.latitude, lng: c.longitude })),
      strokeColor: "#b8860b",
      strokeWeight: 3,
      fillColor: "#b8860b",
      fillOpacity: 0.3,
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
  }, [map, editingBoundary, syncEditPolygon]);

  // Drawing manager for creating new polygons
  useEffect(() => {
    if (!map || !drawingLib) return;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const DM = (google.maps.drawing as any).DrawingManager;
    const dm = new DM({
      drawingMode: null,
      drawingControl: false,
      polygonOptions: {
        strokeColor: "#b8860b",
        strokeWeight: 3,
        fillColor: "#b8860b",
        fillOpacity: 0.3,
        editable: true,
      },
    });

    dm.setMap(map);
    drawingManagerRef.current = dm;

    dm.addListener("polygoncomplete", (polygon: google.maps.Polygon) => {
      const path = polygon.getPath();
      const coords: Coordinate[] = [];
      for (let i = 0; i < path.getLength(); i++) {
        const pt = path.getAt(i);
        coords.push({ latitude: pt.lat(), longitude: pt.lng() });
      }
      onBoundaryChange(coords);
      polygon.setMap(null);
      dm.setDrawingMode(null);
      setDrawingActive(false);
    });

    return () => {
      dm.setMap(null);
    };
  }, [map, drawingLib, onBoundaryChange]);

  const toggleDrawing = useCallback(() => {
    const dm = drawingManagerRef.current;
    if (!dm) return;

    if (drawingActive) {
      dm.setDrawingMode(null);
      setDrawingActive(false);
    } else {
      dm.setDrawingMode((google.maps.drawing as any).OverlayType.POLYGON);
      setDrawingActive(true);
    }
  }, [drawingActive]);

  const clearBoundary = useCallback(() => {
    onBoundaryChange([]);
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
            <button
              onClick={toggleDrawing}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium shadow-lg transition-colors ${
                drawingActive
                  ? "bg-signal-red text-white"
                  : "bg-white text-navy hover:bg-gray-50"
              }`}
            >
              {drawingActive ? "Cancel Drawing" : "Draw Boundary"}
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
      </div>
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
        onClick={() => onSelectLot(null)}
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
    <APIProvider
      apiKey={props.apiKey}
      libraries={["drawing"]}
    >
      <div className="w-full h-full relative rounded-xl overflow-hidden">
        <MapContent {...props} />
      </div>
    </APIProvider>
  );
}
