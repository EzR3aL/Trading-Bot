import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Area, AreaChart } from 'recharts'
import api from '../api/client'
import { useFilterStore } from '../stores/filterStore'
import { SkeletonChart, SkeletonTable } from '../components/ui/Skeleton'

/* ── Color palette for bot lines ─────────────────────────── */
const BOT_COLORS = [
  '#00e676', '#3b82f6', '#f59e0b', '#ff5252', '#a855f7',
  '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#6366f1',
]

interface BotCompareData {
  bot_id: number
  name: string
  strategy_type: string
  exchange_type: string
  mode: string
  total_trades: number
  total_pnl: number
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
    avg_pnl: number
    best_trade: number
    worst_trade: number
  }
  daily_series: { date: string; pnl: number; cumulative_pnl: number; trades: number; wins: number }[]
  recent_trades: {
    id: number; symbol: string; side: string; entry_price: number; exit_price: number | null
    pnl: number; pnl_percent: number; confidence: number; status: string
    demo_mode: boolean; entry_time: string | null; exit_time: string | null; exit_reason: string | null
  }[]
}

function formatPnl(value: number): string {
  const prefix = value >= 0 ? '+' : ''
  return `${prefix}$${value.toFixed(2)}`
}

export default function BotPerformance() {
  const { t } = useTranslation()
  const { demoFilter } = useFilterStore()
  const [days, setDays] = useState(30)
  const [compareData, setCompareData] = useState<BotCompareData[]>([])
  const [selectedBot, setSelectedBot] = useState<number | null>(null)
  const [botDetail, setBotDetail] = useState<BotDetailStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [detailError, setDetailError] = useState('')

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

  // Build chart data
  const chartData = (() => {
    const dateMap: Record<string, Record<string, number>> = {}
    compareData.forEach((bot) => {
      bot.series.forEach((pt) => {
        if (!dateMap[pt.date]) dateMap[pt.date] = {}
        dateMap[pt.date][`bot_${bot.bot_id}`] = pt.cumulative_pnl
      })
    })
    return Object.entries(dateMap)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, values]) => ({ date, ...values }))
  })()

  return (
    <div className="animate-in">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white tracking-tight">{t('performance.title')}</h1>
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
          {/* Multi-bot PnL Chart */}
          <div className="glass-card rounded-xl p-5 mb-6">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-4">{t('performance.cumulativePnl')}</h2>
            <ResponsiveContainer width="100%" height={350}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: 11 }} tickLine={false} />
                <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} tickLine={false} tickFormatter={(v) => `$${v}`} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'rgba(17, 24, 39, 0.95)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: 12,
                    backdropFilter: 'blur(10px)',
                  }}
                  labelStyle={{ color: '#9ca3af' }}
                  formatter={(value: number, name: string) => {
                    const bot = compareData.find(b => `bot_${b.bot_id}` === name)
                    return [formatPnl(value), bot?.name || name]
                  }}
                />
                <Legend formatter={(value) => {
                  const bot = compareData.find(b => `bot_${b.bot_id}` === value)
                  return bot?.name || value
                }} />
                {compareData.map((bot, i) => (
                  <Line
                    key={bot.bot_id}
                    type="monotone"
                    dataKey={`bot_${bot.bot_id}`}
                    stroke={BOT_COLORS[i % BOT_COLORS.length]}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    connectNulls
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Agent Table */}
          <div className="glass-card rounded-xl overflow-hidden mb-6">
            <table className="table-premium">
              <thead>
                <tr>
                  <th className="text-left">{t('performance.bot')}</th>
                  <th className="text-left">{t('performance.direction')}</th>
                  <th className="text-left">{t('performance.confidence')}</th>
                  <th className="text-left">{t('performance.winRate')}</th>
                  <th className="text-left">{t('performance.trades')}</th>
                  <th className="text-left">{t('performance.pnl')}</th>
                  <th className="text-left">{t('performance.strategy')}</th>
                </tr>
              </thead>
              <tbody>
                {compareData.map((bot, i) => (
                  <tr
                    key={bot.bot_id}
                    onClick={() => setSelectedBot(selectedBot === bot.bot_id ? null : bot.bot_id)}
                    role="button"
                    tabIndex={0}
                    aria-label={`${t('performance.details')}: ${bot.name}`}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setSelectedBot(selectedBot === bot.bot_id ? null : bot.bot_id)
                      }
                    }}
                    className={`cursor-pointer transition-all duration-200 ${
                      selectedBot === bot.bot_id
                        ? '!bg-primary-500/10 border-l-2 border-l-primary-500'
                        : 'hover:!bg-white/[0.04]'
                    }`}
                  >
                    <td>
                      <div className="flex items-center gap-2.5">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: BOT_COLORS[i % BOT_COLORS.length] }} />
                        <span className="text-white font-medium">{bot.name}</span>
                        <span className={bot.mode === 'live' ? 'badge-live' : 'badge-demo'}>
                          {bot.mode}
                        </span>
                      </div>
                    </td>
                    <td>
                      {bot.last_direction ? (
                        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                          bot.last_direction === 'LONG' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
                        }`}>
                          {bot.last_direction === 'LONG' ? '+' : '-'} {bot.last_direction}
                        </span>
                      ) : <span className="text-gray-600">--</span>}
                    </td>
                    <td className="text-gray-300">
                      {bot.last_confidence != null ? `${bot.last_confidence}%` : '--'}
                    </td>
                    <td>
                      <span className={bot.win_rate >= 50 ? 'text-profit' : 'text-loss'}>
                        {bot.win_rate}%
                      </span>
                    </td>
                    <td className="text-gray-300">
                      {bot.wins} / {bot.total_trades}
                    </td>
                    <td>
                      <span className={bot.total_pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}>
                        {formatPnl(bot.total_pnl)}
                      </span>
                    </td>
                    <td className="text-gray-500 text-xs">{bot.strategy_type}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Detail Error */}
          {detailError && (
            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
              {detailError}
            </div>
          )}

          {/* Bot Detail Panel */}
          {botDetail && (
            <div className="glass-card rounded-xl p-5 slide-in-panel">
              <h2 className="text-white font-semibold mb-4">{botDetail.bot_name} -- {t('performance.details')}</h2>

              {/* Summary Cards */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
                {[
                  {
                    label: t('performance.totalPnl'),
                    value: formatPnl(botDetail.summary.total_pnl),
                    color: botDetail.summary.total_pnl >= 0 ? 'text-profit' : 'text-loss',
                  },
                  {
                    label: t('performance.winRate'),
                    value: `${botDetail.summary.win_rate}%`,
                    color: botDetail.summary.win_rate >= 50 ? 'text-profit' : 'text-loss',
                  },
                  {
                    label: t('performance.bestTrade'),
                    value: formatPnl(botDetail.summary.best_trade),
                    color: 'text-profit',
                  },
                  {
                    label: t('performance.worstTrade'),
                    value: formatPnl(botDetail.summary.worst_trade),
                    color: 'text-loss',
                  },
                ].map((card) => (
                  <div key={card.label} className="bg-white/5 rounded-xl p-3 border border-white/5">
                    <div className="text-[10px] text-gray-500 mb-1 uppercase tracking-wider font-medium">{card.label}</div>
                    <div className={`text-lg font-bold ${card.color}`}>{card.value}</div>
                  </div>
                ))}
              </div>

              {/* Bot PnL Chart */}
              {botDetail.daily_series.length > 0 && (
                <div className="mb-5">
                  <ResponsiveContainer width="100%" height={200}>
                    <AreaChart data={botDetail.daily_series}>
                      <defs>
                        <linearGradient id="detailGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#00e676" stopOpacity={0.2} />
                          <stop offset="95%" stopColor="#00e676" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                      <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: 10 }} tickLine={false} />
                      <YAxis tick={{ fill: '#6b7280', fontSize: 10 }} tickLine={false} tickFormatter={(v) => `$${v}`} />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: 'rgba(17, 24, 39, 0.95)',
                          border: '1px solid rgba(255,255,255,0.1)',
                          borderRadius: 12,
                        }}
                        formatter={(value: number, name: string) => {
                          const labels: Record<string, string> = {
                            cumulative_pnl: t('performance.cumulative'),
                            pnl: 'PnL',
                          }
                          return [formatPnl(value), labels[name] || name]
                        }}
                      />
                      <Area
                        type="monotone"
                        dataKey="cumulative_pnl"
                        stroke="#00e676"
                        strokeWidth={2}
                        fill="url(#detailGradient)"
                      />
                      <Line type="monotone" dataKey="pnl" stroke="#6366f1" strokeWidth={1} dot={false} />
                    </AreaChart>
                  </ResponsiveContainer>
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
                          <span className={trade.pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}>
                            {formatPnl(trade.pnl)}
                          </span>
                        </td>
                        <td>
                          <span className={trade.status === 'open' ? 'badge-open' : 'badge-neutral'}>
                            {trade.status}
                          </span>
                        </td>
                        <td className="text-gray-500 text-xs">
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
