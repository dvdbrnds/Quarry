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
  notes: string | null;
  zones?: LotZone[];
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
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

export const api = {
  permits: {
    list: (params?: { page?: number; search?: string; status?: string; lot?: string }) => {
      const qs = new URLSearchParams();
      if (params?.page) qs.set("page", String(params.page));
      if (params?.search) qs.set("search", params.search);
      if (params?.status) qs.set("status", params.status);
      if (params?.lot) qs.set("lot", params.lot);
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
    zones: {
      list: (lotId: string) => request<LotZone[]>(`/lots/${lotId}/zones`),
      create: (lotId: string, data: Partial<LotZone>) =>
        request<LotZone>(`/lots/${lotId}/zones`, { method: "POST", body: JSON.stringify(data) }),
      update: (lotId: string, zoneId: string, data: Partial<LotZone>) =>
        request<LotZone>(`/lots/${lotId}/zones/${zoneId}`, { method: "PUT", body: JSON.stringify(data) }),
      delete: (lotId: string, zoneId: string) =>
        request<void>(`/lots/${lotId}/zones/${zoneId}`, { method: "DELETE" }),
    },
  },
  devices: {
    list: () => request<Device[]>("/devices"),
    create: (data: { name: string; device_type?: string }) =>
      request<Device>("/devices", { method: "POST", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<void>(`/devices/${id}`, { method: "DELETE" }),
  },
};
