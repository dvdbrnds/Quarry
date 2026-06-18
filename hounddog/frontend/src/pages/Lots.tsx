import { useCallback, useEffect, useState } from "react";
import { api, Coordinate, Lot } from "../api";
import { loadConfig } from "../auth";
import LotMap from "../components/LotMap";

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
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      if (initial) {
        await api.lots.update(initial.id, { name, boundary });
      } else {
        await api.lots.create({ name, boundary });
      }
      onSave();
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="p-4 border-t border-gray-200 bg-gray-50">
      <div className="mb-3">
        <label className="block text-xs font-medium text-ink-mute mb-1">
          Lot Name
        </label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none"
          placeholder="e.g. Lot A"
        />
      </div>
      <p className="text-xs text-ink-mute mb-3">
        {boundary.length === 0
          ? 'Click "Draw Boundary" on the map, then click to place points. Double-click to finish.'
          : `${boundary.length} points — drag vertices on the map to adjust.`}
      </p>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving || boundary.length < 3}
          className="flex-1 px-3 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors disabled:opacity-50"
        >
          {saving ? "Saving..." : initial ? "Update" : "Create"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-2 text-sm text-ink-mute hover:text-ink"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function Lots() {
  const [lots, setLots] = useState<Lot[]>([]);
  const [selectedLotId, setSelectedLotId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Lot | null>(null);
  const [creating, setCreating] = useState(false);
  const [editingBoundary, setEditingBoundary] = useState<Coordinate[] | null>(null);
  const [mapsApiKey, setMapsApiKey] = useState("");

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
            <div
              key={lot.id}
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
                  <h3 className="font-semibold text-sm">{lot.name}</h3>
                  <p className="text-xs text-ink-mute mt-0.5">
                    {lot.boundary.length > 0
                      ? `${lot.boundary.length} boundary points`
                      : "No boundary defined"}
                  </p>
                </div>
                {!isEditing && (
                  <div className="flex gap-2 ml-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        startEdit(lot);
                      }}
                      className="text-brass-deep hover:text-brass text-xs"
                    >
                      Edit
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(lot.id);
                      }}
                      className="text-signal-red/60 hover:text-signal-red text-xs"
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
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
    </div>
  );
}
