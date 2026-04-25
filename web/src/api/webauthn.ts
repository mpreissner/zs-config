import { apiFetch } from "./client";

export interface WebAuthnCredential {
  credential_id: string;
  label: string | null;
  aaguid: string | null;
  created_at: string;
  last_used_at: string | null;
}

export const beginRegistration = (label: string): Promise<unknown> =>
  apiFetch<unknown>("/api/v1/auth/webauthn/register/begin", {
    method: "POST",
    body: JSON.stringify({ label }),
  });

export const completeRegistration = (
  label: string,
  credential: unknown
): Promise<{ ok: boolean; credential_id: string }> =>
  apiFetch<{ ok: boolean; credential_id: string }>(
    "/api/v1/auth/webauthn/register/complete",
    { method: "POST", body: JSON.stringify({ label, credential }) }
  );

export const beginAuthentication = (username: string): Promise<unknown> =>
  apiFetch<unknown>("/api/v1/auth/webauthn/authenticate/begin", {
    method: "POST",
    body: JSON.stringify({ username }),
  });

export const completeAuthentication = (
  username: string,
  credential: unknown
): Promise<{ access_token: string; token_type: string; force_password_change: boolean }> =>
  apiFetch<{ access_token: string; token_type: string; force_password_change: boolean }>(
    "/api/v1/auth/webauthn/authenticate/complete",
    { method: "POST", body: JSON.stringify({ username, credential }) }
  );

export const listCredentials = (): Promise<WebAuthnCredential[]> =>
  apiFetch<WebAuthnCredential[]>("/api/v1/auth/webauthn/credentials");

export const deleteCredential = (credentialId: string): Promise<void> =>
  apiFetch<void>(`/api/v1/auth/webauthn/credentials/${encodeURIComponent(credentialId)}`, {
    method: "DELETE",
  });

export const renameCredential = (
  credentialId: string,
  label: string
): Promise<{ credential_id: string; label: string }> =>
  apiFetch<{ credential_id: string; label: string }>(
    `/api/v1/auth/webauthn/credentials/${encodeURIComponent(credentialId)}`,
    { method: "PATCH", body: JSON.stringify({ label }) }
  );
