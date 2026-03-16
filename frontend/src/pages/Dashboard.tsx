import { Fragment, useEffect, useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../api/client'
import { useFilterStore } from '../stores/filterStore'
import type { Statistics, Trade, DailyStats } from '../types'
import PnlChart from '../components/dashboard/PnlChart'
import WinLossChart from '../components/dashboard/WinLossChart'
import RevenueChart from '../components/dashboard/RevenueChart'
import { DashboardSkeleton } from '../components/ui/Skeleton'
import PnlCell from '../components/ui/PnlCell'
import { ArrowUpRight, ArrowDownRight, ChevronRight } from 'lucide-react'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import GuidedTour, { TourHelpButton, type TourStep } from '../components/ui/GuidedTour'
import { formatDate, formatTime } from '../utils/dateUtils'
import MobileTradeCard from '../components/ui/MobileTradeCard'
import useIsMobile from '../hooks/useIsMobile'

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
  const { demoFilter } = useFilterStore()
  const [stats, setStats] = useState<Statistics | null>(null)
  const [dailyStats, setDailyStats] = useState<DailyStats[]>([])
  const [recentTrades, setRecentTrades] = useState<Trade[]>([])
  const [period, setPeriod] = useState<number>(30)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        await api.post('/trades/sync').catch((err) => { console.error('Failed to sync trades:', err) })

        const demoParam = demoFilter === 'demo' ? '&demo_mode=true' : demoFilter === 'live' ? '&demo_mode=false' : ''
        const [statsRes, dailyRes, tradesRes] = await Promise.all([
          api.get(`/statistics?days=${period}${demoParam}`),
          api.get(`/statistics/daily?days=${period}${demoParam}`),
          api.get(`/trades?per_page=10&status=closed${demoParam}`),
        ])
        setStats(statsRes.data)
        setDailyStats(dailyRes.data.days)
        setRecentTrades(tradesRes.data.trades)
      } catch {
        setError(t('common.error'))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [period, demoFilter, t])

  if (loading) {
    return <DashboardSkeleton />
  }

  return (
    <div className="animate-in">
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
      <DashboardRecentTrades trades={recentTrades} />

      {/* Guided Tour */}
      <GuidedTour tourId="dashboard" steps={dashboardTourSteps} />
    </div>
  )
}

function DashboardRecentTrades({ trades }: { trades: Trade[] }) {
  const { t } = useTranslation()
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const isMobile = useIsMobile()

  return (
    <div className="glass-card rounded-xl overflow-hidden" data-tour="dash-trades">
      <div className="px-4 sm:px-5 pt-4 sm:pt-5 pb-3 sm:pb-4 sm:border-b sm:border-white/5">
        <h2 className="text-base font-semibold text-white">
          {t('dashboard.recentTrades')}
        </h2>
      </div>
      {/* Mobile: Card layout */}
      {isMobile ? (
        <div className="px-1 pb-1 pt-1 space-y-1.5">
          {trades.length === 0 ? (
            <p className="py-8 text-center text-gray-500 text-sm">{t('dashboard.noTrades')}</p>
          ) : (
            trades.map((trade) => <MobileTradeCard key={trade.id} trade={trade} />)
          )}
        </div>
      ) : (
      /* Desktop: Table layout */
      <div className="overflow-x-auto">
        <table className="table-premium">
          <thead>
            <tr>
              <th className="text-left">{t('trades.date')}</th>
              <th className="text-left hidden xl:table-cell">{t('trades.bot')}</th>
              <th className="text-center hidden lg:table-cell">{t('trades.exchange')}</th>
              <th className="text-left">{t('trades.symbol')}</th>
              <th className="text-center">{t('trades.side')}</th>
              <th className="text-right hidden xl:table-cell">{t('trades.entryPrice')}</th>
              <th className="text-right">{t('trades.pnl')}</th>
              <th className="text-center hidden 2xl:table-cell">{t('trades.mode')}</th>
              <th className="text-center">{t('trades.status')}</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr>
                <td colSpan={9} className="p-8 text-center text-gray-500">
                  {t('dashboard.noTrades')}
                </td>
              </tr>
            ) : (
              trades.map((trade) => (
                <Fragment key={trade.id}>
                  <tr
                    onClick={() => setExpandedId(expandedId === trade.id ? null : trade.id)}
                    className="cursor-pointer"
                  >
                    <td className="text-gray-300">
                      <span className="inline-flex items-center">
                        <ChevronRight size={14} className={`expand-chevron ${expandedId === trade.id ? 'open' : ''}`} />
                        <span title={formatTime(trade.entry_time)}>{formatDate(trade.entry_time)}</span>
                      </span>
                    </td>
                    <td className="hidden xl:table-cell">
                      {trade.bot_name ? (
                        <span className="text-white font-medium text-xs">{trade.bot_name}</span>
                      ) : (
                        <span className="text-gray-600">--</span>
                      )}
                    </td>
                    <td className="text-center hidden lg:table-cell">
                      <span className="inline-flex justify-center">
                        <ExchangeIcon exchange={trade.bot_exchange || trade.exchange} size={18} />
                      </span>
                    </td>
                    <td className="text-white font-medium">{trade.symbol}</td>
                    <td className="text-center">
                      <span className={trade.side === 'long' ? 'text-profit' : 'text-loss'}>
                        {trade.side === 'long' ? '+' : '-'} {trade.side.toUpperCase()}
                      </span>
                    </td>
                    <td className="text-right text-gray-300 hidden xl:table-cell">
                      ${trade.entry_price.toLocaleString()}
                    </td>
                    <td className="text-right">
                      <PnlCell
                        pnl={trade.pnl}
                        fees={trade.fees}
                        fundingPaid={trade.funding_paid}
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
                  {expandedId === trade.id && (
                    <tr className="table-expand-row">
                      <td colSpan={9} className="!p-0 !border-b-0">
                        <dl className="table-expand-content">
                          <div className="xl:hidden">
                            <dt>{t('trades.bot')}</dt>
                            <dd>{trade.bot_name || '--'}</dd>
                          </div>
                          <div className="lg:hidden">
                            <dt>{t('trades.exchange')}</dt>
                            <dd className="capitalize">{trade.bot_exchange || trade.exchange}</dd>
                          </div>
                          <div className="xl:hidden">
                            <dt>{t('trades.entryPrice')}</dt>
                            <dd>${trade.entry_price.toLocaleString()}</dd>
                          </div>
                          <div>
                            <dt>{t('trades.exitPrice')}</dt>
                            <dd>{trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}</dd>
                          </div>
                          <div className="2xl:hidden">
                            <dt>{t('trades.mode')}</dt>
                            <dd>{trade.demo_mode ? t('common.demo') : t('common.live')}</dd>
                          </div>
                        </dl>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))
            )}
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
