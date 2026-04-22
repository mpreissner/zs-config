import { apiFetch } from "./client";

export interface AuditEntry {
  id: number;
  timestamp: string;
  product: string;
  operation: string;
  action: string;
  status: string;
  resource_type: string | null;
  resource_id: string | null;
  resource_name: string | null;
  details: Record<string, unknown> | string | null;
  error_message: string | null;
}

export interface AuditParams {
  tenant_id?: number;
  product?: string;
  limit?: number;
}

export function fetchAuditLog(params: AuditParams = {}): Promise<AuditEntry[]> {
  const qs = new URLSearchParams();
  if (params.tenant_id !== undefined) qs.set("tenant_id", String(params.tenant_id));
  if (params.product) qs.set("product", params.product);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const query = qs.toString();
  return apiFetch<AuditEntry[]>(`/api/v1/audit${query ? `?${query}` : ""}`);
}
