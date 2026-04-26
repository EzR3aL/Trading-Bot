import { CUMULATIVE_COLOR, FEES_COLOR, FUNDING_COLOR, PNL_NEG, PNL_POS } from './types'

interface Props {
  active?: boolean
  payload?: Array<{ name: string; value: number; dataKey: string }>
  label?: string
  t: (key: string) => string
}

/**
 * Custom recharts tooltip for the bot detail PnL chart that shows daily PnL,
 * fees, funding, the net (PnL minus costs), and the cumulative line value.
 */
export default function BotPnlTooltip({ active, payload, label, t }: Props) {
  if (!active || !payload?.length) return null

  const pnlEntry = payload.find(e => e.dataKey === 'dailyPnl')
  const feesEntry = payload.find(e => e.dataKey === 'fees')
  const fundingEntry = payload.find(e => e.dataKey === 'funding')
  const cumEntry = payload.find(e => e.dataKey === 'cumulativePnl')

  const pnl = pnlEntry?.value ?? 0
  const fees = feesEntry?.value ?? 0
  const funding = fundingEntry?.value ?? 0
  const total = pnl - fees - funding

  return (
    <div className="bg-[#141a2a]/95 border border-white/10 rounded-xl p-3 shadow-lg backdrop-blur-xl min-w-[180px]">
      <p className="text-gray-400 text-xs mb-2 font-medium">{label}</p>
      {pnlEntry && (
        <div className="flex justify-between text-sm mb-0.5">
          <span style={{ color: pnl >= 0 ? PNL_POS : PNL_NEG }}>{pnlEntry.name}</span>
          <span className="font-medium ml-4" style={{ color: pnl >= 0 ? PNL_POS : PNL_NEG }}>${pnl.toFixed(2)}</span>
        </div>
      )}
      {feesEntry && fees > 0 && (
        <div className="flex justify-between text-sm mb-0.5">
          <span style={{ color: FEES_COLOR }}>{feesEntry.name}</span>
          <span className="font-medium ml-4" style={{ color: FEES_COLOR }}>-${fees.toFixed(2)}</span>
        </div>
      )}
      {fundingEntry && funding > 0 && (
        <div className="flex justify-between text-sm mb-0.5">
          <span style={{ color: FUNDING_COLOR }}>{fundingEntry.name}</span>
          <span className="font-medium ml-4" style={{ color: FUNDING_COLOR }}>-${funding.toFixed(2)}</span>
        </div>
      )}
      {(feesEntry || fundingEntry) && (fees > 0 || funding > 0) && (
        <div className="flex justify-between text-sm mt-1.5 pt-1.5 border-t border-white/10">
          <span className="text-gray-400">{t('common.net')}</span>
          <span className="font-bold ml-4" style={{ color: total >= 0 ? PNL_POS : PNL_NEG }}>${total.toFixed(2)}</span>
        </div>
      )}
      {cumEntry && (
        <div className="flex justify-between text-sm mt-1.5 pt-1.5 border-t border-white/10">
          <span style={{ color: CUMULATIVE_COLOR }}>{cumEntry.name}</span>
          <span className="font-medium ml-4" style={{ color: cumEntry.value >= 0 ? PNL_POS : PNL_NEG }}>${cumEntry.value.toFixed(2)}</span>
        </div>
      )}
    </div>
  )
}
