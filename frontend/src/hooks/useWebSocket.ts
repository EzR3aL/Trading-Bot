import { useEffect, useRef, useCallback, useMemo, useState } from 'react'
import { useAuthStore } from '../stores/authStore'

type EventHandler = (data: unknown) => void

const INITIAL_RECONNECT_DELAY_MS = 1000
const MAX_RECONNECT_DELAY_MS = 30000
const MAX_RECONNECT_ATTEMPTS = 10
const PING_INTERVAL_MS = 30000

export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'failed'

/**
 * Custom hook that maintains a WebSocket connection to the backend.
 *
 * Features:
 * - Connects automatically when the user is logged in
 * - Exponential backoff reconnection (1s, 2s, 4s, ... up to 30s)
 * - Stops reconnecting after 10 failed attempts
 * - Reconnects immediately when the tab becomes visible
 * - Periodic keep-alive pings
 */
export function useWebSocket(handlers: Record<string, EventHandler>) {
  const ws = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<number>()
  const pingInterval = useRef<number>()
  const reconnectDelay = useRef(INITIAL_RECONNECT_DELAY_MS)
  const attemptCount = useRef(0)
  const isIntentionallyClosed = useRef(false)
  const { user } = useAuthStore()

  const [status, setStatus] = useState<WebSocketStatus>('disconnected')

  // Stabilise the handler map so the effect doesn't re-run on every render
  const handlerKeys = Object.keys(handlers).sort().join(',')
  const stableHandlers = useMemo(() => handlers, [handlerKeys]) // eslint-disable-line react-hooks/exhaustive-deps

  const connect = useCallback(() => {
    const token = localStorage.getItem('access_token')
    if (!token) return

    // Don't reconnect if we've exceeded the attempt limit
    if (attemptCount.current >= MAX_RECONNECT_ATTEMPTS) {
      setStatus('failed')
      return
    }

    // Close any existing connection first
    if (ws.current) {
      ws.current.onclose = null
      ws.current.close()
      ws.current = null
    }

    setStatus('connecting')

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/ws`
    const socket = new WebSocket(wsUrl)

    socket.onopen = () => {
      // Send JWT as first message (instead of URL query param)
      socket.send(token)

      // Reset backoff on successful connection
      reconnectDelay.current = INITIAL_RECONNECT_DELAY_MS
      attemptCount.current = 0
      setStatus('connected')

      // Start keep-alive pings
      pingInterval.current = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send('ping')
        }
      }, PING_INTERVAL_MS)
    }

    socket.onmessage = (event) => {
      if (event.data === 'pong' || event.data === 'authenticated') return
      try {
        const msg = JSON.parse(event.data) as { type: string; data: unknown }
        const handler = stableHandlers[msg.type]
        if (handler) handler(msg.data)
      } catch {
        // Ignore non-JSON messages
      }
    }

    socket.onclose = () => {
      clearInterval(pingInterval.current)

      // Don't reconnect if this was an intentional close (cleanup)
      if (isIntentionallyClosed.current) return

      setStatus('disconnected')
      attemptCount.current++

      if (attemptCount.current >= MAX_RECONNECT_ATTEMPTS) {
        setStatus('failed')
        return
      }

      // Schedule reconnect with exponential backoff
      const delay = reconnectDelay.current
      reconnectDelay.current = Math.min(delay * 2, MAX_RECONNECT_DELAY_MS)
      reconnectTimer.current = window.setTimeout(connect, delay)
    }

    socket.onerror = () => {
      // onclose will fire after onerror, triggering reconnect
    }

    ws.current = socket
  }, [stableHandlers])

  // Main connection effect
  useEffect(() => {
    if (user) {
      isIntentionallyClosed.current = false
      attemptCount.current = 0
      reconnectDelay.current = INITIAL_RECONNECT_DELAY_MS
      connect()
    }
    return () => {
      isIntentionallyClosed.current = true
      clearTimeout(reconnectTimer.current)
      clearInterval(pingInterval.current)
      if (ws.current) {
        ws.current.onclose = null
        ws.current.close()
        ws.current = null
      }
      setStatus('disconnected')
    }
  }, [user, connect])

  // Reconnect when tab becomes visible again
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState !== 'visible') return
      if (!user) return
      if (isIntentionallyClosed.current) return

      // Only reconnect if not already connected
      if (ws.current?.readyState === WebSocket.OPEN) return

      // Clear any pending reconnect timer and try immediately
      clearTimeout(reconnectTimer.current)
      // Reset attempt count on manual visibility trigger to give it a fresh chance
      attemptCount.current = 0
      reconnectDelay.current = INITIAL_RECONNECT_DELAY_MS
      setStatus('disconnected')
      connect()
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [user, connect])

  return { ws, status }
}
