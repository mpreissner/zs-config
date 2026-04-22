import { apiFetch } from "./client";

export interface Tenant {
  id: number;
  name: string;
  vanity_domain: string;
  zidentity_base_url: string;
  oneapi_base_url: string;
  client_id: string;
  has_credentials: boolean;
  govcloud: boolean;
  zpa_customer_id: string | null;
  zia_tenant_id: string | null;
  zia_cloud: string | null;
  last_validation_error: string | null;
  notes: string | null;
  created_at: string | null;
}

export interface TenantCreate {
  name: string;
  vanity_domain: string;
  client_id: string;
  client_secret: string;
  govcloud?: boolean;
  govcloud_oneapi_url?: string;
  zpa_customer_id?: string;
  notes?: string;
}

export interface TenantUpdate {
  vanity_domain?: string;
  client_id?: string;
  client_secret?: string;
  govcloud?: boolean;
  govcloud_oneapi_url?: string;
  zpa_customer_id?: string;
  notes?: string;
}

export interface ImportResult {
  status: string;
  resources_synced: number;
  resources_updated: number;
  error_message: string | null;
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

export const importZIA = (id: number): Promise<ImportResult> =>
  apiFetch<ImportResult>(`/api/v1/tenants/${id}/import/zia`, { method: "POST" });

export const importZPA = (id: number): Promise<ImportResult> =>
  apiFetch<ImportResult>(`/api/v1/tenants/${id}/import/zpa`, { method: "POST" });
