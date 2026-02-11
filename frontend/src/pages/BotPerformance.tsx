import { useEffect, useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ComposedChart, Bar, Cell, Line,
  AreaChart, Area,
} from 'recharts'
import api from '../api/client'
import { useFilterStore } from '../stores/filterStore'
import { useThemeStore } from '../stores/themeStore'
import { SkeletonChart, SkeletonTable } from '../components/ui/Skeleton'
import PnlCell from '../components/ui/PnlCell'
import { Eye, EyeOff, ArrowUpRight, ArrowDownRight, Trophy, Target, LayoutGrid, BarChart3 } from 'lucide-react'

/* ── Colors ──────────────────────────────────────────────── */

const BOT_COLORS = [
  '#00e676', '#3b82f6', '#f59e0b', '#ff5252', '#a855f7',
  '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#6366f1',
]

const PNL_POS = '#22c55e'
const PNL_NEG = '#ef4444'
const FEES_COLOR = '#f59e0b'
const FUNDING_COLOR = '#8b5cf6'
const CUMULATIVE_COLOR = '#3b82f6'

/* ── Types ───────────────────────────────────────────────── */

interface BotCompareData {
  bot_id: number
  name: string
  strategy_type: string
  exchange_type: string
  mode: string
  total_trades: number
  total_pnl: number
  total_fees: number
  total_funding: number
  win_rate: number
  wins: number
  last_direction: string | null
  last_confidence: number | null
  series: { date: string; cumulative_pnl: number }[]
}

interface BotDetailStats {
  bot_id: number
  bot_name: string
  summary: {
    total_trades: number
    wins: number
    losses: number
    win_rate: number
    total_pnl: number
    total_fees: number
    total_funding: number
    avg_pnl: number
    best_trade: number
    worst_trade: number
  }
  daily_series: { date: string; pnl: number; cumulative_pnl: number; trades: number; wins: number; fees: number; funding: number }[]
  recent_trades: {
    id: number; symbol: string; side: string; entry_price: number; exit_price: number | null
    pnl: number; pnl_percent: number; confidence: number; status: string
    fees: number; funding_paid: number
    demo_mode: boolean; entry_time: string | null; exit_time: string | null; exit_reason: string | null
  }[]
}

function formatPnl(value: number): string {
  const prefix = value >= 0 ? '+' : ''
  return `${prefix}$${value.toFixed(2)}`
}

/* ── Sparkline (SVG) ─────────────────────────────────────── */

function Sparkline({ data, color, width = 80, height = 32 }: {
  data: number[]; color: string; width?: number; height?: number
}) {
  if (data.length < 2) return <div style={{ width, height }} />

  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const pad = 2

  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (width - pad * 2)
    const y = pad + (1 - (v - min) / range) * (height - pad * 2)
    return `${x},${y}`
  })

  const linePath = points.join(' ')
  const areaPath = `${points.join(' ')} ${width - pad},${height} ${pad},${height}`

  const gradientId = `spark-${color.replace('#', '')}`

  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="w-full overflow-visible" style={{ height }}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.3} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <polygon points={areaPath} fill={`url(#${gradientId})`} />
      <polyline points={linePath} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/* ── Bot Card ────────────────────────────────────────────── */

function BotCard({ bot, color, isSelected, isHovered, onClick, onMouseEnter, onMouseLeave, index }: {
  bot: BotCompareData
  color: string
  isSelected: boolean
  isHovered: boolean
  onClick: () => void
  onMouseEnter: () => void
  onMouseLeave: () => void
  index: number
}) {
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

      {/* Header: name + mode */}
      <div className="flex items-center gap-2 mb-2.5">
        <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
        <span className="text-white text-sm font-medium truncate">{bot.name}</span>
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
      <div className="flex items-center gap-3 text-[10px] text-gray-500 mb-3">
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

/* ── Small Multiple Card ─────────────────────────────────── */

function SmallMultipleCard({ bot, color, yDomain, chartGridColor, chartTickColor, isSelected, onClick }: {
  bot: BotCompareData
  color: string
  yDomain: [number, number]
  chartGridColor: string
  chartTickColor: string
  isSelected: boolean
  onClick: () => void
}) {
  const { t } = useTranslation()
  const isPositive = bot.total_pnl >= 0
  const chartData = bot.series.map(s => ({
    date: new Date(s.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
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
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
          <span className="text-white text-sm font-medium truncate">{bot.name}</span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-medium ${
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
      <div className="flex items-center gap-4 text-[10px] text-gray-500 mb-3">
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
          <YAxis domain={yDomain} tick={{ fill: chartTickColor, fontSize: 9 }} tickLine={false} tickFormatter={(v) => `$${v}`} />
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

/* ── Bot Detail PnL Tooltip ──────────────────────────────── */

function BotPnlTooltip({ active, payload, label }: {
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

/* ── Stat Card ───────────────────────────────────────────── */

function StatCard({ label, value, color, isPositive }: {
  label: string; value: string; color?: string; isPositive?: boolean | null
}) {
  return (
    <div className="bg-white/5 rounded-xl p-3 border border-white/5 text-center">
      <div className="text-[10px] text-gray-500 mb-1 uppercase tracking-wider font-medium">{label}</div>
      <div className={`text-lg font-bold flex items-center justify-center gap-1 ${color || 'text-white'}`}>
        {value}
        {isPositive === true && <ArrowUpRight size={16} className="text-profit" />}
        {isPositive === false && <ArrowDownRight size={16} className="text-loss" />}
      </div>
    </div>
  )
}

/* ── Main Component ──────────────────────────────────────── */

export default function BotPerformance() {
  const { t } = useTranslation()
  const { demoFilter } = useFilterStore()
  const theme = useThemeStore((s) => s.theme)
  const chartGridColor = theme === 'light' ? '#e2e8f0' : '#374151'
  const chartTickColor = theme === 'light' ? '#64748b' : '#9ca3af'
  const refColor = theme === 'light' ? '#cbd5e1' : '#6b7280'
  const [days, setDays] = useState(30)
  const [compareData, setCompareData] = useState<BotCompareData[]>([])
  const [selectedBot, setSelectedBot] = useState<number | null>(null)
  const [hoveredBot, setHoveredBot] = useState<number | null>(null)
  const [botDetail, setBotDetail] = useState<BotDetailStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [detailError, setDetailError] = useState('')
  const [showCosts, setShowCosts] = useState(true)
  const [viewMode, setViewMode] = useState<'cards' | 'grid'>('cards')

  const demoParam = demoFilter === 'demo' ? '&demo_mode=true' : demoFilter === 'live' ? '&demo_mode=false' : ''

  useEffect(() => {
    loadCompareData()
  }, [days, demoFilter])

  useEffect(() => {
    if (selectedBot) loadBotDetail(selectedBot)
    else setBotDetail(null)
  }, [selectedBot, days, demoFilter])

  const loadCompareData = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.get(`/bots/compare/performance?days=${days}${demoParam}`)
      setCompareData(res.data.bots || [])
    } catch {
      setError(t('performance.loadError'))
    }
    setLoading(false)
  }

  const loadBotDetail = async (botId: number) => {
    setDetailError('')
    try {
      const res = await api.get(`/bots/${botId}/statistics?days=${days}${demoParam}`)
      setBotDetail(res.data)
    } catch {
      setDetailError(t('performance.detailError'))
    }
  }

  // Build bot detail chart data
  const botChartData = useMemo(() => {
    if (!botDetail) return []
    let cumulative = 0
    return botDetail.daily_series.map((d) => {
      cumulative += d.pnl
      return {
        date: new Date(d.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
        dailyPnl: Number(d.pnl.toFixed(2)),
        fees: Number(Math.abs(d.fees || 0).toFixed(2)),
        funding: Number(Math.abs(d.funding || 0).toFixed(2)),
        cumulativePnl: Number(cumulative.toFixed(2)),
      }
    })
  }, [botDetail])

  // Shared Y-axis domain for Small Multiples (fair comparison)
  const sharedYDomain = useMemo<[number, number]>(() => {
    const allValues = compareData.flatMap(b => b.series.map(s => s.cumulative_pnl))
    if (allValues.length === 0) return [-10, 10]
    const min = Math.min(...allValues, 0)
    const max = Math.max(...allValues, 0)
    const pad = Math.max(Math.abs(max - min) * 0.1, 5)
    return [Math.floor(min - pad), Math.ceil(max + pad)]
  }, [compareData])

  const handleCardClick = (botId: number) => {
    setSelectedBot(selectedBot === botId ? null : botId)
  }

  return (
    <div className="animate-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white tracking-tight">{t('performance.title')}</h1>
        <div className="flex items-center gap-3">
          {/* View Toggle */}
          <div className="flex gap-0.5 bg-white/5 rounded-lg p-0.5 border border-white/5">
            <button
              onClick={() => setViewMode('cards')}
              aria-label="Cards view"
              className={`p-1.5 rounded-md transition-all duration-200 ${
                viewMode === 'cards'
                  ? 'bg-white/10 text-white'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              <BarChart3 size={14} />
            </button>
            <button
              onClick={() => setViewMode('grid')}
              aria-label="Grid view"
              className={`p-1.5 rounded-md transition-all duration-200 ${
                viewMode === 'grid'
                  ? 'bg-white/10 text-white'
                  : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              <LayoutGrid size={14} />
            </button>
          </div>
        <div className="flex gap-1 bg-white/5 rounded-xl p-0.5 border border-white/5">
          {[7, 14, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              aria-label={`${d} days period`}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 ${
                days === d
                  ? 'bg-gradient-to-r from-primary-600 to-primary-500 text-white shadow-glow-sm'
                  : 'text-gray-400 hover:text-white hover:bg-white/5'
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-6">
          <SkeletonChart height="h-[400px]" />
          <SkeletonTable rows={4} cols={7} />
        </div>
      ) : compareData.length === 0 ? (
        <div className="glass-card rounded-xl p-16 text-center">
          <div className="text-gray-500 text-sm">{t('performance.noData')}</div>
        </div>
      ) : (
        <>
          {viewMode === 'cards' ? (
            <>
              {/* ── Konzept 1: Bot Cards + Interactive Chart ──── */}
              <div className="mb-5">
                <div className="flex flex-wrap gap-3">
                  {compareData.map((bot, i) => (
                    <BotCard
                      key={bot.bot_id}
                      bot={bot}
                      color={BOT_COLORS[i % BOT_COLORS.length]}
                      isSelected={selectedBot === bot.bot_id}
                      isHovered={hoveredBot === bot.bot_id}
                      onClick={() => handleCardClick(bot.bot_id)}
                      onMouseEnter={() => setHoveredBot(bot.bot_id)}
                      onMouseLeave={() => setHoveredBot(null)}
                      index={i}
                    />
                  ))}
                </div>
              </div>

            </>
          ) : (
            /* ── Konzept 2: Small Multiples Grid ─────────── */
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
              {compareData.map((bot, i) => (
                <SmallMultipleCard
                  key={bot.bot_id}
                  bot={bot}
                  color={BOT_COLORS[i % BOT_COLORS.length]}
                  yDomain={sharedYDomain}
                  chartGridColor={chartGridColor}
                  chartTickColor={chartTickColor}
                  isSelected={selectedBot === bot.bot_id}
                  onClick={() => handleCardClick(bot.bot_id)}
                />
              ))}
            </div>
          )}

          {/* Detail Error */}
          {detailError && (
            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
              {detailError}
            </div>
          )}

          {/* ── Bot Detail Panel ─────────────────────────── */}
          {botDetail && (
            <div className="glass-card rounded-xl p-5 slide-in-panel">
              <h2 className="text-white font-semibold mb-4">{botDetail.bot_name} -- {t('performance.details')}</h2>

              {/* Summary Cards (centered) */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
                <div className="bg-white/5 rounded-xl p-3 border border-white/5 text-center">
                  <div className="text-[10px] text-gray-500 mb-1 uppercase tracking-wider font-medium">{t('performance.totalPnl')}</div>
                  <div className={`text-lg font-bold flex items-center justify-center gap-1 ${botDetail.summary.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                    <PnlCell
                      pnl={botDetail.summary.total_pnl}
                      fees={botDetail.summary.total_fees ?? 0}
                      fundingPaid={botDetail.summary.total_funding ?? 0}
                      className={`text-lg font-bold ${botDetail.summary.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}
                    />
                    {botDetail.summary.total_pnl >= 0
                      ? <ArrowUpRight size={16} className="text-profit" />
                      : <ArrowDownRight size={16} className="text-loss" />
                    }
                  </div>
                </div>
                <StatCard
                  label={t('performance.winRate')}
                  value={`${botDetail.summary.win_rate}%`}
                  color={botDetail.summary.win_rate >= 60 ? 'text-profit' : botDetail.summary.win_rate >= 40 ? 'text-yellow-400' : 'text-loss'}
                />
                <StatCard
                  label={t('performance.bestTrade')}
                  value={formatPnl(botDetail.summary.best_trade)}
                  color="text-profit"
                  isPositive={true}
                />
                <StatCard
                  label={t('performance.worstTrade')}
                  value={formatPnl(botDetail.summary.worst_trade)}
                  color="text-loss"
                  isPositive={false}
                />
              </div>

              {/* Bot PnL Chart (stacked bars + cumulative line) */}
              {botChartData.length > 0 && (
                <div className="mb-5 relative">
                  <button
                    onClick={() => setShowCosts(!showCosts)}
                    className={`absolute -top-1 right-0 z-10 flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-all duration-200 border ${
                      showCosts
                        ? 'bg-white/5 border-white/10 text-gray-300 hover:bg-white/10'
                        : 'bg-white/[0.02] border-white/5 text-gray-500 hover:text-gray-400'
                    }`}
                  >
                    {showCosts ? <Eye size={13} /> : <EyeOff size={13} />}
                    {t('dashboard.fees')} & {t('dashboard.funding')}
                  </button>
                  <div className="pt-8">
                    <ResponsiveContainer width="100%" height={250}>
                      <ComposedChart data={botChartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke={chartGridColor} vertical={false} />
                        <XAxis dataKey="date" tick={{ fill: chartTickColor, fontSize: 11 }} tickLine={false} />
                        <YAxis tick={{ fill: chartTickColor, fontSize: 11 }} tickLine={false} tickFormatter={(v) => `$${v}`} />
                        <Tooltip content={<BotPnlTooltip />} />
                        <ReferenceLine y={0} stroke={refColor} strokeDasharray="3 3" />
                        <Bar dataKey="dailyPnl" name={t('dashboard.dailyPnl')} stackId="pnl" maxBarSize={40}>
                          {botChartData.map((entry, index) => (
                            <Cell key={index} fill={entry.dailyPnl >= 0 ? PNL_POS : PNL_NEG} fillOpacity={0.75} />
                          ))}
                        </Bar>
                        {showCosts && (
                          <Bar dataKey="fees" name={t('dashboard.fees')} stackId="pnl" fill={FEES_COLOR} fillOpacity={0.8} maxBarSize={40} />
                        )}
                        {showCosts && (
                          <Bar dataKey="funding" name={t('dashboard.funding')} stackId="pnl" fill={FUNDING_COLOR} fillOpacity={0.8} maxBarSize={40} radius={[3, 3, 0, 0]} />
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
                </div>
              )}

              {/* Recent Trades */}
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">{t('performance.recentTrades')}</h3>
              <div className="overflow-x-auto rounded-xl border border-white/5">
                <table className="table-premium">
                  <thead>
                    <tr>
                      <th className="text-left">{t('trades.symbol')}</th>
                      <th className="text-left">{t('trades.side')}</th>
                      <th className="text-left">{t('trades.entryPrice')}</th>
                      <th className="text-left">{t('trades.exitPrice')}</th>
                      <th className="text-left">{t('trades.pnl')}</th>
                      <th className="text-left">{t('trades.status')}</th>
                      <th className="text-left">{t('trades.date')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {botDetail.recent_trades.map((trade) => (
                      <tr key={trade.id}>
                        <td className="text-white font-medium">{trade.symbol}</td>
                        <td>
                          <span className={trade.side === 'long' ? 'text-profit' : 'text-loss'}>
                            {trade.side === 'long' ? '+' : '-'} {trade.side.toUpperCase()}
                          </span>
                        </td>
                        <td className="text-gray-300">${trade.entry_price.toFixed(2)}</td>
                        <td className="text-gray-300">{trade.exit_price ? `$${trade.exit_price.toFixed(2)}` : '--'}</td>
                        <td>
                          <PnlCell
                            pnl={trade.pnl}
                            fees={trade.fees ?? 0}
                            fundingPaid={trade.funding_paid ?? 0}
                            status={trade.status}
                            className={trade.pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}
                          />
                        </td>
                        <td>
                          <span className={trade.status === 'open' ? 'badge-open' : 'badge-neutral'}>
                            {trade.status}
                          </span>
                        </td>
                        <td className="text-gray-500 text-xs cursor-default" title={trade.entry_time ? new Date(trade.entry_time).toLocaleTimeString('de-DE', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit' }) + ' UTC' : undefined}>
                          {trade.entry_time ? new Date(trade.entry_time).toLocaleDateString() : '--'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
