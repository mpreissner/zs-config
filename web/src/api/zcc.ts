import { apiFetch } from "./client";

export interface ZccDevice {
  udid: string;
  machine_hostname?: string;
  user?: string;
  type?: number;
  os_version?: string;
  registration_state?: string;
  [key: string]: unknown;
}

export interface ZccTrustedNetwork {
  id?: string;
  name?: string;
  networkName?: string;
  [key: string]: unknown;
}

export interface ZccFpAction {
  action_type?: number;
  enable_packet_tunnel?: number;
  primary_transport?: number;
  system_proxy?: number;
  system_proxy_data?: { enable_proxy_server?: number; [key: string]: unknown };
  network_type?: number;
  [key: string]: unknown;
}

export interface ZccFpZpaAction {
  action_type?: number;
  primary_transport?: number;
  network_type?: number;
  [key: string]: unknown;
}

export interface ZccForwardingProfile {
  id?: string;
  name?: string;
  active?: string | number | boolean;
  trusted_networks?: string[];
  trusted_network_ids?: string[];
  predefined_trusted_networks?: boolean;
  predefined_tn_all?: boolean;
  forwarding_profile_actions?: ZccFpAction[];
  forwarding_profile_zpa_actions?: ZccFpZpaAction[];
  [key: string]: unknown;
}

export interface ZccWebPolicy {
  id?: string;
  name?: string;
  [key: string]: unknown;
}

export interface ZccWebAppService {
  id?: string;
  name?: string;
  appName?: string;
  [key: string]: unknown;
}

export interface ZccAdminRole {
  id?: string;
  name?: string;
  roleName?: string;
  [key: string]: unknown;
}

export interface ZccFailOpenPolicy {
  id?: string;
  name?: string;
  enableFailOpen?: boolean;
  active?: boolean;
  [key: string]: unknown;
}

export interface ZccWebPrivacy {
  id?: string;
  name?: string;
  collectUserInfo?: boolean;
  collectMachineHostname?: boolean;
  enablePacketCapture?: boolean;
  [key: string]: unknown;
}

export interface ZccIpApp {
  id?: string;
  name?: string;
  appName?: string;
  appDataBlob?: string[];
  appDataBlobV6?: string[];
  active?: string;
  [key: string]: unknown;
}

export interface ZccProcessApp {
  id?: string;
  name?: string;
  appName?: string;
  processNames?: string[];
  active?: string;
  [key: string]: unknown;
}

export interface ZccRemoveBody {
  udids: string[];
  os_type: number;
}

const base = (tenant: string) => `/api/v1/zcc/${encodeURIComponent(tenant)}`;

export const listDevices = (
  tenant: string,
  params?: { username?: string; os_type?: number; page_size?: number }
): Promise<ZccDevice[]> => {
  const qs = new URLSearchParams();
  if (params?.username) qs.set("username", params.username);
  if (params?.os_type !== undefined) qs.set("os_type", String(params.os_type));
  if (params?.page_size !== undefined) qs.set("page_size", String(params.page_size));
  const query = qs.toString();
  return apiFetch<ZccDevice[]>(`${base(tenant)}/devices${query ? `?${query}` : ""}`);
};

export const removeDevices = (
  tenant: string,
  body: ZccRemoveBody
): Promise<unknown> =>
  apiFetch<unknown>(`${base(tenant)}/devices/remove`, {
    method: "DELETE",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });

export const forceRemoveDevices = (
  tenant: string,
  body: ZccRemoveBody
): Promise<unknown> =>
  apiFetch<unknown>(`${base(tenant)}/devices/force-remove`, {
    method: "DELETE",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });

export const getDeviceOtp = (tenant: string, udid: string): Promise<{ otp: string }> =>
  apiFetch<{ otp: string }>(`${base(tenant)}/devices/otp/${encodeURIComponent(udid)}`);

export const listTrustedNetworks = (tenant: string): Promise<ZccTrustedNetwork[]> =>
  apiFetch<ZccTrustedNetwork[]>(`${base(tenant)}/trusted-networks`);

export const listForwardingProfiles = (tenant: string): Promise<ZccForwardingProfile[]> =>
  apiFetch<ZccForwardingProfile[]>(`${base(tenant)}/forwarding-profiles`);

export const listWebPolicies = (tenant: string): Promise<ZccWebPolicy[]> =>
  apiFetch<ZccWebPolicy[]>(`${base(tenant)}/web-policies`);

export const listWebAppServices = (tenant: string): Promise<ZccWebAppService[]> =>
  apiFetch<ZccWebAppService[]>(`${base(tenant)}/web-app-services`);

export const listAdminRoles = (tenant: string): Promise<ZccAdminRole[]> =>
  apiFetch<ZccAdminRole[]>(`${base(tenant)}/admin-roles`);

export const listFailOpenPolicies = (tenant: string): Promise<ZccFailOpenPolicy[]> =>
  apiFetch<ZccFailOpenPolicy[]>(`${base(tenant)}/fail-open-policies`);

export const getWebPrivacy = (tenant: string): Promise<ZccWebPrivacy> =>
  apiFetch<ZccWebPrivacy>(`${base(tenant)}/web-privacy`);

export const listIpAppsPredefined = (tenant: string): Promise<ZccIpApp[]> =>
  apiFetch<ZccIpApp[]>(`${base(tenant)}/ip-apps/predefined`);

export const listIpAppsCustom = (tenant: string): Promise<ZccIpApp[]> =>
  apiFetch<ZccIpApp[]>(`${base(tenant)}/ip-apps/custom`);

export const listProcessApps = (tenant: string): Promise<ZccProcessApp[]> =>
  apiFetch<ZccProcessApp[]>(`${base(tenant)}/process-apps`);

// ── Traffic Profile types and fetch ─────────────────────────────────────────

export interface PolicyTarget {
  id: string;
  name: string;
}

export interface PortBypass {
  port: string;
  protocol: string;
}

export interface ProcessBypass {
  processName: string;
  platform: string;
}

export interface VpnGatewayBypass {
  gateway: string;
}

export interface TunnelRoute {
  cidr: string;
  direction: "include" | "exclude";
  ipVersion: "ipv4" | "ipv6";
}

export interface DnsRoute {
  suffix: string;
  direction: "include" | "exclude";
}

export interface PacConfig {
  url: string | null;
  profilePacUrl: string | null;
  customPacContent: number | null;  // length in bytes, not raw content
  enablePac: boolean;
  ziaPacFileId: number | null;
  ziaPacFileName: string | null;
}

export type TunnelMode = "Z-Tunnel 1.0" | "Z-Tunnel 2.0" | "Proxy" | "Unknown";

export interface TrafficProfile {
  policyId: string;
  policyName: string;
  active: boolean;
  tunnelMode: TunnelMode;
  forwardingProfileName: string | null;
  forwardingProfileId: string | null;
  pac: PacConfig;
  processBypasses: ProcessBypass[];
  portBypasses: PortBypass[];
  vpnGatewayBypasses: VpnGatewayBypass[];
  tunnelRoutes: TunnelRoute[];
  dnsRoutes: DnsRoute[];
  tunnelZappTraffic: boolean;
  trustedNetworks: string[];
  zpaEnabled: boolean;
  deviceType: string | null;
  targetUsers: PolicyTarget[];
  targetGroups: PolicyTarget[];
  targetDepartments: PolicyTarget[];
  rawPolicySnippet: Record<string, unknown>;
  rawForwardingSnippet: Record<string, unknown> | null;
}

export const fetchTrafficProfile = (
  tenantName: string,
  policyId: string,
): Promise<TrafficProfile> =>
  apiFetch<TrafficProfile>(`/api/v1/zcc/${encodeURIComponent(tenantName)}/traffic-profile/${encodeURIComponent(policyId)}`);

// ── Snapshot types and API ───────────────────────────────────────────────────

export interface ZccSnapshot {
  id: number;
  tenant_id: number;
  label: string;
  note: string | null;
  created_at: string;
  resource_count: number;
}

export interface ZccDiffEntry {
  resource_type: string;
  added_since: number;
  removed_since: number;
  changed_since: number;
  unchanged: number;
  restorable: boolean;
}

export interface ZccRestoreResult {
  resource_type: string;
  action: string;
  name: string | null;
  success: boolean;
  reason: string | null;
}

export interface ZccRestoreSummary {
  created: number;
  updated: number;
  deleted: number;
  skipped: number;
  failed: number;
  unrestorable: number;
}

export interface ZccRestoreResponse {
  snapshot_id: number;
  dry_run: boolean;
  results: ZccRestoreResult[];
  summary: ZccRestoreSummary;
}

export interface ZccSnapshotCreateBody {
  label: string;
  note?: string;
}

export interface ZccSnapshotRestoreBody {
  resource_types?: string[];
  dry_run?: boolean;
  target_tenant?: string;
}

export const listZccSnapshots = (tenant: string): Promise<ZccSnapshot[]> =>
  apiFetch<ZccSnapshot[]>(`${base(tenant)}/snapshots`);

export const createZccSnapshot = (
  tenant: string,
  body: ZccSnapshotCreateBody
): Promise<ZccSnapshot> =>
  apiFetch<ZccSnapshot>(`${base(tenant)}/snapshots`, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });

export const deleteZccSnapshot = (
  tenant: string,
  snapshotId: number
): Promise<{ deleted: boolean }> =>
  apiFetch<{ deleted: boolean }>(`${base(tenant)}/snapshots/${snapshotId}`, {
    method: "DELETE",
  });

export const diffZccSnapshot = (
  tenant: string,
  snapshotId: number
): Promise<ZccDiffEntry[]> =>
  apiFetch<ZccDiffEntry[]>(`${base(tenant)}/snapshots/${snapshotId}/diff`);

export const restoreZccSnapshot = (
  tenant: string,
  snapshotId: number,
  body: ZccSnapshotRestoreBody
): Promise<ZccRestoreResponse> =>
  apiFetch<ZccRestoreResponse>(`${base(tenant)}/snapshots/${snapshotId}/restore`, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });
