import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../api/client'
import type { Trade } from '../types'

export default function Trades() {
  const { t } = useTranslation()
  const [trades, setTrades] = useState<Trade[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const [symbolFilter, setSymbolFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const perPage = 25

  const [synced, setSynced] = useState(false)

  // Sync open trades with exchange on first load
  useEffect(() => {
    api.post('/trades/sync').catch(() => {}).finally(() => setSynced(true))
  }, [])

  useEffect(() => {
    if (!synced) return
    const load = async () => {
      setLoading(true)
      setError('')
      const params = new URLSearchParams({ page: String(page), per_page: String(perPage) })
      if (statusFilter) params.set('status', statusFilter)
      if (symbolFilter) params.set('symbol', symbolFilter)

      try {
        const res = await api.get(`/trades?${params}`)
        setTrades(res.data.trades)
        setTotal(res.data.total)
      } catch {
        setError(t('common.error'))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [synced, page, statusFilter, symbolFilter])

  const totalPages = Math.ceil(total / perPage)

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">{t('trades.title')}</h1>

      {/* Error */}
      {error && (
        <div className="mb-4 p-3 bg-red-900/30 border border-red-800 rounded text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-4 mb-4">
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
          className="bg-gray-800 border border-gray-700 text-gray-300 rounded px-3 py-2 text-sm"
        >
          <option value="">{t('trades.allModes')}</option>
          <option value="open">{t('trades.open')}</option>
          <option value="closed">{t('trades.closed')}</option>
          <option value="cancelled">{t('trades.cancelled')}</option>
        </select>
        <input
          type="text"
          placeholder="Symbol..."
          value={symbolFilter}
          onChange={(e) => { setSymbolFilter(e.target.value.toUpperCase()); setPage(1) }}
          className="bg-gray-800 border border-gray-700 text-gray-300 rounded px-3 py-2 text-sm w-40"
        />
      </div>

      {/* Loading */}
      {loading && (
        <div className="text-center text-gray-500 py-12">{t('common.loading')}</div>
      )}

      {/* Table */}
      {!loading && (
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left p-3 text-gray-400">#</th>
              <th className="text-left p-3 text-gray-400">{t('trades.date')}</th>
              <th className="text-left p-3 text-gray-400">{t('trades.bot')}</th>
              <th className="text-left p-3 text-gray-400">{t('trades.symbol')}</th>
              <th className="text-left p-3 text-gray-400">{t('trades.side')}</th>
              <th className="text-right p-3 text-gray-400">{t('trades.size')}</th>
              <th className="text-right p-3 text-gray-400">{t('trades.entryPrice')}</th>
              <th className="text-right p-3 text-gray-400">{t('trades.exitPrice')}</th>
              <th className="text-right p-3 text-gray-400">{t('trades.pnl')}</th>
              <th className="text-left p-3 text-gray-400">{t('trades.exchange')}</th>
              <th className="text-left p-3 text-gray-400">{t('trades.mode')}</th>
              <th className="text-left p-3 text-gray-400">{t('trades.status')}</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr>
                <td colSpan={12} className="p-8 text-center text-gray-500">
                  {t('dashboard.noTrades')}
                </td>
              </tr>
            ) : (
            trades.map((trade) => (
              <tr key={trade.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                <td className="p-3 text-gray-500">{trade.id}</td>
                <td className="p-3 text-gray-300">{new Date(trade.entry_time).toLocaleDateString()}</td>
                <td className="p-3">
                  {trade.bot_name ? (
                    <div>
                      <span className="text-white font-medium">{trade.bot_name}</span>
                      <span className="text-gray-500 text-xs ml-1">({trade.bot_exchange || trade.exchange})</span>
                    </div>
                  ) : (
                    <span className="text-gray-600">—</span>
                  )}
                </td>
                <td className="p-3 text-white font-medium">{trade.symbol}</td>
                <td className="p-3">
                  <span className={trade.side === 'long' ? 'text-profit' : 'text-loss'}>
                    {trade.side.toUpperCase()}
                  </span>
                </td>
                <td className="p-3 text-right text-gray-300">{trade.size}</td>
                <td className="p-3 text-right text-gray-300">${trade.entry_price.toLocaleString()}</td>
                <td className="p-3 text-right text-gray-300">
                  {trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}
                </td>
                <td className="p-3 text-right">
                  <span className={trade.pnl && trade.pnl >= 0 ? 'text-profit' : 'text-loss'}>
                    {trade.pnl !== null ? `$${trade.pnl.toFixed(2)}` : '--'}
                  </span>
                </td>
                <td className="p-3 text-gray-400">{trade.exchange}</td>
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
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-4">
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page === 1}
            className="px-3 py-1 bg-gray-800 text-gray-300 rounded disabled:opacity-30"
          >
            &lt;
          </button>
          <span className="text-gray-400 text-sm">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage(Math.min(totalPages, page + 1))}
            disabled={page === totalPages}
            className="px-3 py-1 bg-gray-800 text-gray-300 rounded disabled:opacity-30"
          >
            &gt;
          </button>
        </div>
      )}
    </div>
  )
}
