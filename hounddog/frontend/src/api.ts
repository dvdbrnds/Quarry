const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
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

export interface Lot {
  id: string;
  name: string;
  boundary: Coordinate[];
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface ImportResult {
  inserted: number;
  updated: number;
  skipped: number;
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
    create: (data: { name: string; boundary: Coordinate[] }) =>
      request<Lot>("/lots", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: { name?: string; boundary?: Coordinate[] }) =>
      request<Lot>(`/lots/${id}`, { method: "PUT", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<void>(`/lots/${id}`, { method: "DELETE" }),
  },
};
