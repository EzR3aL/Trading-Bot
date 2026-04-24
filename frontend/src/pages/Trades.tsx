import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
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
import { useTradesFilterOptions } from '../hooks/useTradesFilterOptions'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useVirtualRows } from '../components/virtualised/useVirtualRows'

// URL-search-param keys used by the filters — keeping them in a
// const object so the URL surface is in one obvious spot and typos
// at call sites fail the type checker.
const PARAM_KEYS = {
  status: 'status',
  symbol: 'symbol',
  exchange: 'exchange',
  bot: 'bot',
  dateFrom: 'date_from',
  dateTo: 'date_to',
  page: 'page',
} as const

// Debounce for free-text filter inputs (e.g. symbol textbox) before
// they hit the history stack. 300ms keeps typing responsive without
// creating a new history entry for every keystroke.
const TEXT_DEBOUNCE_MS = 300

interface FiltersFromUrl {
  status: string
  symbol: string
  exchange: string
  bot: string
  dateFrom: string
  dateTo: string
  page: number
}

function readFiltersFromParams(params: URLSearchParams): FiltersFromUrl {
  const rawPage = Number(params.get(PARAM_KEYS.page) ?? '1')
  const page = Number.isFinite(rawPage) && rawPage >= 1 ? rawPage : 1
  return {
    status: params.get(PARAM_KEYS.status) ?? '',
    symbol: params.get(PARAM_KEYS.symbol) ?? '',
    exchange: params.get(PARAM_KEYS.exchange) ?? '',
    bot: params.get(PARAM_KEYS.bot) ?? '',
    dateFrom: params.get(PARAM_KEYS.dateFrom) ?? '',
    dateTo: params.get(PARAM_KEYS.dateTo) ?? '',
    page,
  }
}

export default function Trades() {
  const { t } = useTranslation()
  useDocumentTitle(t('nav.trades'))
  const isMobile = useIsMobile()
  const { toggle: toggleSizeUnit } = useSizeUnitStore()
  const sizeUnit = useSizeUnitStore((s) => s.unit)
  const { demoFilter } = useFilterStore()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const perPage = 25

  // ── Filter state: URL is the single source of truth ────────────
  // `filters` mirrors the URL. We derive it inside useMemo so the
  // memoized value is referentially stable across renders where the
  // search-param string hasn't changed. Local state exists only for
  // the symbol textbox (so typing stays snappy without writing the
  // URL on every keystroke — debounced below).
  const filters = useMemo(() => readFiltersFromParams(searchParams), [searchParams])

  // Symbol textbox buffer — pre-populated from the URL and kept in
  // sync whenever the URL changes out from under us (back/forward
  // navigation, programmatic navigation, etc.).
  const [symbolDraft, setSymbolDraft] = useState(filters.symbol)
  useEffect(() => {
    setSymbolDraft(filters.symbol)
  }, [filters.symbol])

  // ── URL mutators ────────────────────────────────────────────────
  // All filter-control onChange handlers funnel through updateParams
  // so there's exactly one place that touches the URL. Passing null
  // strips a key; any non-null string sets it. We reset `page` to 1
  // on every filter change (unless the caller is setting `page`
  // itself) — required because moving to page 3 of an old filter and
  // then switching filters would otherwise land the user on a page
  // that no longer exists.
  const updateParams = useCallback(
    (updates: Record<string, string | null>) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          const isPageUpdate = Object.prototype.hasOwnProperty.call(updates, PARAM_KEYS.page)
          for (const [key, value] of Object.entries(updates)) {
            if (value === null || value === '') {
              next.delete(key)
            } else {
              next.set(key, value)
            }
          }
          if (!isPageUpdate) {
            next.delete(PARAM_KEYS.page)
          }
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  // Debounced write of the symbol textbox. Typing "BTCUSDT" shouldn't
  // create 7 history entries, and shouldn't fire 7 queries. We still
  // let the URL be the source of truth — we're only delaying WHEN the
  // URL gets updated, not skipping the update.
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (symbolDraft === filters.symbol) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      updateParams({ [PARAM_KEYS.symbol]: symbolDraft || null })
    }, TEXT_DEBOUNCE_MS)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [symbolDraft, filters.symbol, updateParams])

  // ── Sync trades on mount ────────────────────────────────────────
  const syncTrades = useSyncTrades()
  const [synced, setSynced] = useState(false)
  // Intentional: run once on mount. Excluding syncTrades — the mutation object
  // from react-query is a new reference on every render, so including it would
  // trigger repeated syncs. We only want a single sync when the page opens.
  useEffect(() => {
    syncTrades.mutate(undefined, {
      onSettled: () => setSynced(true),
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Filter-option lists (symbols, bots, exchanges, statuses) ───
  // Served by a dedicated endpoint so dropdowns include values that
  // exist across ALL the user's trades, not just the currently-loaded
  // page. Falls back to empty arrays while loading/on error.
  const { data: options } = useTradesFilterOptions()

  // Reset to page 1 when the demo-mode filter flips. demoFilter isn't
  // part of the URL (it's a global store) but it does affect which
  // trades we fetch, so we need to guard against sitting on page 5 of
  // a live-only view after switching to demo-only.
  const demoFilterRef = useRef(demoFilter)
  useEffect(() => {
    if (demoFilterRef.current !== demoFilter) {
      demoFilterRef.current = demoFilter
      if (filters.page !== 1) {
        updateParams({ [PARAM_KEYS.page]: null })
      }
    }
  }, [demoFilter, filters.page, updateParams])

  // ── Main trade list query ───────────────────────────────────────
  // Query key is derived from URL-parsed filters so two renders with
  // the same URL hit the same cache entry — no drift between UI and
  // request params even during fast navigation.
  const tradeFilters: Record<string, unknown> = useMemo(() => ({
    page: filters.page,
    per_page: perPage,
    ...(filters.status ? { status: filters.status } : {}),
    ...(filters.symbol ? { symbol: filters.symbol } : {}),
    ...(filters.exchange ? { exchange: filters.exchange } : {}),
    ...(filters.bot ? { bot_name: filters.bot } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
    ...(demoFilter === 'demo' ? { demo_mode: 'true' } : demoFilter === 'live' ? { demo_mode: 'false' } : {}),
  }), [filters, demoFilter])

  const { data: tradeData, isLoading: loading, error: tradeError } = useTrades(tradeFilters)
  const trades: Trade[] = synced ? (tradeData?.trades ?? []) : []
  const total = synced ? (tradeData?.total ?? 0) : 0
  const error = tradeError ? t('common.error') : ''

  const [expandedId, setExpandedId] = useState<number | null>(null)

  // Scroll anchor for window-virtualised trade rows. Points at the
  // overflow-x wrapper around the <table> so useVirtualRows can convert
  // the page scroll offset into the correct row window. Only activates
  // when trades.length crosses VIRTUALISATION_THRESHOLD (see hook).
  const tradesTableRef = useRef<HTMLDivElement | null>(null)
  const {
    isVirtualised: tradesVirtualised,
    virtualItems: tradesVirtualItems,
    paddingTop: tradesPaddingTop,
    paddingBottom: tradesPaddingBottom,
    measureElement: tradesMeasureElement,
  } = useVirtualRows({
    count: trades.length,
    scrollMarginRef: tradesTableRef,
  })

  const refreshData = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.trades.all })
  }, [queryClient])

  const { containerRef, refreshing, pullDistance } = usePullToRefresh({
    onRefresh: refreshData,
    disabled: !isMobile,
  })

  const totalPages = Math.ceil(total / perPage)

  const hasActiveFilters = Boolean(
    filters.status ||
    filters.symbol ||
    filters.exchange ||
    filters.bot ||
    filters.dateFrom ||
    filters.dateTo,
  )

  const clearAllFilters = useCallback(() => {
    // Clearing wipes every filter param and the page cursor in one
    // setSearchParams call — avoids the URL briefly showing a stale
    // combination during multiple updates.
    setSearchParams(new URLSearchParams(), { replace: true })
  }, [setSearchParams])

  const handlePageChange = useCallback(
    (nextPage: number) => {
      updateParams({ [PARAM_KEYS.page]: nextPage === 1 ? null : String(nextPage) })
    },
    [updateParams],
  )

  // ── Dropdown options ────────────────────────────────────────────
  // Built from the /filter-options endpoint. The statuses list has a
  // default fallback because the current UI already translates the
  // three known statuses — if the endpoint ships without statuses we
  // still want the dropdown usable.
  const statusOptions = useMemo(() => {
    const fromApi = options?.statuses ?? []
    const statuses = fromApi.length > 0 ? fromApi : ['open', 'closed', 'cancelled']
    return [
      { value: '', label: t('trades.allStatuses') },
      ...statuses.map((s) => ({ value: s, label: t(`trades.${s}`, { defaultValue: s }) })),
    ]
  }, [options?.statuses, t])

  const exchangeOptions = useMemo(() => {
    const exchanges = options?.exchanges ?? []
    return [
      { value: '', label: t('trades.allExchanges') },
      ...exchanges.map((ex) => ({ value: ex, label: ex.charAt(0).toUpperCase() + ex.slice(1) })),
    ]
  }, [options?.exchanges, t])

  const botOptions = useMemo(() => {
    const bots = options?.bots ?? []
    return [
      { value: '', label: t('trades.allBots') },
      ...bots.map((b) => ({ value: b.name, label: b.name })),
    ]
  }, [options?.bots, t])

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
          value={filters.status}
          onChange={(v) => updateParams({ [PARAM_KEYS.status]: v || null })}
          ariaLabel={t('trades.status')}
          options={statusOptions}
        />

        <input
          type="text"
          placeholder={`${t('trades.symbol')}...`}
          value={symbolDraft}
          onChange={(e) => setSymbolDraft(e.target.value.toUpperCase())}
          aria-label={t('trades.symbol')}
          className="filter-select w-32"
          list="trades-symbol-options"
        />
        {/* Native combobox data-list — optional hinting from the API,
            doesn't constrain what the user can type. */}
        <datalist id="trades-symbol-options">
          {(options?.symbols ?? []).map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>

        <FilterDropdown
          value={filters.exchange}
          onChange={(v) => updateParams({ [PARAM_KEYS.exchange]: v || null })}
          ariaLabel={t('trades.exchange')}
          options={exchangeOptions}
        />

        <FilterDropdown
          value={filters.bot}
          onChange={(v) => updateParams({ [PARAM_KEYS.bot]: v || null })}
          ariaLabel={t('trades.bot')}
          options={botOptions}
        />

        <DatePicker
          value={filters.dateFrom}
          onChange={(v) => updateParams({ [PARAM_KEYS.dateFrom]: v || null })}
          label={t('trades.dateFrom')}
          placeholder={t('trades.dateFrom') + '...'}
        />

        <DatePicker
          value={filters.dateTo}
          onChange={(v) => updateParams({ [PARAM_KEYS.dateTo]: v || null })}
          label={t('trades.dateTo')}
          placeholder={t('trades.dateTo') + '...'}
        />

        {hasActiveFilters && (
          <button
            onClick={clearAllFilters}
            className="filter-reset"
            aria-label={t('trades.clearAllFilters')}
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
          (() => {
            // Row renderer shared between the virtualised and full paths.
            // Kept as a closure so it can read `expandedId`, translations,
            // and the measureElement ref without prop drilling. The
            // `virtualIndex` arg is only non-null when virtualised — it's
            // forwarded as data-index so react-virtual can dynamically
            // measure rows whose expanded height differs from the estimate.
            const renderTradeRow = (trade: Trade, virtualIndex: number | null) => (
              <Fragment key={trade.id}>
                <tr
                  onClick={() => setExpandedId(expandedId === trade.id ? null : trade.id)}
                  className="cursor-pointer"
                  data-index={virtualIndex ?? undefined}
                  ref={virtualIndex !== null ? tradesMeasureElement : undefined}
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
            )

            return (
          <div className="overflow-x-auto" ref={tradesTableRef}>
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
                ) : tradesVirtualised ? (
                  // Windowed render: only rows inside (viewport + overscan) hit
                  // the DOM. Top/bottom spacer <tr>s preserve the scrollbar
                  // extent so scrolling feels identical to the full render.
                  <>
                    {tradesPaddingTop > 0 && (
                      <tr aria-hidden="true" style={{ height: tradesPaddingTop }}>
                        <td colSpan={12} />
                      </tr>
                    )}
                    {tradesVirtualItems.map((vi) => renderTradeRow(trades[vi.index], vi.index))}
                    {tradesPaddingBottom > 0 && (
                      <tr aria-hidden="true" style={{ height: tradesPaddingBottom }}>
                        <td colSpan={12} />
                      </tr>
                    )}
                  </>
                ) : (
                  trades.map((trade) => renderTradeRow(trade, null))
                )}
              </tbody>
            </table>
          </div>
            )
          })()
          )}
        </div>
      )}

      {/* Pagination */}
      <div className="mt-5">
        <Pagination
          page={filters.page}
          totalPages={totalPages}
          onPageChange={handlePageChange}
          label={totalPages > 1 ? `${t('common.page')} ${filters.page} ${t('common.of')} ${totalPages}` : undefined}
        />
      </div>
    </div>
  )
}
