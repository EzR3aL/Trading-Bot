import { create } from 'zustand'
import api from '../api/client'
import type { BotStatus } from '../types'

interface BotState {
  status: BotStatus | null
  isLoading: boolean
  fetchStatus: () => Promise<void>
  startBot: (exchangeType: string, presetId?: number, demoMode?: boolean) => Promise<void>
  stopBot: () => Promise<void>
}

export const useBotStore = create<BotState>((set) => ({
  status: null,
  isLoading: false,

  fetchStatus: async () => {
    try {
      const res = await api.get('/bot/status')
      set({ status: res.data })
    } catch {
      set({ status: null })
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
      set({ status: res.data, isLoading: false })
    } catch {
      set({ isLoading: false })
      throw new Error('Failed to start bot')
    }
  },

  stopBot: async () => {
    set({ isLoading: true })
    try {
      await api.post('/bot/stop')
      const res = await api.get('/bot/status')
      set({ status: res.data, isLoading: false })
    } catch {
      set({ isLoading: false })
      throw new Error('Failed to stop bot')
    }
  },
}))
