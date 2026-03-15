import { Fragment, useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, Legend,
} from 'recharts'
import {
  Briefcase, ArrowUpRight, ArrowDownRight, TrendingUp,
  ChevronUp, ChevronDown, ChevronRight, ShieldCheck,
} from 'lucide-react'
import api from '../api/client'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import type {
  PortfolioSummary, PortfolioPosition,
  PortfolioDaily, PortfolioAllocation,
} from '../types'

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
  if (!active || !payload?.length) return null
  return (
    <div className="bg-[#0d1117]/95 border border-white/10 rounded-lg px-3 py-2 text-xs shadow-xl backdrop-blur-sm">
      <div className="text-gray-400 mb-1">{label}</div>
      {payload.map((entry: any) => (
        <div key={entry.dataKey} className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full" style={{ background: entry.color }} />
          <span className="text-gray-300">{entry.name}:</span>
          <span className={entry.value >= 0 ? 'text-emerald-400' : 'text-red-400'}>
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

  // Data state
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [positions, setPositions] = useState<PortfolioPosition[]>([])
  const [dailyData, setDailyData] = useState<PortfolioDaily[]>([])
  const [allocation, setAllocation] = useState<PortfolioAllocation[]>([])
  const [period, setPeriod] = useState<number>(30)
  const [loading, setLoading] = useState(true)
  const [loadingExchange, setLoadingExchange] = useState(true)
  const [error, setError] = useState('')

  // Sorting state for positions
  const [sortAsc, setSortAsc] = useState(false)
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  /* ── Data Fetching ──────────────────────────────────────── */

  // Phase 1: Fast DB queries (summary + daily) -- renders page instantly
  useEffect(() => {
    const loadFast = async () => {
      setLoading(true)
      setError('')
      try {
        const [sumRes, dailyRes] = await Promise.all([
          api.get(`/portfolio/summary?days=${period}`),
          api.get(`/portfolio/daily?days=${period}`),
        ])
        setSummary(sumRes.data)
        setDailyData(dailyRes.data.daily || dailyRes.data || [])
      } catch {
        setError(t('common.error'))
      } finally {
        setLoading(false)
      }
    }
    loadFast()
  }, [period, t])

  // Phase 2: Slow exchange API calls (positions + allocation) -- loads in background
  useEffect(() => {
    const loadExchange = async () => {
      setLoadingExchange(true)
      try {
        const [posRes, allocRes] = await Promise.all([
          api.get('/portfolio/positions'),
          api.get('/portfolio/allocation'),
        ])
        setPositions(posRes.data.positions || posRes.data || [])
        setAllocation(allocRes.data.allocations || allocRes.data || [])
      } catch {
        // Exchange data is optional -- don't block the page
      } finally {
        setLoadingExchange(false)
      }
    }
    loadExchange()
  }, [t])

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

  // Sorted positions
  const sortedPositions = [...positions].sort((a, b) =>
    sortAsc
      ? a.unrealized_pnl - b.unrealized_pnl
      : b.unrealized_pnl - a.unrealized_pnl
  )

  // Pie chart data
  const pieData = allocation.map((a) => ({
    name: a.exchange,
    value: a.balance,
  }))

  // Merge exchange cards: DB trades + live balances (so all exchanges appear)
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

  /* ── Loading State ──────────────────────────────────────── */

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  /* ── Render ─────────────────────────────────────────────── */

  return (
    <div className="animate-in">
      {/* Error */}
      {error && (
        <div role="alert" className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
            <Briefcase size={24} className="text-primary-400" />
            {t('portfolio.title')}
          </h1>
          <p className="text-sm text-gray-400 mt-1">{t('portfolio.subtitle')}</p>
        </div>
        <div className="flex items-center gap-1.5 bg-white/5 rounded-xl p-0.5 border border-white/5">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 ${
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

      {/* Summary Hero */}
      <div className="glass-card rounded-2xl p-6 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-5 gap-6">
          {/* Total Balance */}
          <div className="md:col-span-2">
            <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">
              {t('portfolio.totalBalance')}
            </div>
            <div className="text-3xl font-bold text-white flex items-center gap-3">
              ${totalBalance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              {loadingExchange && (
                <div className="w-4 h-4 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
              )}
            </div>
            {summary && (
              <div className={`flex items-center gap-1 mt-1 text-sm ${summary.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
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
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        {/* Stacked Area Chart */}
        <div className="lg:col-span-2 glass-card rounded-2xl p-5">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-4">
            {t('portfolio.dailyChart')}
          </h3>
          {chartData.rows.length === 0 ? (
            <div className="flex items-center justify-center h-48 text-gray-500 text-sm">
              {t('portfolio.noData')}
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
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis
                  dataKey="date"
                  stroke="rgba(255,255,255,0.3)"
                  tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  stroke="rgba(255,255,255,0.3)"
                  tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v: number) => `$${v}`}
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
            <div className="flex items-center justify-center h-48 text-gray-500 text-sm">
              {t('portfolio.noData')}
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
                >
                  {pieData.map((entry, idx) => (
                    <Cell
                      key={idx}
                      fill={exchangeColor(entry.name)}
                    />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(value: number, name: string) => [
                    `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                    name.charAt(0).toUpperCase() + name.slice(1),
                  ]}
                  contentStyle={{
                    background: 'rgba(13,17,23,0.95)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: '8px',
                    fontSize: '12px',
                  }}
                  itemStyle={{ color: 'rgba(255,255,255,0.8)' }}
                />
                <Legend
                  verticalAlign="bottom"
                  iconType="circle"
                  iconSize={8}
                  formatter={(value: string) => (
                    <span className="text-xs text-gray-300 capitalize">{value}</span>
                  )}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Positions Table */}
      <div className="glass-card rounded-2xl overflow-hidden">
        <div className="p-5 border-b border-white/5 flex items-center justify-between">
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
          <div className="p-8 text-center text-gray-500">{t('portfolio.noPositions')}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="table-premium">
              <thead>
                <tr>
                  <th className="text-left">{t('portfolio.exchange')}</th>
                  <th className="text-left">{t('portfolio.symbol')}</th>
                  <th className="text-center">{t('portfolio.side')}</th>
                  <th className="text-right hidden xl:table-cell">{t('portfolio.size')}</th>
                  <th className="text-right hidden lg:table-cell">{t('portfolio.entryPrice')}</th>
                  <th className="text-right hidden lg:table-cell">{t('portfolio.currentPrice')}</th>
                  <th className="text-right">
                    <button
                      onClick={() => setSortAsc(!sortAsc)}
                      className="inline-flex items-center gap-1 hover:text-white transition-colors"
                    >
                      {t('portfolio.pnl')}
                      {sortAsc ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                    </button>
                  </th>
                  <th className="text-center hidden 2xl:table-cell">{t('portfolio.leverage')}</th>
                  <th className="text-center hidden xl:table-cell">{t('bots.trailingStop')}</th>
                </tr>
              </thead>
              <tbody>
                {sortedPositions.map((pos, idx) => (
                  <Fragment key={`${pos.exchange}-${pos.symbol}-${idx}`}>
                    <tr
                      onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
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
                      <td className="text-right text-gray-300 text-sm font-mono hidden xl:table-cell">
                        {pos.size.toFixed(4)}
                      </td>
                      <td className="text-right text-gray-300 text-sm font-mono hidden lg:table-cell">
                        ${pos.entry_price.toLocaleString()}
                      </td>
                      <td className="text-right text-gray-300 text-sm font-mono hidden lg:table-cell">
                        ${pos.current_price.toLocaleString()}
                      </td>
                      <td className={`text-right text-sm font-medium font-mono ${
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
                    </tr>
                    {expandedIdx === idx && (
                      <tr className="table-expand-row">
                        <td colSpan={9} className="!p-0 !border-b-0">
                          <dl className="table-expand-content">
                            <div className="xl:hidden">
                              <dt>{t('portfolio.size')}</dt>
                              <dd>{pos.size.toFixed(4)}</dd>
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
    </div>
  )
}
