import { apiFetch } from "./client";

export interface ZidUser {
  id?: string;
  login_name?: string;
  display_name?: string;
  primary_email?: string;
  [key: string]: unknown;
}

export interface ZidGroup {
  id?: string;
  name?: string;
  type?: string;
  [key: string]: unknown;
}

export interface ZidApiClient {
  id?: string;
  name?: string;
  created_at?: string;
  modified_at?: string;
  [key: string]: unknown;
}

export interface ZidApiClientSecret {
  secret_id?: string;
  created_at?: string;
  expires_at?: string | null;
  [key: string]: unknown;
}

const base = (tenant: string) => `/api/v1/zid/${encodeURIComponent(tenant)}`;

export const listUsers = (
  tenant: string,
  params?: { login_name?: string; display_name?: string; primary_email?: string; domain_name?: string }
): Promise<ZidUser[]> => {
  const qs = new URLSearchParams();
  if (params?.login_name) qs.set("login_name", params.login_name);
  if (params?.display_name) qs.set("display_name", params.display_name);
  if (params?.primary_email) qs.set("primary_email", params.primary_email);
  if (params?.domain_name) qs.set("domain_name", params.domain_name);
  const q = qs.toString();
  return apiFetch<ZidUser[]>(`${base(tenant)}/users${q ? `?${q}` : ""}`);
};

export const listGroups = (
  tenant: string,
  params?: { name?: string; exclude_dynamic?: boolean }
): Promise<ZidGroup[]> => {
  const qs = new URLSearchParams();
  if (params?.name) qs.set("name", params.name);
  if (params?.exclude_dynamic !== undefined) qs.set("exclude_dynamic", String(params.exclude_dynamic));
  const q = qs.toString();
  return apiFetch<ZidGroup[]>(`${base(tenant)}/groups${q ? `?${q}` : ""}`);
};

export const getGroupMembers = (tenant: string, groupId: string): Promise<ZidUser[]> =>
  apiFetch<ZidUser[]>(`${base(tenant)}/groups/${encodeURIComponent(groupId)}/members`);

export const addGroupMember = (
  tenant: string,
  groupId: string,
  body: { user_id: string; username: string }
): Promise<{ ok: boolean }> =>
  apiFetch<{ ok: boolean }>(`${base(tenant)}/groups/${encodeURIComponent(groupId)}/members`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const removeGroupMember = (
  tenant: string,
  groupId: string,
  userId: string
): Promise<void> =>
  apiFetch<void>(`${base(tenant)}/groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(userId)}`, {
    method: "DELETE",
  });

export const listApiClients = (
  tenant: string,
  params?: { name?: string }
): Promise<ZidApiClient[]> => {
  const qs = params?.name ? `?name=${encodeURIComponent(params.name)}` : "";
  return apiFetch<ZidApiClient[]>(`${base(tenant)}/api-clients${qs}`);
};

export const getApiClientSecrets = (
  tenant: string,
  clientId: string
): Promise<ZidApiClientSecret[]> =>
  apiFetch<ZidApiClientSecret[]>(`${base(tenant)}/api-clients/${encodeURIComponent(clientId)}/secrets`);

export const addApiClientSecret = (
  tenant: string,
  clientId: string,
  body?: { expires_at?: string | null }
): Promise<{ secret_id: string; client_secret: string }> =>
  apiFetch<{ secret_id: string; client_secret: string }>(
    `${base(tenant)}/api-clients/${encodeURIComponent(clientId)}/secrets`,
    { method: "POST", body: JSON.stringify(body ?? {}) }
  );

export const deleteApiClientSecret = (
  tenant: string,
  clientId: string,
  secretId: string
): Promise<void> =>
  apiFetch<void>(
    `${base(tenant)}/api-clients/${encodeURIComponent(clientId)}/secrets/${encodeURIComponent(secretId)}`,
    { method: "DELETE" }
  );

export const deleteApiClient = (tenant: string, clientId: string): Promise<void> =>
  apiFetch<void>(`${base(tenant)}/api-clients/${encodeURIComponent(clientId)}`, {
    method: "DELETE",
  });

export const resetUserPassword = (
  tenant: string,
  userId: string
): Promise<{ temporary_password: string }> =>
  apiFetch<{ temporary_password: string }>(
    `${base(tenant)}/users/${encodeURIComponent(userId)}/reset-password`,
    { method: "POST" }
  );

export const setUserPassword = (
  tenant: string,
  userId: string,
  body: { password: string; reset_on_login: boolean }
): Promise<{ ok: boolean }> =>
  apiFetch<{ ok: boolean }>(
    `${base(tenant)}/users/${encodeURIComponent(userId)}/password`,
    { method: "PUT", body: JSON.stringify(body) }
  );

export const skipUserMfa = (
  tenant: string,
  userId: string,
  body: { until_timestamp: number }
): Promise<{ ok: boolean }> =>
  apiFetch<{ ok: boolean }>(
    `${base(tenant)}/users/${encodeURIComponent(userId)}/skip-mfa`,
    { method: "POST", body: JSON.stringify(body) }
  );
