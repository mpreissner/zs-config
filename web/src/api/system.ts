import { apiFetch } from "./client";

export interface SystemInfo {
  version: string;
  container_mode: boolean;
  db_path: string;
  plugin_dir: string | null;
}

export interface HealthStatus {
  status: string;
  version: string;
}

export function fetchSystemInfo(): Promise<SystemInfo> {
  return apiFetch<SystemInfo>("/api/v1/system/info");
}

export function fetchHealth(): Promise<HealthStatus> {
  return apiFetch<HealthStatus>("/health");
}
