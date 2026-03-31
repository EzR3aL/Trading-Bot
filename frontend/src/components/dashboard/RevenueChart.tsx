import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { useTranslation } from 'react-i18next'
import { formatChartDate, formatChartCurrency } from '../../utils/dateUtils'
import { useThemeStore } from '../../stores/themeStore'
import type { DailyStats } from '../../types'
import ChartTooltip from './ChartTooltip'

interface Props {
  data: DailyStats[]
}

export default function RevenueChart({ data }: Props) {
  const { t } = useTranslation()
  const theme = useThemeStore((s) => s.theme)
  const isLight = theme === 'light'
  const gridColor = isLight ? '#e2e8f0' : '#374151'
  const tickColor = isLight ? '#64748b' : '#9ca3af'

  const chartData = data.map((d) => ({
    date: formatChartDate(d.date),
    builderFees: Number((d.builder_fees || 0).toFixed(4)),
  }))

  const hasData = chartData.some(d => d.builderFees > 0)

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
        <XAxis dataKey="date" tick={{ fill: tickColor, fontSize: 10 }} tickLine={false} />
        <YAxis width={45} tick={{ fill: tickColor, fontSize: 10 }} tickLine={false} tickFormatter={formatChartCurrency} />
        <Tooltip content={<ChartTooltip />} />
        <Legend
          wrapperStyle={{ fontSize: '12px', color: isLight ? '#64748b' : '#9ca3af' }}
          formatter={(value) => <span className={isLight ? 'text-gray-500' : 'text-gray-400'}>{value}</span>}
        />
        <Bar
          dataKey="builderFees"
          name={t('dashboard.builderFees')}
          fill={isLight ? '#059669' : '#10b981'}
          radius={[2, 2, 0, 0]}
        />
      </BarChart>
    </ResponsiveContainer>
  )
}
