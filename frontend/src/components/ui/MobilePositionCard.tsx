import { memo } from 'react'
import { ShieldCheck } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ExchangeIcon } from './ExchangeLogo'
import MobileCollapsibleCard from './MobileCollapsibleCard'
import { DetailGrid } from './DetailGrid'

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
  demo_mode?: boolean
  take_profit?: number | null
  stop_loss?: number | null
}

function MobilePositionCardInner({ pos }: { pos: Position }) {
  const { t } = useTranslation()
  const isLong = pos.side.toLowerCase() === 'long'
  const isPnlPositive = pos.unrealized_pnl >= 0

  const header = (
    <>
      <ExchangeIcon exchange={pos.exchange} size={14} />
      <span className="text-gray-900 dark:text-white font-semibold text-[13px] truncate">{pos.symbol}</span>
      <span className={`text-[10px] font-medium px-1 py-px rounded ${
        isLong ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
      }`}>
        {pos.side.toUpperCase()}
      </span>
      {pos.demo_mode && (
        <span className="text-[8px] font-medium px-1 py-px rounded bg-amber-500/10 text-amber-400">DEMO</span>
      )}
      {pos.trailing_stop_active && (
        <ShieldCheck size={10} className="text-emerald-400" />
      )}
    </>
  )

  const summary = (
    <>
      <span>
        <span className="text-gray-500 text-[9px] uppercase tracking-wider mr-1">{t('portfolio.size')}</span>
        {pos.size.toFixed(4)} {pos.symbol.replace('USDT', '')}
      </span>
      <div className="shrink-0 flex items-center gap-1.5 ml-auto">
        <span className={`text-[13px] font-semibold tabular-nums ${isPnlPositive ? 'text-emerald-400' : 'text-red-400'}`}>
          {isPnlPositive ? '+' : ''}${pos.unrealized_pnl.toFixed(2)}
        </span>
      </div>
    </>
  )

  const details = [
    { label: t('portfolio.entryPrice'), value: <span className="tabular-nums">${pos.entry_price.toLocaleString()}</span> },
    { label: t('portfolio.currentPrice'), value: <span className="tabular-nums">${pos.current_price.toLocaleString()}</span> },
    { label: t('portfolio.leverage'), value: `${pos.leverage}x` },
    { label: t('portfolio.size'), value: <span className="tabular-nums">{pos.size.toFixed(4)}</span> },
    { label: t('portfolio.margin', 'Margin'), value: <span className="tabular-nums">${pos.margin?.toFixed(2)}</span>, hidden: !pos.margin || pos.margin <= 0 },
    {
      label: t('bots.trailingStop'),
      value: (
        <span className="text-emerald-400 tabular-nums inline-flex items-center gap-1">
          ${pos.trailing_stop_price?.toLocaleString()}
          {pos.trailing_stop_distance_pct != null && (
            <span className="text-gray-400">({pos.trailing_stop_distance_pct.toFixed(2)}%)</span>
          )}
          {pos.can_close_at_loss === false && (
            <span title={t('bots.trailingStopProtecting')}>
              <ShieldCheck size={12} className="text-emerald-400" />
            </span>
          )}
        </span>
      ),
      hidden: !pos.trailing_stop_active || pos.trailing_stop_price == null,
    },
    { label: 'Bot', value: pos.bot_name ?? '', hidden: !pos.bot_name },
    {
      label: 'Exchange',
      value: (
        <span className="inline-flex items-center gap-1">
          <ExchangeIcon exchange={pos.exchange} size={14} />
          <span className="capitalize">{pos.exchange}</span>
        </span>
      ),
    },
  ]

  return (
    <MobileCollapsibleCard header={header} summary={summary}>
      <DetailGrid items={details} />
    </MobileCollapsibleCard>
  )
}

const MobilePositionCard = memo(MobilePositionCardInner)
export default MobilePositionCard
