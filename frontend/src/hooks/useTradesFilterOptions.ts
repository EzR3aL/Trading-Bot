import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

// Global option lists that drive the Trades page filter dropdowns.
// Served by GET /api/trades/filter-options — scans ALL of the user's
// trades (not just the currently-rendered page) so dropdowns don't
// silently miss symbols/bots/exchanges that exist in older trades.

export interface TradeFilterBot {
  id: number
  name: string
}

export interface TradeFilterOptions {
  symbols: string[]
  bots: TradeFilterBot[]
  exchanges: string[]
  statuses: string[]
}

const EMPTY_OPTIONS: TradeFilterOptions = {
  symbols: [],
  bots: [],
  exchanges: [],
  statuses: [],
}

// Option lists don't change fast — 5 min of cache is plenty and keeps
// the network quiet while the user twiddles filters.
const FILTER_OPTIONS_STALE_MS = 5 * 60 * 1000

export function useTradesFilterOptions() {
  return useQuery<TradeFilterOptions>({
    queryKey: ['trades', 'filter-options'],
    queryFn: async () => {
      const { data } = await api.get<Partial<TradeFilterOptions>>('/trades/filter-options')
      // Defensive normalization — if the endpoint is missing a field
      // (or we're pointing at an older backend), fall back to empty
      // arrays so the UI keeps rendering.
      return {
        symbols: data.symbols ?? [],
        bots: data.bots ?? [],
        exchanges: data.exchanges ?? [],
        statuses: data.statuses ?? [],
      }
    },
    staleTime: FILTER_OPTIONS_STALE_MS,
    // If the endpoint isn't live yet in dev, don't spam retries —
    // the component falls back to empty lists and keeps working.
    retry: 1,
    placeholderData: EMPTY_OPTIONS,
  })
}
