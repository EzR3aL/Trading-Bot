import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useIntervalPaused, useVisibleTab } from '../useIntervalPaused'

/**
 * Helper: override document.visibilityState. `visibilityState` is a read-only
 * getter, so we redefine it via Object.defineProperty for each test.
 */
function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => state,
  })
}

function fireVisibilityChange() {
  document.dispatchEvent(new Event('visibilitychange'))
}

describe('useIntervalPaused', () => {
  beforeEach(() => {
    setVisibility('visible')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns baseMs when the tab is visible', () => {
    setVisibility('visible')
    const { result } = renderHook(() => useIntervalPaused(5000))
    expect(result.current).toBe(5000)
  })

  it('returns false when the tab is hidden', () => {
    setVisibility('hidden')
    const { result } = renderHook(() => useIntervalPaused(5000))
    expect(result.current).toBe(false)
  })

  it('responds to visibilitychange events', () => {
    setVisibility('visible')
    const { result } = renderHook(() => useIntervalPaused(2500))
    expect(result.current).toBe(2500)

    // Tab is backgrounded
    act(() => {
      setVisibility('hidden')
      fireVisibilityChange()
    })
    expect(result.current).toBe(false)

    // Tab is foregrounded again
    act(() => {
      setVisibility('visible')
      fireVisibilityChange()
    })
    expect(result.current).toBe(2500)
  })

  it('removes its visibilitychange listener on unmount', () => {
    const removeSpy = vi.spyOn(document, 'removeEventListener')
    const { unmount } = renderHook(() => useIntervalPaused(1000))
    unmount()
    const calls = removeSpy.mock.calls.filter(([evt]) => evt === 'visibilitychange')
    expect(calls.length).toBeGreaterThan(0)
  })
})

describe('useVisibleTab', () => {
  beforeEach(() => {
    setVisibility('visible')
  })

  it('returns true when the tab is visible', () => {
    setVisibility('visible')
    const { result } = renderHook(() => useVisibleTab())
    expect(result.current).toBe(true)
  })

  it('returns false when the tab is hidden', () => {
    setVisibility('hidden')
    const { result } = renderHook(() => useVisibleTab())
    expect(result.current).toBe(false)
  })

  it('flips on visibilitychange events', () => {
    setVisibility('visible')
    const { result } = renderHook(() => useVisibleTab())
    expect(result.current).toBe(true)

    act(() => {
      setVisibility('hidden')
      fireVisibilityChange()
    })
    expect(result.current).toBe(false)
  })
})
