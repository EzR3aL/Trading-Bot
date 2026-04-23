import { useEffect } from 'react'

/**
 * Set the browser tab title for the lifetime of a route.
 *
 * Keeps each route's `<title>` distinct without pulling in
 * `react-helmet-async` — a simple `useEffect` with cleanup
 * covers the need here (no SSR, no nested metadata).
 *
 * The cleanup restores the previous title on unmount so
 * back-navigation shows the correct tab title for the
 * previous route until the next `useDocumentTitle` fires.
 */
export function useDocumentTitle(title: string, appName = 'Edge Bots'): void {
  useEffect(() => {
    const previous = document.title
    document.title = title ? `${title} · ${appName}` : appName
    return () => {
      document.title = previous
    }
  }, [title, appName])
}

export default useDocumentTitle
