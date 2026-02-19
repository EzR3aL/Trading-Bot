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

  // Periodic API health check (every 30s)
  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch('/api/health', { signal: AbortSignal.timeout(5000) })
        setApiDown(!res.ok)
      } catch {
        setApiDown(true)
      }
    }
    check()
    const interval = setInterval(check, 30_000)
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
