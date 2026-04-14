import { Trans, useTranslation } from 'react-i18next'
import { Check, LayoutGrid, List, Zap, Clock } from 'lucide-react'
import FilterDropdown from '../ui/FilterDropdown'
import NumInput from '../ui/NumInput'
import type { Strategy, ParamDef, ParamOption } from './BotBuilderTypes'
import { STRATEGY_RECOMMENDATIONS } from './BotBuilderTypes'
import { strategyLabel as getStrategyDisplayName } from '../../constants/strategies'

interface Props {
  strategies: Strategy[]
  strategyType: string
  strategyParams: Record<string, any>
  strategyView: 'grid' | 'list'
  proMode: boolean
  targetExchange?: string
  onStrategyChange: (name: string) => void
  onStrategyParamsChange: (params: Record<string, any>) => void
  onStrategyViewChange: (view: 'grid' | 'list') => void
  onToggleProMode: () => void
  b: Record<string, string>
}

export default function BotBuilderStepStrategy({
  strategies, strategyType, strategyParams, strategyView, proMode, targetExchange: _targetExchange,
  onStrategyChange, onStrategyParamsChange, onStrategyViewChange, onToggleProMode,
  b,
}: Props) {
  const { t } = useTranslation()
  const selectedStrategy = strategies.find(s => s.name === strategyType)

  const setParam = (key: string, value: any) => {
    onStrategyParamsChange({ ...strategyParams, [key]: value })
  }

  const setParams = (updates: Record<string, any>) => {
    onStrategyParamsChange({ ...strategyParams, ...updates })
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm text-gray-400">{b.selectStrategy}</label>
          <div className="flex items-center gap-1 bg-white/5 rounded-lg p-0.5">
            <button
              type="button"
              onClick={() => onStrategyViewChange('grid')}
              className={`p-1.5 rounded-md transition-colors ${strategyView === 'grid' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
              title={b.viewGrid}
            >
              <LayoutGrid size={14} />
            </button>
            <button
              type="button"
              onClick={() => onStrategyViewChange('list')}
              className={`p-1.5 rounded-md transition-colors ${strategyView === 'list' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
              title={b.viewList}
            >
              <List size={14} />
            </button>
          </div>
        </div>

        {strategyView === 'grid' ? (
          <div className="grid grid-cols-2 gap-2">
            {strategies.map(s => {
              const isSelected = strategyType === s.name
              return (
                <button
                  key={s.name}
                  onClick={() => onStrategyChange(s.name)}
                  className={`text-left p-3 rounded-xl border transition-all ${
                    isSelected
                      ? 'border-primary-500 bg-primary-500/10 ring-1 ring-primary-500/30'
                      : 'border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]'
                  }`}
                >
                  <div className={`flex items-center gap-1.5 text-sm font-medium ${isSelected ? 'text-primary-400' : 'text-white'}`}>
                    {getStrategyDisplayName(s.name)}
                  </div>
                  <div className="text-xs text-gray-400 mt-1 line-clamp-2">
                    {t(`bots.builder.strategyDesc_${s.name}`, { defaultValue: s.description })}
                  </div>
                </button>
              )
            })}
          </div>
        ) : (
          <div className="space-y-1">
            {strategies.map(s => {
              const isSelected = strategyType === s.name
              return (
                <button
                  key={s.name}
                  onClick={() => onStrategyChange(s.name)}
                  className={`w-full flex flex-col gap-1 px-3 py-2.5 rounded-xl border transition-all text-left ${
                    isSelected
                      ? 'border-primary-500 bg-primary-500/10 ring-1 ring-primary-500/30'
                      : 'border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]'
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    {isSelected && <Check size={14} className="text-primary-400 shrink-0" />}
                    <span className={`text-sm font-medium ${isSelected ? 'text-primary-400' : 'text-white'}`}>
                      {getStrategyDisplayName(s.name)}
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 leading-relaxed">
                    {t(`bots.builder.strategyDesc_${s.name}`, { defaultValue: s.description })}
                  </p>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {/* Strategy Recommendations from Backtest */}
      {strategyType && strategyType === 'edge_indicator' && STRATEGY_RECOMMENDATIONS[strategyType] && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-primary-500/10 border border-primary-500/20">
          <Clock size={14} className="text-primary-400 shrink-0" />
          <span className="text-xs text-primary-300">
            <Trans i18nKey="bots.builder.recommendedTimeframe" values={{ timeframe: STRATEGY_RECOMMENDATIONS[strategyType].bestTimeframe }} components={{ strong: <strong /> }} />
            {' · '}
            <Trans i18nKey="bots.builder.recommendedSchedule" values={{ minutes: STRATEGY_RECOMMENDATIONS[strategyType].scheduleMinutes }} components={{ strong: <strong /> }} />
          </span>
          <span className="text-xs text-gray-400 ml-auto">{t('bots.builder.backtestDays')}</span>
        </div>
      )}

      {selectedStrategy && Object.keys(selectedStrategy.param_schema).length > 0 && (() => {
        // For copy_trading bots, Step 2 only shows the core fields
        // (source_wallet, budget_usdt, max_slots). The whitelist/blacklist
        // pickers and wallet validator live in Step 3.
        const isCopyTrading = strategyType === 'copy_trading'
        const copyTradingStep2Keys = new Set(['source_wallet', 'budget_usdt', 'max_slots'])
        const schemaEntries = Object.entries(selectedStrategy.param_schema).filter(
          ([key]) => !isCopyTrading || copyTradingStep2Keys.has(key)
        )
        const selectEntries = schemaEntries.filter(
          ([, def]) => (def as ParamDef).type === 'select' || (def as ParamDef).type === 'dependent_select'
        )
        const textareaEntries = schemaEntries.filter(
          ([, def]) => (def as ParamDef).type === 'textarea'
        )
        const textEntries = schemaEntries.filter(
          ([, def]) => (def as ParamDef).type === 'text'
        )
        // All non-select, non-textarea, non-text params go behind Pro Mode
        const proModeEntries = schemaEntries.filter(
          ([, def]) => {
            const d = def as ParamDef
            return d.type !== 'select' && d.type !== 'dependent_select' && d.type !== 'textarea' && d.type !== 'text'
          }
        )
        const hasAlwaysVisible = selectEntries.length > 0 || textareaEntries.length > 0 || textEntries.length > 0 || isCopyTrading
        // For copy_trading, budget_usdt + max_slots are rendered inline; no Pro Mode needed.
        const hasProParams = !isCopyTrading && proModeEntries.length > 0

        return (
          <div>
            {/* Always visible: select dropdowns + textarea params */}
            {hasAlwaysVisible && (
              <div className="space-y-3">
                {selectEntries.length > 0 && (
                  <div className="flex items-end gap-3 flex-wrap">
                    {selectEntries.map(([key, def]) => {
                      const d = def as ParamDef
                      if (d.type === 'select' && d.options) {
                        const selectOptions = d.options.map(opt => {
                          const value = typeof opt === 'string' ? opt : opt.value
                          const rawLabel = typeof opt === 'string' ? opt : opt.label
                          const i18nKey = `bots.builder.paramOption_${key}_${value}`
                          const translated = t(i18nKey, '')
                          return { value, label: translated || rawLabel }
                        })
                        const paramLabel = t(`bots.builder.paramLabel_${key}`, '') || d.label
                        const paramDesc = t(`bots.builder.paramDesc_${key}`, '') || d.description
                        return (
                          <div key={key}>
                            <label className="block text-xs text-gray-300 mb-1">{paramLabel}</label>
                            <FilterDropdown
                              value={String(strategyParams[key] ?? d.default)}
                              onChange={val => {
                                const updates: Record<string, any> = { [key]: val }
                                if (key === 'risk_profile') {
                                  const klineMap: Record<string, string> = { conservative: '4h', standard: '1h', aggressive: '15m' }
                                  if (klineMap[val]) updates.kline_interval = klineMap[val]
                                }
                                setParams(updates)
                              }}
                              options={selectOptions}
                              ariaLabel={paramLabel}
                            />
                            {paramDesc && <p className="text-[10px] text-gray-400 mt-1">{paramDesc}</p>}
                          </div>
                        )
                      }
                      if (d.type === 'dependent_select' && d.options_map && d.depends_on) {
                        const parentValue = (strategyParams[d.depends_on] ?? '') as string
                        const depOptions = (d.options_map[parentValue] || []).map((opt: ParamOption) => ({
                          value: opt.value,
                          label: opt.label,
                        }))
                        const currentValue = strategyParams[key] ?? ''
                        const isValid = depOptions.some(opt => opt.value === currentValue)
                        const displayValue = isValid ? String(currentValue) : (depOptions[0]?.value ?? '')
                        const depLabel = t(`bots.builder.paramLabel_${key}`, '') || d.label
                        const depDesc = t(`bots.builder.paramDesc_${key}`, '') || d.description
                        return (
                          <div key={key}>
                            <label className="block text-xs text-gray-300 mb-1">{depLabel}</label>
                            <FilterDropdown
                              value={displayValue}
                              onChange={val => setParam(key, val)}
                              options={depOptions}
                              ariaLabel={depLabel}
                            />
                            {depDesc && <p className="text-[10px] text-gray-400 mt-1">{depDesc}</p>}
                          </div>
                        )
                      }
                      return null
                    })}
                  </div>
                )}

                {/* First pass: render source_wallet (and any non-symbol-list text params) */}
                {textEntries
                  .filter(([key]) => key !== 'symbol_whitelist' && key !== 'symbol_blacklist')
                  .map(([key, def]) => {
                    const d = def as ParamDef
                    const txtLabel = t(`bots.builder.paramLabel_${key}`, '') || d.label
                    const txtDesc = t(`bots.builder.paramDesc_${key}`, '') || d.description
                    const placeholder = key === 'source_wallet' ? '0x…' : ''
                    return (
                      <div key={key}>
                        <label className="block text-xs text-gray-300 mb-1">{txtLabel}</label>
                        <input
                          type="text"
                          value={strategyParams[key] ?? ''}
                          onChange={e => setParam(key, e.target.value)}
                          placeholder={placeholder}
                          className="filter-select w-full text-sm font-mono"
                        />
                        {txtDesc && <p className="text-[10px] text-gray-400 mt-1">{txtDesc}</p>}
                      </div>
                    )
                  })}

                {/* Copy-trading wallet validator moved to Step 3 */}

                {/* For copy_trading, render budget_usdt and max_slots as always-visible numeric inputs */}
                {isCopyTrading && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {proModeEntries
                      .filter(([key]) => key === 'budget_usdt' || key === 'max_slots')
                      .map(([key, def]) => {
                        const d = def as ParamDef
                        const numLabel = t(`bots.builder.paramLabel_${key}`, '') || d.label
                        const numDesc = t(`bots.builder.paramDesc_${key}`, '') || d.description
                        const val = strategyParams[key] ?? d.default ?? ''
                        return (
                          <div key={key}>
                            <label className="block text-xs text-gray-300 mb-1">{numLabel}</label>
                            <NumInput
                              value={val}
                              onChange={e => setParam(key, parseFloat(e.target.value) || 0)}
                              min={d.min}
                              max={d.max}
                              step={d.type === 'float' ? 0.01 : 1}
                              className="filter-select text-sm w-full"
                            />
                            {numDesc && <p className="text-[10px] text-gray-400 mt-1">{numDesc}</p>}
                          </div>
                        )
                      })}
                  </div>
                )}

                {/* Second pass: symbol_whitelist / symbol_blacklist with chip-pickers */}
                {textEntries
                  .filter(([key]) => key === 'symbol_whitelist' || key === 'symbol_blacklist')
                  .map(([key, def]) => {
                    const d = def as ParamDef
                    const txtLabel = t(`bots.builder.paramLabel_${key}`, '') || d.label
                    const txtDesc = t(`bots.builder.paramDesc_${key}`, '') || d.description
                    const currentValue: string = strategyParams[key] ?? ''
                    const currentSet = new Set(
                      currentValue.split(',').map((s: string) => s.trim().toUpperCase()).filter(Boolean)
                    )
                    const validation = strategyParams._validation
                    const availableCoins: string[] = validation?.available ?? []

                    const toggleCoin = (coin: string) => {
                      const next = new Set(currentSet)
                      if (next.has(coin)) next.delete(coin)
                      else next.add(coin)
                      setParam(key, Array.from(next).join(', '))
                    }

                    return (
                      <div key={key}>
                        <label className="block text-xs text-gray-300 mb-1">{txtLabel}</label>
                        <input
                          type="text"
                          value={currentValue}
                          onChange={e => setParam(key, e.target.value)}
                          placeholder="z.B. BTC, ETH, SOL"
                          className="filter-select w-full text-sm font-mono"
                        />
                        <p className="text-[10px] text-gray-400 mt-1">
                          {txtDesc} — {t('bots.builder.copyTrading.symbolFormatHint', 'Hyperliquid Coin-Namen ohne USDT-Suffix, kommagetrennt')}
                        </p>
                        {availableCoins.length > 0 && (
                          <div className="mt-2">
                            <p className="text-[10px] text-gray-500 mb-1">
                              {t('bots.builder.copyTrading.clickToAdd', 'Klick zum Hinzufügen')}:
                            </p>
                            <div className="flex flex-wrap gap-1">
                              {availableCoins.map((coin) => {
                                const isActive = currentSet.has(coin.toUpperCase())
                                return (
                                  <button
                                    key={coin}
                                    type="button"
                                    onClick={() => toggleCoin(coin.toUpperCase())}
                                    className={`px-2 py-0.5 rounded text-[10px] font-mono transition-colors ${
                                      isActive
                                        ? 'bg-primary-500/25 text-primary-300 ring-1 ring-primary-500/40'
                                        : 'bg-white/5 text-gray-400 hover:bg-white/10 hover:text-gray-200'
                                    }`}
                                  >
                                    {coin}
                                  </button>
                                )
                              })}
                            </div>
                          </div>
                        )}
                      </div>
                    )
                  })}

                {textareaEntries.map(([key, def]) => {
                  const d = def as ParamDef
                  const taLabel = t(`bots.builder.paramLabel_${key}`, '') || d.label
                  const taDesc = t(`bots.builder.paramDesc_${key}`, '') || d.description
                  return (
                    <div key={key}>
                      <label className="block text-xs text-gray-300 mb-1">{taLabel}</label>
                      {taDesc && <p className="text-[10px] text-gray-400 mb-1.5">{taDesc}</p>}
                      <textarea
                        value={strategyParams[key] ?? ''}
                        onChange={e => setParam(key, e.target.value)}
                        rows={6}
                        placeholder={t('bots.builder.customPromptPlaceholder')}
                        className="filter-select w-full text-sm font-mono !h-auto"
                      />
                    </div>
                  )
                })}
              </div>
            )}

            {/* Pro Mode toggle — reveals ALL strategy params */}
            {hasProParams && (
              <div className={`${hasAlwaysVisible ? 'mt-6' : ''} border-t border-white/5 pt-4`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Zap size={15} className={proMode ? 'text-amber-400' : 'text-gray-500'} />
                    <div>
                      <span className="text-sm font-medium text-gray-300">Pro Mode</span>
                      <p className="text-xs text-gray-400">
                        {proMode
                          ? b.proModeParamsActiveHint
                          : b.proModeParamsHint}
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={onToggleProMode}
                    role="switch"
                    aria-checked={proMode}
                    aria-label="Pro Mode"
                    className={`relative w-11 h-6 rounded-full transition-colors ${proMode ? 'bg-amber-500' : 'bg-gray-700'}`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${proMode ? 'translate-x-5' : ''}`} />
                  </button>
                </div>

                {proMode && (() => {
                  const tempEntry = proModeEntries.find(([k]) => k === 'temperature')
                  const boolEntries = proModeEntries.filter(([, def]) => (def as ParamDef).type === 'bool')
                  const numericEntries = proModeEntries.filter(([k, def]) => {
                    const d = def as ParamDef
                    return k !== 'temperature' && d.type !== 'bool'
                  })

                  // Range position as percentage (0-100)
                  const rangePercent = (val: number, min: number, max: number) => {
                    if (max === min) return 50
                    return Math.max(0, Math.min(100, ((val - min) / (max - min)) * 100))
                  }

                  return (
                    <div className="mt-4 space-y-3">
                      {/* Temperature — dedicated slider */}
                      {tempEntry && (() => {
                        const [tKey, tDef] = tempEntry
                        const td = tDef as ParamDef
                        const tVal = Number(strategyParams[tKey] ?? td.default)
                        const pct = rangePercent(tVal, td.min ?? 0, td.max ?? 1)
                        const tempLabel = t(`bots.builder.paramLabel_${tKey}`, '') || td.label
                        return (
                          <div className="relative overflow-hidden rounded-lg bg-gradient-to-r from-gray-800/40 to-gray-800/20 px-3 py-2 max-w-md">
                            <div className="flex items-center justify-between mb-1.5">
                              <span className="text-[10px] font-medium text-gray-400 uppercase tracking-wider">{tempLabel}</span>
                              <span className="text-xs font-mono font-semibold text-amber-400">{tVal.toFixed(1)}</span>
                            </div>
                            <div className="relative h-1.5 rounded-full bg-gray-900/60 overflow-hidden">
                              <div
                                className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-blue-500 via-amber-400 to-red-500 transition-all"
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                            <input
                              type="range" min={td.min} max={td.max} step={0.1} value={tVal}
                              onChange={e => setParam(tKey, parseFloat(e.target.value))}
                              aria-label={tempLabel}
                              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer touch-none"
                            />
                            <div className="flex justify-between mt-1">
                              <span className="text-[10px] text-gray-400">{t('bots.builder.deterministic')}</span>
                              <span className="text-[10px] text-gray-400">{t('bots.builder.creative')}</span>
                            </div>
                          </div>
                        )
                      })()}

                      {/* Bool toggles — compact inline pills */}
                      {boolEntries.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {boolEntries.map(([key, def]) => {
                            const d = def as ParamDef
                            const isOn = strategyParams[key] ?? d.default
                            const boolLabel = t(`bots.builder.paramLabel_${key}`, '') || d.label
                            const boolDesc = t(`bots.builder.paramDesc_${key}`, '') || d.description
                            return (
                              <button
                                key={key} type="button"
                                onClick={() => setParam(key, !isOn)}
                                title={boolDesc}
                                className={`inline-flex items-center gap-1.5 pl-2 pr-2.5 py-1.5 rounded-full text-[11px] font-medium transition-all ${
                                  isOn
                                    ? 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/25'
                                    : 'bg-gray-800/40 text-gray-500 ring-1 ring-white/[0.04]'
                                }`}
                              >
                                <span className={`w-1.5 h-1.5 rounded-full ${isOn ? 'bg-emerald-400' : 'bg-gray-600'}`} />
                                {boolLabel}
                              </button>
                            )
                          })}
                        </div>
                      )}

                      {/* Numeric params — compact 2-col grid */}
                      {numericEntries.length > 0 && (
                        <div className="grid grid-cols-2 gap-2">
                          {numericEntries.map(([key, def]) => {
                            const d = def as ParamDef
                            const val = Number(strategyParams[key] ?? d.default)
                            const numLabel = t(`bots.builder.paramLabel_${key}`, '') || d.label
                            const numDesc = t(`bots.builder.paramDesc_${key}`, '') || d.description

                            return (
                              <div
                                key={key}
                                className="rounded-md bg-gray-800/30 px-2.5 py-2 border border-white/[0.04] hover:border-white/[0.08] transition-colors"
                              >
                                <label className="block text-xs text-gray-400 mb-1 truncate">{numLabel}</label>
                                <NumInput
                                  value={val}
                                  onChange={e => setParam(key, parseFloat(e.target.value) || 0)}
                                  min={d.min}
                                  max={d.max}
                                  step={d.type === 'float' ? 0.0001 : 1}
                                  className="filter-select text-sm !w-full text-gray-200"
                                />
                                {numDesc && <p className="text-[10px] text-gray-400 mt-1 leading-tight">{numDesc}</p>}
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )
                })()}
              </div>
            )}
          </div>
        )
      })()}
    </div>
  )
}
