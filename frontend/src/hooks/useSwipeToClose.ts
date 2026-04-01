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
  const startX = useRef(0)
  const startTime = useRef(0)
  const offsetRef = useRef(0)
  const onCloseRef = useRef(onClose)
  const locked = useRef<'swipe' | 'scroll' | null>(null)

  onCloseRef.current = onClose
  offsetRef.current = offset

  useEffect(() => {
    if (!enabled) return
    const el = ref.current
    if (!el) return

    // Find the nearest scrollable child from the touch target
    const findScrollableParent = (target: EventTarget | null): HTMLElement | null => {
      let node = target as HTMLElement | null
      while (node && node !== el) {
        if (node.scrollHeight > node.clientHeight && node.scrollTop > 0) return node
        node = node.parentElement
      }
      return null
    }

    const onTouchStart = (e: TouchEvent) => {
      startY.current = e.touches[0].clientY
      startX.current = e.touches[0].clientX
      startTime.current = Date.now()
      locked.current = null

      // If the touch started inside a scrollable area that isn't at the top,
      // lock to scroll immediately — don't compete with the swipe gesture
      const scrollable = findScrollableParent(e.target)
      if (scrollable) {
        locked.current = 'scroll'
      }
    }

    const onTouchMove = (e: TouchEvent) => {
      if (!startY.current || locked.current === 'scroll') return

      const dy = e.touches[0].clientY - startY.current
      const dx = e.touches[0].clientX - startX.current

      // First significant movement decides: swipe or scroll
      if (!locked.current) {
        const absDy = Math.abs(dy)
        const absDx = Math.abs(dx)
        // Need at least 10px of movement to decide
        if (absDy < 10 && absDx < 10) return
        // Horizontal movement dominates — this is a scroll/pan, not a close swipe
        if (absDx > absDy) { locked.current = 'scroll'; return }
        // Upward movement — user is scrolling up, not closing
        if (dy < 0) { locked.current = 'scroll'; return }
        // Downward swipe confirmed
        locked.current = 'swipe'
        setSwiping(true)
      }

      if (locked.current === 'swipe' && dy > 0) {
        setOffset(dy)
        offsetRef.current = dy
        e.preventDefault()
      }
    }

    const onTouchEnd = () => {
      if (locked.current === 'swipe') {
        const currentOffset = offsetRef.current
        const elapsed = Date.now() - startTime.current
        const velocity = currentOffset / Math.max(elapsed, 1)

        if (currentOffset >= threshold || (currentOffset > 40 && velocity > 0.5)) {
          onCloseRef.current()
        }
      }
      setOffset(0)
      offsetRef.current = 0
      setSwiping(false)
      startY.current = 0
      startX.current = 0
      locked.current = null
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
