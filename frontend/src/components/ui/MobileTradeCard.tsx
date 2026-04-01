import { memo } from 'react'
import { Share2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ExchangeIcon } from './ExchangeLogo'
import ExitReasonBadge from './ExitReasonBadge'
import MobileCollapsibleCard from './MobileCollapsibleCard'
import { DetailGrid } from './DetailGrid'
import { formatDateTime } from '../../utils/dateUtils'
import SizeValue from './SizeValue'

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
  onShare?: () => void
}

function formatPnl(v: number | null | undefined): string {
  if (v == null) return '--'
  const prefix = v >= 0 ? '+' : ''
  return `${prefix}$${v.toFixed(2)}`
}

function MobileTradeCardInner({ trade, extraDetails, onShare }: MobileTradeCardProps) {
  const { t } = useTranslation()

  const isLong = trade.side === 'long'
  const isPnlPositive = trade.pnl != null && trade.pnl >= 0
  const exchange = trade.bot_exchange || trade.exchange || ''

  const header = (
    <>
      <ExchangeIcon exchange={exchange} size={14} />
      <span className="text-gray-900 dark:text-white font-semibold text-[13px] truncate">{trade.symbol}</span>
      <span className={`text-[10px] font-medium px-1 py-px rounded ${
        isLong ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
      }`}>
        {isLong ? 'LONG' : 'SHORT'}
      </span>
      {trade.demo_mode && (
        <span className="text-[8px] font-medium px-1 py-px rounded bg-amber-500/10 text-amber-400">DEMO</span>
      )}
      <span className="ml-auto text-[10px] text-gray-500 tabular-nums shrink-0">
        {formatDateTime(trade.exit_time || trade.entry_time).split(',')[0]}
      </span>
      {onShare && (
        <button
          onClick={(e) => { e.stopPropagation(); onShare() }}
          className="p-1 text-gray-500 hover:text-white transition-colors rounded shrink-0"
          title={t('bots.shareImage')}
        >
          <Share2 size={13} />
        </button>
      )}
    </>
  )

  const summary = (
    <>
      <span className="tabular-nums truncate">{formatDateTime(trade.exit_time || trade.entry_time)}</span>
      {trade.size != null && (
        <SizeValue size={trade.size} price={trade.entry_price} symbol={trade.symbol} compact />
      )}
      <div className="shrink-0 ml-auto">
        {trade.status === 'closed' && trade.pnl != null ? (
          <span className={`text-[12px] font-semibold tabular-nums ${isPnlPositive ? 'text-emerald-400' : 'text-red-400'}`}>
            {formatPnl(trade.pnl)}
          </span>
        ) : (
          <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
            trade.status === 'open' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-gray-500/10 text-gray-400'
          }`}>
            {t(`trades.${trade.status}`)}
          </span>
        )}
      </div>
    </>
  )

  const details = [
    { label: 'Bot', value: trade.bot_name ?? '', hidden: !trade.bot_name },
    {
      label: 'Exchange',
      value: (
        <span className="inline-flex items-center gap-1">
          <ExchangeIcon exchange={exchange} size={14} />
          <span className="capitalize">{exchange}</span>
        </span>
      ),
    },
    { label: t('trades.entryPrice'), value: <span className="tabular-nums">${trade.entry_price.toLocaleString()}</span> },
    { label: t('trades.exitPrice'), value: <span className="tabular-nums">${trade.exit_price?.toLocaleString()}</span>, hidden: trade.exit_price == null },
    { label: t('trades.leverage'), value: `${trade.leverage}x`, hidden: trade.leverage == null },
    {
      label: 'PnL %',
      value: (
        <span className={`tabular-nums ${(trade.pnl_percent ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
          {(trade.pnl_percent ?? 0) >= 0 ? '+' : ''}{trade.pnl_percent?.toFixed(2)}%
        </span>
      ),
      hidden: trade.pnl_percent == null,
    },
    { label: t('trades.fees'), value: <span className="tabular-nums">${trade.fees?.toFixed(2)}</span>, hidden: !trade.fees || trade.fees <= 0 },
    {
      label: t('trades.exitReason'),
      value: <ExitReasonBadge reason={trade.exit_reason ?? null} compact />,
      hidden: !trade.exit_reason,
      colSpan: 2 as const,
    },
    ...(extraDetails ?? []).map((d) => ({ label: d.label, value: d.value })),
  ]

  return (
    <MobileCollapsibleCard header={header} summary={summary}>
      <DetailGrid items={details} />
    </MobileCollapsibleCard>
  )
}

const MobileTradeCard = memo(MobileTradeCardInner)
export default MobileTradeCard
