import { useTranslation } from 'react-i18next'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ArrowDownRight, ArrowUpRight, Target, Trophy } from 'lucide-react'
import { strategyLabel } from '../../constants/strategies'
import { formatChartCurrency, formatChartDate } from '../../utils/dateUtils'
import { formatPnl, type BotCompareData } from './types'

interface Props {
  bot: BotCompareData
  color: string
  yDomain: [number, number]
  chartGridColor: string
  chartTickColor: string
  isSelected: boolean
  onClick: () => void
}

/**
 * Tile used in the BotPerformance "small multiples" grid view: header row plus
 * a per-bot AreaChart sharing the same yDomain for fair comparison.
 */
export default function SmallMultipleCard({ bot, color, yDomain, chartGridColor, chartTickColor, isSelected, onClick }: Props) {
  const { t } = useTranslation()
  const isPositive = bot.total_pnl >= 0
  const chartData = bot.series.map(s => ({
    date: formatChartDate(s.date),
    value: s.cumulative_pnl,
  }))

  const gradientId = `sm-grad-${bot.bot_id}`

  return (
    <button
      onClick={onClick}
      className={`glass-card rounded-xl p-4 text-left transition-all duration-300 cursor-pointer w-full ${
        isSelected
          ? 'ring-1 ring-white/20 bg-white/[0.06]'
          : 'hover:bg-white/[0.03]'
      }`}
      style={isSelected ? { boxShadow: `0 0 24px ${color}12` } : {}}
    >
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 mb-1">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
          <span className="text-white text-sm font-medium truncate">{bot.name}</span>
          <span className="text-[10px] text-gray-400 truncate">{strategyLabel(bot.strategy_type)}</span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-medium flex-shrink-0 ${
            bot.mode === 'live' ? 'badge-live' : 'badge-demo'
          }`}>
            {bot.mode.toUpperCase()}
          </span>
        </div>
        <div className={`flex items-center gap-1 text-sm font-bold ${isPositive ? 'text-profit' : 'text-loss'}`}>
          {formatPnl(bot.total_pnl)}
          {isPositive ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
        </div>
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-4 text-[10px] text-gray-400 mb-3">
        <span className="flex items-center gap-0.5 text-amber-400" title={t('performance.tooltipWinRate', { rate: bot.win_rate })}>
          <Trophy size={9} />
          <span className={bot.win_rate >= 60 ? 'text-profit' : bot.win_rate >= 40 ? 'text-yellow-400' : 'text-loss'}>{bot.win_rate}%</span>
        </span>
        <span className="flex items-center gap-0.5 text-white" title={t('performance.tooltipTrades', { wins: bot.wins, total: bot.total_trades })}>
          <Target size={9} />
          {bot.wins}/{bot.total_trades}
        </span>
        {bot.last_direction && (
          <span
            className={`flex items-center gap-0.5 ${bot.last_direction === 'LONG' ? 'text-emerald-400' : 'text-red-400'}`}
            title={t('performance.tooltipLastTrade', { direction: bot.last_direction })}
          >
            <span className="text-gray-500">{t('performance.lastTrade')}:</span> {bot.last_direction}
            {bot.last_direction === 'LONG'
              ? <ArrowUpRight size={9} />
              : <ArrowDownRight size={9} />
            }
          </span>
        )}
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={120}>
        <AreaChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.25} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={chartGridColor} vertical={false} />
          <XAxis dataKey="date" tick={{ fill: chartTickColor, fontSize: 9 }} tickLine={false} interval="preserveStartEnd" />
          <YAxis domain={yDomain} width={45} tick={{ fill: chartTickColor, fontSize: 9 }} tickLine={false} tickFormatter={formatChartCurrency} />
          <ReferenceLine y={0} stroke={chartTickColor} strokeDasharray="2 2" strokeOpacity={0.5} />
          <Tooltip
            contentStyle={{
              backgroundColor: 'rgba(17, 24, 39, 0.95)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 8,
              fontSize: 11,
            }}
            formatter={(value: number) => [formatPnl(value), 'PnL']}
            labelStyle={{ color: '#9ca3af', fontSize: 10 }}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={2}
            fill={`url(#${gradientId})`}
            dot={false}
            activeDot={{ r: 3, fill: color, stroke: '#fff', strokeWidth: 1 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </button>
  )
}
