import { describe, it, expect, beforeEach } from 'vitest'
import { useFilterStore, type DemoFilter } from '../filterStore'

describe('filterStore', () => {
  beforeEach(() => {
    localStorage.clear()
    useFilterStore.setState({ demoFilter: 'all' })
  })

  it('should have default demoFilter of "all"', () => {
    const state = useFilterStore.getState()
    expect(state.demoFilter).toBe('all')
  })

  describe('setDemoFilter', () => {
    it('should set filter to "demo"', () => {
      useFilterStore.getState().setDemoFilter('demo')
      expect(useFilterStore.getState().demoFilter).toBe('demo')
      expect(localStorage.getItem('demo_filter')).toBe('demo')
    })

    it('should set filter to "live"', () => {
      useFilterStore.getState().setDemoFilter('live')
      expect(useFilterStore.getState().demoFilter).toBe('live')
      expect(localStorage.getItem('demo_filter')).toBe('live')
    })

    it('should set filter to "all"', () => {
      useFilterStore.getState().setDemoFilter('demo')
      useFilterStore.getState().setDemoFilter('all')
      expect(useFilterStore.getState().demoFilter).toBe('all')
      expect(localStorage.getItem('demo_filter')).toBe('all')
    })

    it('should persist filter changes to localStorage', () => {
      const filters: DemoFilter[] = ['demo', 'live', 'all']
      filters.forEach((filter) => {
        useFilterStore.getState().setDemoFilter(filter)
        expect(localStorage.getItem('demo_filter')).toBe(filter)
      })
    })
  })
})
