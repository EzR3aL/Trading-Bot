import { memo, useState } from 'react'
import { Settings, ShieldCheck } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ExchangeIcon } from './ExchangeLogo'
import MobileCollapsibleCard from './MobileCollapsibleCard'
import { DetailGrid } from './DetailGrid'
import SizeValue from './SizeValue'
import EditPositionPanel from './EditPositionPanel'
import api from '../../api/client'

interface Position {
  trade_id?: number
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
  const [editOpen, setEditOpen] = useState(false)
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
      <SizeValue size={pos.size} price={pos.current_price || pos.entry_price} symbol={pos.symbol} />
      <span className={`text-[13px] font-semibold tabular-nums shrink-0 ml-auto ${isPnlPositive ? 'text-emerald-400' : 'text-red-400'}`}>
        {isPnlPositive ? '+' : ''}${pos.unrealized_pnl.toFixed(2)}
      </span>
    </>
  )

  const details = [
    { label: t('portfolio.entryPrice'), value: <span className="tabular-nums">${pos.entry_price.toLocaleString()}</span> },
    { label: t('portfolio.currentPrice'), value: <span className="tabular-nums">${pos.current_price.toLocaleString()}</span> },
    { label: t('portfolio.leverage'), value: `${pos.leverage}x` },
    { label: t('portfolio.size'), value: <SizeValue size={pos.size} price={pos.current_price || pos.entry_price} symbol={pos.symbol} /> },
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
    { label: 'Take Profit', value: <span className="tabular-nums text-emerald-400">${pos.take_profit?.toLocaleString()}</span>, hidden: pos.take_profit == null },
    { label: 'Stop Loss', value: <span className="tabular-nums text-red-400">${pos.stop_loss?.toLocaleString()}</span>, hidden: pos.stop_loss == null },
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

  const handleSave = async (data: { take_profit: number | null; stop_loss: number | null; trailing_stop: unknown }) => {
    if (!pos.trade_id) throw new Error('No trade ID')
    await api.put(`/trades/${pos.trade_id}/tp-sl`, {
      take_profit: data.take_profit,
      stop_loss: data.stop_loss,
    })
    pos.take_profit = data.take_profit
    pos.stop_loss = data.stop_loss
  }

  return (
    <>
      <MobileCollapsibleCard
        header={header}
        summary={summary}
        action={pos.trade_id ? (
          <button
            onClick={(e) => { e.stopPropagation(); setEditOpen(true) }}
            className="p-1 text-gray-500 hover:text-white transition-colors rounded"
            title={t('editPosition.title')}
          >
            <Settings size={13} />
          </button>
        ) : undefined}
      >
        <DetailGrid items={details} />
      </MobileCollapsibleCard>
      {editOpen && pos.trade_id && (
        <EditPositionPanel
          position={{
            trade_id: pos.trade_id,
            symbol: pos.symbol,
            side: pos.side,
            entry_price: pos.entry_price,
            current_price: pos.current_price,
            leverage: pos.leverage,
            exchange: pos.exchange,
            bot_name: pos.bot_name,
            demo_mode: pos.demo_mode,
            take_profit: pos.take_profit,
            stop_loss: pos.stop_loss,
            trailing_stop_active: pos.trailing_stop_active ?? false,
            trailing_stop_price: pos.trailing_stop_price,
            trailing_stop_distance_pct: pos.trailing_stop_distance_pct,
          }}
          onClose={() => setEditOpen(false)}
          onSave={handleSave}
        />
      )}
    </>
  )
}

const MobilePositionCard = memo(MobilePositionCardInner)
export default MobilePositionCard
