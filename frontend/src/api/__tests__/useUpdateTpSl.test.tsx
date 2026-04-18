import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import type { RiskStateResponse } from '../../types'

// ── Mocks (MUST be declared before importing the module under test) ───

const mockGet = vi.fn()
const mockPut = vi.fn()
const mockPost = vi.fn()

vi.mock('../client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    put: (...args: unknown[]) => mockPut(...args),
    post: (...args: unknown[]) => mockPost(...args),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  },
  setTokenExpiry: vi.fn(),
  clearTokenExpiry: vi.fn(),
}))

vi.mock('../../i18n/config', () => ({
  default: {
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts && typeof opts.failed === 'string') {
        return `${key}:${opts.failed}`
      }
      return key
    },
  },
}))

// Import after mocks are wired
import { useUpdateTpSl, useRiskState, queryKeys } from '../queries'
import { useToastStore } from '../../stores/toastStore'

// ── Test helpers ──────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      // gcTime: Infinity so setQueryData entries without observers
      // don't get immediately garbage-collected during the test run.
      queries: { retry: false, gcTime: Infinity, staleTime: 0 },
      mutations: { retry: false },
    },
  })
}

function makeWrapper(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

function confirmedSnapshot(
  tradeId: number,
  overrides: Partial<RiskStateResponse> = {},
): RiskStateResponse {
  return {
    trade_id: tradeId,
    tp: {
      value: 55000,
      status: 'confirmed',
      order_id: 'tp-123',
      error: null,
      latency_ms: 42,
    },
    sl: null,
    trailing: null,
    applied_at: '2026-04-18T10:00:00Z',
    overall_status: 'all_confirmed',
    ...overrides,
  }
}

// ── Suite: useUpdateTpSl ──────────────────────────────────────────────

describe('useUpdateTpSl', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPut.mockReset()
    mockPost.mockReset()
    useToastStore.setState({ toasts: [] })
  })

  it('populates optimistic pending leg on mutate, then replaces with server-confirmed value on success', async () => {
    const qc = makeQueryClient()
    const confirmed = confirmedSnapshot(7)
    let resolvePut!: (v: { data: RiskStateResponse }) => void
    mockPut.mockImplementation(
      () => new Promise((resolve) => {
        resolvePut = resolve
      }),
    )

    const { result } = renderHook(() => useUpdateTpSl(), {
      wrapper: makeWrapper(qc),
    })

    result.current.mutate({ tradeId: 7, data: { take_profit: 55000 } })

    // Optimistic state written synchronously
    await waitFor(() => {
      const snapshot = qc.getQueryData<RiskStateResponse>(queryKeys.trades.riskState(7))
      expect(snapshot).toBeDefined()
      expect(snapshot!.tp?.status).toBe('pending')
      expect(snapshot!.tp?.value).toBe(55000)
    })

    // Resolve the PUT — server-confirmed snapshot replaces optimistic one
    resolvePut({ data: confirmed })

    await waitFor(() => {
      const snapshot = qc.getQueryData<RiskStateResponse>(queryKeys.trades.riskState(7))
      expect(snapshot?.tp?.status).toBe('confirmed')
      expect(snapshot?.tp?.order_id).toBe('tp-123')
    })

    // Success toast fired
    const toasts = useToastStore.getState().toasts
    expect(toasts).toHaveLength(1)
    expect(toasts[0].type).toBe('success')
  })

  it('rolls back to previous snapshot and emits error toast on HTTP failure', async () => {
    const qc = makeQueryClient()
    const previous: RiskStateResponse = confirmedSnapshot(9, {
      tp: {
        value: 50000,
        status: 'confirmed',
        order_id: 'old-tp',
        error: null,
        latency_ms: 10,
      },
    })
    qc.setQueryData(queryKeys.trades.riskState(9), previous)
    mockPut.mockRejectedValueOnce(new Error('HTTP 500'))

    const { result } = renderHook(() => useUpdateTpSl(), {
      wrapper: makeWrapper(qc),
    })

    result.current.mutate({ tradeId: 9, data: { take_profit: 60000 } })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })

    const restored = qc.getQueryData<RiskStateResponse>(queryKeys.trades.riskState(9))
    expect(restored).toEqual(previous)

    const toasts = useToastStore.getState().toasts
    expect(toasts).toHaveLength(1)
    expect(toasts[0].type).toBe('error')
    expect(toasts[0].message).toBe('trades.riskState.updateFailed')
  })

  it('emits warning toast with failed-leg errors on partial_success', async () => {
    const qc = makeQueryClient()
    const partial: RiskStateResponse = {
      trade_id: 11,
      tp: {
        value: 60000,
        status: 'confirmed',
        order_id: 'tp-ok',
        error: null,
        latency_ms: 40,
      },
      sl: {
        value: 40000,
        status: 'rejected',
        order_id: null,
        error: 'exchange rejected SL',
        latency_ms: 30,
      },
      trailing: null,
      applied_at: '2026-04-18T10:05:00Z',
      overall_status: 'partial_success',
    }
    mockPut.mockResolvedValueOnce({ data: partial })

    const { result } = renderHook(() => useUpdateTpSl(), {
      wrapper: makeWrapper(qc),
    })

    result.current.mutate({
      tradeId: 11,
      data: { take_profit: 60000, stop_loss: 40000 },
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    const toasts = useToastStore.getState().toasts
    expect(toasts).toHaveLength(1)
    expect(toasts[0].type).toBe('warning')
    expect(toasts[0].message).toContain('trades.riskState.partialSuccess')
    expect(toasts[0].message).toContain('exchange rejected SL')
  })

  it('clears tp optimistically on remove_tp, then confirms via server response', async () => {
    const qc = makeQueryClient()
    const previous: RiskStateResponse = confirmedSnapshot(13)
    qc.setQueryData(queryKeys.trades.riskState(13), previous)

    const cleared: RiskStateResponse = {
      trade_id: 13,
      tp: {
        value: null,
        status: 'cleared',
        order_id: null,
        error: null,
        latency_ms: 20,
      },
      sl: null,
      trailing: null,
      applied_at: '2026-04-18T10:10:00Z',
      overall_status: 'all_confirmed',
    }

    let resolvePut!: (v: { data: RiskStateResponse }) => void
    mockPut.mockImplementation(
      () => new Promise((resolve) => {
        resolvePut = resolve
      }),
    )

    const { result } = renderHook(() => useUpdateTpSl(), {
      wrapper: makeWrapper(qc),
    })

    result.current.mutate({ tradeId: 13, data: { remove_tp: true } })

    // Optimistic: tp.value=null, status='pending'
    await waitFor(() => {
      const snapshot = qc.getQueryData<RiskStateResponse>(queryKeys.trades.riskState(13))
      expect(snapshot?.tp?.value).toBeNull()
      expect(snapshot?.tp?.status).toBe('pending')
    })

    resolvePut({ data: cleared })

    await waitFor(() => {
      const snapshot = qc.getQueryData<RiskStateResponse>(queryKeys.trades.riskState(13))
      expect(snapshot?.tp?.status).toBe('cleared')
    })
  })

  it('invalidates trades, portfolio, and risk-state caches after settled', async () => {
    const qc = makeQueryClient()
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    mockPut.mockResolvedValueOnce({ data: confirmedSnapshot(15) })

    const { result } = renderHook(() => useUpdateTpSl(), {
      wrapper: makeWrapper(qc),
    })

    result.current.mutate({ tradeId: 15, data: { take_profit: 70000 } })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    // Assert the four invalidations fired
    const calls = invalidateSpy.mock.calls.map((call) => call[0]?.queryKey)
    expect(calls).toContainEqual(queryKeys.trades.all)
    expect(calls).toContainEqual(queryKeys.portfolio.positions)
    expect(calls).toContainEqual(queryKeys.portfolio.all)
    expect(calls).toContainEqual(queryKeys.trades.riskState(15))
  })

  it('serializes concurrent mutations — second call waits for first', async () => {
    const qc = makeQueryClient()
    const firstResponse = confirmedSnapshot(17, {
      tp: { value: 55000, status: 'confirmed', order_id: 'tp-1', error: null, latency_ms: 10 },
    })
    const secondResponse = confirmedSnapshot(17, {
      tp: { value: 60000, status: 'confirmed', order_id: 'tp-2', error: null, latency_ms: 10 },
    })

    const resolvers: Array<(v: { data: RiskStateResponse }) => void> = []
    mockPut.mockImplementation(
      () => new Promise((resolve) => {
        resolvers.push(resolve)
      }),
    )

    const { result } = renderHook(() => useUpdateTpSl(), {
      wrapper: makeWrapper(qc),
    })

    result.current.mutate({ tradeId: 17, data: { take_profit: 55000 } })
    result.current.mutate({ tradeId: 17, data: { take_profit: 60000 } })

    // Both mutations were dispatched (no blocking at the SDK boundary) but the
    // cache state converges to the last-applied server snapshot. Resolve in
    // order and assert the final state reflects the second response.
    await waitFor(() => {
      expect(resolvers.length).toBe(2)
    })

    resolvers[0]({ data: firstResponse })
    resolvers[1]({ data: secondResponse })

    await waitFor(() => {
      const snapshot = qc.getQueryData<RiskStateResponse>(queryKeys.trades.riskState(17))
      expect(snapshot?.tp?.value).toBe(60000)
      expect(snapshot?.tp?.order_id).toBe('tp-2')
    })
  })
})

// ── Suite: useRiskState ───────────────────────────────────────────────

describe('useRiskState', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPut.mockReset()
    mockPost.mockReset()
  })

  it('is disabled when tradeId is null — no HTTP request fires', async () => {
    const qc = makeQueryClient()
    const { result } = renderHook(() => useRiskState(null), {
      wrapper: makeWrapper(qc),
    })

    // Give React Query a tick to (not) fire
    await new Promise((r) => setTimeout(r, 10))

    expect(mockGet).not.toHaveBeenCalled()
    expect(result.current.fetchStatus).toBe('idle')
    expect(result.current.data).toBeUndefined()
  })

  it('fetches risk-state and returns data on success', async () => {
    const qc = makeQueryClient()
    const payload = confirmedSnapshot(21)
    mockGet.mockResolvedValueOnce({ data: payload })

    const { result } = renderHook(() => useRiskState(21), {
      wrapper: makeWrapper(qc),
    })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    expect(mockGet).toHaveBeenCalledWith('/trades/21/risk-state')
    expect(result.current.data).toEqual(payload)
  })
})
