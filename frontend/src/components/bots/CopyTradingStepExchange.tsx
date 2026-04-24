import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import NumInput from '../ui/NumInput'
import CopyTradingValidator from './CopyTradingValidator'

interface Props {
  exchangeType: string
  mode: 'live' | 'demo' | string
  strategyParams: Record<string, any>
  onStrategyParamsChange: (params: Record<string, any>) => void
  onTradingPairsChange: (pairs: string[]) => void
}

type ChipPickerProps = {
  label: string
  paramKey: 'symbol_whitelist' | 'symbol_blacklist'
  value: string
  available: string[]
  onChange: (next: string) => void
  placeholder?: string
  description?: string
}

function SymbolChipPicker({ label, paramKey, value, available, onChange, placeholder, description }: ChipPickerProps) {
  const { t } = useTranslation()
  const currentSet = new Set(
    value.split(',').map(s => s.trim().toUpperCase()).filter(Boolean)
  )

  const toggleCoin = (coin: string) => {
    const next = new Set(currentSet)
    if (next.has(coin)) next.delete(coin)
    else next.add(coin)
    onChange(Array.from(next).join(', '))
  }

  return (
    <div>
      <label className="block text-xs text-gray-300 mb-1">{label}</label>
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder ?? 'z.B. BTC, ETH, SOL'}
        className="filter-select w-full text-sm font-mono"
        data-param={paramKey}
      />
      {description && (
        <p className="text-[10px] text-gray-400 mt-1">
          {description} — {t('bots.builder.copyTrading.symbolFormatHint', 'Hyperliquid Coin-Namen ohne USDT-Suffix, kommagetrennt')}
        </p>
      )}
      {available.length > 0 && (
        <div className="mt-2">
          <p className="text-[10px] text-gray-500 mb-1">
            {t('bots.builder.copyTrading.clickToAdd', 'Klick zum Hinzufügen')}:
          </p>
          <div className="flex flex-wrap gap-1">
            {available.map(coin => {
              const upper = coin.toUpperCase()
              const isActive = currentSet.has(upper)
              return (
                <button
                  key={coin}
                  type="button"
                  onClick={() => toggleCoin(upper)}
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
}

export default function CopyTradingStepExchange({
  exchangeType,
  strategyParams,
  onStrategyParamsChange,
  onTradingPairsChange,
}: Props) {
  const { t } = useTranslation()

  // Set the sentinel trading pair once on mount so backend validation passes.
  useEffect(() => {
    onTradingPairsChange(['__copy__'])
    // Intentional: run once on mount. Excluding onTradingPairsChange — parent
    // passes a fresh closure on every render, so including it would re-fire
    // the effect on every parent render and spam the sentinel write.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const setParam = (key: string, value: any) => {
    onStrategyParamsChange({ ...strategyParams, [key]: value })
  }

  const setNumParam = (key: string, raw: string) => {
    if (raw === '' || raw === undefined) {
      const next = { ...strategyParams }
      delete next[key]
      onStrategyParamsChange(next)
      return
    }
    const num = parseFloat(raw)
    if (!Number.isNaN(num)) setParam(key, num)
  }

  const validation = strategyParams._validation
  const availableCoins: string[] = validation?.available ?? []

  const whitelistValue: string = strategyParams.symbol_whitelist ?? ''
  const blacklistValue: string = strategyParams.symbol_blacklist ?? ''

  return (
    <div className="space-y-6">
      {/* Block 1 — Wallet & Symbol Filter */}
      <div className="border border-white/[0.06] bg-white/[0.02] rounded-xl p-4">
        <h3 className="text-sm text-gray-400 mb-3">
          {t('bots.builder.copyTradingStep3.blockFilter', 'Wallet & Symbol-Filter')}
        </h3>
        <div className="space-y-4">
          {strategyParams.source_wallet && exchangeType && (
            <CopyTradingValidator
              wallet={strategyParams.source_wallet}
              targetExchange={exchangeType}
              onValidated={(r) => onStrategyParamsChange({ ...strategyParams, _validation: r })}
            />
          )}

          <SymbolChipPicker
            label={t('bots.builder.paramLabel_symbol_whitelist', 'Symbol-Whitelist')}
            paramKey="symbol_whitelist"
            value={whitelistValue}
            available={availableCoins}
            onChange={(next) => setParam('symbol_whitelist', next)}
          />

          <SymbolChipPicker
            label={t('bots.builder.paramLabel_symbol_blacklist', 'Symbol-Blacklist')}
            paramKey="symbol_blacklist"
            value={blacklistValue}
            available={availableCoins}
            onChange={(next) => setParam('symbol_blacklist', next)}
          />
        </div>
      </div>

      {/* Block 2 — Risk Overrides */}
      <div className="border border-white/[0.06] bg-white/[0.02] rounded-xl p-4">
        <h3 className="text-sm text-gray-400 mb-3">
          {t('bots.builder.copyTradingStep3.blockOverrides', 'Risiko-Overrides')}
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-gray-300 mb-1">
              {t('bots.builder.copyTradingStep3.leverage', 'Hebel')}
            </label>
            <NumInput
              value={strategyParams.leverage ?? ''}
              onChange={e => setNumParam('leverage', e.target.value)}
              placeholder={t('bots.builder.copyTradingStep3.emptyLikeSource', 'leer = wie Source') as string}
              min={1}
              max={125}
              step={1}
              className="filter-select w-full text-sm tabular-nums"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-300 mb-1">
              {t('bots.builder.copyTradingStep3.takeProfit', 'Take Profit %')}
            </label>
            <NumInput
              value={strategyParams.take_profit_pct ?? ''}
              onChange={e => setNumParam('take_profit_pct', e.target.value)}
              placeholder={t('bots.builder.copyTradingStep3.emptyLikeSource', 'leer = wie Source') as string}
              min={0.1}
              max={100}
              step={0.1}
              className="filter-select w-full text-sm tabular-nums"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-300 mb-1">
              {t('bots.builder.copyTradingStep3.stopLoss', 'Stop Loss %')}
            </label>
            <NumInput
              value={strategyParams.stop_loss_pct ?? ''}
              onChange={e => setNumParam('stop_loss_pct', e.target.value)}
              placeholder={t('bots.builder.copyTradingStep3.emptyLikeSource', 'leer = wie Source') as string}
              min={0.1}
              max={50}
              step={0.1}
              className="filter-select w-full text-sm tabular-nums"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-300 mb-1">
              {t('bots.builder.copyTradingStep3.minSize', 'Min. Trade-Größe (USDT)')}
            </label>
            <NumInput
              value={strategyParams.min_position_size_usdt ?? 10}
              onChange={e => setNumParam('min_position_size_usdt', e.target.value)}
              placeholder="10"
              min={1}
              max={1000}
              step={1}
              className="filter-select w-full text-sm tabular-nums"
            />
          </div>
        </div>
        <p className="text-[11px] italic text-gray-400 mt-3">
          {t('bots.builder.copyTradingStep3.overridesHint', 'Felder leer = die Werte der Source-Wallet werden 1:1 übernommen.')}
        </p>
      </div>

      {/* Block 3 — Globale Sicherheits-Limits */}
      <div className="border border-white/[0.06] bg-white/[0.02] rounded-xl p-4">
        <h3 className="text-sm text-gray-400 mb-3">
          {t('bots.builder.copyTradingStep3.blockSafety', 'Globale Sicherheits-Limits')}
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-gray-300 mb-1">
              {t('bots.builder.copyTradingStep3.dailyLossLimit', 'Tägliches Verlustlimit %')}
            </label>
            <NumInput
              value={strategyParams.daily_loss_limit_pct ?? ''}
              onChange={e => setNumParam('daily_loss_limit_pct', e.target.value)}
              placeholder="-"
              min={0.5}
              max={50}
              step={0.5}
              className="filter-select w-full text-sm tabular-nums"
            />
            <p className="text-[10px] text-gray-400 mt-1">
              {t('bots.builder.copyTradingStep3.dailyLossLimitHint', 'Bei Erreichen werden alle weiteren Kopien bis Mitternacht UTC pausiert')}
            </p>
          </div>
          <div>
            <label className="block text-xs text-gray-300 mb-1">
              {t('bots.builder.copyTradingStep3.maxTradesPerDay', 'Max Trades pro Tag')}
            </label>
            <NumInput
              value={strategyParams.max_trades_per_day ?? ''}
              onChange={e => setNumParam('max_trades_per_day', e.target.value)}
              placeholder="-"
              min={1}
              max={200}
              step={1}
              className="filter-select w-full text-sm tabular-nums"
            />
            <p className="text-[10px] text-gray-400 mt-1">
              {t('bots.builder.copyTradingStep3.maxTradesPerDayHint', 'Maximale Anzahl kopierter Entries pro UTC-Tag')}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
