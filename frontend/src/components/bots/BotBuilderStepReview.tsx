import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Bot, TrendingUp, ArrowLeftRight, Clock, Shield, Database } from 'lucide-react'
import ExchangeLogo from '../ui/ExchangeLogo'
import type { BalancePreview, SymbolConflict, PerAssetEntry } from './BotBuilderTypes'
import { strategyLabel as getStrategyDisplayName } from '../../constants/strategies'

interface Props {
  name: string
  strategyType: string
  strategyParams?: Record<string, any>
  exchangeType: string
  mode: string
  marginMode: 'cross' | 'isolated'
  tradingPairs: string[]
  perAssetConfig: Record<string, PerAssetEntry>
  balancePreview: BalancePreview | null
  scheduleType: string
  intervalMinutes: number | ''
  customHours: number[]
  maxTrades: number | null
  dailyLossLimit: number | null
  symbolConflicts: SymbolConflict[]
  selectedSources: string[]
  usesData: boolean
  hasFixedSources: boolean
  riskAccepted: boolean
  onRiskAcceptedChange: (val: boolean) => void
  b: Record<string, string>
}

/* Reusable row for review sections */
function ReviewRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-white/5 last:border-b-0">
      <span className="text-gray-400 text-sm">{label}</span>
      <span className="text-white text-sm font-medium text-right">{children}</span>
    </div>
  )
}

export default function BotBuilderStepReview({
  name, strategyType, strategyParams, exchangeType, mode, marginMode,
  tradingPairs, perAssetConfig, balancePreview,
  scheduleType, intervalMinutes, customHours,
  maxTrades, dailyLossLimit,
  symbolConflicts, selectedSources, usesData, hasFixedSources,
  riskAccepted, onRiskAcceptedChange,
  b,
}: Props) {
  const { t } = useTranslation()

  return (
    <div className="space-y-4">
      <h3 className="text-white font-medium mb-4">{b.review}</h3>

      {/* Bot Identity */}
      <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-white/5 bg-white/[0.02]">
          <Bot size={16} className="text-primary-400" />
          <span className="text-sm font-semibold text-white">Bot</span>
        </div>
        <div className="px-4 py-1">
          <ReviewRow label={b.name}>{name}</ReviewRow>
          <ReviewRow label={b.mode}>
            <span className={mode === 'live' ? 'text-emerald-400' : 'text-amber-400'}>
              {mode.toUpperCase()}
            </span>
          </ReviewRow>
        </div>
      </div>

      {/* Strategy & Exchange */}
      <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-white/5 bg-white/[0.02]">
          <TrendingUp size={16} className="text-primary-400" />
          <span className="text-sm font-semibold text-white">{b.strategy} & {b.exchange}</span>
        </div>
        <div className="px-4 py-1">
          <ReviewRow label={b.strategy}>{getStrategyDisplayName(strategyType)}</ReviewRow>
          <ReviewRow label={b.exchange}>
            <span className="inline-flex items-center gap-1.5">
              <ExchangeLogo exchange={exchangeType} size={14} />
            </span>
          </ReviewRow>
          <ReviewRow label={t('bots.builder.marginMode')}>{t(`bots.builder.${marginMode}`)}</ReviewRow>
        </div>
      </div>

      {/* Trading Pairs — hidden for copy_trading (assets are decided by source wallet) */}
      {strategyType !== 'copy_trading' && (
        <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
          <div className="flex items-center gap-2.5 px-4 py-3 border-b border-white/5 bg-white/[0.02]">
            <ArrowLeftRight size={16} className="text-primary-400" />
            <span className="text-sm font-semibold text-white">{b.tradingPairs}</span>
            <span className="ml-auto text-xs text-gray-500">{tradingPairs.length} {tradingPairs.length === 1 ? 'Pair' : 'Pairs'}</span>
          </div>
          <div className="px-4 py-3">
            <div className="flex flex-wrap gap-1.5">
              {tradingPairs.map(p => (
                <span key={p} className="px-2.5 py-1 rounded-lg bg-primary-500/10 text-primary-400 text-xs font-medium border border-primary-500/20">
                  {p}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Copy Trading config summary */}
      {strategyType === 'copy_trading' && strategyParams && (
        <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
          <div className="flex items-center gap-2.5 px-4 py-3 border-b border-white/5 bg-white/[0.02]">
            <ArrowLeftRight size={16} className="text-primary-400" />
            <span className="text-sm font-semibold text-white">Copy Trading</span>
          </div>
          <div className="px-4 py-3 space-y-1.5 text-xs">
            {strategyParams.source_wallet && (
              <div className="text-gray-300">
                <span className="text-gray-500">Source:</span>{' '}
                <span className="font-mono">{`${String(strategyParams.source_wallet).slice(0, 6)}…${String(strategyParams.source_wallet).slice(-4)}`}</span>
              </div>
            )}
            <div className="text-gray-300">
              <span className="text-gray-500">Budget:</span> ${strategyParams.budget_usdt ?? '—'}{' · '}
              <span className="text-gray-500">Slots:</span> {strategyParams.max_slots ?? '—'}
            </div>
            {strategyParams.symbol_whitelist && (
              <div className="text-gray-300">
                <span className="text-gray-500">Whitelist:</span> {strategyParams.symbol_whitelist}
              </div>
            )}
            {strategyParams.symbol_blacklist && (
              <div className="text-gray-300">
                <span className="text-gray-500">Blacklist:</span> {strategyParams.symbol_blacklist}
              </div>
            )}
            {(strategyParams.leverage || strategyParams.take_profit_pct || strategyParams.stop_loss_pct) && (
              <div className="text-gray-300">
                <span className="text-gray-500">Overrides:</span>{' '}
                {strategyParams.leverage && `${strategyParams.leverage}x · `}
                {strategyParams.take_profit_pct && `TP ${strategyParams.take_profit_pct}% · `}
                {strategyParams.stop_loss_pct && `SL ${strategyParams.stop_loss_pct}%`}
              </div>
            )}
            {(strategyParams.daily_loss_limit_pct || strategyParams.max_trades_per_day) && (
              <div className="text-gray-300">
                <span className="text-gray-500">Sicherheits-Limits:</span>{' '}
                {strategyParams.daily_loss_limit_pct && `Daily Loss ${strategyParams.daily_loss_limit_pct}% · `}
                {strategyParams.max_trades_per_day && `${strategyParams.max_trades_per_day} Trades/Tag`}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Data Sources (if applicable) */}
      {usesData && (
        <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
          <div className="flex items-center gap-2.5 px-4 py-3 border-b border-white/5 bg-white/[0.02]">
            <Database size={16} className="text-primary-400" />
            <span className="text-sm font-semibold text-white">{b.dataSources}</span>
          </div>
          <div className="px-4 py-1">
            <ReviewRow label={b.dataSources}>
              {hasFixedSources
                ? `${selectedSources.length} (${b.fixedSources})`
                : `${selectedSources.length} ${b.sourcesSelected}`}
            </ReviewRow>
          </div>
        </div>
      )}

      {/* Schedule */}
      <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-white/5 bg-white/[0.02]">
          <Clock size={16} className="text-primary-400" />
          <span className="text-sm font-semibold text-white">{b.schedule}</span>
        </div>
        <div className="px-4 py-1">
          <ReviewRow label={b.schedule}>
            {scheduleType === 'interval' ? `${t('bots.builder.interval')} (${intervalMinutes || '\u2013'} Min.)` :
             scheduleType === 'custom_cron' ? customHours.map(h => `${h}:00`).join(', ') :
             scheduleType}
          </ReviewRow>
        </div>
      </div>

      {/* Risk Limits */}
      {(maxTrades != null || dailyLossLimit != null) && (
        <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
          <div className="flex items-center gap-2.5 px-4 py-3 border-b border-white/5 bg-white/[0.02]">
            <Shield size={16} className="text-primary-400" />
            <span className="text-sm font-semibold text-white">{b.riskLimits || t('bots.builder.riskLimits')}</span>
          </div>
          <div className="px-4 py-1">
            {maxTrades != null && (
              <ReviewRow label={b.maxTrades}>{maxTrades}</ReviewRow>
            )}
            {dailyLossLimit != null && (
              <ReviewRow label={b.dailyLossLimit}>{dailyLossLimit}%</ReviewRow>
            )}
          </div>
        </div>
      )}

      {/* Symbol conflict warning */}
      {symbolConflicts.length > 0 && (
        <div className="p-3 bg-amber-900/30 border border-amber-800 rounded-xl space-y-1.5">
          <div className="flex items-center gap-2 text-amber-400 font-medium text-sm">
            <AlertTriangle size={16} className="flex-shrink-0" />
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

      {/* Per-asset config review — hidden for copy_trading */}
      {strategyType !== 'copy_trading' && tradingPairs.length > 0 && (
        <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
          <div className="flex items-center gap-2.5 px-4 py-3 border-b border-white/5 bg-white/[0.02]">
            <ArrowLeftRight size={16} className="text-primary-400" />
            <span className="text-sm font-semibold text-white">{t('bots.builder.perAssetConfig')}</span>
          </div>
          <div className="px-4 py-3">
            <div className="flex flex-wrap gap-2 text-xs">
              {(() => {
                const totalFixed = tradingPairs.reduce((sum, p) => sum + (perAssetConfig[p]?.position_usdt || 0), 0)
                const unfixedCount = tradingPairs.filter(p => !perAssetConfig[p]?.position_usdt).length
                const equity = balancePreview?.exchange_equity || 0
                const remaining = Math.max(0, equity - totalFixed)
                const perUnfixed = unfixedCount > 0 ? remaining / unfixedCount : 0
                return tradingPairs.map(p => {
                  const cfg = perAssetConfig[p] || {}
                  const usdt = cfg.position_usdt || perUnfixed
                  const parts = [`$${usdt.toFixed(0)}`]
                  if (cfg.leverage) parts.push(`${cfg.leverage}x`)
                  if (cfg.tp) parts.push(`TP ${cfg.tp}%`)
                  if (cfg.sl) parts.push(`SL ${cfg.sl}%`)
                  if (!cfg.tp && !cfg.sl) parts.push(t('bots.builder.noTpSlLabel'))
                  if (cfg.max_trades) parts.push(`${cfg.max_trades} Trades`)
                  if (cfg.loss_limit) parts.push(`Verlust ${cfg.loss_limit}%`)
                  return (
                    <span key={p} className="bg-white/5 px-2.5 py-1.5 rounded-lg border border-white/5">
                      <span className="text-white font-medium">{p}</span>
                      <span className="text-gray-400 ml-1.5">{parts.join(' \u00B7 ')}</span>
                    </span>
                  )
                })
              })()}
            </div>
          </div>
        </div>
      )}

      {/* Risk Disclaimer */}
      <div className="mt-6 p-4 bg-amber-500/5 border border-amber-500/20 rounded-xl">
        <div className="flex items-center gap-2 mb-2">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5 text-amber-400 shrink-0"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
          <h4 className="text-amber-400 font-semibold text-sm">{b.riskDisclaimerTitle}</h4>
        </div>
        <p className="text-gray-400 text-xs leading-relaxed mb-3">{b.riskDisclaimer}</p>
        <label className="flex items-start gap-2.5 cursor-pointer group">
          <input
            type="checkbox"
            checked={riskAccepted}
            onChange={(e) => onRiskAcceptedChange(e.target.checked)}
            className="mt-0.5 w-4 h-4 rounded border-amber-500/30 bg-white/5 text-amber-500 focus:ring-amber-500/30 shrink-0"
          />
          <span className="text-xs text-gray-300 group-hover:text-white transition-colors leading-relaxed">{b.riskAccept}</span>
        </label>
      </div>
    </div>
  )
}
