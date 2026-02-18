import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { X, ChevronLeft, ChevronRight, HelpCircle } from 'lucide-react'
import { useTourStore } from '../../stores/tourStore'

export interface TourStep {
  target: string
  titleKey: string
  descriptionKey: string
  position?: 'top' | 'bottom' | 'left' | 'right'
}

interface GuidedTourProps {
  tourId: string
  steps: TourStep[]
  autoStart?: boolean
  onComplete?: () => void
}

interface Rect {
  top: number
  left: number
  width: number
  height: number
}

function getTooltipPosition(
  targetRect: Rect,
  position: 'top' | 'bottom' | 'left' | 'right',
  tooltipWidth: number,
  tooltipHeight: number,
) {
  const gap = 12
  const pad = 16

  let top = 0
  let left = 0

  switch (position) {
    case 'bottom':
      top = targetRect.top + targetRect.height + gap
      left = targetRect.left + targetRect.width / 2 - tooltipWidth / 2
      break
    case 'top':
      top = targetRect.top - tooltipHeight - gap
      left = targetRect.left + targetRect.width / 2 - tooltipWidth / 2
      break
    case 'right':
      top = targetRect.top + targetRect.height / 2 - tooltipHeight / 2
      left = targetRect.left + targetRect.width + gap
      break
    case 'left':
      top = targetRect.top + targetRect.height / 2 - tooltipHeight / 2
      left = targetRect.left - tooltipWidth - gap
      break
  }

  // Clamp to viewport
  left = Math.max(pad, Math.min(left, window.innerWidth - tooltipWidth - pad))
  top = Math.max(pad, Math.min(top, window.innerHeight - tooltipHeight - pad))

  return { top, left }
}

function bestPosition(targetRect: Rect): 'top' | 'bottom' | 'left' | 'right' {
  const spaceBelow = window.innerHeight - (targetRect.top + targetRect.height)
  const spaceAbove = targetRect.top
  const spaceRight = window.innerWidth - (targetRect.left + targetRect.width)
  const spaceLeft = targetRect.left

  const minSpace = 200
  if (spaceBelow >= minSpace) return 'bottom'
  if (spaceAbove >= minSpace) return 'top'
  if (spaceRight >= minSpace) return 'right'
  if (spaceLeft >= minSpace) return 'left'
  return 'bottom'
}

export default function GuidedTour({ tourId, steps, autoStart = true, onComplete }: GuidedTourProps) {
  const { t } = useTranslation()
  const { markComplete, shouldShowTour, activeTour, setActiveTour } = useTourStore()
  const [currentStep, setCurrentStep] = useState(0)
  const [targetRect, setTargetRect] = useState<Rect | null>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)
  const [tooltipSize, setTooltipSize] = useState({ width: 320, height: 160 })

  const isActive = activeTour === tourId

  // Auto-start on first visit
  useEffect(() => {
    if (autoStart && shouldShowTour(tourId) && !activeTour) {
      const timer = setTimeout(() => setActiveTour(tourId), 600)
      return () => clearTimeout(timer)
    }
  }, [autoStart, tourId, shouldShowTour, activeTour, setActiveTour])

  // Find and highlight target element
  const updateTargetRect = useCallback(() => {
    if (!isActive || !steps[currentStep]) return

    const el = document.querySelector(steps[currentStep].target)
    if (el) {
      const rect = el.getBoundingClientRect()
      setTargetRect({
        top: rect.top,
        left: rect.left,
        width: rect.width,
        height: rect.height,
      })

      // Scroll element into view if needed
      const isVisible =
        rect.top >= 0 &&
        rect.bottom <= window.innerHeight &&
        rect.left >= 0 &&
        rect.right <= window.innerWidth

      if (!isVisible) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        // Update rect after scroll
        setTimeout(() => {
          const newRect = el.getBoundingClientRect()
          setTargetRect({
            top: newRect.top,
            left: newRect.left,
            width: newRect.width,
            height: newRect.height,
          })
        }, 400)
      }
    } else {
      setTargetRect(null)
    }
  }, [isActive, currentStep, steps])

  useEffect(() => {
    updateTargetRect()
    window.addEventListener('resize', updateTargetRect)
    window.addEventListener('scroll', updateTargetRect, true)
    return () => {
      window.removeEventListener('resize', updateTargetRect)
      window.removeEventListener('scroll', updateTargetRect, true)
    }
  }, [updateTargetRect])

  // Measure tooltip
  useEffect(() => {
    if (tooltipRef.current) {
      const { offsetWidth, offsetHeight } = tooltipRef.current
      setTooltipSize({ width: offsetWidth, height: offsetHeight })
    }
  }, [currentStep, isActive])

  const handleNext = () => {
    if (currentStep < steps.length - 1) {
      setCurrentStep(currentStep + 1)
    } else {
      handleComplete()
    }
  }

  const handlePrev = () => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1)
    }
  }

  const handleSkip = () => {
    markComplete(tourId)
    setCurrentStep(0)
    onComplete?.()
  }

  const handleComplete = () => {
    markComplete(tourId)
    setCurrentStep(0)
    onComplete?.()
  }

  if (!isActive || steps.length === 0) return null

  const step = steps[currentStep]
  const pos = step.position || (targetRect ? bestPosition(targetRect) : 'bottom')
  const tooltipPos = targetRect
    ? getTooltipPosition(targetRect, pos, tooltipSize.width, tooltipSize.height)
    : { top: window.innerHeight / 2 - 80, left: window.innerWidth / 2 - 160 }

  const highlightPad = 6

  return (
    <div className="fixed inset-0 z-[9999]" style={{ pointerEvents: 'auto' }}>
      {/* Dark overlay with cutout */}
      <svg className="absolute inset-0 w-full h-full" style={{ pointerEvents: 'none' }}>
        <defs>
          <mask id={`tour-mask-${tourId}`}>
            <rect x="0" y="0" width="100%" height="100%" fill="white" />
            {targetRect && (
              <rect
                x={targetRect.left - highlightPad}
                y={targetRect.top - highlightPad}
                width={targetRect.width + highlightPad * 2}
                height={targetRect.height + highlightPad * 2}
                rx="8"
                fill="black"
              />
            )}
          </mask>
        </defs>
        <rect
          x="0"
          y="0"
          width="100%"
          height="100%"
          fill="rgba(0,0,0,0.72)"
          mask={`url(#tour-mask-${tourId})`}
        />
      </svg>

      {/* Highlight border ring */}
      {targetRect && (
        <div
          className="absolute border-2 border-primary-400 rounded-lg pointer-events-none animate-pulse"
          style={{
            top: targetRect.top - highlightPad,
            left: targetRect.left - highlightPad,
            width: targetRect.width + highlightPad * 2,
            height: targetRect.height + highlightPad * 2,
            boxShadow: '0 0 20px rgba(99, 179, 237, 0.3)',
          }}
        />
      )}

      {/* Click-through on highlighted area */}
      {targetRect && (
        <div
          className="absolute"
          style={{
            top: targetRect.top - highlightPad,
            left: targetRect.left - highlightPad,
            width: targetRect.width + highlightPad * 2,
            height: targetRect.height + highlightPad * 2,
            pointerEvents: 'auto',
            cursor: 'default',
          }}
        />
      )}

      {/* Click overlay to prevent interaction outside target */}
      <div className="absolute inset-0" onClick={handleSkip} style={{ pointerEvents: 'auto' }} />

      {/* Tooltip */}
      <div
        ref={tooltipRef}
        className="absolute w-80 bg-gray-900 border border-white/10 rounded-xl shadow-2xl p-4 pointer-events-auto"
        style={{
          top: tooltipPos.top,
          left: tooltipPos.left,
          zIndex: 10000,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Step indicator + counter + close */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5">
            {steps.map((_, i) => (
              <div
                key={i}
                className={`h-1.5 rounded-full transition-all duration-300 ${
                  i === currentStep
                    ? 'w-6 bg-primary-400'
                    : i < currentStep
                      ? 'w-1.5 bg-primary-600'
                      : 'w-1.5 bg-gray-700'
                }`}
              />
            ))}
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-500">
              {currentStep + 1}/{steps.length}
            </span>
            <button
              onClick={handleSkip}
              className="text-gray-500 hover:text-gray-300 transition-colors"
              aria-label={t('tour.skip')}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Content */}
        <h3 className="text-sm font-semibold text-white mb-1">{t(step.titleKey)}</h3>
        <p className="text-xs text-gray-400 leading-relaxed mb-4">{t(step.descriptionKey)}</p>

        {/* Navigation */}
        <div className="flex items-center justify-between">
          <button
            onClick={handleSkip}
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            {t('tour.skip')}
          </button>

          <div className="flex items-center gap-2">
            {currentStep > 0 && (
              <button
                onClick={handlePrev}
                className="flex items-center gap-1 px-3 py-1.5 text-xs text-gray-300 bg-white/5 hover:bg-white/10 rounded-lg border border-white/5 transition-colors"
              >
                <ChevronLeft size={14} />
                {t('tour.prev')}
              </button>
            )}
            <button
              onClick={handleNext}
              className="flex items-center gap-1 px-3 py-1.5 text-xs text-white bg-primary-600 hover:bg-primary-500 rounded-lg transition-colors font-medium"
            >
              {currentStep === steps.length - 1 ? t('tour.done') : t('tour.next')}
              {currentStep < steps.length - 1 && <ChevronRight size={14} />}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// Reusable help button to restart a tour
export function TourHelpButton({ tourId }: { tourId: string }) {
  const { t } = useTranslation()
  const { setActiveTour } = useTourStore()

  return (
    <button
      onClick={() => setActiveTour(tourId)}
      className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-gray-400 hover:text-white bg-white/5 hover:bg-white/10 rounded-lg border border-white/5 transition-all duration-200"
      aria-label={t('tour.helpButton')}
      title={t('tour.helpButton')}
    >
      <HelpCircle size={14} />
      <span className="hidden sm:inline">{t('tour.helpButton')}</span>
    </button>
  )
}
