import { Fragment, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../api/client'
import { useToastStore } from '../stores/toastStore'
import { useFilterStore } from '../stores/filterStore'
import type { Trade } from '../types'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import { SkeletonTable } from '../components/ui/Skeleton'
import PnlCell from '../components/ui/PnlCell'
import { X, ChevronRight } from 'lucide-react'
import { formatDate, formatTime } from '../utils/dateUtils'
import Pagination from '../components/ui/Pagination'
import DatePicker from '../components/ui/DatePicker'
import FilterDropdown from '../components/ui/FilterDropdown'
import ExitReasonBadge from '../components/ui/ExitReasonBadge'
import MobileTradeCard from '../components/ui/MobileTradeCard'
import useIsMobile from '../hooks/useIsMobile'

export default function Trades() {
  const { t } = useTranslation()
  const isMobile = useIsMobile()
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
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const perPage = 25

  const [synced, setSynced] = useState(false)
  const [allTrades, setAllTrades] = useState<Trade[]>([])

  useEffect(() => {
    api.post('/trades/sync').catch((err) => { console.error('Failed to sync trades:', err) }).finally(() => setSynced(true))
  }, [])

  // Fetch a larger set once to extract unique exchanges/bots
  useEffect(() => {
    if (!synced) return
    const params = new URLSearchParams({ page: '1', per_page: '200' })
    if (demoFilter === 'demo') params.set('demo_mode', 'true')
    else if (demoFilter === 'live') params.set('demo_mode', 'false')
    api.get(`/trades?${params}`).then(res => setAllTrades(res.data.trades)).catch((err) => { console.error('Failed to load trade filters:', err); useToastStore.getState().addToast('error', t('common.loadError', 'Failed to load data')) })
  }, [synced, demoFilter])

  const uniqueExchanges = useMemo(() => {
    const set = new Set<string>()
    allTrades.forEach(trade => {
      const ex = trade.bot_exchange || trade.exchange
      if (ex) set.add(ex)
    })
    return Array.from(set).sort()
  }, [allTrades])

  const uniqueBots = useMemo(() => {
    const set = new Set<string>()
    allTrades.forEach(trade => { if (trade.bot_name) set.add(trade.bot_name) })
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
    <div className="animate-in min-w-0">
      <h1 className="text-2xl font-bold text-white mb-6 tracking-tight">{t('trades.title')}</h1>

      {error && (
        <div role="alert" className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
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
      {loading && <SkeletonTable rows={8} cols={8} />}

      {/* Table */}
      {!loading && (
        <div className="glass-card rounded-xl overflow-hidden min-w-0">
          {isMobile ? (
            trades.length === 0 ? (
              <div className="p-8 text-center text-gray-500">
                {t('dashboard.noTrades')}
              </div>
            ) : (
              <div className="px-2 py-2 space-y-1.5">
                {trades.map(trade => <MobileTradeCard key={trade.id} trade={trade} />)}
              </div>
            )
          ) : (
          <div className="overflow-x-auto">
            <table className="table-premium w-full">
              <thead>
                <tr>
                  <th className="text-left hidden 2xl:table-cell">#</th>
                  <th className="text-left">{t('trades.date')}</th>
                  <th className="text-left hidden xl:table-cell">{t('trades.bot')}</th>
                  <th className="text-center hidden lg:table-cell">{t('trades.exchange')}</th>
                  <th className="text-left">{t('trades.symbol')}</th>
                  <th className="text-center">{t('trades.side')}</th>
                  <th className="text-right hidden 2xl:table-cell">{t('trades.size')}</th>
                  <th className="text-right hidden xl:table-cell">{t('trades.entryPrice')}</th>
                  <th className="text-right hidden 2xl:table-cell">{t('trades.exitPrice')}</th>
                  <th className="text-right">{t('trades.pnl')}</th>
                  <th className="text-center hidden 2xl:table-cell">{t('trades.mode')}</th>
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
                    <Fragment key={trade.id}>
                      <tr
                        onClick={() => setExpandedId(expandedId === trade.id ? null : trade.id)}
                        className="cursor-pointer"
                      >
                        <td className="text-gray-500 text-xs hidden 2xl:table-cell">{trade.id}</td>
                        <td className="text-gray-300">
                          <span className="inline-flex items-center">
                            <ChevronRight size={14} className={`expand-chevron ${expandedId === trade.id ? 'open' : ''}`} />
                            <span title={formatTime(trade.entry_time)}>{formatDate(trade.entry_time)}</span>
                          </span>
                        </td>
                        <td className="hidden xl:table-cell">
                          {trade.bot_name ? (
                            <span className="text-white font-medium">{trade.bot_name}</span>
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
                        <td className="text-right text-gray-300 hidden 2xl:table-cell">{Number(trade.size).toFixed(4)}</td>
                        <td className="text-right text-gray-300 hidden xl:table-cell">${trade.entry_price.toLocaleString()}</td>
                        <td className="text-right text-gray-300 hidden 2xl:table-cell">
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
                          <td colSpan={12} className="!p-0 !border-b-0">
                            <dl className="table-expand-content">
                              <div className="2xl:hidden">
                                <dt>ID</dt>
                                <dd>{trade.id}</dd>
                              </div>
                              <div className="xl:hidden">
                                <dt>{t('trades.bot')}</dt>
                                <dd>{trade.bot_name || '--'}</dd>
                              </div>
                              <div className="lg:hidden">
                                <dt>{t('trades.exchange')}</dt>
                                <dd className="capitalize">{trade.bot_exchange || trade.exchange}</dd>
                              </div>
                              <div className="2xl:hidden">
                                <dt>{t('trades.size')}</dt>
                                <dd>{Number(trade.size).toFixed(4)}</dd>
                              </div>
                              <div className="xl:hidden">
                                <dt>{t('trades.entryPrice')}</dt>
                                <dd>${trade.entry_price.toLocaleString()}</dd>
                              </div>
                              <div className="2xl:hidden">
                                <dt>{t('trades.exitPrice')}</dt>
                                <dd>{trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}</dd>
                              </div>
                              <div className="2xl:hidden">
                                <dt>{t('trades.mode')}</dt>
                                <dd>{trade.demo_mode ? t('common.demo') : t('common.live')}</dd>
                              </div>
                              <div>
                                <dt>{t('trades.pnl')} %</dt>
                                <dd className={trade.pnl_percent && trade.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}>
                                  {trade.pnl_percent != null ? `${trade.pnl_percent >= 0 ? '+' : ''}${trade.pnl_percent.toFixed(2)}%` : '--'}
                                </dd>
                              </div>
                              {trade.exit_time && (
                                <div>
                                  <dt>{t('trades.exitTime')}</dt>
                                  <dd>{formatDate(trade.exit_time)} {formatTime(trade.exit_time)}</dd>
                                </div>
                              )}
                              {trade.exit_reason && (
                                <div>
                                  <dt>{t('trades.exitReason')}</dt>
                                  <dd><ExitReasonBadge reason={trade.exit_reason} /></dd>
                                </div>
                              )}
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
