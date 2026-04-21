import { apiFetch } from "./client";

export interface Tenant {
  id: number;
  name: string;
  zidentity_base_url: string;
  oneapi_base_url: string;
  client_id: string;
  has_credentials: boolean;
  govcloud: boolean;
  zpa_customer_id: string | null;
  notes: string | null;
  created_at: string | null;
}

export interface TenantCreate {
  name: string;
  zidentity_base_url: string;
  client_id: string;
  client_secret: string;
  oneapi_base_url?: string;
  govcloud?: boolean;
  zpa_customer_id?: string;
  notes?: string;
}

export interface TenantUpdate {
  zidentity_base_url?: string;
  client_id?: string;
  client_secret?: string;
  oneapi_base_url?: string;
  govcloud?: boolean;
  zpa_customer_id?: string;
  notes?: string;
}

export const fetchTenants = (): Promise<Tenant[]> =>
  apiFetch<Tenant[]>("/api/v1/tenants");

export const fetchTenant = (id: number): Promise<Tenant> =>
  apiFetch<Tenant>(`/api/v1/tenants/${id}`);

export const createTenant = (body: TenantCreate): Promise<Tenant> =>
  apiFetch<Tenant>("/api/v1/tenants", { method: "POST", body: JSON.stringify(body) });

export const updateTenant = (id: number, body: TenantUpdate): Promise<Tenant> =>
  apiFetch<Tenant>(`/api/v1/tenants/${id}`, { method: "PUT", body: JSON.stringify(body) });

export const deleteTenant = (id: number): Promise<void> =>
  apiFetch<void>(`/api/v1/tenants/${id}`, { method: "DELETE" });
