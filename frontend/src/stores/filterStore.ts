import { create } from 'zustand'

export type DemoFilter = 'demo' | 'live' | 'all'

interface FilterState {
  demoFilter: DemoFilter
  setDemoFilter: (filter: DemoFilter) => void
}

const stored = localStorage.getItem('demo_filter') as DemoFilter | null
const initial: DemoFilter = stored === 'demo' || stored === 'live' ? stored : 'all'

export const useFilterStore = create<FilterState>((set) => ({
  demoFilter: initial,
  setDemoFilter: (filter: DemoFilter) => {
    localStorage.setItem('demo_filter', filter)
    set({ demoFilter: filter })
  },
}))
