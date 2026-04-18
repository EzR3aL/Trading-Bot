import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { useTrades, useSyncTrades, queryKeys } from '../api/queries'
import { useFilterStore } from '../stores/filterStore'
import type { Trade } from '../types'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import { SkeletonTable } from '../components/ui/Skeleton'
import PnlCell from '../components/ui/PnlCell'
import { X, ChevronRight, FileText } from 'lucide-react'
import { formatDate, formatTime } from '../utils/dateUtils'
import Pagination from '../components/ui/Pagination'
import DatePicker from '../components/ui/DatePicker'
import FilterDropdown from '../components/ui/FilterDropdown'
import ExitReasonBadge from '../components/ui/ExitReasonBadge'
import RiskStateBadge from '../components/ui/RiskStateBadge'
import { deriveRiskStateFromPosition } from '../utils/riskState'
import MobileTradeCard from '../components/ui/MobileTradeCard'
import SizeValue from '../components/ui/SizeValue'
import { useSizeUnitStore } from '../stores/sizeUnitStore'
import useIsMobile from '../hooks/useIsMobile'
import usePullToRefresh from '../hooks/usePullToRefresh'
import PullToRefreshIndicator from '../components/ui/PullToRefreshIndicator'

export default function Trades() {
  const { t } = useTranslation()
  const isMobile = useIsMobile()
  const { toggle: toggleSizeUnit } = useSizeUnitStore()
  const sizeUnit = useSizeUnitStore((s) => s.unit)
  const { demoFilter } = useFilterStore()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const [symbolFilter, setSymbolFilter] = useState('')
  const [exchangeFilter, setExchangeFilter] = useState('')
  const [botFilter, setBotFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const perPage = 25

  // Sync trades on mount
  const syncTrades = useSyncTrades()
  const [synced, setSynced] = useState(false)
  useEffect(() => {
    syncTrades.mutate(undefined, {
      onSettled: () => setSynced(true),
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch a larger set once to extract unique exchanges/bots for filter dropdowns
  const allTradesFilters: Record<string, unknown> = {
    page: 1, per_page: 200,
    ...(demoFilter === 'demo' ? { demo_mode: 'true' } : demoFilter === 'live' ? { demo_mode: 'false' } : {}),
  }
  const { data: allTradesData } = useTrades(allTradesFilters)
  const allTrades: Trade[] = synced ? (allTradesData?.trades || []) : []

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

  // Main trade list query
  const tradeFilters: Record<string, unknown> = {
    page, per_page: perPage,
    ...(statusFilter ? { status: statusFilter } : {}),
    ...(symbolFilter ? { symbol: symbolFilter } : {}),
    ...(exchangeFilter ? { exchange: exchangeFilter } : {}),
    ...(botFilter ? { bot_name: botFilter } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    ...(demoFilter === 'demo' ? { demo_mode: 'true' } : demoFilter === 'live' ? { demo_mode: 'false' } : {}),
  }
  const { data: tradeData, isLoading: loading, error: tradeError } = useTrades(tradeFilters)
  const trades: Trade[] = synced ? (tradeData?.trades || []) : []
  const total = synced ? (tradeData?.total || 0) : 0
  const error = tradeError ? t('common.error') : ''

  const refreshData = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.trades.all })
  }, [queryClient])

  const { containerRef, refreshing, pullDistance } = usePullToRefresh({
    onRefresh: refreshData,
    disabled: !isMobile,
  })

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
    <div ref={containerRef} style={{ overscrollBehavior: 'contain' }} className="animate-in min-w-0" aria-busy={loading}>
      <PullToRefreshIndicator pullDistance={pullDistance} refreshing={refreshing} />
      <h1 className="text-2xl font-bold text-white mb-6 tracking-tight">{t('trades.title')}</h1>

      {error && (
        <div role="alert" className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Filters */}
      <div className="grid grid-cols-2 sm:flex sm:flex-wrap items-center gap-2 sm:gap-2.5 mb-5">
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
            aria-label="Clear all filters"
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
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <FileText className="w-12 h-12 text-gray-600 dark:text-gray-600 mb-3" />
                <p className="text-gray-500 dark:text-gray-400 font-medium">{t('trades.noTradesTitle')}</p>
                <p className="text-gray-400 dark:text-gray-500 text-sm mt-1">{t('trades.noTradesHint')}</p>
              </div>
            ) : (
              <div className="px-1 py-1 space-y-1.5">
                {trades.map(trade => <MobileTradeCard key={trade.id} trade={trade} />)}
              </div>
            )
          ) : (
          <div className="overflow-x-auto">
            <table className="table-premium w-full">
              <thead>
                <tr>
                  <th scope="col" className="text-left">#</th>
                  <th scope="col" className="text-left">{t('trades.date')}</th>
                  <th scope="col" className="text-left hidden xl:table-cell">{t('trades.bot')}</th>
                  <th scope="col" className="text-center hidden lg:table-cell">{t('trades.exchange')}</th>
                  <th scope="col" className="text-left">{t('trades.symbol')}</th>
                  <th scope="col" className="text-center">{t('trades.side')}</th>
                  <th scope="col" className="text-right hidden 2xl:table-cell">
                    <button
                      onClick={() => toggleSizeUnit()}
                      className="inline-flex items-center gap-1 hover:text-white transition-colors ml-auto"
                      title={sizeUnit === 'token' ? 'Show USDT value' : 'Show token size'}
                    >
                      {t('trades.size')} <span className="text-[10px] text-gray-500">{sizeUnit === 'usdt' ? '$' : '#'}</span>
                    </button>
                  </th>
                  <th scope="col" className="text-right hidden xl:table-cell">{t('trades.entryPrice')}</th>
                  <th scope="col" className="text-right hidden 2xl:table-cell">{t('trades.exitPrice')}</th>
                  <th scope="col" className="text-right">{t('trades.pnl')}</th>
                  <th scope="col" className="text-center hidden 2xl:table-cell">{t('trades.mode')}</th>
                  <th scope="col" className="text-center">{t('trades.status')}</th>
                </tr>
              </thead>
              <tbody>
                {trades.length === 0 ? (
                  <tr>
                    <td colSpan={12} className="p-8 text-center">
                      <div className="flex flex-col items-center justify-center py-4">
                        <FileText className="w-10 h-10 text-gray-600 dark:text-gray-600 mb-2" />
                        <p className="text-gray-500 dark:text-gray-400 font-medium">{t('trades.noTradesTitle')}</p>
                        <p className="text-gray-400 dark:text-gray-500 text-sm mt-1">{t('trades.noTradesHint')}</p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  trades.map((trade) => (
                    <Fragment key={trade.id}>
                      <tr
                        onClick={() => setExpandedId(expandedId === trade.id ? null : trade.id)}
                        className="cursor-pointer"
                      >
                        <td className="text-gray-500 text-xs font-mono">#{trade.id}</td>
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
                        <td className="text-right text-gray-300 hidden 2xl:table-cell">
                          <SizeValue size={Number(trade.size)} price={trade.entry_price} symbol={trade.symbol} />
                        </td>
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
                                <dd>
                                  <SizeValue size={Number(trade.size)} price={trade.entry_price} symbol={trade.symbol} />
                                </dd>
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
                              {trade.status === 'open' && (() => {
                                const risk = deriveRiskStateFromPosition({
                                  trade_id: trade.id,
                                  symbol: trade.symbol,
                                  take_profit: trade.take_profit,
                                  stop_loss: trade.stop_loss,
                                  trailing_stop_active: trade.trailing_stop_active ?? false,
                                  trailing_stop_price: trade.trailing_stop_price,
                                  trailing_stop_distance_pct: trade.trailing_stop_distance_pct,
                                })
                                const hasAny = risk.tp != null || risk.sl != null || risk.trailing != null
                                if (!hasAny) return null
                                return (
                                  <div className="col-span-full">
                                    <dt>{t('trades.riskBadges.tp')}/{t('trades.riskBadges.sl')}/{t('trades.riskBadges.trail')}</dt>
                                    <dd>
                                      <RiskStateBadge
                                        tp={risk.tp}
                                        sl={risk.sl}
                                        trailing={risk.trailing}
                                        riskSource={risk.risk_source}
                                      />
                                    </dd>
                                  </div>
                                )
                              })()}
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
