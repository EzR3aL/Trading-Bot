import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import api from '../api/client'

/* ── Color palette for bot lines ─────────────────────────── */
const BOT_COLORS = [
  '#22c55e', '#3b82f6', '#f59e0b', '#ef4444', '#a855f7',
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

export default function BotPerformance() {
  const { t } = useTranslation()
  const [days, setDays] = useState(30)
  const [compareData, setCompareData] = useState<BotCompareData[]>([])
  const [selectedBot, setSelectedBot] = useState<number | null>(null)
  const [botDetail, setBotDetail] = useState<BotDetailStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadCompareData()
  }, [days])

  useEffect(() => {
    if (selectedBot) loadBotDetail(selectedBot)
    else setBotDetail(null)
  }, [selectedBot, days])

  const loadCompareData = async () => {
    setLoading(true)
    try {
      const res = await api.get(`/bots/compare/performance?days=${days}`)
      setCompareData(res.data.bots || [])
    } catch { /* ignore */ }
    setLoading(false)
  }

  const loadBotDetail = async (botId: number) => {
    try {
      const res = await api.get(`/bots/${botId}/statistics?days=${days}`)
      setBotDetail(res.data)
    } catch { /* ignore */ }
  }

  // Build chart data: merge all bot series into one array keyed by date
  const chartData = (() => {
    const dateMap: Record<string, Record<string, number>> = {}
    compareData.forEach((bot, i) => {
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
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">{t('performance.title')}</h1>
        <div className="flex gap-2">
          {[7, 14, 30, 90].map((d) => (
            <button key={d} onClick={() => setDays(d)}
              className={`px-3 py-1.5 text-sm rounded ${days === d ? 'bg-primary-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}>
              {d}d
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="text-gray-500 text-center py-12">{t('common.loading')}</div>
      ) : compareData.length === 0 ? (
        <div className="text-gray-500 text-center py-12">{t('performance.noData')}</div>
      ) : (
        <>
          {/* Multi-bot PnL Chart */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 mb-6">
            <h2 className="text-sm font-medium text-gray-400 mb-4">{t('performance.cumulativePnl')}</h2>
            <ResponsiveContainer width="100%" height={350}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: 11 }} />
                <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} tickFormatter={(v) => `$${v}`} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                  labelStyle={{ color: '#9ca3af' }}
                  formatter={(value: number, name: string) => {
                    const bot = compareData.find(b => `bot_${b.bot_id}` === name)
                    return [`$${value.toFixed(2)}`, bot?.name || name]
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
          <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden mb-6">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">{t('performance.bot')}</th>
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">{t('performance.direction')}</th>
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">{t('performance.confidence')}</th>
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">{t('performance.winRate')}</th>
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">{t('performance.trades')}</th>
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">{t('performance.pnl')}</th>
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">{t('performance.strategy')}</th>
                </tr>
              </thead>
              <tbody>
                {compareData.map((bot, i) => (
                  <tr
                    key={bot.bot_id}
                    onClick={() => setSelectedBot(selectedBot === bot.bot_id ? null : bot.bot_id)}
                    className={`border-b border-gray-800/50 cursor-pointer transition-colors ${
                      selectedBot === bot.bot_id ? 'bg-primary-900/20' : 'hover:bg-gray-800/50'
                    }`}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: BOT_COLORS[i % BOT_COLORS.length] }} />
                        <span className="text-white font-medium">{bot.name}</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded ${bot.mode === 'live' ? 'bg-green-900/40 text-green-400' : 'bg-yellow-900/40 text-yellow-400'}`}>
                          {bot.mode}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {bot.last_direction ? (
                        <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                          bot.last_direction === 'LONG' ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'
                        }`}>
                          {bot.last_direction}
                        </span>
                      ) : <span className="text-gray-600">—</span>}
                    </td>
                    <td className="px-4 py-3 text-gray-300">
                      {bot.last_confidence != null ? `${bot.last_confidence}%` : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <span className={bot.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}>
                        {bot.win_rate}%
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-300">
                      {bot.wins} / {bot.total_trades}
                    </td>
                    <td className="px-4 py-3">
                      <span className={bot.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                        ${bot.total_pnl.toFixed(2)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">{bot.strategy_type}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Bot Detail Panel */}
          {botDetail && (
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
              <h2 className="text-white font-semibold mb-4">{botDetail.bot_name} — {t('performance.details')}</h2>

              {/* Summary Cards */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
                {[
                  { label: t('performance.totalPnl'), value: `$${botDetail.summary.total_pnl.toFixed(2)}`, color: botDetail.summary.total_pnl >= 0 ? 'text-green-400' : 'text-red-400' },
                  { label: t('performance.winRate'), value: `${botDetail.summary.win_rate}%`, color: botDetail.summary.win_rate >= 50 ? 'text-green-400' : 'text-red-400' },
                  { label: t('performance.bestTrade'), value: `$${botDetail.summary.best_trade.toFixed(2)}`, color: 'text-green-400' },
                  { label: t('performance.worstTrade'), value: `$${botDetail.summary.worst_trade.toFixed(2)}`, color: 'text-red-400' },
                ].map((card) => (
                  <div key={card.label} className="bg-gray-800 rounded-lg p-3">
                    <div className="text-xs text-gray-500 mb-1">{card.label}</div>
                    <div className={`text-lg font-bold ${card.color}`}>{card.value}</div>
                  </div>
                ))}
              </div>

              {/* Bot PnL Chart */}
              {botDetail.daily_series.length > 0 && (
                <div className="mb-5">
                  <ResponsiveContainer width="100%" height={200}>
                    <LineChart data={botDetail.daily_series}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                      <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: 10 }} />
                      <YAxis tick={{ fill: '#6b7280', fontSize: 10 }} tickFormatter={(v) => `$${v}`} />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                        formatter={(value: number, name: string) => {
                          const labels: Record<string, string> = { cumulative_pnl: 'Kumulativ', pnl: 'PnL' }
                          return [`$${value.toFixed(2)}`, labels[name] || name]
                        }}
                      />
                      <Line type="monotone" dataKey="cumulative_pnl" stroke="#22c55e" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="pnl" stroke="#6366f1" strokeWidth={1} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              {/* Recent Trades */}
              <h3 className="text-sm font-medium text-gray-400 mb-2">{t('performance.recentTrades')}</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-gray-800">
                      <th className="text-left px-3 py-2 text-gray-500">Symbol</th>
                      <th className="text-left px-3 py-2 text-gray-500">{t('trades.side')}</th>
                      <th className="text-left px-3 py-2 text-gray-500">{t('trades.entryPrice')}</th>
                      <th className="text-left px-3 py-2 text-gray-500">{t('trades.exitPrice')}</th>
                      <th className="text-left px-3 py-2 text-gray-500">PnL</th>
                      <th className="text-left px-3 py-2 text-gray-500">{t('trades.status')}</th>
                      <th className="text-left px-3 py-2 text-gray-500">{t('trades.date')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {botDetail.recent_trades.map((trade) => (
                      <tr key={trade.id} className="border-b border-gray-800/50">
                        <td className="px-3 py-2 text-white">{trade.symbol}</td>
                        <td className="px-3 py-2">
                          <span className={trade.side === 'long' ? 'text-green-400' : 'text-red-400'}>
                            {trade.side.toUpperCase()}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-gray-300">${trade.entry_price.toFixed(2)}</td>
                        <td className="px-3 py-2 text-gray-300">{trade.exit_price ? `$${trade.exit_price.toFixed(2)}` : '—'}</td>
                        <td className={`px-3 py-2 ${trade.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          ${trade.pnl.toFixed(2)}
                        </td>
                        <td className="px-3 py-2">
                          <span className={`px-1.5 py-0.5 rounded text-xs ${
                            trade.status === 'open' ? 'bg-blue-900/40 text-blue-400' : 'bg-gray-800 text-gray-400'
                          }`}>
                            {trade.status}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-gray-500">
                          {trade.entry_time ? new Date(trade.entry_time).toLocaleDateString() : '—'}
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
