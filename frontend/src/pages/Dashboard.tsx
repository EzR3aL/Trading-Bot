import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../api/client'
import type { Statistics, Trade, BotStatus } from '../types'

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <div className="text-sm text-gray-400">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${color || 'text-white'}`}>
        {value}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { t } = useTranslation()
  const [stats, setStats] = useState<Statistics | null>(null)
  const [recentTrades, setRecentTrades] = useState<Trade[]>([])
  const [botStatus, setBotStatus] = useState<BotStatus | null>(null)

  useEffect(() => {
    const load = async () => {
      try {
        const [statsRes, tradesRes, botRes] = await Promise.all([
          api.get('/statistics?days=30'),
          api.get('/trades?per_page=10'),
          api.get('/bot/status'),
        ])
        setStats(statsRes.data)
        setRecentTrades(tradesRes.data.trades)
        setBotStatus(botRes.data)
      } catch {
        // API may not be fully set up yet
      }
    }
    load()
  }, [])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">{t('dashboard.title')}</h1>
        {botStatus && (
          <span
            className={`px-3 py-1 rounded-full text-sm font-medium ${
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

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard
          label={t('dashboard.totalPnl')}
          value={stats ? `$${stats.net_pnl.toFixed(2)}` : '--'}
          color={stats && stats.net_pnl >= 0 ? 'text-profit' : 'text-loss'}
        />
        <StatCard
          label={t('dashboard.winRate')}
          value={stats ? `${stats.win_rate.toFixed(1)}%` : '--'}
        />
        <StatCard
          label={t('dashboard.totalTrades')}
          value={stats ? String(stats.total_trades) : '--'}
        />
        <StatCard
          label={t('dashboard.balance')}
          value="--"
        />
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
                <th className="text-left p-3 text-gray-400">{t('trades.status')}</th>
              </tr>
            </thead>
            <tbody>
              {recentTrades.length === 0 ? (
                <tr>
                  <td colSpan={6} className="p-8 text-center text-gray-500">
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
