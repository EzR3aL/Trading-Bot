import { useMemo, useRef, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Info, AlertTriangle, Wallet, Search, X, Loader2 } from 'lucide-react'
import ExchangeLogo from '../ui/ExchangeLogo'
import NumInput from '../ui/NumInput'
import type { BalancePreview, SymbolConflict, PerAssetEntry } from './BotBuilderTypes'
import { EXCHANGES, EXCHANGE_SUPPORTS_DEMO, POPULAR_BASES } from './BotBuilderTypes'
import CopyTradingStepExchange from './CopyTradingStepExchange'

interface Props {
  exchangeType: string
  mode: string
  marginMode: 'cross' | 'isolated'
  tradingPairs: string[]
  perAssetConfig: Record<string, PerAssetEntry>
  exchangeSymbols: string[]
  symbolsLoading: boolean
  balancePreview: BalancePreview | null
  balanceOverview: BalancePreview[]
  overviewLoading: boolean
  symbolConflicts: SymbolConflict[]
  hlGateStatus?: { needs_approval: boolean; needs_referral: boolean }
  strategyType?: string
  strategyParams?: Record<string, any>
  onStrategyParamsChange?: (params: Record<string, any>) => void
  onTradingPairsChange?: (pairs: string[]) => void
  onExchangeTypeChange: (val: string) => void
  onModeChange: (val: string) => void
  onMarginModeChange: (val: 'cross' | 'isolated') => void
  onTogglePair: (pair: string) => void
  onPerAssetConfigChange: (config: Record<string, PerAssetEntry>) => void
  b: Record<string, string>
}

export default function BotBuilderStepExchange({
  exchangeType, mode, marginMode, tradingPairs, perAssetConfig,
  exchangeSymbols, symbolsLoading, balancePreview, balanceOverview, overviewLoading,
  symbolConflicts, hlGateStatus,
  strategyType, strategyParams, onStrategyParamsChange, onTradingPairsChange,
  onExchangeTypeChange, onModeChange, onMarginModeChange, onTogglePair, onPerAssetConfigChange,
  b,
}: Props) {
  const { t } = useTranslation()
  const isHyperliquid = exchangeType === 'hyperliquid'
  const isBingx = exchangeType === 'bingx'

  if (strategyType === 'copy_trading' && strategyParams && onStrategyParamsChange && onTradingPairsChange) {
    return (
      <CopyTradingStepExchange
        exchangeType={exchangeType}
        mode={mode as 'live' | 'demo'}
        strategyParams={strategyParams}
        onStrategyParamsChange={onStrategyParamsChange}
        onTradingPairsChange={onTradingPairsChange}
      />
    )
  }

  const [symbolSearch, setSymbolSearch] = useState('')
  const [symbolDropdownOpen, setSymbolDropdownOpen] = useState(false)
  const symbolDropdownRef = useRef<HTMLDivElement>(null)

  // Close dropdown on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (symbolDropdownRef.current && !symbolDropdownRef.current.contains(e.target as Node)) {
        setSymbolDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  // Filter symbols by search query
  const filteredSymbols = useMemo(() => {
    if (!symbolSearch.trim()) return exchangeSymbols
    const q = symbolSearch.toUpperCase()
    return exchangeSymbols.filter(s => s.toUpperCase().includes(q))
  }, [exchangeSymbols, symbolSearch])

  const updateAsset = (pair: string, field: string, val: string) => {
    const num = val === '' ? undefined : parseFloat(val)
    onPerAssetConfigChange({
      ...perAssetConfig,
      [pair]: { ...perAssetConfig[pair], [field]: num }
    })
  }

  const effectiveMode = mode === 'both' ? 'live' : mode

  return (
    <div className="space-y-6">
      {/* Exchange selection */}
      <div>
        <label className="block text-sm text-gray-400 mb-2">{b.exchange}</label>
        <div className="flex flex-wrap gap-2">
          {EXCHANGES.map(ex => {
            const active = exchangeType === ex
            return (
              <button key={ex} onClick={() => onExchangeTypeChange(ex)}
                className={`px-4 py-2 rounded-xl border transition-all ${
                  active
                    ? 'border-primary-500 bg-primary-500/10 text-white ring-1 ring-primary-500/30'
                    : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-white/20 hover:bg-white/[0.06]'
                }`}>
                <ExchangeLogo exchange={ex} size={16} />
              </button>
            )
          })}
        </div>
        {exchangeType === 'bitget' && (
          <div className="flex items-start gap-2 p-3 mt-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-300 text-xs sm:w-fit">
            <AlertTriangle size={16} className="shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold">{t('bots.builder.bitgetWarningTitle', 'Hinweis für deutsche Neukunden:')}</span>{' '}
              {t('bots.builder.bitgetWarningText', 'Bitget Futures sind für neue deutsche Kunden voraussichtlich bis 2027 nicht verfügbar. Bestehende Konten mit aktiviertem Futures-Trading sind nicht betroffen.')}
            </div>
          </div>
        )}
        {/* Hyperliquid gate warning: referral or builder fee not yet completed */}
        {isHyperliquid && hlGateStatus && (hlGateStatus.needs_approval || hlGateStatus.needs_referral) && (
          <div className="flex items-start gap-2 p-3 mt-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-300 text-xs sm:w-fit">
            <AlertTriangle size={16} className="shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold">{t('hlSetup.gateWarningTitle', 'Einrichtung erforderlich:')}</span>{' '}
              {t('hlSetup.gateWarningText', 'Hyperliquid Referral oder Builder Fee sind noch nicht abgeschlossen. Bitte schließe die Einrichtung in den Einstellungen ab.')}
            </div>
          </div>
        )}
      </div>

      {/* Mode + Margin Mode */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm text-gray-400 mb-2">{b.mode}</label>
          <div className="flex gap-2">
            {(['demo', 'live'] as const).map(m => {
              const active = mode === m
              const demoDisabled = m === 'demo' && !EXCHANGE_SUPPORTS_DEMO[exchangeType]
              const colorMap = {
                demo: active ? 'border-blue-500 bg-blue-500/10 text-blue-400 ring-1 ring-blue-500/30' : '',
                live: active ? 'border-orange-500 bg-orange-500/10 text-orange-400 ring-1 ring-orange-500/30' : '',
              }
              return (
                <button key={m} onClick={() => !demoDisabled && onModeChange(m)}
                  disabled={demoDisabled}
                  title={demoDisabled ? t('bots.builder.demoNotSupported') : undefined}
                  className={`px-4 py-2 rounded-xl border transition-all ${
                    demoDisabled
                      ? 'border-white/5 bg-white/[0.02] text-gray-600 cursor-not-allowed opacity-50'
                      : active
                        ? colorMap[m]
                        : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-white/20 hover:bg-white/[0.06]'
                  }`}>
                  {b[m]}
                </button>
              )
            })}
          </div>
          {!EXCHANGE_SUPPORTS_DEMO[exchangeType] && (
            <p className="flex items-center gap-1.5 text-xs text-gray-500 mt-1.5">
              <Info size={12} className="shrink-0" />
              {t('bots.builder.demoNotSupportedHint')}
            </p>
          )}
        </div>
        <div>
          <label className="block text-sm text-gray-400 mb-2">{t('bots.builder.marginMode')}</label>
          <div className="flex gap-2">
            {(['cross', 'isolated'] as const).map(mm => {
              const active = marginMode === mm
              return (
                <button key={mm} onClick={() => onMarginModeChange(mm)}
                  className={`px-4 py-2 rounded-xl border transition-all ${
                    active
                      ? 'border-primary-500 bg-primary-500/10 text-white ring-1 ring-primary-500/30'
                      : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-white/20 hover:bg-white/[0.06]'
                  }`}>
                  {t(`bots.builder.${mm}`)}
                </button>
              )
            })}
          </div>
          <div className="text-xs text-gray-400 mt-1.5 space-y-0.5">
            <p>{t('bots.builder.marginModeHintCross')}</p>
            <p>{t('bots.builder.marginModeHintIsolated')}</p>
          </div>
        </div>
      </div>

      {/* Trading pairs — searchable multi-select */}
      <div>
        <label className="block text-sm text-gray-400 mb-2">{b.tradingPairs}</label>

        {/* Selected pairs as chips */}
        {tradingPairs.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {tradingPairs.map(pair => (
              <span key={pair} className="inline-flex items-center gap-1 px-2.5 py-1 text-sm rounded-lg border border-primary-500/30 bg-primary-500/15 text-primary-400">
                {pair}
                <button onClick={() => onTogglePair(pair)} className="hover:text-white transition-colors" aria-label={`Remove ${pair}`}>
                  <X size={13} />
                </button>
              </span>
            ))}
          </div>
        )}

        {/* Popular quick buttons */}
        <div className="flex flex-wrap gap-1.5 mb-2">
          {POPULAR_BASES.map(base => {
            const symbol = isHyperliquid ? base : isBingx ? `${base}-USDT` : `${base}USDT`
            const isSelected = tradingPairs.includes(symbol)
            const isAvailable = exchangeSymbols.includes(symbol)
            if (!isAvailable && !symbolsLoading) return null
            return (
              <button key={base} onClick={() => onTogglePair(symbol)} disabled={symbolsLoading}
                className={`px-3 py-1.5 text-xs rounded-lg border transition-all ${
                  isSelected
                    ? 'border-primary-500 bg-primary-500/15 text-primary-400'
                    : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-white/20 hover:bg-white/[0.06]'
                }`}>
                {base}
              </button>
            )
          })}
        </div>

        {/* Searchable dropdown */}
        <div className="relative" ref={symbolDropdownRef}>
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              type="text"
              value={symbolSearch}
              onChange={e => { setSymbolSearch(e.target.value); setSymbolDropdownOpen(true) }}
              onFocus={() => setSymbolDropdownOpen(true)}
              placeholder={t('bots.builder.searchSymbols')}
              className="filter-select w-full text-sm !pl-10 pr-10"
            />
            {symbolsLoading && (
              <Loader2 size={15} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 animate-spin" />
            )}
            {!symbolsLoading && exchangeSymbols.length > 0 && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-gray-500">
                {exchangeSymbols.length} {t('bots.builder.available')}
              </span>
            )}
          </div>

          {symbolDropdownOpen && !symbolsLoading && filteredSymbols.length > 0 && (
            <div className="absolute z-30 w-full mt-1 max-h-60 overflow-y-auto rounded-xl border border-white/10 bg-[#0f1420] shadow-2xl">
              {filteredSymbols.slice(0, 100).map(sym => {
                const isSelected = tradingPairs.includes(sym)
                return (
                  <button
                    key={sym}
                    onClick={() => { onTogglePair(sym); setSymbolSearch('') }}
                    className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                      isSelected
                        ? 'bg-primary-500/10 text-primary-400'
                        : 'text-gray-300 hover:bg-white/[0.04] hover:text-white'
                    }`}
                  >
                    <span className="font-medium">{sym}</span>
                    {isSelected && <Check size={14} className="float-right mt-0.5 text-primary-400" />}
                  </button>
                )
              })}
              {filteredSymbols.length > 100 && (
                <div className="px-3 py-2 text-xs text-gray-500 text-center">
                  {t('bots.builder.moreResults', { count: filteredSymbols.length - 100 })}
                </div>
              )}
            </div>
          )}
        </div>
        <p className="text-xs text-gray-400 mt-1">{t('bots.builder.maxPairs')}</p>
      </div>

      {/* Symbol conflict warning */}
      {symbolConflicts.length > 0 && (
        <div className="p-3 bg-amber-900/30 border border-amber-800 rounded-xl space-y-1.5 w-fit">
          <div className="flex items-center gap-2 text-amber-400 font-medium text-sm">
            <AlertTriangle size={16} />
            {t('bots.builder.symbolConflictTitle')}
          </div>
          {symbolConflicts.map((c, i) => (
            <div key={i} className="text-sm text-amber-300/80 ml-6">
              {t('bots.builder.symbolConflictItem', { symbol: c.symbol, botName: c.existing_bot_name, mode: c.existing_bot_mode.toUpperCase() })}
            </div>
          ))}
          <p className="text-xs text-amber-400/60 ml-6">{t('bots.builder.symbolConflictHint')}</p>
        </div>
      )}

      {/* Exchange Balance Overview — all exchanges */}
      {(() => {
        if (overviewLoading) {
          return (
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 animate-pulse">
              <div className="flex items-center gap-2">
                <Wallet size={16} className="text-gray-500" />
                <div className="h-4 w-32 bg-white/10 rounded" />
              </div>
            </div>
          )
        }
        if (balanceOverview.length === 0 && !overviewLoading) {
          return (
            <div className="rounded-xl border border-amber-500/30 bg-amber-900/10 p-4 space-y-2">
              <div className="flex items-center gap-2 text-amber-400">
                <AlertTriangle size={16} />
                <span className="text-sm font-medium">{t('bots.builder.noConnectionsTitle')}</span>
              </div>
              <p className="text-sm text-amber-300/80 ml-6">{t('bots.builder.noConnectionsHint')}</p>
            </div>
          )
        }

        // Calculate this bot's allocation for warning on selected exchange
        const thisBotUsdt = tradingPairs.reduce((sum, p) => sum + (perAssetConfig[p]?.position_usdt || 0), 0)
        const selectedEntry = balanceOverview.find(e => e.exchange_type === exchangeType && e.mode === effectiveMode)
        const totalAllocated = selectedEntry ? selectedEntry.existing_allocated_amount + thisBotUsdt : 0
        const isOverAllocated = selectedEntry ? totalAllocated > selectedEntry.exchange_equity : false
        const isInsufficientBalance = selectedEntry ? thisBotUsdt > selectedEntry.remaining_balance && thisBotUsdt > 0 : false

        return (
          <div className={`rounded-xl border p-4 ${
            isOverAllocated ? 'border-amber-500/40 bg-amber-900/10' :
            isInsufficientBalance ? 'border-amber-500/30 bg-amber-900/5' :
            'border-white/[0.06] bg-white/[0.02]'
          }`}>
            <div className="flex items-center gap-2 mb-3">
              <Wallet size={16} className="text-primary-400" />
              <span className="text-sm font-medium text-gray-300">{t('bots.builder.allExchanges')}</span>
              {mode === 'both' && (
                <span className="text-xs text-gray-400 ml-auto">{t('bots.builder.bothModeNote')}</span>
              )}
            </div>

            {/* Mobile: Cards */}
            <div className="sm:hidden space-y-2">
              {balanceOverview.map(entry => {
                const isSelected = entry.exchange_type === exchangeType && entry.mode === effectiveMode
                const isOver = entry.existing_allocated_pct > 100
                return (
                  <div key={`${entry.exchange_type}-${entry.mode}`} className={`p-3 rounded-lg border transition-colors ${
                    isSelected ? 'bg-primary-500/5 border-primary-500/20' : 'bg-white/[0.02] border-white/[0.06]'
                  }`}>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <ExchangeLogo exchange={entry.exchange_type} size={18} />
                        {isSelected && <span className="w-1.5 h-1.5 rounded-full bg-primary-400" />}
                        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                          entry.mode === 'demo' ? 'bg-blue-500/10 text-blue-400' : 'bg-orange-500/10 text-orange-400'
                        }`}>
                          {entry.mode.toUpperCase()}
                        </span>
                      </div>
                      <span className="font-mono text-sm font-semibold text-gray-200">
                        ${entry.exchange_equity.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                        <span className="text-gray-400 ml-0.5 text-xs font-normal">{entry.currency}</span>
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-xs">
                      <span className={isOver ? 'text-red-400' : 'text-amber-400'}>
                        {t('bots.builder.allocated')}: {entry.existing_allocated_pct.toFixed(0)}%
                        <span className="text-gray-400 ml-1">(${entry.existing_allocated_amount.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })})</span>
                      </span>
                      <span className="text-green-400">
                        {t('bots.builder.available')}: ${entry.remaining_balance.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Desktop: Table */}
            <div className="hidden sm:block overflow-x-auto rounded-lg border border-white/[0.04]">
              <table className="w-full text-xs min-w-[480px]">
                <thead>
                  <tr className="bg-white/[0.03] text-gray-400 text-xs uppercase tracking-wider">
                    <th scope="col" className="text-left px-3 py-1.5 font-medium">{t('bots.builder.exchange')}</th>
                    <th scope="col" className="text-left px-2 py-1.5 font-medium">{t('bots.builder.mode')}</th>
                    <th scope="col" className="text-right px-2 py-1.5 font-medium">{t('bots.builder.equity')}</th>
                    <th scope="col" className="text-right px-2 py-1.5 font-medium">{t('bots.builder.allocated')}</th>
                    <th scope="col" className="text-right px-3 py-1.5 font-medium">{t('bots.builder.available')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {balanceOverview.map(entry => {
                    const isSelected = entry.exchange_type === exchangeType && entry.mode === effectiveMode
                    const isOver = entry.existing_allocated_pct > 100
                    return (
                      <tr key={`${entry.exchange_type}-${entry.mode}`} className={`transition-colors ${
                        isSelected ? 'bg-primary-500/5' : 'hover:bg-white/[0.02]'
                      }`}>
                        <td className="px-3 py-2 flex items-center gap-1.5">
                          <ExchangeLogo exchange={entry.exchange_type} size={14} />
                          {isSelected && <span className="w-1 h-1 rounded-full bg-primary-400" />}
                        </td>
                        <td className="px-2 py-2">
                          <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                            entry.mode === 'demo' ? 'bg-blue-500/10 text-blue-400' : 'bg-orange-500/10 text-orange-400'
                          }`}>
                            {entry.mode.toUpperCase()}
                          </span>
                        </td>
                        <td className="px-2 py-2 text-right tabular-nums text-gray-300">
                          ${entry.exchange_equity.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                          <span className="text-gray-400 ml-0.5 text-xs">{entry.currency}</span>
                        </td>
                        <td className={`px-2 py-2 text-right tabular-nums ${isOver ? 'text-red-400' : 'text-amber-400'}`}>
                          {entry.existing_allocated_pct.toFixed(0)}%
                          <span className="text-gray-400 ml-1">(${entry.existing_allocated_amount.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })})</span>
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-green-400">
                          ${entry.remaining_balance.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {/* Warnings for the selected exchange */}
            {isOverAllocated && (
              <div className="mt-3 flex items-center gap-1.5 text-xs text-amber-400">
                <AlertTriangle size={13} />
                {t('bots.builder.overAllocatedWarning', { pct: selectedEntry ? (totalAllocated / selectedEntry.exchange_equity * 100).toFixed(0) : '0' })}
              </div>
            )}
            {!isOverAllocated && isInsufficientBalance && (
              <div className="mt-3 flex items-center gap-1.5 text-xs text-amber-400">
                <AlertTriangle size={13} />
                {t('bots.builder.insufficientBalanceWarning', {
                  needed: thisBotUsdt.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
                  available: (selectedEntry?.remaining_balance ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
                })}
              </div>
            )}
          </div>
        )
      })()}

      {/* Per-asset config */}
      {tradingPairs.length > 0 && (
        <div>
          <label className="block text-sm text-gray-400 mb-3">{t('bots.builder.perAssetConfig')}</label>
          <div className="space-y-3">
            {tradingPairs.map(pair => {
              const cfg = perAssetConfig[pair] || {}
              return (
                <div key={pair} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-white">{pair}</span>
                    {balancePreview && balancePreview.remaining_balance > 0 && (
                      <span className="text-[10px] text-gray-400">
                        {t('bots.builder.availableShort')}: <span className="text-green-400 tabular-nums">${balancePreview.remaining_balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                      </span>
                    )}
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    <div>
                      <label className="block text-xs text-gray-300 mb-1">{t('bots.builder.budgetUsdt')}</label>
                      <NumInput value={cfg.position_usdt ?? ''} onChange={e => updateAsset(pair, 'position_usdt', e.target.value)}
                        placeholder="-" min={1} max={999999} step={1}
                        className={`filter-select w-full text-sm tabular-nums text-center ${
                          balancePreview && cfg.position_usdt && cfg.position_usdt > balancePreview.remaining_balance ? 'border-amber-500/50' : ''
                        }`} />
                    </div>
                    <div>
                      <label className="flex items-center gap-0.5 text-xs text-gray-300 mb-1">
                        {b.leverage}
                        <span className="relative group">
                          <Info size={10} className="text-blue-400 cursor-help" />
                          <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block w-44 p-1.5 text-[10px] text-gray-200 bg-gray-800 border border-gray-600 rounded-lg shadow-lg z-50 whitespace-normal leading-relaxed">
                            {t('bots.builder.leverageHint')}
                          </span>
                        </span>
                      </label>
                      <NumInput value={cfg.leverage ?? ''} onChange={e => updateAsset(pair, 'leverage', e.target.value)}
                        placeholder="-" min={1} max={20}
                        className="filter-select w-full text-sm tabular-nums text-center" />
                    </div>
                    <div>
                      <label className="flex items-center gap-0.5 text-xs text-gray-300 mb-1">
                        TP %
                        <span className="relative group">
                          <Info size={10} className="text-blue-400 cursor-help" />
                          <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block w-44 p-1.5 text-[10px] text-gray-200 bg-gray-800 border border-gray-600 rounded-lg shadow-lg z-50 whitespace-normal leading-relaxed">
                            {t('bots.builder.tpHint')}
                          </span>
                        </span>
                      </label>
                      <NumInput value={cfg.tp ?? ''} onChange={e => updateAsset(pair, 'tp', e.target.value)}
                        placeholder="-" min={0.5} max={20} step={0.5}
                        className="filter-select w-full text-sm tabular-nums text-center" />
                    </div>
                    <div>
                      <label className="flex items-center gap-0.5 text-xs text-gray-300 mb-1">
                        SL %
                        <span className="relative group">
                          <Info size={10} className="text-blue-400 cursor-help" />
                          <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block w-44 p-1.5 text-[10px] text-gray-200 bg-gray-800 border border-gray-600 rounded-lg shadow-lg z-50 whitespace-normal leading-relaxed">
                            {t('bots.builder.slHint')}
                          </span>
                        </span>
                      </label>
                      <NumInput value={cfg.sl ?? ''} onChange={e => updateAsset(pair, 'sl', e.target.value)}
                        placeholder="-" min={0.5} max={10} step={0.5}
                        className="filter-select w-full text-sm tabular-nums text-center" />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-300 mb-1">{b.maxTrades}</label>
                      <NumInput value={cfg.max_trades ?? ''} onChange={e => updateAsset(pair, 'max_trades', e.target.value)}
                        placeholder="-" min={1} max={50}
                        className="filter-select w-full text-sm tabular-nums text-center" />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-300 mb-1">{b.dailyLossLimit}</label>
                      <NumInput value={cfg.loss_limit ?? ''} onChange={e => updateAsset(pair, 'loss_limit', e.target.value)}
                        placeholder="-" min={1} max={50} step={0.5}
                        className="filter-select w-full text-sm tabular-nums text-center" />
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
          {/* Balance preview */}
          <div className="mt-3 flex flex-wrap gap-2 text-xs text-gray-400">
            {(() => {
              const totalFixed = tradingPairs.reduce((sum, p) => sum + (perAssetConfig[p]?.position_usdt || 0), 0)
              const unfixedCount = tradingPairs.filter(p => !perAssetConfig[p]?.position_usdt).length
              const equity = balancePreview?.exchange_equity || 0
              const remaining = Math.max(0, equity - totalFixed)
              const perUnfixed = unfixedCount > 0 ? remaining / unfixedCount : 0
              return tradingPairs.map(p => {
                const usdt = perAssetConfig[p]?.position_usdt || perUnfixed
                return (
                  <span key={p} className="bg-white/5 px-2 py-0.5 rounded">
                    {p}: <span className="tabular-nums">${usdt.toFixed(0)}</span>
                    {equity > 0 && <span className="text-gray-400 ml-1">({(usdt / equity * 100).toFixed(1)}%)</span>}
                  </span>
                )
              })
            })()}
          </div>
          <p className="text-xs text-gray-400 mt-1">{t('bots.builder.perAssetHint')}</p>
          {/* TP/SL warning */}
          {(() => {
            const pairsWithoutSl = tradingPairs.filter(p => !perAssetConfig[p]?.sl)
            const pairsWithoutTpSl = tradingPairs.filter(p => !perAssetConfig[p]?.tp && !perAssetConfig[p]?.sl)
            if (pairsWithoutTpSl.length > 0 && pairsWithoutTpSl.length === pairsWithoutSl.length) {
              return (
                <div className="mt-2 flex items-start gap-2 p-2.5 bg-amber-900/20 border border-amber-800/50 rounded-lg w-fit">
                  <AlertTriangle size={14} className="text-amber-400 mt-0.5 flex-shrink-0" />
                  <p className="text-xs text-amber-400">{t('bots.builder.noTpSlWarning')}</p>
                </div>
              )
            }
            if (pairsWithoutSl.length > 0) {
              return (
                <div className="mt-2 flex items-start gap-2 p-2.5 bg-yellow-900/20 border border-yellow-800/50 rounded-lg w-fit">
                  <AlertTriangle size={14} className="text-yellow-400 mt-0.5 flex-shrink-0" />
                  <p className="text-xs text-yellow-400">{t('bots.builder.noSlWarning')}</p>
                </div>
              )
            }
            return null
          })()}
        </div>
      )}

    </div>
  )
}
