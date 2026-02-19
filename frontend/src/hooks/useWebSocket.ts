import { useEffect, useRef, useCallback, useMemo } from 'react'
import { useAuthStore } from '../stores/authStore'

type EventHandler = (data: unknown) => void

const RECONNECT_DELAY_MS = 5000
const PING_INTERVAL_MS = 30000

/**
 * Custom hook that maintains a WebSocket connection to the backend.
 *
 * Automatically connects when the user is logged in, sends periodic
 * pings to keep the connection alive, and reconnects on disconnect.
 */
export function useWebSocket(handlers: Record<string, EventHandler>) {
  const ws = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<number>()
  const pingInterval = useRef<number>()
  const { user } = useAuthStore()

  // Stabilise the handler map so the effect doesn't re-run on every render
  const handlerKeys = Object.keys(handlers).sort().join(',')
  const stableHandlers = useMemo(() => handlers, [handlerKeys]) // eslint-disable-line react-hooks/exhaustive-deps

  const connect = useCallback(() => {
    const token = localStorage.getItem('token')
    if (!token) return

    // Close any existing connection first
    if (ws.current) {
      ws.current.close()
      ws.current = null
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/ws?token=${token}`
    const socket = new WebSocket(wsUrl)

    socket.onopen = () => {
      // Start keep-alive pings
      pingInterval.current = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send('ping')
        }
      }, PING_INTERVAL_MS)
    }

    socket.onmessage = (event) => {
      if (event.data === 'pong') return
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
      // Auto-reconnect after delay
      reconnectTimer.current = window.setTimeout(connect, RECONNECT_DELAY_MS)
    }

    socket.onerror = () => {
      // onclose will fire after onerror, triggering reconnect
    }

    ws.current = socket
  }, [stableHandlers])

  useEffect(() => {
    if (user) {
      connect()
    }
    return () => {
      clearTimeout(reconnectTimer.current)
      clearInterval(pingInterval.current)
      if (ws.current) {
        ws.current.onclose = null // prevent reconnect on intentional close
        ws.current.close()
        ws.current = null
      }
    }
  }, [user, connect])

  return ws
}
