import { QueryClient } from "@tanstack/react-query";

export function createWorkbenchQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
