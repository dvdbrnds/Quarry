import { useCallback, useEffect, useState } from "react";
import { api, Coordinate, Lot, LotClosure, LotZone, ParkingSpot } from "../api";
import { authHeaders, loadConfig } from "../auth";
import LotMap from "../components/LotMap";

const DESIGNATION_OPTIONS = [
  { code: "", label: "— None —" },
  { code: "FS", label: "FS — Faculty/Staff Only" },
  { code: "FSC", label: "FSC — Faculty/Staff + Commuter (time-split)" },
  { code: "C", label: "C — Commuter" },
  { code: "PR", label: "PR — Premium Resident" },
  { code: "RS", label: "RS — Resident & Seminary" },
  { code: "VPR", label: "VPR — Visitor / Premium Resident" },
];

const SPOT_TYPE_OPTIONS = [
  { value: "standard", label: "Standard", color: "bg-blue-500" },
  { value: "ev", label: "EV Charging", color: "bg-green-500" },
  { value: "handicap", label: "Handicap", color: "bg-indigo-500" },
  { value: "reserved", label: "Reserved", color: "bg-amber-500" },
  { value: "loading", label: "Loading Zone", color: "bg-gray-500" },
];

function spotTypeBadge(type: string) {
  const info = SPOT_TYPE_OPTIONS.find((t) => t.value === type);
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium text-white ${info?.color ?? "bg-gray-400"}`}>
      {info?.label ?? type}
    </span>
  );
}

/* ============================================================
   Lot Form (Create / Edit)
   ============================================================ */

function LotForm({
  initial,
  boundary,
  onBoundaryChange,
  onSave,
  onCancel,
}: {
  initial?: Lot;
  boundary: Coordinate[];
  onBoundaryChange: (coords: Coordinate[]) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [totalSpaces, setTotalSpaces] = useState(initial?.total_spaces ?? 0);
  const [handicapSpaces, setHandicapSpaces] = useState(initial?.handicap_spaces ?? 0);
  const [designationCode, setDesignationCode] = useState(initial?.designation_code ?? "");
  const [isSnowLot, setIsSnowLot] = useState(initial?.is_snow_lot ?? false);
  const [hasSheepDog, setHasSheepDog] = useState(initial?.has_sheepdog ?? false);
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [accessScheduleJson, setAccessScheduleJson] = useState(
    initial?.access_schedule && initial.access_schedule.length > 0
      ? JSON.stringify(initial.access_schedule, null, 2)
      : ""
  );
  const [scheduleError, setScheduleError] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setScheduleError("");
    const designLabel = DESIGNATION_OPTIONS.find(d => d.code === designationCode)?.label.split(" — ")[1] || "";
    let parsedSchedule = undefined;
    if (accessScheduleJson.trim()) {
      try {
        parsedSchedule = JSON.parse(accessScheduleJson);
      } catch {
        setScheduleError("Invalid JSON in access schedule");
        setSaving(false);
        return;
      }
    }
    try {
      const data = {
        name,
        boundary,
        total_spaces: totalSpaces,
        handicap_spaces: handicapSpaces,
        designation_code: designationCode,
        designation_label: designLabel,
        is_snow_lot: isSnowLot,
        has_sheepdog: hasSheepDog,
        notes: notes || null,
        ...(parsedSchedule !== undefined ? { access_schedule: parsedSchedule } : {}),
      };
      if (initial) {
        await api.lots.update(initial.id, data);
      } else {
        await api.lots.create(data);
      }
      onSave();
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="p-4 border-t border-gray-200 bg-gray-50 space-y-3 overflow-y-auto max-h-[50vh]">
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Lot Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} required
          placeholder="e.g. Lot A"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Designation</label>
        <select value={designationCode} onChange={(e) => setDesignationCode(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none">
          {DESIGNATION_OPTIONS.map(d => <option key={d.code} value={d.code}>{d.label}</option>)}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">Total Spaces</label>
          <input type="number" value={totalSpaces} onChange={(e) => setTotalSpaces(Number(e.target.value))}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">HC Spaces</label>
          <input type="number" value={handicapSpaces} onChange={(e) => setHandicapSpaces(Number(e.target.value))}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
        </div>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={isSnowLot} onChange={(e) => setIsSnowLot(e.target.checked)}
          className="rounded border-gray-300 text-brass focus:ring-brass" />
        Snow lot (prohibited 11pm-7am during snow regulations)
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={hasSheepDog} onChange={(e) => setHasSheepDog(e.target.checked)}
          className="rounded border-gray-300 text-amber-500 focus:ring-amber-500" />
        SheepDog occupancy monitoring
      </label>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Notes</label>
        <input value={notes} onChange={(e) => setNotes(e.target.value)}
          placeholder="EV charging, flood risk, etc."
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">
          Access Schedule (JSON)
          <span className="ml-1 font-normal opacity-60">optional</span>
        </label>
        <textarea
          value={accessScheduleJson}
          onChange={(e) => { setAccessScheduleJson(e.target.value); setScheduleError(""); }}
          rows={4}
          placeholder={'[\n  {\n    "season": "fall_spring",\n    "label": "Fall/Spring",\n    "rules": [{"start": "07:00", "end": "22:00", "days": ["Mon","Tue","Wed","Thu","Fri"], "allowed_permit_types": ["FS"], "label": "Weekday"}]\n  }\n]'}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-brass focus:outline-none resize-y"
        />
        {scheduleError && <p className="text-xs text-signal-red mt-1">{scheduleError}</p>}
        <p className="text-xs text-ink-mute mt-1">
          Array of season schedules. Each entry: <code className="bg-gray-100 px-1 rounded">season</code>, <code className="bg-gray-100 px-1 rounded">label</code>, <code className="bg-gray-100 px-1 rounded">rules[]</code>
        </p>
      </div>
      <p className="text-xs text-ink-mute">
        {boundary.length === 0
          ? 'Click "Draw Boundary" on the map, then click to place points. Double-click to finish.'
          : `${boundary.length} points — drag vertices on the map to adjust.`}
      </p>
      <div className="flex gap-2">
        <button type="submit" disabled={saving || boundary.length < 3}
          className="flex-1 px-3 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors disabled:opacity-50">
          {saving ? "Saving..." : initial ? "Update" : "Create"}
        </button>
        <button type="button" onClick={onCancel}
          className="px-3 py-2 text-sm text-ink-mute hover:text-ink">Cancel</button>
      </div>
    </form>
  );
}

/* ============================================================
   Zone Form + Panel (unchanged)
   ============================================================ */

const ZONE_TYPE_OPTIONS = [
  { value: "disability", label: "Disability" },
  { value: "fire_lane", label: "Fire Lane" },
  { value: "visitor", label: "Visitor" },
  { value: "admissions_visitor", label: "Admissions Visitor (Premium)" },
  { value: "loading", label: "Loading Zone" },
  { value: "ev_charging", label: "EV Charging" },
  { value: "reserved_tenant", label: "Reserved Tenant" },
];

type ZoneFormState = { zone_type: string; label: string; space_count: number; fine_override: string; is_premium: boolean; notes: string };
const EMPTY_ZONE_FORM: ZoneFormState = { zone_type: "disability", label: "", space_count: 0, fine_override: "", is_premium: false, notes: "" };

function ZoneForm({ initial, onSubmit, onCancel }: {
  initial?: ZoneFormState;
  onSubmit: (data: ZoneFormState) => Promise<void>;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<ZoneFormState>(initial ?? EMPTY_ZONE_FORM);
  const [saving, setSaving] = useState(false);
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try { await onSubmit(form); } finally { setSaving(false); }
  }
  return (
    <form onSubmit={handleSubmit} className="mt-2 space-y-2 bg-brass/5 rounded-lg p-2">
      <select value={form.zone_type} onChange={(e) => setForm({ ...form, zone_type: e.target.value })}
        className="w-full border border-gray-300 rounded px-2 py-1 text-xs">
        {ZONE_TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })}
        placeholder="Label (optional)" className="w-full border border-gray-300 rounded px-2 py-1 text-xs" />
      <div className="flex gap-2">
        <input type="number" value={form.space_count} onChange={(e) => setForm({ ...form, space_count: Number(e.target.value) })}
          placeholder="# spaces" className="flex-1 border border-gray-300 rounded px-2 py-1 text-xs" />
        <input value={form.fine_override} onChange={(e) => setForm({ ...form, fine_override: e.target.value })}
          placeholder="Fine $" className="flex-1 border border-gray-300 rounded px-2 py-1 text-xs" />
      </div>
      <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
        placeholder="Notes" className="w-full border border-gray-300 rounded px-2 py-1 text-xs" />
      <label className="flex items-center gap-1 text-xs">
        <input type="checkbox" checked={form.is_premium} onChange={(e) => setForm({ ...form, is_premium: e.target.checked })} />
        Premium
      </label>
      <div className="flex gap-2">
        <button type="submit" disabled={saving} className="px-2 py-1 bg-brass text-navy-deep text-xs rounded disabled:opacity-50">
          {saving ? "..." : initial ? "Update" : "Add"}
        </button>
        <button type="button" onClick={onCancel} className="px-2 py-1 text-xs text-ink-mute">Cancel</button>
      </div>
    </form>
  );
}

function ZonePanel({ lotId }: { lotId: string }) {
  const [zones, setZones] = useState<LotZone[]>([]);
  const [adding, setAdding] = useState(false);
  const [editingZoneId, setEditingZoneId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setZones(await api.lots.zones.list(lotId));
  }, [lotId]);

  useEffect(() => { load(); }, [load]);

  async function handleAdd(data: ZoneFormState) {
    await api.lots.zones.create(lotId, {
      zone_type: data.zone_type,
      label: data.label || data.zone_type.replace(/_/g, " "),
      space_count: data.space_count,
      fine_override: data.fine_override || null,
      is_premium: data.is_premium,
      notes: data.notes || null,
    });
    setAdding(false);
    load();
  }

  async function handleUpdate(zoneId: string, data: ZoneFormState) {
    await api.lots.zones.update(lotId, zoneId, {
      zone_type: data.zone_type,
      label: data.label || data.zone_type.replace(/_/g, " "),
      space_count: data.space_count,
      fine_override: data.fine_override || null,
      is_premium: data.is_premium,
      notes: data.notes || null,
    });
    setEditingZoneId(null);
    load();
  }

  async function handleDelete(zoneId: string) {
    if (!confirm("Remove this zone?")) return;
    await api.lots.zones.delete(lotId, zoneId);
    load();
  }

  return (
    <div className="p-4 border-t border-gray-200">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-bold uppercase text-ink-mute tracking-wide">Zones</h4>
        <button onClick={() => setAdding(true)} className="text-xs text-brass-deep hover:text-brass">+ Add</button>
      </div>
      {zones.map(z => editingZoneId === z.id ? (
        <ZoneForm
          key={z.id}
          initial={{ zone_type: z.zone_type, label: z.label, space_count: z.space_count, fine_override: z.fine_override ?? "", is_premium: z.is_premium, notes: z.notes ?? "" }}
          onSubmit={(data) => handleUpdate(z.id, data)}
          onCancel={() => setEditingZoneId(null)}
        />
      ) : (
        <div key={z.id} className="flex items-center justify-between text-xs py-1">
          <span className="capitalize">
            {z.zone_type.replace(/_/g, " ")} ({z.space_count})
            {z.is_premium && <span className="ml-1 text-[10px] bg-brass/20 text-brass-deep px-1 rounded">Premium</span>}
            {z.fine_override && <span className="ml-1 text-ink-mute">${z.fine_override}</span>}
          </span>
          <div className="flex gap-2">
            <button onClick={() => setEditingZoneId(z.id)} className="text-brass-deep hover:text-brass">Edit</button>
            <button onClick={() => handleDelete(z.id)} className="text-signal-red/60 hover:text-signal-red">Remove</button>
          </div>
        </div>
      ))}
      {zones.length === 0 && !adding && (
        <p className="text-xs text-ink-mute">No special zones defined</p>
      )}
      {adding && <ZoneForm onSubmit={handleAdd} onCancel={() => setAdding(false)} />}
    </div>
  );
}

/* ============================================================
   Spot Detail Editor (shown when a spot is selected on the map)
   ============================================================ */

function SpotDetail({
  spot,
  lotId,
  onSaved,
  onClose,
  onStartPlacing,
  placingSpot,
}: {
  spot: ParkingSpot;
  lotId: string;
  onSaved: () => void;
  onClose: () => void;
  onStartPlacing: () => void;
  placingSpot: boolean;
}) {
  const [number, setNumber] = useState(spot.number);
  const [label, setLabel] = useState(spot.label ?? "");
  const [spotType, setSpotType] = useState(spot.spot_type);
  const [sensorId, setSensorId] = useState(spot.sensor_id ?? "");
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await api.lots.spots.update(lotId, spot.id, {
        number,
        label: label || null,
        spot_type: spotType,
        sensor_id: sensorId || null,
      });
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!confirm(`Remove spot #${spot.number}?`)) return;
    await api.lots.spots.delete(lotId, spot.id);
    onSaved();
    onClose();
  }

  return (
    <div className="p-4 border-t border-amber-300 bg-amber-50/50 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-bold uppercase text-amber-700 tracking-wide">Edit Spot #{spot.number}</h4>
        <button onClick={onClose} className="text-xs text-ink-mute hover:text-ink">Back to list</button>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-[10px] font-medium text-ink-mute mb-0.5">Spot Number</label>
          <input type="number" value={number} onChange={(e) => setNumber(Number(e.target.value))}
            className="w-full border border-gray-300 rounded px-2 py-1 text-xs" />
        </div>
        <div>
          <label className="block text-[10px] font-medium text-ink-mute mb-0.5">Label</label>
          <input value={label} onChange={(e) => setLabel(e.target.value)}
            placeholder="Optional label"
            className="w-full border border-gray-300 rounded px-2 py-1 text-xs" />
        </div>
      </div>

      <div>
        <label className="block text-[10px] font-medium text-ink-mute mb-0.5">Spot Type</label>
        <select value={spotType} onChange={(e) => setSpotType(e.target.value)}
          className="w-full border border-gray-300 rounded px-2 py-1 text-xs">
          {SPOT_TYPE_OPTIONS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
      </div>

      <div>
        <label className="block text-[10px] font-medium text-ink-mute mb-0.5">LoRaWAN Sensor ID</label>
        <input value={sensorId} onChange={(e) => setSensorId(e.target.value)}
          placeholder="e.g. A-001"
          className="w-full border border-gray-300 rounded px-2 py-1 text-xs font-mono" />
      </div>

      <div>
        <label className="block text-[10px] font-medium text-ink-mute mb-0.5">Location</label>
        {spot.latitude != null && spot.longitude != null ? (
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-ink-mute">{spot.latitude.toFixed(6)}, {spot.longitude.toFixed(6)}</span>
            <button onClick={onStartPlacing} className="text-xs text-amber-600 hover:text-amber-700">
              {placingSpot ? "Click the map..." : "Reposition"}
            </button>
          </div>
        ) : (
          <button onClick={onStartPlacing} className={`text-xs px-2 py-1 rounded ${
            placingSpot
              ? "bg-amber-200 text-amber-800 animate-pulse"
              : "bg-amber-100 text-amber-700 hover:bg-amber-200"
          }`}>
            {placingSpot ? "Click the map to place..." : "Place on Map"}
          </button>
        )}
      </div>

      <div className="flex gap-2 pt-1">
        <button onClick={handleSave} disabled={saving}
          className="px-3 py-1.5 bg-amber-500 text-white text-xs rounded font-medium disabled:opacity-50">
          {saving ? "Saving..." : "Save Changes"}
        </button>
        <button onClick={handleDelete} className="px-3 py-1.5 text-xs text-signal-red/70 hover:text-signal-red">
          Delete Spot
        </button>
      </div>
    </div>
  );
}

/* ============================================================
   Spot Panel (list view + add form)
   ============================================================ */

function SpotPanel({
  lotId,
  spots,
  selectedSpotId,
  onSelectSpot,
  onSpotsChanged,
  onStartPlacing,
  placingSpot,
  batchPlacing,
  batchNextNumber,
  onStartBatch,
  onStopBatch,
  spotsVisible,
  onToggleVisible,
}: {
  lotId: string;
  spots: ParkingSpot[];
  selectedSpotId: string | null;
  onSelectSpot: (id: string | null) => void;
  onSpotsChanged: () => void;
  onStartPlacing: () => void;
  placingSpot: boolean;
  batchPlacing: boolean;
  batchNextNumber: number;
  onStartBatch: () => void;
  onStopBatch: () => void;
  spotsVisible: boolean;
  onToggleVisible: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const [newNumber, setNewNumber] = useState(spots.length > 0 ? Math.max(...spots.map(s => s.number)) + 1 : 1);
  const [newLabel, setNewLabel] = useState("");
  const [newSpotType, setNewSpotType] = useState("standard");
  const [newSensorId, setNewSensorId] = useState("");
  const [saving, setSaving] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);

  const selectedSpot = spots.find(s => s.id === selectedSpotId);

  if (selectedSpot && !batchPlacing) {
    return (
      <SpotDetail
        spot={selectedSpot}
        lotId={lotId}
        onSaved={onSpotsChanged}
        onClose={() => onSelectSpot(null)}
        onStartPlacing={onStartPlacing}
        placingSpot={placingSpot}
      />
    );
  }

  function toggleCheck(id: string) {
    setChecked(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (checked.size === spots.length) {
      setChecked(new Set());
    } else {
      setChecked(new Set(spots.map(s => s.id)));
    }
  }

  async function handleBulkDelete() {
    if (checked.size === 0) return;
    if (!confirm(`Delete ${checked.size} spot(s)?`)) return;
    setDeleting(true);
    try {
      await api.lots.spots.bulkDelete(lotId, Array.from(checked));
      setChecked(new Set());
      onSpotsChanged();
    } finally {
      setDeleting(false);
    }
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.lots.spots.create(lotId, {
        number: newNumber,
        label: newLabel || null,
        spot_type: newSpotType,
        sensor_id: newSensorId || null,
      });
      setAdding(false);
      setNewLabel("");
      setNewSensorId("");
      setNewSpotType("standard");
      onSpotsChanged();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="p-4 border-t border-amber-200 bg-amber-50/30">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-bold uppercase text-amber-700 tracking-wide flex items-center gap-1.5">
          SheepDog Spots
          <button
            onClick={onToggleVisible}
            title={spotsVisible ? "Hide spots on map" : "Show spots on map"}
            className={`inline-flex items-center justify-center w-5 h-5 rounded transition-colors ${
              spotsVisible
                ? "bg-amber-200 text-amber-700 hover:bg-amber-300"
                : "bg-gray-200 text-gray-400 hover:bg-gray-300"
            }`}
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3 h-3">
              {spotsVisible ? (
                <path d="M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5z" />
              ) : (
                <path fillRule="evenodd" d="M3.28 2.22a.75.75 0 00-1.06 1.06l14.5 14.5a.75.75 0 101.06-1.06l-1.745-1.745a10.029 10.029 0 003.3-4.38 1.651 1.651 0 000-1.185A10.004 10.004 0 009.999 3a9.956 9.956 0 00-4.744 1.194L3.28 2.22zM7.752 6.69l1.092 1.092a2.5 2.5 0 013.374 3.373l1.092 1.092a4 4 0 00-5.558-5.558z" clipRule="evenodd" />
              )}
              {spotsVisible && (
                <path fillRule="evenodd" d="M10 3C5.523 3 1.73 6.068.458 10.003a1.651 1.651 0 000 1.185A10.004 10.004 0 0010 17c4.478 0 8.27-3.068 9.542-7.003a1.651 1.651 0 000-1.185A10.004 10.004 0 0010 3zm0 11a4 4 0 100-8 4 4 0 000 8z" clipRule="evenodd" />
              )}
            </svg>
          </button>
        </h4>
        <div className="flex items-center gap-2">
          {batchPlacing ? (
            <button onClick={onStopBatch}
              className="text-xs text-emerald-700 bg-emerald-100 hover:bg-emerald-200 px-2 py-0.5 rounded font-medium">
              Done Placing
            </button>
          ) : (
            <>
              <button onClick={onStartBatch}
                className="text-xs text-amber-600 hover:text-amber-700">Place Spots</button>
              <button onClick={() => { setAdding(true); setNewNumber(spots.length > 0 ? Math.max(...spots.map(s => s.number)) + 1 : 1); }}
                className="text-xs text-amber-600 hover:text-amber-700">+ Add</button>
            </>
          )}
        </div>
      </div>
      {batchPlacing && (
        <div className="mb-2 px-2 py-1.5 bg-amber-100 border border-amber-300 rounded text-xs text-amber-800">
          Click on the map to place spots. Next spot: <strong>#{batchNextNumber}</strong>
        </div>
      )}
      {spots.length > 0 && (
        <div className="flex items-center justify-between mb-1.5 pb-1.5 border-b border-amber-200/60">
          <label className="flex items-center gap-1.5 text-[10px] text-ink-mute cursor-pointer select-none">
            <input
              type="checkbox"
              checked={checked.size === spots.length && spots.length > 0}
              onChange={toggleAll}
              className="rounded border-gray-300 text-amber-500 focus:ring-amber-500 h-3 w-3"
            />
            {checked.size > 0 ? `${checked.size} selected` : "Select all"}
          </label>
          {checked.size > 0 && (
            <button
              onClick={handleBulkDelete}
              disabled={deleting}
              className="text-[10px] text-signal-red hover:text-red-700 font-medium disabled:opacity-50"
            >
              {deleting ? "Deleting..." : `Delete ${checked.size}`}
            </button>
          )}
        </div>
      )}
      {spots.map(s => (
        <div
          key={s.id}
          className={`flex items-center text-xs py-1.5 px-1 rounded cursor-pointer transition-colors ${
            s.id === selectedSpotId ? "bg-amber-100" : "hover:bg-amber-50"
          }`}
        >
          <input
            type="checkbox"
            checked={checked.has(s.id)}
            onChange={(e) => { e.stopPropagation(); toggleCheck(s.id); }}
            className="rounded border-gray-300 text-amber-500 focus:ring-amber-500 h-3 w-3 mr-1.5 flex-shrink-0"
          />
          <span
            className="flex items-center gap-1.5 flex-1 min-w-0"
            onClick={() => onSelectSpot(s.id)}
          >
            <span className="font-mono font-bold text-amber-700">#{s.number}</span>
            {spotTypeBadge(s.spot_type)}
            {s.label && <span className="text-ink-mute truncate">{s.label}</span>}
            {s.sensor_id && <span className="font-mono bg-amber-100 text-amber-700 px-1 rounded text-[10px]">{s.sensor_id}</span>}
          </span>
          {s.latitude == null && (
            <span className="text-[10px] text-ink-mute italic flex-shrink-0">no location</span>
          )}
        </div>
      ))}
      {spots.length === 0 && !adding && !batchPlacing && (
        <p className="text-xs text-ink-mute">No spots assigned. Use Place Spots or + Add.</p>
      )}
      {adding && (
        <form onSubmit={handleAdd} className="mt-2 space-y-2 bg-amber-50 rounded-lg p-2">
          <div className="flex gap-2">
            <input type="number" value={newNumber} onChange={(e) => setNewNumber(Number(e.target.value))}
              placeholder="#" className="w-16 border border-gray-300 rounded px-2 py-1 text-xs" />
            <input value={newLabel} onChange={(e) => setNewLabel(e.target.value)}
              placeholder="Label (optional)" className="flex-1 border border-gray-300 rounded px-2 py-1 text-xs" />
          </div>
          <select value={newSpotType} onChange={(e) => setNewSpotType(e.target.value)}
            className="w-full border border-gray-300 rounded px-2 py-1 text-xs">
            {SPOT_TYPE_OPTIONS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
          <input value={newSensorId} onChange={(e) => setNewSensorId(e.target.value)}
            placeholder="Sensor ID (e.g. A-001)" className="w-full border border-gray-300 rounded px-2 py-1 text-xs font-mono" />
          <p className="text-[10px] text-ink-mute">After adding, select the spot and click "Place on Map" to set its location.</p>
          <div className="flex gap-2">
            <button type="submit" disabled={saving} className="px-2 py-1 bg-amber-500 text-white text-xs rounded disabled:opacity-50">
              {saving ? "..." : "Add"}
            </button>
            <button type="button" onClick={() => setAdding(false)} className="px-2 py-1 text-xs text-ink-mute">Cancel</button>
          </div>
        </form>
      )}
    </div>
  );
}

/* ============================================================
   Close Lot Modal
   ============================================================ */

function CloseLotModal({
  lot,
  onClose,
  onDone,
}: {
  lot: Lot;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const [reopensAt, setReopensAt] = useState("");
  const [extraRecipients, setExtraRecipients] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const recipients = extraRecipients
        .split(",")
        .map((e) => e.trim())
        .filter(Boolean);
      await api.lots.close(lot.id, {
        reason,
        reopens_at: reopensAt ? new Date(reopensAt).toISOString() : undefined,
        recipients,
      });
      onDone();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4"
      >
        <h3 className="text-lg font-bold text-signal-red">
          Close {lot.name}
        </h3>
        <p className="text-sm text-ink-mute">
          This will immediately close the lot and send notification emails to
          all permit holders assigned to this lot plus any additional recipients
          below.
        </p>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">
            Reason
          </label>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Snow removal, event, maintenance..."
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">
            Reopens At (optional)
          </label>
          <input
            type="datetime-local"
            value={reopensAt}
            onChange={(e) => setReopensAt(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-mute mb-1">
            Additional Recipients (comma-separated emails)
          </label>
          <input
            value={extraRecipients}
            onChange={(e) => setExtraRecipients(e.target.value)}
            placeholder="dean@campus.edu, security@campus.edu"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
          />
        </div>
        <div className="flex gap-2 pt-2">
          <button
            type="submit"
            disabled={submitting}
            className="flex-1 px-4 py-2 bg-signal-red text-white font-medium rounded-lg text-sm hover:bg-red-700 transition-colors disabled:opacity-50"
          >
            {submitting ? "Closing..." : "Close Lot Now"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm text-ink-mute hover:text-ink"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}

/* ============================================================
   Main Lots Component
   ============================================================ */

export default function Lots() {
  const [lots, setLots] = useState<Lot[]>([]);
  const [selectedLotId, setSelectedLotId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Lot | null>(null);
  const [creating, setCreating] = useState(false);
  const [editingBoundary, setEditingBoundary] = useState<Coordinate[] | null>(null);
  const [mapsApiKey, setMapsApiKey] = useState("");
  const [campusCenter, setCampusCenter] = useState({ lat: 40.6265, lng: -75.3707 });
  const [closingLot, setClosingLot] = useState<Lot | null>(null);
  const [deletingLot, setDeletingLot] = useState<Lot | null>(null);

  // SheepDog spot state (lifted to parent so both map + panel can share)
  const [spots, setSpots] = useState<ParkingSpot[]>([]);
  const [selectedSpotId, setSelectedSpotId] = useState<string | null>(null);
  const [placingSpot, setPlacingSpot] = useState(false);
  const [batchPlacing, setBatchPlacing] = useState(false);
  const [batchNextNumber, setBatchNextNumber] = useState(1);
  const [spotsVisible, setSpotsVisible] = useState(true);

  const selectedLot = lots.find(l => l.id === selectedLotId);
  const isSheepDogLot = selectedLot?.has_sheepdog ?? false;

  const load = useCallback(async () => {
    setLots(await api.lots.list());
  }, []);

  const loadSpots = useCallback(async () => {
    if (!selectedLotId || !isSheepDogLot) {
      setSpots([]);
      return;
    }
    try {
      setSpots(await api.lots.spots.list(selectedLotId));
    } catch {
      setSpots([]);
    }
  }, [selectedLotId, isSheepDogLot]);

  useEffect(() => {
    load();
    loadConfig().then((cfg) => {
      setMapsApiKey(cfg.google_maps_api_key || "");
      if (cfg.campus_lat && cfg.campus_lng) {
        setCampusCenter({ lat: cfg.campus_lat, lng: cfg.campus_lng });
      }
    });
  }, [load]);

  useEffect(() => {
    loadSpots();
    setSelectedSpotId(null);
    setPlacingSpot(false);
    setBatchPlacing(false);
  }, [loadSpots]);

  function handleSelectLot(id: string | null) {
    if (creating || editing) return;
    setSelectedLotId(id === selectedLotId ? null : id);
  }

  function startCreate() {
    setCreating(true);
    setEditing(null);
    setSelectedLotId(null);
    setEditingBoundary([]);
  }

  function startEdit(lot: Lot) {
    setEditing(lot);
    setCreating(false);
    setSelectedLotId(lot.id);
    setEditingBoundary([...lot.boundary]);
  }

  function cancelEdit() {
    setCreating(false);
    setEditing(null);
    setEditingBoundary(null);
  }

  function handleSaved() {
    cancelEdit();
    load();
  }

  async function confirmDelete() {
    if (!deletingLot) return;
    await api.lots.delete(deletingLot.id);
    if (selectedLotId === deletingLot.id) setSelectedLotId(null);
    setDeletingLot(null);
    load();
  }

  async function handleReopen(lot: Lot) {
    if (!confirm(`Reopen ${lot.name}?`)) return;
    await api.lots.reopen(lot.id);
    load();
  }

  function handlePlaceSpot(lat: number, lng: number) {
    if (!selectedLotId) return;

    // Batch placement mode: create a new spot on each click
    if (batchPlacing) {
      api.lots.spots.create(selectedLotId, {
        number: batchNextNumber,
        spot_type: "standard",
        latitude: lat,
        longitude: lng,
      }).then(() => {
        setBatchNextNumber(n => n + 1);
        loadSpots();
      });
      return;
    }

    // Single reposition mode
    if (!selectedSpotId) return;
    api.lots.spots.update(selectedLotId, selectedSpotId, {
      latitude: lat,
      longitude: lng,
    }).then(() => {
      setPlacingSpot(false);
      loadSpots();
    });
  }

  function startBatchPlacing() {
    const nextNum = spots.length > 0 ? Math.max(...spots.map(s => s.number)) + 1 : 1;
    setBatchNextNumber(nextNum);
    setBatchPlacing(true);
    setPlacingSpot(true);
    setSelectedSpotId(null);
  }

  function stopBatchPlacing() {
    setBatchPlacing(false);
    setPlacingSpot(false);
  }

  const isEditing = creating || editing !== null;

  return (
    <div className="flex gap-6 h-[calc(100vh-7rem)]">
      {/* Side panel */}
      <div className="w-80 flex-shrink-0 flex flex-col bg-white rounded-xl shadow overflow-hidden">
        <div className="p-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-bold">Parking Lots</h2>
          <button
            onClick={startCreate}
            disabled={isEditing}
            className="px-3 py-1.5 bg-brass text-navy-deep font-medium rounded-lg text-xs hover:bg-brass-deep transition-colors disabled:opacity-50"
          >
            + New Lot
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {lots.length === 0 && (
            <div className="text-center py-12 text-ink-mute text-sm px-4">
              No lots yet. Click "+ New Lot" then draw a boundary on the map.
            </div>
          )}
          {lots.map((lot) => (
            <div key={lot.id}>
              <div
                onClick={() => handleSelectLot(lot.id)}
                className={`p-4 border-b border-gray-100 cursor-pointer transition-colors ${
                  lot.id === selectedLotId
                    ? "bg-brass/10 border-l-4 border-l-brass"
                    : "hover:bg-gray-50"
                }`}
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-sm">{lot.name}</h3>
                      {lot.has_sheepdog && (
                        <span className="inline-block bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded text-[10px] font-bold">
                          SD
                        </span>
                      )}
                      {lot.is_closed && (
                        <span className="inline-block bg-signal-red/10 text-signal-red px-1.5 py-0.5 rounded text-[10px] font-bold uppercase">
                          Closed
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-ink-mute mt-0.5">
                      {lot.designation_code && (
                        <span className="inline-block bg-navy/10 text-navy px-1.5 py-0.5 rounded text-[10px] font-bold mr-1">
                          {lot.designation_code}
                        </span>
                      )}
                      {lot.boundary.length >= 3
                        ? lot.total_spaces > 0 ? `${lot.total_spaces} spaces` : "Boundary set"
                        : "No boundary defined"}
                      {lot.is_snow_lot && " · Snow"}
                    </p>
                  </div>
                  {!isEditing && (
                    <div className="flex gap-2 ml-2 flex-shrink-0">
                      {lot.is_closed ? (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleReopen(lot); }}
                          className="text-emerald-600 hover:text-emerald-700 text-xs font-medium"
                        >Reopen</button>
                      ) : (
                        <button
                          onClick={(e) => { e.stopPropagation(); setClosingLot(lot); }}
                          className="text-signal-red/60 hover:text-signal-red text-xs"
                        >Close</button>
                      )}
                      <button
                        onClick={(e) => { e.stopPropagation(); startEdit(lot); }}
                        className="text-brass-deep hover:text-brass text-xs"
                      >Edit</button>
                      <button
                        onClick={(e) => { e.stopPropagation(); setDeletingLot(lot); }}
                        className="text-signal-red/60 hover:text-signal-red text-xs"
                      >Delete</button>
                    </div>
                  )}
                </div>
              </div>
              {lot.id === selectedLotId && !isEditing && (
                <>
                  <ZonePanel lotId={lot.id} />
                  {lot.has_sheepdog && (
                    <SpotPanel
                      lotId={lot.id}
                      spots={spots}
                      selectedSpotId={selectedSpotId}
                      onSelectSpot={setSelectedSpotId}
                      onSpotsChanged={loadSpots}
                      onStartPlacing={() => setPlacingSpot(true)}
                      placingSpot={placingSpot}
                      batchPlacing={batchPlacing}
                      batchNextNumber={batchNextNumber}
                      onStartBatch={startBatchPlacing}
                      onStopBatch={stopBatchPlacing}
                      spotsVisible={spotsVisible}
                      onToggleVisible={() => setSpotsVisible(v => !v)}
                    />
                  )}
                </>
              )}
            </div>
          ))}
        </div>

        {isEditing && (
          <LotForm
            initial={editing ?? undefined}
            boundary={editingBoundary ?? []}
            onBoundaryChange={setEditingBoundary}
            onSave={handleSaved}
            onCancel={cancelEdit}
          />
        )}
      </div>

      {/* Map */}
      <div className="flex-1 rounded-xl shadow overflow-hidden">
        <LotMap
          apiKey={mapsApiKey}
          lots={lots}
          selectedLotId={selectedLotId}
          onSelectLot={handleSelectLot}
          editingBoundary={editingBoundary}
          onBoundaryChange={setEditingBoundary}
          defaultCenter={campusCenter}
          spots={isSheepDogLot && spotsVisible ? spots : []}
          selectedSpotId={selectedSpotId}
          onSelectSpot={setSelectedSpotId}
          placingSpot={placingSpot}
          onPlaceSpot={handlePlaceSpot}
        />
      </div>

      {closingLot && (
        <CloseLotModal
          lot={closingLot}
          onClose={() => setClosingLot(null)}
          onDone={() => {
            setClosingLot(null);
            load();
          }}
        />
      )}

      {deletingLot && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
            <h3 className="text-lg font-bold text-signal-red">Delete {deletingLot.name}?</h3>
            <p className="text-sm text-ink-mute">
              This will permanently remove <strong>{deletingLot.name}</strong> and
              all its zones. This action cannot be undone.
            </p>
            <div className="flex gap-2 pt-2">
              <button
                onClick={confirmDelete}
                className="flex-1 px-4 py-2 bg-signal-red text-white font-medium rounded-lg text-sm hover:bg-red-700 transition-colors"
              >
                Delete Lot
              </button>
              <button
                onClick={() => setDeletingLot(null)}
                className="px-4 py-2 text-sm text-ink-mute hover:text-ink"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
