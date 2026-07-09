import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { api, Device } from "../api";
import { Table, Button, Input, Card, Space, Empty, App, Spin } from "antd";
import type { ColumnsType } from "antd/es/table";

export default function Devices() {
  const { modal, message } = App.useApp();
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [newDeviceName, setNewDeviceName] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [pairingDevice, setPairingDevice] = useState<Device | null>(null);
  const [creating, setCreating] = useState(false);

  async function loadDevices() {
    setLoading(true);
    try { setDevices(await api.devices.list()); }
    catch { message.error("Failed to load devices"); }
    finally { setLoading(false); }
  }

  useEffect(() => { loadDevices(); }, []);

  async function handleCreate() {
    if (!newDeviceName.trim()) return;
    setCreating(true);
    try {
      const device = await api.devices.create({ name: newDeviceName.trim() });
      setPairingDevice(device);
      message.success("Device created");
      setNewDeviceName(""); setShowAddForm(false);
      await loadDevices();
    } catch { message.error("Failed to create device"); }
    finally { setCreating(false); }
  }

  function handleDelete(id: string) {
    modal.confirm({
      title: "Revoke this device?",
      content: "It will no longer be able to sync.",
      okText: "Revoke", okButtonProps: { danger: true },
      onOk: async () => {
        try { await api.devices.delete(id); message.success("Device revoked"); await loadDevices(); }
        catch { message.error("Failed to revoke device"); }
      },
    });
  }

  const columns: ColumnsType<Device> = [
    { title: "Name", dataIndex: "name", key: "name", render: (v) => <span className="font-medium">{v}</span> },
    { title: "Type", dataIndex: "device_type", key: "type", render: (v) => <span className="capitalize">{v}</span> },
    { title: "Last Seen", dataIndex: "last_seen", key: "last_seen", render: (d) => d ? new Date(d).toLocaleString() : "Never" },
    { title: "Created", dataIndex: "created_at", key: "created_at", render: (d) => d ? new Date(d).toLocaleString() : "—" },
    {
      title: "Actions", key: "actions", align: "right" as const,
      render: (_, d) => <Button type="link" danger size="small" onClick={() => handleDelete(d.id)}>Revoke</Button>,
    },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-navy">Devices</h2>
        <Button type="primary" onClick={() => setShowAddForm(true)}>+ Add Device</Button>
      </div>

      {showAddForm && (
        <Card className="mb-6" title="Register New Device">
          <Space>
            <Input placeholder="Device name (e.g. Campus Safety iPad 1)" value={newDeviceName}
              onChange={e => setNewDeviceName(e.target.value)}
              onPressEnter={handleCreate} style={{ width: 350 }} />
            <Button type="primary" onClick={handleCreate} disabled={!newDeviceName.trim()} loading={creating}>Create & Get QR</Button>
            <Button onClick={() => setShowAddForm(false)}>Cancel</Button>
          </Space>
        </Card>
      )}

      {pairingDevice && (
        <Card className="mb-6 !border-2 !border-brass">
          <div className="flex items-start gap-8">
            <div className="bg-white p-4 rounded-lg border border-gray-100">
              <QRCodeSVG value={JSON.stringify(pairingDevice.pairing_payload)} size={200} level="M" />
            </div>
            <div className="flex-1">
              <h3 className="text-xl font-bold text-navy mb-2">Scan to Pair: {pairingDevice.name}</h3>
              <p className="text-gray-600 mb-4">
                Open BirdDog on the iPad and scan this QR code to connect it to this server.
              </p>
              <div className="bg-gray-50 rounded-lg p-4 text-sm font-mono">
                <div><span className="text-gray-500">Server:</span> {pairingDevice.pairing_payload?.url}</div>
                <div><span className="text-gray-500">API Key:</span> {pairingDevice.api_key.slice(0, 8)}...</div>
                <div><span className="text-gray-500">School:</span> {pairingDevice.pairing_payload?.name || "—"}</div>
              </div>
              <Button className="mt-4" onClick={() => setPairingDevice(null)}>Done</Button>
            </div>
          </div>
        </Card>
      )}

      <Table dataSource={devices} columns={columns} rowKey="id" loading={loading} size="small"
        pagination={false}
        locale={{ emptyText: <Empty description="No devices registered. Click '+ Add Device' to generate a pairing QR code." /> }}
      />
    </div>
  );
}
