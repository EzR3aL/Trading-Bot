import { useEffect, useState } from 'react'

/**
 * Visibility-aware interval helpers.
 *
 * Browsers already throttle background tabs heavily, but React Query's
 * `refetchInterval` and raw `setInterval` still fire — which means we keep
 * hitting the backend while the user isn't watching and then flash stale
 * data for a moment when the tab comes back. These helpers return `false`
 * (React Query's "disable" sentinel) whenever `document.visibilityState`
 * is not `visible`, so polling quietly pauses until the tab is foregrounded
 * again.
 */

/** SSR-safe read of the current visibility state. */
function getInitialVisible(): boolean {
  return typeof document !== 'undefined'
    ? document.visibilityState === 'visible'
    : true
}

/**
 * Returns a computed `refetchInterval` value for React Query:
 * - `baseMs` when the tab is visible
 * - `false` when the tab is hidden (React Query treats this as "do not poll")
 *
 * @example
 *   const positions = useQuery({
 *     queryKey,
 *     queryFn,
 *     refetchInterval: useIntervalPaused(5000),
 *   })
 */
export function useIntervalPaused(baseMs: number): number | false {
  const [visible, setVisible] = useState<boolean>(getInitialVisible)

  useEffect(() => {
    if (typeof document === 'undefined') return
    const onChange = () => setVisible(document.visibilityState === 'visible')
    document.addEventListener('visibilitychange', onChange)
    // Resync once on mount in case visibility changed between initial
    // render and effect attach.
    onChange()
    return () => document.removeEventListener('visibilitychange', onChange)
  }, [])

  return visible ? baseMs : false
}

/**
 * Boolean companion for non-React-Query consumers. Returns `true` when the
 * tab is currently visible, `false` when it's hidden. Useful for gating
 * things like `useTradesSSE({ enabled: useVisibleTab() })` so background
 * tabs stop consuming the SSE stream and its polling fallback.
 */
export function useVisibleTab(): boolean {
  const [visible, setVisible] = useState<boolean>(getInitialVisible)

  useEffect(() => {
    if (typeof document === 'undefined') return
    const onChange = () => setVisible(document.visibilityState === 'visible')
    document.addEventListener('visibilitychange', onChange)
    onChange()
    return () => document.removeEventListener('visibilitychange', onChange)
  }, [])

  return visible
}
