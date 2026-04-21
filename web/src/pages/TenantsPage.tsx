import { useQuery } from "@tanstack/react-query";
import { fetchTenants } from "../api/tenants";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorMessage from "../components/ErrorMessage";

export default function TenantsPage() {
  const { data: tenants, isLoading, error } = useQuery({
    queryKey: ["tenants"],
    queryFn: fetchTenants,
  });

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Tenants</h1>

      {isLoading && <LoadingSpinner />}
      {error && (
        <ErrorMessage
          message={error instanceof Error ? error.message : "Failed to load tenants"}
        />
      )}
      {tenants && (
        <div className="overflow-hidden shadow ring-1 ring-black ring-opacity-5 rounded-lg">
          <table className="min-w-full divide-y divide-gray-300">
            <thead className="bg-gray-50">
              <tr>
                <th className="py-3 pl-4 pr-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                  ID
                </th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Name
                </th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                  ZIdentity URL
                </th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                  OneAPI URL
                </th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Gov Cloud
                </th>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Created
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {tenants.length === 0 && (
                <tr>
                  <td
                    colSpan={6}
                    className="py-8 text-center text-sm text-gray-500"
                  >
                    No tenants configured.
                  </td>
                </tr>
              )}
              {tenants.map((t) => (
                <tr key={t.id} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap py-3 pl-4 pr-3 text-sm text-gray-500">
                    {t.id}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm font-medium text-gray-900">
                    {t.name}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">
                    {t.zidentity_base_url || "-"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">
                    {t.oneapi_base_url || "-"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">
                    {t.govcloud ? "Yes" : "No"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm text-gray-500">
                    {t.created_at
                      ? new Date(t.created_at).toLocaleDateString()
                      : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
