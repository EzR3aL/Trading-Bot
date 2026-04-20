import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

// ── Mocks ─────────────────────────────────────────────────────────────

const mockAuthStore = { user: null as { id: number; username: string } | null }
vi.mock('../../stores/authStore', () => ({
  useAuthStore: () => mockAuthStore,
}))

// ── EventSource mock ──────────────────────────────────────────────────
// Shape mirrors the browser API: constructor, onopen/onmessage/onerror
// callbacks, close(). Tests drive events via the `simulate*` helpers.

type ESListener = ((ev?: unknown) => void) | null

class MockEventSource {
  static instances: MockEventSource[] = []

  url: string
  withCredentials: boolean
  onopen: ESListener = null
  onmessage: ESListener = null
  onerror: ESListener = null
  close = vi.fn()

  constructor(url: string, init?: { withCredentials?: boolean }) {
    this.url = url
    this.withCredentials = !!init?.withCredentials
    MockEventSource.instances.push(this)
  }

  simulateOpen() {
    if (this.onopen) this.onopen({})
  }

  simulateMessage(data: string) {
    if (this.onmessage) this.onmessage({ data })
  }

  simulateError() {
    if (this.onerror) this.onerror({})
  }
}

Object.defineProperty(globalThis, 'EventSource', {
  value: MockEventSource,
  writable: true,
  configurable: true,
})

// Import after mocks are wired so the hook picks up our EventSource stub.
import { useTradesSSE } from '../useTradesSSE'

// ── Helpers ──────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, staleTime: 0 },
    },
  })
}

function makeWrapper(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

const latestEs = (): MockEventSource =>
  MockEventSource.instances[MockEventSource.instances.length - 1]


describe('useTradesSSE', () => {
  beforeEach(() => {
    MockEventSource.instances = []
    mockAuthStore.user = { id: 1, username: 'tester' }
  })

  // ─── 1. Fallback to polling ──────────────────────────────────────

  it('falls back to polling when EventSource errors', async () => {
    vi.useFakeTimers()
    try {
      const qc = makeQueryClient()
      const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')

      const { result } = renderHook(() => useTradesSSE(), {
        wrapper: makeWrapper(qc),
      })

      // Let React flush the effect that opens EventSource.
      await act(async () => { await Promise.resolve() })
      expect(MockEventSource.instances.length).toBeGreaterThan(0)

      // Trigger an error — hook switches to polling while it waits to
      // retry the SSE connection.
      await act(async () => {
        latestEs().simulateError()
      })

      expect(result.current.connectionState).toBe('polling')

      // The polling loop invalidates the trades cache immediately + on
      // every 5-second tick. Advance the fake clock and verify.
      invalidateSpy.mockClear()
      await act(async () => {
        vi.advanceTimersByTime(5000)
      })
      expect(invalidateSpy).toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  // ─── 2. Connection-state transitions ─────────────────────────────

  it('transitions disconnected → sse → polling across the lifecycle', async () => {
    mockAuthStore.user = null  // start logged out
    const qc = makeQueryClient()

    const { result, rerender } = renderHook(() => useTradesSSE(), {
      wrapper: makeWrapper(qc),
    })

    // Logged out: no EventSource opened, state stays disconnected.
    expect(MockEventSource.instances).toHaveLength(0)
    expect(result.current.connectionState).toBe('disconnected')

    // Log the user in → hook should open an EventSource.
    mockAuthStore.user = { id: 1, username: 'tester' }
    await act(async () => {
      rerender()
    })
    expect(MockEventSource.instances).toHaveLength(1)

    await act(async () => {
      latestEs().simulateOpen()
    })
    expect(result.current.connectionState).toBe('sse')

    // Server-side close → hook falls back to polling.
    await act(async () => {
      latestEs().simulateError()
    })
    expect(result.current.connectionState).toBe('polling')
  })
})
