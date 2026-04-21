import { apiFetch } from "./client";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  force_password_change: boolean;
}

export function login(username: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function changePassword(current_password: string, new_password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/api/v1/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password, new_password }),
  });
}
