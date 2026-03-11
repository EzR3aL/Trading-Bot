import { useState, useEffect, useCallback } from 'react'
import { WifiOff, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'

export default function OfflineIndicator() {
  const { t } = useTranslation()
  const [isOffline, setIsOffline] = useState(!navigator.onLine)
  const [apiDown, setApiDown] = useState(false)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    const handleOnline = () => setIsOffline(false)
    const handleOffline = () => setIsOffline(true)
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  // Reset dismiss when state changes (e.g. goes offline again after recovery)
  useEffect(() => {
    if (!isOffline && !apiDown) setDismissed(false)
  }, [isOffline, apiDown])

  // Periodic API health check (every 30s, require 3 consecutive failures)
  useEffect(() => {
    let failCount = 0
    const check = async () => {
      try {
        const res = await fetch('/api/health', { signal: AbortSignal.timeout(8000) })
        if (res.ok) {
          failCount = 0
          setApiDown(false)
        } else {
          failCount++
          if (failCount >= 3) setApiDown(true)
        }
      } catch {
        failCount++
        if (failCount >= 3) setApiDown(true)
      }
    }
    // Delay first check to avoid false positives during page load
    const initialTimeout = setTimeout(check, 5_000)
    const interval = setInterval(check, 30_000)
    return () => {
      clearTimeout(initialTimeout)
      clearInterval(interval)
    }
  }, [])

  const handleDismiss = useCallback(() => setDismissed(true), [])

  if (dismissed || (!isOffline && !apiDown)) return null

  return (
    <div role="alert" aria-live="assertive" className="fixed top-0 left-0 right-0 z-50 bg-yellow-600 text-white text-center py-2 text-sm font-medium flex items-center justify-center gap-2">
      <WifiOff className="h-4 w-4" />
      {isOffline
        ? t('common.noInternet', 'No internet connection')
        : t('common.apiUnreachable', 'API server temporarily unreachable')}
      <button
        onClick={handleDismiss}
        className="ml-3 p-0.5 rounded hover:bg-yellow-700 transition-colors"
        aria-label="Dismiss"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
