import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the underlying store BEFORE importing the wrapper so the SUT
// picks up our spy rather than the real Zustand store.
const mockAddToast = vi.fn()
vi.mock('../../stores/toastStore', () => ({
  useToastStore: {
    getState: () => ({ addToast: mockAddToast }),
  },
}))

import { showSuccess, showError, showInfo, showWarning } from '../toast'

describe('toast wrapper', () => {
  beforeEach(() => {
    mockAddToast.mockClear()
  })

  describe('showSuccess', () => {
    it('calls addToast with success type and default duration', () => {
      showSuccess('Saved!')
      expect(mockAddToast).toHaveBeenCalledTimes(1)
      expect(mockAddToast).toHaveBeenCalledWith('success', 'Saved!', 5000)
    })

    it('respects an explicit duration override', () => {
      showSuccess('Saved!', 1000)
      expect(mockAddToast).toHaveBeenCalledWith('success', 'Saved!', 1000)
    })
  })

  describe('showError', () => {
    it('calls addToast with error type and longer default duration', () => {
      showError('Something broke')
      expect(mockAddToast).toHaveBeenCalledWith('error', 'Something broke', 7000)
    })

    it('allows duration=0 for persistent toasts', () => {
      showError('Critical', 0)
      expect(mockAddToast).toHaveBeenCalledWith('error', 'Critical', 0)
    })
  })

  describe('showInfo', () => {
    it('calls addToast with info type and 5s default', () => {
      showInfo('FYI')
      expect(mockAddToast).toHaveBeenCalledWith('info', 'FYI', 5000)
    })
  })

  describe('showWarning', () => {
    it('calls addToast with warning type and 6s default', () => {
      showWarning('Careful')
      expect(mockAddToast).toHaveBeenCalledWith('warning', 'Careful', 6000)
    })
  })

  it('fires each helper independently', () => {
    showSuccess('a')
    showError('b')
    showInfo('c')
    showWarning('d')
    expect(mockAddToast).toHaveBeenCalledTimes(4)
    expect(mockAddToast.mock.calls.map((c) => c[0])).toEqual([
      'success',
      'error',
      'info',
      'warning',
    ])
  })
})
