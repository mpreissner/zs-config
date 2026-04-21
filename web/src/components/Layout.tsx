import { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "../api/system";
import { useSystemInfo } from "../hooks/useSystemInfo";
import { useAuth } from "../context/AuthContext";

interface LayoutProps {
  children: ReactNode;
}

function ZscalerMark() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="28" height="28" rx="6" fill="white" fillOpacity="0.15" />
      <text x="5" y="21" fontFamily="Arial, sans-serif" fontWeight="bold" fontSize="18" fill="white">Z</text>
    </svg>
  );
}

function StatusIndicator() {
  const { data: health, isError } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
  });
  const { data: sysInfo } = useSystemInfo();
  const connected = health?.status === "ok" && !isError;

  return (
    <div className="flex items-center gap-2 px-4 py-3 border-t border-zs-600 text-xs text-blue-100">
      <span className={`h-2 w-2 rounded-full flex-shrink-0 ${connected ? "bg-green-400" : "bg-red-400"}`} />
      <span>{connected ? "Connected" : "Disconnected"}</span>
      {sysInfo?.version && (
        <span className="ml-auto text-blue-200">v{sysInfo.version}</span>
      )}
    </div>
  );
}

const navItems = [
  { to: "/tenants", label: "Tenants" },
  { to: "/audit", label: "Audit Log" },
];

export default function Layout({ children }: LayoutProps) {
  const { logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  return (
    <div className="flex h-screen bg-gray-50">
      <aside className="w-56 bg-zs-500 flex flex-col">
        <div className="flex items-center gap-3 px-4 py-5">
          <ZscalerMark />
          <span className="text-lg font-semibold text-white tracking-tight">zs-config</span>
        </div>
        <nav className="flex-1 px-2 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `block px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-white text-zs-500 font-semibold"
                    : "text-blue-100 hover:bg-zs-600 hover:text-white"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="px-2 pb-2">
          <button
            onClick={handleLogout}
            className="w-full text-left block px-3 py-2 rounded-md text-sm font-medium text-blue-100 hover:bg-zs-600 hover:text-white transition-colors"
          >
            Sign out
          </button>
        </div>
        <StatusIndicator />
      </aside>
      <main className="flex-1 overflow-y-auto p-6">{children}</main>
    </div>
  );
}
