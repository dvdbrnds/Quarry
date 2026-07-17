import { useCallback, useEffect, useState, useRef } from "react";
import { Card, Button, Input, Upload, App, Spin, ColorPicker, Popconfirm, Space, Modal } from "antd";
import { UploadOutlined, UndoOutlined, SaveOutlined, DeleteOutlined } from "@ant-design/icons";
import { authHeaders } from "../auth";
import { useBranding } from "../useBranding";

interface BrandPreset {
  name: string;
  brand_name: string;
  primary_color: string;
  accent_color: string;
}

const PRESETS_KEY = "quarry_brand_presets";

function loadPresets(): BrandPreset[] {
  try { return JSON.parse(localStorage.getItem(PRESETS_KEY) || "[]"); }
  catch { return []; }
}

function savePresets(presets: BrandPreset[]) {
  localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
}

interface BrandingData {
  brand_name: string;
  primary_color: string;
  accent_color: string;
  logo_url: string | null;
  favicon_url: string;
  school_name: string;
}

export default function BrandingSettings() {
  const { message } = App.useApp();
  const brand = useBranding();
  const [data, setData] = useState<BrandingData | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState<"logo" | "favicon" | null>(null);
  const logoRef = useRef<HTMLInputElement>(null);
  const faviconRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/branding");
      if (res.ok) setData(await res.json());
    } catch { /* fallback is fine */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function saveBrandIdentity() {
    if (!data) return;
    try {
      const res = await fetch("/api/branding/identity", {
        method: "POST",
        headers: { ...(await authHeaders()), "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_name: data.brand_name,
          primary_color: data.primary_color,
          accent_color: data.accent_color,
        }),
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        if (res.status === 403) {
          message.error("Permission denied — try logging out and back in.");
        } else {
          message.error(`Failed to save branding: ${res.status} ${detail}`);
        }
        return;
      }
      message.success("Branding saved — reloading…");
      setTimeout(() => window.location.reload(), 400);
    } catch { message.error("Failed to save branding — network error"); }
  }

  async function handleUpload(type: "logo" | "favicon", file: File) {
    setUploading(type);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`/api/branding/${type}`, {
        method: "POST",
        headers: Object.fromEntries(
          Object.entries(await authHeaders()).filter(([k]) => k !== "Content-Type")
        ),
        body: form,
      });
      if (!res.ok) throw new Error("Upload failed");
      message.success(`${type === "logo" ? "Logo" : "Favicon"} uploaded`);
      load();
    } catch { message.error("Upload failed"); }
    finally { setUploading(null); }
  }

  const [resetting, setResetting] = useState(false);
  const [presets, setPresets] = useState<BrandPreset[]>(loadPresets);
  const [presetName, setPresetName] = useState("");
  const [showSavePreset, setShowSavePreset] = useState(false);

  function handleSavePreset() {
    if (!data || !presetName.trim()) return;
    const preset: BrandPreset = {
      name: presetName.trim(),
      brand_name: data.brand_name,
      primary_color: data.primary_color,
      accent_color: data.accent_color,
    };
    const updated = [...presets.filter(p => p.name !== preset.name), preset];
    savePresets(updated);
    setPresets(updated);
    setPresetName("");
    setShowSavePreset(false);
    message.success(`Preset "${preset.name}" saved`);
  }

  function handleLoadPreset(preset: BrandPreset) {
    if (!data) return;
    setData({ ...data, brand_name: preset.brand_name, primary_color: preset.primary_color, accent_color: preset.accent_color });
    message.info(`Loaded "${preset.name}" — click Save Branding to apply`);
  }

  function handleDeletePreset(name: string) {
    const updated = presets.filter(p => p.name !== name);
    savePresets(updated);
    setPresets(updated);
    message.success(`Preset "${name}" deleted`);
  }

  async function resetToDefaults() {
    setResetting(true);
    try {
      const res = await fetch("/api/branding/reset", {
        method: "POST",
        headers: await authHeaders(),
      });
      if (!res.ok) throw new Error("Reset failed");
      message.success("Branding reset to Quarry defaults — reloading…");
      setTimeout(() => window.location.reload(), 400);
    } catch { message.error("Failed to reset branding"); }
    finally { setResetting(false); }
  }

  if (loading) return <div className="flex justify-center py-12"><Spin size="large" /></div>;
  if (!data) return <p className="text-ink-mute">Unable to load branding config.</p>;

  return (
    <div className="space-y-6">
      <Card title="Logo & Favicon">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          <div>
            <label className="block text-sm font-medium text-ink mb-2">Logo</label>
            <p className="text-xs text-ink-mute mb-3">
              Displayed in nav bars and email headers. Recommended: PNG or SVG, max height 48px.
            </p>
            <div className="flex items-center gap-4 mb-3">
              {data.logo_url ? (
                <div className="rounded-lg p-4" style={{ background: data.primary_color }}>
                  <img
                    src={data.logo_url}
                    alt="Current logo"
                    className="h-12 w-auto"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                </div>
              ) : (
                <div className="border rounded-lg p-3 bg-gray-50 text-sm text-ink-mute">
                  No logo uploaded{data.brand_name ? <> — using text: <strong>{data.brand_name}</strong></> : ""}
                </div>
              )}
            </div>
            <input
              ref={logoRef}
              type="file"
              accept="image/png,image/jpeg,image/svg+xml,image/webp"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleUpload("logo", file);
                e.target.value = "";
              }}
            />
            <Button
              icon={<UploadOutlined />}
              loading={uploading === "logo"}
              onClick={() => logoRef.current?.click()}
            >
              Upload Logo
            </Button>
          </div>

          <div>
            <label className="block text-sm font-medium text-ink mb-2">Favicon</label>
            <p className="text-xs text-ink-mute mb-3">
              Browser tab icon. Recommended: 32x32 or 64x64 PNG.
            </p>
            <div className="flex items-center gap-4 mb-3">
              <div className="border rounded-lg p-3 bg-gray-50">
                <img
                  src={data.favicon_url}
                  alt="Current favicon"
                  className="h-8 w-auto"
                  onError={(e) => { (e.target as HTMLImageElement).src = "/favicon.png"; }}
                />
              </div>
            </div>
            <input
              ref={faviconRef}
              type="file"
              accept="image/png,image/x-icon,image/vnd.microsoft.icon,image/jpeg"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleUpload("favicon", file);
                e.target.value = "";
              }}
            />
            <Button
              icon={<UploadOutlined />}
              loading={uploading === "favicon"}
              onClick={() => faviconRef.current?.click()}
            >
              Upload Favicon
            </Button>
          </div>
        </div>
      </Card>

      <Card title="Brand Identity">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div>
            <label className="block text-sm font-medium text-ink mb-1">Product Name</label>
            <Input
              value={data.brand_name}
              onChange={(e) => setData({ ...data, brand_name: e.target.value })}
              placeholder="Leave blank to use logo only"
              allowClear
            />
            <p className="text-xs text-ink-mute mt-1">Optional if you have a logo uploaded.</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-ink mb-1">Primary Color</label>
            <div className="flex items-center gap-2">
              <div
                className="w-8 h-8 rounded border shrink-0"
                style={{ background: data.primary_color }}
              />
              <Input
                value={data.primary_color}
                onChange={(e) => setData({ ...data, primary_color: e.target.value })}
                className="flex-1"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-ink mb-1">Accent Color</label>
            <div className="flex items-center gap-2">
              <div
                className="w-8 h-8 rounded border shrink-0"
                style={{ background: data.accent_color }}
              />
              <Input
                value={data.accent_color}
                onChange={(e) => setData({ ...data, accent_color: e.target.value })}
                className="flex-1"
              />
            </div>
          </div>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Button type="primary" onClick={saveBrandIdentity}>Save Branding</Button>
          <Button icon={<SaveOutlined />} onClick={() => setShowSavePreset(true)}>Save as Preset</Button>
          <Popconfirm
            title="Reset to Quarry defaults?"
            description="This will reset colors, name, logo, and favicon to the original Quarry theme."
            onConfirm={resetToDefaults}
            okText="Reset"
            okButtonProps={{ danger: true }}
          >
            <Button icon={<UndoOutlined />} loading={resetting} danger>
              Reset to Defaults
            </Button>
          </Popconfirm>
        </div>

        {presets.length > 0 && (
          <div className="mt-4 pt-4 border-t">
            <label className="block text-sm font-medium text-ink mb-2">Saved Presets</label>
            <div className="flex flex-wrap gap-2">
              {presets.map(p => (
                <div key={p.name} className="flex items-center gap-1 border rounded-lg px-3 py-1.5 bg-gray-50 hover:bg-gray-100 transition-colors">
                  <div className="w-4 h-4 rounded-full border shrink-0" style={{ background: p.primary_color }} />
                  <div className="w-4 h-4 rounded-full border shrink-0 -ml-1" style={{ background: p.accent_color }} />
                  <button
                    onClick={() => handleLoadPreset(p)}
                    className="text-sm font-medium text-ink ml-1 hover:underline"
                  >
                    {p.name}
                  </button>
                  <button
                    onClick={() => handleDeletePreset(p.name)}
                    className="text-gray-400 hover:text-red-500 ml-1 transition-colors"
                    title="Delete preset"
                  >
                    <DeleteOutlined className="text-xs" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        <Modal
          open={showSavePreset}
          title="Save Brand Preset"
          onCancel={() => { setShowSavePreset(false); setPresetName(""); }}
          onOk={handleSavePreset}
          okText="Save"
          okButtonProps={{ disabled: !presetName.trim() }}
        >
          <p className="text-sm text-ink-mute mb-3">
            Save the current name and colors as a preset you can quickly switch to later.
          </p>
          <Input
            placeholder="e.g. Moravian Blue, Holiday Theme"
            value={presetName}
            onChange={e => setPresetName(e.target.value)}
            onPressEnter={handleSavePreset}
            autoFocus
          />
        </Modal>
      </Card>

      <Card title="Preview">
        <p className="text-xs text-ink-mute mb-4">How the nav bar appears to students:</p>
        <div
          style={{ background: data.primary_color }}
          className="rounded-lg px-6 py-4 flex items-center gap-3 shadow"
        >
          {data.logo_url && (
            <img
              src={data.logo_url}
              alt={data.brand_name || "Logo"}
              className="h-8 w-auto"
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          )}
          {data.brand_name && (
            <span
              style={{ color: data.accent_color }}
              className="text-lg font-bold tracking-wide"
            >
              {data.brand_name}
            </span>
          )}
          <span className="text-sm text-white/60 ml-2">Parking Services</span>
        </div>
      </Card>
    </div>
  );
}
