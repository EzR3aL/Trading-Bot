import { useEffect, useRef, useState, useCallback } from 'react'

interface PullToRefreshOptions {
  onRefresh: () => Promise<void>
  threshold?: number
  disabled?: boolean
}

export default function usePullToRefresh({ onRefresh, threshold = 80, disabled = false }: PullToRefreshOptions) {
  const [pulling, setPulling] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [pullDistance, setPullDistance] = useState(0)
  const startY = useRef(0)
  const pullDistanceRef = useRef(0)
  const containerRef = useRef<HTMLDivElement>(null)

  const handleRefresh = useCallback(async () => {
    setRefreshing(true)
    setPullDistance(0)
    pullDistanceRef.current = 0
    try {
      await onRefresh()
    } finally {
      setRefreshing(false)
    }
  }, [onRefresh])

  useEffect(() => {
    if (disabled) return
    const container = containerRef.current
    if (!container) return

    const onTouchStart = (e: TouchEvent) => {
      if (container.scrollTop > 0) return
      startY.current = e.touches[0].clientY
      setPulling(true)
    }

    const onTouchMove = (e: TouchEvent) => {
      if (!startY.current || container.scrollTop > 0) return
      const currentY = e.touches[0].clientY
      const distance = Math.max(0, currentY - startY.current)
      if (distance > 0) {
        const dampened = distance > threshold
          ? threshold + (distance - threshold) * 0.3
          : distance
        setPullDistance(dampened)
        pullDistanceRef.current = dampened
        if (distance > 10) e.preventDefault()
      }
    }

    const onTouchEnd = () => {
      const currentPullDistance = pullDistanceRef.current
      if (currentPullDistance >= threshold) {
        handleRefresh()
      } else {
        setPullDistance(0)
        pullDistanceRef.current = 0
      }
      setPulling(false)
      startY.current = 0
    }

    container.addEventListener('touchstart', onTouchStart, { passive: true })
    container.addEventListener('touchmove', onTouchMove, { passive: false })
    container.addEventListener('touchend', onTouchEnd, { passive: true })

    return () => {
      container.removeEventListener('touchstart', onTouchStart)
      container.removeEventListener('touchmove', onTouchMove)
      container.removeEventListener('touchend', onTouchEnd)
    }
  }, [disabled, threshold, handleRefresh])

  return { containerRef, pulling, refreshing, pullDistance }
}
