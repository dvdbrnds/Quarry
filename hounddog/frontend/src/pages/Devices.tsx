import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { api, Device } from "../api";

export default function Devices() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [newDeviceName, setNewDeviceName] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [pairingDevice, setPairingDevice] = useState<Device | null>(null);

  async function loadDevices() {
    setLoading(true);
    try {
      const data = await api.devices.list();
      setDevices(data);
    } catch (e) {
      console.error("Failed to load devices", e);
    }
    setLoading(false);
  }

  useEffect(() => {
    loadDevices();
  }, []);

  async function handleCreate() {
    if (!newDeviceName.trim()) return;
    try {
      const device = await api.devices.create({ name: newDeviceName.trim() });
      setPairingDevice(device);
      setNewDeviceName("");
      setShowAddForm(false);
      await loadDevices();
    } catch (e) {
      console.error("Failed to create device", e);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Revoke this device? It will no longer be able to sync.")) return;
    try {
      await api.devices.delete(id);
      await loadDevices();
    } catch (e) {
      console.error("Failed to delete device", e);
    }
  }

  function formatDate(iso: string | null) {
    if (!iso) return "Never";
    return new Date(iso).toLocaleString();
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-navy">Devices</h2>
        <button
          onClick={() => setShowAddForm(true)}
          className="px-4 py-2 bg-brass text-navy-deep rounded-lg font-medium hover:bg-brass/90 transition-colors"
        >
          + Add Device
        </button>
      </div>

      {showAddForm && (
        <div className="bg-white rounded-lg shadow p-6 mb-6 border border-gray-200">
          <h3 className="text-lg font-semibold mb-3">Register New Device</h3>
          <div className="flex gap-3">
            <input
              type="text"
              placeholder="Device name (e.g. Campus Safety iPad 1)"
              value={newDeviceName}
              onChange={(e) => setNewDeviceName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brass focus:border-transparent"
            />
            <button
              onClick={handleCreate}
              disabled={!newDeviceName.trim()}
              className="px-4 py-2 bg-navy text-bone rounded-lg font-medium hover:bg-navy-700 transition-colors disabled:opacity-50"
            >
              Create & Get QR
            </button>
            <button
              onClick={() => setShowAddForm(false)}
              className="px-4 py-2 text-gray-600 hover:text-gray-800 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {pairingDevice && (
        <div className="bg-white rounded-lg shadow p-8 mb-6 border-2 border-brass">
          <div className="flex items-start gap-8">
            <div className="bg-white p-4 rounded-lg border border-gray-100">
              <QRCodeSVG
                value={JSON.stringify(pairingDevice.pairing_payload)}
                size={200}
                level="M"
              />
            </div>
            <div className="flex-1">
              <h3 className="text-xl font-bold text-navy mb-2">
                Scan to Pair: {pairingDevice.name}
              </h3>
              <p className="text-gray-600 mb-4">
                Open BirdDog on the iPad and scan this QR code to connect it to this server.
                The device will automatically sync permits and lot data.
              </p>
              <div className="bg-gray-50 rounded-lg p-4 text-sm font-mono">
                <div><span className="text-gray-500">Server:</span> {pairingDevice.pairing_payload?.url}</div>
                <div><span className="text-gray-500">API Key:</span> {pairingDevice.api_key.slice(0, 8)}...</div>
                <div><span className="text-gray-500">School:</span> {pairingDevice.pairing_payload?.name || "—"}</div>
              </div>
              <button
                onClick={() => setPairingDevice(null)}
                className="mt-4 px-4 py-2 text-sm text-gray-600 hover:text-gray-800 border border-gray-300 rounded-lg transition-colors"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-gray-500">Loading devices...</p>
      ) : devices.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <p className="text-lg mb-2">No devices registered</p>
          <p className="text-sm">Click "Add Device" to generate a pairing QR code for an iPad.</p>
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Seen</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {devices.map((device) => (
                <tr key={device.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 font-medium text-gray-900">{device.name}</td>
                  <td className="px-6 py-4 text-gray-600 capitalize">{device.device_type}</td>
                  <td className="px-6 py-4 text-gray-600">{formatDate(device.last_seen)}</td>
                  <td className="px-6 py-4 text-gray-600">{formatDate(device.created_at)}</td>
                  <td className="px-6 py-4 text-right">
                    <button
                      onClick={() => handleDelete(device.id)}
                      className="text-red-600 hover:text-red-800 text-sm font-medium transition-colors"
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
