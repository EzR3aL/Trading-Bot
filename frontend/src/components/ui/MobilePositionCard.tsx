import { useState } from 'react'
import { ChevronDown, ShieldCheck } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ExchangeIcon } from './ExchangeLogo'

interface Position {
  exchange: string
  symbol: string
  side: string
  size: number
  entry_price: number
  current_price: number
  unrealized_pnl: number
  leverage: number
  margin?: number | null
  liquidation_price?: number | null
  trailing_stop_active?: boolean
  trailing_stop_price?: number | null
  trailing_stop_distance_pct?: number | null
  can_close_at_loss?: boolean | null
  bot_name?: string | null
  take_profit?: number | null
  stop_loss?: number | null
}

export default function MobilePositionCard({ pos }: { pos: Position }) {
  const [open, setOpen] = useState(false)
  const { t } = useTranslation()
  const isLong = pos.side.toLowerCase() === 'long'
  const isPnlPositive = pos.unrealized_pnl >= 0

  return (
    <div
      className="border border-white/[0.06] rounded-lg bg-white/[0.02] overflow-hidden"
      onClick={() => setOpen(!open)}
    >
      {/* Header: Symbol + Side | PnL + Chevron */}
      <div className="flex items-center justify-between px-3 py-2 cursor-pointer">
        <div className="flex items-center gap-1.5 min-w-0">
          <ExchangeIcon exchange={pos.exchange} size={14} />
          <span className="text-white font-semibold text-[13px] truncate">{pos.symbol}</span>
          <span className={`text-[10px] font-medium px-1 py-px rounded ${
            isLong ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
          }`}>
            {pos.side.toUpperCase()}
          </span>
          {pos.trailing_stop_active && (
            <ShieldCheck size={10} className="text-emerald-400" />
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className={`text-[13px] font-semibold tabular-nums ${isPnlPositive ? 'text-emerald-400' : 'text-red-400'}`}>
            {isPnlPositive ? '+' : ''}${pos.unrealized_pnl.toFixed(2)}
          </span>
          <ChevronDown size={12} className={`text-gray-500 transition-transform ${open ? 'rotate-180' : ''}`} />
        </div>
      </div>

      {/* Sub Row: Size + Leverage + Price */}
      <div className="flex items-center justify-between px-3 pb-2 text-[11px] text-gray-500">
        <span>{pos.size.toFixed(4)} {pos.symbol.replace('USDT', '')}</span>
        <span>{pos.leverage}x</span>
        <span className="tabular-nums">${pos.current_price.toLocaleString()}</span>
      </div>

      {/* Expandable Details */}
      {open && (
        <div className="border-t border-white/[0.04] px-3 py-2 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px]">
          <div>
            <span className="text-gray-500 block text-[9px] uppercase tracking-wider">{t('portfolio.entryPrice')}</span>
            <span className="text-gray-300 tabular-nums">${pos.entry_price.toLocaleString()}</span>
          </div>
          <div>
            <span className="text-gray-500 block text-[9px] uppercase tracking-wider">{t('portfolio.currentPrice')}</span>
            <span className="text-gray-300 tabular-nums">${pos.current_price.toLocaleString()}</span>
          </div>
          <div>
            <span className="text-gray-500 block text-[9px] uppercase tracking-wider">{t('portfolio.leverage')}</span>
            <span className="text-gray-300">{pos.leverage}x</span>
          </div>
          <div>
            <span className="text-gray-500 block text-[9px] uppercase tracking-wider">{t('portfolio.size')}</span>
            <span className="text-gray-300 tabular-nums">{pos.size.toFixed(4)}</span>
          </div>
          {pos.margin != null && pos.margin > 0 && (
            <div>
              <span className="text-gray-500 block text-[9px] uppercase tracking-wider">{t('portfolio.margin', 'Margin')}</span>
              <span className="text-gray-300 tabular-nums">${pos.margin.toFixed(2)}</span>
            </div>
          )}
          {pos.trailing_stop_active && pos.trailing_stop_price != null && (
            <div>
              <span className="text-gray-500 block text-[9px] uppercase tracking-wider">{t('bots.trailingStop')}</span>
              <span className="text-emerald-400 tabular-nums">
                ${pos.trailing_stop_price.toLocaleString()}
                {pos.trailing_stop_distance_pct != null && (
                  <span className="text-gray-400 ml-1">({pos.trailing_stop_distance_pct.toFixed(2)}%)</span>
                )}
              </span>
            </div>
          )}
          {pos.bot_name && (
            <div>
              <span className="text-gray-500 block text-[9px] uppercase tracking-wider">Bot</span>
              <span className="text-gray-300">{pos.bot_name}</span>
            </div>
          )}
          <div>
            <span className="text-gray-500 block text-[9px] uppercase tracking-wider">Exchange</span>
            <span className="text-gray-300 inline-flex items-center gap-1">
              <ExchangeIcon exchange={pos.exchange} size={14} />
              <span className="capitalize">{pos.exchange}</span>
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
