import { useState } from "react";
import { App, Button, Card, Descriptions, Input, Modal, Space, Tag } from "antd";
import { authHeaders } from "../auth";

interface HoldSummary {
  moravian_id: string;
  name: string | null;
  email: string | null;
  unpaid_tickets: number;
  hold_threshold: number;
  quarry_hold_active: boolean;
  jenzabar_hold_active: boolean | null;
}

function holdTag(active: boolean | null) {
  if (active === null) return <Tag>Unknown</Tag>;
  return active ? <Tag color="red">Active</Tag> : <Tag color="green">None</Tag>;
}

export default function JenzabarHoldLookup({ canRelease }: { canRelease: boolean }) {
  const { message } = App.useApp();
  const [id, setId] = useState("");
  const [loading, setLoading] = useState(false);
  const [releasing, setReleasing] = useState(false);
  const [summary, setSummary] = useState<HoldSummary | null>(null);

  async function lookup(target = id.trim()) {
    if (!target) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/conduct/jenzabar-hold/${encodeURIComponent(target)}`, { headers: await authHeaders() });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "Lookup failed");
      setSummary(body);
    } catch (e: any) {
      message.error(e.message);
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }

  function release() {
    if (!summary) return;
    const owes = summary.unpaid_tickets >= summary.hold_threshold;
    Modal.confirm({
      title: `Remove the parking hold for ${summary.name || summary.moravian_id}?`,
      content: owes
        ? `This student still has ${summary.unpaid_tickets} unpaid tickets (threshold ${summary.hold_threshold}). Quarry may place the hold again on their next ticket.`
        : "This sends the removal flag (N) to Jenzabar. Jenzabar's scheduled job applies it.",
      okText: "Remove hold",
      okButtonProps: { danger: true },
      onOk: async () => {
        setReleasing(true);
        try {
          const headers = { ...(await authHeaders()), "Content-Type": "application/json" };
          const res = await fetch(`/api/conduct/jenzabar-hold/${encodeURIComponent(summary.moravian_id)}/release`, { method: "POST", headers });
          const body = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(body.detail || "Removal failed");
          message.success("Removal flag sent to Jenzabar");
          await lookup(summary.moravian_id);
        } catch (e: any) {
          message.error(e.message);
        } finally {
          setReleasing(false);
        }
      },
    });
  }

  return (
    <Card size="small" title="Jenzabar parking hold" className="mb-4">
      <Space.Compact style={{ width: 320 }}>
        <Input
          placeholder="Moravian ID (e.g. 550534)"
          value={id}
          onChange={e => setId(e.target.value)}
          onPressEnter={() => lookup()}
        />
        <Button type="primary" loading={loading} onClick={() => lookup()}>Look up</Button>
      </Space.Compact>
      {summary && (
        <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }} className="mt-3">
          <Descriptions.Item label="Student">{summary.name || "—"} {summary.email ? `(${summary.email})` : ""}</Descriptions.Item>
          <Descriptions.Item label="Unpaid tickets">{summary.unpaid_tickets} (hold at {summary.hold_threshold})</Descriptions.Item>
          <Descriptions.Item label="Quarry hold">{holdTag(summary.quarry_hold_active)}</Descriptions.Item>
          <Descriptions.Item label="Jenzabar hold">{holdTag(summary.jenzabar_hold_active)}</Descriptions.Item>
          {canRelease && (
            <Descriptions.Item label="Action">
              <Button danger size="small" loading={releasing} onClick={release}>Remove hold in Jenzabar</Button>
            </Descriptions.Item>
          )}
        </Descriptions>
      )}
    </Card>
  );
}
