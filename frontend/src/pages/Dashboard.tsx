import { useEffect, useState, useRef, useCallback, useMemo, Fragment } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { useDashboardStats, useDashboardDaily, usePortfolioPositions, useUpdateTpSl, useSyncTrades, queryKeys } from '../api/queries'
import { useFilterStore } from '../stores/filterStore'
import type { DailyStats, PortfolioPosition } from '../types'
import PnlChart from '../components/dashboard/PnlChart'
import WinLossChart from '../components/dashboard/WinLossChart'
import RevenueChart from '../components/dashboard/RevenueChart'
import { DashboardSkeleton } from '../components/ui/Skeleton'
import { ArrowUpRight, ArrowDownRight, TrendingUp, ChevronRight, ChevronUp, ChevronDown, ShieldCheck, Settings } from 'lucide-react'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import SizeValue from '../components/ui/SizeValue'
import { useSizeUnitStore } from '../stores/sizeUnitStore'
import GuidedTour, { TourHelpButton, type TourStep } from '../components/ui/GuidedTour'
import MobilePositionCard from '../components/ui/MobilePositionCard'
import EditPositionPanel from '../components/ui/EditPositionPanel'
import useIsMobile from '../hooks/useIsMobile'
import usePullToRefresh from '../hooks/usePullToRefresh'
import { useTradesSSE } from '../hooks/useTradesSSE'
import { useVisibleTab } from '../hooks/useIntervalPaused'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import PullToRefreshIndicator from '../components/ui/PullToRefreshIndicator'

/* ── Animated Number ─────────────────────────────────────── */

function AnimatedNumber({ value, prefix = '', suffix = '', decimals = 2 }: {
  value: number; prefix?: string; suffix?: string; decimals?: number
}) {
  const [display, setDisplay] = useState(0)
  const frameRef = useRef<number>(0)
  const displayRef = useRef(0)
  displayRef.current = display

  useEffect(() => {
    const duration = 600
    const startTime = performance.now()
    const startValue = displayRef.current

    const animate = (currentTime: number) => {
      const elapsed = currentTime - startTime
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(startValue + (value - startValue) * eased)

      if (progress < 1) {
        frameRef.current = requestAnimationFrame(animate)
      }
    }

    frameRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(frameRef.current)
  }, [value])

  return <>{prefix}{display.toFixed(decimals)}{suffix}</>
}

/* ── Stat Card ───────────────────────────────────────────── */

function StatCard({ label, value, numericValue, color, sub, isPositive }: {
  label: string; value: string; numericValue?: number; color?: string; sub?: string; isPositive?: boolean | null
}) {
  return (
    <div className="glass-card rounded-xl p-3 sm:p-5 group hover:border-white/10 transition-all duration-300 text-center">
      <div className="text-[10px] sm:text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">{label}</div>
      <div className={`text-lg sm:text-2xl font-bold mt-1 count-up flex items-center justify-center gap-1.5 ${color || 'text-white'}`}>
        {numericValue !== undefined ? (
          <AnimatedNumber value={numericValue} prefix="$" />
        ) : (
          value
        )}
        {isPositive === true && <ArrowUpRight size={18} className="text-profit" />}
        {isPositive === false && <ArrowDownRight size={18} className="text-loss" />}
      </div>
      {sub && <div className="text-[10px] sm:text-xs text-gray-400 mt-1.5 truncate">{sub}</div>}
    </div>
  )
}


const PERIODS = [7, 14, 30, 90] as const
const PERIOD_LABELS: Record<number, string> = { 7: 'dashboard.days7', 14: 'dashboard.days14', 30: 'dashboard.days30', 90: 'dashboard.days90' }

export default function Dashboard() {
  const { t } = useTranslation()
  useDocumentTitle(t('nav.dashboard'))
  const { demoFilter } = useFilterStore()
  const isMobile = useIsMobile()
  const [period, setPeriod] = useState<number>(30)
  const [editingPos, setEditingPos] = useState<PortfolioPosition | null>(null)
  const queryClient = useQueryClient()

  // Sync trades once per session
  const syncTrades = useSyncTrades()
  // Intentional: run once on mount. Excluding syncTrades — the mutation object
  // from react-query is a new reference on every render, so including it would
  // loop the sync. The sessionStorage guard ensures only one sync per session
  // even if the component remounts.
  useEffect(() => {
    const syncKey = 'trades_synced'
    if (!sessionStorage.getItem(syncKey)) {
      syncTrades.mutate(undefined, {
        onSettled: () => sessionStorage.setItem(syncKey, '1'),
      })
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Data fetching via React Query
  const statsQuery = useDashboardStats(period, demoFilter)
  const dailyQuery = useDashboardDaily(period, demoFilter)
  const positionsQuery = usePortfolioPositions()
  const { data: stats = null, isLoading: loadingStats, error: statsError } = statsQuery
  const { data: dailyData, isLoading: loadingDaily, error: dailyError } = dailyQuery
  const { data: positions = [], isLoading: loadingPositions } = positionsQuery
  const updateTpSl = useUpdateTpSl()

  // Gate the onboarding tour until the core queries have delivered real
  // content — otherwise the tour highlights empty skeleton elements.
  // If any query errors out we still allow auto-start so the user is not
  // locked out of the tutorial; the UI shows the error banner and the tour
  // can run alongside it.
  const dashboardReady =
    (statsQuery.isSuccess || statsQuery.isError) &&
    (dailyQuery.isSuccess || dailyQuery.isError) &&
    (positionsQuery.isSuccess || positionsQuery.isError)

  // Real-time trade updates via SSE (Issue #216 §2.2). Replaces the previous
  // 5-second polling loop; falls back to polling automatically if the
  // EventSource connection fails. Paused while the tab is backgrounded so
  // we don't keep hammering the API for a user who isn't looking (UX-M9).
  const tabVisible = useVisibleTab()
  useTradesSSE({ enabled: tabVisible })

  const dailyStats: DailyStats[] = dailyData?.days || []
  const loading = loadingStats || loadingDaily
  const error = statsError || dailyError ? t('common.error') : ''

  const refreshData = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats({ period, demoFilter }) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.daily({ period, demoFilter }) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.portfolio.positions }),
    ])
  }, [queryClient, period, demoFilter])

  const handleEditPosition = useCallback((pos: PortfolioPosition) => {
    setEditingPos(pos)
  }, [])

  // editingPos is a snapshot taken at click-time. Re-resolve against the
  // live positions cache so the modal reflects any updates (e.g. a cleared
  // SL from the previous Übernehmen). Without this the form fields show
  // stale values until the user reloads the whole page.
  const livePosition = editingPos?.trade_id
    ? positions.find(p => p.trade_id === editingPos.trade_id) ?? editingPos
    : null

  const { containerRef, refreshing, pullDistance } = usePullToRefresh({
    onRefresh: refreshData,
    disabled: !isMobile,
  })

  if (loading) {
    return <DashboardSkeleton />
  }

  return (
    <div ref={containerRef} style={{ overscrollBehavior: 'contain' }} className="animate-in" aria-busy={loading}>
      <PullToRefreshIndicator pullDistance={pullDistance} refreshing={refreshing} />
      {/* Error */}
      {error && (
        <div role="alert" className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-6">
        <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">{t('dashboard.title')}</h1>
        <div className="flex items-center gap-2">
        <TourHelpButton tourId="dashboard" />
        <div className="flex items-center gap-1.5 bg-white/5 rounded-xl p-0.5 border border-white/5" data-tour="dash-period">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              aria-label={t(PERIOD_LABELS[p])}
              className={`min-w-[4rem] sm:min-w-[4.5rem] px-2 sm:px-3 py-1.5 text-xs font-medium rounded-lg text-center transition-all duration-200 ${
                period === p
                  ? 'bg-gradient-to-r from-primary-600 to-primary-500 text-white shadow-glow-sm'
                  : 'text-gray-400 hover:text-white hover:bg-white/5'
              }`}
            >
              {t(PERIOD_LABELS[p])}
            </button>
          ))}
        </div>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 sm:gap-4 mb-6" data-tour="dash-stats" aria-live="polite">
        <StatCard
          label={t('dashboard.totalPnl')}
          value={stats ? `$${stats.net_pnl.toFixed(2)}` : '--'}
          numericValue={stats?.net_pnl}
          color={stats && stats.net_pnl >= 0 ? 'text-profit' : 'text-loss'}
          isPositive={stats ? stats.net_pnl >= 0 : null}
          sub={stats ? `${t('dashboard.fees')}: $${stats.total_fees.toFixed(2)} | ${t('dashboard.funding')}: $${stats.total_funding.toFixed(2)}` : undefined}
        />
        <StatCard
          label={t('dashboard.winRate')}
          value={stats ? `${stats.win_rate.toFixed(1)}%` : '--'}
          color={stats ? (stats.win_rate >= 60 ? 'text-profit' : stats.win_rate >= 40 ? 'text-yellow-400' : 'text-loss') : undefined}
          sub={stats ? `${stats.winning_trades}W / ${stats.losing_trades}L` : undefined}
        />
        <StatCard
          label={t('dashboard.bestTrade')}
          value={stats && stats.best_trade ? `+$${stats.best_trade.toFixed(2)}` : '--'}
          color="text-profit"
          isPositive={true}
        />
        <StatCard
          label={t('dashboard.worstTrade')}
          value={stats && stats.worst_trade ? `$${stats.worst_trade.toFixed(2)}` : '--'}
          color="text-loss"
          isPositive={false}
        />
      </div>

      {/* Charts Row 1: PnL + Win/Loss */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6" data-tour="dash-charts">
        <div className="lg:col-span-2 glass-card rounded-xl p-5">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-4">{t('dashboard.pnlOverTime')}</h3>
          <PnlChart data={dailyStats} />
        </div>
        <div className="glass-card rounded-xl p-5">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-4">{t('dashboard.winLoss')}</h3>
          <WinLossChart
            wins={stats?.winning_trades || 0}
            losses={stats?.losing_trades || 0}
            winRate={stats?.win_rate || 0}
          />
        </div>
      </div>

      {/* Revenue Section (Builder Fees) */}
      {dailyStats.some(d => (d.builder_fees || 0) > 0) && (
        <div className="glass-card rounded-xl p-5 mb-6">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 mb-4">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
              {t('dashboard.revenueTitle')}
            </h3>
            {stats && (stats.total_builder_fees || 0) > 0 && (
              <div className="flex flex-wrap items-center gap-2 sm:gap-4 text-xs">
                <span className="text-gray-400">
                  {t('dashboard.totalBuilderFees')}: <span className="text-emerald-400 font-medium">${stats.total_builder_fees.toFixed(4)}</span>
                </span>
                <span className="text-gray-400">
                  {t('dashboard.monthlyEstimate')}: <span className="text-emerald-400 font-medium">${((stats.total_builder_fees / period) * 30).toFixed(2)}/mo</span>
                </span>
              </div>
            )}
          </div>
          <RevenueChart data={dailyStats} />
        </div>
      )}

      {/* Recent trades */}
      <DashboardOpenPositions
        positions={demoFilter === 'all' ? positions : positions.filter(p => demoFilter === 'demo' ? p.demo_mode : !p.demo_mode)}
        loading={loadingPositions}
        onEditPosition={handleEditPosition}
      />

      {/* Guided Tour — auto-start only once the core queries have data so
          the highlighted targets contain real content, not skeletons. */}
      <GuidedTour tourId="dashboard" steps={dashboardTourSteps} autoStart={dashboardReady} />

      {/* Edit TP/SL Panel — rendered at top level for correct z-index */}
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

function DashboardOpenPositions({ positions, loading, onEditPosition }: { positions: PortfolioPosition[]; loading: boolean; onEditPosition: (pos: PortfolioPosition) => void }) {
  const { t } = useTranslation()
  const isMobile = useIsMobile()
  const { unit: sizeUnit, toggle: toggleSizeUnit } = useSizeUnitStore()
  const [sortAsc, setSortAsc] = useState(false)
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  const sortedPositions = useMemo(() =>
    [...positions].sort((a, b) =>
      sortAsc
        ? a.unrealized_pnl - b.unrealized_pnl
        : b.unrealized_pnl - a.unrealized_pnl
    ), [positions, sortAsc]
  )

  return (
    <div className="glass-card rounded-2xl overflow-hidden min-w-0" data-tour="dash-trades">
      <div className="p-5 border-b border-white/5 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-white flex items-center gap-2">
          <TrendingUp size={16} className="text-primary-400" />
          {t('portfolio.positions')}
        </h2>
      </div>
      {loading ? (
        <div className="p-8 flex items-center justify-center">
          <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : sortedPositions.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <TrendingUp className="w-12 h-12 text-gray-600 dark:text-gray-600 mb-3" />
          <p className="text-gray-500 dark:text-gray-400 font-medium">{t('dashboard.noPositionsTitle')}</p>
          <p className="text-gray-400 dark:text-gray-500 text-sm mt-1">{t('dashboard.noPositionsHint')}</p>
        </div>
      ) : isMobile ? (
        <div className="px-1 pb-1 pt-1 space-y-1.5">
          {sortedPositions.map((pos, idx) => (
            <MobilePositionCard key={`${pos.exchange}-${pos.symbol}-${idx}`} pos={pos} />
          ))}
        </div>
      ) : (
        <div className="overflow-x-auto">
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
              {sortedPositions.map((pos, idx) => (
                <Fragment key={`${pos.exchange}-${pos.symbol}-${idx}`}>
                  <tr
                    tabIndex={0}
                    aria-expanded={expandedIdx === idx}
                    onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setExpandedIdx(expandedIdx === idx ? null : idx)
                      }
                    }}
                    className="cursor-pointer"
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
                          onClick={(e) => { e.stopPropagation(); onEditPosition(pos) }}
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
              ))}
            </tbody>
          </table>
        </div>
      )}

    </div>
  )
}

const dashboardTourSteps: TourStep[] = [
  {
    target: '[data-tour="dash-stats"]',
    titleKey: 'tour.dashPnlTitle',
    descriptionKey: 'tour.dashPnlDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="dash-charts"]',
    titleKey: 'tour.dashChartsTitle',
    descriptionKey: 'tour.dashChartsDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="dash-trades"]',
    titleKey: 'tour.dashTradesTitle',
    descriptionKey: 'tour.dashTradesDesc',
    position: 'top',
  },
]
