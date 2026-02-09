import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import { useTranslation } from 'react-i18next'
import { useThemeStore } from '../../stores/themeStore'

interface Props {
  wins: number
  losses: number
  winRate: number
}

const COLORS = { wins: '#22c55e', losses: '#ef4444' }

export default function WinLossChart({ wins, losses, winRate }: Props) {
  const { t } = useTranslation()
  const theme = useThemeStore((s) => s.theme)
  const total = wins + losses

  if (total === 0) {
    return (
      <div className="flex items-center justify-center h-[250px] text-gray-500 text-sm">
        {t('dashboard.noData')}
      </div>
    )
  }

  const data = [
    { name: t('dashboard.winLoss').split(' / ')[0], value: wins },
    { name: t('dashboard.winLoss').split(' / ')[1], value: losses },
  ]

  return (
    <div className="relative">
      <ResponsiveContainer width="100%" height={250}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={65}
            outerRadius={90}
            dataKey="value"
            strokeWidth={0}
          >
            <Cell fill={COLORS.wins} />
            <Cell fill={COLORS.losses} />
          </Pie>
          <Tooltip
            contentStyle={{
              backgroundColor: theme === 'light' ? '#ffffff' : '#1f2937',
              border: `1px solid ${theme === 'light' ? '#e2e8f0' : '#374151'}`,
              borderRadius: '8px',
              color: theme === 'light' ? '#334155' : '#e5e7eb',
              fontSize: '13px',
            }}
            formatter={(value: number, name: string) => [`${value} trades`, name]}
          />
        </PieChart>
      </ResponsiveContainer>
      {/* Center label */}
      <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
        <span className="text-2xl font-bold text-white">{winRate.toFixed(0)}%</span>
        <span className="text-xs text-gray-400">{total} trades</span>
      </div>
      {/* Legend */}
      <div className="flex justify-center gap-6 -mt-2">
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: COLORS.wins }} />
          <span className="text-xs text-gray-400">{wins}W</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: COLORS.losses }} />
          <span className="text-xs text-gray-400">{losses}L</span>
        </div>
      </div>
    </div>
  )
}
