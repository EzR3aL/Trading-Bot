import { renderHook, act } from '@testing-library/react'
import useIsMobile from '../useIsMobile'

describe('useIsMobile', () => {
  let listeners: Map<string, (e: MediaQueryListEvent) => void>
  let currentMatches: boolean

  beforeEach(() => {
    listeners = new Map()
    currentMatches = false

    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (query: string) => ({
        matches: currentMatches,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: (_event: string, handler: (e: MediaQueryListEvent) => void) => {
          listeners.set(query, handler)
        },
        removeEventListener: (_event: string, _handler: (e: MediaQueryListEvent) => void) => {
          listeners.delete(query)
        },
        dispatchEvent: () => false,
      }),
    })
  })

  it('returns true for narrow viewport (below default 640px breakpoint)', () => {
    currentMatches = true
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(true)
  })

  it('returns false for wide viewport (above default 640px breakpoint)', () => {
    currentMatches = false
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(false)
  })

  it('respects custom breakpoint parameter', () => {
    currentMatches = true
    const { result } = renderHook(() => useIsMobile(1024))
    expect(result.current).toBe(true)
  })

  it('updates when media query change event fires', () => {
    currentMatches = false
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(false)

    // Simulate resize to narrow viewport
    const handler = listeners.get('(max-width: 639px)')
    if (handler) {
      act(() => {
        handler({ matches: true } as MediaQueryListEvent)
      })
    }
    expect(result.current).toBe(true)
  })
})
