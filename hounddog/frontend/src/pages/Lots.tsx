import { useCallback, useEffect, useMemo, useState } from "react";
import { api, Coordinate, Lot, LotZone, ParkingSpot } from "../api";
import { loadConfig } from "../auth";
import LotMap from "../components/LotMap";
import {
  Button, Input, InputNumber, Select, Checkbox, Modal, Form, DatePicker, Tag, Space, App, Card, Empty, Segmented,
} from "antd";
import dayjs from "dayjs";

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
  { value: "standard", label: "Standard", color: "blue" },
  { value: "ev", label: "EV Charging", color: "green" },
  { value: "handicap", label: "Handicap", color: "purple" },
  { value: "reserved", label: "Reserved", color: "gold" },
  { value: "loading", label: "Loading Zone", color: "default" },
];

const ZONE_TYPE_OPTIONS = [
  { value: "disability", label: "Disability" },
  { value: "fire_lane", label: "Fire Lane" },
  { value: "visitor", label: "Visitor" },
  { value: "admissions_visitor", label: "Admissions Visitor (Premium)" },
  { value: "loading", label: "Loading Zone" },
  { value: "ev_charging", label: "EV Charging" },
  { value: "reserved_tenant", label: "Reserved Tenant" },
];

const CAMPUS_OPTIONS = [
  { value: "", label: "— None —" },
  { value: "north", label: "North Campus" },
  { value: "south", label: "South Campus" },
  { value: "remote", label: "Remote Campus" },
];

const LOT_TYPE_OPTIONS = [
  { value: "lot", label: "Parking Lot" },
  { value: "street", label: "Street Parking" },
];

function LotForm({
  initial, boundary, onBoundaryChange, onSave, onCancel,
}: {
  initial?: Lot; boundary: Coordinate[]; onBoundaryChange: (c: Coordinate[]) => void;
  onSave: () => void; onCancel: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [scheduleError, setScheduleError] = useState("");

  useEffect(() => {
    if (initial) {
      form.setFieldsValue({
        name: initial.name,
        lot_type: initial.lot_type ?? "lot",
        designation_code: initial.designation_code ?? "",
        campus: initial.campus ?? "",
        total_spaces: initial.total_spaces,
        handicap_spaces: initial.handicap_spaces,
        is_snow_lot: initial.is_snow_lot,
        has_sheepdog: initial.has_sheepdog,
        notes: initial.notes ?? "",
        access_schedule_json: initial.access_schedule?.length ? JSON.stringify(initial.access_schedule, null, 2) : "",
      });
    } else {
      form.resetFields();
    }
  }, [initial, form]);

  async function handleFinish(values: any) {
    setSaving(true);
    setScheduleError("");
    const designLabel = DESIGNATION_OPTIONS.find(d => d.code === values.designation_code)?.label.split(" — ")[1] || "";
    let parsedSchedule = undefined;
    if (values.access_schedule_json?.trim()) {
      try { parsedSchedule = JSON.parse(values.access_schedule_json); }
      catch { setScheduleError("Invalid JSON"); setSaving(false); return; }
    }
    try {
      const data = {
        name: values.name, boundary,
        total_spaces: values.total_spaces ?? 0,
        handicap_spaces: values.handicap_spaces ?? 0,
        designation_code: values.designation_code,
        designation_label: designLabel,
        is_snow_lot: values.is_snow_lot ?? false,
        has_sheepdog: values.has_sheepdog ?? false,
        lot_type: values.lot_type ?? "lot",
        campus: values.campus || null,
        notes: values.notes || null,
        ...(parsedSchedule !== undefined ? { access_schedule: parsedSchedule } : {}),
      };
      if (initial) await api.lots.update(initial.id, data);
      else await api.lots.create(data);
      message.success(initial ? "Lot updated" : "Lot created");
      onSave();
    } catch { message.error("Failed to save lot"); } finally { setSaving(false); }
  }

  return (
    <div className="p-4 border-t border-gray-200 bg-gray-50 overflow-y-auto max-h-[50vh]">
      <Form form={form} layout="vertical" onFinish={handleFinish} size="small"
        initialValues={{ total_spaces: 0, handicap_spaces: 0, designation_code: "", campus: "", lot_type: "lot" }}>
        <Form.Item name="name" label="Name" rules={[{ required: true }]}>
          <Input placeholder="e.g. Lot A or Main St" />
        </Form.Item>
        <div className="grid grid-cols-2 gap-2">
          <Form.Item name="lot_type" label="Type">
            <Select options={LOT_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="campus" label="Campus">
            <Select options={CAMPUS_OPTIONS} />
          </Form.Item>
        </div>
        <Form.Item name="designation_code" label="Designation">
          <Select options={DESIGNATION_OPTIONS.map(d => ({ label: d.label, value: d.code }))} />
        </Form.Item>
        <div className="grid grid-cols-2 gap-2">
          <Form.Item name="total_spaces" label="Total Spaces">
            <InputNumber className="w-full" />
          </Form.Item>
          <Form.Item name="handicap_spaces" label="HC Spaces">
            <InputNumber className="w-full" />
          </Form.Item>
        </div>
        <Form.Item name="is_snow_lot" valuePropName="checked">
          <Checkbox>Snow lot (prohibited 11pm-7am during snow regulations)</Checkbox>
        </Form.Item>
        <Form.Item name="has_sheepdog" valuePropName="checked">
          <Checkbox>SheepDog occupancy monitoring</Checkbox>
        </Form.Item>
        <Form.Item name="notes" label="Notes">
          <Input placeholder="EV charging, flood risk, etc." />
        </Form.Item>
        <Form.Item name="access_schedule_json" label="Access Schedule (JSON)"
          help={scheduleError ? <span className="text-red-500">{scheduleError}</span> : "Array of season schedules"}>
          <Input.TextArea rows={4} className="font-mono text-xs"
            placeholder={'[\n  {"season": "fall_spring", "label": "Fall/Spring", "rules": [...]}\n]'} />
        </Form.Item>
        <p className="text-xs text-ink-mute mb-3">
          {boundary.length === 0
            ? 'Click "Draw Boundary" on the map, then click to place points.'
            : `${boundary.length} points — drag vertices to adjust.`}
        </p>
        <Space>
          <Button type="primary" htmlType="submit" loading={saving} disabled={boundary.length < 3}>
            {initial ? "Update" : "Create"}
          </Button>
          <Button onClick={onCancel}>Cancel</Button>
        </Space>
      </Form>
    </div>
  );
}

type ZoneFormState = { zone_type: string; label: string; space_count: number; fine_override: string; is_premium: boolean; notes: string };
const EMPTY_ZONE_FORM: ZoneFormState = { zone_type: "disability", label: "", space_count: 0, fine_override: "", is_premium: false, notes: "" };

function ZoneForm({ initial, onSubmit, onCancel }: {
  initial?: ZoneFormState; onSubmit: (d: ZoneFormState) => Promise<void>; onCancel: () => void;
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
      <Select value={form.zone_type} onChange={v => setForm({ ...form, zone_type: v })} size="small" className="w-full"
        options={ZONE_TYPE_OPTIONS} />
      <Input size="small" value={form.label} onChange={e => setForm({ ...form, label: e.target.value })} placeholder="Label" />
      <Space>
        <InputNumber size="small" value={form.space_count} onChange={v => setForm({ ...form, space_count: v ?? 0 })} placeholder="# spaces" />
        <Input size="small" value={form.fine_override} onChange={e => setForm({ ...form, fine_override: e.target.value })} placeholder="Fine $" style={{ width: 80 }} />
      </Space>
      <Input size="small" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} placeholder="Notes" />
      <Checkbox checked={form.is_premium} onChange={e => setForm({ ...form, is_premium: e.target.checked })}>Premium</Checkbox>
      <Space>
        <Button type="primary" size="small" htmlType="submit" loading={saving}>{initial ? "Update" : "Add"}</Button>
        <Button size="small" onClick={onCancel}>Cancel</Button>
      </Space>
    </form>
  );
}

function ZonePanel({ lotId }: { lotId: string }) {
  const { modal, message } = App.useApp();
  const [zones, setZones] = useState<LotZone[]>([]);
  const [adding, setAdding] = useState(false);
  const [editingZoneId, setEditingZoneId] = useState<string | null>(null);

  const load = useCallback(async () => { setZones(await api.lots.zones.list(lotId)); }, [lotId]);
  useEffect(() => { load(); }, [load]);

  async function handleAdd(data: ZoneFormState) {
    await api.lots.zones.create(lotId, { zone_type: data.zone_type, label: data.label || data.zone_type.replace(/_/g, " "), space_count: data.space_count, fine_override: data.fine_override || null, is_premium: data.is_premium, notes: data.notes || null });
    message.success("Zone added");
    setAdding(false); load();
  }

  async function handleUpdate(zoneId: string, data: ZoneFormState) {
    await api.lots.zones.update(lotId, zoneId, { zone_type: data.zone_type, label: data.label || data.zone_type.replace(/_/g, " "), space_count: data.space_count, fine_override: data.fine_override || null, is_premium: data.is_premium, notes: data.notes || null });
    message.success("Zone updated");
    setEditingZoneId(null); load();
  }

  function handleDelete(zoneId: string) {
    modal.confirm({
      title: "Remove this zone?",
      okText: "Remove", okButtonProps: { danger: true },
      onOk: async () => {
        await api.lots.zones.delete(lotId, zoneId);
        message.success("Zone removed");
        load();
      },
    });
  }

  return (
    <div className="p-4 border-t border-gray-200">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-bold uppercase text-ink-mute tracking-wide">Zones</h4>
        <Button type="link" size="small" onClick={() => setAdding(true)}>+ Add</Button>
      </div>
      {zones.map(z => editingZoneId === z.id ? (
        <ZoneForm key={z.id}
          initial={{ zone_type: z.zone_type, label: z.label, space_count: z.space_count, fine_override: z.fine_override ?? "", is_premium: z.is_premium, notes: z.notes ?? "" }}
          onSubmit={data => handleUpdate(z.id, data)} onCancel={() => setEditingZoneId(null)} />
      ) : (
        <div key={z.id} className="flex items-center justify-between text-xs py-1">
          <span className="capitalize">
            {z.zone_type.replace(/_/g, " ")} ({z.space_count})
            {z.is_premium && <Tag color="gold" className="ml-1 !text-[10px]">Premium</Tag>}
            {z.fine_override && <span className="ml-1 text-ink-mute">${z.fine_override}</span>}
          </span>
          <Space>
            <Button type="link" size="small" onClick={() => setEditingZoneId(z.id)}>Edit</Button>
            <Button type="link" size="small" danger onClick={() => handleDelete(z.id)}>Remove</Button>
          </Space>
        </div>
      ))}
      {zones.length === 0 && !adding && <p className="text-xs text-ink-mute">No special zones defined</p>}
      {adding && <ZoneForm onSubmit={handleAdd} onCancel={() => setAdding(false)} />}
    </div>
  );
}

function SpotDetail({ spot, lotId, onSaved, onClose, onStartPlacing, placingSpot }: {
  spot: ParkingSpot; lotId: string; onSaved: () => void; onClose: () => void;
  onStartPlacing: () => void; placingSpot: boolean;
}) {
  const { modal, message } = App.useApp();
  const [number, setNumber] = useState(spot.number);
  const [label, setLabel] = useState(spot.label ?? "");
  const [spotType, setSpotType] = useState(spot.spot_type);
  const [sensorId, setSensorId] = useState(spot.sensor_id ?? "");
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await api.lots.spots.update(lotId, spot.id, { number, label: label || null, spot_type: spotType, sensor_id: sensorId || null });
      message.success("Spot updated");
      onSaved();
    } catch { message.error("Failed to save spot"); } finally { setSaving(false); }
  }

  function handleDelete() {
    modal.confirm({
      title: `Remove spot #${spot.number}?`, okText: "Delete", okButtonProps: { danger: true },
      onOk: async () => { await api.lots.spots.delete(lotId, spot.id); message.success("Spot deleted"); onSaved(); onClose(); },
    });
  }

  return (
    <div className="p-4 border-t border-amber-300 bg-amber-50/50 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-bold uppercase text-amber-700 tracking-wide">Edit Spot #{spot.number}</h4>
        <Button type="link" size="small" onClick={onClose}>Back to list</Button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-[10px] font-medium text-ink-mute mb-0.5">Spot Number</label>
          <InputNumber size="small" value={number} onChange={v => setNumber(v ?? 0)} className="w-full" />
        </div>
        <div>
          <label className="block text-[10px] font-medium text-ink-mute mb-0.5">Label</label>
          <Input size="small" value={label} onChange={e => setLabel(e.target.value)} placeholder="Optional" />
        </div>
      </div>
      <div>
        <label className="block text-[10px] font-medium text-ink-mute mb-0.5">Spot Type</label>
        <Select size="small" value={spotType} onChange={setSpotType} className="w-full"
          options={SPOT_TYPE_OPTIONS.map(t => ({ label: t.label, value: t.value }))} />
      </div>
      <div>
        <label className="block text-[10px] font-medium text-ink-mute mb-0.5">LoRaWAN Sensor ID</label>
        <Input size="small" value={sensorId} onChange={e => setSensorId(e.target.value)} placeholder="e.g. A-001" className="font-mono" />
      </div>
      <div>
        <label className="block text-[10px] font-medium text-ink-mute mb-0.5">Location</label>
        {spot.latitude != null && spot.longitude != null ? (
          <Space>
            <span className="text-xs font-mono text-ink-mute">{spot.latitude.toFixed(6)}, {spot.longitude.toFixed(6)}</span>
            <Button type="link" size="small" onClick={onStartPlacing}>{placingSpot ? "Click the map..." : "Reposition"}</Button>
          </Space>
        ) : (
          <Button size="small" type={placingSpot ? "primary" : "default"} onClick={onStartPlacing}>
            {placingSpot ? "Click the map to place..." : "Place on Map"}
          </Button>
        )}
      </div>
      <Space className="pt-1">
        <Button type="primary" size="small" loading={saving} onClick={handleSave} style={{ background: "#f59e0b" }}>Save Changes</Button>
        <Button type="text" size="small" danger onClick={handleDelete}>Delete Spot</Button>
      </Space>
    </div>
  );
}

function SpotPanel({
  lotId, spots, selectedSpotId, onSelectSpot, onSpotsChanged, onStartPlacing, placingSpot,
  batchPlacing, batchNextNumber, onStartBatch, onStopBatch, spotsVisible, onToggleVisible,
}: {
  lotId: string; spots: ParkingSpot[]; selectedSpotId: string | null; onSelectSpot: (id: string | null) => void;
  onSpotsChanged: () => void; onStartPlacing: () => void; placingSpot: boolean;
  batchPlacing: boolean; batchNextNumber: number; onStartBatch: () => void; onStopBatch: () => void;
  spotsVisible: boolean; onToggleVisible: () => void;
}) {
  const { modal, message } = App.useApp();
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
    return <SpotDetail spot={selectedSpot} lotId={lotId} onSaved={onSpotsChanged} onClose={() => onSelectSpot(null)}
      onStartPlacing={onStartPlacing} placingSpot={placingSpot} />;
  }

  function toggleCheck(id: string) {
    setChecked(prev => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }
  function toggleAll() { setChecked(checked.size === spots.length ? new Set() : new Set(spots.map(s => s.id))); }

  function handleBulkDelete() {
    if (checked.size === 0) return;
    modal.confirm({
      title: `Delete ${checked.size} spot(s)?`, okText: "Delete", okButtonProps: { danger: true },
      onOk: async () => {
        setDeleting(true);
        try { await api.lots.spots.bulkDelete(lotId, Array.from(checked)); message.success("Spots deleted"); setChecked(new Set()); onSpotsChanged(); }
        finally { setDeleting(false); }
      },
    });
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.lots.spots.create(lotId, { number: newNumber, label: newLabel || null, spot_type: newSpotType, sensor_id: newSensorId || null });
      message.success("Spot added");
      setAdding(false); setNewLabel(""); setNewSensorId(""); setNewSpotType("standard"); onSpotsChanged();
    } catch { message.error("Failed to add spot"); } finally { setSaving(false); }
  }

  return (
    <div className="p-4 border-t border-amber-200 bg-amber-50/30">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-bold uppercase text-amber-700 tracking-wide flex items-center gap-1.5">
          SheepDog Spots
          <Button size="small" type={spotsVisible ? "primary" : "default"} onClick={onToggleVisible}
            style={spotsVisible ? { background: "#f59e0b", borderColor: "#f59e0b" } : {}} className="!w-5 !h-5 !min-w-0 !p-0">
            {spotsVisible ? "👁" : "🚫"}
          </Button>
        </h4>
        <Space>
          {batchPlacing ? (
            <Button size="small" type="primary" style={{ background: "#059669" }} onClick={onStopBatch}>Done Placing</Button>
          ) : (
            <>
              <Button type="link" size="small" onClick={onStartBatch}>Place Spots</Button>
              <Button type="link" size="small" onClick={() => { setAdding(true); setNewNumber(spots.length > 0 ? Math.max(...spots.map(s => s.number)) + 1 : 1); }}>+ Add</Button>
            </>
          )}
        </Space>
      </div>
      {batchPlacing && (
        <div className="mb-2 px-2 py-1.5 bg-amber-100 border border-amber-300 rounded text-xs text-amber-800">
          Click on the map to place spots. Next spot: <strong>#{batchNextNumber}</strong>
        </div>
      )}
      {spots.length > 0 && (
        <div className="flex items-center justify-between mb-1.5 pb-1.5 border-b border-amber-200/60">
          <Checkbox checked={checked.size === spots.length && spots.length > 0} onChange={toggleAll}>
            <span className="text-[10px] text-ink-mute">{checked.size > 0 ? `${checked.size} selected` : "Select all"}</span>
          </Checkbox>
          {checked.size > 0 && <Button size="small" type="text" danger loading={deleting} onClick={handleBulkDelete}>Delete {checked.size}</Button>}
        </div>
      )}
      {spots.map(s => (
        <div key={s.id} className={`flex items-center text-xs py-1.5 px-1 rounded cursor-pointer transition-colors ${s.id === selectedSpotId ? "bg-amber-100" : "hover:bg-amber-50"}`}>
          <Checkbox checked={checked.has(s.id)} onChange={() => toggleCheck(s.id)} className="mr-1.5" />
          <span className="flex items-center gap-1.5 flex-1 min-w-0" onClick={() => onSelectSpot(s.id)}>
            <span className="font-mono font-bold text-amber-700">#{s.number}</span>
            <Tag color={SPOT_TYPE_OPTIONS.find(t => t.value === s.spot_type)?.color}>{SPOT_TYPE_OPTIONS.find(t => t.value === s.spot_type)?.label ?? s.spot_type}</Tag>
            {s.label && <span className="text-ink-mute truncate">{s.label}</span>}
            {s.sensor_id && <Tag className="!text-[10px]">{s.sensor_id}</Tag>}
          </span>
          {s.latitude == null && <span className="text-[10px] text-ink-mute italic flex-shrink-0">no location</span>}
        </div>
      ))}
      {spots.length === 0 && !adding && !batchPlacing && <Empty description="No spots assigned" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      {adding && (
        <form onSubmit={handleAdd} className="mt-2 space-y-2 bg-amber-50 rounded-lg p-2">
          <Space>
            <InputNumber size="small" value={newNumber} onChange={v => setNewNumber(v ?? 1)} style={{ width: 60 }} />
            <Input size="small" value={newLabel} onChange={e => setNewLabel(e.target.value)} placeholder="Label" />
          </Space>
          <Select size="small" value={newSpotType} onChange={setNewSpotType} className="w-full"
            options={SPOT_TYPE_OPTIONS.map(t => ({ label: t.label, value: t.value }))} />
          <Input size="small" value={newSensorId} onChange={e => setNewSensorId(e.target.value)} placeholder="Sensor ID" className="font-mono" />
          <Space>
            <Button size="small" type="primary" htmlType="submit" loading={saving} style={{ background: "#f59e0b" }}>Add</Button>
            <Button size="small" onClick={() => setAdding(false)}>Cancel</Button>
          </Space>
        </form>
      )}
    </div>
  );
}

export default function Lots() {
  const { modal, message } = App.useApp();
  const [lots, setLots] = useState<Lot[]>([]);
  const [selectedLotId, setSelectedLotId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Lot | null>(null);
  const [creating, setCreating] = useState(false);
  const [editingBoundary, setEditingBoundary] = useState<Coordinate[] | null>(null);
  const [mapsApiKey, setMapsApiKey] = useState("");
  const [campusCenter, setCampusCenter] = useState({ lat: 40.6265, lng: -75.3707 });
  const [closingLot, setClosingLot] = useState<Lot | null>(null);

  const [spots, setSpots] = useState<ParkingSpot[]>([]);
  const [selectedSpotId, setSelectedSpotId] = useState<string | null>(null);
  const [placingSpot, setPlacingSpot] = useState(false);
  const [batchPlacing, setBatchPlacing] = useState(false);
  const [batchNextNumber, setBatchNextNumber] = useState(1);
  const [spotsVisible, setSpotsVisible] = useState(true);

  const [selectedCampus, setSelectedCampus] = useState<string>("all");
  const [selectedType, setSelectedType] = useState<string>("all");

  const [closeReason, setCloseReason] = useState("");
  const [closeReopensAt, setCloseReopensAt] = useState<dayjs.Dayjs | null>(null);
  const [closeRecipients, setCloseRecipients] = useState("");
  const [closeSubmitting, setCloseSubmitting] = useState(false);

  const filteredLots = useMemo(() => {
    let result = lots;
    if (selectedCampus !== "all") result = result.filter(l => l.campus === selectedCampus);
    if (selectedType !== "all") result = result.filter(l => (l.lot_type || "lot") === selectedType);
    return result;
  }, [lots, selectedCampus, selectedType]);

  const selectedLot = lots.find(l => l.id === selectedLotId);
  const isSheepDogLot = selectedLot?.has_sheepdog ?? false;

  const load = useCallback(async () => { setLots(await api.lots.list()); }, []);
  const loadSpots = useCallback(async () => {
    if (!selectedLotId || !isSheepDogLot) { setSpots([]); return; }
    try { setSpots(await api.lots.spots.list(selectedLotId)); } catch { setSpots([]); }
  }, [selectedLotId, isSheepDogLot]);

  useEffect(() => {
    load();
    loadConfig().then(cfg => {
      setMapsApiKey(cfg.google_maps_api_key || "");
      if (cfg.campus_lat && cfg.campus_lng) setCampusCenter({ lat: cfg.campus_lat, lng: cfg.campus_lng });
    });
  }, [load]);

  useEffect(() => { loadSpots(); setSelectedSpotId(null); setPlacingSpot(false); setBatchPlacing(false); }, [loadSpots]);

  function handleSelectLot(id: string | null) {
    if (creating || editing) return;
    setSelectedLotId(id === selectedLotId ? null : id);
  }

  function startCreate() { setCreating(true); setEditing(null); setSelectedLotId(null); setEditingBoundary([]); }
  function startEdit(lot: Lot) { setEditing(lot); setCreating(false); setSelectedLotId(lot.id); setEditingBoundary([...lot.boundary]); }
  function cancelEdit() { setCreating(false); setEditing(null); setEditingBoundary(null); }
  function handleSaved() { cancelEdit(); load(); }

  function handleDeleteLot(lot: Lot) {
    modal.confirm({
      title: `Delete ${lot.name}?`,
      content: `This will permanently remove ${lot.name} and all its zones. This action cannot be undone.`,
      okText: "Delete Lot", okButtonProps: { danger: true },
      onOk: async () => {
        await api.lots.delete(lot.id);
        if (selectedLotId === lot.id) setSelectedLotId(null);
        message.success("Lot deleted");
        load();
      },
    });
  }


  function handleReopen(lot: Lot) {
    modal.confirm({
      title: `Reopen ${lot.name}?`,
      onOk: async () => { await api.lots.reopen(lot.id); message.success("Lot reopened"); load(); },
    });
  }

  async function handleCloseLot() {
    if (!closingLot) return;
    setCloseSubmitting(true);
    try {
      const recipients = closeRecipients.split(",").map(e => e.trim()).filter(Boolean);
      await api.lots.close(closingLot.id, {
        reason: closeReason,
        reopens_at: closeReopensAt ? closeReopensAt.toISOString() : undefined,
        recipients,
      });
      message.success(`${closingLot.name} closed`);
      setClosingLot(null); setCloseReason(""); setCloseReopensAt(null); setCloseRecipients("");
      load();
    } catch { message.error("Failed to close lot"); } finally { setCloseSubmitting(false); }
  }

  function handlePlaceSpot(lat: number, lng: number) {
    if (!selectedLotId) return;
    if (batchPlacing) {
      api.lots.spots.create(selectedLotId, { number: batchNextNumber, spot_type: "standard", latitude: lat, longitude: lng })
        .then(() => { setBatchNextNumber(n => n + 1); loadSpots(); });
      return;
    }
    if (!selectedSpotId) return;
    api.lots.spots.update(selectedLotId, selectedSpotId, { latitude: lat, longitude: lng })
      .then(() => { setPlacingSpot(false); loadSpots(); });
  }

  function startBatchPlacing() {
    const nextNum = spots.length > 0 ? Math.max(...spots.map(s => s.number)) + 1 : 1;
    setBatchNextNumber(nextNum); setBatchPlacing(true); setPlacingSpot(true); setSelectedSpotId(null);
  }

  const isEditing = creating || editing !== null;

  return (
    <div className="flex gap-6 h-[calc(100vh-7rem)]">
      <div className="w-80 flex-shrink-0 flex flex-col bg-white rounded-xl shadow overflow-hidden">
        <div className="p-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-bold">Parking</h2>
          <Button type="primary" size="small" disabled={isEditing} onClick={startCreate}>+ New</Button>
        </div>
        {(lots.some(l => l.campus) || lots.some(l => l.lot_type === "street")) && (
          <div className="px-3 py-2 border-b border-gray-100 space-y-1.5">
            {lots.some(l => l.campus) && (
              <Segmented
                size="small"
                block
                value={selectedCampus}
                onChange={v => { setSelectedCampus(v as string); setSelectedLotId(null); }}
                options={[
                  { label: "All", value: "all" },
                  ...CAMPUS_OPTIONS.filter(c => c.value && lots.some(l => l.campus === c.value))
                    .map(c => ({ label: c.label, value: c.value })),
                ]}
              />
            )}
            {lots.some(l => l.lot_type === "street") && (
              <Segmented
                size="small"
                block
                value={selectedType}
                onChange={v => { setSelectedType(v as string); setSelectedLotId(null); }}
                options={[
                  { label: "All Types", value: "all" },
                  { label: "Lots", value: "lot" },
                  { label: "Streets", value: "street" },
                ]}
              />
            )}
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          {filteredLots.length === 0 && <Empty description={lots.length === 0 ? 'No parking yet. Click "+ New"' : "No matches for this filter"} className="py-12" />}
          {filteredLots.map(lot => (
            <div key={lot.id}>
              <div onClick={() => handleSelectLot(lot.id)}
                className={`p-4 border-b border-gray-100 cursor-pointer transition-colors ${lot.id === selectedLotId ? "bg-brass/10 border-l-4 border-l-brass" : "hover:bg-gray-50"}`}>
                <div className="flex items-start justify-between">
                  <div>
                    <Space>
                      <h3 className="font-semibold text-sm">{lot.name}</h3>
                      {lot.lot_type === "street" && <Tag color="default" className="!text-[10px]">Street</Tag>}
                      {lot.campus && <Tag color="blue" className="!text-[10px]">{CAMPUS_OPTIONS.find(c => c.value === lot.campus)?.label ?? lot.campus}</Tag>}
                      {lot.has_sheepdog && <Tag color="gold" className="!text-[10px]">SD</Tag>}
                      {lot.is_closed && lot.lot_type !== "street" && <Tag color="red" className="!text-[10px]">CLOSED</Tag>}
                    </Space>
                    <p className="text-xs text-ink-mute mt-0.5">
                      {lot.designation_code && <Tag className="!text-[10px]">{lot.designation_code}</Tag>}
                      {lot.boundary.length >= 3
                        ? lot.total_spaces > 0 ? `${lot.total_spaces} spaces` : "Boundary set"
                        : "No boundary defined"}
                      {lot.is_snow_lot && " · Snow"}
                    </p>
                  </div>
                  {!isEditing && (
                    <Space className="ml-2 flex-shrink-0" onClick={e => e.stopPropagation()}>
                      {lot.lot_type !== "street" && (lot.is_closed
                        ? <Button type="link" size="small" onClick={() => handleReopen(lot)}>Reopen</Button>
                        : <Button type="link" size="small" danger onClick={() => setClosingLot(lot)}>Close</Button>)}
                      <Button type="link" size="small" onClick={() => startEdit(lot)}>Edit</Button>
                      <Button type="link" size="small" danger onClick={() => handleDeleteLot(lot)}>Delete</Button>
                    </Space>
                  )}
                </div>
              </div>
              {lot.id === selectedLotId && !isEditing && (
                <>
                  <ZonePanel lotId={lot.id} />
                  {lot.has_sheepdog && (
                    <SpotPanel lotId={lot.id} spots={spots} selectedSpotId={selectedSpotId}
                      onSelectSpot={setSelectedSpotId} onSpotsChanged={loadSpots}
                      onStartPlacing={() => setPlacingSpot(true)} placingSpot={placingSpot}
                      batchPlacing={batchPlacing} batchNextNumber={batchNextNumber}
                      onStartBatch={startBatchPlacing} onStopBatch={() => { setBatchPlacing(false); setPlacingSpot(false); }}
                      spotsVisible={spotsVisible} onToggleVisible={() => setSpotsVisible(v => !v)} />
                  )}
                </>
              )}
            </div>
          ))}
        </div>

        {isEditing && (
          <LotForm initial={editing ?? undefined} boundary={editingBoundary ?? []}
            onBoundaryChange={setEditingBoundary} onSave={handleSaved} onCancel={cancelEdit} />
        )}
      </div>

      <div className="flex-1 rounded-xl shadow overflow-hidden">
        <LotMap apiKey={mapsApiKey} lots={filteredLots} selectedLotId={selectedLotId}
          onSelectLot={handleSelectLot} editingBoundary={editingBoundary}
          onBoundaryChange={setEditingBoundary} defaultCenter={campusCenter}
          spots={isSheepDogLot && spotsVisible ? spots : []} selectedSpotId={selectedSpotId}
          onSelectSpot={setSelectedSpotId} placingSpot={placingSpot} onPlaceSpot={handlePlaceSpot} />
      </div>

      <Modal open={!!closingLot} title={<span className="text-red-600">Close {closingLot?.name}</span>}
        okText="Close Lot Now" okButtonProps={{ danger: true }} confirmLoading={closeSubmitting}
        onOk={handleCloseLot} onCancel={() => setClosingLot(null)}>
        <p className="text-sm text-ink-mute mb-4">
          This will immediately close the lot and send notification emails to all permit holders assigned to this lot.
        </p>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Reason</label>
            <Input value={closeReason} onChange={e => setCloseReason(e.target.value)} placeholder="Snow removal, event, maintenance..." />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Reopens At (optional)</label>
            <DatePicker showTime value={closeReopensAt} onChange={setCloseReopensAt} className="w-full" />
          </div>
          <div>
            <label className="block text-xs font-medium text-ink-mute mb-1">Additional Recipients</label>
            <Input value={closeRecipients} onChange={e => setCloseRecipients(e.target.value)} placeholder="dean@campus.edu, security@campus.edu" />
          </div>
        </div>
      </Modal>
    </div>
  );
}
