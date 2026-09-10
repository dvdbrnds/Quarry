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
  updated_at: string | null;
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
  status: string;
  location_text: string | null;
  location_lat: number | null;
  location_lng: number | null;
  vehicle_description: string | null;
  driver_name: string | null;
  driver_license: string | null;
  dispute_name: string | null;
  dispute_email: string | null;
  dispute_phone: string | null;
  photo_url: string | null;
  additional_photo_count: number;
  additional_violations: { code: string; label: string; fine: string }[] | null;
  permit_number: string | null;
  permit_type_label: string | null;
  permit_lot_zone: string | null;
  ocr_original_plate: string | null;
  appeal_decision: string | null;
  appeal_decided_by: string | null;
  appeal_decision_reason: string | null;
  created_at: string | null;
  updated_at: string | null;
  votes: VoteInfo[];
  my_vote: string | null;
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
  const [filter, setFilter] = useState<Filter>("voting");
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
      const result = await res.json();
      message.success(result.changed_from ? `Vote changed to: ${vote}` : `Vote cast: ${vote}`);
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
                {detail.my_vote && (
                  <Tag color={detail.my_vote === "uphold" ? "green" : "red"} className="mr-1">
                    You voted: {detail.my_vote === "uphold" ? "Uphold" : "Deny"}
                  </Tag>
                )}
                <Button
                  type="primary"
                  style={{ background: "#22C55E" }}
                  loading={voting}
                  disabled={detail.my_vote === "uphold"}
                  onClick={() => handleVote("uphold")}
                >
                  {detail.my_vote && detail.my_vote !== "uphold" ? "Change to Uphold" : "Uphold Appeal"}
                </Button>
                <Button
                  danger
                  loading={voting}
                  disabled={detail.my_vote === "deny"}
                  onClick={() => handleVote("deny")}
                >
                  {detail.my_vote && detail.my_vote !== "deny" ? "Change to Deny" : "Deny Appeal"}
                </Button>
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
            {/* Full Ticket Info */}
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="Plate">
                <span className="font-mono font-bold">{detail.plate}</span>
                {detail.ocr_original_plate && (
                  <Tag color="volcano" className="ml-2" style={{ fontSize: 11 }}>
                    OCR read: {detail.ocr_original_plate}
                  </Tag>
                )}
              </Descriptions.Item>
              <Descriptions.Item label={detail.ticket_category === "moving" ? "Location" : "Lot"}>
                {detail.ticket_category === "moving" ? (detail.location_text || "—") : detail.lot}
              </Descriptions.Item>
              <Descriptions.Item label="Violation">
                <Tag color="blue" className="capitalize">{detail.violation_type.replace(/_/g, " ")}</Tag>
                {detail.additional_violations?.map((v, i) => (
                  <Tag key={i} color="blue" className="capitalize">{v.label || v.code.replace(/_/g, " ")}</Tag>
                ))}
              </Descriptions.Item>
              <Descriptions.Item label="Fine">${detail.fine_amount.toFixed(2)}</Descriptions.Item>
              <Descriptions.Item label="Status"><Tag color={detail.status === "escalated" ? "purple" : "default"}>{detail.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="Officer">
                <div>{detail.officer_name || "—"}</div>
                {detail.officer_email && <div className="text-xs text-gray-400">{detail.officer_email}</div>}
              </Descriptions.Item>
              {detail.owner_name && <Descriptions.Item label="Owner">{detail.owner_name}</Descriptions.Item>}
              {detail.permit_number && <Descriptions.Item label="Permit #">{detail.permit_number}</Descriptions.Item>}
              {detail.permit_type_label && <Descriptions.Item label="Permit Type">{detail.permit_type_label}</Descriptions.Item>}
              {detail.permit_lot_zone && <Descriptions.Item label="Permit Lot">{detail.permit_lot_zone}</Descriptions.Item>}
              <Descriptions.Item label="Issued" span={2}>{fmtDateTime(detail.issued_at)}</Descriptions.Item>
              {detail.location_lat && detail.location_lng && (
                <Descriptions.Item label="GPS" span={2}>
                  <a
                    href={`https://maps.google.com/?q=${detail.location_lat},${detail.location_lng}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline font-mono text-xs"
                  >
                    {detail.location_lat.toFixed(6)}, {detail.location_lng.toFixed(6)}
                  </a>
                </Descriptions.Item>
              )}
            </Descriptions>

            {/* Activity Log */}
            <div className="bg-gray-50 rounded-lg px-3 py-2 text-xs text-gray-500">
              <div className="font-medium text-gray-600 mb-2">Activity Log</div>
              <div className="space-y-1.5 border-l-2 border-gray-200 pl-3 ml-1">
                <div className="relative">
                  <span className="absolute -left-[11px] top-1 w-2 h-2 rounded-full bg-gray-300" />
                  <span className="text-gray-400">{fmtDateTime(detail.created_at)}</span>
                  <span className="ml-2">Ticket issued</span>
                </div>
                {detail.appeal_note && (
                  <div className="relative">
                    <span className="absolute -left-[11px] top-1 w-2 h-2 rounded-full bg-yellow-400" />
                    <span className="text-gray-400">{fmtDateTime(detail.updated_at)}</span>
                    <span className="ml-2">Appeal submitted by student</span>
                  </div>
                )}
                {detail.escalated_at && (
                  <div className="relative">
                    <span className="absolute -left-[11px] top-1 w-2 h-2 rounded-full bg-purple-400" />
                    <span className="text-gray-400">{fmtDateTime(detail.escalated_at)}</span>
                    <span className="ml-2">Escalated to committee by <strong>{detail.escalated_by}</strong></span>
                  </div>
                )}
                {detail.votes.map((v, i) => (
                  <div key={i} className="relative">
                    <span className={`absolute -left-[11px] top-1 w-2 h-2 rounded-full ${v.vote === "uphold" ? "bg-green-400" : "bg-red-400"}`} />
                    <span className="text-gray-400">{fmtDateTime(v.voted_at)}</span>
                    <span className="ml-2">
                      <strong>{v.voter_email}</strong> voted <Tag color={v.vote === "uphold" ? "green" : "red"} className="!text-[10px] !px-1 !py-0 !leading-4">{v.vote === "uphold" ? "Uphold" : "Deny"}</Tag>
                    </span>
                    {v.updated_at && (
                      <span className="text-orange-500 ml-1">(changed {fmtDateTime(v.updated_at)})</span>
                    )}
                  </div>
                ))}
                {detail.committee_decided_at && (
                  <div className="relative">
                    <span className={`absolute -left-[11px] top-1 w-2 h-2 rounded-full ${detail.committee_decision === "upheld" ? "bg-green-600" : "bg-red-600"}`} />
                    <span className="text-gray-400">{fmtDateTime(detail.committee_decided_at)}</span>
                    <span className="ml-2 font-medium">
                      Decision recorded: {detail.committee_decision === "upheld" ? "Appeal Upheld" : "Appeal Denied"}
                      {detail.appeal_decided_by && <span className="font-normal text-gray-400"> by {detail.appeal_decided_by}</span>}
                    </span>
                  </div>
                )}
              </div>
              <div className="font-mono text-[10px] text-gray-400 select-all mt-2 pt-1.5 border-t border-gray-200">
                Ticket ID: {detail.id}
              </div>
            </div>

            {/* Driver & Vehicle (moving violations) */}
            {detail.ticket_category === "moving" && (detail.driver_name || detail.vehicle_description) && (
              <div className="bg-red-50 border border-red-100 rounded-lg p-3 text-sm">
                <div className="font-medium text-red-800 mb-2">Driver &amp; Vehicle</div>
                <Descriptions size="small" column={2}>
                  {detail.driver_name && <Descriptions.Item label="Driver">{detail.driver_name}</Descriptions.Item>}
                  {detail.driver_license && <Descriptions.Item label="License"><span className="font-mono">{detail.driver_license}</span></Descriptions.Item>}
                  {detail.vehicle_description && <Descriptions.Item label="Vehicle" span={2}>{detail.vehicle_description}</Descriptions.Item>}
                </Descriptions>
              </div>
            )}

            {/* Officer Notes */}
            {detail.officer_notes && (
              <div className="bg-gray-50 rounded-lg p-3 text-sm">
                <div className="font-medium text-gray-700 mb-1">Officer Notes</div>
                <p>{detail.officer_notes}</p>
              </div>
            )}

            {/* Evidence Photos — use the public ticket photo endpoints */}
            <div>
              <div className="text-xs font-medium text-gray-500 mb-2">Evidence Photos</div>
              <div className="flex gap-2 flex-wrap">
                <img
                  src={`/api/tickets/${detail.id}/photo`}
                  alt="Primary citation photo"
                  className="max-h-48 rounded border cursor-pointer"
                  onClick={e => window.open((e.target as HTMLImageElement).src, "_blank")}
                  onError={e => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
                {detail.additional_photo_count > 0 && Array.from({ length: detail.additional_photo_count }).map((_, i) => (
                  <img
                    key={i}
                    src={`/api/tickets/${detail.id}/photos/${i}`}
                    alt={`Additional photo ${i + 1}`}
                    className="max-h-48 rounded border cursor-pointer"
                    onClick={e => window.open((e.target as HTMLImageElement).src, "_blank")}
                    onError={e => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                ))}
              </div>
            </div>

            {/* Appeal Note */}
            <Card size="small" title="Student's Appeal" className="!bg-yellow-50">
              <p className="text-sm">{detail.appeal_note || <em className="text-gray-400">No note provided</em>}</p>
              {(detail.dispute_name || detail.dispute_email || detail.dispute_phone) && (
                <div className="mt-2 pt-2 border-t border-yellow-200 text-xs text-gray-500 space-y-0.5">
                  {detail.dispute_name && <div>Name: <span className="text-gray-700">{detail.dispute_name}</span></div>}
                  {detail.dispute_email && (
                    <div>Email: <a href={`mailto:${detail.dispute_email}`} className="text-blue-600 hover:underline">{detail.dispute_email}</a></div>
                  )}
                  {detail.dispute_phone && <div>Phone: <span className="text-gray-700">{detail.dispute_phone}</span></div>}
                </div>
              )}
            </Card>

            {/* Escalation Info */}
            <Card size="small" title="Escalation" className="!bg-purple-50">
              <div className="text-xs text-gray-600 space-y-1">
                <p>Escalated by <strong>{detail.escalated_by}</strong> on {fmtDateTime(detail.escalated_at)}</p>
                {detail.committee_notes && <p className="mt-1">{detail.committee_notes}</p>}
              </div>
            </Card>

            {/* Vote Comment (shown when voting is open) */}
            {detail.committee_status === "voting" && (
              <div>
                <div className="text-xs font-medium text-gray-500 mb-1">
                  {detail.my_vote ? "Update comment (optional)" : "Comment (optional)"}
                </div>
                <Input.TextArea
                  value={voteComment}
                  onChange={e => setVoteComment(e.target.value)}
                  placeholder={detail.my_vote ? "Update your comment when changing your vote..." : "Add a comment with your vote..."}
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
                        {v.updated_at && (
                          <Tooltip title={`Vote last changed on ${fmtDateTime(v.updated_at)}`}>
                            <span className="text-orange-500 ml-1">(changed)</span>
                          </Tooltip>
                        )}
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
