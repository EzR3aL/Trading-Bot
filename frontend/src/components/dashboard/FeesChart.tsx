import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { useTranslation } from 'react-i18next'
import { useThemeStore } from '../../stores/themeStore'
import type { DailyStats } from '../../types'

interface Props {
  data: DailyStats[]
}

const FEES_COLOR = '#f59e0b'
const FUNDING_COLOR = '#8b5cf6'

function FeesTooltip({ active, payload, label }: {
  active?: boolean; payload?: Array<{ name: string; value: number; dataKey: string }>; label?: string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-3 shadow-lg">
      <p className="text-gray-400 text-xs mb-1">{label}</p>
      {payload.map((entry, i) => (
        <p key={i} className="text-sm font-medium" style={{ color: entry.dataKey === 'fees' ? FEES_COLOR : FUNDING_COLOR }}>
          {entry.name}: ${entry.value.toFixed(2)}
        </p>
      ))}
    </div>
  )
}

export default function FeesChart({ data }: Props) {
  const { t } = useTranslation()
  const theme = useThemeStore((s) => s.theme)
  const gridColor = theme === 'light' ? '#e2e8f0' : '#374151'
  const tickColor = theme === 'light' ? '#64748b' : '#9ca3af'

  const chartData = data.map((d) => ({
    date: new Date(d.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    fees: Number(Math.abs(d.fees).toFixed(2)),
    funding: Number(Math.abs(d.funding).toFixed(2)),
  }))

  const hasData = chartData.some(d => d.fees > 0 || d.funding > 0)

  if (chartData.length === 0 || !hasData) {
    return (
      <div className="flex items-center justify-center h-[200px] text-gray-500 text-sm">
        {t('dashboard.noData')}
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
        <defs>
          <linearGradient id="feesGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={FEES_COLOR} stopOpacity={0.4} />
            <stop offset="95%" stopColor={FEES_COLOR} stopOpacity={0.05} />
          </linearGradient>
          <linearGradient id="fundingGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={FUNDING_COLOR} stopOpacity={0.4} />
            <stop offset="95%" stopColor={FUNDING_COLOR} stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke={gridColor} vertical={false} />
        <XAxis dataKey="date" tick={{ fill: tickColor, fontSize: 11 }} tickLine={false} />
        <YAxis tick={{ fill: tickColor, fontSize: 11 }} tickLine={false} tickFormatter={(v) => `$${v}`} />
        <Tooltip content={<FeesTooltip />} />
        <Legend
          wrapperStyle={{ fontSize: '12px', color: '#9ca3af' }}
          formatter={(value) => <span className="text-gray-400">{value}</span>}
        />
        <Area
          type="monotone"
          dataKey="fees"
          name={t('dashboard.fees')}
          stroke={FEES_COLOR}
          strokeWidth={2}
          fill="url(#feesGrad)"
          stackId="costs"
        />
        <Area
          type="monotone"
          dataKey="funding"
          name={t('dashboard.funding')}
          stroke={FUNDING_COLOR}
          strokeWidth={2}
          fill="url(#fundingGrad)"
          stackId="costs"
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
