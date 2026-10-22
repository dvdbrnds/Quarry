import { useCallback, useEffect, useState } from "react";
import { Button, Card, Checkbox, Empty, Input, Popconfirm, Space, Spin, Table, Tag, App } from "antd";
import { authHeaders } from "../auth";

interface Member {
  id: string;
  email: string;
  name: string;
  is_chair: boolean;
  added_by: string;
  added_at: string;
}

export default function CommitteeSettings() {
  const { message } = App.useApp();
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [isChair, setIsChair] = useState(false);
  const [sampleSending, setSampleSending] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/appeal-committee/members", { headers: await authHeaders() });
      if (res.ok) setMembers(await res.json());
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleAdd() {
    if (!email.trim() || !name.trim()) { message.warning("Email and name are required"); return; }
    setAdding(true);
    try {
      const res = await fetch("/api/appeal-committee/members", {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({ email: email.trim(), name: name.trim(), is_chair: isChair }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        message.error(err.detail || "Failed to add member");
        return;
      }
      message.success("Member added");
      setEmail(""); setName(""); setIsChair(false);
      load();
    } catch { message.error("Failed to add member"); }
    finally { setAdding(false); }
  }

  async function handleRemove(id: string) {
    try {
      const res = await fetch(`/api/appeal-committee/members/${id}`, {
        method: "DELETE",
        headers: await authHeaders(),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        message.error(err.detail || `Failed to remove (${res.status})`);
        return;
      }
      message.success("Member removed");
      await load();
    } catch { message.error("Failed to remove"); }
  }

  async function sendSample(decision: "denied" | "approved", committee: boolean) {
    const key = `${decision}-${committee}`;
    setSampleSending(key);
    try {
      const res = await fetch("/api/appeal-committee/sample-decision-email", {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({ decision, committee }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { message.error(data.detail || "Failed to send sample"); return; }
      message.success(`Sample sent to ${data.sent_to}`);
    } catch { message.error("Failed to send sample"); }
    finally { setSampleSending(null); }
  }

  if (loading) return <Spin className="py-8 flex justify-center" />;

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-xl font-bold mb-4">Appeals Committee Members</h3>
        <p className="text-sm text-gray-500 mb-4">
          Committee members can log in at <code>/appeals-committee</code> to review escalated appeals and cast votes.
        </p>
      </div>

      <Card size="small" title="Add Member">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Email</label>
            <Input
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="member@moravian.edu"
              style={{ width: 260 }}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Display Name</label>
            <Input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Dr. Jane Smith"
              style={{ width: 200 }}
            />
          </div>
          <Checkbox checked={isChair} onChange={e => setIsChair(e.target.checked)}>Chair</Checkbox>
          <Button type="primary" onClick={handleAdd} loading={adding}>Add</Button>
        </div>
      </Card>

      {members.length === 0 ? (
        <Empty description="No committee members configured" />
      ) : (
        <Table
          dataSource={members}
          rowKey="id"
          pagination={false}
          size="small"
          columns={[
            {
              title: "Name",
              dataIndex: "name",
              render: (name: string, row: Member) => (
                <span>
                  {name}
                  {row.is_chair && <Tag color="purple" className="ml-2">Chair</Tag>}
                </span>
              ),
            },
            { title: "Email", dataIndex: "email" },
            { title: "Added By", dataIndex: "added_by", responsive: ["md"] as any },
            {
              title: "",
              width: 80,
              render: (_: any, row: Member) => (
                <Popconfirm title="Remove this member?" onConfirm={() => handleRemove(row.id)}>
                  <Button size="small" danger>Remove</Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      )}

      <Card size="small" title="Appeal Decision Emails">
        <p className="text-sm text-gray-500 mb-3">
          Students get an email automatically when an appeal is approved or denied. Send yourself a sample to see what they receive.
        </p>
        <Space wrap>
          <Button loading={sampleSending === "denied-true"} onClick={() => sendSample("denied", true)}>Sample: Denied (committee)</Button>
          <Button loading={sampleSending === "denied-false"} onClick={() => sendSample("denied", false)}>Sample: Denied (office)</Button>
          <Button loading={sampleSending === "approved-true"} onClick={() => sendSample("approved", true)}>Sample: Approved (committee)</Button>
        </Space>
      </Card>
    </div>
  );
}
