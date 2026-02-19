import { create } from 'zustand'

interface TourState {
  completedTours: Record<string, boolean>
  activeTour: string | null
  markComplete: (tourId: string) => void
  reset: (tourId: string) => void
  shouldShowTour: (tourId: string) => boolean
  setActiveTour: (tourId: string | null) => void
}

const STORAGE_KEY = 'completed_tours'

function loadCompleted(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function saveCompleted(data: Record<string, boolean>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
}

export const useTourStore = create<TourState>((set, get) => ({
  completedTours: loadCompleted(),
  activeTour: null,

  markComplete: (tourId: string) => {
    const updated = { ...get().completedTours, [tourId]: true }
    saveCompleted(updated)
    set({ completedTours: updated, activeTour: null })
  },

  reset: (tourId: string) => {
    const updated = { ...get().completedTours }
    delete updated[tourId]
    saveCompleted(updated)
    set({ completedTours: updated })
  },

  shouldShowTour: (tourId: string) => {
    return !get().completedTours[tourId]
  },

  setActiveTour: (tourId: string | null) => {
    set({ activeTour: tourId })
  },
}))
