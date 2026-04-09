import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from './client'
import type {
  Statistics,
  DailyStats,
  TradeListResponse,
  PortfolioSummary,
  PortfolioPosition,
  PortfolioDaily,
  PortfolioAllocation,
} from '../types'

// ── Query Key Factory ─────────────────────────────────────────
// Consistent keys for cache lookups, invalidation, and deduplication

export const queryKeys = {
  bots: {
    all: ['bots'] as const,
    list: (params: Record<string, unknown>) => ['bots', params] as const,
    detail: (id: number) => ['bots', id] as const,
    statistics: (id: number, params: Record<string, unknown>) => ['bots', id, 'statistics', params] as const,
    compare: (params: Record<string, unknown>) => ['bots', 'compare', params] as const,
  },
  trades: {
    all: ['trades'] as const,
    list: (filters: Record<string, unknown>) => ['trades', filters] as const,
  },
  portfolio: {
    all: ['portfolio'] as const,
    summary: (params: Record<string, unknown>) => ['portfolio', 'summary', params] as const,
    daily: (params: Record<string, unknown>) => ['portfolio', 'daily', params] as const,
    positions: ['portfolio', 'positions'] as const,
    allocation: ['portfolio', 'allocation'] as const,
  },
  dashboard: {
    stats: (params: Record<string, unknown>) => ['dashboard', 'stats', params] as const,
    daily: (params: Record<string, unknown>) => ['dashboard', 'daily', params] as const,
  },
  affiliateLinks: ['affiliate-links'] as const,
} as const

// ── Dashboard Queries ─────────────────────────────────────────

export function useDashboardStats(period: number, demoFilter: string) {
  const demoParam = demoFilter === 'demo' ? '&demo_mode=true' : demoFilter === 'live' ? '&demo_mode=false' : ''
  return useQuery<Statistics>({
    queryKey: queryKeys.dashboard.stats({ period, demoFilter }),
    queryFn: async () => {
      const { data } = await api.get(`/statistics?days=${period}${demoParam}`)
      return data
    },
  })
}

export function useDashboardDaily(period: number, demoFilter: string) {
  const demoParam = demoFilter === 'demo' ? '&demo_mode=true' : demoFilter === 'live' ? '&demo_mode=false' : ''
  return useQuery<{ days: DailyStats[] }>({
    queryKey: queryKeys.dashboard.daily({ period, demoFilter }),
    queryFn: async () => {
      const { data } = await api.get(`/statistics/daily?days=${period}${demoParam}`)
      return data
    },
  })
}

// ── Portfolio Queries ─────────────────────────────────────────

export function usePortfolioSummary(period: number, demoFilter: string) {
  const demoParam = demoFilter === 'demo' ? '&demo_mode=true' : demoFilter === 'live' ? '&demo_mode=false' : ''
  return useQuery<PortfolioSummary>({
    queryKey: queryKeys.portfolio.summary({ period, demoFilter }),
    queryFn: async () => {
      const { data } = await api.get(`/portfolio/summary?days=${period}${demoParam}`)
      return data
    },
  })
}

export function usePortfolioDaily(period: number, demoFilter: string) {
  const demoParam = demoFilter === 'demo' ? '&demo_mode=true' : demoFilter === 'live' ? '&demo_mode=false' : ''
  return useQuery<PortfolioDaily[]>({
    queryKey: queryKeys.portfolio.daily({ period, demoFilter }),
    queryFn: async () => {
      const { data } = await api.get(`/portfolio/daily?days=${period}${demoParam}`)
      return data.daily || data || []
    },
  })
}

export function usePortfolioPositions() {
  return useQuery<PortfolioPosition[]>({
    queryKey: queryKeys.portfolio.positions,
    queryFn: async () => {
      const { data } = await api.get('/portfolio/positions')
      return data.positions || data || []
    },
  })
}

export function usePortfolioAllocation() {
  return useQuery<PortfolioAllocation[]>({
    queryKey: queryKeys.portfolio.allocation,
    queryFn: async () => {
      const { data } = await api.get('/portfolio/allocation')
      return data.allocations || data || []
    },
  })
}

// ── Trade Queries ─────────────────────────────────────────────

export function useTrades(filters: Record<string, unknown>) {
  return useQuery<TradeListResponse>({
    queryKey: queryKeys.trades.list(filters),
    queryFn: async () => {
      const params = new URLSearchParams()
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== '' && value !== undefined && value !== null) {
          params.set(key, String(value))
        }
      })
      const { data } = await api.get(`/trades?${params}`)
      return data
    },
  })
}

// ── Bot Queries ───────────────────────────────────────────────

export function useBots(demoFilter: string) {
  const demoParam = demoFilter === 'demo' ? '?demo_mode=true' : demoFilter === 'live' ? '?demo_mode=false' : ''
  return useQuery<{ bots: unknown[] }>({
    queryKey: queryKeys.bots.list({ demoFilter }),
    queryFn: async () => {
      const { data } = await api.get(`/bots${demoParam}`)
      return data
    },
    refetchInterval: 5000, // Poll every 5 seconds (matches original setInterval)
  })
}

export function useBotStatistics(botId: number, days: number, demoFilter: string) {
  const demoParam = demoFilter === 'demo' ? '&demo_mode=true' : demoFilter === 'live' ? '&demo_mode=false' : ''
  return useQuery({
    queryKey: queryKeys.bots.statistics(botId, { days, demoFilter }),
    queryFn: async () => {
      const { data } = await api.get(`/bots/${botId}/statistics?days=${days}${demoParam}`)
      return data
    },
    enabled: botId > 0,
  })
}

export function useBotComparePerformance(days: number, demoFilter: string) {
  const dp = demoFilter === 'demo' ? '&demo_mode=true' : demoFilter === 'live' ? '&demo_mode=false' : ''
  return useQuery({
    queryKey: queryKeys.bots.compare({ days, demoFilter }),
    queryFn: async () => {
      const { data } = await api.get(`/bots/compare/performance?days=${days}${dp}`)
      return data.bots || []
    },
  })
}

export function useAffiliateLinks() {
  return useQuery({
    queryKey: queryKeys.affiliateLinks,
    queryFn: async () => {
      const { data } = await api.get('/affiliate-links')
      return data
    },
  })
}

// ── Mutations ─────────────────────────────────────────────────

export function useStartBot() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (botId: number) => api.post(`/bots/${botId}/start`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.bots.all }),
  })
}

export function useStopBot() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (botId: number) => api.post(`/bots/${botId}/stop`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.bots.all }),
  })
}

export function useDeleteBot() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (botId: number) => api.delete(`/bots/${botId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.bots.all }),
  })
}

export function useDuplicateBot() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (botId: number) => api.post(`/bots/${botId}/duplicate`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.bots.all }),
  })
}

export function useStopAllBots() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post('/bots/stop-all'),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.bots.all }),
  })
}

export function useClosePosition() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ botId, symbol }: { botId: number; symbol: string }) =>
      api.post(`/bots/${botId}/close-position/${symbol}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.bots.all }),
  })
}

export function useUpdateTpSl() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ tradeId, data }: { tradeId: number; data: Record<string, unknown> }) =>
      api.put(`/trades/${tradeId}/tp-sl`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.portfolio.positions })
    },
  })
}

export function useSyncTrades() {
  return useMutation({
    mutationFn: () => api.post('/trades/sync'),
  })
}
