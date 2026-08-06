import { getAccessToken } from "./auth";

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let method = init?.method ?? "GET";
  if (method === "DELETE") {
    method = "POST";
    headers["X-HTTP-Method-Override"] = "DELETE";
  }

  const res = await fetch(`${BASE}${path}`, { ...init, method, headers });
  if (!res.ok) {
    if (res.status === 401) {
      window.location.href = "/";
      throw new Error("Session expired");
    }
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export interface Permit {
  id: string;
  permit_number: string | null;
  student_id: string;
  name: string;
  email: string | null;
  phone: string;
  sms_opt_in: boolean;
  plates: string[];
  lot_assignment: string;
  permit_type: string;
  beacon_id: string | null;
  start_date: string;
  end_date: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface MessageTemplate {
  id: string;
  reason_code: string;
  reason_label: string;
  is_emergency: boolean;
  email_subject: string;
  email_body: string;
  sms_body: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SendMessagePreview {
  email_recipient_count: number;
  sms_recipient_count: number;
  sms_opted_in_count: number;
  sms_total_with_phone: number;
  is_emergency: boolean;
  rendered_email_subject: string;
  rendered_sms_body: string;
}

export interface SendMessageResult {
  emails_sent: number;
  sms_sent: number;
}

export interface PermitNotificationStatus {
  permit_id: string;
  name: string;
  lot_assignment: string;
  email: string | null;
  phone: string | null;
  sms_opt_in: boolean;
  preference_url: string;
}

export interface NotificationPreferenceRead {
  first_name: string;
  phone: string | null;
  sms_opt_in: boolean;
  email_always_on: boolean;
}

export interface PermitList {
  items: Permit[];
  total: number;
  page: number;
  page_size: number;
}

export interface Coordinate {
  latitude: number;
  longitude: number;
}

export interface TimeRule {
  start: string;
  end: string;
  days: string[];
  allowed_permit_types: string[];
  label: string;
}

export interface SeasonSchedule {
  season: string;
  label: string;
  rules: TimeRule[];
}

export interface LotZone {
  id: string;
  lot_id: string;
  zone_type: string;
  label: string;
  space_count: number;
  boundary: Coordinate[];
  fine_override: string | null;
  is_premium: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ParkingSpot {
  id: string;
  lot_id: string;
  number: number;
  label: string | null;
  spot_type: string;
  sensor_id: string | null;
  latitude: number | null;
  longitude: number | null;
  created_at: string;
  updated_at: string;
}

export interface Lot {
  id: string;
  name: string;
  boundary: Coordinate[];
  total_spaces: number;
  handicap_spaces: number;
  designation_code: string;
  designation_label: string;
  access_schedule: SeasonSchedule[];
  is_snow_lot: boolean;
  is_closed: boolean;
  has_sheepdog: boolean;
  lot_type: string;
  external_url: string | null;
  external_provider: string | null;
  campus: string | null;
  notes: string | null;
  zones?: LotZone[];
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface LotClosure {
  id: string;
  lot_id: string;
  reason: string;
  closes_at: string;
  reopens_at: string | null;
  is_immediate: boolean;
  notification_sent: boolean;
  reopen_notification_sent: boolean;
  created_by: string;
  status: string;
  created_at: string;
  updated_at: string;
  lot_name?: string;
}

export interface ImportResult {
  inserted: number;
  updated: number;
  skipped: number;
}

export interface Device {
  id: string;
  name: string;
  api_key: string;
  device_type: string;
  last_seen: string | null;
  created_at: string;
  pairing_url?: string;
  pairing_payload?: { url: string; key: string; name: string };
}

export interface AcademicSeason {
  id: string;
  code: string;
  label: string;
  start_date: string;
  end_date: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface AlertSubscriber {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  sms_enabled: boolean;
  email_enabled: boolean;
  categories: string[];
  unsubscribe_token: string;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface AlertSendPreview {
  category: string;
  email_recipient_count: number;
  sms_recipient_count: number;
  total_subscribers: number;
  configured_channels: string[];
}

export interface AlertSendResult {
  alert_id: string;
  emails_sent: number;
  sms_sent: number;
  channel_results: Record<string, { sent: number; failed: number; error?: string | null }>;
}

export interface AlertLogEntry {
  id: string;
  category: string;
  subject: string;
  body_text: string;
  body_sms: string;
  sent_by: string;
  email_count: number;
  sms_count: number;
  status: string;
  cleared_at: string | null;
  cleared_by: string | null;
  channel_results: Record<string, { sent: number; failed: number; error?: string | null }> | null;
  response_options: string[] | null;
  is_checkin: boolean;
  target_group_ids: string[] | null;
  scheduled_for: string | null;
  recurrence_rule: string | null;
  sent_at: string;
}

export interface ActiveAlert {
  id: string;
  category: string;
  subject: string;
  body_text: string;
  sent_at: string;
  status: string;
}

export interface AlertChannelInfo {
  name: string;
  configured: boolean;
  emergency_only: boolean;
}

export interface ChannelSettingsField {
  key: string;
  label: string;
  type: string;
  required: boolean;
}

export interface ChannelConfig {
  name: string;
  enabled: boolean;
  configured: boolean;
  emergency_only: boolean;
  settings: Record<string, any>;
  categories: string[];
  settings_schema: ChannelSettingsField[];
}

export interface ChannelConfigUpdate {
  enabled?: boolean;
  settings?: Record<string, any>;
  categories?: string[];
}

export interface AlertTestSendResult {
  alert_id: string;
  channel: string;
  sent: number;
  failed: number;
  error: string | null;
  status: string;
}

export interface AlertTemplate {
  id: string;
  name: string;
  category: string;
  subject: string;
  body_text: string;
  body_sms: string;
  created_by: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface AlertResponseEntry {
  id: string;
  alert_id: string;
  subscriber_id: string | null;
  phone: string | null;
  channel: string;
  response_text: string;
  received_at: string;
}

export interface AlertResponseSummary {
  alert_id: string;
  total_sent: number;
  total_responses: number;
  response_counts: Record<string, number>;
  non_responder_count: number;
  first_response_at: string | null;
  last_response_at: string | null;
}

export interface CheckInStatus {
  alert_id: string;
  total_subscribers: number;
  responded_safe: number;
  responded_help: number;
  no_response: number;
  help_details: AlertResponseEntry[];
}

export interface SubscriberGroup {
  id: string;
  name: string;
  description: string;
  group_type: string;
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface AlertScenario {
  id: string;
  name: string;
  description: string;
  steps: ScenarioStep[];
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScenarioStep {
  action: "send_alert" | "wait" | "clear_previous";
  template_id?: string;
  group_ids?: string[];
  channels?: string[];
  delay_seconds?: number;
}

export interface RunningScenario {
  task_id: string;
  scenario_id: string;
  scenario_name: string;
  current_step: number;
  total_steps: number;
  started_at: string;
  started_by: string;
}

export interface AlertDeliverySummary {
  total_alerts: number;
  total_emails: number;
  total_sms: number;
  avg_channels_per_alert: number;
  by_category: Record<string, number>;
  by_month: { month: string; count: number; emails: number; sms: number }[];
}

export interface ChannelDeliveryStats {
  channel: string;
  total_sent: number;
  total_failed: number;
  success_rate: number;
}

export interface ResponseRateStats {
  alert_id: string;
  subject: string;
  category: string;
  total_subscribers: number;
  total_responses: number;
  response_rate: number;
  checkin_safe: number;
  checkin_help: number;
  sent_at: string;
}

export interface AlertAnalyticsDashboard {
  summary: AlertDeliverySummary;
  channel_stats: ChannelDeliveryStats[];
  recent_response_rates: ResponseRateStats[];
}

export interface AfterActionReport {
  alert_id: string;
  subject: string;
  category: string;
  sent_by: string;
  sent_at: string;
  cleared_at: string | null;
  channel_results: Record<string, { sent: number; failed: number; error?: string | null }> | null;
  total_subscribers: number;
  total_responses: number;
  response_rate: number;
  response_breakdown: Record<string, number>;
  timeline: { time: string; phone: string; response: string; channel: string }[];
}

export interface WeatherAlertConfig {
  enabled: boolean;
  zone_id: string;
  poll_interval_seconds: number;
  event_mappings: { event: string; category: string; auto_send: boolean; template_id?: string }[];
}

export interface SisSubscriberSyncConfig {
  enabled: boolean;
  sync_url: string;
  last_sync_at: string | null;
  total_synced: number;
}

export interface SignageScreen {
  id: string;
  name: string;
  location: string;
  playlist: { type: string; url: string; duration: number }[];
  last_seen: string | null;
  is_online: boolean;
  created_at: string;
  updated_at: string;
}

export interface LotteryRunResult {
  success: boolean;
  permit_type: string;
  strategy: string;
  seed_hash: string;
  total_applicants: number;
  eligible_applicants: number;
  filtered: { test_entries: number; unpaid_citations: number };
  spots_available: number;
  selected: number;
  waitlisted: number;
  warnings: string[];
  run_at: string | null;
}

export interface LotteryAudit {
  strategy: string;
  seed_hash: string;
  total_applicants: number;
  eligible_applicants: number;
  spots_available: number;
  selected_count: number;
  waitlisted_count: number;
  filtered_test_entries: number;
  filtered_unpaid_citations: number;
  run_at: string;
  run_by: string;
}

export interface LotteryApplicationResult {
  id: string;
  student_name: string;
  student_email: string;
  class_year: number;
  plate: string;
  status: string;
  lottery_rank: number | null;
  waitlist_position: number | null;
  assigned_lot: string | null;
  offer_expires_at: string | null;
  admin_notes: string | null;
}

export interface LotteryResults {
  audit: LotteryAudit;
  applications: LotteryApplicationResult[];
}

export interface LotteryVerification {
  verified: boolean;
  error?: string;
  seed_hash?: string;
  strategy?: string;
  selected_count?: number;
  waitlisted_count?: number;
  run_at?: string;
  run_by?: string;
}

export interface BackupSchedule {
  enabled: boolean;
  frequency: string;
  time: string;
  retention_days: number;
  google_drive_folder_id: string;
  last_run: string | null;
  next_run: string | null;
  last_drive_upload: string | null;
}

export interface BackupScheduleInput {
  enabled: boolean;
  frequency: string;
  time: string;
  retention_days: number;
  google_drive_folder_id?: string;
}

export interface BackupHistoryEntry {
  filename: string;
  size_bytes: number;
  created_at: string;
  source?: string;
}

export const api = {
  academicCalendar: {
    list: () => request<AcademicSeason[]>("/academic-calendar"),
  },
  permits: {
    list: (params?: { page?: number; search?: string; status?: string; lot?: string; permit_type?: string; max_age_years?: number; sort?: string }) => {
      const qs = new URLSearchParams();
      if (params?.page) qs.set("page", String(params.page));
      if (params?.search) qs.set("search", params.search);
      if (params?.status) qs.set("status", params.status);
      if (params?.lot) qs.set("lot", params.lot);
      if (params?.permit_type) qs.set("permit_type", params.permit_type);
      if (params?.max_age_years) qs.set("max_age_years", String(params.max_age_years));
      if (params?.sort) qs.set("sort", params.sort);
      return request<PermitList>(`/permits?${qs}`);
    },
    get: (id: string) => request<Permit>(`/permits/${id}`),
    create: (data: Partial<Permit>) =>
      request<Permit>("/permits", { method: "POST", body: JSON.stringify(data) }),
    createWithCharge: (data: {
      name: string; email: string; phone?: string; plates?: string[];
      student_id?: string; lot_assignment?: string; permit_type: string;
      start_date?: string; end_date?: string; waive_fee?: boolean; voucher_code?: string;
    }) =>
      request<{ permit_id: string; status: string; waived: boolean; checkout_url?: string; amount?: string; voucher_applied?: boolean }>(
        "/permits/charge", { method: "POST", body: JSON.stringify(data) }
      ),
    update: (id: string, data: Partial<Permit>) =>
      request<Permit>(`/permits/${id}`, { method: "PUT", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<void>(`/permits/${id}`, { method: "DELETE" }),
    importJson: (permits: object[]) =>
      request<ImportResult>("/permits/import", {
        method: "POST",
        body: JSON.stringify({ permits }),
      }),
    stats: () => request<{ total: number; active: number; expired: number; expiring_soon: number; revoked: number; unique_users: number }>("/permits/stats"),
    bulkStatus: (ids: string[], status: string) =>
      request<{ updated: number }>("/permits/bulk-status", {
        method: "POST",
        body: JSON.stringify({ ids, status }),
      }),
    history: (id: string) => request<any>(`/permits/${id}/history`),
    renew: (id: string) =>
      request<Permit>(`/permits/${id}/renew`, { method: "POST" }),
    duplicates: () => request<any[]>("/permits/duplicates"),
    lottery: {
      run: (permitTypeId: string, force = false) =>
        request<LotteryRunResult>(`/permits/types/${permitTypeId}/run-lottery?force=${force}`, {
          method: "POST",
        }),
      results: (permitTypeId: string) =>
        request<LotteryResults>(`/permits/types/${permitTypeId}/lottery-results`),
      verify: (permitTypeId: string, seed: string) =>
        request<LotteryVerification>(`/permits/types/${permitTypeId}/verify-lottery?seed=${encodeURIComponent(seed)}`, {
          method: "POST",
        }),
    },
  },
  lots: {
    list: () => request<Lot[]>("/lots"),
    get: (id: string) => request<Lot>(`/lots/${id}`),
    create: (data: Partial<Lot>) =>
      request<Lot>("/lots", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: Partial<Lot>) =>
      request<Lot>(`/lots/${id}`, { method: "PUT", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<void>(`/lots/${id}`, { method: "DELETE" }),
    close: (lotId: string, data: { reason?: string; reopens_at?: string; recipients?: string[] }) =>
      request<LotClosure>(`/lots/${lotId}/close`, { method: "POST", body: JSON.stringify(data) }),
    reopen: (lotId: string) =>
      request<Lot>(`/lots/${lotId}/reopen`, { method: "POST" }),
    closures: {
      listAll: (status?: string) => {
        const qs = status ? `?status=${status}` : "";
        return request<LotClosure[]>(`/lots/closures/all${qs}`);
      },
      listForLot: (lotId: string) => request<LotClosure[]>(`/lots/${lotId}/closures`),
      schedule: (data: { lot_id: string; reason?: string; closes_at: string; reopens_at?: string; is_immediate?: boolean; recipients?: string[] }) =>
        request<LotClosure>("/lots/closures", { method: "POST", body: JSON.stringify(data) }),
      update: (closureId: string, data: Partial<LotClosure>) =>
        request<LotClosure>(`/lots/closures/${closureId}`, { method: "PUT", body: JSON.stringify(data) }),
      cancel: (closureId: string) =>
        request<void>(`/lots/closures/${closureId}`, { method: "DELETE" }),
    },
    zones: {
      list: (lotId: string) => request<LotZone[]>(`/lots/${lotId}/zones`),
      create: (lotId: string, data: Partial<LotZone>) =>
        request<LotZone>(`/lots/${lotId}/zones`, { method: "POST", body: JSON.stringify(data) }),
      update: (lotId: string, zoneId: string, data: Partial<LotZone>) =>
        request<LotZone>(`/lots/${lotId}/zones/${zoneId}`, { method: "PUT", body: JSON.stringify(data) }),
      delete: (lotId: string, zoneId: string) =>
        request<void>(`/lots/${lotId}/zones/${zoneId}`, { method: "DELETE" }),
    },
    spots: {
      list: (lotId: string) => request<ParkingSpot[]>(`/lots/${lotId}/spots`),
      create: (lotId: string, data: Partial<ParkingSpot>) =>
        request<ParkingSpot>(`/lots/${lotId}/spots`, { method: "POST", body: JSON.stringify(data) }),
      update: (lotId: string, spotId: string, data: Partial<ParkingSpot>) =>
        request<ParkingSpot>(`/lots/${lotId}/spots/${spotId}`, { method: "PUT", body: JSON.stringify(data) }),
      delete: (lotId: string, spotId: string) =>
        request<void>(`/lots/${lotId}/spots/${spotId}`, { method: "DELETE" }),
      bulkDelete: (lotId: string, spotIds: string[]) =>
        request<void>(`/lots/${lotId}/spots/bulk-delete`, { method: "POST", body: JSON.stringify({ spot_ids: spotIds }) }),
      detect: (lotId: string) =>
        request<ParkingSpot[]>(`/lots/${lotId}/spots/detect`, { method: "POST" }),
    },
  },
  devices: {
    list: () => request<Device[]>("/devices"),
    create: (data: { name: string; device_type?: string }) =>
      request<Device>("/devices", { method: "POST", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<void>(`/devices/${id}`, { method: "DELETE" }),
  },
  messaging: {
    templates: {
      list: () => request<MessageTemplate[]>("/messaging/templates"),
      create: (data: Partial<MessageTemplate>) =>
        request<MessageTemplate>("/messaging/templates", { method: "POST", body: JSON.stringify(data) }),
      update: (id: string, data: Partial<MessageTemplate>) =>
        request<MessageTemplate>(`/messaging/templates/${id}`, { method: "PUT", body: JSON.stringify(data) }),
      delete: (id: string) =>
        request<void>(`/messaging/templates/${id}`, { method: "DELETE" }),
    },
    preview: (params: { template_id?: string; lot_id?: string }) => {
      const qs = new URLSearchParams();
      if (params.template_id) qs.set("template_id", params.template_id);
      if (params.lot_id) qs.set("lot_id", params.lot_id);
      return request<SendMessagePreview>(`/messaging/send/preview?${qs}`);
    },
    send: (data: {
      template_id?: string;
      lot_id?: string;
      custom_email_subject?: string;
      custom_email_body?: string;
      custom_sms_body?: string;
      send_email?: boolean;
      send_sms?: boolean;
      extra_emails?: string[];
      extra_phones?: string[];
    }) =>
      request<SendMessageResult>("/messaging/send", { method: "POST", body: JSON.stringify(data) }),
    preferences: (lot?: string) => {
      const qs = lot ? `?lot=${encodeURIComponent(lot)}` : "";
      return request<PermitNotificationStatus[]>(`/messaging/preferences${qs}`);
    },
  },
  alerts: {
    preview: (category: string) =>
      request<AlertSendPreview>(`/alerts/send/preview?category=${encodeURIComponent(category)}`),
    send: (data: {
      category: string;
      subject: string;
      body_text?: string;
      body_sms?: string;
      send_email?: boolean;
      send_sms?: boolean;
      response_options?: string[] | null;
      group_ids?: string[] | null;
      is_checkin?: boolean;
      scheduled_for?: string | null;
      recurrence_rule?: string | null;
    }) =>
      request<AlertSendResult>("/alerts/send", { method: "POST", body: JSON.stringify(data) }),
    clear: (alertId: string) =>
      request<AlertLogEntry>(`/alerts/${alertId}/clear`, { method: "POST" }),
    testSend: (data: {
      channel: string;
      category?: string;
      subject?: string;
      body_text?: string;
      body_sms?: string;
      test_email?: string | null;
      test_phone?: string | null;
      screen_id?: string | null;
    }) =>
      request<AlertTestSendResult>("/alerts/test-send", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    active: () =>
      fetch(`${BASE}/alerts/active`).then(async (res) => {
        if (!res.ok) return null;
        const data = await res.json();
        return data as ActiveAlert | null;
      }),
    channels: () => request<AlertChannelInfo[]>("/alerts/channels"),
    channelsConfig: () => request<ChannelConfig[]>("/alerts/channels/config"),
    updateChannelConfig: (name: string, data: ChannelConfigUpdate) =>
      request<ChannelConfig>(`/alerts/channels/${name}/config`, { method: "PUT", body: JSON.stringify(data) }),
    history: (params?: { limit?: number; offset?: number; include_tests?: boolean }) => {
      const qs = new URLSearchParams();
      if (params?.limit) qs.set("limit", String(params.limit));
      if (params?.offset) qs.set("offset", String(params.offset));
      if (params?.include_tests) qs.set("include_tests", "true");
      return request<AlertLogEntry[]>(`/alerts/history?${qs}`);
    },
    templates: {
      list: (category?: string) => {
        const qs = category ? `?category=${encodeURIComponent(category)}` : "";
        return request<AlertTemplate[]>(`/alerts/templates${qs}`);
      },
      get: (id: string) => request<AlertTemplate>(`/alerts/templates/${id}`),
      create: (data: Partial<AlertTemplate>) =>
        request<AlertTemplate>("/alerts/templates", { method: "POST", body: JSON.stringify(data) }),
      update: (id: string, data: Partial<AlertTemplate>) =>
        request<AlertTemplate>(`/alerts/templates/${id}`, { method: "PUT", body: JSON.stringify(data) }),
      delete: (id: string) =>
        request<void>(`/alerts/templates/${id}`, { method: "DELETE" }),
    },
    responses: {
      summary: (alertId: string) =>
        request<AlertResponseSummary>(`/alerts/${alertId}/responses`),
      detail: (alertId: string) =>
        request<AlertResponseEntry[]>(`/alerts/${alertId}/responses/detail`),
      nonResponders: (alertId: string) =>
        request<AlertSubscriber[]>(`/alerts/${alertId}/non-responders`),
      checkinStatus: (alertId: string) =>
        request<CheckInStatus>(`/alerts/${alertId}/checkin-status`),
      resendNonResponders: (alertId: string) =>
        request<AlertSendResult>(`/alerts/${alertId}/resend-non-responders`, { method: "POST" }),
    },
    groups: {
      list: () => request<SubscriberGroup[]>("/alerts/groups"),
      get: (id: string) => request<SubscriberGroup>(`/alerts/groups/${id}`),
      create: (data: { name: string; description?: string; group_type?: string }) =>
        request<SubscriberGroup>("/alerts/groups", { method: "POST", body: JSON.stringify(data) }),
      update: (id: string, data: Partial<SubscriberGroup>) =>
        request<SubscriberGroup>(`/alerts/groups/${id}`, { method: "PUT", body: JSON.stringify(data) }),
      delete: (id: string) =>
        request<void>(`/alerts/groups/${id}`, { method: "DELETE" }),
      members: (id: string) =>
        request<AlertSubscriber[]>(`/alerts/groups/${id}/members`),
      addMembers: (id: string, subscriberIds: string[]) =>
        request<{ added: number }>(`/alerts/groups/${id}/members`, { method: "POST", body: JSON.stringify({ subscriber_ids: subscriberIds }) }),
      removeMembers: (id: string, subscriberIds: string[]) =>
        request<{ removed: number }>(`/alerts/groups/${id}/members`, { method: "DELETE", body: JSON.stringify({ subscriber_ids: subscriberIds }) }),
    },
    scenarios: {
      list: () => request<AlertScenario[]>("/alerts/scenarios"),
      get: (id: string) => request<AlertScenario>(`/alerts/scenarios/${id}`),
      create: (data: { name: string; description?: string; steps: ScenarioStep[] }) =>
        request<AlertScenario>("/alerts/scenarios", { method: "POST", body: JSON.stringify(data) }),
      update: (id: string, data: Partial<AlertScenario>) =>
        request<AlertScenario>(`/alerts/scenarios/${id}`, { method: "PUT", body: JSON.stringify(data) }),
      delete: (id: string) =>
        request<void>(`/alerts/scenarios/${id}`, { method: "DELETE" }),
      run: (id: string) =>
        request<{ task_id: string }>(`/alerts/scenarios/${id}/run`, { method: "POST" }),
      running: () => request<RunningScenario[]>("/alerts/scenarios/running"),
      abort: (taskId: string) =>
        request<void>(`/alerts/scenarios/running/${taskId}/abort`, { method: "POST" }),
    },
    subscribers: {
      list: (params?: { search?: string; category?: string }) => {
        const qs = new URLSearchParams();
        if (params?.search) qs.set("search", params.search);
        if (params?.category) qs.set("category", params.category);
        return request<AlertSubscriber[]>(`/alerts/subscribers?${qs}`);
      },
      create: (data: Partial<AlertSubscriber>) =>
        request<AlertSubscriber>("/alerts/subscribers", { method: "POST", body: JSON.stringify(data) }),
      update: (id: string, data: Partial<AlertSubscriber>) =>
        request<AlertSubscriber>(`/alerts/subscribers/${id}`, { method: "PUT", body: JSON.stringify(data) }),
      delete: (id: string) =>
        request<void>(`/alerts/subscribers/${id}`, { method: "DELETE" }),
      importCsv: async (file: File) => {
        const token = await getAccessToken();
        const form = new FormData();
        form.append("file", file);
        const headers: Record<string, string> = {};
        if (token) headers["Authorization"] = `Bearer ${token}`;
        const res = await fetch(`${BASE}/alerts/subscribers/import`, { method: "POST", headers, body: form });
        if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
        return res.json() as Promise<{ created: number; skipped: number }>;
      },
      exportUrl: `${BASE}/alerts/subscribers/export`,
    },
    subscribe: (data: { name: string; email?: string; phone?: string; categories?: string[] }) =>
      fetch(`${BASE}/alerts/subscribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }).then(async (res) => {
        if (!res.ok) {
          const body = await res.text();
          throw new Error(`${res.status}: ${body}`);
        }
        return res.json() as Promise<{ message: string; subscriber_id: string }>;
      }),
    scheduled: {
      list: () => request<AlertLogEntry[]>("/alerts/scheduled"),
      cancel: (id: string) =>
        request<void>(`/alerts/scheduled/${id}`, { method: "DELETE" }),
    },
    analytics: {
      dashboard: (days?: number) => {
        const qs = days ? `?days=${days}` : "";
        return request<AlertAnalyticsDashboard>(`/alerts/analytics${qs}`);
      },
      afterAction: (alertId: string) =>
        request<AfterActionReport>(`/alerts/analytics/after-action/${alertId}`),
    },
    weather: {
      config: () => request<WeatherAlertConfig>("/alerts/weather/config"),
      recent: () => request<{ seen_events: string[] }>("/alerts/weather/recent"),
    },
    sisSync: {
      status: () => request<SisSubscriberSyncConfig>("/alerts/sis-sync/status"),
      trigger: () => request<SisSubscriberSyncConfig>("/alerts/sis-sync/trigger", { method: "POST" }),
    },
  },
  signage: {
    screens: {
      list: () => request<SignageScreen[]>("/signage/screens"),
      create: (data: { name: string; location?: string; playlist?: { type: string; url: string; duration: number }[] }) =>
        request<SignageScreen>("/signage/screens", { method: "POST", body: JSON.stringify(data) }),
      update: (id: string, data: Partial<SignageScreen>) =>
        request<SignageScreen>(`/signage/screens/${id}`, { method: "PUT", body: JSON.stringify(data) }),
      delete: (id: string) =>
        request<void>(`/signage/screens/${id}`, { method: "DELETE" }),
    },
  },
  backup: {
    tables: () => request<{ tables: Record<string, number> }>("/backup/tables"),
    exportUrl: `${BASE}/backup/export`,
    restore: async (file: File) => {
      const token = await getAccessToken();
      const form = new FormData();
      form.append("file", file);
      const headers: Record<string, string> = {};
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const res = await fetch(`${BASE}/backup/restore`, { method: "POST", headers, body: form });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(`${res.status}: ${body}`);
      }
      return res.json() as Promise<{
        status: string;
        restored: Record<string, number>;
        skipped: string[];
        exported_at: string;
      }>;
    },
    clearTickets: () =>
      request<{ deleted: number }>("/backup/clear-tickets", { method: "DELETE" }),
    clearPermits: () =>
      request<{ permits_deleted: number; applications_deleted: number; payments_deleted: number }>(
        "/backup/clear-permits", { method: "DELETE" }
      ),
    schedule: {
      get: () => request<BackupSchedule>("/backup/schedule"),
      set: (data: BackupScheduleInput) =>
        request<BackupSchedule>("/backup/schedule", { method: "POST", body: JSON.stringify(data) }),
      disable: () =>
        request<BackupSchedule>("/backup/schedule/disable", { method: "POST" }),
      runNow: () =>
        request<{ filename: string; status: string; drive_uploaded: boolean }>("/backup/run-now", { method: "POST" }),
    },
    testDrive: (folderId: string) =>
      request<{ ok: boolean; folder_name: string }>(`/backup/test-drive?folder_id=${encodeURIComponent(folderId)}`, { method: "POST" }),
    history: {
      list: () => request<BackupHistoryEntry[]>("/backup/history"),
      downloadUrl: (filename: string) => `${BASE}/backup/history/${filename}`,
      delete: (filename: string) =>
        request<{ deleted: string }>(`/backup/history/${filename}`, { method: "DELETE" }),
    },
  },
};
