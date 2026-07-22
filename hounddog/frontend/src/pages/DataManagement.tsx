import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Card, Table, App, Typography, Switch, Select, TimePicker, InputNumber, Space, Tag, Popconfirm } from "antd";
import { DownloadOutlined, UploadOutlined, DatabaseOutlined, WarningOutlined, DeleteOutlined, ClockCircleOutlined, HistoryOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import { api, BackupSchedule, BackupHistoryEntry } from "../api";
import { authHeaders } from "../auth";

dayjs.extend(relativeTime);

const { Text, Title } = Typography;

export default function DataManagement() {
  const { modal, message } = App.useApp();
  const [tables, setTables] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [clearing, setClearing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Scheduled backup state
  const [schedule, setSchedule] = useState<BackupSchedule | null>(null);
  const [scheduleLoading, setScheduleLoading] = useState(true);
  const [scheduleSaving, setScheduleSaving] = useState(false);
  const [history, setHistory] = useState<BackupHistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

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

  const loadSchedule = useCallback(async () => {
    setScheduleLoading(true);
    try {
      const data = await api.backup.schedule.get();
      setSchedule(data);
    } catch {
      // Schedule endpoint may not exist yet on older backends
    } finally {
      setScheduleLoading(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const data = await api.backup.history.list();
      setHistory(data);
    } catch {
      // Ignore
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => { load(); loadSchedule(); loadHistory(); }, [load, loadSchedule, loadHistory]);

  const handleScheduleToggle = async (enabled: boolean) => {
    if (!schedule) return;
    setScheduleSaving(true);
    try {
      const updated = await api.backup.schedule.set({
        enabled,
        frequency: schedule.frequency || "daily",
        time: schedule.time || "02:00",
        retention_days: schedule.retention_days || 30,
      });
      setSchedule(updated);
      message.success(enabled ? "Scheduled backups enabled" : "Scheduled backups disabled");
    } catch (e: any) {
      message.error(e.message || "Failed to update schedule");
    } finally {
      setScheduleSaving(false);
    }
  };

  const handleScheduleSave = async (patch: Partial<BackupSchedule>) => {
    if (!schedule) return;
    setScheduleSaving(true);
    try {
      const updated = await api.backup.schedule.set({
        enabled: patch.enabled ?? schedule.enabled,
        frequency: patch.frequency ?? schedule.frequency ?? "daily",
        time: patch.time ?? schedule.time ?? "02:00",
        retention_days: patch.retention_days ?? schedule.retention_days ?? 30,
      });
      setSchedule(updated);
      message.success("Backup schedule updated");
    } catch (e: any) {
      message.error(e.message || "Failed to update schedule");
    } finally {
      setScheduleSaving(false);
    }
  };

  const handleDeleteBackup = async (filename: string) => {
    try {
      await api.backup.history.delete(filename);
      message.success("Backup deleted");
      loadHistory();
    } catch (e: any) {
      message.error(e.message || "Failed to delete backup");
    }
  };

  const handleDownloadBackup = async (filename: string) => {
    const headers = await authHeaders();
    const url = api.backup.history.downloadUrl(filename);
    const res = await fetch(url, { headers });
    if (!res.ok) {
      message.error("Download failed");
      return;
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
  };

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
      <div className="flex items-start gap-3 rounded-lg border border-brand-primary/30 bg-gray-50 px-5 py-4 mb-6">
        <DatabaseOutlined className="text-brand-primary text-lg mt-0.5" />
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

      {/* Scheduled Backup Card */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 24 }}>
        <Card style={{ flex: 2, minWidth: 340 }} loading={scheduleLoading}>
          <Title level={5} style={{ marginTop: 0 }}>
            <ClockCircleOutlined style={{ marginRight: 8 }} />
            Scheduled Backups
          </Title>
          <p className="text-ink-mute text-sm mb-4">
            Automatically create backup snapshots on a recurring schedule. Backups are stored on the server and can be downloaded from the history below.
          </p>
          {schedule && (
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium w-20">Enabled</span>
                <Switch
                  checked={schedule.enabled}
                  loading={scheduleSaving}
                  onChange={handleScheduleToggle}
                />
                {schedule.enabled ? (
                  <Tag color="green">Active</Tag>
                ) : (
                  <Tag>Disabled</Tag>
                )}
              </div>

              <div className="flex items-center gap-3">
                <span className="text-sm font-medium w-20">Frequency</span>
                <Select
                  value={schedule.frequency || "daily"}
                  onChange={(v) => handleScheduleSave({ frequency: v })}
                  style={{ width: 140 }}
                  disabled={scheduleSaving}
                  options={[
                    { value: "daily", label: "Daily" },
                    { value: "weekly", label: "Weekly" },
                    { value: "monthly", label: "Monthly" },
                  ]}
                />
              </div>

              <div className="flex items-center gap-3">
                <span className="text-sm font-medium w-20">Time (UTC)</span>
                <TimePicker
                  value={dayjs(schedule.time || "02:00", "HH:mm")}
                  format="HH:mm"
                  onChange={(v) => {
                    if (v) handleScheduleSave({ time: v.format("HH:mm") });
                  }}
                  disabled={scheduleSaving}
                  minuteStep={15}
                />
              </div>

              <div className="flex items-center gap-3">
                <span className="text-sm font-medium w-20">Keep for</span>
                <InputNumber
                  min={1}
                  max={365}
                  value={schedule.retention_days || 30}
                  onChange={(v) => {
                    if (v) handleScheduleSave({ retention_days: v });
                  }}
                  disabled={scheduleSaving}
                  addonAfter="days"
                  style={{ width: 140 }}
                />
              </div>

              {schedule.last_run && (
                <div className="text-xs text-ink-mute mt-1">
                  Last backup: {dayjs(schedule.last_run).fromNow()} ({dayjs(schedule.last_run).format("MMM D, YYYY h:mm A")} UTC)
                </div>
              )}
              {schedule.next_run && schedule.enabled && (
                <div className="text-xs text-ink-mute">
                  Next backup: {dayjs(schedule.next_run).fromNow()} ({dayjs(schedule.next_run).format("MMM D, YYYY h:mm A")} UTC)
                </div>
              )}
            </Space>
          )}
        </Card>

        <Card
          style={{ flex: 3, minWidth: 400 }}
          title={
            <span>
              <HistoryOutlined style={{ marginRight: 8 }} />
              Backup History
              {history.length > 0 && <Tag style={{ marginLeft: 8 }}>{history.length}</Tag>}
            </span>
          }
          size="small"
          extra={
            <Button size="small" onClick={loadHistory} loading={historyLoading}>
              Refresh
            </Button>
          }
        >
          <Table
            dataSource={history}
            loading={historyLoading}
            size="small"
            pagination={{ pageSize: 5, size: "small" }}
            locale={{ emptyText: "No scheduled backups yet" }}
            rowKey="filename"
            columns={[
              {
                title: "File",
                dataIndex: "filename",
                key: "filename",
                render: (name: string) => (
                  <span className="font-mono text-xs">{name}</span>
                ),
              },
              {
                title: "Size",
                dataIndex: "size_bytes",
                key: "size",
                width: 100,
                render: (bytes: number) => {
                  if (bytes < 1024) return `${bytes} B`;
                  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
                  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
                },
              },
              {
                title: "Created",
                dataIndex: "created_at",
                key: "created_at",
                width: 160,
                render: (dt: string) => (
                  <span title={dt}>{dayjs(dt).fromNow()}</span>
                ),
              },
              {
                title: "",
                key: "actions",
                width: 120,
                render: (_: any, record: BackupHistoryEntry) => (
                  <Space size="small">
                    <Button
                      size="small"
                      type="link"
                      icon={<DownloadOutlined />}
                      onClick={() => handleDownloadBackup(record.filename)}
                    />
                    <Popconfirm
                      title="Delete this backup?"
                      onConfirm={() => handleDeleteBackup(record.filename)}
                      okText="Delete"
                      okType="danger"
                    >
                      <Button size="small" type="link" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
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
