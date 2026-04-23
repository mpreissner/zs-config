import { apiFetch } from "./client";

export interface ZdxDevice {
  id?: string;
  name?: string;
  user?: string;
  [key: string]: unknown;
}

export interface ZdxUser {
  id?: string;
  name?: string;
  email?: string;
  [key: string]: unknown;
}

const base = (tenant: string) => `/api/v1/zdx/${encodeURIComponent(tenant)}`;

export const searchDevices = (
  tenant: string,
  query?: string,
  hours?: number
): Promise<ZdxDevice[]> => {
  const qs = new URLSearchParams();
  if (query) qs.set("query", query);
  if (hours !== undefined) qs.set("hours", String(hours));
  const q = qs.toString();
  return apiFetch<ZdxDevice[]>(`${base(tenant)}/devices${q ? `?${q}` : ""}`);
};

export const getDevice = (tenant: string, deviceId: string): Promise<unknown> =>
  apiFetch<unknown>(`${base(tenant)}/devices/${encodeURIComponent(deviceId)}`);

export const lookupUsers = (tenant: string, query?: string): Promise<ZdxUser[]> => {
  const qs = query ? `?query=${encodeURIComponent(query)}` : "";
  return apiFetch<ZdxUser[]>(`${base(tenant)}/users${qs}`);
};
