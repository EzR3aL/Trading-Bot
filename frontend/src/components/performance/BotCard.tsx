import { useTranslation } from 'react-i18next'
import { ArrowDownRight, ArrowUpRight, Target, Trophy } from 'lucide-react'
import { strategyLabel } from '../../constants/strategies'
import Sparkline from './Sparkline'
import { formatPnl, type BotCompareData } from './types'

interface Props {
  bot: BotCompareData
  color: string
  isSelected: boolean
  isHovered: boolean
  onClick: () => void
  onMouseEnter: () => void
  onMouseLeave: () => void
  index: number
}

/**
 * Compact comparison card for the BotPerformance "cards" view: name, mode badge,
 * total PnL, win-rate / wins-of-total chips, last-trade direction and a sparkline.
 */
export default function BotCard({ bot, color, isSelected, isHovered, onClick, onMouseEnter, onMouseLeave, index }: Props) {
  const { t } = useTranslation()
  const sparkData = bot.series.map(s => s.cumulative_pnl)
  const isPositive = bot.total_pnl >= 0

  return (
    <button
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className={`relative min-w-[200px] flex-1 rounded-xl p-4 pb-3 text-left transition-all duration-300 border cursor-pointer group ${
        isSelected
          ? 'bg-white/[0.08] border-white/20 shadow-lg'
          : isHovered
            ? 'bg-white/[0.05] border-white/10'
            : 'bg-white/[0.02] border-white/5 hover:bg-white/[0.04] hover:border-white/10'
      }`}
      style={{
        animationDelay: `${index * 60}ms`,
        ...(isSelected ? { boxShadow: `0 0 20px ${color}15, 0 0 40px ${color}08` } : {}),
      }}
    >
      {/* Color accent bar */}
      <div
        className="absolute top-0 left-4 right-4 h-[2px] rounded-b-full transition-opacity duration-300"
        style={{
          backgroundColor: color,
          opacity: isSelected ? 1 : isHovered ? 0.6 : 0.2,
        }}
      />

      {/* Header: name + strategy + mode */}
      <div className="flex items-center gap-2 mb-1">
        <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
        <span className="text-white text-sm font-medium truncate">{bot.name}</span>
        <span className="text-[10px] text-gray-400 truncate">{strategyLabel(bot.strategy_type)}</span>
        <span className={`ml-auto text-[9px] px-1.5 py-0.5 rounded-full font-medium flex-shrink-0 ${
          bot.mode === 'live' ? 'badge-live' : 'badge-demo'
        }`}>
          {bot.mode.toUpperCase()}
        </span>
      </div>

      {/* PnL + Arrow */}
      <div className="flex items-center gap-1.5 mb-1">
        <span className={`text-lg font-bold ${isPositive ? 'text-profit' : 'text-loss'}`}>
          {formatPnl(bot.total_pnl)}
        </span>
        {isPositive
          ? <ArrowUpRight size={14} className="text-profit" />
          : <ArrowDownRight size={14} className="text-loss" />
        }
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-3 text-[10px] text-gray-400 mb-3">
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
            className={`flex items-center gap-0.5 ${
              bot.last_direction === 'LONG' ? 'text-emerald-400' : 'text-red-400'
            }`}
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

      {/* Sparkline */}
      <Sparkline data={sparkData} color={color} width={218} height={28} />
    </button>
  )
}
