import { apiFetch, getAuthHeaders } from "./client";

export interface ZpaCertificate {
  id: string;
  name: string;
  description?: string;
  issued_to?: string;
  issued_by?: string;
  valid_to_in_epoch_sec?: number;
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
  zpa_id: string;
  id?: string;
  name: string;
  domain?: string;
  certificate_id?: string;
  certificate_name?: string;
  enabled?: boolean;
  [key: string]: unknown;
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
  zpa_id: string;
  id?: string;
  name: string;
  enabled?: boolean;
  [key: string]: unknown;
}

export interface ZpaServiceEdge {
  zpa_id: string;
  id?: string;
  name: string;
  enabled?: boolean;
  [key: string]: unknown;
}

export interface ZpaConnectorGroup {
  zpa_id: string;
  id?: string;
  name: string;
  enabled?: boolean;
  [key: string]: unknown;
}

export interface ZpaPraConsole {
  zpa_id: string;
  id?: string;
  name: string;
  enabled?: boolean;
  [key: string]: unknown;
}

export interface ZpaAccessPolicyRule {
  zpa_id: string;
  id?: string;
  name: string;
  action?: string;
  rule_order?: number;
  [key: string]: unknown;
}

export interface ZpaSamlAttribute {
  zpa_id: string;
  id?: string;
  name: string;
  [key: string]: unknown;
}

export interface ZpaScimAttribute {
  zpa_id: string;
  id?: string;
  name: string;
  [key: string]: unknown;
}

export interface ZpaScimGroup {
  zpa_id: string;
  id?: string;
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

// ── Application mutations ──────────────────────────────────────────────────────

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

// ── Segment / Server groups ────────────────────────────────────────────────────

export const listSegmentGroups = (tenant: string): Promise<ZpaSegmentGroup[]> =>
  apiFetch<ZpaSegmentGroup[]>(`${base(tenant)}/segment-groups`);

export const listServerGroups = (tenant: string): Promise<ZpaServerGroup[]> =>
  apiFetch<ZpaServerGroup[]>(`${base(tenant)}/server-groups`);

// ── App Connectors ─────────────────────────────────────────────────────────────

export const listAppConnectors = (tenant: string): Promise<ZpaAppConnector[]> =>
  apiFetch<ZpaAppConnector[]>(`${base(tenant)}/app-connectors`);

export const listConnectors = (tenant: string, q?: string): Promise<ZpaAppConnector[]> =>
  apiFetch<ZpaAppConnector[]>(
    `${base(tenant)}/connectors${q ? `?q=${encodeURIComponent(q)}` : ""}`
  );

export const patchConnectorEnabled = (
  tenant: string,
  id: string,
  enabled: boolean
): Promise<ZpaAppConnector> =>
  apiFetch<ZpaAppConnector>(`${base(tenant)}/connectors/${encodeURIComponent(id)}/enabled`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });

export const patchConnectorName = (
  tenant: string,
  id: string,
  name: string
): Promise<ZpaAppConnector> =>
  apiFetch<ZpaAppConnector>(`${base(tenant)}/connectors/${encodeURIComponent(id)}/name`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });

export const deleteConnector = (tenant: string, id: string): Promise<{ deleted: boolean }> =>
  apiFetch<{ deleted: boolean }>(`${base(tenant)}/connectors/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

// ── Connector Groups ───────────────────────────────────────────────────────────

export const listConnectorGroups = (tenant: string, q?: string): Promise<ZpaConnectorGroup[]> =>
  apiFetch<ZpaConnectorGroup[]>(
    `${base(tenant)}/connector-groups${q ? `?q=${encodeURIComponent(q)}` : ""}`
  );

export const createConnectorGroup = (
  tenant: string,
  name: string,
  description?: string
): Promise<ZpaConnectorGroup> =>
  apiFetch<ZpaConnectorGroup>(`${base(tenant)}/connector-groups`, {
    method: "POST",
    body: JSON.stringify({ name, description }),
  });

export const patchConnectorGroupEnabled = (
  tenant: string,
  id: string,
  enabled: boolean
): Promise<ZpaConnectorGroup> =>
  apiFetch<ZpaConnectorGroup>(
    `${base(tenant)}/connector-groups/${encodeURIComponent(id)}/enabled`,
    {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }
  );

export const deleteConnectorGroup = (tenant: string, id: string): Promise<{ deleted: boolean }> =>
  apiFetch<{ deleted: boolean }>(`${base(tenant)}/connector-groups/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

// ── Service Edges ──────────────────────────────────────────────────────────────

export const listServiceEdges = (tenant: string): Promise<ZpaServiceEdge[]> =>
  apiFetch<ZpaServiceEdge[]>(`${base(tenant)}/service-edges`);

export const patchServiceEdgeEnabled = (
  tenant: string,
  id: string,
  enabled: boolean
): Promise<ZpaServiceEdge> =>
  apiFetch<ZpaServiceEdge>(`${base(tenant)}/service-edges/${encodeURIComponent(id)}/enabled`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });

// ── PRA Portals ────────────────────────────────────────────────────────────────

export const patchPraPortalEnabled = (
  tenant: string,
  id: string,
  enabled: boolean
): Promise<ZpaPraPortal> =>
  apiFetch<ZpaPraPortal>(`${base(tenant)}/pra-portals/${encodeURIComponent(id)}/enabled`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });

export const deletePraPortal = (tenant: string, id: string): Promise<{ deleted: boolean }> =>
  apiFetch<{ deleted: boolean }>(`${base(tenant)}/pra-portals/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

// ── PRA Consoles ───────────────────────────────────────────────────────────────

export const listPraConsoles = (tenant: string, q?: string): Promise<ZpaPraConsole[]> =>
  apiFetch<ZpaPraConsole[]>(
    `${base(tenant)}/pra-consoles${q ? `?q=${encodeURIComponent(q)}` : ""}`
  );

export const patchPraConsoleEnabled = (
  tenant: string,
  id: string,
  enabled: boolean
): Promise<ZpaPraConsole> =>
  apiFetch<ZpaPraConsole>(`${base(tenant)}/pra-consoles/${encodeURIComponent(id)}/enabled`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });

export const deletePraConsole = (tenant: string, id: string): Promise<{ deleted: boolean }> =>
  apiFetch<{ deleted: boolean }>(`${base(tenant)}/pra-consoles/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

// ── Access Policy ──────────────────────────────────────────────────────────────

export const listAccessPolicyRules = (
  tenant: string,
  q?: string
): Promise<ZpaAccessPolicyRule[]> =>
  apiFetch<ZpaAccessPolicyRule[]>(
    `${base(tenant)}/access-policy/rules${q ? `?q=${encodeURIComponent(q)}` : ""}`
  );

export async function exportAccessPolicyCsv(tenant: string, tenantName: string): Promise<void> {
  const res = await fetch(
    `/api/v1/zpa/${encodeURIComponent(tenant)}/access-policy/rules/export.csv`,
    {
      headers: getAuthHeaders(),
      credentials: "include",
    }
  );
  if (!res.ok) throw new Error("Export failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `access_policy_${tenantName}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Identity ───────────────────────────────────────────────────────────────────

export const listSamlAttributes = (tenant: string, q?: string): Promise<ZpaSamlAttribute[]> =>
  apiFetch<ZpaSamlAttribute[]>(
    `${base(tenant)}/saml-attributes${q ? `?q=${encodeURIComponent(q)}` : ""}`
  );

export const listScimAttributes = (tenant: string, q?: string): Promise<ZpaScimAttribute[]> =>
  apiFetch<ZpaScimAttribute[]>(
    `${base(tenant)}/scim-attributes${q ? `?q=${encodeURIComponent(q)}` : ""}`
  );

export const listScimGroups = (tenant: string, q?: string): Promise<ZpaScimGroup[]> =>
  apiFetch<ZpaScimGroup[]>(
    `${base(tenant)}/scim-groups${q ? `?q=${encodeURIComponent(q)}` : ""}`
  );
