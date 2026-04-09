import { describe, it, expect, beforeEach } from 'vitest'
import { useRealtimeStore } from '../realtimeStore'

describe('realtimeStore', () => {
  beforeEach(() => {
    useRealtimeStore.setState({
      lastEvent: null,
      botStatuses: {},
    })
  })

  // ─── pushEvent ──────────────────────────────────────────────

  it('should have correct initial state', () => {
    const state = useRealtimeStore.getState()
    expect(state.lastEvent).toBeNull()
    expect(state.botStatuses).toEqual({})
  })

  it('should push an event and update lastEvent', () => {
    const before = Date.now()
    useRealtimeStore.getState().pushEvent('trade', { symbol: 'BTCUSDT' })

    const { lastEvent } = useRealtimeStore.getState()
    expect(lastEvent).not.toBeNull()
    expect(lastEvent!.type).toBe('trade')
    expect(lastEvent!.data).toEqual({ symbol: 'BTCUSDT' })
    expect(lastEvent!.timestamp).toBeGreaterThanOrEqual(before)
  })

  it('should overwrite lastEvent on subsequent pushEvent', () => {
    useRealtimeStore.getState().pushEvent('trade', { id: 1 })
    useRealtimeStore.getState().pushEvent('bot_status', { id: 2 })

    const { lastEvent } = useRealtimeStore.getState()
    expect(lastEvent!.type).toBe('bot_status')
    expect(lastEvent!.data).toEqual({ id: 2 })
  })

  // ─── updateBotStatus ───────────────────────────────────────

  it('should update a single bot status', () => {
    useRealtimeStore.getState().updateBotStatus(1, { status: 'running' })

    const { botStatuses } = useRealtimeStore.getState()
    expect(botStatuses[1]).toEqual({ status: 'running' })
  })

  it('should update multiple bot statuses independently', () => {
    useRealtimeStore.getState().updateBotStatus(1, { status: 'running' })
    useRealtimeStore.getState().updateBotStatus(2, { status: 'stopped' })

    const { botStatuses } = useRealtimeStore.getState()
    expect(botStatuses[1]).toEqual({ status: 'running' })
    expect(botStatuses[2]).toEqual({ status: 'stopped' })
  })

  it('should overwrite existing bot status on update', () => {
    useRealtimeStore.getState().updateBotStatus(1, { status: 'running', trades: 5 })
    useRealtimeStore.getState().updateBotStatus(1, { status: 'stopped', trades: 10 })

    const { botStatuses } = useRealtimeStore.getState()
    expect(botStatuses[1]).toEqual({ status: 'stopped', trades: 10 })
  })

  // ─── removeBotStatus ───────────────────────────────────────

  it('should remove a bot status entry', () => {
    useRealtimeStore.getState().updateBotStatus(1, { status: 'running' })
    useRealtimeStore.getState().updateBotStatus(2, { status: 'stopped' })
    useRealtimeStore.getState().removeBotStatus(1)

    const { botStatuses } = useRealtimeStore.getState()
    expect(botStatuses[1]).toBeUndefined()
    expect(botStatuses[2]).toEqual({ status: 'stopped' })
  })

  it('should handle removing a non-existent bot status gracefully', () => {
    useRealtimeStore.getState().updateBotStatus(1, { status: 'running' })
    useRealtimeStore.getState().removeBotStatus(999)

    const { botStatuses } = useRealtimeStore.getState()
    expect(botStatuses[1]).toEqual({ status: 'running' })
  })
})
