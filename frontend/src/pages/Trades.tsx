import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../api/client'
import { useFilterStore } from '../stores/filterStore'
import type { Trade } from '../types'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import { SkeletonTable } from '../components/ui/Skeleton'
import PnlCell from '../components/ui/PnlCell'
import { ChevronLeft, ChevronRight } from 'lucide-react'

export default function Trades() {
  const { t } = useTranslation()
  const { demoFilter } = useFilterStore()
  const [trades, setTrades] = useState<Trade[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const [symbolFilter, setSymbolFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const perPage = 25

  const [synced, setSynced] = useState(false)

  useEffect(() => {
    api.post('/trades/sync').catch(() => {}).finally(() => setSynced(true))
  }, [])

  useEffect(() => {
    setPage(1)
  }, [demoFilter])

  useEffect(() => {
    if (!synced) return
    const load = async () => {
      setLoading(true)
      setError('')
      const params = new URLSearchParams({ page: String(page), per_page: String(perPage) })
      if (statusFilter) params.set('status', statusFilter)
      if (symbolFilter) params.set('symbol', symbolFilter)
      if (demoFilter === 'demo') params.set('demo_mode', 'true')
      else if (demoFilter === 'live') params.set('demo_mode', 'false')

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
  }, [synced, page, statusFilter, symbolFilter, demoFilter])

  const totalPages = Math.ceil(total / perPage)

  // Generate page numbers for pagination
  const getPageNumbers = () => {
    const pages: (number | '...')[] = []
    if (totalPages <= 7) {
      for (let i = 1; i <= totalPages; i++) pages.push(i)
    } else {
      pages.push(1)
      if (page > 3) pages.push('...')
      for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) {
        pages.push(i)
      }
      if (page < totalPages - 2) pages.push('...')
      pages.push(totalPages)
    }
    return pages
  }

  return (
    <div className="animate-in">
      <h1 className="text-2xl font-bold text-white mb-6 tracking-tight">{t('trades.title')}</h1>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3 mb-5">
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
          aria-label={t('trades.status')}
          className="input-dark w-auto py-2"
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
          aria-label={t('trades.symbol')}
          className="input-dark w-40 py-2"
        />
      </div>

      {/* Loading */}
      {loading && <SkeletonTable rows={8} cols={10} />}

      {/* Table */}
      {!loading && (
        <div className="glass-card rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="table-premium">
              <thead>
                <tr>
                  <th className="text-left">#</th>
                  <th className="text-left">{t('trades.date')}</th>
                  <th className="text-left">{t('trades.bot')}</th>
                  <th className="text-center">{t('trades.exchange')}</th>
                  <th className="text-left">{t('trades.symbol')}</th>
                  <th className="text-center">{t('trades.side')}</th>
                  <th className="text-right">{t('trades.size')}</th>
                  <th className="text-right">{t('trades.entryPrice')}</th>
                  <th className="text-right">{t('trades.exitPrice')}</th>
                  <th className="text-right">{t('trades.pnl')}</th>
                  <th className="text-center">{t('trades.mode')}</th>
                  <th className="text-center">{t('trades.status')}</th>
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
                    <tr key={trade.id}>
                      <td className="text-gray-500 text-xs">{trade.id}</td>
                      <td className="text-gray-300 cursor-default" title={new Date(trade.entry_time).toLocaleTimeString('de-DE', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit' }) + ' UTC'}>{new Date(trade.entry_time).toLocaleDateString()}</td>
                      <td>
                        {trade.bot_name ? (
                          <span className="text-white font-medium">{trade.bot_name}</span>
                        ) : (
                          <span className="text-gray-600">--</span>
                        )}
                      </td>
                      <td className="text-center">
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
                      <td className="text-right text-gray-300">{trade.size}</td>
                      <td className="text-right text-gray-300">${trade.entry_price.toLocaleString()}</td>
                      <td className="text-right text-gray-300">
                        {trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}
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
                      <td className="text-center">
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
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-1 mt-5">
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page === 1}
            aria-label="Previous page"
            className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
          >
            <ChevronLeft size={16} />
          </button>

          {getPageNumbers().map((p, i) => (
            p === '...' ? (
              <span key={`dots-${i}`} className="px-2 text-gray-500 text-sm">...</span>
            ) : (
              <button
                key={p}
                onClick={() => setPage(p)}
                aria-label={`${t('common.page')} ${p}`}
                className={`min-w-[32px] h-8 rounded-lg text-xs font-medium transition-all duration-200 ${
                  page === p
                    ? 'bg-gradient-to-r from-primary-600 to-primary-500 text-white shadow-glow-sm'
                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`}
              >
                {p}
              </button>
            )
          ))}

          <button
            onClick={() => setPage(Math.min(totalPages, page + 1))}
            disabled={page === totalPages}
            aria-label="Next page"
            className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
          >
            <ChevronRight size={16} />
          </button>

          <span className="text-xs text-gray-500 ml-3">
            {t('common.page')} {page} {t('common.of')} {totalPages}
          </span>
        </div>
      )}
    </div>
  )
}
