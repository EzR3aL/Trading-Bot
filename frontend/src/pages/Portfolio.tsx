import { Fragment, useState, useMemo, useCallback, useRef } from 'react'
import { formatChartCurrency } from '../utils/dateUtils'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, Legend, Sector,
} from 'recharts'
import {
  Briefcase, ArrowUpRight, ArrowDownRight, TrendingUp,
  ChevronUp, ChevronDown, ChevronRight, ShieldCheck, Settings,
} from 'lucide-react'
import { usePortfolioSummary, usePortfolioDaily, usePortfolioPositions, usePortfolioAllocation, useUpdateTpSl, queryKeys } from '../api/queries'
import { getApiErrorMessage } from '../utils/api-error'
import { useFilterStore } from '../stores/filterStore'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import type { PortfolioPosition } from '../types'
import MobilePositionCard from '../components/ui/MobilePositionCard'
import EditPositionPanel from '../components/ui/EditPositionPanel'
import SizeValue from '../components/ui/SizeValue'
import { useSizeUnitStore } from '../stores/sizeUnitStore'
import { useThemeStore } from '../stores/themeStore'
import useIsMobile from '../hooks/useIsMobile'
import usePullToRefresh from '../hooks/usePullToRefresh'
import { useTradesSSE } from '../hooks/useTradesSSE'
import { useVisibleTab } from '../hooks/useIntervalPaused'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import PullToRefreshIndicator from '../components/ui/PullToRefreshIndicator'
import GuidedTour, { TourHelpButton, type TourStep } from '../components/ui/GuidedTour'
import { useVirtualRows } from '../components/virtualised/useVirtualRows'

/* ── Constants ────────────────────────────────────────────── */

const PERIODS = [7, 14, 30, 90] as const

const EXCHANGE_COLORS: Record<string, string> = {
  bitget: '#3b82f6',
  hyperliquid: '#22c55e',
  weex: '#f97316',
  bitunix: '#b9f641',
  bingx: '#2954fe',
}

function exchangeColor(name: string): string {
  return EXCHANGE_COLORS[name.toLowerCase()] || '#6b7280'
}

/* ── Custom Chart Tooltip ─────────────────────────────────── */

function ChartTooltip({ active, payload, label }: any) {
  const { theme: tooltipTheme } = useThemeStore()
  const tooltipLight = tooltipTheme === 'light'
  if (!active || !payload?.length) return null
  return (
    <div className={`${tooltipLight ? 'bg-white/95 border-gray-200' : 'bg-[#0d1117]/95 border-white/10'} border rounded-lg px-3 py-2 text-xs shadow-xl backdrop-blur-sm`}>
      <div className={tooltipLight ? 'text-gray-500 mb-1' : 'text-gray-400 mb-1'}>{label}</div>
      {payload.map((entry: any) => (
        <div key={entry.dataKey} className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full" style={{ background: entry.color }} />
          <span className={tooltipLight ? 'text-gray-600' : 'text-gray-300'}>{entry.name}:</span>
          <span className={entry.value >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}>
            ${entry.value.toFixed(2)}
          </span>
        </div>
      ))}
    </div>
  )
}

/* ── Main Component ───────────────────────────────────────── */

export default function Portfolio() {
  const { t } = useTranslation()
  useDocumentTitle(t('nav.portfolio'))
  const { demoFilter } = useFilterStore()
  const { theme } = useThemeStore()
  const isLight = theme === 'light'

  const queryClient = useQueryClient()

  // Data state
  const [period, setPeriod] = useState<number>(30)
  const isMobile = useIsMobile()
  const { toggle: toggleSizeUnit } = useSizeUnitStore()
  const sizeUnit = useSizeUnitStore((s) => s.unit)

  // Sorting state for positions
  const [sortAsc, setSortAsc] = useState(false)
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  /* ── Data Fetching via React Query ─────────────────────── */

  // Phase 1: Fast DB queries (summary + daily) -- renders page instantly
  const { data: summary = null, isLoading: loading, error: summaryError } = usePortfolioSummary(period, demoFilter)
  const { data: dailyData = [], error: dailyError } = usePortfolioDaily(period, demoFilter)

  // Phase 2: Slow exchange API calls (positions + allocation) -- loads in background
  const { data: positions = [], isLoading: loadingExchange, error: positionsError } = usePortfolioPositions()
  const { data: allocation = [], error: allocationError } = usePortfolioAllocation()
  const updateTpSl = useUpdateTpSl()

  // Real-time trade updates via SSE (Issue #216 §2.2). Replaces the previous
  // 5-second polling loop; falls back to polling automatically if the
  // EventSource connection fails. Paused while the tab is backgrounded so
  // we don't keep hammering the API for a user who isn't looking (UX-M9).
  const tabVisible = useVisibleTab()
  useTradesSSE({ enabled: tabVisible })

  // Priority order for surfacing API errors: summary (core data) > positions
  // > daily (chart) > allocation. Whichever fails first in this chain is what
  // the user sees — we never hide a backend failure behind a skeleton or an
  // empty-state (UX-H8).
  const firstError = summaryError ?? positionsError ?? dailyError ?? allocationError

  const refreshData = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.portfolio.summary({ period, demoFilter }) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.portfolio.daily({ period, demoFilter }) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.portfolio.positions }),
      queryClient.invalidateQueries({ queryKey: queryKeys.portfolio.allocation }),
    ])
  }, [queryClient, period, demoFilter])

  const { containerRef, refreshing, pullDistance } = usePullToRefresh({
    onRefresh: refreshData,
    disabled: !isMobile,
  })

  /* ── Derived Data ───────────────────────────────────────── */

  // Build chart data: pivot daily data by exchange into rows keyed by date
  const chartData = useMemo(() => {
    const dateMap: Record<string, Record<string, number>> = {}
    const exchangeSet = new Set<string>()

    dailyData.forEach((d) => {
      exchangeSet.add(d.exchange)
      if (!dateMap[d.date]) dateMap[d.date] = {}
      dateMap[d.date][d.exchange] = (dateMap[d.date][d.exchange] || 0) + d.pnl
    })

    const exchanges = Array.from(exchangeSet)

    return {
      exchanges,
      rows: Object.entries(dateMap)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([date, vals]) => ({
          date: date.slice(5), // MM-DD
          ...vals,
        })),
    }
  }, [dailyData])

  // Total balance from allocation
  const totalBalance = allocation.reduce((sum, a) => sum + a.balance, 0)

  // Filter positions by demo/live mode
  const filteredPositions = demoFilter === 'all'
    ? positions
    : positions.filter((p) => demoFilter === 'demo' ? p.demo_mode : !p.demo_mode)

  // Sorted positions
  const sortedPositions = [...filteredPositions].sort((a, b) =>
    sortAsc
      ? a.unrealized_pnl - b.unrealized_pnl
      : b.unrealized_pnl - a.unrealized_pnl
  )
  const [editingPos, setEditingPos] = useState<PortfolioPosition | null>(null)

  // Scroll anchor for window-virtualised position rows. In day-to-day
  // use there are rarely more than ~20 open positions, so virtualisation
  // is dormant — but the hook is ready to kick in if a user connects
  // many exchanges or the feed grows beyond the threshold.
  const positionsTableRef = useRef<HTMLDivElement | null>(null)
  const {
    isVirtualised: positionsVirtualised,
    virtualItems: positionsVirtualItems,
    paddingTop: positionsPaddingTop,
    paddingBottom: positionsPaddingBottom,
    measureElement: positionsMeasureElement,
  } = useVirtualRows({
    count: sortedPositions.length,
    scrollMarginRef: positionsTableRef,
  })

  // Re-resolve the clicked position against the live positions query so the
  // modal always reflects the latest server state (e.g. a just-cleared SL).
  // Snapshotting at click-time showed stale fields after a save-close-reopen.
  const livePosition = editingPos?.trade_id
    ? positions.find(p => p.trade_id === editingPos.trade_id) ?? editingPos
    : null

  // Pie chart data
  const pieData = allocation.map((a) => ({
    name: a.exchange,
    value: a.balance,
  }))

  const [activePieIndex, setActivePieIndex] = useState<number | undefined>(undefined)

  // Custom active shape: slightly enlarged segment, no outline
  const renderActiveShape = (props: any) => {
    const { cx, cy, innerRadius, outerRadius, startAngle, endAngle, fill, payload, value } = props
    return (
      <g>
        {/* Highlighted segment — slightly bigger */}
        <Sector
          cx={cx} cy={cy}
          innerRadius={innerRadius - 3}
          outerRadius={outerRadius + 6}
          startAngle={startAngle}
          endAngle={endAngle}
          fill={fill}
          opacity={1}
        />
        {/* Center label: exchange name + funds */}
        <text x={cx} y={cy - 10} textAnchor="middle" fill={isLight ? '#0f172a' : '#fff'} fontSize={14} fontWeight={600}>
          {payload.name.charAt(0).toUpperCase() + payload.name.slice(1)}
        </text>
        <text x={cx} y={cy + 12} textAnchor="middle" fill={isLight ? 'rgba(15,23,42,0.6)' : 'rgba(255,255,255,0.7)'} fontSize={13}>
          ${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </text>
      </g>
    )
  }

  // Merge exchange cards: DB trades + live balances (so all exchanges appear)
  const mergedExchanges = (() => {
    const byName = new Map<string, { exchange: string; total_pnl: number; win_rate: number; total_trades: number; total_fees: number; balance?: number }>()
    if (summary) {
      for (const ex of summary.exchanges) {
        byName.set(ex.exchange.toLowerCase(), { ...ex, exchange: ex.exchange.toLowerCase() })
      }
    }
    for (const a of allocation) {
      const key = a.exchange.toLowerCase()
      if (byName.has(key)) {
        byName.get(key)!.balance = a.balance
      } else {
        byName.set(key, {
          exchange: key, total_pnl: 0, win_rate: 0, total_trades: 0,
          total_fees: 0, balance: a.balance,
        })
      }
    }
    return Array.from(byName.values())
  })()

  /* ── Error / Loading State ──────────────────────────────── */

  // Render order is ERROR → LOADING → CONTENT (UX-H8). If ANY of the four
  // portfolio queries errors out we show the error view immediately; otherwise
  // a partial failure could be masked by a still-loading skeleton or by an
  // empty-state fallback for the query that did succeed.
  if (firstError) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[40vh] gap-4 px-4 text-center">
        <div role="alert" className="p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm max-w-md">
          {getApiErrorMessage(firstError, t('common.error'))}
        </div>
        <button
          type="button"
          onClick={() => { void refreshData() }}
          className="px-4 py-2 text-sm rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20 transition-colors focus:outline-none focus:ring-2 focus:ring-emerald-500"
        >
          {t('common.retry', 'Retry')}
        </button>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  /* ── Render ─────────────────────────────────────────────── */

  return (
    <div ref={containerRef} style={{ overscrollBehavior: 'contain' }} className="animate-in min-w-0" aria-busy={loading}>
      <PullToRefreshIndicator pullDistance={pullDistance} refreshing={refreshing} />

      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
            <Briefcase size={24} className="text-primary-400" />
            {t('portfolio.title')}
          </h1>
          <p className="text-sm text-gray-400 mt-1">{t('portfolio.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <TourHelpButton tourId="portfolio" />
          <div className="flex items-center gap-1.5 bg-white/5 rounded-xl p-0.5 border border-white/5">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`min-w-[4rem] sm:min-w-[4.5rem] px-2 sm:px-3 py-1.5 text-xs font-medium rounded-lg text-center transition-all duration-200 ${
                period === p
                  ? 'bg-gradient-to-r from-primary-600 to-primary-500 text-white shadow-glow-sm'
                  : 'text-gray-400 hover:text-white hover:bg-white/5'
              }`}
            >
              {t(`portfolio.days${p}` as any)}
            </button>
          ))}
          </div>
        </div>
      </div>

      {/* Summary Hero */}
      <div className="glass-card rounded-2xl p-6 mb-6" data-tour="portfolio-summary">
        <div className="grid grid-cols-1 md:grid-cols-5 gap-6 items-center">
          {/* Total Balance */}
          <div className="md:col-span-2 text-center md:text-left">
            <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">
              {t('portfolio.totalBalance')}
            </div>
            <div className="text-3xl font-bold text-white flex items-center justify-center md:justify-start gap-3">
              ${totalBalance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              {loadingExchange && (
                <div className="w-4 h-4 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
              )}
            </div>
            {summary && (
              <div className={`flex items-center justify-center md:justify-start gap-1 mt-1 text-sm ${summary.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {summary.total_pnl >= 0 ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}
                <span>${Math.abs(summary.total_pnl).toFixed(2)} PnL</span>
              </div>
            )}
          </div>

          {/* Summary stats */}
          {summary && (
            <>
              <div className="text-center">
                <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">
                  {t('portfolio.totalTrades')}
                </div>
                <div className="text-xl font-bold text-white">{summary.total_trades}</div>
              </div>
              <div className="text-center">
                <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">
                  {t('portfolio.winRate')}
                </div>
                <div className={`text-xl font-bold ${summary.overall_win_rate >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {summary.overall_win_rate.toFixed(1)}%
                </div>
              </div>
              <div className="text-center">
                <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">
                  {t('portfolio.fees')}
                </div>
                <div className="text-xl font-bold text-yellow-400">${summary.total_fees.toFixed(2)}</div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Exchange Cards */}
      {mergedExchanges.length > 0 && (
        <div className="mb-6">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
            {t('portfolio.exchangeCards')}
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {mergedExchanges.map((ex) => {
              const color = exchangeColor(ex.exchange)
              return (
                <div
                  key={ex.exchange}
                  className="glass-card rounded-xl p-5 group hover:border-white/10 transition-all duration-300"
                  style={{ borderLeft: `3px solid ${color}` }}
                >
                  <div className="flex items-center gap-3 mb-3">
                    <ExchangeIcon exchange={ex.exchange} size={24} />
                    <span className="text-white font-semibold capitalize">{ex.exchange}</span>
                    {ex.balance !== undefined && (
                      <span className="ml-auto text-xs text-gray-400">
                        ${ex.balance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <div className="text-gray-400 text-xs">{t('portfolio.totalPnl')}</div>
                      <div className={`font-medium ${ex.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        ${ex.total_pnl.toFixed(2)}
                      </div>
                    </div>
                    <div>
                      <div className="text-gray-400 text-xs">{t('portfolio.winRate')}</div>
                      <div className="text-white font-medium">{ex.win_rate.toFixed(1)}%</div>
                    </div>
                    <div>
                      <div className="text-gray-400 text-xs">{t('portfolio.totalTrades')}</div>
                      <div className="text-white font-medium">{ex.total_trades}</div>
                    </div>
                    <div>
                      <div className="text-gray-400 text-xs">{t('portfolio.fees')}</div>
                      <div className="text-yellow-400 font-medium">${ex.total_fees.toFixed(2)}</div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Charts Row: Daily PnL + Allocation Donut */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6" data-tour="portfolio-charts">
        {/* Stacked Area Chart */}
        <div className="lg:col-span-2 glass-card rounded-2xl p-5">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-4">
            {t('portfolio.dailyChart')}
          </h3>
          {chartData.rows.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-48 text-center">
              <p className="text-gray-500 dark:text-gray-500 text-sm">{t('portfolio.noData')}</p>
              <p className="text-gray-400 dark:text-gray-600 text-xs mt-1">{t('portfolio.noDataHint')}</p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={chartData.rows}>
                <defs>
                  {chartData.exchanges.map((ex) => (
                    <linearGradient key={ex} id={`grad-${ex}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={exchangeColor(ex)} stopOpacity={0.3} />
                      <stop offset="95%" stopColor={exchangeColor(ex)} stopOpacity={0} />
                    </linearGradient>
                  ))}
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={isLight ? '#e5e7eb' : 'rgba(255,255,255,0.05)'} />
                <XAxis
                  dataKey="date"
                  stroke={isLight ? '#d1d5db' : 'rgba(255,255,255,0.3)'}
                  tick={{ fill: isLight ? '#374151' : 'rgba(255,255,255,0.5)', fontSize: 10 }}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  width={45}
                  stroke={isLight ? '#d1d5db' : 'rgba(255,255,255,0.3)'}
                  tick={{ fill: isLight ? '#374151' : 'rgba(255,255,255,0.5)', fontSize: 10 }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={formatChartCurrency}
                />
                <Tooltip content={<ChartTooltip />} />
                {chartData.exchanges.map((ex) => (
                  <Area
                    key={ex}
                    type="monotone"
                    dataKey={ex}
                    name={ex.charAt(0).toUpperCase() + ex.slice(1)}
                    stackId="1"
                    stroke={exchangeColor(ex)}
                    fill={`url(#grad-${ex})`}
                    strokeWidth={2}
                  />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Allocation Donut */}
        <div className="glass-card rounded-2xl p-5">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-4">
            {t('portfolio.allocation')}
          </h3>
          {loadingExchange ? (
            <div className="flex items-center justify-center h-48">
              <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : pieData.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-48 text-center">
              <Briefcase className="w-10 h-10 text-gray-600 dark:text-gray-600 mb-2" />
              <p className="text-gray-500 dark:text-gray-500 text-sm">{t('portfolio.noData')}</p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="45%"
                  innerRadius={55}
                  outerRadius={85}
                  paddingAngle={pieData.length > 1 ? 3 : 0}
                  dataKey="value"
                  nameKey="name"
                  stroke="none"
                  activeIndex={activePieIndex}
                  activeShape={renderActiveShape}
                  onMouseEnter={(_, index) => setActivePieIndex(index)}
                  onMouseLeave={() => setActivePieIndex(undefined)}
                  onClick={(_, index) => setActivePieIndex(prev => prev === index ? undefined : index)}
                  style={{ cursor: 'pointer', outline: 'none' }}
                >
                  {pieData.map((entry, idx) => (
                    <Cell
                      key={idx}
                      fill={exchangeColor(entry.name)}
                      style={{ outline: 'none' }}
                    />
                  ))}
                </Pie>
                {activePieIndex === undefined && (
                  <text x="50%" y="42%" textAnchor="middle" fill={isLight ? 'rgba(15,23,42,0.5)' : 'rgba(255,255,255,0.5)'} fontSize={12}>
                    {t('portfolio.total', 'Gesamt')}
                  </text>
                )}
                {activePieIndex === undefined && (
                  <text x="50%" y="50%" textAnchor="middle" fill={isLight ? '#0f172a' : '#fff'} fontSize={14} fontWeight={600}>
                    ${totalBalance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </text>
                )}
                <Legend
                  verticalAlign="bottom"
                  iconType="circle"
                  iconSize={8}
                  formatter={(value: string) => (
                    <span className={`text-xs capitalize ${isLight ? 'text-gray-600' : 'text-gray-300'}`}>{value}</span>
                  )}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Positions Table */}
      <div className="glass-card rounded-2xl overflow-hidden min-w-0" data-tour="portfolio-positions">
        <div className="p-5 border-b border-white/5 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <TrendingUp size={16} className="text-primary-400" />
            {t('portfolio.positions')}
          </h2>
        </div>
        {loadingExchange ? (
          <div className="p-8 flex items-center justify-center">
            <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : sortedPositions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <TrendingUp className="w-12 h-12 text-gray-600 dark:text-gray-600 mb-3" />
            <p className="text-gray-500 dark:text-gray-400 font-medium">{t('portfolio.noPositions')}</p>
            <p className="text-gray-400 dark:text-gray-500 text-sm mt-1">{t('portfolio.noPositionsHint')}</p>
          </div>
        ) : isMobile ? (
          <div className="px-1 pb-1 pt-1 space-y-1.5">
            {sortedPositions.map((pos, idx) => (
              <MobilePositionCard key={`${pos.exchange}-${pos.symbol}-${idx}`} pos={pos} />
            ))}
          </div>
        ) : (
          (() => {
            // Row renderer shared between the virtualised and full paths.
            // Closure over `expandedIdx`, translations, and the measure ref
            // keeps the JSX shape identical regardless of which path we take.
            const renderPositionRow = (pos: PortfolioPosition, idx: number, virtualIndex: number | null) => (
              <Fragment key={`${pos.exchange}-${pos.symbol}-${idx}`}>
                <tr
                  onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
                  className="cursor-pointer"
                  data-index={virtualIndex ?? undefined}
                  ref={virtualIndex !== null ? positionsMeasureElement : undefined}
                >
                  <td>
                    <span className="inline-flex items-center gap-2">
                      <ChevronRight size={14} className={`expand-chevron ${expandedIdx === idx ? 'open' : ''}`} />
                      <ExchangeIcon exchange={pos.exchange} size={16} />
                      <span className="text-gray-300 capitalize text-sm hidden md:inline">{pos.exchange}</span>
                    </span>
                  </td>
                  <td className="text-white font-medium text-sm">{pos.symbol}</td>
                  <td className="text-center">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded ${
                      pos.side.toLowerCase() === 'long'
                        ? 'bg-emerald-500/10 text-emerald-400'
                        : 'bg-red-500/10 text-red-400'
                    }`}>
                      {pos.side.toUpperCase()}
                    </span>
                  </td>
                  <td className="text-right text-gray-300 text-sm hidden xl:table-cell">
                    <SizeValue size={pos.size} price={pos.current_price || pos.entry_price} symbol={pos.symbol} />
                  </td>
                  <td className="text-right text-gray-300 text-sm hidden lg:table-cell">
                    ${pos.entry_price.toLocaleString()}
                  </td>
                  <td className="text-right text-gray-300 text-sm hidden lg:table-cell">
                    ${pos.current_price.toLocaleString()}
                  </td>
                  <td className={`text-right text-sm font-medium whitespace-nowrap ${
                    pos.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
                  }`}>
                    {pos.unrealized_pnl >= 0 ? '▲ +' : '▼ '}${Math.abs(pos.unrealized_pnl).toFixed(2)}
                  </td>
                  <td className="text-center text-gray-300 text-sm hidden 2xl:table-cell">{pos.leverage}x</td>
                  <td className="text-center hidden xl:table-cell">
                    {pos.trailing_stop_active && pos.trailing_stop_price != null ? (
                      <span className="inline-flex items-center justify-center gap-1 text-emerald-400 text-sm">
                        ${pos.trailing_stop_price.toLocaleString()}
                        <span className="text-xs text-gray-400">({pos.trailing_stop_distance_pct?.toFixed(2)}%)</span>
                        {pos.can_close_at_loss === false && (
                          <span title={t('bots.trailingStopProtecting')}>
                            <ShieldCheck size={14} className="text-emerald-400" />
                          </span>
                        )}
                      </span>
                    ) : (
                      <span className="text-gray-600 text-sm">--</span>
                    )}
                  </td>
                  <td className="text-center">
                    {pos.trade_id && (
                      <button
                        onClick={(e) => { e.stopPropagation(); setEditingPos(pos) }}
                        className="p-1.5 text-gray-500 hover:text-white transition-colors rounded-lg hover:bg-white/5"
                        title={t('editPosition.title')}
                        aria-label="Edit position"
                      >
                        <Settings size={14} />
                      </button>
                    )}
                  </td>
                </tr>
                {expandedIdx === idx && (
                  <tr className="table-expand-row">
                    <td colSpan={10} className="!p-0 !border-b-0">
                      <dl className="table-expand-content">
                        <div className="xl:hidden">
                          <dt>{t('portfolio.size')}</dt>
                          <dd>
                            <SizeValue size={pos.size} price={pos.current_price || pos.entry_price} symbol={pos.symbol} />
                          </dd>
                        </div>
                        <div className="lg:hidden">
                          <dt>{t('portfolio.entryPrice')}</dt>
                          <dd>${pos.entry_price.toLocaleString()}</dd>
                        </div>
                        <div className="lg:hidden">
                          <dt>{t('portfolio.currentPrice')}</dt>
                          <dd>${pos.current_price.toLocaleString()}</dd>
                        </div>
                        <div className="2xl:hidden">
                          <dt>{t('portfolio.leverage')}</dt>
                          <dd>{pos.leverage}x</dd>
                        </div>
                        <div className="xl:hidden">
                          <dt>{t('bots.trailingStop')}</dt>
                          <dd>
                            {pos.trailing_stop_active && pos.trailing_stop_price != null
                              ? `$${pos.trailing_stop_price.toLocaleString()} (${pos.trailing_stop_distance_pct?.toFixed(2)}%)`
                              : '--'}
                          </dd>
                        </div>
                        {pos.bot_name && (
                          <div>
                            <dt>{t('trades.bot')}</dt>
                            <dd>{pos.bot_name}</dd>
                          </div>
                        )}
                        {pos.margin != null && pos.margin > 0 && (
                          <div>
                            <dt>{t('portfolio.margin', 'Margin')}</dt>
                            <dd>${pos.margin.toFixed(2)}</dd>
                          </div>
                        )}
                      </dl>
                    </td>
                  </tr>
                )}
              </Fragment>
            )

            return (
          <div className="overflow-x-auto" ref={positionsTableRef}>
            <table className="table-premium w-full">
              <thead>
                <tr>
                  <th className="text-left">{t('portfolio.exchange')}</th>
                  <th className="text-left">{t('portfolio.symbol')}</th>
                  <th className="text-center">{t('portfolio.side')}</th>
                  <th className="text-right hidden xl:table-cell">
                    <button
                      onClick={() => toggleSizeUnit()}
                      className="inline-flex items-center gap-1 hover:text-white transition-colors ml-auto"
                      title={sizeUnit === 'token' ? 'Show USDT value' : 'Show token size'}
                    >
                      {t('portfolio.size')} <span className="text-[10px] text-gray-500">{sizeUnit === 'usdt' ? '$' : '#'}</span>
                    </button>
                  </th>
                  <th className="text-right hidden lg:table-cell">{t('portfolio.entryPrice')}</th>
                  <th className="text-right hidden lg:table-cell">{t('portfolio.currentPrice')}</th>
                  <th className="text-right">
                    <button
                      onClick={() => setSortAsc(!sortAsc)}
                      className="inline-flex items-center gap-1 hover:text-white transition-colors"
                      aria-label="Sort by PnL"
                    >
                      {t('portfolio.pnl')}
                      {sortAsc ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                    </button>
                  </th>
                  <th className="text-center hidden 2xl:table-cell">{t('portfolio.leverage')}</th>
                  <th className="text-center hidden xl:table-cell">{t('bots.trailingStop')}</th>
                  <th className="w-8"></th>
                </tr>
              </thead>
              <tbody>
                {positionsVirtualised ? (
                  <>
                    {positionsPaddingTop > 0 && (
                      <tr aria-hidden="true" style={{ height: positionsPaddingTop }}>
                        <td colSpan={10} />
                      </tr>
                    )}
                    {positionsVirtualItems.map((vi) =>
                      renderPositionRow(sortedPositions[vi.index], vi.index, vi.index)
                    )}
                    {positionsPaddingBottom > 0 && (
                      <tr aria-hidden="true" style={{ height: positionsPaddingBottom }}>
                        <td colSpan={10} />
                      </tr>
                    )}
                  </>
                ) : (
                  sortedPositions.map((pos, idx) => renderPositionRow(pos, idx, null))
                )}
              </tbody>
            </table>
          </div>
            )
          })()
        )}
      </div>

      <GuidedTour tourId="portfolio" steps={portfolioTourSteps} />

      {livePosition && livePosition.trade_id && (
        <EditPositionPanel
          position={{
            trade_id: livePosition.trade_id,
            symbol: livePosition.symbol,
            side: livePosition.side,
            entry_price: livePosition.entry_price,
            current_price: livePosition.current_price,
            leverage: livePosition.leverage,
            exchange: livePosition.exchange,
            bot_name: livePosition.bot_name,
            demo_mode: livePosition.demo_mode,
            take_profit: livePosition.take_profit,
            stop_loss: livePosition.stop_loss,
            trailing_stop_active: livePosition.trailing_stop_active,
            trailing_stop_price: livePosition.trailing_stop_price,
            trailing_stop_distance_pct: livePosition.trailing_stop_distance_pct,
            trailing_atr_override: livePosition.trailing_atr_override,
            native_trailing_stop: livePosition.native_trailing_stop,
          }}
          onClose={() => setEditingPos(null)}
          onSave={async (data) => {
            if (!livePosition.trade_id) return
            await updateTpSl.mutateAsync({
              tradeId: livePosition.trade_id,
              data,
            })
          }}
        />
      )}
    </div>
  )
}

/* ── Tour Steps ───────────────────────────────────────────── */

const portfolioTourSteps: TourStep[] = [
  {
    target: '[data-tour="portfolio-summary"]',
    titleKey: 'tour.portfolioSummaryTitle',
    descriptionKey: 'tour.portfolioSummaryDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="portfolio-charts"]',
    titleKey: 'tour.portfolioChartsTitle',
    descriptionKey: 'tour.portfolioChartsDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="portfolio-positions"]',
    titleKey: 'tour.portfolioPositionsTitle',
    descriptionKey: 'tour.portfolioPositionsDesc',
    position: 'top',
  },
]
