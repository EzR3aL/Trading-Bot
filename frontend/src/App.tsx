import { Routes, Route, Navigate } from 'react-router-dom'
import { lazy, Suspense, useEffect } from 'react'
import { useAuthStore } from './stores/authStore'
import AppLayout from './components/layout/AppLayout'
import ToastContainer from './components/ui/Toast'
import ErrorBoundary from './components/ui/ErrorBoundary'
import Login from './pages/Login'

// Lazy-loaded page components for code splitting
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Trades = lazy(() => import('./pages/Trades'))
const Settings = lazy(() => import('./pages/Settings'))
const Presets = lazy(() => import('./pages/Presets'))
const Bots = lazy(() => import('./pages/Bots'))
const BotDetail = lazy(() => import('./pages/BotDetail'))
const BotPerformance = lazy(() => import('./pages/BotPerformance'))
const TaxReport = lazy(() => import('./pages/TaxReport'))
const GettingStarted = lazy(() => import('./pages/GettingStarted'))
const AdminUsers = lazy(() => import('./pages/AdminUsers'))
const NotFound = lazy(() => import('./pages/NotFound'))

function PageLoader() {
  return (
    <div className="flex items-center justify-center min-h-[40vh]">
      <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
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
  if (!user || user.role !== 'admin') return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  const { isAuthenticated, fetchUser } = useAuthStore()

  useEffect(() => {
    if (isAuthenticated) {
      fetchUser()
    }
  }, [isAuthenticated, fetchUser])

  return (
    <ErrorBoundary>
      <ToastContainer />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <AppLayout>
                <Suspense fallback={<PageLoader />}>
                  <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/trades" element={<Trades />} />
                    <Route path="/settings" element={<Settings />} />
                    <Route path="/presets" element={<Presets />} />
                    <Route path="/bots" element={<Bots />} />
                    <Route path="/bots/:botId" element={<BotDetail />} />
                    <Route path="/performance" element={<BotPerformance />} />
                    <Route path="/tax-report" element={<TaxReport />} />
                    <Route path="/guide" element={<GettingStarted />} />
                    <Route
                      path="/admin/users"
                      element={
                        <AdminRoute>
                          <AdminUsers />
                        </AdminRoute>
                      }
                    />
                    <Route path="*" element={<NotFound />} />
                  </Routes>
                </Suspense>
              </AppLayout>
            </ProtectedRoute>
          }
        />
      </Routes>
    </ErrorBoundary>
  )
}
