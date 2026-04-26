import { type KeyboardEvent } from 'react'
import {
  AlertCircle,
  AlertTriangle,
  ChevronDown,
  Clock,
  Copy,
  MoreVertical,
  Pencil,
  Play,
  RefreshCw,
  Shield,
  Square,
  Trash2,
  TrendingUp,
  XCircle,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ExchangeIcon } from '../ui/ExchangeLogo'
import PnlCell from '../ui/PnlCell'
import { formatTime } from '../../utils/dateUtils'
import { utcHourToLocal } from '../../utils/timezone'
import { strategyLabel } from '../../constants/strategies'
import {
  STATUS_STYLES,
  formatHourLocal,
  getScheduleHoursUtc,
  shortenWallet,
  type BotStatus,
} from './types'

interface Props {
  bot: BotStatus
  isFirst: boolean
  isMobile: boolean
  isAdmin: boolean
  isExpanded: boolean
  actionLoading: number | null
  closePositionOpen: number | null
  moreMenuOpen: number | null
  onToggleExpand: () => void
  onStart: (id: number) => void
  onStopClick: (id: number) => void
  onClosePosition: (botId: number, symbol: string) => void
  onSetClosePositionOpen: (id: number | null) => void
  onShowHistory: (bot: BotStatus) => void
  onSetMoreMenuOpen: (id: number | null) => void
  onEdit: (id: number) => void
  onDuplicate: (id: number) => void
  onDelete: (id: number, name: string) => void
}

export default function BotCard({
  bot,
  isFirst,
  isMobile,
  isAdmin,
  isExpanded,
  actionLoading,
  closePositionOpen,
  moreMenuOpen,
  onToggleExpand,
  onStart,
  onStopClick,
  onClosePosition,
  onSetClosePositionOpen,
  onShowHistory,
  onSetMoreMenuOpen,
  onEdit,
  onDuplicate,
  onDelete,
}: Props) {
  const { t } = useTranslation()
  const style = STATUS_STYLES[bot.status] || STATUS_STYLES.idle
  const isBotExpanded = !isMobile || isExpanded

  return (
    <div
      className={`glass-card rounded-xl ${isMobile ? 'p-3' : 'p-5'} border transition-all duration-300 ${style.card} ${moreMenuOpen === bot.bot_config_id ? 'relative z-30' : ''}`}
      {...(isFirst ? { 'data-tour': 'bot-card' } : {})}
    >
      {/* Header row */}
      <div
        className={`flex items-start justify-between gap-2 ${isBotExpanded ? 'mb-3' : ''} ${isMobile ? 'cursor-pointer' : ''}`}
        {...(isMobile
          ? {
              role: 'button',
              tabIndex: 0,
              'aria-expanded': isBotExpanded,
              onClick: onToggleExpand,
              onKeyDown: (e: KeyboardEvent) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  onToggleExpand()
                }
              },
            }
          : {})}
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className={`text-white font-semibold ${isMobile ? 'text-[13px]' : 'text-lg'} truncate block`}>{bot.name}</span>
            {isMobile && bot.status === 'running' && (
              <span className="relative flex h-2 w-2 shrink-0">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className="badge-neutral text-xs inline-flex items-center gap-1">
              <ExchangeIcon exchange={bot.exchange_type} size={16} />
            </span>
            <span className={bot.mode === 'demo' ? 'badge-demo text-xs' : bot.mode === 'live' ? 'badge-live text-xs' : 'badge-open text-xs'}>
              {bot.mode.toUpperCase()}
            </span>
            <span className="text-xs text-gray-500 inline-flex items-center gap-1">
              {strategyLabel(bot.strategy_type)}
              {bot.strategy_type === 'copy_trading' ? (
                <span className="text-gray-400">
                  · Source: <span className="font-mono">{shortenWallet(bot.copy_source_wallet)}</span>
                  {bot.copy_max_slots != null && <> · Slots: {bot.open_trades}/{bot.copy_max_slots}</>}
                  {bot.copy_budget_usdt != null && <> · Budget: ${bot.copy_budget_usdt}</>}
                </span>
              ) : bot.risk_profile && (
                <span className={`inline-flex items-center gap-0.5 ${
                  bot.risk_profile === 'aggressive' ? 'text-red-400' :
                  bot.risk_profile === 'conservative' ? 'text-blue-400' :
                  'text-gray-500'
                }`}>
                  · <Shield size={10} />
                  {t(`bots.builder.paramOption_risk_profile_${bot.risk_profile}`)}
                </span>
              )}
            </span>
          </div>
        </div>
        <div className="text-right shrink-0 flex items-center gap-1.5">
          <div>
            <div className="flex items-center justify-end gap-1.5">
              {!isMobile && bot.status === 'running' && (
                <span className="relative flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
                </span>
              )}
              <span className={`text-sm font-medium ${style.text}`}>
                {isMobile ? '' : t(`bots.${bot.status}`)}
              </span>
            </div>
          </div>
          {isMobile && (
            <ChevronDown size={14} className={`text-gray-400 transition-transform ${isBotExpanded ? 'rotate-180' : ''}`} />
          )}
        </div>
      </div>

      {/* Collapsible content on mobile */}
      {isBotExpanded && (
      <>

      {/* Pairs */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {bot.trading_pairs.map(pair => (
          <span key={pair} className="text-xs px-2 py-0.5 bg-white/5 text-gray-300 rounded-md border border-white/5">
            {pair}
          </span>
        ))}
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-1 sm:gap-2 mb-3 text-center" {...(isFirst ? { 'data-tour': 'bot-stats' } : {})}>
        <div>
          <div className="text-xs text-gray-400 uppercase tracking-wider">{t('bots.totalPnl')}</div>
          <div className={`text-base font-semibold ${bot.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
            <PnlCell
              pnl={bot.total_pnl}
              fees={bot.total_fees ?? 0}
              fundingPaid={bot.total_funding ?? 0}
              className={`text-base font-semibold ${bot.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}
            />
          </div>
        </div>
        <div>
          <div className="text-xs text-gray-400 uppercase tracking-wider">{t('bots.trades')}</div>
          <div className="text-base text-white font-semibold">{bot.total_trades}</div>
        </div>
        <div>
          <div className="text-xs text-gray-400 uppercase tracking-wider">{t('bots.openTrades')}</div>
          <div className={`text-base font-semibold ${bot.open_trades > 0 ? 'text-amber-400' : 'text-white'}`}>
            {bot.open_trades > 0 && <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 mr-1.5 mb-0.5 animate-pulse" />}
            {bot.open_trades}
          </div>
        </div>
      </div>

      {/* Error message */}
      {bot.error_message && (
        <div className="flex items-center gap-1.5 mb-3 text-sm text-red-400 bg-red-500/5 rounded-lg px-2.5 py-2">
          <AlertCircle size={14} />
          <span className="truncate">{bot.error_message}</span>
        </div>
      )}

      {/* Hyperliquid gate warning: setup incomplete (hidden for admins) */}
      {!isAdmin && bot.exchange_type === 'hyperliquid' && (bot.builder_fee_approved === false || bot.referral_verified === false) && bot.status !== 'running' && (
        <div className="flex items-center gap-1.5 mb-3 text-xs text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg px-2.5 py-2">
          <AlertTriangle size={14} className="shrink-0" />
          <span>{t('hlSetup.botCardWarning', 'Einrichtung in Einstellungen erforderlich')}</span>
        </div>
      )}

      {/* Last analysis + schedule dots */}
      {bot.last_analysis && (
        <div className="mb-3">
          <div className="flex items-center gap-1.5 text-sm text-gray-500">
            <Clock size={14} />
            {t('bots.lastAnalysis')}: {formatTime(bot.last_analysis)}
          </div>
          {(() => {
            const hours = getScheduleHoursUtc(bot.schedule_type, bot.schedule_config)
            if (hours) {
              const nowLocal = new Date().getHours()
              const mapped = hours.map(utcH => {
                const local = utcHourToLocal(utcH)
                return { utcH, local, isPast: local <= nowLocal }
              })
              const lastDone = [...mapped].filter(h => h.isPast).pop()
              const nextUp = mapped.find(h => !h.isPast)
              return (
                <div className="flex items-center gap-3 mt-1.5 ml-5">
                  {mapped.map(({ utcH, isPast }) => {
                    const isLast = lastDone && lastDone.utcH === utcH
                    const isNext = nextUp && nextUp.utcH === utcH
                    return (
                      <span key={utcH} className={`inline-flex items-center gap-1 text-xs ${
                        isLast ? 'text-emerald-400' : isPast ? 'text-gray-500' : 'text-white/30'
                      }`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${
                          isLast ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]' : isPast ? 'bg-gray-500' : 'bg-white/20'
                        }`} />
                        {formatHourLocal(utcH)}
                        {isNext && <span className="text-[10px] text-white/40 ml-0.5">&#x25C2;</span>}
                      </span>
                    )
                  })}
                </div>
              )
            }
            if (bot.schedule_type === 'interval' && bot.schedule_config?.interval_minutes) {
              return (
                <div className="flex items-center gap-1.5 mt-1 ml-5 text-xs text-gray-500">
                  <RefreshCw size={10} />
                  {t('bots.scheduleEvery', { minutes: bot.schedule_config.interval_minutes })}
                </div>
              )
            }
            return null
          })()}
        </div>
      )}

      {/* Close Position — sichtbar solange Trades offen sind (auch bei gestopptem Bot) */}
      {bot.open_trades > 0 && (
        <div className="mb-3">
          {bot.trading_pairs.length === 1 ? (
            <button
              onClick={() => onClosePosition(bot.bot_config_id, bot.trading_pairs[0])}
              disabled={actionLoading === bot.bot_config_id}
              className="w-full flex items-center justify-center gap-2 px-3 py-2.5 text-sm font-medium bg-amber-500/10 text-amber-400 rounded-xl border border-amber-500/25 hover:bg-amber-500/20 hover:border-amber-500/40 disabled:opacity-50 transition-all duration-200"
            >
              <XCircle size={15} />
              {t('bots.closePosition')} {bot.trading_pairs[0]}
            </button>
          ) : (
            <div className="relative">
              <button
                onClick={() => onSetClosePositionOpen(closePositionOpen === bot.bot_config_id ? null : bot.bot_config_id)}
                disabled={actionLoading === bot.bot_config_id}
                className="w-full flex items-center justify-center gap-2 px-3 py-2.5 text-sm font-medium bg-amber-500/10 text-amber-400 rounded-xl border border-amber-500/25 hover:bg-amber-500/20 hover:border-amber-500/40 disabled:opacity-50 transition-all duration-200"
              >
                <XCircle size={15} />
                {t('bots.closePosition')} ({bot.open_trades})
                <ChevronDown size={14} className={`transition-transform ${closePositionOpen === bot.bot_config_id ? 'rotate-180' : ''}`} />
              </button>
              {closePositionOpen === bot.bot_config_id && (
                <>
                  <button
                    type="button"
                    aria-label={t('common.close')}
                    tabIndex={-1}
                    onClick={() => onSetClosePositionOpen(null)}
                    className="fixed inset-0 z-10 w-full h-full bg-transparent border-0 appearance-none cursor-default"
                  />
                  <div className="absolute left-0 right-0 top-full mt-1 z-20 bg-[#1a1f2e] border border-amber-500/20 rounded-xl shadow-xl overflow-hidden">
                    {bot.trading_pairs.map(symbol => (
                      <button
                        key={symbol}
                        onClick={() => { onSetClosePositionOpen(null); onClosePosition(bot.bot_config_id, symbol) }}
                        disabled={actionLoading === bot.bot_config_id}
                        className="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-amber-400 hover:bg-amber-500/10 disabled:opacity-30 transition-colors"
                      >
                        <XCircle size={14} />
                        {symbol}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 pt-3 border-t border-white/5" {...(isFirst ? { 'data-tour': 'bot-actions' } : {})}>
        {bot.status === 'running' ? (
          <button
            onClick={() => onStopClick(bot.bot_config_id)}
            disabled={actionLoading === bot.bot_config_id}
            aria-label={`${t('bots.stop')} ${bot.name}`}
            className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs rounded-lg border disabled:opacity-50 transition-all duration-200 bg-red-500/10 text-red-400 border-red-500/10 hover:bg-red-500/20"
          >
            <Square size={14} />
            {t('bots.stop')}
          </button>
        ) : (
          <button
            onClick={() => onStart(bot.bot_config_id)}
            disabled={actionLoading === bot.bot_config_id}
            aria-label={`${t('bots.start')} ${bot.name}`}
            className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs bg-emerald-500/10 text-emerald-400 rounded-lg border border-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-50 transition-all duration-200"
          >
            {actionLoading === bot.bot_config_id ? (
              <RefreshCw size={14} className="animate-spin" />
            ) : (
              <Play size={14} />
            )}
            {t('bots.start')}
          </button>
        )}
        <button
          onClick={() => onShowHistory(bot)}
          aria-label={t('bots.showTrades')}
          className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs text-primary-400 bg-primary-500/10 hover:bg-primary-500/20 border border-primary-500/20 transition-all duration-200 rounded-lg"
          title={t('bots.tradeHistory')}
        >
          <TrendingUp size={14} />
          {t('bots.tradeHistory')}
        </button>
        {/* 3-dot menu for Edit, Duplicate, Delete */}
        <div className="relative flex-shrink-0">
          <button
            onClick={(e) => { e.stopPropagation(); onSetMoreMenuOpen(moreMenuOpen === bot.bot_config_id ? null : bot.bot_config_id) }}
            aria-label={t('bots.moreActions')}
            className="p-2 text-gray-400 hover:text-white transition-all duration-200 rounded-lg hover:bg-white/5"
            title={t('bots.moreActions')}
          >
            <MoreVertical size={16} />
          </button>
          {/* Desktop dropdown menu */}
          {!isMobile && moreMenuOpen === bot.bot_config_id && (
            <div className="absolute left-0 top-full mt-1 w-48 bg-[#141a2a] border border-white/10 rounded-xl shadow-2xl z-50 py-1 overflow-hidden">
              <button
                onClick={() => { onSetMoreMenuOpen(null); onEdit(bot.bot_config_id) }}
                disabled={bot.status === 'running'}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-gray-200 hover:bg-white/5 disabled:opacity-30 transition-colors"
              >
                <Pencil size={15} /> {t('bots.edit')}
              </button>
              <button
                onClick={() => { onSetMoreMenuOpen(null); onDuplicate(bot.bot_config_id) }}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-gray-200 hover:bg-white/5 transition-colors"
              >
                <Copy size={15} /> {t('bots.duplicate')}
              </button>
              <div className="border-t border-white/5 my-0.5" />
              <button
                onClick={() => { onSetMoreMenuOpen(null); onDelete(bot.bot_config_id, bot.name) }}
                disabled={bot.status === 'running'}
                className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-red-400 hover:bg-red-500/5 disabled:opacity-30 transition-colors"
              >
                <Trash2 size={15} /> {t('bots.delete')}
              </button>
            </div>
          )}
        </div>
      </div>
      </>
      )}
    </div>
  )
}
