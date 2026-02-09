import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { useTranslation } from 'react-i18next'
import { useThemeStore } from '../../stores/themeStore'
import type { DailyStats } from '../../types'
import ChartTooltip from './ChartTooltip'

interface Props {
  data: DailyStats[]
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
      <BarChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
        <XAxis dataKey="date" tick={{ fill: tickColor, fontSize: 11 }} tickLine={false} />
        <YAxis tick={{ fill: tickColor, fontSize: 11 }} tickLine={false} tickFormatter={(v) => `$${v}`} />
        <Tooltip content={<ChartTooltip />} />
        <Legend
          wrapperStyle={{ fontSize: '12px', color: '#9ca3af' }}
          formatter={(value) => <span className="text-gray-400">{value}</span>}
        />
        <Bar dataKey="fees" name={t('dashboard.fees')} fill="#f59e0b" radius={[2, 2, 0, 0]} stackId="costs" />
        <Bar dataKey="funding" name={t('dashboard.funding')} fill="#8b5cf6" radius={[2, 2, 0, 0]} stackId="costs" />
      </BarChart>
    </ResponsiveContainer>
  )
}
