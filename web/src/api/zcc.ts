import { apiFetch } from "./client";

export interface ZccDevice {
  udid: string;
  hostname?: string;
  username?: string;
  os_type?: number;
  os_version?: string;
  registration_state?: string;
  owner?: string;
  [key: string]: unknown;
}

export interface ZccTrustedNetwork {
  id?: string;
  name?: string;
  [key: string]: unknown;
}

export interface ZccForwardingProfile {
  id?: string;
  name?: string;
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

// ── Traffic Profile types and fetch ─────────────────────────────────────────

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
  rawPolicySnippet: Record<string, unknown>;
  rawForwardingSnippet: Record<string, unknown> | null;
}

export const fetchTrafficProfile = (
  tenantName: string,
  policyId: string,
): Promise<TrafficProfile> =>
  apiFetch<TrafficProfile>(`/api/v1/zcc/${encodeURIComponent(tenantName)}/traffic-profile/${encodeURIComponent(policyId)}`);
