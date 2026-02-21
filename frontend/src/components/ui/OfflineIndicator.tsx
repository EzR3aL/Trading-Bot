import { useState, useEffect } from 'react'
import { WifiOff } from 'lucide-react'

export default function OfflineIndicator() {
  const [isOffline, setIsOffline] = useState(!navigator.onLine)
  const [apiDown, setApiDown] = useState(false)

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

  // Periodic API health check (every 15s, require 2 consecutive failures)
  useEffect(() => {
    let failCount = 0
    const check = async () => {
      try {
        const res = await fetch('/api/health', { signal: AbortSignal.timeout(5000) })
        if (res.ok) {
          failCount = 0
          setApiDown(false)
        } else {
          failCount++
          if (failCount >= 2) setApiDown(true)
        }
      } catch {
        failCount++
        if (failCount >= 2) setApiDown(true)
      }
    }
    check()
    const interval = setInterval(check, 15_000)
    return () => clearInterval(interval)
  }, [])

  if (!isOffline && !apiDown) return null

  return (
    <div className="fixed top-0 left-0 right-0 z-50 bg-red-600 text-white text-center py-2 text-sm font-medium flex items-center justify-center gap-2">
      <WifiOff className="h-4 w-4" />
      {isOffline ? 'No internet connection' : 'API server unreachable'}
    </div>
  )
}
