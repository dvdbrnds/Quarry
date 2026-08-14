import { useEffect, useState } from "react";
import {
  Alert, Button, InputNumber, Modal, Progress, Radio, Space, Statistic, Table, Tag, App,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { authHeaders } from "../auth";

const fmtDollars = (val: string | number) =>
  `$${Number(val).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;

interface PreviewRow {
  id: string;
  customer_name: string | null;
  customer_email: string | null;
  description: string | null;
  amount: string;
  amount_refunded: string;
  refundable: string;
  eligible: boolean;
  proposed: string | null;
  skip_reason: string | null;
}

interface PreviewResponse {
  eligible: PreviewRow[];
  skipped: PreviewRow[];
  eligible_count: number;
  skipped_count: number;
  total_refund: string;
}

interface StreamItem {
  event: "start" | "item" | "done";
  index?: number;
  total?: number;
  id?: string;
  status?: "succeeded" | "failed" | "skipped";
  reason?: string;
  refund_id?: string;
  amount?: string;
  customer_email?: string | null;
  customer_name?: string | null;
  succeeded?: number;
  failed?: number;
  skipped?: number;
}

interface Props {
  open: boolean;
  transactionIds: string[];
  onClose: () => void;
  onFinished: () => void;
}

export default function BulkRefundModal({ open, transactionIds, onClose, onFinished }: Props) {
  const { message, modal } = App.useApp();
  const [mode, setMode] = useState<"flat" | "percent">("flat");
  const [amount, setAmount] = useState<number | null>(100);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number }>({ done: 0, total: 0 });
  const [log, setLog] = useState<StreamItem[]>([]);
  const [summary, setSummary] = useState<{ succeeded: number; failed: number; skipped: number } | null>(null);

  useEffect(() => {
    if (!open) {
      setPreview(null);
      setPreviewError(null);
      setRunning(false);
      setProgress({ done: 0, total: 0 });
      setLog([]);
      setSummary(null);
      setMode("flat");
      setAmount(100);
    }
  }, [open]);

  async function loadPreview() {
    if (amount == null || amount <= 0) {
      message.warning("Enter a refund amount");
      return;
    }
    setPreviewLoading(true);
    setPreviewError(null);
    setSummary(null);
    setLog([]);
    try {
      const res = await fetch("/api/payments/bulk-refund/preview", {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({
          transaction_ids: transactionIds,
          mode,
          amount,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      setPreview(await res.json());
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : String(err));
      setPreview(null);
    } finally {
      setPreviewLoading(false);
    }
  }

  async function runRefunds(ids: string[]) {
    if (!ids.length) return;
    setRunning(true);
    setSummary(null);
    setLog([]);
    setProgress({ done: 0, total: ids.length });
    const items: StreamItem[] = [];
    try {
      const res = await fetch("/api/payments/bulk-refund", {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({
          transaction_ids: ids,
          mode,
          amount,
          confirm: true,
        }),
      });
      if (!res.ok || !res.body) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const evt = JSON.parse(line) as StreamItem;
          if (evt.event === "start") {
            setProgress({ done: 0, total: evt.total || ids.length });
          } else if (evt.event === "item") {
            items.push(evt);
            setLog([...items]);
            setProgress({ done: evt.index || items.length, total: evt.total || ids.length });
          } else if (evt.event === "done") {
            setSummary({
              succeeded: evt.succeeded || 0,
              failed: evt.failed || 0,
              skipped: evt.skipped || 0,
            });
          }
        }
      }
      onFinished();
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  function handleConfirm() {
    if (!preview || preview.eligible_count === 0) return;
    const total = fmtDollars(preview.total_refund);
    const count = preview.eligible_count;
    modal.confirm({
      title: "Confirm bulk refund",
      content: `You are about to refund ${total} across ${count} transaction${count === 1 ? "" : "s"}. Confirm?`,
      okText: "Issue refunds",
      okButtonProps: { danger: true },
      onOk: () => runRefunds(preview.eligible.map((r) => r.id)),
    });
  }

  function handleRetryFailed() {
    const failedIds = log.filter((i) => i.status === "failed" && i.id).map((i) => i.id as string);
    if (!failedIds.length) {
      message.info("No failed refunds to retry");
      return;
    }
    modal.confirm({
      title: "Retry failed refunds",
      content: `Retry ${failedIds.length} failed transaction${failedIds.length === 1 ? "" : "s"}? Successful refunds will not be sent again.`,
      okText: "Retry failed",
      onOk: () => runRefunds(failedIds),
    });
  }

  const previewRows: PreviewRow[] = preview
    ? [...preview.eligible, ...preview.skipped].sort((a, b) =>
        (a.customer_email || "").localeCompare(b.customer_email || "", undefined, { sensitivity: "base" }),
      )
    : [];

  const columns: ColumnsType<PreviewRow> = [
    {
      title: "Customer",
      key: "customer",
      ellipsis: true,
      render: (_, r) => r.customer_name || r.customer_email || "—",
    },
    {
      title: "Email",
      dataIndex: "customer_email",
      ellipsis: true,
      render: (v) => v || "—",
    },
    {
      title: "Original",
      dataIndex: "amount",
      align: "right",
      render: (v) => fmtDollars(v),
    },
    {
      title: "Already refunded",
      dataIndex: "amount_refunded",
      align: "right",
      render: (v) => Number(v) > 0 ? fmtDollars(v) : "—",
    },
    {
      title: "Refundable",
      dataIndex: "refundable",
      align: "right",
      render: (v) => fmtDollars(v),
    },
    {
      title: "This refund",
      key: "proposed",
      align: "right",
      render: (_, r) =>
        r.eligible && r.proposed
          ? <span className="font-semibold text-green-700">{fmtDollars(r.proposed)}</span>
          : <span className="text-red-600 text-xs">{r.skip_reason || "Skipped"}</span>,
    },
  ];

  const failedCount = log.filter((i) => i.status === "failed").length;

  return (
    <Modal
      title="Bulk Refund"
      open={open}
      onCancel={onClose}
      width={920}
      footer={
        summary ? (
          <Space>
            {failedCount > 0 && (
              <Button onClick={handleRetryFailed} disabled={running}>Retry failed</Button>
            )}
            <Button type="primary" onClick={onClose}>Done</Button>
          </Space>
        ) : (
          <Space>
            <Button onClick={onClose} disabled={running}>Cancel</Button>
            <Button onClick={loadPreview} loading={previewLoading} disabled={running || amount == null}>
              Preview
            </Button>
            <Button
              type="primary"
              danger
              onClick={handleConfirm}
              disabled={!preview || preview.eligible_count === 0 || running}
              loading={running}
            >
              Issue refunds
            </Button>
          </Space>
        )
      }
    >
      <p className="text-sm text-ink-mute mb-3">
        {transactionIds.length} transaction{transactionIds.length === 1 ? "" : "s"} in the current selection.
        Enter a flat dollar amount per charge (or a percentage of the original), then preview before confirming.
      </p>

      <Space className="mb-4" wrap>
        <Radio.Group
          value={mode}
          onChange={(e) => { setMode(e.target.value); setPreview(null); setSummary(null); }}
          disabled={running}
          optionType="button"
          options={[
            { label: "Flat $", value: "flat" },
            { label: "Percent %", value: "percent" },
          ]}
        />
        <InputNumber
          min={0.01}
          max={mode === "percent" ? 100 : 10000}
          step={mode === "percent" ? 1 : 1}
          value={amount}
          onChange={(v) => { setAmount(v); setPreview(null); setSummary(null); }}
          addonBefore={mode === "flat" ? "$" : undefined}
          addonAfter={mode === "percent" ? "%" : undefined}
          disabled={running}
          style={{ width: 160 }}
        />
      </Space>

      {previewError && <Alert type="error" message={previewError} className="mb-3" showIcon />}

      {preview && !running && !summary && (
        <div className="flex gap-6 mb-3">
          <Statistic title="Eligible" value={preview.eligible_count} />
          <Statistic title="Skipped" value={preview.skipped_count} />
          <Statistic title="Total to refund" value={fmtDollars(preview.total_refund)} />
        </div>
      )}

      {preview && !summary && (
        <Table
          dataSource={previewRows}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={false}
          scroll={{ y: 280 }}
          rowClassName={(r) => (r.eligible ? "" : "opacity-60")}
        />
      )}

      {running && (
        <div className="mt-4">
          <Progress
            percent={progress.total ? Math.round((progress.done / progress.total) * 100) : 0}
            status="active"
            format={() => `${progress.done} / ${progress.total}`}
          />
        </div>
      )}

      {(running || summary) && log.length > 0 && (
        <div className="mt-3 max-h-56 overflow-auto text-xs font-mono border rounded p-2 bg-gray-50">
          {log.map((item, i) => (
            <div key={`${item.id}-${i}`} className="flex gap-2 py-0.5">
              <Tag
                color={item.status === "succeeded" ? "green" : item.status === "failed" ? "red" : "orange"}
                className="m-0"
              >
                {item.status}
              </Tag>
              <span>{item.customer_name || item.customer_email || item.id}</span>
              {item.amount && <span className="ml-auto">{fmtDollars(item.amount)}</span>}
              {item.reason && <span className="text-red-600">{item.reason}</span>}
            </div>
          ))}
        </div>
      )}

      {summary && (
        <Alert
          className="mt-4"
          type={summary.failed > 0 ? "warning" : "success"}
          showIcon
          message={`Finished: ${summary.succeeded} succeeded, ${summary.failed} failed, ${summary.skipped} skipped`}
        />
      )}
    </Modal>
  );
}
