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

  const res = await fetch(`${BASE}${path}`, { ...init, headers });
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
  student_id: string;
  name: string;
  email: string | null;
  phone: string | null;
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

export const api = {
  academicCalendar: {
    list: () => request<AcademicSeason[]>("/academic-calendar"),
  },
  permits: {
    list: (params?: { page?: number; search?: string; status?: string; lot?: string; permit_type?: string; sort?: string }) => {
      const qs = new URLSearchParams();
      if (params?.page) qs.set("page", String(params.page));
      if (params?.search) qs.set("search", params.search);
      if (params?.status) qs.set("status", params.status);
      if (params?.lot) qs.set("lot", params.lot);
      if (params?.permit_type) qs.set("permit_type", params.permit_type);
      if (params?.sort) qs.set("sort", params.sort);
      return request<PermitList>(`/permits?${qs}`);
    },
    get: (id: string) => request<Permit>(`/permits/${id}`),
    create: (data: Partial<Permit>) =>
      request<Permit>("/permits", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: Partial<Permit>) =>
      request<Permit>(`/permits/${id}`, { method: "PUT", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<void>(`/permits/${id}`, { method: "DELETE" }),
    importJson: (permits: object[]) =>
      request<ImportResult>("/permits/import", {
        method: "POST",
        body: JSON.stringify({ permits }),
      }),
    stats: () => request<{ total: number; active: number; expired: number; expiring_soon: number; revoked: number }>("/permits/stats"),
    bulkStatus: (ids: string[], status: string) =>
      request<{ updated: number }>("/permits/bulk-status", {
        method: "POST",
        body: JSON.stringify({ ids, status }),
      }),
    history: (id: string) => request<any>(`/permits/${id}/history`),
    renew: (id: string) =>
      request<Permit>(`/permits/${id}/renew`, { method: "POST" }),
    duplicates: () => request<any[]>("/permits/duplicates"),
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
      schedule: (data: { lot_id: string; reason?: string; closes_at: string; reopens_at?: string; is_immediate?: boolean }) =>
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
};
