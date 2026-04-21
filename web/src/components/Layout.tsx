import { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "../api/system";
import { useSystemInfo } from "../hooks/useSystemInfo";

interface LayoutProps {
  children: ReactNode;
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
    <div className="flex items-center gap-2 px-4 py-3 border-t border-gray-200 text-xs text-gray-500">
      <span
        className={`h-2 w-2 rounded-full flex-shrink-0 ${connected ? "bg-green-500" : "bg-red-500"}`}
      />
      <span>{connected ? "Connected" : "Disconnected"}</span>
      {sysInfo?.version && (
        <span className="ml-auto text-gray-400">v{sysInfo.version}</span>
      )}
    </div>
  );
}

const navItems = [
  { to: "/tenants", label: "Tenants" },
  { to: "/audit", label: "Audit Log" },
];

export default function Layout({ children }: LayoutProps) {
  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="w-56 bg-white border-r border-gray-200 flex flex-col">
        <div className="px-4 py-5">
          <span className="text-lg font-semibold text-gray-900">zs-config</span>
        </div>
        <nav className="flex-1 px-2 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `block px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-blue-50 text-blue-700"
                    : "text-gray-700 hover:bg-gray-100"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <StatusIndicator />
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto p-6">{children}</main>
    </div>
  );
}
