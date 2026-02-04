import { create } from 'zustand'
import api from '../api/client'
import type { BotStatus } from '../types'

interface BotState {
  statuses: BotStatus[]
  isLoading: boolean
  fetchStatus: () => Promise<void>
  startBot: (exchangeType: string, presetId?: number, demoMode?: boolean) => Promise<void>
  stopBot: (exchangeType: string) => Promise<void>
  stopAll: () => Promise<void>
}

export const useBotStore = create<BotState>((set) => ({
  statuses: [],
  isLoading: false,

  fetchStatus: async () => {
    try {
      const res = await api.get('/bot/status')
      set({ statuses: res.data.bots || [] })
    } catch {
      set({ statuses: [] })
    }
  },

  startBot: async (exchangeType: string, presetId?: number, demoMode = true) => {
    set({ isLoading: true })
    try {
      await api.post('/bot/start', {
        exchange_type: exchangeType,
        preset_id: presetId,
        demo_mode: demoMode,
      })
      const res = await api.get('/bot/status')
      set({ statuses: res.data.bots || [], isLoading: false })
    } catch {
      set({ isLoading: false })
      throw new Error('Failed to start bot')
    }
  },

  stopBot: async (exchangeType: string) => {
    set({ isLoading: true })
    try {
      await api.post('/bot/stop', { exchange_type: exchangeType })
      const res = await api.get('/bot/status')
      set({ statuses: res.data.bots || [], isLoading: false })
    } catch {
      set({ isLoading: false })
      throw new Error('Failed to stop bot')
    }
  },

  stopAll: async () => {
    set({ isLoading: true })
    try {
      await api.post('/bot/stop-all')
      const res = await api.get('/bot/status')
      set({ statuses: res.data.bots || [], isLoading: false })
    } catch {
      set({ isLoading: false })
      throw new Error('Failed to stop bots')
    }
  },
}))
