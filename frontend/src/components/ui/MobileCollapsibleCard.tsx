import { useState } from 'react'
import { ChevronDown } from 'lucide-react'

interface MobileCollapsibleCardProps {
  /** Always-visible header content */
  header: React.ReactNode
  /** Always-visible summary row below header */
  summary?: React.ReactNode
  /** Content shown when expanded */
  children: React.ReactNode
  /** Control expanded state externally (optional) */
  isOpen?: boolean
  /** Callback when toggled (optional, for external state) */
  onToggle?: () => void
  /** Additional className for the outer container */
  className?: string
}

/**
 * Shared collapsible card for mobile views.
 * Used by: MobileTradeCard, MobilePositionCard, Bots, Backtest, TaxReport.
 *
 * Provides consistent styling: border, rounded corners, chevron, expand animation.
 */
export default function MobileCollapsibleCard({
  header,
  summary,
  children,
  isOpen: controlledOpen,
  onToggle,
  className = '',
}: MobileCollapsibleCardProps) {
  const [internalOpen, setInternalOpen] = useState(false)
  const isOpen = controlledOpen ?? internalOpen
  const toggle = onToggle ?? (() => setInternalOpen(!internalOpen))

  return (
    <div className={`border border-white/[0.06] rounded-lg bg-white/[0.02] overflow-hidden ${className}`}>
      {/* Header — always visible, clickable */}
      <div className="cursor-pointer" onClick={toggle}>
        <div className="flex items-center justify-between px-3 pt-2 pb-1">
          <div className="flex items-center gap-1.5 min-w-0 flex-1">
            {header}
          </div>
          {!summary && (
            <ChevronDown size={12} className={`text-gray-400 shrink-0 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} />
          )}
        </div>
        {/* Summary row — always visible */}
        {summary && (
          <div className="flex items-center justify-between px-3 pb-2 text-[11px] gap-2">
            <div className="flex items-center gap-3 text-gray-400 min-w-0 flex-1">
              {summary}
            </div>
            <ChevronDown size={12} className={`text-gray-400 shrink-0 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} />
          </div>
        )}
      </div>
      {/* Expandable details */}
      {isOpen && (
        <div className="border-t border-white/[0.04] px-3 py-2">
          {children}
        </div>
      )}
    </div>
  )
}
