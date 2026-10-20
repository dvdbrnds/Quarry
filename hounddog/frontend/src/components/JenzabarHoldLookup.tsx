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

interface StaleHolds {
  active_in_jenzabar: number;
  to_clear: HoldSummary[];
  still_owed: HoldSummary[];
  unknown: HoldSummary[];
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
  const [placing, setPlacing] = useState(false);
  const [summary, setSummary] = useState<HoldSummary | null>(null);
  const [matches, setMatches] = useState<{ moravian_id: string; name: string | null; email: string | null }[] | null>(null);
  const [stale, setStale] = useState<StaleHolds | null>(null);

  async function search(q: string): Promise<void> {
    setLoading(true);
    setSummary(null);
    try {
      const res = await fetch(`/api/conduct/jenzabar-hold/search?q=${encodeURIComponent(q)}`, { headers: await authHeaders() });
      const body = await res.json().catch(() => []);
      if (!res.ok) throw new Error(body.detail || "Search failed");
      if (body.length === 0) message.info("No student with a Moravian ID matches that name or email");
      else if (body.length === 1) { setLoading(false); return lookup(body[0].moravian_id); }
      else setMatches(body);
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setLoading(false);
    }
  }
  const [scanning, setScanning] = useState(false);

  async function scan() {
    setScanning(true);
    try {
      const res = await fetch("/api/conduct/jenzabar-hold/stale", { headers: await authHeaders() });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "Scan failed");
      setStale(body);
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setScanning(false);
    }
  }

  function releaseAll() {
    if (!stale?.to_clear.length) return;
    Modal.confirm({
      title: `Remove ${stale.to_clear.length} parking hold(s) in Jenzabar?`,
      content: "Each of these students is under the hold threshold in Quarry. This sends the removal flag (N) for each one.",
      okText: "Remove all",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const headers = { ...(await authHeaders()), "Content-Type": "application/json" };
          const res = await fetch("/api/conduct/jenzabar-hold/release-stale", { method: "POST", headers });
          const body = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(body.detail || "Removal failed");
          if (body.failed?.length) message.warning(`Sent ${body.sent.length}; failed for ${body.failed.join(", ")}`);
          else message.success(`Removal flag sent for ${body.sent.length} student(s)`);
          await scan();
        } catch (e: any) {
          message.error(e.message);
        }
      },
    });
  }

  async function lookup(target = id.trim()): Promise<void> {
    if (!target) return;
    setMatches(null);
    if (!/^\d+$/.test(target)) return search(target);
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

  function place() {
    if (!summary) return;
    const under = summary.unpaid_tickets < summary.hold_threshold;
    Modal.confirm({
      title: `Place a parking hold in Jenzabar for ${summary.name || summary.moravian_id}?`,
      content: under
        ? `This student has only ${summary.unpaid_tickets} unpaid ticket(s), under the hold threshold of ${summary.hold_threshold}. Place the hold anyway?`
        : `This sends the hold flag (Y) to Jenzabar for ${summary.unpaid_tickets} unpaid tickets. Jenzabar's scheduled job applies it.`,
      okText: "Place hold",
      onOk: async () => {
        setPlacing(true);
        try {
          const headers = { ...(await authHeaders()), "Content-Type": "application/json" };
          const res = await fetch(`/api/conduct/jenzabar-hold/${encodeURIComponent(summary.moravian_id)}/apply`, { method: "POST", headers });
          const body = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(body.detail || "Placing the hold failed");
          message.success(body.opened_quarry_hold ? "Hold sent to Jenzabar and recorded in Quarry" : "Hold sent to Jenzabar");
          await lookup(summary.moravian_id);
        } catch (e: any) {
          message.error(e.message);
        } finally {
          setPlacing(false);
        }
      },
    });
  }

  return (
    <Card size="small" title="Jenzabar parking hold" className="mb-4">
      <Space.Compact style={{ width: 360 }}>
        <Input
          placeholder="Name, email, or Moravian ID"
          value={id}
          onChange={e => setId(e.target.value)}
          onPressEnter={() => lookup()}
        />
        <Button type="primary" loading={loading} onClick={() => lookup()}>Look up</Button>
      </Space.Compact>
      <Button className="ml-2" loading={scanning} onClick={scan}>Find holds to clear</Button>
      {matches && (
        <div className="mt-2">
          {matches.map(m => (
            <Button key={m.moravian_id} size="small" className="mr-2 mb-1" onClick={() => { setId(m.moravian_id); lookup(m.moravian_id); }}>
              {m.name || "—"} · {m.email || "no email"} · {m.moravian_id}
            </Button>
          ))}
        </div>
      )}
      {stale && (
        <div className="mt-3 text-sm">
          <div>
            {stale.active_in_jenzabar} active in Jenzabar · <b>{stale.to_clear.length} to clear</b> (under threshold) ·{" "}
            {stale.still_owed.length} still owe · {stale.unknown.length} not in Quarry (review by hand)
          </div>
          {stale.to_clear.length > 0 && (
            <div className="mt-2">
              {stale.to_clear.map(s => (
                <Tag key={s.moravian_id} className="mb-1">{s.moravian_id} {s.name || ""} ({s.unpaid_tickets})</Tag>
              ))}
              {canRelease && <div className="mt-2"><Button danger size="small" onClick={releaseAll}>Remove all {stale.to_clear.length}</Button></div>}
            </div>
          )}
          {stale.unknown.length > 0 && (
            <div className="mt-2 text-gray-500">Not in Quarry: {stale.unknown.map(s => s.moravian_id).join(", ")}</div>
          )}
        </div>
      )}
      {summary && (
        <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }} className="mt-3">
          <Descriptions.Item label="Student">{summary.name || "—"} {summary.email ? `(${summary.email})` : ""}</Descriptions.Item>
          <Descriptions.Item label="Unpaid tickets">{summary.unpaid_tickets} (hold at {summary.hold_threshold})</Descriptions.Item>
          <Descriptions.Item label="Quarry hold">{holdTag(summary.quarry_hold_active)}</Descriptions.Item>
          <Descriptions.Item label="Jenzabar hold">{holdTag(summary.jenzabar_hold_active)}</Descriptions.Item>
          {canRelease && (
            <Descriptions.Item label="Action">
              <Space>
                <Button type="primary" size="small" loading={placing} onClick={place}>Place hold in Jenzabar</Button>
                <Button danger size="small" loading={releasing} onClick={release}>Remove hold in Jenzabar</Button>
              </Space>
            </Descriptions.Item>
          )}
        </Descriptions>
      )}
    </Card>
  );
}
