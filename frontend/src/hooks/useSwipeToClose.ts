import { useRef, useEffect, useState } from 'react'

interface SwipeToCloseOptions {
  onClose: () => void
  threshold?: number // px to trigger close (default 120)
  enabled?: boolean
}

export default function useSwipeToClose({ onClose, threshold = 120, enabled = true }: SwipeToCloseOptions) {
  const [offset, setOffset] = useState(0)
  const [swiping, setSwiping] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const startY = useRef(0)
  const startTime = useRef(0)
  const offsetRef = useRef(0)
  const onCloseRef = useRef(onClose)

  // Keep refs in sync to avoid stale closures in touch handlers
  onCloseRef.current = onClose
  offsetRef.current = offset

  useEffect(() => {
    if (!enabled) return
    const el = ref.current
    if (!el) return

    const onTouchStart = (e: TouchEvent) => {
      startY.current = e.touches[0].clientY
      startTime.current = Date.now()
      setSwiping(true)
    }

    const onTouchMove = (e: TouchEvent) => {
      if (!startY.current) return
      const dy = e.touches[0].clientY - startY.current
      // Only allow downward swipe
      if (dy > 0) {
        setOffset(dy)
        offsetRef.current = dy
        e.preventDefault()
      }
    }

    const onTouchEnd = () => {
      const currentOffset = offsetRef.current
      const elapsed = Date.now() - startTime.current
      const velocity = currentOffset / Math.max(elapsed, 1)

      // Close if threshold reached OR fast swipe (velocity > 0.5px/ms)
      if (currentOffset >= threshold || (currentOffset > 40 && velocity > 0.5)) {
        onCloseRef.current()
      }
      setOffset(0)
      offsetRef.current = 0
      setSwiping(false)
      startY.current = 0
    }

    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    el.addEventListener('touchend', onTouchEnd, { passive: true })

    return () => {
      el.removeEventListener('touchstart', onTouchStart)
      el.removeEventListener('touchmove', onTouchMove)
      el.removeEventListener('touchend', onTouchEnd)
    }
  }, [enabled, threshold])

  const style = offset > 0
    ? { transform: `translateY(${offset}px)`, opacity: Math.max(1 - offset / 300, 0.3), transition: swiping ? 'none' : 'transform 0.2s, opacity 0.2s' }
    : { transition: 'transform 0.2s, opacity 0.2s' }

  return { ref, style, swiping, offset }
}
