import { useCallback, useEffect, useState } from "react";
import { api, Coordinate, Lot, LotClosure, LotZone } from "../api";
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
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    const designLabel = DESIGNATION_OPTIONS.find(d => d.code === designationCode)?.label.split(" — ")[1] || "";
    try {
      const data = {
        name,
        boundary,
        total_spaces: totalSpaces,
        handicap_spaces: handicapSpaces,
        designation_code: designationCode,
        designation_label: designLabel,
        is_snow_lot: isSnowLot,
        notes: notes || null,
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
      <div>
        <label className="block text-xs font-medium text-ink-mute mb-1">Notes</label>
        <input value={notes} onChange={(e) => setNotes(e.target.value)}
          placeholder="EV charging, flood risk, etc."
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
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

function ZonePanel({ lotId }: { lotId: string }) {
  const [zones, setZones] = useState<LotZone[]>([]);
  const [adding, setAdding] = useState(false);
  const [zoneType, setZoneType] = useState("disability");
  const [zoneLabel, setZoneLabel] = useState("");
  const [spaceCount, setSpaceCount] = useState(0);

  const load = useCallback(async () => {
    setZones(await api.lots.zones.list(lotId));
  }, [lotId]);

  useEffect(() => { load(); }, [load]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    await api.lots.zones.create(lotId, {
      zone_type: zoneType,
      label: zoneLabel || zoneType.replace(/_/g, " "),
      space_count: spaceCount,
    });
    setAdding(false);
    setZoneLabel("");
    setSpaceCount(0);
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
      {zones.map(z => (
        <div key={z.id} className="flex items-center justify-between text-xs py-1">
          <span className="capitalize">{z.zone_type.replace(/_/g, " ")} ({z.space_count})</span>
          <button onClick={() => handleDelete(z.id)} className="text-signal-red/60 hover:text-signal-red">Remove</button>
        </div>
      ))}
      {zones.length === 0 && !adding && (
        <p className="text-xs text-ink-mute">No special zones defined</p>
      )}
      {adding && (
        <form onSubmit={handleAdd} className="mt-2 space-y-2">
          <select value={zoneType} onChange={(e) => setZoneType(e.target.value)}
            className="w-full border border-gray-300 rounded px-2 py-1 text-xs">
            <option value="disability">Disability</option>
            <option value="fire_lane">Fire Lane</option>
            <option value="visitor">Visitor</option>
            <option value="admissions_visitor">Admissions Visitor (Premium)</option>
            <option value="loading">Loading Zone</option>
            <option value="ev_charging">EV Charging</option>
            <option value="reserved_tenant">Reserved Tenant</option>
          </select>
          <input type="number" value={spaceCount} onChange={(e) => setSpaceCount(Number(e.target.value))}
            placeholder="# spaces" className="w-full border border-gray-300 rounded px-2 py-1 text-xs" />
          <div className="flex gap-2">
            <button type="submit" className="px-2 py-1 bg-brass text-navy-deep text-xs rounded">Add</button>
            <button type="button" onClick={() => setAdding(false)} className="px-2 py-1 text-xs text-ink-mute">Cancel</button>
          </div>
        </form>
      )}
    </div>
  );
}

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

export default function Lots() {
  const [lots, setLots] = useState<Lot[]>([]);
  const [selectedLotId, setSelectedLotId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Lot | null>(null);
  const [creating, setCreating] = useState(false);
  const [editingBoundary, setEditingBoundary] = useState<Coordinate[] | null>(null);
  const [mapsApiKey, setMapsApiKey] = useState("");
  const [closingLot, setClosingLot] = useState<Lot | null>(null);

  const load = useCallback(async () => {
    setLots(await api.lots.list());
  }, []);

  useEffect(() => {
    load();
    loadConfig().then((cfg) => setMapsApiKey(cfg.google_maps_api_key || ""));
  }, [load]);

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

  async function handleDelete(id: string) {
    if (!confirm("Delete this lot?")) return;
    await api.lots.delete(id);
    if (selectedLotId === id) setSelectedLotId(null);
    load();
  }

  async function handleReopen(lot: Lot) {
    if (!confirm(`Reopen ${lot.name}?`)) return;
    await api.lots.reopen(lot.id);
    load();
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
                onClick={() => {
                  if (!isEditing) setSelectedLotId(lot.id === selectedLotId ? null : lot.id);
                }}
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
                      {lot.total_spaces > 0 ? `${lot.total_spaces} spaces` : "No boundary defined"}
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
                        onClick={(e) => { e.stopPropagation(); handleDelete(lot.id); }}
                        className="text-signal-red/60 hover:text-signal-red text-xs"
                      >Delete</button>
                    </div>
                  )}
                </div>
              </div>
              {lot.id === selectedLotId && !isEditing && <ZonePanel lotId={lot.id} />}
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
          onSelectLot={(id) => {
            if (!isEditing) setSelectedLotId(id);
          }}
          editingBoundary={editingBoundary}
          onBoundaryChange={setEditingBoundary}
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
    </div>
  );
}
