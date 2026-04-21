import { apiFetch } from "./client";

export interface Tenant {
  id: number;
  name: string;
  zidentity_base_url: string;
  oneapi_base_url: string;
  govcloud: boolean;
  zpa_customer_id: string | null;
  notes: string | null;
  created_at: string | null;
}

export function fetchTenants(): Promise<Tenant[]> {
  return apiFetch<Tenant[]>("/api/v1/tenants");
}
