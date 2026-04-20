import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '../api/queries'
import { useAuthStore } from '../stores/authStore'

/**
 * Connection state reported by {@link useTradesSSE}.
 *
 * * `sse`          — EventSource is open, events are flowing.
 * * `polling`      — SSE unavailable (error or closed), we fall back to
 *                    refetching the trades list every 5 seconds.
 * * `disconnected` — User is logged out or the hook is unmounted.
 */
export type TradesStreamState = 'sse' | 'polling' | 'disconnected'

/** 5-second polling cadence — matches the cadence that SSE replaced. */
const POLLING_INTERVAL_MS = 5000

/** Number of EventSource retries before giving up and switching to polling. */
const MAX_SSE_RECONNECT_ATTEMPTS = 3

/**
 * Shape of a frame delivered by the `/api/trades/stream` backend endpoint.
 * Kept minimal on purpose — the hook only uses it to decide what to
 * invalidate in the React Query cache.
 */
interface TradeStreamEvent {
  event: 'trade_opened' | 'trade_updated' | 'trade_closed'
  trade_id: number | null
  timestamp: string
  data: Record<string, unknown>
}

interface UseTradesSSEOptions {
  /**
   * Disable the hook entirely (e.g. when the parent page is not displaying
   * trades). Defaults to `true` so Dashboard / Portfolio can just call
   * `useTradesSSE()` without arguments.
   */
  enabled?: boolean
}

/**
 * Subscribe to the backend Server-Sent Events feed for real-time trade
 * updates (Issue #216 §2.2).
 *
 * On each incoming event the hook invalidates the React Query `['trades']`
 * cache so any mounted `useTrades` / `usePortfolioPositions` caller
 * re-fetches. When `EventSource` fails or the browser closes the stream,
 * the hook falls back to 5-second polling until the page refreshes.
 *
 * ## Auth
 * The backend accepts the JWT via the `access_token` httpOnly cookie
 * (preferred) or a `?token=` query parameter. Because `EventSource`
 * cannot set custom headers, we rely on same-origin cookies here; the
 * query-param path remains as a server-side safety net.
 */
export function useTradesSSE(options: UseTradesSSEOptions = {}): {
  connectionState: TradesStreamState
} {
  const { enabled = true } = options
  const queryClient = useQueryClient()
  const { user } = useAuthStore()

  const [connectionState, setConnectionState] =
    useState<TradesStreamState>('disconnected')

  // Keep refs for cleanup timers / handles so the effect dependency list
  // stays small (only `enabled` + `user`).
  const eventSourceRef = useRef<EventSource | null>(null)
  const pollingTimerRef = useRef<number | null>(null)
  const sseAttemptsRef = useRef(0)
  const reconnectTimerRef = useRef<number | null>(null)

  useEffect(() => {
    if (!enabled || !user) {
      setConnectionState('disconnected')
      return
    }

    const invalidateTrades = () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.trades.all })
      queryClient.invalidateQueries({ queryKey: queryKeys.portfolio.positions })
    }

    const stopPolling = () => {
      if (pollingTimerRef.current !== null) {
        window.clearInterval(pollingTimerRef.current)
        pollingTimerRef.current = null
      }
    }

    const startPolling = () => {
      stopPolling()
      setConnectionState('polling')
      // Fire immediately so the UI refreshes without waiting a full 5s.
      invalidateTrades()
      pollingTimerRef.current = window.setInterval(
        invalidateTrades,
        POLLING_INTERVAL_MS,
      )
    }

    const openEventSource = () => {
      // Same-origin request — cookies are sent automatically. `withCredentials`
      // makes sure they still flow if the app is served from a different port
      // (e.g. during Vite dev).
      const es = new EventSource('/api/trades/stream', { withCredentials: true })
      eventSourceRef.current = es

      es.onopen = () => {
        sseAttemptsRef.current = 0
        setConnectionState('sse')
        // If we were polling during a reconnect window, stop now that the
        // SSE connection is healthy again.
        stopPolling()
      }

      es.onmessage = (ev) => {
        try {
          const payload = JSON.parse(ev.data) as TradeStreamEvent
          if (
            payload.event === 'trade_opened'
            || payload.event === 'trade_updated'
            || payload.event === 'trade_closed'
          ) {
            invalidateTrades()
          }
        } catch {
          // Malformed frame — ignore. The next valid frame still refreshes.
        }
      }

      es.onerror = () => {
        // Browsers reuse `onerror` for both transient network blips and hard
        // server closures. Count the attempts; after the budget we stop
        // reconnecting and hand over to polling so the user still gets
        // updates.
        es.close()
        eventSourceRef.current = null

        sseAttemptsRef.current += 1
        if (sseAttemptsRef.current >= MAX_SSE_RECONNECT_ATTEMPTS) {
          startPolling()
          return
        }

        // Briefly drop into polling so the UI is never longer than 5s stale
        // while we wait to retry the SSE connection.
        startPolling()
        reconnectTimerRef.current = window.setTimeout(
          openEventSource,
          POLLING_INTERVAL_MS,
        )
      }
    }

    if (typeof window === 'undefined' || typeof EventSource === 'undefined') {
      // EventSource unavailable (SSR / very old browser) — polling only.
      startPolling()
    } else {
      openEventSource()
    }

    return () => {
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      stopPolling()
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
      setConnectionState('disconnected')
    }
  }, [enabled, user, queryClient])

  return { connectionState }
}
