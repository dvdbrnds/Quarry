import { useCallback, useEffect, useState } from "react";
import { api, Coordinate, Lot } from "../api";

function CoordinateEditor({
  coords,
  onChange,
}: {
  coords: Coordinate[];
  onChange: (coords: Coordinate[]) => void;
}) {
  function update(i: number, field: "latitude" | "longitude", value: string) {
    const next = [...coords];
    next[i] = { ...next[i], [field]: parseFloat(value) || 0 };
    onChange(next);
  }

  function addPoint() {
    onChange([...coords, { latitude: 0, longitude: 0 }]);
  }

  function removePoint(i: number) {
    onChange(coords.filter((_, idx) => idx !== i));
  }

  function handlePaste(e: React.ClipboardEvent) {
    const text = e.clipboardData.getData("text");
    const lines = text.trim().split("\n").filter(Boolean);
    if (lines.length < 3) return;

    const parsed = lines.map((line) => {
      const parts = line.split(/[,\t\s]+/).map(Number);
      if (parts.length >= 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
        return { latitude: parts[0], longitude: parts[1] };
      }
      return null;
    }).filter(Boolean) as Coordinate[];

    if (parsed.length >= 3) {
      e.preventDefault();
      onChange(parsed);
    }
  }

  return (
    <div onPaste={handlePaste}>
      <div className="flex items-center justify-between mb-2">
        <label className="text-xs font-medium text-ink-mute">
          Boundary Points ({coords.length})
        </label>
        <button type="button" onClick={addPoint}
          className="text-xs text-brass-deep hover:text-brass">+ Add Point</button>
      </div>
      <p className="text-xs text-ink-mute mb-2">
        Paste lat/lng pairs from Google Earth (one per line) or enter manually.
      </p>
      <div className="space-y-2 max-h-60 overflow-y-auto">
        {coords.map((c, i) => (
          <div key={i} className="flex gap-2 items-center">
            <span className="text-xs text-ink-mute w-6 text-right">{i + 1}.</span>
            <input type="number" step="any" value={c.latitude}
              onChange={(e) => update(i, "latitude", e.target.value)}
              className="flex-1 border rounded px-2 py-1 text-xs" placeholder="Latitude" />
            <input type="number" step="any" value={c.longitude}
              onChange={(e) => update(i, "longitude", e.target.value)}
              className="flex-1 border rounded px-2 py-1 text-xs" placeholder="Longitude" />
            <button type="button" onClick={() => removePoint(i)}
              className="text-signal-red/50 hover:text-signal-red text-xs">&times;</button>
          </div>
        ))}
      </div>
    </div>
  );
}

function LotForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: Lot;
  onSave: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [boundary, setBoundary] = useState<Coordinate[]>(initial?.boundary ?? []);
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
    <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow p-6 mb-6">
      <div className="mb-4">
        <label className="block text-xs font-medium text-ink-mute mb-1">Lot Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} required
          className="w-full max-w-sm border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brass focus:outline-none" />
      </div>
      <CoordinateEditor coords={boundary} onChange={setBoundary} />
      <div className="flex gap-3 justify-end mt-4">
        <button type="button" onClick={onCancel}
          className="px-4 py-2 text-sm text-ink-mute hover:text-ink">Cancel</button>
        <button type="submit" disabled={saving}
          className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep transition-colors disabled:opacity-50">
          {saving ? "Saving..." : initial ? "Update" : "Create"}
        </button>
      </div>
    </form>
  );
}

export default function Lots() {
  const [lots, setLots] = useState<Lot[]>([]);
  const [editing, setEditing] = useState<Lot | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLots(await api.lots.list());
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleDelete(id: string) {
    if (!confirm("Delete this lot?")) return;
    await api.lots.delete(id);
    load();
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Parking Lots</h2>
        <button onClick={() => { setCreating(true); setEditing(null); }}
          className="px-4 py-2 bg-brass text-navy-deep font-medium rounded-lg text-sm hover:bg-brass-deep">
          + New Lot
        </button>
      </div>

      {(creating || editing) && (
        <LotForm
          initial={editing ?? undefined}
          onSave={() => { setCreating(false); setEditing(null); load(); }}
          onCancel={() => { setCreating(false); setEditing(null); }}
        />
      )}

      <div className="grid gap-4">
        {lots.map((lot) => (
          <div key={lot.id} className="bg-white rounded-xl shadow p-5 flex items-start justify-between">
            <div>
              <h3 className="font-semibold text-lg">{lot.name}</h3>
              <p className="text-sm text-ink-mute mt-1">
                {lot.boundary.length} boundary points
              </p>
              {lot.boundary.length > 0 && (
                <p className="text-xs text-ink-mute mt-1 font-mono">
                  {lot.boundary.slice(0, 3).map(
                    (c) => `${c.latitude.toFixed(5)}, ${c.longitude.toFixed(5)}`
                  ).join(" → ")}
                  {lot.boundary.length > 3 && ` → ... (${lot.boundary.length - 3} more)`}
                </p>
              )}
            </div>
            <div className="flex gap-2">
              <button onClick={() => { setEditing(lot); setCreating(false); }}
                className="text-brass-deep hover:text-brass text-sm">Edit</button>
              <button onClick={() => handleDelete(lot.id)}
                className="text-signal-red/70 hover:text-signal-red text-sm">Delete</button>
            </div>
          </div>
        ))}
        {lots.length === 0 && (
          <div className="text-center py-12 text-ink-mute">
            No parking lots configured yet. Add one to get started.
          </div>
        )}
      </div>
    </div>
  );
}
