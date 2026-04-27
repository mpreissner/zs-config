import { createContext, useContext, useState, useEffect, ReactNode } from "react";

const STORAGE_KEY = "zs-config:active-tenant-id";

interface ActiveTenantContextValue {
  activeTenantId: number | null;
  setActiveTenantId: (id: number | null) => void;
}

const ActiveTenantContext = createContext<ActiveTenantContextValue | null>(null);

export function ActiveTenantProvider({ children }: { children: ReactNode }) {
  const [activeTenantId, setActiveTenantIdState] = useState<number | null>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = parseInt(stored, 10);
      return isNaN(parsed) ? null : parsed;
    }
    return null;
  });

  useEffect(() => {
    if (activeTenantId !== null) {
      localStorage.setItem(STORAGE_KEY, String(activeTenantId));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [activeTenantId]);

  function setActiveTenantId(id: number | null) {
    setActiveTenantIdState(id);
  }

  return (
    <ActiveTenantContext.Provider value={{ activeTenantId, setActiveTenantId }}>
      {children}
    </ActiveTenantContext.Provider>
  );
}

export function useActiveTenant() {
  const ctx = useContext(ActiveTenantContext);
  if (!ctx) throw new Error("useActiveTenant must be used within ActiveTenantProvider");
  return ctx;
}
