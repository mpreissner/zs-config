import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";
import { apiFetch, setTokenGetter } from "../api/client";

interface TokenPayload {
  sub: number;
  username: string;
  role: string;
  fpc: boolean;
  mfa_enroll?: boolean;
  exp: number;
}

interface AuthState {
  token: string | null;
  user: TokenPayload | null;
}

interface AuthContextValue extends AuthState {
  login: (token: string) => void;
  logout: () => void;
  isAuthenticated: boolean;
  isAdmin: boolean;
  mfaEnrollRequired: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function parseToken(token: string): TokenPayload | null {
  try {
    const payload = token.split(".")[1];
    return JSON.parse(atob(payload)) as TokenPayload;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState>({ token: null, user: null });
  const [ready, setReady] = useState(false);

  const login = useCallback((token: string) => {
    const user = parseToken(token);
    setAuth({ token, user });
  }, []);

  const logout = useCallback(async () => {
    try { await apiFetch("/api/v1/auth/logout", { method: "POST" }); } catch { /* ignore */ }
    setAuth({ token: null, user: null });
  }, []);

  useEffect(() => {
    setTokenGetter(() => auth.token);
  }, [auth.token]);

  useEffect(() => {
    apiFetch<{ access_token: string }>("/api/v1/auth/refresh", { method: "POST" })
      .then((r) => login(r.access_token))
      .catch(() => {})
      .finally(() => setReady(true));
  }, [login]);

  if (!ready) return null;

  return (
    <AuthContext.Provider value={{
      ...auth,
      login,
      logout,
      isAuthenticated: !!auth.token,
      isAdmin: auth.user?.role === "admin",
      mfaEnrollRequired: !!auth.user?.mfa_enroll,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
