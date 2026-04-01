import { useEffect, useState, useMemo, useRef, useCallback, Fragment } from 'react'
import { useTranslation } from 'react-i18next'
import {
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ComposedChart, Bar, Cell, Line,
  AreaChart, Area,
} from 'recharts'
import { toBlob } from 'html-to-image'
import api from '../api/client'
import { useToastStore } from '../stores/toastStore'
import { useFilterStore } from '../stores/filterStore'
import { useThemeStore } from '../stores/themeStore'
import { SkeletonChart, SkeletonTable } from '../components/ui/Skeleton'
import PnlCell from '../components/ui/PnlCell'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import ExitReasonBadge from '../components/ui/ExitReasonBadge'
import MobileTradeCard from '../components/ui/MobileTradeCard'
import useIsMobile from '../hooks/useIsMobile'
import useSwipeToClose from '../hooks/useSwipeToClose'
import { Eye, EyeOff, ArrowUpRight, ArrowDownRight, Trophy, Target, LayoutGrid, BarChart3, X, ChevronRight, Share2 } from 'lucide-react'
import SizeValue from '../components/ui/SizeValue'

import { formatDate, formatChartDate, formatTime, formatChartCurrency } from '../utils/dateUtils'

import { strategyLabel } from '../constants/strategies'

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
    id: number; symbol: string; side: string; size?: number; entry_price: number; exit_price: number | null
    pnl: number; pnl_percent: number; confidence: number; reason: string; status: string
    fees: number; funding_paid: number; leverage?: number
    demo_mode: boolean; entry_time: string | null; exit_time: string | null; exit_reason: string | null
    trailing_stop_active?: boolean | null; trailing_stop_price?: number | null
    trailing_stop_distance?: number | null; trailing_stop_distance_pct?: number | null
    can_close_at_loss?: boolean | null
  }[]
}

function formatPnl(value: number): string {
  const prefix = value >= 0 ? '+' : ''
  return `${prefix}$${value.toFixed(2)}`
}

function formatPnlPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
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

/* ── Bot Detail PnL Tooltip ──────────────────────────────── */

function BotPnlTooltip({ active, payload, label, t }: {
  active?: boolean
  payload?: Array<{ name: string; value: number; dataKey: string }>
  label?: string
  t: (key: string) => string
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

/* ── Stat Card ───────────────────────────────────────────── */

function StatCard({ label, value, color, isPositive }: {
  label: string; value: string; color?: string; isPositive?: boolean | null
}) {
  return (
    <div className="bg-white/5 rounded-xl p-3 border border-white/5 text-center">
      <div className="text-[10px] text-gray-400 mb-1 uppercase tracking-wider font-medium">{label}</div>
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
  const isMobile = useIsMobile()
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
  const [selectedTrade, setSelectedTrade] = useState<BotDetailStats['recent_trades'][0] | null>(null)
  const [expandedTradeId, setExpandedTradeId] = useState<number | null>(null)
  const [copied, setCopied] = useState(false)
  const tradeCardRef = useRef<HTMLDivElement>(null)
  const swipeTradeModal = useSwipeToClose({ onClose: () => setSelectedTrade(null), enabled: isMobile && selectedTrade !== null })
  const latestCardRef = useRef<HTMLDivElement>(null)
  const mobileShareRefs = useRef<Map<number, HTMLDivElement>>(new Map())
  const [affiliateLinks, setAffiliateLinks] = useState<{ exchange_type: string; affiliate_url: string; label: string | null }[]>([])

  const handleShare = async (ref: React.RefObject<HTMLDivElement | null>, trade: { symbol: string; side: string; pnl_percent: number }, affiliateUrl?: string, copiedSetter?: (v: boolean) => void) => {
    if (!ref.current) return
    const setFlag = copiedSetter || setCopied
    try {
      const isMobileDevice = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)
      const el = ref.current

      if (!isMobileDevice) {
        // Desktop: pass a Promise to ClipboardItem so the async toBlob
        // stays within the user-gesture window (Chrome requirement)
        const blobPromise = toBlob(el, {
          pixelRatio: 2,
          backgroundColor: theme === 'light' ? '#f8fafc' : '#0b0f19',
        }).then(b => {
          if (!b) throw new Error('toBlob returned null')
          return new Blob([b], { type: 'image/png' })
        })
        await navigator.clipboard.write([
          new ClipboardItem({ 'image/png': blobPromise }),
        ])
        setFlag(true)
        setTimeout(() => setFlag(false), 2000)
        return
      }

      // Mobile: native share
      const blob = await toBlob(el, {
        pixelRatio: 2,
        backgroundColor: theme === 'light' ? '#f8fafc' : '#0b0f19',
      })
      if (!blob) return
      if (navigator.share && navigator.canShare) {
        const file = new File([blob], 'trade.png', { type: 'image/png' })
        const pnlStr = trade.pnl_percent >= 0 ? `+${trade.pnl_percent.toFixed(2)}%` : `${trade.pnl_percent.toFixed(2)}%`
        if (navigator.canShare({ files: [file] })) {
          await navigator.share({
            title: `${trade.symbol} ${trade.side.toUpperCase()} ${pnlStr}`,
            text: affiliateUrl || 'Edge Bots by Trading Department',
            files: [file],
          })
        }
      }
    } catch (err) {
      if ((err as DOMException).name !== 'AbortError') {
        console.error('Failed to share image:', err)
        useToastStore.getState().addToast('error', t('common.error'))
      }
    }
  }

  const handleMobileDirectShare = useCallback(async (trade: BotDetailStats['recent_trades'][0]) => {
    const ref = mobileShareRefs.current.get(trade.id)
    if (!ref) { setSelectedTrade(trade); return }
    try {
      const blob = await toBlob(ref, {
        pixelRatio: 2,
        backgroundColor: theme === 'light' ? '#f8fafc' : '#0b0f19',
      })
      if (!blob) { setSelectedTrade(trade); return }
      const file = new File([blob], 'trade.png', { type: 'image/png' })
      const pnlStr = trade.pnl_percent >= 0 ? `+${trade.pnl_percent.toFixed(2)}%` : `${trade.pnl_percent.toFixed(2)}%`
      if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
        const botEx = compareData.find(b => b.bot_id === selectedBot)?.exchange_type
        const aLink = botEx ? affiliateLinks.find(l => l.exchange_type === botEx) : null
        await navigator.share({
          title: `${trade.symbol} ${trade.side.toUpperCase()} ${pnlStr}`,
          text: aLink?.affiliate_url || 'Edge Bots by Trading Department',
          files: [file],
        })
      } else {
        // Fallback: open modal
        setSelectedTrade(trade)
      }
    } catch (err) {
      if ((err as DOMException).name !== 'AbortError') {
        console.error('Failed to share image:', err)
        useToastStore.getState().addToast('error', t('common.error'))
      }
    }
  }, [theme, compareData, selectedBot, affiliateLinks, t])

  const loadCompareData = useCallback(async () => {
    const dp = demoFilter === 'demo' ? '&demo_mode=true' : demoFilter === 'live' ? '&demo_mode=false' : ''
    setLoading(true)
    setError('')
    try {
      const res = await api.get(`/bots/compare/performance?days=${days}${dp}`)
      setCompareData(res.data.bots || [])
    } catch {
      setError(t('performance.loadError'))
    }
    setLoading(false)
  }, [days, demoFilter, t])

  const loadBotDetail = useCallback(async (botId: number) => {
    const dp = demoFilter === 'demo' ? '&demo_mode=true' : demoFilter === 'live' ? '&demo_mode=false' : ''
    setDetailError('')
    try {
      const res = await api.get(`/bots/${botId}/statistics?days=${days}${dp}`)
      setBotDetail(res.data)
    } catch {
      setDetailError(t('performance.detailError'))
    }
  }, [days, demoFilter, t])

  useEffect(() => {
    loadCompareData()
    api.get('/affiliate-links').then(res => setAffiliateLinks(res.data)).catch((err) => { console.error('Failed to load affiliate links:', err); useToastStore.getState().addToast('error', t('common.loadError', 'Failed to load data')) })
  }, [loadCompareData])

  useEffect(() => {
    if (selectedBot) loadBotDetail(selectedBot)
    else setBotDetail(null)
  }, [selectedBot, loadBotDetail])

  // Build bot detail chart data
  const botChartData = useMemo(() => {
    if (!botDetail) return []
    let cumulative = 0
    return botDetail.daily_series.map((d) => {
      cumulative += d.pnl
      return {
        date: formatChartDate(d.date),
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
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
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
        <div role="alert" className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
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
            <div role="alert" className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
              {detailError}
            </div>
          )}

          {/* ── Bot Detail Panel ─────────────────────────── */}
          {botDetail && (
            <div className="glass-card rounded-xl p-5 slide-in-panel">
              <h2 className="text-white font-semibold mb-4">
                {botDetail.bot_name} -- {t('performance.details')}
                {(() => {
                  const st = compareData.find(b => b.bot_id === selectedBot)?.strategy_type
                  return st ? <span className="ml-2 text-sm font-normal text-gray-400">{strategyLabel(st)}</span> : null
                })()}
              </h2>

              {/* Summary Cards (centered) */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
                <div className="bg-white/5 rounded-xl p-3 border border-white/5 text-center">
                  <div className="text-[10px] text-gray-400 mb-1 uppercase tracking-wider font-medium">{t('performance.totalPnl')}</div>
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

              {/* Latest Trade Card */}
              {(() => {
                const latestClosed = botDetail.recent_trades.find(tr => tr.status === 'closed')
                const botExchange = compareData.find(b => b.bot_id === selectedBot)?.exchange_type || ''
                const affiliateLink = affiliateLinks.find(l => l.exchange_type === botExchange)
                if (!latestClosed) return null
                return (
                  <div className="mb-5">
                    <div className="flex items-center mb-2">
                      <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold">{t('bots.latestTrade')}</div>
                    </div>
                    <div
                      ref={latestCardRef}
                      className="bg-white/[0.02] rounded-xl p-4 border border-white/5 cursor-pointer hover:border-white/10 transition-all"
                      onClick={() => setSelectedTrade(latestClosed)}
                    >
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-3">
                          <span className="text-white font-bold text-lg">{latestClosed.symbol}</span>
                          <span className={`px-2 py-0.5 rounded-lg text-sm font-bold ${
                            latestClosed.side === 'long' ? 'bg-emerald-500/15 text-profit border border-emerald-500/20' : 'bg-red-500/15 text-loss border border-red-500/20'
                          }`}>
                            {latestClosed.side === 'long' ? '+ LONG' : '- SHORT'}
                          </span>
                          {latestClosed.leverage && (
                            <span className="text-sm font-semibold text-white bg-white/10 px-2 py-0.5 rounded-lg">{latestClosed.leverage}x</span>
                          )}
                        </div>
                        <span className="text-xs text-gray-500" title={formatTime(latestClosed.entry_time)}>
                          {formatDate(latestClosed.entry_time)}
                        </span>
                      </div>
                      {/* Mobile: centered PnL + entry/exit row */}
                      <div className="sm:hidden">
                        <div className="text-center my-4">
                          <div className={`text-4xl font-bold tracking-tight ${latestClosed.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}`}>
                            {formatPnlPercent(latestClosed.pnl_percent)}
                          </div>
                          <PnlCell pnl={latestClosed.pnl} fees={latestClosed.fees ?? 0} fundingPaid={latestClosed.funding_paid ?? 0} status={latestClosed.status}
                            className={`text-lg font-semibold ${latestClosed.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`} />
                        </div>
                        <div className="grid grid-cols-2 gap-4 max-w-xs mx-auto">
                          <div className="text-center">
                            <div className="text-xs text-gray-400 mb-1">{t('bots.entryPrice')}</div>
                            <div className="text-white font-semibold text-lg">${latestClosed.entry_price.toLocaleString()}</div>
                          </div>
                          <div className="text-center">
                            <div className="text-xs text-gray-400 mb-1">{t('bots.exitPrice')}</div>
                            <div className="text-white font-semibold text-lg">{latestClosed.exit_price ? `$${latestClosed.exit_price.toLocaleString()}` : '--'}</div>
                          </div>
                        </div>
                      </div>
                      {/* Desktop: horizontal grid */}
                      <div className="hidden sm:grid grid-cols-4 gap-4">
                        <div>
                          <div className="text-xs text-gray-400 uppercase tracking-wider mb-0.5">{t('bots.result')}</div>
                          <div className={`text-2xl font-bold tracking-tight ${latestClosed.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}`}>
                            {formatPnlPercent(latestClosed.pnl_percent)}
                          </div>
                          <PnlCell pnl={latestClosed.pnl} fees={latestClosed.fees ?? 0} fundingPaid={latestClosed.funding_paid ?? 0} status={latestClosed.status}
                            className={`text-sm font-medium ${latestClosed.pnl >= 0 ? 'text-profit/60' : 'text-loss/60'}`} />
                        </div>
                        <div>
                          <div className="text-xs text-gray-400 uppercase tracking-wider mb-0.5">{t('bots.entryPrice')}</div>
                          <div className="text-lg font-bold text-white">${latestClosed.entry_price.toLocaleString()}</div>
                        </div>
                        <div>
                          <div className="text-xs text-gray-400 uppercase tracking-wider mb-0.5">{t('bots.exitPrice')}</div>
                          <div className="text-lg font-bold text-white">
                            {latestClosed.exit_price ? `$${latestClosed.exit_price.toLocaleString()}` : '--'}
                          </div>
                        </div>
                      </div>
                      <div className="mt-3 pt-2 border-t border-white/5">
                        <div className="text-xs text-gray-500">Edge Bots by Trading Department</div>
                        {affiliateLink && (
                          <div className="flex items-center justify-between mt-0.5">
                            <span className="text-xs text-gray-500">{affiliateLink.label || t('bots.affiliateLink')}</span>
                            <span className="text-xs text-primary-400 font-medium">{affiliateLink.affiliate_url}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })()}

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
                        <XAxis dataKey="date" tick={{ fill: chartTickColor, fontSize: 10 }} tickLine={false} />
                        <YAxis width={45} tick={{ fill: chartTickColor, fontSize: 10 }} tickLine={false} tickFormatter={formatChartCurrency} />
                        <Tooltip content={<BotPnlTooltip t={t} />} />
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
              {isMobile ? (
                <div className="space-y-2">
                  {(() => {
                    const botExchange = compareData.find(b => b.bot_id === selectedBot)?.exchange_type || ''
                    const affiliateLink = affiliateLinks.find(l => l.exchange_type === botExchange)
                    return (
                      <>
                        {botDetail.recent_trades.map((trade) => (
                          <MobileTradeCard
                            key={trade.id}
                            trade={{
                              ...trade,
                              entry_time: trade.entry_time || '',
                              pnl_percent: trade.pnl_percent,
                              fees: trade.fees,
                              funding_paid: trade.funding_paid,
                              bot_exchange: botExchange,
                              exit_reason: trade.exit_reason,
                            }}
                            extraDetails={[
                              ...(trade.reason ? [{ label: t('bots.reasoning'), value: trade.reason }] : []),
                            ]}
                            onShare={() => handleMobileDirectShare(trade)}
                          />
                        ))}
                        {/* Hidden capture divs for mobile direct share */}
                        <div className="absolute -left-[9999px] pointer-events-none" aria-hidden="true">
                          {botDetail.recent_trades.filter(tr => tr.status === 'closed').map((trade) => (
                            <div
                              key={trade.id}
                              ref={(el) => { if (el) mobileShareRefs.current.set(trade.id, el); else mobileShareRefs.current.delete(trade.id) }}
                              className="bg-[#0f1420] rounded-2xl p-5 w-[420px] border border-white/10 shadow-2xl"
                            >
                              <div className="flex items-center gap-2 mb-1">
                                <ExchangeIcon exchange={botExchange} size={18} />
                                <span className="text-lg font-bold text-white">{trade.symbol}</span>
                              </div>
                              <div className="flex items-center justify-between text-sm text-gray-400 mb-4">
                                <div className="flex items-center gap-2">
                                  <span>Perp</span>
                                  <span className="text-gray-600">|</span>
                                  <span className={trade.side === 'long' ? 'text-emerald-400 font-medium' : 'text-red-400 font-medium'}>
                                    {trade.side === 'long' ? '+ LONG' : '- SHORT'}
                                  </span>
                                  {trade.leverage && (
                                    <>
                                      <span className="text-gray-600">|</span>
                                      <span className="text-white font-medium">{trade.leverage}x</span>
                                    </>
                                  )}
                                </div>
                                <span className="text-xs text-gray-500">{formatDate(trade.entry_time)}</span>
                              </div>
                              <div className="text-center py-5 mb-4">
                                <div className={`text-5xl font-bold tracking-tight ${trade.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}`}>
                                  {formatPnlPercent(trade.pnl_percent)}
                                </div>
                                <div className={`text-lg font-semibold mt-1 ${trade.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`}>
                                  <PnlCell pnl={trade.pnl} fees={trade.fees ?? 0} fundingPaid={trade.funding_paid ?? 0} status={trade.status}
                                    className={`text-lg font-semibold ${trade.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`} />
                                </div>
                              </div>
                              <div className="grid grid-cols-2 gap-4 max-w-xs mx-auto mb-4">
                                <div className="text-center">
                                  <div className="text-xs text-gray-400 mb-1">{t('bots.entryPrice')}</div>
                                  <div className="text-white font-semibold text-lg">${trade.entry_price.toLocaleString()}</div>
                                </div>
                                <div className="text-center">
                                  <div className="text-xs text-gray-400 mb-1">{t('bots.exitPrice')}</div>
                                  <div className="text-white font-semibold text-lg">{trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}</div>
                                </div>
                              </div>
                              <div className="pt-3 border-t border-white/5">
                                <div className="text-xs text-gray-500">Edge Bots by Trading Department</div>
                                {affiliateLink && (
                                  <>
                                    {affiliateLink.label && <div className="text-xs text-gray-400 mt-0.5">{affiliateLink.label}</div>}
                                    <div className="text-xs text-primary-400 font-medium mt-0.5">{affiliateLink.affiliate_url}</div>
                                  </>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </>
                    )
                  })()}
                </div>
              ) : (
                <div className="overflow-x-auto rounded-xl border border-white/5">
                  <table className="table-premium w-full">
                    <thead>
                      <tr>
                        <th className="text-left">{t('trades.date')}</th>
                        <th className="text-center hidden lg:table-cell">{t('trades.exchange')}</th>
                        <th className="text-left">{t('trades.symbol')}</th>
                        <th className="text-center">{t('trades.side')}</th>
                        <th className="text-right hidden xl:table-cell">{t('trades.entryPrice')}</th>
                        <th className="text-right hidden xl:table-cell">{t('trades.exitPrice')}</th>
                        <th className="text-right">{t('trades.pnl')}</th>
                        <th className="text-center hidden 2xl:table-cell">{t('trades.mode')}</th>
                        <th className="text-center">{t('trades.status')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(() => {
                        const botExchange = compareData.find(b => b.bot_id === selectedBot)?.exchange_type || ''
                        return botDetail.recent_trades.map((trade) => (
                          <Fragment key={trade.id}>
                          <tr
                            onClick={() => setExpandedTradeId(expandedTradeId === trade.id ? null : trade.id)}
                            className="cursor-pointer"
                          >
                            <td className="text-gray-300">
                              <span className="inline-flex items-center">
                                <ChevronRight size={14} className={`expand-chevron ${expandedTradeId === trade.id ? 'open' : ''}`} />
                                <span title={formatTime(trade.entry_time)}>{formatDate(trade.entry_time)}</span>
                              </span>
                            </td>
                            <td className="text-center hidden lg:table-cell">
                              <span className="inline-flex justify-center">
                                <ExchangeIcon exchange={botExchange} size={18} />
                              </span>
                            </td>
                            <td className="text-white font-medium">{trade.symbol}</td>
                            <td className="text-center">
                              <span className={trade.side === 'long' ? 'text-profit' : 'text-loss'}>
                                {trade.side === 'long' ? '+' : '-'} {trade.side.toUpperCase()}
                              </span>
                            </td>
                            <td className="text-right text-gray-300 hidden xl:table-cell">${trade.entry_price.toLocaleString()}</td>
                            <td className="text-right text-gray-300 hidden xl:table-cell">
                              {trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}
                            </td>
                            <td className="text-right">
                              <PnlCell
                                pnl={trade.pnl}
                                fees={trade.fees ?? 0}
                                fundingPaid={trade.funding_paid ?? 0}
                                status={trade.status}
                                className={trade.pnl && trade.pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}
                              />
                            </td>
                            <td className="text-center hidden 2xl:table-cell">
                              <span className={trade.demo_mode ? 'badge-demo' : 'badge-live'}>
                                {trade.demo_mode ? t('common.demo') : t('common.live')}
                              </span>
                            </td>
                            <td className="text-center">
                              <span className={
                                trade.status === 'open' ? 'badge-open' :
                                trade.status === 'closed' ? 'badge-neutral' :
                                'badge-demo'
                              }>
                                {t(`trades.${trade.status}`)}
                              </span>
                            </td>
                          </tr>
                          {expandedTradeId === trade.id && (
                            <tr className="table-expand-row">
                              <td colSpan={9} className="!p-0 !border-b-0">
                                <dl className="table-expand-content">
                                  <div>
                                    <dt>ID</dt>
                                    <dd>{trade.id}</dd>
                                  </div>
                                  <div className="xl:hidden">
                                    <dt>{t('trades.entryPrice')}</dt>
                                    <dd>${trade.entry_price.toLocaleString()}</dd>
                                  </div>
                                  <div className="xl:hidden">
                                    <dt>{t('trades.exitPrice')}</dt>
                                    <dd>{trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}</dd>
                                  </div>
                                  <div>
                                    <dt>{t('trades.size')}</dt>
                                    <dd><SizeValue size={trade.size ?? 0} price={trade.entry_price} symbol={trade.symbol} /></dd>
                                  </div>
                                  <div>
                                    <dt>{t('trades.pnl')} %</dt>
                                    <dd className={trade.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}>
                                      {trade.pnl_percent >= 0 ? '+' : ''}{trade.pnl_percent.toFixed(2)}%
                                    </dd>
                                  </div>
                                  <div className="2xl:hidden">
                                    <dt>{t('trades.mode')}</dt>
                                    <dd>{trade.demo_mode ? t('common.demo') : t('common.live')}</dd>
                                  </div>
                                  <div className="hidden sm:block">
                                    <dt>&nbsp;</dt>
                                    <dd>
                                      <button
                                        onClick={() => setSelectedTrade(trade)}
                                        className="p-2 rounded-lg text-gray-400 hover:text-white bg-white/5 hover:bg-white/10 border border-white/5 transition-all"
                                        title={t('bots.shareImage')}
                                      >
                                        <Share2 size={14} />
                                      </button>
                                    </dd>
                                  </div>
                                  {trade.exit_time && (
                                    <div>
                                      <dt>{t('trades.exitTime')}</dt>
                                      <dd>{formatDate(trade.exit_time)} {formatTime(trade.exit_time)}</dd>
                                    </div>
                                  )}
                                  {trade.exit_reason && (
                                    <div>
                                      <dt>{t('trades.exitReason')}</dt>
                                      <dd><ExitReasonBadge reason={trade.exit_reason} /></dd>
                                    </div>
                                  )}
                                  {trade.fees > 0 && (
                                    <div>
                                      <dt>{t('trades.fees')}</dt>
                                      <dd>${trade.fees.toFixed(2)}</dd>
                                    </div>
                                  )}
                                  {trade.reason && (
                                    <div className="col-span-2">
                                      <dt>{t('bots.reasoning')}</dt>
                                      <dd className="text-gray-400 text-xs">{trade.reason}</dd>
                                    </div>
                                  )}
                                  <div className="sm:hidden pt-1">
                                    <button
                                      onClick={() => setSelectedTrade(trade)}
                                      className="p-2 rounded-lg text-gray-400 hover:text-white bg-white/5 hover:bg-white/10 border border-white/5 transition-all"
                                      title={t('bots.shareImage')}
                                    >
                                      <Share2 size={14} />
                                    </button>
                                  </div>
                                </dl>
                              </td>
                            </tr>
                          )}
                          </Fragment>
                        ))
                      })()}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* Trade Detail Modal */}
      {selectedTrade && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-md" onClick={() => setSelectedTrade(null)}>
          <div
            ref={swipeTradeModal.ref}
            style={swipeTradeModal.style}
            className="bg-[#0f1420] rounded-2xl max-w-lg w-full mx-4 border border-white/10 shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {isMobile && (
              <div className="flex justify-center pt-2 pb-1 lg:hidden">
                <div className="w-10 h-1 rounded-full bg-white/20" />
              </div>
            )}
            {/* Modal Header with Copy Button */}
            <div className="flex items-center justify-between px-7 pt-7 pb-0">
              <div className="flex items-center gap-3">
                <h3 className="text-xl font-bold text-white">{selectedTrade.symbol}</h3>
                <span className={`px-3 py-1 rounded-lg text-xs font-bold ${
                  selectedTrade.side === 'long' ? 'bg-emerald-500/15 text-profit border border-emerald-500/20' : 'bg-red-500/15 text-loss border border-red-500/20'
                }`}>
                  {selectedTrade.side === 'long' ? '+ LONG' : '- SHORT'}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    const botEx = compareData.find(b => b.bot_id === selectedBot)?.exchange_type
                    const aLink = botEx ? affiliateLinks.find(l => l.exchange_type === botEx) : null
                    handleShare(tradeCardRef, selectedTrade, aLink?.affiliate_url)
                  }}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg transition-all border ${
                    copied
                      ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
                      : 'text-gray-400 hover:text-white bg-white/5 hover:bg-white/10 border-white/5'
                  }`}
                  title={t('bots.shareImage')}
                >
                  <Share2 size={14} />
                  {copied ? t('bots.copied') : t('bots.shareImage')}
                </button>
                <button onClick={() => setSelectedTrade(null)} className="hidden sm:block p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-all" aria-label="Close">
                  <X size={20} />
                </button>
              </div>
            </div>

            {/* Capturable Card Content */}
            <div ref={tradeCardRef} className="p-5">
              {/* Header: Exchange logo + Symbol */}
              {(() => {
                const botEx = compareData.find(b => b.bot_id === selectedBot)?.exchange_type
                return (
                  <div className="flex items-center gap-2 mb-1">
                    {botEx && <ExchangeIcon exchange={botEx} size={18} />}
                    <span className="text-lg font-bold text-white">{selectedTrade.symbol}</span>
                  </div>
                )
              })()}
              {/* Perp | Side | Leverage | Date */}
              <div className="flex items-center justify-between text-sm text-gray-400 mb-4">
                <div className="flex items-center gap-2">
                  <span>Perp</span>
                  <span className="text-gray-600">|</span>
                  <span className={selectedTrade.side === 'long' ? 'text-emerald-400 font-medium' : 'text-red-400 font-medium'}>
                    {selectedTrade.side === 'long' ? '+ LONG' : '- SHORT'}
                  </span>
                  {selectedTrade.leverage && (
                    <>
                      <span className="text-gray-600">|</span>
                      <span className="text-white font-medium">{selectedTrade.leverage}x</span>
                    </>
                  )}
                </div>
                <span className="text-xs text-gray-500">{formatDate(selectedTrade.entry_time)}</span>
              </div>

              {/* PnL - Hero */}
              <div className="text-center py-5 mb-4">
                <div className={`text-5xl font-bold tracking-tight ${selectedTrade.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}`}>
                  {formatPnlPercent(selectedTrade.pnl_percent)}
                </div>
                <div className={`text-lg font-semibold mt-1 ${selectedTrade.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`}>
                  <PnlCell
                    pnl={selectedTrade.pnl}
                    fees={selectedTrade.fees ?? 0}
                    fundingPaid={selectedTrade.funding_paid ?? 0}
                    status={selectedTrade.status}
                    className={`text-lg font-semibold ${selectedTrade.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`}
                  />
                </div>
              </div>

              {/* Entry / Exit Price */}
              <div className="grid grid-cols-2 gap-4 max-w-xs mx-auto mb-4">
                <div className="text-center">
                  <div className="text-xs text-gray-400 mb-1">{t('bots.entryPrice')}</div>
                  <div className="text-white font-semibold text-lg">${selectedTrade.entry_price.toLocaleString()}</div>
                </div>
                <div className="text-center">
                  <div className="text-xs text-gray-400 mb-1">{t('bots.exitPrice')}</div>
                  <div className="text-white font-semibold text-lg">
                    {selectedTrade.exit_price ? `$${selectedTrade.exit_price.toLocaleString()}` : '--'}
                  </div>
                </div>
              </div>

              {/* Footer: Branding + Affiliate */}
              <div className="pt-3 border-t border-white/5">
                <div className="text-xs text-gray-500">Edge Bots by Trading Department</div>
                {(() => {
                  const botEx = compareData.find(b => b.bot_id === selectedBot)?.exchange_type
                  const aLink = botEx ? affiliateLinks.find(l => l.exchange_type === botEx) : null
                  return aLink ? (
                    <>
                      {aLink.label && <div className="text-xs text-gray-400 mt-0.5">{aLink.label}</div>}
                      <div className="text-xs text-primary-400 font-medium mt-0.5">{aLink.affiliate_url}</div>
                    </>
                  ) : null
                })()}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
