import { apiFetch } from "./client";

export interface ZpaCertificate {
  id: string;
  name: string;
  description?: string;
  issuedTo?: string;
  issuedBy?: string;
  expireTime?: string;
  status?: string;
}

export interface ZpaApplication {
  id: string;
  name: string;
  enabled: boolean;
  applicationType?: string;
  domainNames?: string[];
}

export interface ZpaPraPortal {
  id: string;
  name: string;
  domain?: string;
  certificateId?: string;
  certificateName?: string;
}

export interface ZpaSegmentGroup {
  id: string;
  name: string;
  [key: string]: unknown;
}

export interface ZpaServerGroup {
  id: string;
  name: string;
  [key: string]: unknown;
}

export interface ZpaAppConnector {
  id: string;
  name: string;
  [key: string]: unknown;
}

export interface ZpaServiceEdge {
  id: string;
  name: string;
  [key: string]: unknown;
}

const base = (tenant: string) => `/api/v1/zpa/${encodeURIComponent(tenant)}`;

export const fetchCertificates = (tenant: string): Promise<ZpaCertificate[]> =>
  apiFetch<ZpaCertificate[]>(`${base(tenant)}/certificates`);

export const fetchApplications = (tenant: string, appType = "BROWSER_ACCESS"): Promise<ZpaApplication[]> =>
  apiFetch<ZpaApplication[]>(`${base(tenant)}/applications?app_type=${encodeURIComponent(appType)}`);

export const fetchPraPortals = (tenant: string): Promise<ZpaPraPortal[]> =>
  apiFetch<ZpaPraPortal[]>(`${base(tenant)}/pra-portals`);

// ── Mutations ─────────────────────────────────────────────────────────────────

export const createApplication = (tenant: string, body: unknown): Promise<ZpaApplication> =>
  apiFetch<ZpaApplication>(`${base(tenant)}/applications`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateApplication = (
  tenant: string,
  appId: string,
  body: unknown
): Promise<ZpaApplication> =>
  apiFetch<ZpaApplication>(`${base(tenant)}/applications/${encodeURIComponent(appId)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteApplication = (
  tenant: string,
  appId: string
): Promise<{ deleted: boolean }> =>
  apiFetch<{ deleted: boolean }>(`${base(tenant)}/applications/${encodeURIComponent(appId)}`, {
    method: "DELETE",
  });

export const patchApplicationEnabled = (
  tenant: string,
  appId: string,
  enabled: boolean
): Promise<ZpaApplication> =>
  apiFetch<ZpaApplication>(`${base(tenant)}/applications/${encodeURIComponent(appId)}/enabled`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });

export const listSegmentGroups = (tenant: string): Promise<ZpaSegmentGroup[]> =>
  apiFetch<ZpaSegmentGroup[]>(`${base(tenant)}/segment-groups`);

export const listServerGroups = (tenant: string): Promise<ZpaServerGroup[]> =>
  apiFetch<ZpaServerGroup[]>(`${base(tenant)}/server-groups`);

export const listAppConnectors = (tenant: string): Promise<ZpaAppConnector[]> =>
  apiFetch<ZpaAppConnector[]>(`${base(tenant)}/app-connectors`);

export const listServiceEdges = (tenant: string): Promise<ZpaServiceEdge[]> =>
  apiFetch<ZpaServiceEdge[]>(`${base(tenant)}/service-edges`);
