import { useEffect, useState } from "react";
import {
  Alert, App, Badge, Button, Card, Descriptions, Empty, Input, Modal,
  Popconfirm, Segmented, Space, Spin, Tag, Tooltip,
} from "antd";
import { initAuth, isAuthenticated, login, authHeaders, fetchCurrentUser, type AuthUser } from "../auth";
import { isAdminRole } from "../auth";
import { useBranding } from "../useBranding";
import PublicPageNav from "../components/PublicPageNav";
import PublicFooter from "../components/PublicFooter";

interface VoteInfo {
  voter_email: string;
  vote: string;
  comment: string | null;
  voted_at: string;
}

interface CaseSummary {
  id: string;
  ticket_number: string | null;
  plate: string;
  lot: string;
  violation_type: string;
  fine_amount: number;
  issued_at: string;
  appeal_note: string | null;
  committee_notes: string | null;
  committee_status: string | null;
  committee_decision: string | null;
  committee_decided_at: string | null;
  escalated_by: string | null;
  escalated_at: string | null;
  owner_name: string | null;
  officer_name: string | null;
  votes_uphold: number;
  votes_deny: number;
  total_members: number;
  has_voted: boolean;
}

interface CaseDetail extends CaseSummary {
  officer_email: string | null;
  officer_notes: string | null;
  ticket_category: string;
  location_text: string | null;
  vehicle_description: string | null;
  driver_name: string | null;
  dispute_name: string | null;
  dispute_email: string | null;
  additional_photo_count: number;
  appeal_decision: string | null;
  appeal_decided_by: string | null;
  appeal_decision_reason: string | null;
  votes: VoteInfo[];
}

type Filter = "all" | "voting" | "decided";

const STATUS_COLORS: Record<string, string> = {
  voting: "processing",
  decided: "success",
};
const DECISION_COLORS: Record<string, string> = {
  upheld: "green",
  denied: "red",
};

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
  });
}

export default function AppealsCommittee() {
  return (
    <App>
      <CommitteePage />
    </App>
  );
}

function CommitteePage() {
  const brand = useBranding();
  const { message, modal } = App.useApp();
  const [authState, setAuthState] = useState<"loading" | "ready" | "error">("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [voteComment, setVoteComment] = useState("");
  const [voting, setVoting] = useState(false);
  const [accessDenied, setAccessDenied] = useState(false);

  const isAdmin = isAdminRole(user?.role);

  useEffect(() => {
    (async () => {
      try {
        await initAuth();
        const authed = await isAuthenticated();
        if (!authed) {
          sessionStorage.setItem("quarry_return_path", window.location.pathname);
          await login();
          return;
        }
        const u = await fetchCurrentUser();
        setUser(u);
        setAuthState(u ? "ready" : "error");
      } catch {
        setAuthState("error");
      }
    })();
  }, []);

  useEffect(() => {
    if (authState === "ready") loadCases();
  }, [authState]);

  async function loadCases() {
    setLoading(true);
    try {
      const res = await fetch("/api/appeal-committee/cases", { headers: await authHeaders() });
      if (res.status === 403) { setAccessDenied(true); return; }
      if (!res.ok) throw new Error("Failed to load cases");
      setCases(await res.json());
    } catch (e: any) { message.error(e.message); }
    finally { setLoading(false); }
  }

  async function loadDetail(ticketId: string) {
    setDetailLoading(true);
    setSelectedId(ticketId);
    try {
      const res = await fetch(`/api/appeal-committee/cases/${ticketId}`, { headers: await authHeaders() });
      if (!res.ok) throw new Error("Failed to load case");
      setDetail(await res.json());
    } catch (e: any) { message.error(e.message); }
    finally { setDetailLoading(false); }
  }

  async function handleVote(vote: "uphold" | "deny") {
    if (!selectedId) return;
    setVoting(true);
    try {
      const res = await fetch(`/api/appeal-committee/cases/${selectedId}/vote`, {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({ vote, comment: voteComment }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to vote");
      }
      message.success(`Vote cast: ${vote}`);
      setVoteComment("");
      await loadDetail(selectedId);
      await loadCases();
    } catch (e: any) { message.error(e.message); }
    finally { setVoting(false); }
  }

  function handleClose() {
    if (!selectedId || !detail) return;
    let reason = "";
    modal.confirm({
      title: "Close Voting & Record Decision",
      content: (
        <div className="space-y-3">
          <p className="text-sm text-gray-600">
            Current tally: <strong>{detail.votes_uphold}</strong> uphold, <strong>{detail.votes_deny}</strong> deny
            ({detail.total_members - detail.votes_uphold - detail.votes_deny} pending)
          </p>
          <Segmented
            options={[
              { label: "Uphold Appeal (void ticket)", value: "upheld" },
              { label: "Deny Appeal (ticket stands)", value: "denied" },
            ]}
            onChange={(v) => {
              const btn = document.querySelector(".ant-modal-confirm-btns .ant-btn-primary") as HTMLButtonElement;
              if (btn) btn.dataset.decision = v as string;
            }}
            block
          />
          <Input.TextArea
            placeholder="Reason (optional)"
            rows={2}
            onChange={e => { reason = e.target.value; }}
          />
        </div>
      ),
      okText: "Record Decision",
      onOk: async () => {
        const btn = document.querySelector(".ant-modal-confirm-btns .ant-btn-primary") as HTMLButtonElement;
        const decision = btn?.dataset.decision || (detail.votes_uphold >= detail.votes_deny ? "upheld" : "denied");
        const res = await fetch(`/api/appeal-committee/cases/${selectedId}/close`, {
          method: "POST",
          headers: await authHeaders(),
          body: JSON.stringify({ decision, reason }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          message.error(err.detail || "Failed to close");
          throw new Error("abort");
        }
        message.success("Decision recorded");
        await loadDetail(selectedId);
        await loadCases();
      },
    });
  }

  const filtered = cases.filter(c => {
    if (filter === "voting") return c.committee_status === "voting";
    if (filter === "decided") return c.committee_status === "decided";
    return true;
  });

  const counts = {
    all: cases.length,
    voting: cases.filter(c => c.committee_status === "voting").length,
    decided: cases.filter(c => c.committee_status === "decided").length,
  };

  if (authState === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      <PublicPageNav title="Appeals Committee" brand={brand} />

      <div className="flex-1 max-w-5xl mx-auto w-full px-4 py-8">
        {accessDenied ? (
          <Alert
            type="error"
            message="Access Denied"
            description="You are not a member of the appeals committee. Contact an administrator to be added."
            showIcon
          />
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
              <h1 className="text-2xl font-bold">Escalated Appeals</h1>
              <Segmented
                value={filter}
                onChange={v => setFilter(v as Filter)}
                options={[
                  { label: `All (${counts.all})`, value: "all" },
                  { label: `Open (${counts.voting})`, value: "voting" },
                  { label: `Decided (${counts.decided})`, value: "decided" },
                ]}
              />
            </div>

            {loading ? (
              <div className="text-center py-12"><Spin size="large" /></div>
            ) : filtered.length === 0 ? (
              <Empty description="No cases" />
            ) : (
              <div className="space-y-3">
                {filtered.map(c => (
                  <Card
                    key={c.id}
                    size="small"
                    hoverable
                    onClick={() => loadDetail(c.id)}
                    className="cursor-pointer"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-mono font-bold text-sm">
                            {c.ticket_number || c.id.slice(0, 8)}
                          </span>
                          <Tag>{c.violation_type.replace(/_/g, " ")}</Tag>
                          <Tag color={STATUS_COLORS[c.committee_status || ""] || "default"}>
                            {c.committee_status === "voting" ? "Open" : "Decided"}
                          </Tag>
                          {c.committee_decision && (
                            <Tag color={DECISION_COLORS[c.committee_decision] || "default"}>
                              {c.committee_decision === "upheld" ? "Appeal Upheld" : "Appeal Denied"}
                            </Tag>
                          )}
                        </div>
                        <div className="text-xs text-gray-500 space-x-3">
                          <span>Plate: <strong>{c.plate}</strong></span>
                          <span>Lot: {c.lot}</span>
                          <span>${c.fine_amount.toFixed(2)}</span>
                          <span>Issued: {fmtDate(c.issued_at)}</span>
                          {c.owner_name && <span>Owner: {c.owner_name}</span>}
                        </div>
                        {c.appeal_note && (
                          <p className="text-xs text-gray-600 mt-1 line-clamp-2 italic">
                            "{c.appeal_note}"
                          </p>
                        )}
                      </div>
                      <div className="shrink-0 text-right">
                        <VoteTally uphold={c.votes_uphold} deny={c.votes_deny} total={c.total_members} />
                        {!c.has_voted && c.committee_status === "voting" && (
                          <div className="mt-1">
                            <Badge status="warning" text={<span className="text-xs">Needs your vote</span>} />
                          </div>
                        )}
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <PublicFooter brand={brand} />

      {/* Case Detail Modal */}
      <Modal
        open={!!selectedId}
        onCancel={() => { setSelectedId(null); setDetail(null); setVoteComment(""); }}
        width={680}
        title={detail ? `Case: ${detail.ticket_number || detail.id.slice(0, 8)}` : "Loading..."}
        footer={
          detail && detail.committee_status === "voting" ? (
            <div className="flex items-center justify-between">
              <div>
                {isAdmin && (
                  <Button onClick={handleClose}>Close Voting</Button>
                )}
              </div>
              <Space>
                {!detail.has_voted ? (
                  <>
                    <Button
                      type="primary"
                      style={{ background: "#22C55E" }}
                      loading={voting}
                      onClick={() => handleVote("uphold")}
                    >
                      Uphold Appeal
                    </Button>
                    <Button danger loading={voting} onClick={() => handleVote("deny")}>
                      Deny Appeal
                    </Button>
                  </>
                ) : (
                  <Tag color="blue">You have voted</Tag>
                )}
              </Space>
            </div>
          ) : detail?.committee_status === "decided" ? (
            <Tag
              color={DECISION_COLORS[detail.committee_decision || ""] || "default"}
              className="text-sm"
            >
              {detail.committee_decision === "upheld"
                ? "Appeal Upheld — Ticket Voided"
                : "Appeal Denied — Ticket Stands"}
            </Tag>
          ) : null
        }
      >
        {detailLoading || !detail ? (
          <div className="text-center py-8"><Spin /></div>
        ) : (
          <div className="space-y-4">
            {/* Ticket Info */}
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="Plate">
                <span className="font-mono font-bold">{detail.plate}</span>
              </Descriptions.Item>
              <Descriptions.Item label={detail.ticket_category === "moving" ? "Location" : "Lot"}>
                {detail.ticket_category === "moving" ? (detail.location_text || "—") : detail.lot}
              </Descriptions.Item>
              <Descriptions.Item label="Violation">{detail.violation_type.replace(/_/g, " ")}</Descriptions.Item>
              <Descriptions.Item label="Fine">${detail.fine_amount.toFixed(2)}</Descriptions.Item>
              <Descriptions.Item label="Issued">{fmtDateTime(detail.issued_at)}</Descriptions.Item>
              <Descriptions.Item label="Officer">{detail.officer_name || detail.officer_email || "—"}</Descriptions.Item>
              {detail.owner_name && (
                <Descriptions.Item label="Owner" span={2}>{detail.owner_name}</Descriptions.Item>
              )}
              {detail.vehicle_description && (
                <Descriptions.Item label="Vehicle" span={2}>{detail.vehicle_description}</Descriptions.Item>
              )}
              {detail.driver_name && (
                <Descriptions.Item label="Driver">{detail.driver_name}</Descriptions.Item>
              )}
              {detail.officer_notes && (
                <Descriptions.Item label="Officer Notes" span={2}>{detail.officer_notes}</Descriptions.Item>
              )}
            </Descriptions>

            {/* Photo */}
            {detail.additional_photo_count > 0 || true ? (
              <div>
                <div className="text-xs font-medium text-gray-500 mb-1">Citation Photo</div>
                <img
                  src={`/api/appeal-committee/cases/${detail.id}/photo`}
                  alt="Citation"
                  className="max-h-48 rounded border"
                  onError={e => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
              </div>
            ) : null}

            {/* Appeal Note */}
            <Card size="small" title="Student's Appeal" className="!bg-yellow-50">
              <p className="text-sm">{detail.appeal_note || <em className="text-gray-400">No note provided</em>}</p>
              {detail.dispute_name && (
                <p className="text-xs text-gray-500 mt-1">Filed by: {detail.dispute_name} ({detail.dispute_email})</p>
              )}
            </Card>

            {/* Escalation Info */}
            <Card size="small" title="Escalation" className="!bg-purple-50">
              <div className="text-xs text-gray-600 space-y-1">
                <p>Escalated by <strong>{detail.escalated_by}</strong> on {fmtDateTime(detail.escalated_at)}</p>
                {detail.committee_notes && <p className="mt-1">{detail.committee_notes}</p>}
              </div>
            </Card>

            {/* Vote Comment (only when voting is open and user hasn't voted) */}
            {detail.committee_status === "voting" && !detail.has_voted && (
              <div>
                <div className="text-xs font-medium text-gray-500 mb-1">Comment (optional)</div>
                <Input.TextArea
                  value={voteComment}
                  onChange={e => setVoteComment(e.target.value)}
                  placeholder="Add a comment with your vote..."
                  rows={2}
                />
              </div>
            )}

            {/* Votes */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-gray-500">Votes</span>
                <VoteTally uphold={detail.votes_uphold} deny={detail.votes_deny} total={detail.total_members} />
              </div>
              {detail.votes.length === 0 ? (
                <p className="text-xs text-gray-400 italic">No votes yet</p>
              ) : (
                <div className="space-y-2">
                  {detail.votes.map((v, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs">
                      <Tag color={v.vote === "uphold" ? "green" : "red"} className="shrink-0">
                        {v.vote === "uphold" ? "Uphold" : "Deny"}
                      </Tag>
                      <div>
                        <span className="font-medium">{v.voter_email}</span>
                        <span className="text-gray-400 ml-2">{fmtDateTime(v.voted_at)}</span>
                        {v.comment && <p className="text-gray-600 mt-0.5">{v.comment}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Decision result (if decided) */}
            {detail.committee_status === "decided" && (
              <Alert
                type={detail.committee_decision === "upheld" ? "success" : "error"}
                message={detail.committee_decision === "upheld" ? "Appeal Upheld" : "Appeal Denied"}
                description={
                  <div className="text-xs space-y-1">
                    <p>Decision recorded on {fmtDateTime(detail.committee_decided_at)}</p>
                    {detail.appeal_decision_reason && <p>Reason: {detail.appeal_decision_reason}</p>}
                    <p>Decided by: {detail.appeal_decided_by}</p>
                  </div>
                }
                showIcon
              />
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}

function VoteTally({ uphold, deny, total }: { uphold: number; deny: number; total: number }) {
  const pending = Math.max(0, total - uphold - deny);
  return (
    <Tooltip title={`${uphold} uphold, ${deny} deny, ${pending} pending — ${total} members`}>
      <div className="flex items-center gap-1 text-xs">
        <span className="text-green-600 font-bold">{uphold}</span>
        <span className="text-gray-400">/</span>
        <span className="text-red-600 font-bold">{deny}</span>
        <span className="text-gray-400">/</span>
        <span className="text-gray-400">{pending}</span>
      </div>
    </Tooltip>
  );
}
