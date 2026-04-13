import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Bot, TrendingUp, ArrowLeftRight, Clock, Shield, Database, Bell } from 'lucide-react'
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
  discordConfigured: boolean
  telegramConfigured: boolean
  discordWebhookUrl: string
  telegramBotToken: string
  pnlAlertSettings: { enabled: boolean; mode: 'dollar' | 'percent'; threshold: number; direction: 'profit' | 'loss' | 'both' }
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
  discordConfigured, telegramConfigured, discordWebhookUrl, telegramBotToken, pnlAlertSettings,
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

      {/* Notifications */}
      <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-white/5 bg-white/[0.02]">
          <Bell size={16} className="text-primary-400" />
          <span className="text-sm font-semibold text-white">{t('settings.notifications')}</span>
        </div>
        <div className="px-4 py-1">
          <ReviewRow label="Discord">
            {discordWebhookUrl || discordConfigured ? (
              <span className="flex items-center gap-1.5 text-emerald-400">
                <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="#5865F2"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>
                {t('common.active', 'Aktiv')}
              </span>
            ) : (
              <span className="text-gray-500">{t('common.inactive', 'Nicht konfiguriert')}</span>
            )}
          </ReviewRow>
          <ReviewRow label="Telegram">
            {(telegramBotToken) || telegramConfigured ? (
              <span className="flex items-center gap-1.5 text-emerald-400">
                <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="#26A5E4"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0h-.056zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.479.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg>
                {t('common.active', 'Aktiv')}
              </span>
            ) : (
              <span className="text-gray-500">{t('common.inactive', 'Nicht konfiguriert')}</span>
            )}
          </ReviewRow>
          <ReviewRow label="PnL-Alerts">
            {pnlAlertSettings.enabled ? (
              <span className="text-amber-400 text-xs">
                {pnlAlertSettings.direction === 'both' ? 'Gewinn & Verlust' : pnlAlertSettings.direction === 'profit' ? 'Gewinn' : 'Verlust'}
                {' '}| {pnlAlertSettings.threshold}{pnlAlertSettings.mode === 'percent' ? '%' : '$'}
              </span>
            ) : (
              <span className="text-gray-500">{t('common.inactive', 'Nicht konfiguriert')}</span>
            )}
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
