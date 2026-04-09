import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useWebSocket } from '../useWebSocket'

// Mock authStore
const mockAuthStore = { user: null as { id: number; username: string } | null }
vi.mock('../../stores/authStore', () => ({
  useAuthStore: () => mockAuthStore,
}))

// ─── WebSocket mock ────────────────────────────────────────────

type WSListener = ((ev?: any) => void) | null

class MockWebSocket {
  static OPEN = 1
  static CLOSED = 3
  static instances: MockWebSocket[] = []

  url: string
  readyState = MockWebSocket.OPEN
  onopen: WSListener = null
  onclose: WSListener = null
  onmessage: WSListener = null
  onerror: WSListener = null
  send = vi.fn()
  close = vi.fn()

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  /** Helper to simulate server opening the connection */
  simulateOpen() {
    if (this.onopen) this.onopen({})
  }

  /** Helper to simulate server sending a message */
  simulateMessage(data: string) {
    if (this.onmessage) this.onmessage({ data })
  }

  /** Helper to simulate connection close */
  simulateClose() {
    if (this.onclose) this.onclose({})
  }

  simulateError() {
    if (this.onerror) this.onerror({})
  }
}

// Install the mock globally
Object.defineProperty(globalThis, 'WebSocket', {
  value: MockWebSocket,
  writable: true,
  configurable: true,
})

describe('useWebSocket', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    MockWebSocket.instances = []
    mockAuthStore.user = null
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  const latestWs = (): MockWebSocket =>
    MockWebSocket.instances[MockWebSocket.instances.length - 1]

  // ─── Connection lifecycle ──────────────────────────────────

  it('should not connect when user is null', () => {
    renderHook(() => useWebSocket({}))
    expect(MockWebSocket.instances).toHaveLength(0)
  })

  it('should connect when user is logged in', () => {
    mockAuthStore.user = { id: 1, username: 'tester' }
    renderHook(() => useWebSocket({}))
    expect(MockWebSocket.instances).toHaveLength(1)
  })

  it('should set status to connecting then connected on open', () => {
    mockAuthStore.user = { id: 1, username: 'tester' }
    const { result } = renderHook(() => useWebSocket({}))

    // Before open fires the status should be 'connecting'
    expect(result.current.status).toBe('connecting')

    act(() => latestWs().simulateOpen())
    expect(result.current.status).toBe('connected')
  })

  it('should disconnect on cleanup (unmount)', () => {
    mockAuthStore.user = { id: 1, username: 'tester' }
    const { unmount } = renderHook(() => useWebSocket({}))

    const ws = latestWs()
    act(() => ws.simulateOpen())

    unmount()
    expect(ws.close).toHaveBeenCalled()
  })

  // ─── Cookie-auth marker ────────────────────────────────────

  it('should send cookie-auth on open', () => {
    mockAuthStore.user = { id: 1, username: 'tester' }
    renderHook(() => useWebSocket({}))

    act(() => latestWs().simulateOpen())
    expect(latestWs().send).toHaveBeenCalledWith('cookie-auth')
  })

  // ─── Ping interval ────────────────────────────────────────

  it('should start pinging after connection opens', () => {
    mockAuthStore.user = { id: 1, username: 'tester' }
    renderHook(() => useWebSocket({}))

    const ws = latestWs()
    act(() => ws.simulateOpen())

    // Advance past the initial cookie-auth send
    ws.send.mockClear()

    // Advance 30s (PING_INTERVAL_MS)
    act(() => { vi.advanceTimersByTime(30_000) })
    expect(ws.send).toHaveBeenCalledWith('ping')
  })

  it('should clear ping interval on unmount', () => {
    mockAuthStore.user = { id: 1, username: 'tester' }
    const { unmount } = renderHook(() => useWebSocket({}))

    act(() => latestWs().simulateOpen())
    const ws = latestWs()
    ws.send.mockClear()

    unmount()

    // Advance timers — no pings should fire
    act(() => { vi.advanceTimersByTime(60_000) })
    expect(ws.send).not.toHaveBeenCalled()
  })

  // ─── Reconnection with exponential backoff ─────────────────

  it('should reconnect with exponential backoff after close', () => {
    mockAuthStore.user = { id: 1, username: 'tester' }
    const { result } = renderHook(() => useWebSocket({}))

    // Open then close
    act(() => latestWs().simulateOpen())
    act(() => latestWs().simulateClose())

    expect(result.current.status).toBe('disconnected')
    const countBefore = MockWebSocket.instances.length

    // After 1s (initial delay) a new WebSocket should be created
    act(() => { vi.advanceTimersByTime(1000) })
    expect(MockWebSocket.instances.length).toBe(countBefore + 1)

    // Close again — next delay should be 2s
    act(() => latestWs().simulateClose())
    const countBefore2 = MockWebSocket.instances.length
    act(() => { vi.advanceTimersByTime(1000) })
    expect(MockWebSocket.instances.length).toBe(countBefore2) // Not yet
    act(() => { vi.advanceTimersByTime(1000) })
    expect(MockWebSocket.instances.length).toBe(countBefore2 + 1)
  })

  // ─── Max reconnect attempts ────────────────────────────────

  it('should set status to failed after 10 attempts', () => {
    mockAuthStore.user = { id: 1, username: 'tester' }
    const { result } = renderHook(() => useWebSocket({}))

    act(() => latestWs().simulateOpen())

    // Simulate 10 close events with timer advances
    for (let i = 0; i < 10; i++) {
      act(() => latestWs().simulateClose())
      // Advance enough to trigger reconnect (max 30s)
      act(() => { vi.advanceTimersByTime(60_000) })
    }

    expect(result.current.status).toBe('failed')
  })

  // ─── Message handling ──────────────────────────────────────

  it('should dispatch messages to correct handler', () => {
    const botHandler = vi.fn()
    const tradeHandler = vi.fn()
    mockAuthStore.user = { id: 1, username: 'tester' }

    renderHook(() => useWebSocket({ bot_status: botHandler, trade: tradeHandler }))

    act(() => latestWs().simulateOpen())
    act(() => latestWs().simulateMessage(JSON.stringify({ type: 'bot_status', data: { id: 1 } })))
    act(() => latestWs().simulateMessage(JSON.stringify({ type: 'trade', data: { id: 2 } })))

    expect(botHandler).toHaveBeenCalledWith({ id: 1 })
    expect(tradeHandler).toHaveBeenCalledWith({ id: 2 })
  })

  it('should ignore pong and authenticated messages', () => {
    const handler = vi.fn()
    mockAuthStore.user = { id: 1, username: 'tester' }

    renderHook(() => useWebSocket({ pong: handler }))
    act(() => latestWs().simulateOpen())
    act(() => latestWs().simulateMessage('pong'))
    act(() => latestWs().simulateMessage('authenticated'))

    expect(handler).not.toHaveBeenCalled()
  })

  it('should ignore non-JSON messages', () => {
    const handler = vi.fn()
    mockAuthStore.user = { id: 1, username: 'tester' }

    renderHook(() => useWebSocket({ something: handler }))
    act(() => latestWs().simulateOpen())
    act(() => latestWs().simulateMessage('not valid json'))

    expect(handler).not.toHaveBeenCalled()
  })

  // ─── Tab visibility reconnect ──────────────────────────────

  it('should reconnect when tab becomes visible and socket is not open', () => {
    mockAuthStore.user = { id: 1, username: 'tester' }
    renderHook(() => useWebSocket({}))

    const ws = latestWs()
    act(() => ws.simulateOpen())

    // Simulate socket dying without triggering onclose
    ws.readyState = MockWebSocket.CLOSED as any

    const countBefore = MockWebSocket.instances.length

    // Simulate visibility change
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
    act(() => { document.dispatchEvent(new Event('visibilitychange')) })

    expect(MockWebSocket.instances.length).toBe(countBefore + 1)
  })

  it('should not reconnect on visibility change when already connected', () => {
    mockAuthStore.user = { id: 1, username: 'tester' }
    renderHook(() => useWebSocket({}))

    const ws = latestWs()
    act(() => ws.simulateOpen())

    // readyState is OPEN by default
    const countBefore = MockWebSocket.instances.length

    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
    act(() => { document.dispatchEvent(new Event('visibilitychange')) })

    expect(MockWebSocket.instances.length).toBe(countBefore)
  })
})
