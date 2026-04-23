import { useEffect, useState } from 'react'
import { useWindowVirtualizer, type VirtualItem } from '@tanstack/react-virtual'

/**
 * Minimum row count before virtualisation kicks in.
 *
 * Below this threshold the overhead of maintaining the virtualiser
 * (scroll listeners, size measurements, spacer <tr>s) exceeds any
 * saving we'd get from skipping DOM creation. At and above it, we
 * start seeing measurable DOM-cost wins in Chrome's perf timeline.
 */
export const VIRTUALISATION_THRESHOLD = 50

/**
 * Default estimated row height in pixels.
 *
 * Derived from the .table-premium CSS:
 *   - `px-4 py-3` (Tailwind) on <td> = 12px top + 12px bottom padding
 *   - text-sm = 20px line-height
 *   - border-b (1px) on <tr>
 *
 * Total baseline ≈ 45px; we round up to 48 to give a small safety
 * margin so the first render doesn't undershoot (which causes a
 * visible re-layout flash as measureElement corrects the offsets).
 */
export const DEFAULT_ROW_HEIGHT = 48

export interface UseVirtualRowsOptions {
  /**
   * The source array length. Virtualisation is applied when this
   * count is >= VIRTUALISATION_THRESHOLD.
   */
  count: number
  /**
   * Ref to the element whose bounding box anchors the virtualiser's
   * scroll offset. Typically the <tbody>'s parent (e.g. the overflow-x-auto
   * wrapper) or the <table> itself — anything that participates in the
   * main page scroll.
   */
  scrollMarginRef: React.RefObject<HTMLElement | null>
  /**
   * Estimated row height in pixels. Defaults to DEFAULT_ROW_HEIGHT.
   */
  estimateSize?: number
  /**
   * Overscan count — rows rendered above and below the viewport so
   * scrolling feels instant. 8 is a sensible default for ~48px rows.
   */
  overscan?: number
}

export interface UseVirtualRowsResult {
  /**
   * Whether virtualisation is active. When false, callers should
   * render the full list normally — virtualItems will be empty and
   * the spacer heights will be zero.
   */
  isVirtualised: boolean
  /**
   * The windowed slice of items to render. Each item has .index
   * into the source array and .key for React's reconciliation.
   */
  virtualItems: VirtualItem[]
  /**
   * Empty-space height (px) to render before the first visible row.
   * Used as the `height` of a placeholder <tr> so scroll position
   * stays consistent.
   */
  paddingTop: number
  /**
   * Empty-space height (px) to render after the last visible row.
   */
  paddingBottom: number
  /**
   * Ref callback to attach to each rendered virtual row's <tr>.
   * Enables dynamic re-measurement when rows turn out to be taller
   * or shorter than our estimate (e.g. expanded detail rows).
   */
  measureElement: (node: Element | null) => void
}

/**
 * Virtualise a long <tr> list anchored to the window scroll.
 *
 * Designed for <table>-based layouts where we want to keep existing
 * CSS (.table-premium hover/nth-child selectors) and can't switch to
 * absolute-positioned divs. The caller emits:
 *
 *   <tbody>
 *     {paddingTop > 0 && <tr style={{ height: paddingTop }} aria-hidden />}
 *     {virtualItems.map(v => <MyRow ref={measureElement} data-index={v.index} ... />)}
 *     {paddingBottom > 0 && <tr style={{ height: paddingBottom }} aria-hidden />}
 *   </tbody>
 *
 * When count < VIRTUALISATION_THRESHOLD the hook returns `isVirtualised: false`
 * with empty items so the caller can fall back to a plain full render.
 */
export function useVirtualRows({
  count,
  scrollMarginRef,
  estimateSize = DEFAULT_ROW_HEIGHT,
  overscan = 8,
}: UseVirtualRowsOptions): UseVirtualRowsResult {
  const isVirtualised = count >= VIRTUALISATION_THRESHOLD
  const scrollMargin = useScrollMargin(scrollMarginRef, isVirtualised)

  const virtualizer = useWindowVirtualizer({
    count: isVirtualised ? count : 0,
    estimateSize: () => estimateSize,
    overscan,
    scrollMargin,
  })

  const virtualItems = isVirtualised ? virtualizer.getVirtualItems() : []
  const totalSize = isVirtualised ? virtualizer.getTotalSize() : 0

  const paddingTop = virtualItems.length > 0 ? virtualItems[0].start : 0
  const paddingBottom =
    virtualItems.length > 0
      ? totalSize - virtualItems[virtualItems.length - 1].end
      : 0

  return {
    isVirtualised,
    virtualItems,
    paddingTop,
    paddingBottom,
    measureElement: virtualizer.measureElement,
  }
}

/**
 * Track the offset-from-document-top of `ref.current` so the window
 * virtualiser knows where the list begins on the page.
 *
 * Updates on resize / layout shifts above the table via ResizeObserver;
 * gated behind `enabled` so we don't pay for observers when the list
 * is short enough to render without virtualisation.
 */
function useScrollMargin(
  ref: React.RefObject<HTMLElement | null>,
  enabled: boolean,
): number {
  const [margin, setMargin] = useState(0)

  useEffect(() => {
    if (!enabled) return
    const node = ref.current
    if (!node) return

    const measure = () => {
      const rect = node.getBoundingClientRect()
      setMargin(rect.top + window.scrollY)
    }

    measure()

    // Guard ResizeObserver: JSDOM in older vitest versions can be
    // missing it. We degrade gracefully — window resize is still
    // observed, which is the common case.
    let ro: ResizeObserver | undefined
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(measure)
      ro.observe(node)
    }
    window.addEventListener('resize', measure)
    return () => {
      ro?.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [enabled, ref])

  return margin
}
