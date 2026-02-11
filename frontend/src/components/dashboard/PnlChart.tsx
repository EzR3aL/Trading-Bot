import { useMemo, useState } from 'react'
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Cell,
} from 'recharts'
import { useTranslation } from 'react-i18next'
import { useThemeStore } from '../../stores/themeStore'
import type { DailyStats } from '../../types'
import { Eye, EyeOff } from 'lucide-react'

const PNL_POS = '#22c55e'
const PNL_NEG = '#ef4444'
const FEES_COLOR = '#f59e0b'
const FUNDING_COLOR = '#8b5cf6'
const CUMULATIVE_COLOR = '#3b82f6'

interface Props {
  data: DailyStats[]
}

function PnlTooltip({ active, payload, label }: {
  active?: boolean
  payload?: Array<{ name: string; value: number; dataKey: string }>
  label?: string
}) {
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
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-3 shadow-lg min-w-[180px]">
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
          <span className="text-gray-400">Netto</span>
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

export default function PnlChart({ data }: Props) {
  const { t } = useTranslation()
  const theme = useThemeStore((s) => s.theme)
  const gridColor = theme === 'light' ? '#e2e8f0' : '#374151'
  const tickColor = theme === 'light' ? '#64748b' : '#9ca3af'
  const refColor = theme === 'light' ? '#cbd5e1' : '#6b7280'
  const [showCosts, setShowCosts] = useState(true)

  const chartData = useMemo(() => {
    let cumulative = 0
    return data.map((d) => {
      cumulative += d.pnl
      return {
        date: new Date(d.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
        dailyPnl: Number(d.pnl.toFixed(2)),
        fees: Number(Math.abs(d.fees).toFixed(2)),
        funding: Number(Math.abs(d.funding).toFixed(2)),
        cumulativePnl: Number(cumulative.toFixed(2)),
      }
    })
  }, [data])

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-[250px] text-gray-500 text-sm">
        {t('dashboard.noData')}
      </div>
    )
  }

  return (
    <div className="relative">
      <button
        onClick={() => setShowCosts(!showCosts)}
        className={`absolute -top-9 right-0 z-10 flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-all duration-200 border ${
          showCosts
            ? 'bg-white/5 border-white/10 text-gray-300 hover:bg-white/10'
            : 'bg-white/[0.02] border-white/5 text-gray-500 hover:text-gray-400'
        }`}
      >
        {showCosts ? <Eye size={13} /> : <EyeOff size={13} />}
        {t('dashboard.fees')} & {t('dashboard.funding')}
      </button>
      <ResponsiveContainer width="100%" height={250}>
        <ComposedChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
          <XAxis dataKey="date" tick={{ fill: tickColor, fontSize: 11 }} tickLine={false} />
          <YAxis tick={{ fill: tickColor, fontSize: 11 }} tickLine={false} tickFormatter={(v) => `$${v}`} />
          <Tooltip content={<PnlTooltip />} />
          <ReferenceLine y={0} stroke={refColor} strokeDasharray="3 3" />
          <Bar
            dataKey="dailyPnl"
            name={t('dashboard.dailyPnl')}
            stackId="pnl"
            maxBarSize={40}
          >
            {chartData.map((entry, index) => (
              <Cell
                key={index}
                fill={entry.dailyPnl >= 0 ? PNL_POS : PNL_NEG}
                fillOpacity={0.75}
              />
            ))}
          </Bar>
          {showCosts && (
            <Bar
              dataKey="fees"
              name={t('dashboard.fees')}
              stackId="pnl"
              fill={FEES_COLOR}
              fillOpacity={0.8}
              maxBarSize={40}
            />
          )}
          {showCosts && (
            <Bar
              dataKey="funding"
              name={t('dashboard.funding')}
              stackId="pnl"
              fill={FUNDING_COLOR}
              fillOpacity={0.8}
              maxBarSize={40}
              radius={[3, 3, 0, 0]}
            />
          )}
          <Line
            type="monotone"
            dataKey="cumulativePnl"
            name={t('dashboard.cumulativePnl')}
            stroke={CUMULATIVE_COLOR}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: CUMULATIVE_COLOR, stroke: '#fff', strokeWidth: 1 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
