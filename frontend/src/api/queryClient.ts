import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,         // 30 seconds before considered stale
      gcTime: 5 * 60_000,        // 5 min garbage collection
      retry: 2,                   // 2 retries on failure
      refetchOnWindowFocus: true, // Refetch when tab gets focus
    },
  },
})
