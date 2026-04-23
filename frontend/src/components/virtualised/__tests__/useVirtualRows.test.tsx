import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { useRef } from 'react'
import {
  useVirtualRows,
  VIRTUALISATION_THRESHOLD,
  DEFAULT_ROW_HEIGHT,
} from '../useVirtualRows'

/**
 * Harness that mounts useVirtualRows into a realistic <table> layout so
 * the hook's contract (windowed <tr> slice + spacer <tr>s) is exercised
 * end-to-end, not via mocked internals.
 *
 * JSDOM does not perform layout: getBoundingClientRect returns zeros
 * and offsetHeight is zero. As a result the exact rendered-slice size
 * inside the test harness is unstable — it depends on react-virtual's
 * internal fallback handling of zero-sized scroll containers. We pin
 * only the behaviours we need to keep stable across library upgrades:
 *
 *   1. Threshold guard: below VIRTUALISATION_THRESHOLD rows, every row
 *      lands in the DOM (no virtualisation overhead).
 *   2. At or above the threshold, virtualisation engages and the
 *      rendered-row count is bounded — strictly less than the source
 *      length. (A precise upper bound requires real layout; we assert
 *      the "< source length" inequality, which is the invariant a
 *      browser run-time upholds.)
 *   3. Sort/filter: source-array changes flow through unchanged —
 *      the hook never reorders or filters on its own.
 */

interface HarnessProps {
  count: number
  estimate?: number
  /**
   * Exposes the rendered-row count after each commit. Used so tests
   * can assert on windowing behaviour without racing react-virtual's
   * internal scheduling.
   */
  onRender?: (info: { renderedCount: number; isVirtualised: boolean }) => void
}

function TableHarness({ count, estimate, onRender }: HarnessProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const { isVirtualised, virtualItems, paddingTop, paddingBottom, measureElement } =
    useVirtualRows({
      count,
      scrollMarginRef: scrollRef,
      estimateSize: estimate,
    })

  onRender?.({ renderedCount: virtualItems.length, isVirtualised })

  return (
    <div ref={scrollRef} data-testid="scroll-container">
      <table>
        <tbody>
          {isVirtualised ? (
            <>
              {paddingTop > 0 && (
                <tr aria-hidden="true" style={{ height: paddingTop }} data-testid="spacer-top">
                  <td />
                </tr>
              )}
              {virtualItems.map((vi) => (
                <tr
                  key={vi.key}
                  ref={measureElement}
                  data-index={vi.index}
                  data-testid="virtual-row"
                >
                  <td>Row {vi.index}</td>
                </tr>
              ))}
              {paddingBottom > 0 && (
                <tr aria-hidden="true" style={{ height: paddingBottom }} data-testid="spacer-bottom">
                  <td />
                </tr>
              )}
            </>
          ) : (
            // Full render — every row hits the DOM. Used to prove the
            // threshold guard: below it, we render count rows verbatim.
            Array.from({ length: count }, (_, i) => (
              <tr key={i} data-testid="full-row" data-index={i}>
                <td>Row {i}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

describe('useVirtualRows', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'setInterval', 'requestAnimationFrame'] })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('exposes the documented threshold and row-height constants', () => {
    // Pin the documented contract — downstream callers depend on these
    // values matching the CSS-derived defaults. If either changes, the
    // callers' estimateSize assumptions may drift.
    expect(VIRTUALISATION_THRESHOLD).toBe(50)
    expect(DEFAULT_ROW_HEIGHT).toBe(48)
  })

  it('does not virtualise below the threshold — every source row renders', () => {
    const count = VIRTUALISATION_THRESHOLD - 1
    let lastInfo: { renderedCount: number; isVirtualised: boolean } | null = null
    render(<TableHarness count={count} onRender={(info) => { lastInfo = info }} />)

    // All `count` rows land in the DOM as plain (non-virtual) rows,
    // and the hook reports the expected mode flag.
    expect(screen.getAllByTestId('full-row')).toHaveLength(count)
    expect(screen.queryAllByTestId('virtual-row')).toHaveLength(0)
    expect(lastInfo!.isVirtualised).toBe(false)
  })

  it('virtualises at the threshold and renders strictly fewer rows than the source', () => {
    const count = 1000
    let lastInfo: { renderedCount: number; isVirtualised: boolean } | null = null
    render(<TableHarness count={count} onRender={(info) => { lastInfo = info }} />)

    act(() => {
      // Flush any rAF-scheduled re-measures so the first settled window
      // (not the pre-measure empty state) is what we assert against.
      vi.runAllTimers()
    })

    // Library-level contract: the hook reports virtualised mode,
    // renders some rows, and renders strictly fewer than the source.
    // Exact bounds depend on real layout (absent in JSDOM); the
    // inequality below is the invariant users care about.
    expect(lastInfo!.isVirtualised).toBe(true)
    const rendered = screen.queryAllByTestId('virtual-row')
    expect(rendered.length).toBeGreaterThan(0)
    expect(rendered.length).toBeLessThan(count)
  })

  it('preserves source-array order — sort/filter flow through unchanged', () => {
    // The hook is pure: it exposes indices into the caller's source
    // array in ascending order. This is the contract a caller relies
    // on when they sort-then-pass — the hook never reorders.
    const count = 1000
    render(<TableHarness count={count} />)
    act(() => { vi.runAllTimers() })

    const rows = screen.queryAllByTestId('virtual-row')
    expect(rows.length).toBeGreaterThan(0)

    // Indices are strictly ascending — no reordering, no duplicates.
    const indices = rows.map((r) => Number(r.getAttribute('data-index')))
    for (let i = 1; i < indices.length; i++) {
      expect(indices[i]).toBeGreaterThan(indices[i - 1])
    }
  })

  it('disengages virtualisation when a filter drops count below threshold', () => {
    // Users filter long lists down to short lists all the time. The
    // hook must switch back to the full-render path without tearing
    // the tree — otherwise the user sees empty rows after filtering.
    let lastInfo: { renderedCount: number; isVirtualised: boolean } | null = null
    const { rerender } = render(
      <TableHarness count={1000} onRender={(i) => { lastInfo = i }} />,
    )
    act(() => { vi.runAllTimers() })
    expect(lastInfo!.isVirtualised).toBe(true)

    // Simulate a filter that drops the source below the threshold.
    rerender(<TableHarness count={10} onRender={(i) => { lastInfo = i }} />)
    expect(screen.getAllByTestId('full-row')).toHaveLength(10)
    expect(screen.queryAllByTestId('virtual-row')).toHaveLength(0)
    expect(lastInfo!.isVirtualised).toBe(false)
  })
})
