import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../api/client'
import { useFilterStore } from '../stores/filterStore'
import type { Trade } from '../types'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import { SkeletonTable } from '../components/ui/Skeleton'
import PnlCell from '../components/ui/PnlCell'
import { X } from 'lucide-react'
import Pagination from '../components/ui/Pagination'
import DatePicker from '../components/ui/DatePicker'
import FilterDropdown from '../components/ui/FilterDropdown'

export default function Trades() {
  const { t } = useTranslation()
  const { demoFilter } = useFilterStore()
  const [trades, setTrades] = useState<Trade[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const [symbolFilter, setSymbolFilter] = useState('')
  const [exchangeFilter, setExchangeFilter] = useState('')
  const [botFilter, setBotFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const perPage = 25

  const [synced, setSynced] = useState(false)
  const [allTrades, setAllTrades] = useState<Trade[]>([])

  useEffect(() => {
    api.post('/trades/sync').catch(() => {}).finally(() => setSynced(true))
  }, [])

  // Fetch a larger set once to extract unique exchanges/bots
  useEffect(() => {
    if (!synced) return
    const params = new URLSearchParams({ page: '1', per_page: '200' })
    if (demoFilter === 'demo') params.set('demo_mode', 'true')
    else if (demoFilter === 'live') params.set('demo_mode', 'false')
    api.get(`/trades?${params}`).then(res => setAllTrades(res.data.trades)).catch(() => {})
  }, [synced, demoFilter])

  const uniqueExchanges = useMemo(() => {
    const set = new Set<string>()
    allTrades.forEach(t => {
      const ex = t.bot_exchange || t.exchange
      if (ex) set.add(ex)
    })
    return Array.from(set).sort()
  }, [allTrades])

  const uniqueBots = useMemo(() => {
    const set = new Set<string>()
    allTrades.forEach(t => { if (t.bot_name) set.add(t.bot_name) })
    return Array.from(set).sort()
  }, [allTrades])

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
      if (exchangeFilter) params.set('exchange', exchangeFilter)
      if (botFilter) params.set('bot_name', botFilter)
      if (dateFrom) params.set('date_from', dateFrom)
      if (dateTo) params.set('date_to', dateTo)
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
  }, [synced, page, statusFilter, symbolFilter, exchangeFilter, botFilter, dateFrom, dateTo, demoFilter])

  const totalPages = Math.ceil(total / perPage)

  const hasActiveFilters = statusFilter || symbolFilter || exchangeFilter || botFilter || dateFrom || dateTo

  const clearAllFilters = () => {
    setStatusFilter('')
    setSymbolFilter('')
    setExchangeFilter('')
    setBotFilter('')
    setDateFrom('')
    setDateTo('')
    setPage(1)
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
      <div className="flex flex-wrap items-center gap-2.5 mb-5">
        <FilterDropdown
          value={statusFilter}
          onChange={(v) => { setStatusFilter(v); setPage(1) }}
          ariaLabel={t('trades.status')}
          options={[
            { value: '', label: t('trades.allStatuses') },
            { value: 'open', label: t('trades.open') },
            { value: 'closed', label: t('trades.closed') },
            { value: 'cancelled', label: t('trades.cancelled') },
          ]}
        />

        <input
          type="text"
          placeholder={`${t('trades.symbol')}...`}
          value={symbolFilter}
          onChange={(e) => { setSymbolFilter(e.target.value.toUpperCase()); setPage(1) }}
          aria-label={t('trades.symbol')}
          className="filter-select w-32"
        />

        <FilterDropdown
          value={exchangeFilter}
          onChange={(v) => { setExchangeFilter(v); setPage(1) }}
          ariaLabel={t('trades.exchange')}
          options={[
            { value: '', label: t('trades.allExchanges') },
            ...uniqueExchanges.map(ex => ({ value: ex, label: ex.charAt(0).toUpperCase() + ex.slice(1) })),
          ]}
        />

        <FilterDropdown
          value={botFilter}
          onChange={(v) => { setBotFilter(v); setPage(1) }}
          ariaLabel={t('trades.bot')}
          options={[
            { value: '', label: t('trades.allBots') },
            ...uniqueBots.map(name => ({ value: name, label: name })),
          ]}
        />

        <DatePicker
          value={dateFrom}
          onChange={(v) => { setDateFrom(v); setPage(1) }}
          label={t('trades.dateFrom')}
          placeholder={t('trades.dateFrom') + '...'}
        />

        <DatePicker
          value={dateTo}
          onChange={(v) => { setDateTo(v); setPage(1) }}
          label={t('trades.dateTo')}
          placeholder={t('trades.dateTo') + '...'}
        />

        {hasActiveFilters && (
          <button
            onClick={clearAllFilters}
            className="filter-reset"
          >
            <X size={12} />
            {t('trades.reset')}
          </button>
        )}
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
                      <td className="text-right text-gray-300">{Number(trade.size).toFixed(4)}</td>
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
      <div className="mt-5">
        <Pagination
          page={page}
          totalPages={totalPages}
          onPageChange={setPage}
          label={totalPages > 1 ? `${t('common.page')} ${page} ${t('common.of')} ${totalPages}` : undefined}
        />
      </div>
    </div>
  )
}
