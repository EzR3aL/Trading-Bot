import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../api/client'
import type { Statistics, Trade, BotStatus, DailyStats } from '../types'
import PnlChart from '../components/dashboard/PnlChart'
import WinLossChart from '../components/dashboard/WinLossChart'
import FeesChart from '../components/dashboard/FeesChart'

function StatCard({ label, value, color, sub }: { label: string; value: string; color?: string; sub?: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <div className="text-sm text-gray-400">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${color || 'text-white'}`}>
        {value}
      </div>
      {sub && <div className="text-xs text-gray-500 mt-0.5">{sub}</div>}
    </div>
  )
}

const PERIODS = [7, 14, 30, 90] as const

export default function Dashboard() {
  const { t } = useTranslation()
  const [stats, setStats] = useState<Statistics | null>(null)
  const [dailyStats, setDailyStats] = useState<DailyStats[]>([])
  const [recentTrades, setRecentTrades] = useState<Trade[]>([])
  const [botStatus, setBotStatus] = useState<BotStatus | null>(null)
  const [period, setPeriod] = useState<number>(30)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        await api.post('/trades/sync').catch(() => {})

        const [statsRes, dailyRes, tradesRes, botRes] = await Promise.all([
          api.get(`/statistics?days=${period}`),
          api.get(`/statistics/daily?days=${period}`),
          api.get('/trades?per_page=10'),
          api.get('/bot/status'),
        ])
        setStats(statsRes.data)
        setDailyStats(dailyRes.data.days)
        setRecentTrades(tradesRes.data.trades)
        setBotStatus(botRes.data)
      } catch {
        setError(t('common.error'))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [period])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-gray-500 text-lg">{t('common.loading')}</div>
      </div>
    )
  }

  return (
    <div>
      {/* Error */}
      {error && (
        <div className="mb-4 p-3 bg-red-900/30 border border-red-800 rounded text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">{t('dashboard.title')}</h1>
        <div className="flex items-center gap-3">
          {/* Period selector */}
          <div className="flex bg-gray-800 rounded-lg overflow-hidden border border-gray-700">
            {PERIODS.map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  period === p
                    ? 'bg-primary-600 text-white'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                {t(`dashboard.days${p}` as any)}
              </button>
            ))}
          </div>
          {/* Bot status */}
          {botStatus && (
            <span
              className={`px-3 py-1.5 rounded-full text-sm font-medium ${
                botStatus.is_running
                  ? 'bg-green-900/30 text-green-400'
                  : 'bg-gray-800 text-gray-400'
              }`}
            >
              {botStatus.is_running ? t('bot.running') : t('bot.stopped')}
              {botStatus.is_running && botStatus.exchange_type && (
                <span className="ml-2 text-xs">
                  ({botStatus.exchange_type} - {botStatus.demo_mode ? t('common.demo') : t('common.live')})
                </span>
              )}
            </span>
          )}
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard
          label={t('dashboard.totalPnl')}
          value={stats ? `$${stats.net_pnl.toFixed(2)}` : '--'}
          color={stats && stats.net_pnl >= 0 ? 'text-profit' : 'text-loss'}
          sub={stats ? `${t('dashboard.fees')}: $${stats.total_fees.toFixed(2)} | ${t('dashboard.funding')}: $${stats.total_funding.toFixed(2)}` : undefined}
        />
        <StatCard
          label={t('dashboard.winRate')}
          value={stats ? `${stats.win_rate.toFixed(1)}%` : '--'}
          sub={stats ? `${stats.winning_trades}W / ${stats.losing_trades}L` : undefined}
        />
        <StatCard
          label={t('dashboard.bestTrade')}
          value={stats && stats.best_trade ? `$${stats.best_trade.toFixed(2)}` : '--'}
          color="text-profit"
        />
        <StatCard
          label={t('dashboard.worstTrade')}
          value={stats && stats.worst_trade ? `$${stats.worst_trade.toFixed(2)}` : '--'}
          color="text-loss"
        />
      </div>

      {/* Charts Row 1: PnL + Win/Loss */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-400 mb-3">{t('dashboard.pnlOverTime')}</h3>
          <PnlChart data={dailyStats} />
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-400 mb-3">{t('dashboard.winLoss')}</h3>
          <WinLossChart
            wins={stats?.winning_trades || 0}
            losses={stats?.losing_trades || 0}
            winRate={stats?.win_rate || 0}
          />
        </div>
      </div>

      {/* Charts Row 2: Fees & Funding */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-6">
        <h3 className="text-sm font-medium text-gray-400 mb-3">{t('dashboard.feesAndFunding')}</h3>
        <FeesChart data={dailyStats} />
      </div>

      {/* Recent trades */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg">
        <div className="p-4 border-b border-gray-800">
          <h2 className="text-lg font-semibold text-white">
            {t('dashboard.recentTrades')}
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="text-left p-3 text-gray-400">{t('trades.date')}</th>
                <th className="text-left p-3 text-gray-400">{t('trades.symbol')}</th>
                <th className="text-left p-3 text-gray-400">{t('trades.side')}</th>
                <th className="text-right p-3 text-gray-400">{t('trades.entryPrice')}</th>
                <th className="text-right p-3 text-gray-400">{t('trades.pnl')}</th>
                <th className="text-left p-3 text-gray-400">{t('trades.mode')}</th>
                <th className="text-left p-3 text-gray-400">{t('trades.status')}</th>
              </tr>
            </thead>
            <tbody>
              {recentTrades.length === 0 ? (
                <tr>
                  <td colSpan={7} className="p-8 text-center text-gray-500">
                    {t('dashboard.noTrades')}
                  </td>
                </tr>
              ) : (
                recentTrades.map((trade) => (
                  <tr key={trade.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="p-3 text-gray-300">
                      {new Date(trade.entry_time).toLocaleDateString()}
                    </td>
                    <td className="p-3 text-white font-medium">{trade.symbol}</td>
                    <td className="p-3">
                      <span className={trade.side === 'long' ? 'text-profit' : 'text-loss'}>
                        {trade.side.toUpperCase()}
                      </span>
                    </td>
                    <td className="p-3 text-right text-gray-300">
                      ${trade.entry_price.toLocaleString()}
                    </td>
                    <td className="p-3 text-right">
                      <span className={trade.pnl && trade.pnl >= 0 ? 'text-profit' : 'text-loss'}>
                        {trade.pnl !== null ? `$${trade.pnl.toFixed(2)}` : '--'}
                      </span>
                    </td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded text-xs ${
                        trade.demo_mode
                          ? 'bg-yellow-900/30 text-yellow-400 border border-yellow-800'
                          : 'bg-green-900/30 text-green-400 border border-green-800'
                      }`}>
                        {trade.demo_mode ? t('common.demo') : t('common.live')}
                      </span>
                    </td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded text-xs ${
                        trade.status === 'open' ? 'bg-blue-900/30 text-blue-400' :
                        trade.status === 'closed' ? 'bg-gray-800 text-gray-400' :
                        'bg-yellow-900/30 text-yellow-400'
                      }`}>
                        {t(`trades.${trade.status}`)}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
