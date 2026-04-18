import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import i18n from '../i18n/config'
import api from './client'
import { useToastStore } from '../stores/toastStore'
import type {
  Statistics,
  DailyStats,
  TradeListResponse,
  PortfolioSummary,
  PortfolioPosition,
  PortfolioDaily,
  PortfolioAllocation,
  RiskLegStatus,
  RiskStateResponse,
  UpdateTpSlPayload,
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
    detail: (id: number) => ['trades', 'detail', id] as const,
    riskState: (id: number) => ['trades', 'riskState', id] as const,
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

// ── Risk-State Queries (Epic #188, Issue #195) ───────────────────
// Readback snapshot from GET /trades/{id}/risk-state. Source of truth:
// RiskStateManager.reconcile() — probes the exchange and writes the
// aligned state back to the DB. Fresh for 10 seconds so rapid re-renders
// don't spam the backend; use queryClient.invalidateQueries to force
// a refetch after mutations.
const RISK_STATE_STALE_MS = 10_000

export function useRiskState(tradeId: number | null) {
  return useQuery<RiskStateResponse>({
    queryKey: queryKeys.trades.riskState(tradeId ?? -1),
    queryFn: async () => {
      const { data } = await api.get<RiskStateResponse>(
        `/trades/${tradeId}/risk-state`,
      )
      return data
    },
    enabled: tradeId !== null,
    staleTime: RISK_STATE_STALE_MS,
  })
}

// ── TP/SL Mutation with Optimistic Updates (Issue #195) ──────────
// Each leg (tp/sl/trailing) is applied independently on the backend and
// its outcome surfaces via the RiskStateResponse. Optimistic updates
// populate the trade-detail cache with a PENDING entry so the UI shows
// immediate feedback; onError rolls back on HTTP failure; onSuccess
// replaces the cache with the server-confirmed readback. Concurrent
// mutations are serialized by TanStack Query's default single-mutation
// behavior when using mutate() off the same hook instance.

export interface UpdateTpSlVars {
  tradeId: number
  data: UpdateTpSlPayload
  idempotencyKey?: string
}

interface TpSlMutationContext {
  previous: RiskStateResponse | undefined
}

function makePendingLeg(value: RiskLegStatus['value']): RiskLegStatus {
  return {
    value,
    status: 'pending',
    order_id: null,
    error: null,
    latency_ms: 0,
  }
}

function clearedLeg(): RiskLegStatus {
  return {
    value: null,
    status: 'pending',
    order_id: null,
    error: null,
    latency_ms: 0,
  }
}

function buildOptimisticSnapshot(
  existing: RiskStateResponse | undefined,
  tradeId: number,
  vars: UpdateTpSlVars,
): RiskStateResponse {
  const base: RiskStateResponse = existing ?? {
    trade_id: tradeId,
    tp: null,
    sl: null,
    trailing: null,
    applied_at: new Date().toISOString(),
    overall_status: 'no_change',
  }

  const next: RiskStateResponse = { ...base, trade_id: tradeId }

  if (vars.data.remove_tp) {
    next.tp = clearedLeg()
  } else if (vars.data.take_profit !== undefined && vars.data.take_profit !== null) {
    next.tp = makePendingLeg(vars.data.take_profit)
  }

  if (vars.data.remove_sl) {
    next.sl = clearedLeg()
  } else if (vars.data.stop_loss !== undefined && vars.data.stop_loss !== null) {
    next.sl = makePendingLeg(vars.data.stop_loss)
  }

  if (vars.data.remove_trailing) {
    next.trailing = clearedLeg()
  } else if (vars.data.trailing_stop) {
    next.trailing = makePendingLeg(vars.data.trailing_stop)
  }

  return next
}

function describeRejectedLegs(response: RiskStateResponse): string {
  const legs: Array<RiskLegStatus | null> = [response.tp, response.sl, response.trailing]
  const errors = legs
    .filter((leg): leg is RiskLegStatus =>
      leg !== null && (leg.status === 'rejected' || leg.status === 'cancel_failed'),
    )
    .map((leg) => leg.error ?? leg.status)
  return errors.join(', ')
}

export function useUpdateTpSl() {
  const qc = useQueryClient()
  const addToast = useToastStore.getState().addToast

  return useMutation<RiskStateResponse, Error, UpdateTpSlVars, TpSlMutationContext>({
    mutationFn: async ({ tradeId, data, idempotencyKey }) => {
      const headers: Record<string, string> = {}
      if (idempotencyKey) {
        headers['Idempotency-Key'] = idempotencyKey
      }
      const { data: response } = await api.put<RiskStateResponse>(
        `/trades/${tradeId}/tp-sl`,
        data,
        { headers },
      )
      return response
    },

    onMutate: async (vars) => {
      // Cancel in-flight risk-state reads so we don't clobber the
      // optimistic snapshot with stale server data
      await qc.cancelQueries({
        queryKey: queryKeys.trades.riskState(vars.tradeId),
      })
      const previous = qc.getQueryData<RiskStateResponse>(
        queryKeys.trades.riskState(vars.tradeId),
      )
      const optimistic = buildOptimisticSnapshot(previous, vars.tradeId, vars)
      qc.setQueryData(
        queryKeys.trades.riskState(vars.tradeId),
        optimistic,
      )
      return { previous }
    },

    onError: (_err, vars, ctx) => {
      // Roll back to pre-mutation snapshot
      if (ctx?.previous !== undefined) {
        qc.setQueryData(
          queryKeys.trades.riskState(vars.tradeId),
          ctx.previous,
        )
      } else {
        qc.removeQueries({ queryKey: queryKeys.trades.riskState(vars.tradeId) })
      }
      addToast('error', i18n.t('trades.riskState.updateFailed'))
    },

    onSuccess: (data, vars) => {
      // Replace optimistic snapshot with server-confirmed readback
      qc.setQueryData(queryKeys.trades.riskState(vars.tradeId), data)

      if (data.overall_status === 'partial_success') {
        addToast(
          'warning',
          i18n.t('trades.riskState.partialSuccess', {
            failed: describeRejectedLegs(data),
          }),
        )
      } else if (data.overall_status === 'all_rejected') {
        addToast(
          'error',
          i18n.t('trades.riskState.partialSuccess', {
            failed: describeRejectedLegs(data),
          }),
        )
      } else if (data.overall_status === 'all_confirmed') {
        addToast('success', i18n.t('trades.riskState.updated'))
      }
    },

    onSettled: async (_data, _err, vars) => {
      // Full cache invalidation — list, detail, risk-state, positions, summary.
      // Each trade row on the positions page reads from portfolio.positions;
      // the trades page reads from trades.list; the edit panel reads from
      // trades.riskState. All three must refresh after a mutation.
      //
      // CRITICAL: we await the invalidations so mutateAsync() resolves only
      // after the caches have been refreshed. Without the await, the modal's
      // handleSave returns immediately and onClose() unmounts before the
      // refetch lands — the next open then renders the previous (stale)
      // position snapshot until the user reloads the page.
      await Promise.all([
        qc.invalidateQueries({ queryKey: queryKeys.trades.all }),
        qc.invalidateQueries({ queryKey: queryKeys.portfolio.positions }),
        qc.invalidateQueries({ queryKey: queryKeys.portfolio.all }),
        qc.invalidateQueries({
          queryKey: queryKeys.trades.riskState(vars.tradeId),
        }),
      ])
    },
  })
}

export function useSyncTrades() {
  return useMutation({
    mutationFn: () => api.post('/trades/sync'),
  })
}
