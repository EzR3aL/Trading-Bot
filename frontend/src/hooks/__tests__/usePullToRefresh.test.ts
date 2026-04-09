import { renderHook } from '@testing-library/react'
import usePullToRefresh from '../usePullToRefresh'

describe('usePullToRefresh', () => {
  it('returns initial pull state values', () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      usePullToRefresh({ onRefresh }),
    )

    expect(result.current.pulling).toBe(false)
    expect(result.current.refreshing).toBe(false)
    expect(result.current.pullDistance).toBe(0)
    expect(result.current.containerRef).toBeDefined()
  })

  it('returns a ref object for the container', () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      usePullToRefresh({ onRefresh }),
    )

    expect(result.current.containerRef.current).toBeNull()
  })

  it('does not call onRefresh on mount', () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined)
    renderHook(() => usePullToRefresh({ onRefresh }))

    expect(onRefresh).not.toHaveBeenCalled()
  })

  it('accepts disabled option without errors', () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      usePullToRefresh({ onRefresh, disabled: true }),
    )

    expect(result.current.pulling).toBe(false)
    expect(result.current.refreshing).toBe(false)
  })

  it('accepts custom threshold without errors', () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      usePullToRefresh({ onRefresh, threshold: 120 }),
    )

    expect(result.current.pullDistance).toBe(0)
  })
})
