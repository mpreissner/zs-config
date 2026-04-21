import { useQuery } from "@tanstack/react-query";
import { fetchSystemInfo } from "../api/system";

export function useSystemInfo() {
  return useQuery({
    queryKey: ["system", "info"],
    queryFn: fetchSystemInfo,
    staleTime: 60_000,
  });
}
