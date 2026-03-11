import { useState, useRef, useCallback, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { createPortal } from 'react-dom'

interface PnlCellProps {
  pnl: number | null
  fees: number
  fundingPaid: number
  /** "closed" shows tooltip; "open" disables it. Default: "closed". */
  status?: string
  className?: string
  /** Custom content instead of default formatPnl */
  children?: ReactNode
}

function formatPnl(value: number | null): string {
  if (value === null) return '--'
  const prefix = value >= 0 ? '+' : ''
  return `${prefix}$${value.toFixed(2)}`
}

/** Screen-reader-only label describing profit/loss beyond color alone */
function pnlSrLabel(value: number | null): string {
  if (value === null) return ''
  return value >= 0 ? 'Profit' : 'Loss'
}

export default function PnlCell({ pnl, fees, fundingPaid, status = 'closed', className, children }: PnlCellProps) {
  const { t } = useTranslation()
  const [show, setShow] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const ref = useRef<HTMLSpanElement>(null)

  const canShow = status === 'closed'

  const handleEnter = useCallback(() => {
    if (!canShow || !ref.current) return
    const rect = ref.current.getBoundingClientRect()
    setPos({
      top: rect.top - 8,
      left: rect.right,
    })
    setShow(true)
  }, [canShow])

  const handleLeave = useCallback(() => setShow(false), [])

  const pnlColor = pnl !== null && pnl >= 0 ? 'text-profit' : 'text-loss'
  const total = fees + fundingPaid

  return (
    <>
      <span
        ref={ref}
        className={`cursor-default ${className ?? pnlColor}`}
        onMouseEnter={handleEnter}
        onMouseLeave={handleLeave}
        onFocus={handleEnter}
        onBlur={handleLeave}
        tabIndex={canShow ? 0 : undefined}
        role="cell"
        aria-label={pnl !== null ? `${pnlSrLabel(pnl)}: ${formatPnl(pnl)}` : undefined}
      >
        {children ?? formatPnl(pnl)}
      </span>

      {show && canShow && createPortal(
        <div
          className="fixed z-[9999] pointer-events-none"
          style={{ top: pos.top, left: pos.left, transform: 'translate(-100%, -100%)' }}
        >
          <div className="bg-[#141a2a]/95 border border-white/10 rounded-xl px-3 py-2 text-xs whitespace-nowrap shadow-2xl backdrop-blur-xl">
            <div className="flex justify-between gap-4">
              <span className="text-gray-400">{t('trades.fees')}:</span>
              <span className="text-amber-400 font-mono">{fees > 0 ? `$${fees.toFixed(2)}` : '--'}</span>
            </div>
            <div className="flex justify-between gap-4 mt-0.5">
              <span className="text-gray-400">{t('dashboard.funding')}:</span>
              <span className="text-purple-400 font-mono">{fundingPaid > 0 ? `$${fundingPaid.toFixed(2)}` : '--'}</span>
            </div>
            {total > 0 && (
              <div className="flex justify-between gap-4 mt-1 pt-1 border-t border-white/10">
                <span className="text-gray-300">{t('common.total')}:</span>
                <span className="text-white font-mono font-semibold">${total.toFixed(2)}</span>
              </div>
            )}
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}
