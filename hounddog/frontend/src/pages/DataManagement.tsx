import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Card, Table, App, Typography } from "antd";
import { DownloadOutlined, UploadOutlined, DatabaseOutlined, WarningOutlined, DeleteOutlined } from "@ant-design/icons";
import { api } from "../api";
import { authHeaders } from "../auth";

const { Text, Title } = Typography;

export default function DataManagement() {
  const { modal, message } = App.useApp();
  const [tables, setTables] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [clearing, setClearing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.backup.tables();
      setTables(data.tables);
    } catch {
      message.error("Failed to load table info");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => { load(); }, [load]);

  const totalRows = Object.values(tables).reduce((a, b) => a + b, 0);

  const tableData = Object.entries(tables).map(([name, count]) => ({
    key: name,
    name,
    count,
  }));

  const handleExport = async () => {
    setExporting(true);
    try {
      const headers = await authHeaders();
      const res = await fetch(api.backup.exportUrl, { headers });
      if (!res.ok) throw new Error(`Export failed: ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const disposition = res.headers.get("Content-Disposition");
      const match = disposition?.match(/filename="(.+)"/);
      a.download = match?.[1] || `quarry_backup_${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      message.success("Backup downloaded successfully");
    } catch (e: any) {
      message.error(e.message || "Export failed");
    } finally {
      setExporting(false);
    }
  };

  const handleRestore = (file: File) => {
    if (!file.name.endsWith(".json")) {
      message.error("Please select a .json backup file");
      return;
    }

    modal.confirm({
      title: "Restore Database from Backup",
      icon: <WarningOutlined style={{ color: "#ff4d4f" }} />,
      content: (
        <div>
          <p style={{ fontWeight: 600, color: "#ff4d4f" }}>
            This will permanently replace ALL existing data with the contents of the backup file.
          </p>
          <p>File: <span className="font-mono text-xs">{file.name}</span></p>
          <p>Size: {(file.size / 1024).toFixed(1)} KB</p>
          <p style={{ marginTop: 12 }}>
            This action cannot be undone. Make sure you have exported a backup of your current data first.
          </p>
        </div>
      ),
      okText: "Restore",
      okType: "danger",
      cancelText: "Cancel",
      width: 500,
      onOk: async () => {
        setRestoring(true);
        try {
          const result = await api.backup.restore(file);
          const totalRestored = Object.values(result.restored).reduce((a, b) => a + b, 0);
          message.success(`Restored ${totalRestored.toLocaleString()} rows across ${Object.keys(result.restored).length} tables`);
          load();
        } catch (e: any) {
          message.error(e.message || "Restore failed");
        } finally {
          setRestoring(false);
          if (fileInputRef.current) fileInputRef.current.value = "";
        }
      },
      onCancel: () => {
        if (fileInputRef.current) fileInputRef.current.value = "";
      },
    });
  };

  const ticketCount = tables["tickets"] ?? 0;

  const handleClearTickets = () => {
    modal.confirm({
      title: "Clear All Tickets",
      icon: <WarningOutlined style={{ color: "#ff4d4f" }} />,
      content: (
        <div>
          <p style={{ fontWeight: 600, color: "#ff4d4f" }}>
            This will permanently delete all {ticketCount.toLocaleString()} tickets and their associated payment records.
          </p>
          <p style={{ marginTop: 12 }}>
            This is intended for clearing test data before going live. This action cannot be undone.
          </p>
        </div>
      ),
      okText: `Delete ${ticketCount.toLocaleString()} Tickets`,
      okType: "danger",
      cancelText: "Cancel",
      width: 480,
      onOk: async () => {
        setClearing(true);
        try {
          const result = await api.backup.clearTickets();
          message.success(`Cleared ${result.deleted.toLocaleString()} tickets`);
          load();
        } catch (e: any) {
          message.error(e.message || "Failed to clear tickets");
        } finally {
          setClearing(false);
        }
      },
    });
  };

  return (
    <div>
      <div className="flex items-start gap-3 rounded-lg border border-brass/30 bg-bone-light px-5 py-4 mb-6">
        <DatabaseOutlined className="text-brass text-lg mt-0.5" />
        <div>
          <div className="font-semibold text-ink mb-1">Database Backup & Restore</div>
          <div className="text-ink-mute text-sm">
            Export a complete snapshot of all application data (permits, tickets, lots, audit trail, settings, etc.) or restore from a previously saved backup. Backups do not include uploaded files or application code.
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 24 }}>
        <Card style={{ flex: 1, minWidth: 280 }}>
          <Title level={5} style={{ marginTop: 0 }}>
            <DownloadOutlined style={{ marginRight: 8 }} />
            Export Backup
          </Title>
          <p className="text-ink-mute text-sm mb-4">
            Download a JSON file containing all {totalRows.toLocaleString()} rows across {Object.keys(tables).length} tables.
          </p>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={handleExport}
            loading={exporting}
            size="large"
          >
            Download Backup
          </Button>
        </Card>

        <Card style={{ flex: 1, minWidth: 280 }}>
          <Title level={5} style={{ marginTop: 0 }}>
            <UploadOutlined style={{ marginRight: 8 }} />
            Restore from Backup
          </Title>
          <p className="text-ink-mute text-sm mb-4">
            Upload a previously exported backup file to replace all current data.
          </p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            style={{ display: "none" }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleRestore(file);
            }}
          />
          <Button
            danger
            icon={<UploadOutlined />}
            onClick={() => fileInputRef.current?.click()}
            loading={restoring}
            size="large"
          >
            Upload & Restore
          </Button>
        </Card>

        <Card style={{ flex: 1, minWidth: 280 }}>
          <Title level={5} style={{ marginTop: 0 }}>
            <DeleteOutlined style={{ marginRight: 8 }} />
            Clear Test Tickets
          </Title>
          <p className="text-ink-mute text-sm mb-4">
            Delete all {ticketCount.toLocaleString()} tickets and associated payments. Use before going live.
          </p>
          <Button
            danger
            icon={<DeleteOutlined />}
            onClick={handleClearTickets}
            loading={clearing}
            disabled={ticketCount === 0}
            size="large"
          >
            Clear All Tickets
          </Button>
        </Card>
      </div>

      <Card title="Current Database Contents" size="small">
        <Table
          dataSource={tableData}
          loading={loading}
          size="small"
          pagination={false}
          columns={[
            {
              title: "Table",
              dataIndex: "name",
              key: "name",
              render: (name: string) => (
                <span className="font-mono text-xs">{name}</span>
              ),
            },
            {
              title: "Rows",
              dataIndex: "count",
              key: "count",
              align: "right" as const,
              render: (count: number) => count.toLocaleString(),
              sorter: (a: { count: number }, b: { count: number }) => a.count - b.count,
            },
          ]}
          summary={() => (
            <Table.Summary.Row>
              <Table.Summary.Cell index={0}>
                <Text strong>Total</Text>
              </Table.Summary.Cell>
              <Table.Summary.Cell index={1} align="right">
                <Text strong>{totalRows.toLocaleString()}</Text>
              </Table.Summary.Cell>
            </Table.Summary.Row>
          )}
        />
      </Card>
    </div>
  );
}
