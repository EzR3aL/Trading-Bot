import { useMemo } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { useTranslation } from 'react-i18next'
import type { DailyStats } from '../../types'
import ChartTooltip from './ChartTooltip'

interface Props {
  data: DailyStats[]
}

export default function PnlChart({ data }: Props) {
  const { t } = useTranslation()

  const chartData = useMemo(() => {
    let cumulative = 0
    return data.map((d) => {
      cumulative += d.pnl
      return {
        date: new Date(d.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
        dailyPnl: Number(d.pnl.toFixed(2)),
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
    <ResponsiveContainer width="100%" height={250}>
      <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
        <defs>
          <linearGradient id="pnlGradientPos" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="pnlGradientNeg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
        <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 11 }} tickLine={false} />
        <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} tickLine={false} tickFormatter={(v) => `$${v}`} />
        <Tooltip content={<ChartTooltip />} />
        <ReferenceLine y={0} stroke="#6b7280" strokeDasharray="3 3" />
        <Area
          type="monotone"
          dataKey="cumulativePnl"
          name={t('dashboard.cumulativePnl')}
          stroke="#3b82f6"
          strokeWidth={2}
          fill="url(#pnlGradientPos)"
        />
        <Area
          type="monotone"
          dataKey="dailyPnl"
          name={t('dashboard.dailyPnl')}
          stroke="#22c55e"
          strokeWidth={1.5}
          fill="none"
          strokeDasharray="4 4"
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
