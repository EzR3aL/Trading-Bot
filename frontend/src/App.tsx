import { Routes, Route, Navigate } from 'react-router-dom'
import { lazy, Suspense, useEffect } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from './stores/authStore'
import { queryClient } from './api/queryClient'
import AppLayout from './components/layout/AppLayout'
import ToastContainer from './components/ui/Toast'
import ErrorBoundary from './components/ui/ErrorBoundary'
import RouteErrorBoundary from './components/ui/RouteErrorBoundary'
import Login from './pages/Login'
import AuthCallback from './pages/AuthCallback'

// Lazy-loaded page components for code splitting
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Trades = lazy(() => import('./pages/Trades'))
const Settings = lazy(() => import('./pages/Settings'))
const Bots = lazy(() => import('./pages/Bots'))
const BotPerformance = lazy(() => import('./pages/BotPerformance'))
const Portfolio = lazy(() => import('./pages/Portfolio'))
const TaxReport = lazy(() => import('./pages/TaxReport'))
const GettingStarted = lazy(() => import('./pages/GettingStarted'))
const Admin = lazy(() => import('./pages/Admin'))
const NotFound = lazy(() => import('./pages/NotFound'))

function PageLoader() {
  return (
    <div className="flex items-center justify-center min-h-[40vh]">
      <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  // User data still loading after page refresh — show loader instead of redirecting
  if (isAuthenticated && !user) return <PageLoader />
  if (!user || user.role !== 'admin') return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  const fetchUser = useAuthStore((s) => s.fetchUser)
  const { i18n } = useTranslation()

  // Keep html lang attribute in sync with current language (accessibility)
  useEffect(() => {
    document.documentElement.lang = i18n.language || 'en'
  }, [i18n.language])

  // On mount, check if a valid session exists via httpOnly cookie.
  // This replaces the old localStorage token check.
  useEffect(() => {
    fetchUser()
  }, [fetchUser])

  return (
    <QueryClientProvider client={queryClient}>
    <ErrorBoundary>
      <ToastContainer />
      <Routes>
        <Route path="/login" element={<RouteErrorBoundary><Login /></RouteErrorBoundary>} />
        <Route path="/auth/callback" element={<RouteErrorBoundary><AuthCallback /></RouteErrorBoundary>} />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <AppLayout>
                <Suspense fallback={<PageLoader />}>
                  <Routes>
                    <Route path="/" element={<RouteErrorBoundary><Dashboard /></RouteErrorBoundary>} />
                    <Route path="/portfolio" element={<RouteErrorBoundary><Portfolio /></RouteErrorBoundary>} />
                    <Route path="/trades" element={<RouteErrorBoundary><Trades /></RouteErrorBoundary>} />
                    <Route path="/settings" element={<RouteErrorBoundary><Settings /></RouteErrorBoundary>} />
                    <Route path="/bots" element={<RouteErrorBoundary><Bots /></RouteErrorBoundary>} />
                    <Route path="/performance" element={<RouteErrorBoundary><BotPerformance /></RouteErrorBoundary>} />
                    <Route path="/tax-report" element={<RouteErrorBoundary><TaxReport /></RouteErrorBoundary>} />
                    <Route path="/guide" element={<RouteErrorBoundary><GettingStarted /></RouteErrorBoundary>} />
                    <Route
                      path="/admin"
                      element={
                        <AdminRoute>
                          <RouteErrorBoundary><Admin /></RouteErrorBoundary>
                        </AdminRoute>
                      }
                    />
                    <Route path="*" element={<RouteErrorBoundary><NotFound /></RouteErrorBoundary>} />
                  </Routes>
                </Suspense>
              </AppLayout>
            </ProtectedRoute>
          }
        />
      </Routes>
    </ErrorBoundary>
    </QueryClientProvider>
  )
}
