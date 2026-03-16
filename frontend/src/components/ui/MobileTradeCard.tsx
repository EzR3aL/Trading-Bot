import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ExchangeIcon } from './ExchangeLogo'
import ExitReasonBadge from './ExitReasonBadge'
import { formatDateTime } from '../../utils/dateUtils'

interface MobileTradeCardProps {
  trade: {
    id: number
    symbol: string
    side: string
    entry_price: number
    exit_price?: number | null
    pnl?: number | null
    pnl_percent?: number | null
    fees?: number
    funding_paid?: number
    status: string
    entry_time: string
    exit_time?: string | null
    demo_mode?: boolean
    exchange?: string | null
    bot_exchange?: string | null
    bot_name?: string | null
    leverage?: number
    confidence?: number
    size?: number
    exit_reason?: string | null
  }
  extraDetails?: { label: string; value: string | React.ReactNode }[]
}

function formatPnl(v: number | null | undefined): string {
  if (v == null) return '--'
  const prefix = v >= 0 ? '+' : ''
  return `${prefix}$${v.toFixed(2)}`
}

export default function MobileTradeCard({ trade, extraDetails }: MobileTradeCardProps) {
  const [open, setOpen] = useState(false)
  const { t } = useTranslation()

  const isLong = trade.side === 'long'
  const isPnlPositive = trade.pnl != null && trade.pnl >= 0
  const exchange = trade.bot_exchange || trade.exchange || ''

  return (
    <div
      className="border border-white/[0.06] rounded-lg bg-white/[0.02] overflow-hidden"
      onClick={() => setOpen(!open)}
    >
      {/* Row 1: Symbol + Badges | PnL */}
      <div className="flex items-center justify-between px-3 pt-2 pb-1 cursor-pointer">
        <div className="flex items-center gap-1.5 min-w-0">
          <ExchangeIcon exchange={exchange} size={14} />
          <span className="text-white font-semibold text-[13px] truncate">{trade.symbol}</span>
          <span className={`text-[10px] font-medium px-1 py-px rounded ${
            isLong ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
          }`}>
            {isLong ? 'LONG' : 'SHORT'}
          </span>
          {trade.demo_mode && (
            <span className="text-[8px] font-medium px-1 py-px rounded bg-amber-500/10 text-amber-400">DEMO</span>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {trade.status === 'closed' && trade.pnl != null ? (
            <span className={`text-[13px] font-semibold tabular-nums ${isPnlPositive ? 'text-emerald-400' : 'text-red-400'}`}>
              {formatPnl(trade.pnl)}
            </span>
          ) : (
            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
              trade.status === 'open' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-gray-500/10 text-gray-400'
            }`}>
              {t(`trades.${trade.status}`)}
            </span>
          )}
          <ChevronDown size={12} className={`text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} />
        </div>
      </div>

      {/* Row 2: Date + Size with labels */}
      <div className="flex items-center justify-between px-3 pb-2 text-[11px] text-gray-400 gap-3">
        <span>
          <span className="text-gray-500 text-[9px] uppercase tracking-wider mr-1">{t('trades.date')}</span>
          <span className="tabular-nums">{formatDateTime(trade.exit_time || trade.entry_time)}</span>
        </span>
        {trade.size != null && (
          <span className="shrink-0">
            <span className="text-gray-500 text-[9px] uppercase tracking-wider mr-1">{t('portfolio.size')}</span>
            <span className="tabular-nums">{trade.size.toFixed(4)}</span>
          </span>
        )}
      </div>

      {/* Expandable Details */}
      {open && (
        <div className="border-t border-white/[0.04] px-3 py-2 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px]">
          {trade.bot_name && (
            <div>
              <span className="text-gray-400 block text-[9px] uppercase tracking-wider">Bot</span>
              <span className="text-gray-200">{trade.bot_name}</span>
            </div>
          )}
          <div>
            <span className="text-gray-400 block text-[9px] uppercase tracking-wider">Exchange</span>
            <span className="text-gray-200 inline-flex items-center gap-1">
              <ExchangeIcon exchange={exchange} size={14} />
              <span className="capitalize">{exchange}</span>
            </span>
          </div>
          <div>
            <span className="text-gray-400 block text-[9px] uppercase tracking-wider">{t('trades.entryPrice')}</span>
            <span className="text-gray-200 tabular-nums">${trade.entry_price.toLocaleString()}</span>
          </div>
          {trade.exit_price != null && (
            <div>
              <span className="text-gray-400 block text-[9px] uppercase tracking-wider">{t('trades.exitPrice')}</span>
              <span className="text-gray-200 tabular-nums">${trade.exit_price.toLocaleString()}</span>
            </div>
          )}
          {trade.leverage != null && (
            <div>
              <span className="text-gray-400 block text-[9px] uppercase tracking-wider">{t('trades.leverage')}</span>
              <span className="text-gray-200">{trade.leverage}x</span>
            </div>
          )}
          {trade.pnl_percent != null && (
            <div>
              <span className="text-gray-400 block text-[9px] uppercase tracking-wider">PnL %</span>
              <span className={`tabular-nums ${trade.pnl_percent >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {trade.pnl_percent >= 0 ? '+' : ''}{trade.pnl_percent.toFixed(2)}%
              </span>
            </div>
          )}
          {(trade.fees != null && trade.fees > 0) && (
            <div>
              <span className="text-gray-400 block text-[9px] uppercase tracking-wider">{t('trades.fees')}</span>
              <span className="text-gray-200 tabular-nums">${trade.fees.toFixed(2)}</span>
            </div>
          )}
          {trade.confidence != null && trade.confidence > 0 && (
            <div>
              <span className="text-gray-400 block text-[9px] uppercase tracking-wider">{t('bots.confidence')}</span>
              <span className="text-gray-200">{trade.confidence}%</span>
            </div>
          )}
          {trade.exit_reason && (
            <div className="col-span-2">
              <span className="text-gray-400 block text-[9px] uppercase tracking-wider">{t('trades.exitReason')}</span>
              <ExitReasonBadge reason={trade.exit_reason} compact />
            </div>
          )}
          {extraDetails?.map((d, i) => (
            <div key={i}>
              <span className="text-gray-400 block text-[9px] uppercase tracking-wider">{d.label}</span>
              <span className="text-gray-200">{d.value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
