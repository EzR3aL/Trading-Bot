import { create } from 'zustand'

export interface RealtimeEvent {
  type: string
  data: unknown
  timestamp: number
}

interface RealtimeStore {
  /** Most recent event received via WebSocket. */
  lastEvent: RealtimeEvent | null
  /** Live bot status map: bot_config_id -> status payload. */
  botStatuses: Record<number, unknown>
  /** Push a new real-time event. */
  pushEvent: (type: string, data: unknown) => void
  /** Update the cached status of a single bot. */
  updateBotStatus: (botId: number, status: unknown) => void
}

export const useRealtimeStore = create<RealtimeStore>((set) => ({
  lastEvent: null,
  botStatuses: {},

  pushEvent: (type, data) =>
    set({ lastEvent: { type, data, timestamp: Date.now() } }),

  updateBotStatus: (botId, status) =>
    set((state) => ({
      botStatuses: { ...state.botStatuses, [botId]: status },
    })),
}))
