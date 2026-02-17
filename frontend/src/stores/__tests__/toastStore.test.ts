import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { useToastStore } from '../toastStore'

describe('toastStore', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useToastStore.setState({ toasts: [] })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('should start with empty toasts array', () => {
    expect(useToastStore.getState().toasts).toEqual([])
  })

  describe('addToast', () => {
    it('should add a success toast', () => {
      useToastStore.getState().addToast('success', 'Operation completed')

      const toasts = useToastStore.getState().toasts
      expect(toasts).toHaveLength(1)
      expect(toasts[0].type).toBe('success')
      expect(toasts[0].message).toBe('Operation completed')
      expect(toasts[0].duration).toBe(5000)
    })

    it('should add an error toast', () => {
      useToastStore.getState().addToast('error', 'Something failed')

      const toasts = useToastStore.getState().toasts
      expect(toasts).toHaveLength(1)
      expect(toasts[0].type).toBe('error')
      expect(toasts[0].message).toBe('Something failed')
    })

    it('should add a warning toast', () => {
      useToastStore.getState().addToast('warning', 'Be careful')

      const toasts = useToastStore.getState().toasts
      expect(toasts).toHaveLength(1)
      expect(toasts[0].type).toBe('warning')
    })

    it('should add an info toast', () => {
      useToastStore.getState().addToast('info', 'FYI')

      const toasts = useToastStore.getState().toasts
      expect(toasts).toHaveLength(1)
      expect(toasts[0].type).toBe('info')
    })

    it('should support custom duration', () => {
      useToastStore.getState().addToast('success', 'Quick toast', 2000)

      const toasts = useToastStore.getState().toasts
      expect(toasts[0].duration).toBe(2000)
    })

    it('should generate unique IDs for each toast', () => {
      useToastStore.getState().addToast('success', 'Toast 1')
      useToastStore.getState().addToast('error', 'Toast 2')
      useToastStore.getState().addToast('info', 'Toast 3')

      const toasts = useToastStore.getState().toasts
      const ids = toasts.map((t) => t.id)
      const uniqueIds = new Set(ids)
      expect(uniqueIds.size).toBe(3)
    })

    it('should accumulate multiple toasts', () => {
      useToastStore.getState().addToast('success', 'First')
      useToastStore.getState().addToast('error', 'Second')
      useToastStore.getState().addToast('warning', 'Third')

      expect(useToastStore.getState().toasts).toHaveLength(3)
    })

    it('should auto-remove toast after duration', () => {
      useToastStore.getState().addToast('success', 'Temporary', 3000)
      expect(useToastStore.getState().toasts).toHaveLength(1)

      vi.advanceTimersByTime(3000)
      expect(useToastStore.getState().toasts).toHaveLength(0)
    })

    it('should not auto-remove toast with zero duration', () => {
      useToastStore.getState().addToast('error', 'Persistent', 0)
      expect(useToastStore.getState().toasts).toHaveLength(1)

      vi.advanceTimersByTime(10000)
      expect(useToastStore.getState().toasts).toHaveLength(1)
    })
  })

  describe('removeToast', () => {
    it('should remove a specific toast by id', () => {
      useToastStore.getState().addToast('success', 'Keep me')
      useToastStore.getState().addToast('error', 'Remove me')

      const toasts = useToastStore.getState().toasts
      const toRemove = toasts.find((t) => t.message === 'Remove me')!

      useToastStore.getState().removeToast(toRemove.id)

      const remaining = useToastStore.getState().toasts
      expect(remaining).toHaveLength(1)
      expect(remaining[0].message).toBe('Keep me')
    })

    it('should handle removing non-existent toast gracefully', () => {
      useToastStore.getState().addToast('success', 'Still here')
      useToastStore.getState().removeToast('non-existent-id')

      expect(useToastStore.getState().toasts).toHaveLength(1)
    })
  })
})
