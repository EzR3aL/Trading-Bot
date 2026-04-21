import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import ErrorBoundary from './ErrorBoundary'

interface Props {
  children: ReactNode
}

/**
 * Wraps a route element in an ErrorBoundary whose reset key is tied to
 * the current pathname, so navigating to a new route clears any error
 * thrown by the previous page. Allows sidebar/header to keep working
 * even when a single page component crashes.
 */
export default function RouteErrorBoundary({ children }: Props) {
  const location = useLocation()
  return (
    <ErrorBoundary resetKeys={[location.pathname]}>
      {children}
    </ErrorBoundary>
  )
}
