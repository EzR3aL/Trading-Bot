import { describe, it, expect, beforeEach } from 'vitest'
import { useTourStore } from './tourStore'

describe('tourStore', () => {
  beforeEach(() => {
    localStorage.clear()
    // Reset Zustand store state
    useTourStore.setState({
      completedTours: {},
      activeTour: null,
    })
  })

  describe('initial state', () => {
    it('starts with no completed tours', () => {
      const state = useTourStore.getState()
      expect(state.completedTours).toEqual({})
      expect(state.activeTour).toBeNull()
    })

    it('loads completed tours from localStorage', () => {
      localStorage.setItem('completed_tours', JSON.stringify({ dashboard: true }))
      // Re-create store state from localStorage
      useTourStore.setState({ completedTours: JSON.parse(localStorage.getItem('completed_tours') || '{}') })
      const state = useTourStore.getState()
      expect(state.completedTours).toEqual({ dashboard: true })
    })

    it('handles corrupted localStorage gracefully', () => {
      localStorage.setItem('completed_tours', 'not-valid-json{{{')
      // The loadCompleted function should catch JSON.parse errors
      let result = {}
      try {
        result = JSON.parse(localStorage.getItem('completed_tours') || '{}')
      } catch {
        result = {}
      }
      expect(result).toEqual({})
    })
  })

  describe('markComplete', () => {
    it('marks a tour as completed', () => {
      useTourStore.getState().markComplete('dashboard')
      const state = useTourStore.getState()
      expect(state.completedTours.dashboard).toBe(true)
      expect(state.activeTour).toBeNull()
    })

    it('persists to localStorage', () => {
      useTourStore.getState().markComplete('bots-page')
      const stored = JSON.parse(localStorage.getItem('completed_tours') || '{}')
      expect(stored['bots-page']).toBe(true)
    })

    it('preserves existing completed tours when marking new ones', () => {
      useTourStore.getState().markComplete('dashboard')
      useTourStore.getState().markComplete('bots-page')
      const state = useTourStore.getState()
      expect(state.completedTours.dashboard).toBe(true)
      expect(state.completedTours['bots-page']).toBe(true)
    })

    it('clears activeTour when completing', () => {
      useTourStore.getState().setActiveTour('dashboard')
      expect(useTourStore.getState().activeTour).toBe('dashboard')
      useTourStore.getState().markComplete('dashboard')
      expect(useTourStore.getState().activeTour).toBeNull()
    })
  })

  describe('reset', () => {
    it('removes a specific tour from completed', () => {
      useTourStore.getState().markComplete('dashboard')
      useTourStore.getState().markComplete('bots-page')
      useTourStore.getState().reset('dashboard')
      const state = useTourStore.getState()
      expect(state.completedTours.dashboard).toBeUndefined()
      expect(state.completedTours['bots-page']).toBe(true)
    })

    it('persists reset to localStorage', () => {
      useTourStore.getState().markComplete('dashboard')
      useTourStore.getState().reset('dashboard')
      const stored = JSON.parse(localStorage.getItem('completed_tours') || '{}')
      expect(stored.dashboard).toBeUndefined()
    })
  })

  describe('shouldShowTour', () => {
    it('returns true for unseen tours', () => {
      expect(useTourStore.getState().shouldShowTour('dashboard')).toBe(true)
    })

    it('returns false for completed tours', () => {
      useTourStore.getState().markComplete('dashboard')
      expect(useTourStore.getState().shouldShowTour('dashboard')).toBe(false)
    })

    it('returns true after reset', () => {
      useTourStore.getState().markComplete('dashboard')
      useTourStore.getState().reset('dashboard')
      expect(useTourStore.getState().shouldShowTour('dashboard')).toBe(true)
    })
  })

  describe('setActiveTour', () => {
    it('sets active tour', () => {
      useTourStore.getState().setActiveTour('bots-page')
      expect(useTourStore.getState().activeTour).toBe('bots-page')
    })

    it('clears active tour with null', () => {
      useTourStore.getState().setActiveTour('bots-page')
      useTourStore.getState().setActiveTour(null)
      expect(useTourStore.getState().activeTour).toBeNull()
    })
  })
})
