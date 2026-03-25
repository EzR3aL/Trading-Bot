import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toBlob } from 'html-to-image'
import api from '../api/client'
import { getApiErrorMessage } from '../utils/api-error'
import { useFilterStore } from '../stores/filterStore'
import type { LlmConnection } from '../types'
import { useThemeStore } from '../stores/themeStore'
import { useToastStore } from '../stores/toastStore'
import { utcHourToLocal } from '../utils/timezone'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import BotBuilder from '../components/bots/BotBuilder'
// BuilderFeeApproval moved to Settings page — no longer needed as a modal here
import { SkeletonBotCard } from '../components/ui/Skeleton'
import PnlCell from '../components/ui/PnlCell'
import ExitReasonBadge from '../components/ui/ExitReasonBadge'
import {
  Plus,
  Play,
  Square,
  Pencil,
  Trash2,
  AlertCircle,

  RefreshCw,
  Activity,
  Clock,
  TrendingUp,
  FileText,
  X,
  ArrowUpRight,
  ArrowDownRight,
  Copy,
  ChevronDown,
  Bot,
  MoreVertical,
  XCircle,
  Shield,
  ShieldCheck,
} from 'lucide-react'
import GuidedTour, { TourHelpButton, type TourStep } from '../components/ui/GuidedTour'
import { formatDate, formatDateTime, formatTime } from '../utils/dateUtils'
import MobileTradeCard from '../components/ui/MobileTradeCard'
import useIsMobile from '../hooks/useIsMobile'
import useHaptic from '../hooks/useHaptic'
import useSwipeToClose from '../hooks/useSwipeToClose'
import usePullToRefresh from '../hooks/usePullToRefresh'
import { useAuthStore } from '../stores/authStore'
import PullToRefreshIndicator from '../components/ui/PullToRefreshIndicator'

const STRATEGY_DISPLAY: Record<string, string> = { llm_signal: 'KI-Companion', sentiment_surfer: 'Sentiment Surfer', liquidation_hunter: 'Liquidation Hunter', degen: 'Degen', edge_indicator: 'Edge Indicator', contrarian_pulse: 'Contrarian Pulse' }
const AI_STRATEGIES = new Set(['llm_signal', 'degen'])
function strategyLabel(name: string) { return STRATEGY_DISPLAY[name] || name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) }

interface BotStatus {
  bot_config_id: number
  name: string
  strategy_type: string
  exchange_type: string
  mode: string
  trading_pairs: string[]
  status: string
  error_message: string | null
  started_at: string | null
  last_analysis: string | null
  trades_today: number
  is_enabled: boolean
  total_trades: number
  total_pnl: number
  total_fees: number
  total_funding: number
  open_trades: number
  llm_provider?: string | null
  llm_model?: string | null
  llm_last_direction?: string | null
  llm_last_confidence?: number | null
  llm_last_reasoning?: string | null
  llm_accuracy?: number | null
  llm_total_predictions?: number | null
  llm_total_tokens_used?: number | null
  llm_avg_tokens_per_call?: number | null
  schedule_type?: string | null
  schedule_config?: { interval_minutes?: number; hours?: number[] } | null
  risk_profile?: string | null
  builder_fee_approved?: boolean | null
  referral_verified?: boolean | null
}

interface BotTrade {
  id: number
  symbol: string
  side: string
  size: number
  entry_price: number
  exit_price: number | null
  pnl: number
  pnl_percent: number
  confidence: number
  reason: string
  status: string
  demo_mode: boolean
  entry_time: string
  exit_time: string | null
  exit_reason: string | null
  fees: number
  funding_paid: number
  trailing_stop_active?: boolean | null
  trailing_stop_price?: number | null
  trailing_stop_distance?: number | null
  trailing_stop_distance_pct?: number | null
  can_close_at_loss?: boolean | null
}

interface BotStatistics {
  bot_id: number
  bot_name: string
  strategy_type: string
  exchange_type: string
  summary: {
    total_trades: number
    wins: number
    losses: number
    win_rate: number
    total_pnl: number
    total_fees: number
    total_funding: number
    avg_pnl: number
    best_trade: number
    worst_trade: number
  }
  recent_trades: BotTrade[]
}

const STATUS_STYLES: Record<string, { text: string; card: string; dot: string }> = {
  running: {
    text: 'text-emerald-400',
    card: 'border-emerald-500/20 hover:border-emerald-500/30',
    dot: 'bg-emerald-500',
  },
  stopped: {
    text: 'text-gray-400',
    card: 'border-white/5 hover:border-white/10',
    dot: 'bg-gray-500',
  },
  idle: {
    text: 'text-gray-500',
    card: 'border-white/5 hover:border-white/10',
    dot: 'bg-gray-600',
  },
  error: {
    text: 'text-red-400',
    card: 'border-red-500/20 hover:border-red-500/30',
    dot: 'bg-red-500',
  },
  starting: {
    text: 'text-amber-400',
    card: 'border-amber-500/20 hover:border-amber-500/30',
    dot: 'bg-amber-500',
  },
}

function formatPnl(value: number): string {
  const prefix = value >= 0 ? '+' : ''
  return `${prefix}$${value.toFixed(2)}`
}

function formatPnlPercent(value: number): string {
  const prefix = value >= 0 ? '+' : ''
  return `${prefix}${value.toFixed(2)}%`
}

function confidenceColor(value: number): string {
  if (value >= 75) return 'text-emerald-400'
  if (value >= 50) return 'text-amber-400'
  return 'text-red-400'
}

/* ── Schedule Dots Helper ───────────────────────────────── */

function getScheduleHoursUtc(scheduleType?: string | null, scheduleConfig?: { interval_minutes?: number; hours?: number[] } | null): number[] | null {
  if (scheduleType === 'custom_cron' && scheduleConfig?.hours) return [...scheduleConfig.hours].sort((a, b) => a - b)
  return null
}

// utcHourToLocal is now imported from utils/timezone

function formatHourLocal(utcHour: number): string {
  return String(utcHourToLocal(utcHour)).padStart(2, '0')
}

/* ── Trade Detail Modal ──────────────────────────────────── */

function TradeDetailModal({ trade, onClose, t, affiliateLink }: { trade: BotTrade; onClose: () => void; t: (key: string) => string; affiliateLink?: AffiliateLink | null }) {
  const copyRef = useRef<HTMLDivElement>(null)
  const theme = useThemeStore((s) => s.theme)
  const [copied, setCopied] = useState(false)
  const isMobile = useIsMobile()
  const swipe = useSwipeToClose({ onClose, enabled: isMobile })

  const handleCopyImage = async () => {
    if (!copyRef.current) return
    try {
      const blob = await toBlob(copyRef.current, {
        pixelRatio: 2,
        backgroundColor: theme === 'light' ? '#f8fafc' : '#0b0f19',
      })
      if (!blob) return
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) { console.error('Failed to copy image:', err) }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-md" onClick={onClose} role="dialog" aria-modal="true" onKeyDown={(e) => { if (e.key === 'Escape') onClose() }}>
      <div
        ref={swipe.ref}
        style={swipe.style}
        className="bg-[#0f1420] rounded-2xl p-7 max-w-lg w-full mx-4 border border-white/10 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        aria-label={t('bots.tradeDetail')}
      >
        {isMobile && (
          <div className="flex justify-center pt-2 pb-1 lg:hidden">
            <div className="w-10 h-1 rounded-full bg-white/20" />
          </div>
        )}
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <h3 className="text-xl font-bold text-white">{trade.symbol}</h3>
            <span className={`px-3 py-1 rounded-lg text-xs font-bold ${
              trade.side === 'long' ? 'bg-emerald-500/15 text-profit border border-emerald-500/20' : 'bg-red-500/15 text-loss border border-red-500/20'
            }`}>
              {trade.side === 'long' ? '+ LONG' : '- SHORT'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleCopyImage}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg transition-all border ${
                copied
                  ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
                  : 'text-gray-400 hover:text-white bg-white/5 hover:bg-white/10 border-white/5'
              }`}
              title={t('bots.copyImage')}
            >
              <Copy size={13} />
              {copied ? t('bots.copied') : t('bots.copyImage')}
            </button>
            <button onClick={onClose} className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-all" aria-label="Close">
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Result - Hero */}
        <div className="text-center py-6 mb-5 bg-white/[0.02] rounded-xl border border-white/5">
          <div className="text-xs text-gray-400 uppercase tracking-wider mb-2">{t('bots.result')}</div>
          <div className={`text-5xl font-bold tracking-tight ${trade.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}`}>
            {formatPnlPercent(trade.pnl_percent)}
          </div>
          <div className={`text-lg font-semibold mt-1 ${trade.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`}>
            <PnlCell
              pnl={trade.pnl}
              fees={trade.fees ?? 0}
              fundingPaid={trade.funding_paid ?? 0}
              status={trade.status}
              className={`text-lg font-semibold ${trade.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`}
            />
          </div>
        </div>

        {/* Entry / Exit Price */}
        <div className="grid grid-cols-2 gap-3 mb-5">
          <div className="bg-white/[0.03] rounded-xl p-4 border border-white/5">
            <div className="text-xs text-gray-400 mb-1.5">{t('bots.entryPrice')}</div>
            <div className="text-white font-semibold text-lg">${trade.entry_price.toLocaleString()}</div>
          </div>
          <div className="bg-white/[0.03] rounded-xl p-4 border border-white/5">
            <div className="text-xs text-gray-400 mb-1.5">{t('bots.exitPrice')}</div>
            <div className="text-white font-semibold text-lg">
              {trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}
            </div>
          </div>
        </div>

        {/* Trailing Stop */}
        {trade.status === 'open' && trade.trailing_stop_active && trade.trailing_stop_price != null && (
          <div className="flex items-center justify-between mb-5 bg-emerald-500/5 rounded-xl p-4 border border-emerald-500/10">
            <span className="text-sm text-gray-400 flex items-center gap-2">
              <ShieldCheck size={16} className="text-emerald-400" />
              {t('trades.trailingStop')}
            </span>
            <span className="font-bold text-lg text-emerald-400">
              ${trade.trailing_stop_price.toLocaleString()} ({trade.trailing_stop_distance_pct?.toFixed(2)}%)
            </span>
          </div>
        )}

        {/* Confidence */}
        <div className="flex items-center justify-between mb-5 bg-white/[0.03] rounded-xl p-4 border border-white/5">
          <span className="text-sm text-gray-400">{t('bots.confidence')}</span>
          <span className={`font-bold text-lg ${confidenceColor(trade.confidence)}`}>{trade.confidence}%</span>
        </div>

        {/* Reasoning */}
        {trade.reason && (
          <div className="mb-5">
            <div className="text-xs text-gray-400 uppercase tracking-wider mb-2">{t('bots.reasoning')}</div>
            <p className="text-sm text-gray-300 leading-relaxed bg-white/[0.03] rounded-xl p-4 border border-white/5">
              {trade.reason}
            </p>
          </div>
        )}

        {/* Footer info */}
        <div className="flex items-center justify-between text-sm text-gray-500 pt-4 border-t border-white/5">
          <span>{formatDateTime(trade.entry_time)}</span>
          {trade.status === 'open'
            ? <span className="text-amber-400 font-medium">{t('bots.pending')}</span>
            : <ExitReasonBadge reason={trade.exit_reason} compact />
          }
        </div>
      </div>

      {/* Hidden compact card for image copy */}
      <div className="absolute -left-[9999px] pointer-events-none" aria-hidden="true">
        <div ref={copyRef} className="bg-[#0f1420] rounded-2xl p-7 w-[420px] border border-white/10 shadow-2xl">
          <div className="flex items-center gap-3 mb-5">
            <h3 className="text-xl font-bold text-white">{trade.symbol}</h3>
            <span className={`px-3 py-1 rounded-lg text-xs font-bold ${
              trade.side === 'long' ? 'bg-emerald-500/15 text-profit border border-emerald-500/20' : 'bg-red-500/15 text-loss border border-red-500/20'
            }`}>
              {trade.side === 'long' ? '+ LONG' : '- SHORT'}
            </span>
          </div>
          <div className="text-center py-6 mb-5 bg-white/[0.02] rounded-xl border border-white/5">
            <div className="text-xs text-gray-400 uppercase tracking-wider mb-2">{t('bots.result')}</div>
            <div className={`text-5xl font-bold tracking-tight ${trade.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}`}>
              {formatPnlPercent(trade.pnl_percent)}
            </div>
            <div className={`text-lg font-semibold mt-1 ${trade.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`}>
              <PnlCell pnl={trade.pnl} fees={trade.fees ?? 0} fundingPaid={trade.funding_paid ?? 0} status={trade.status}
                className={`text-lg font-semibold ${trade.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 mb-5">
            <div className="bg-white/[0.03] rounded-xl p-4 border border-white/5">
              <div className="text-xs text-gray-400 mb-1.5">{t('bots.entryPrice')}</div>
              <div className="text-white font-semibold text-lg">${trade.entry_price.toLocaleString()}</div>
            </div>
            <div className="bg-white/[0.03] rounded-xl p-4 border border-white/5">
              <div className="text-xs text-gray-400 mb-1.5">{t('bots.exitPrice')}</div>
              <div className="text-white font-semibold text-lg">{trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}</div>
            </div>
          </div>
          <div className="flex items-center justify-between mb-5 bg-white/[0.03] rounded-xl p-4 border border-white/5">
            <span className="text-sm text-gray-400">{t('bots.confidence')}</span>
            <span className={`font-bold text-lg ${confidenceColor(trade.confidence)}`}>{trade.confidence}%</span>
          </div>
          {trade.reason && (
            <div className="mb-5">
              <div className="text-xs text-gray-400 uppercase tracking-wider mb-2">{t('bots.reasoning')}</div>
              <p className="text-sm text-gray-300 leading-relaxed bg-white/[0.03] rounded-xl p-4 border border-white/5">{trade.reason}</p>
            </div>
          )}
          <div className="flex items-center justify-between text-sm text-gray-500 pt-4 border-t border-white/5">
            <span>{formatDateTime(trade.entry_time)}</span>
            <ExitReasonBadge reason={trade.exit_reason} compact />
          </div>
          {affiliateLink && (
            <div className="mt-3 pt-3 border-t border-white/5">
              <div className="text-xs text-gray-500 mb-1">{affiliateLink.label || t('bots.affiliateLink')}</div>
              <div className="text-xs text-primary-400 font-medium">{affiliateLink.affiliate_url}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ── Bot Trade History Modal ─────────────────────────────── */

interface AffiliateLink {
  exchange_type: string
  affiliate_url: string
  label: string | null
}

function BotTradeHistoryModal({ bot, onClose, t }: { bot: BotStatus; onClose: () => void; t: (key: string) => string }) {
  const [stats, setStats] = useState<BotStatistics | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedTrade, setSelectedTrade] = useState<BotTrade | null>(null)
  const [affiliateLink, setAffiliateLink] = useState<AffiliateLink | null>(null)
  const latestCardRef = useRef<HTMLDivElement>(null)
  const copyCardRef = useRef<HTMLDivElement>(null)
  const theme = useThemeStore((s) => s.theme)
  const isMobile = useIsMobile()
  const swipe = useSwipeToClose({ onClose, enabled: isMobile })

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const [statsRes, affRes] = await Promise.all([
          api.get(`/bots/${bot.bot_config_id}/statistics?days=365`),
          api.get('/affiliate-links'),
        ])
        setStats(statsRes.data)
        const links: AffiliateLink[] = affRes.data
        const match = links.find(l => l.exchange_type === bot.exchange_type)
        if (match) setAffiliateLink(match)
      } catch (err) { console.error('Failed to load bot trade history:', err) }
      setLoading(false)
    }
    load()
  }, [bot.bot_config_id, bot.exchange_type])

  const [copied, setCopied] = useState(false)

  const handleCopyImage = async () => {
    if (!copyCardRef.current) return
    try {
      const blob = await toBlob(copyCardRef.current, {
        pixelRatio: 2,
        backgroundColor: theme === 'light' ? '#f8fafc' : '#0b0f19',
      })
      if (!blob) return
      await navigator.clipboard.write([
        new ClipboardItem({ 'image/png': blob }),
      ])
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) { console.error('Failed to copy image:', err) }
  }

  const latestClosed = stats?.recent_trades.find(tr => tr.status === 'closed')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md" onClick={onClose} role="dialog" aria-modal="true" onKeyDown={(e) => { if (e.key === 'Escape') onClose() }}>
      <div
        ref={swipe.ref}
        style={swipe.style}
        className="bg-[#0b0f19] rounded-2xl max-w-5xl w-full mx-2 sm:mx-4 my-2 sm:my-3 max-h-[95vh] flex flex-col border border-white/10 shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
        aria-label={t('bots.tradeHistory')}
      >
        {isMobile && (
          <div className="flex justify-center pt-2 pb-1 lg:hidden">
            <div className="w-10 h-1 rounded-full bg-white/20" />
          </div>
        )}
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-3.5 border-b border-white/5 shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded-xl bg-white/5">
              <ExchangeIcon exchange={bot.exchange_type} size={20} />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">{bot.name}</h2>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-xs text-gray-500">{strategyLabel(bot.strategy_type)}</span>
                {AI_STRATEGIES.has(bot.strategy_type) && (
                  <Bot size={13} className="text-emerald-400" />
                )}
                {bot.risk_profile && (
                  <>
                    <span className="text-gray-700">·</span>
                    <span className={`inline-flex items-center gap-0.5 text-xs ${
                      bot.risk_profile === 'aggressive' ? 'text-red-400' :
                      bot.risk_profile === 'conservative' ? 'text-blue-400' :
                      'text-gray-500'
                    }`}>
                      <Shield size={11} />
                      {t(`bots.builder.paramOption_risk_profile_${bot.risk_profile}`)}
                    </span>
                  </>
                )}
                <span className="text-gray-700">|</span>
                <span className={`text-xs font-medium ${bot.mode === 'demo' ? 'text-blue-400' : 'text-amber-400'}`}>
                  {bot.mode.toUpperCase()}
                </span>
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-xl text-gray-400 hover:text-white hover:bg-white/5 transition-all"
            aria-label="Close"
          >
            <X size={22} />
          </button>
        </div>

        {/* Content - Scrollable */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <RefreshCw size={24} className="animate-spin text-gray-500" />
            </div>
          ) : !stats || stats.recent_trades.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-gray-500">
              <Activity size={40} className="mb-3 opacity-30" />
              <p className="text-sm">{t('bots.noTrades')}</p>
            </div>
          ) : (
            <>
              {/* Summary Stats */}
              <div className="grid grid-cols-2 gap-2 p-4">
                <div className="glass-card rounded-xl p-3 text-center border border-white/5">
                  <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{t('bots.totalPnl')}</div>
                  <PnlCell
                    pnl={stats.summary.total_pnl}
                    fees={stats.summary.total_fees}
                    fundingPaid={stats.summary.total_funding ?? 0}
                    className={`text-lg font-bold font-mono ${stats.summary.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}
                  />
                </div>
                <div className="glass-card rounded-xl p-3 text-center border border-white/5">
                  <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{t('bots.winRate')}</div>
                  <div className={`text-lg font-bold ${stats.summary.win_rate >= 60 ? 'text-profit' : stats.summary.win_rate >= 40 ? 'text-yellow-400' : 'text-loss'}`}>
                    {stats.summary.win_rate}%
                  </div>
                  <div className="text-[10px] text-gray-500 mt-0.5">{stats.summary.wins}W / {stats.summary.losses}L</div>
                </div>
                <div className="glass-card rounded-xl p-3 text-center border border-white/5">
                  <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1 flex items-center justify-center gap-1">
                    <ArrowUpRight size={11} className="text-profit" /> {t('bots.bestTrade')}
                  </div>
                  <div className="text-lg font-bold text-profit font-mono">{formatPnl(stats.summary.best_trade)}</div>
                </div>
                <div className="glass-card rounded-xl p-3 text-center border border-white/5">
                  <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1 flex items-center justify-center gap-1">
                    <ArrowDownRight size={11} className="text-loss" /> {t('bots.worstTrade')}
                  </div>
                  <div className="text-lg font-bold text-loss font-mono">{formatPnl(stats.summary.worst_trade)}</div>
                </div>
              </div>

              {/* Latest Trade */}
              {latestClosed && (
                <div className="mx-3 mt-4 mb-2">
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold">{t('bots.latestTrade')}</div>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleCopyImage() }}
                      className={`flex items-center gap-1.5 px-3 py-1 text-xs rounded-lg transition-all border ${
                        copied
                          ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
                          : 'text-gray-400 hover:text-white bg-white/5 hover:bg-white/10 border-white/5'
                      }`}
                      title={t('bots.copyImage')}
                    >
                      <Copy size={13} />
                      {copied ? t('bots.copied') : t('bots.copyImage')}
                    </button>
                  </div>
                  {/* Visible card — uses MobileTradeCard style on mobile */}
                  <div ref={latestCardRef}>
                    <MobileTradeCard
                      trade={{
                        ...latestClosed,
                        bot_exchange: bot.exchange_type,
                        bot_name: bot.name,
                        entry_time: latestClosed.entry_time || '',
                        demo_mode: bot.mode === 'demo',
                      }}
                      extraDetails={[
                        ...(latestClosed.reason ? [{ label: t('bots.reasoning'), value: latestClosed.reason }] : []),
                      ]}
                    />
                  </div>

                  {/* Hidden compact card — only used for "Bild kopieren" image export */}
                  <div className="absolute -left-[9999px] pointer-events-none" aria-hidden="true">
                    <div
                      ref={copyCardRef}
                      className="bg-[#0f1420] rounded-2xl p-7 w-[420px] border border-white/10 shadow-2xl"
                    >
                      <div className="flex items-center gap-3 mb-5">
                        <h3 className="text-xl font-bold text-white">{latestClosed.symbol}</h3>
                        <span className={`px-3 py-1 rounded-lg text-xs font-bold ${
                          latestClosed.side === 'long' ? 'bg-emerald-500/15 text-profit border border-emerald-500/20' : 'bg-red-500/15 text-loss border border-red-500/20'
                        }`}>
                          {latestClosed.side === 'long' ? '+ LONG' : '- SHORT'}
                        </span>
                      </div>
                      <div className="text-center py-6 mb-5 bg-white/[0.02] rounded-xl border border-white/5">
                        <div className="text-xs text-gray-400 uppercase tracking-wider mb-2">{t('bots.result')}</div>
                        <div className={`text-5xl font-bold tracking-tight ${latestClosed.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}`}>
                          {formatPnlPercent(latestClosed.pnl_percent)}
                        </div>
                        <div className={`text-lg font-semibold mt-1 ${latestClosed.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`}>
                          <PnlCell pnl={latestClosed.pnl} fees={latestClosed.fees ?? 0} fundingPaid={latestClosed.funding_paid ?? 0} status={latestClosed.status}
                            className={`text-lg font-semibold ${latestClosed.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`} />
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-3 mb-5">
                        <div className="bg-white/[0.03] rounded-xl p-4 border border-white/5">
                          <div className="text-xs text-gray-400 mb-1.5">{t('bots.entryPrice')}</div>
                          <div className="text-white font-semibold text-lg">${latestClosed.entry_price.toLocaleString()}</div>
                        </div>
                        <div className="bg-white/[0.03] rounded-xl p-4 border border-white/5">
                          <div className="text-xs text-gray-400 mb-1.5">{t('bots.exitPrice')}</div>
                          <div className="text-white font-semibold text-lg">{latestClosed.exit_price ? `$${latestClosed.exit_price.toLocaleString()}` : '--'}</div>
                        </div>
                      </div>
                      <div className="flex items-center justify-between mb-5 bg-white/[0.03] rounded-xl p-4 border border-white/5">
                        <span className="text-sm text-gray-400">{t('bots.confidence')}</span>
                        <span className={`font-bold text-lg ${confidenceColor(latestClosed.confidence)}`}>{latestClosed.confidence}%</span>
                      </div>
                      {latestClosed.reason && (
                        <div className="mb-5">
                          <div className="text-xs text-gray-400 uppercase tracking-wider mb-2">{t('bots.reasoning')}</div>
                          <p className="text-sm text-gray-300 leading-relaxed bg-white/[0.03] rounded-xl p-4 border border-white/5">{latestClosed.reason}</p>
                        </div>
                      )}
                      <div className="flex items-center justify-between text-sm text-gray-500 pt-4 border-t border-white/5">
                        <span>{formatDateTime(latestClosed.entry_time)}</span>
                        <ExitReasonBadge reason={latestClosed.exit_reason} compact />
                      </div>
                      {affiliateLink && (
                        <div className="mt-3 pt-3 border-t border-white/5">
                          <div className="text-xs text-gray-500 mb-1">{affiliateLink.label || t('bots.affiliateLink')}</div>
                          <div className="text-xs text-primary-400 font-medium">{affiliateLink.affiliate_url}</div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Trade History Table */}
              <div className="px-6 pt-3 pb-2">
                <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold">{t('bots.tradeHistory')}</div>
              </div>
              {isMobile ? (
                <div className="px-3 pb-6 space-y-1.5">
                  {stats.recent_trades.map(trade => (
                    <MobileTradeCard key={trade.id} trade={{ ...trade, bot_exchange: bot.exchange_type, entry_time: trade.entry_time || '' }} />
                  ))}
                </div>
              ) : (
                <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-t border-b border-white/5 bg-white/[0.02]">
                      <th className="text-left px-3 py-2.5 text-xs text-gray-400 uppercase font-semibold tracking-wider">{t('trades.date')}</th>
                      <th className="text-center px-3 py-2.5 text-xs text-gray-400 uppercase font-semibold tracking-wider">{t('trades.exchange')}</th>
                      <th className="text-left px-3 py-2.5 text-xs text-gray-400 uppercase font-semibold tracking-wider">{t('trades.symbol')}</th>
                      <th className="text-center px-3 py-2.5 text-xs text-gray-400 uppercase font-semibold tracking-wider">{t('trades.side')}</th>
                      <th className="text-right px-3 py-2.5 text-xs text-gray-400 uppercase font-semibold tracking-wider">{t('trades.entryPrice')}</th>
                      <th className="text-right px-3 py-2.5 text-xs text-gray-400 uppercase font-semibold tracking-wider">{t('trades.pnl')}</th>
                      <th className="text-center px-3 py-2.5 text-xs text-gray-400 uppercase font-semibold tracking-wider">{t('trades.trailingStop')}</th>
                      <th className="text-center px-3 py-2.5 text-xs text-gray-400 uppercase font-semibold tracking-wider">{t('trades.mode')}</th>
                      <th className="text-center px-3 py-2.5 text-xs text-gray-400 uppercase font-semibold tracking-wider">{t('trades.status')}</th>
                      <th className="text-center px-3 py-2.5 text-xs text-gray-400 uppercase font-semibold tracking-wider">{t('bots.confidence')}</th>
                      <th className="text-center px-3 py-2.5 text-xs text-gray-400 uppercase font-semibold tracking-wider">{t('bots.details')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.recent_trades.map((trade) => (
                      <tr key={trade.id} className="border-b border-white/5 hover:bg-white/[0.02] transition-colors">
                        <td className="px-3 py-2.5 text-sm text-gray-300" title={formatTime(trade.entry_time)}>
                          {formatDate(trade.entry_time)}
                        </td>
                        <td className="px-3 py-2.5 text-center">
                          <span className="inline-flex justify-center">
                            <ExchangeIcon exchange={bot.exchange_type} size={18} />
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-sm text-white font-semibold">{trade.symbol}</td>
                        <td className="px-3 py-2.5 text-center">
                          <span className={`text-sm ${trade.side === 'long' ? 'text-profit' : 'text-loss'}`}>
                            {trade.side === 'long' ? '+' : '-'} {trade.side.toUpperCase()}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-right text-sm text-gray-300">
                          ${trade.entry_price.toLocaleString()}
                        </td>
                        <td className="px-3 py-2.5 text-right">
                          <PnlCell
                            pnl={trade.pnl}
                            fees={trade.fees ?? 0}
                            fundingPaid={trade.funding_paid ?? 0}
                            status={trade.status}
                            className={`text-sm font-semibold font-mono ${
                              trade.status === 'open' ? 'text-gray-500' :
                              trade.pnl >= 0 ? 'text-profit' : 'text-loss'
                            }`}
                          />
                        </td>
                        <td className="px-3 py-2.5 text-center">
                          {trade.status === 'open' && trade.trailing_stop_active && trade.trailing_stop_price != null ? (
                            <span className="inline-flex items-center justify-center gap-1 text-emerald-400 text-sm">
                              ${trade.trailing_stop_price.toLocaleString()} ({trade.trailing_stop_distance_pct?.toFixed(2)}%)
                              {trade.can_close_at_loss === false && (
                                <span title={t('trades.trailingStopProtecting')}>
                                  <ShieldCheck size={14} className="text-emerald-400" />
                                </span>
                              )}
                            </span>
                          ) : (
                            <span className="text-gray-600">--</span>
                          )}
                        </td>
                        <td className="px-3 py-2.5 text-center">
                          <span className={trade.demo_mode ? 'badge-demo' : 'badge-live'}>
                            {trade.demo_mode ? t('common.demo') : t('common.live')}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-center">
                          <span className={
                            trade.status === 'open' ? 'badge-open' :
                            trade.status === 'closed' ? 'badge-neutral' :
                            'badge-demo'
                          }>
                            {t(`trades.${trade.status}`)}
                          </span>
                        </td>
                        <td className={`px-3 py-2.5 text-center text-sm font-medium ${confidenceColor(trade.confidence)}`}>{trade.confidence}%</td>
                        <td className="px-3 py-2.5 text-center">
                          <button
                            onClick={() => setSelectedTrade(trade)}
                            className="p-1.5 text-gray-400 hover:text-white transition-colors rounded-lg hover:bg-white/5"
                            aria-label={t('bots.details')}
                          >
                            <FileText size={16} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Trade Detail Modal (nested, higher z-index) */}
      {selectedTrade && (
        <TradeDetailModal trade={selectedTrade} onClose={() => setSelectedTrade(null)} t={t} affiliateLink={affiliateLink} />
      )}
    </div>
  )
}

export default function Bots() {
  const { t } = useTranslation()
  const { demoFilter } = useFilterStore()
  const isMobile = useIsMobile()
  const haptic = useHaptic()
  const { addToast } = useToastStore()
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin')

  const handleStartError = (err: unknown) => {
    const detail = (err as any)?.response?.data?.detail
    if (detail && typeof detail === 'object' && detail.message) {
      const msg = detail.affiliate_url
        ? `${detail.message}\n${detail.affiliate_url}`
        : detail.message
      addToast('error', msg, 10000)
    } else {
      addToast('error', getApiErrorMessage(err, t('bots.failedStart')))
    }
  }
  const [bots, setBots] = useState<BotStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [showBuilder, setShowBuilder] = useState(false)
  const [editBotId, setEditBotId] = useState<number | null>(null)
  const [expandedBotId, setExpandedBotId] = useState<number | null>(null)
  const [actionLoading, setActionLoading] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [historyBot, setHistoryBot] = useState<BotStatus | null>(null)
  const [llmConnections, setLlmConnections] = useState<LlmConnection[]>([])

  const [moreMenuOpen, setMoreMenuOpen] = useState<number | null>(null)
  const [closePositionOpen, setClosePositionOpen] = useState<number | null>(null)

  // Build lookup: model_id → display name, provider_type → family_name
  const modelNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const conn of llmConnections) {
      for (const m of conn.models || []) {
        map[m.id] = m.name
      }
    }
    return map
  }, [llmConnections])

  const providerNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const conn of llmConnections) {
      map[conn.provider_type] = conn.family_name || conn.display_name
    }
    return map
  }, [llmConnections])

  const fetchBots = useCallback(async () => {
    try {
      const demoParam = demoFilter === 'demo' ? '?demo_mode=true' : demoFilter === 'live' ? '?demo_mode=false' : ''
      const res = await api.get(`/bots${demoParam}`)
      setBots(res.data.bots)
      setError('')
    } catch {
      setError(t('common.error'))
    } finally {
      setLoading(false)
    }
  }, [demoFilter])

  useEffect(() => {
    fetchBots()
    const interval = setInterval(fetchBots, 5000)
    return () => clearInterval(interval)
  }, [fetchBots])

  useEffect(() => {
    api.get('/config/llm-connections').then(res => setLlmConnections(res.data.connections || [])).catch((err) => { console.error('Failed to load LLM connections:', err); useToastStore.getState().addToast('error', t('common.loadError', 'Failed to load data')) })
  }, [])

  const { containerRef, refreshing, pullDistance } = usePullToRefresh({
    onRefresh: fetchBots,
    disabled: !isMobile,
  })


  const handleStart = async (id: number) => {
    haptic.medium()
    // Check if HL bot needs builder fee approval or referral first (admins bypass)
    // Instead of a modal, redirect the user to Settings
    const bot = bots.find(b => b.bot_config_id === id)
    if (!isAdmin && bot?.exchange_type === 'hyperliquid' && (bot?.builder_fee_approved === false || bot?.referral_verified === false)) {
      addToast('warning', t('hlSetup.setupRequired'), 6000)
      return
    }

    setActionLoading(id)
    try {
      await api.post(`/bots/${id}/start`)
      await fetchBots()
      addToast('success', t('bots.start'))
    } catch (err) {
      handleStartError(err)
    }
    setActionLoading(null)
  }

  const handleStop = async (id: number) => {
    haptic.heavy()
    setActionLoading(id)
    try {
      await api.post(`/bots/${id}/stop`)
      await fetchBots()
      addToast('info', t('bots.stop'))
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('bots.failedStop')))
    }
    setActionLoading(null)
  }

  const handleDelete = async (id: number, name: string) => {
    haptic.error()
    if (!confirm(`${t('bots.confirmDelete')} (${name})`)) return
    try {
      await api.delete(`/bots/${id}`)
      await fetchBots()
      addToast('success', t('bots.deleted', { name }))
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('bots.failedDelete')))
    }
  }

  const handleDuplicate = async (id: number) => {
    haptic.light()
    try {
      await api.post(`/bots/${id}/duplicate`)
      await fetchBots()
      addToast('success', t('bots.duplicated'))
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('bots.failedDuplicate')))
    }
  }

  const handleClosePosition = async (botId: number, symbol: string) => {
    haptic.heavy()
    if (!confirm(t('bots.closePositionConfirm', { symbol }))) return
    setActionLoading(botId)
    try {
      await api.post(`/bots/${botId}/close-position/${symbol}`)
      await fetchBots()
      addToast('success', t('bots.positionClosed', { symbol }))
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('bots.failedClosePosition')))
    }
    setActionLoading(null)
  }

  const handleStopAll = async () => {
    try {
      await api.post('/bots/stop-all')
      await fetchBots()
      addToast('info', t('bots.stopAll'))
    } catch {
      addToast('error', t('common.error'))
    }
  }

  const handleBuilderDone = () => {
    setShowBuilder(false)
    setEditBotId(null)
    fetchBots()
  }

  const runningCount = bots.filter(b => b.status === 'running').length

  if (showBuilder || editBotId !== null) {
    return (
      <BotBuilder
        botId={editBotId}
        onDone={handleBuilderDone}
        onCancel={() => { setShowBuilder(false); setEditBotId(null) }}
      />
    )
  }

  const getStatusStyle = (status: string) => STATUS_STYLES[status] || STATUS_STYLES.idle

  return (
    <div ref={containerRef} style={{ overscrollBehavior: 'contain' }} className="animate-in">
      <PullToRefreshIndicator pullDistance={pullDistance} refreshing={refreshing} />
      {/* Header */}
      <div className="flex items-center justify-between gap-3 mb-6">
        <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">{t('bots.title')}</h1>
        <div className="flex items-center gap-1.5 sm:gap-2">
          <TourHelpButton tourId="bots-page" />
          <button
            onClick={() => setShowBuilder(true)}
            aria-label={t('bots.newBot')}
            className="px-3 py-2 text-xs sm:text-sm btn-gradient flex items-center gap-1.5 rounded-xl font-medium"
            data-tour="new-bot"
          >
            <Plus size={15} />
            {t('bots.newBot')}
          </button>
          {runningCount > 1 && (
            <button
              onClick={handleStopAll}
              aria-label={t('bots.stopAll')}
              className="px-3 py-2 text-xs sm:text-sm bg-red-500/10 text-red-400 rounded-xl border border-red-500/10 hover:bg-red-500/20 transition-all duration-200 font-medium"
            >
              {t('bots.stopAll')} ({runningCount})
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div role="alert" className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <SkeletonBotCard key={i} />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && bots.length === 0 && (
        <div className="glass-card rounded-xl text-center py-16">
          <Activity className="mx-auto mb-4 text-gray-600" size={48} />
          <p className="text-gray-400">{t('bots.noBots')}</p>
        </div>
      )}

      {/* Bot Grid */}
      {!loading && bots.length > 0 && (
        <div className={isMobile ? 'space-y-2' : 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4'}>
          {bots.map((bot) => {
            const style = getStatusStyle(bot.status)
            const isBotExpanded = !isMobile || expandedBotId === bot.bot_config_id
            return (
              <div
                key={bot.bot_config_id}
                className={`glass-card rounded-xl ${isMobile ? 'p-3' : 'p-5'} border transition-all duration-300 ${style.card} ${moreMenuOpen === bot.bot_config_id ? 'relative z-30' : ''}`}
                {...(bot === bots[0] ? { 'data-tour': 'bot-card' } : {})}
              >
                {/* Header row */}
                <div
                  className={`flex items-start justify-between gap-2 ${isBotExpanded ? 'mb-3' : ''} ${isMobile ? 'cursor-pointer' : ''}`}
                  onClick={isMobile ? () => setExpandedBotId(expandedBotId === bot.bot_config_id ? null : bot.bot_config_id) : undefined}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Link to={`/bots/${bot.bot_config_id}`} onClick={(e) => isMobile && e.stopPropagation()} className={`text-white font-semibold ${isMobile ? 'text-[13px]' : 'text-lg'} hover:text-primary-400 transition-colors truncate block`}>{bot.name}</Link>
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
                        {bot.risk_profile && (
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
                      {AI_STRATEGIES.has(bot.strategy_type) && (
                        <Bot size={15} className="text-emerald-400" />
                      )}
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
                    {bot.llm_provider && (
                      <div className="mt-1 text-xs text-gray-500 leading-tight">
                        <span>{providerNameMap[bot.llm_provider] || bot.llm_provider}</span>
                        {bot.llm_model && (
                          <div className="text-gray-400 font-medium">{modelNameMap[bot.llm_model] || bot.llm_model}</div>
                        )}
                      </div>
                    )}
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
                <div className="grid grid-cols-3 gap-1 sm:gap-2 mb-3 text-center" {...(bot === bots[0] ? { 'data-tour': 'bot-stats' } : {})}>
                  <div>
                    <div className="text-xs text-gray-400 uppercase tracking-wider">{t('bots.totalPnl')}</div>
                    <div className={`text-base font-mono font-semibold ${bot.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                      <PnlCell
                        pnl={bot.total_pnl}
                        fees={bot.total_fees ?? 0}
                        fundingPaid={bot.total_funding ?? 0}
                        className={`text-base font-mono font-semibold ${bot.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}
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


                {/* LLM Metrics */}
                {AI_STRATEGIES.has(bot.strategy_type) && (
                  <div className="mb-3 pt-3 border-t border-white/5 space-y-2.5">
                    <div className="flex items-center gap-2 text-sm">
                      <span className="text-gray-500">{t('bots.llmLastSignal')}</span>
                      {bot.llm_last_direction && (
                        <span className={`font-semibold ${bot.llm_last_direction === 'LONG' ? 'text-profit' : 'text-loss'}`}>
                          {bot.llm_last_direction === 'LONG' ? '+' : '-'} {bot.llm_last_direction}
                        </span>
                      )}
                    </div>

                    {bot.llm_last_confidence != null && (
                      <div>
                        <div className="flex items-center justify-between text-sm mb-1">
                          <span className="text-gray-500">{t('bots.confidence')}</span>
                          <span className={`font-medium ${confidenceColor(bot.llm_last_confidence)}`}>{bot.llm_last_confidence}%</span>
                        </div>
                        <div className="w-full bg-white/5 rounded-full h-2">
                          <div
                            className={`h-2 rounded-full transition-all ${
                              bot.llm_last_confidence >= 75 ? 'bg-emerald-500' :
                              bot.llm_last_confidence >= 50 ? 'bg-amber-500' : 'bg-red-500'
                            }`}
                            style={{ width: `${bot.llm_last_confidence}%` }}
                          />
                        </div>
                      </div>
                    )}

                    <div className="text-sm">
                      <span className="text-gray-500">{t('bots.accuracy')}: </span>
                      <span className="text-white font-medium">
                        {bot.llm_accuracy != null ? `${bot.llm_accuracy.toFixed(1)}%` : 'N/A'}
                      </span>
                    </div>

                    {(bot.llm_total_tokens_used != null || bot.llm_avg_tokens_per_call != null) && (
                      <div className="flex gap-4 text-xs">
                        <div>
                          <span className="text-gray-500">{t('bots.totalTokens')}: </span>
                          <span className="text-white font-medium">
                            {bot.llm_total_tokens_used != null ? bot.llm_total_tokens_used.toLocaleString() : 'N/A'}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-500">{t('bots.avgTokensPerCall')}: </span>
                          <span className="text-white font-medium">
                            {bot.llm_avg_tokens_per_call != null ? bot.llm_avg_tokens_per_call.toLocaleString() : 'N/A'}
                          </span>
                        </div>
                      </div>
                    )}

                    {bot.llm_last_reasoning && (
                      <details className="text-xs">
                        <summary className="text-gray-400 cursor-pointer hover:text-gray-300 transition-colors">
                          {t('bots.viewReasoning')}
                        </summary>
                        <p className="text-gray-500 mt-1 italic leading-relaxed p-2 bg-white/5 rounded-lg mt-1.5">
                          &ldquo;{bot.llm_last_reasoning}&rdquo;
                        </p>
                      </details>
                    )}
                  </div>
                )}

                {/* Error message */}
                {bot.error_message && (
                  <div className="flex items-center gap-1.5 mb-3 text-sm text-red-400 bg-red-500/5 rounded-lg px-2.5 py-2">
                    <AlertCircle size={14} />
                    <span className="truncate">{bot.error_message}</span>
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

                {/* Close Position — prominent when trades are open */}
                {bot.open_trades > 0 && bot.status === 'running' && (
                  <div className="mb-3">
                    {bot.trading_pairs.length === 1 ? (
                      <button
                        onClick={() => handleClosePosition(bot.bot_config_id, bot.trading_pairs[0])}
                        disabled={actionLoading === bot.bot_config_id}
                        className="w-full flex items-center justify-center gap-2 px-3 py-2.5 text-sm font-medium bg-amber-500/10 text-amber-400 rounded-xl border border-amber-500/25 hover:bg-amber-500/20 hover:border-amber-500/40 disabled:opacity-50 transition-all duration-200"
                      >
                        <XCircle size={15} />
                        {t('bots.closePosition')} {bot.trading_pairs[0]}
                      </button>
                    ) : (
                      <div className="relative">
                        <button
                          onClick={() => setClosePositionOpen(closePositionOpen === bot.bot_config_id ? null : bot.bot_config_id)}
                          disabled={actionLoading === bot.bot_config_id}
                          className="w-full flex items-center justify-center gap-2 px-3 py-2.5 text-sm font-medium bg-amber-500/10 text-amber-400 rounded-xl border border-amber-500/25 hover:bg-amber-500/20 hover:border-amber-500/40 disabled:opacity-50 transition-all duration-200"
                        >
                          <XCircle size={15} />
                          {t('bots.closePosition')} ({bot.open_trades})
                          <ChevronDown size={14} className={`transition-transform ${closePositionOpen === bot.bot_config_id ? 'rotate-180' : ''}`} />
                        </button>
                        {closePositionOpen === bot.bot_config_id && (
                          <>
                            <div className="fixed inset-0 z-10" onClick={() => setClosePositionOpen(null)} />
                            <div className="absolute left-0 right-0 top-full mt-1 z-20 bg-[#1a1f2e] border border-amber-500/20 rounded-xl shadow-xl overflow-hidden">
                              {bot.trading_pairs.map(symbol => (
                                <button
                                  key={symbol}
                                  onClick={() => { setClosePositionOpen(null); handleClosePosition(bot.bot_config_id, symbol) }}
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
                <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-white/5" {...(bot === bots[0] ? { 'data-tour': 'bot-actions' } : {})}>
                  {bot.status === 'running' ? (
                    <button
                      onClick={() => handleStop(bot.bot_config_id)}
                      disabled={actionLoading === bot.bot_config_id}
                      aria-label={`${t('bots.stop')} ${bot.name}`}
                      className="w-full sm:w-auto sm:flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 text-sm bg-red-500/10 text-red-400 rounded-xl border border-red-500/10 hover:bg-red-500/20 disabled:opacity-50 transition-all duration-200"
                    >
                      <Square size={16} />
                      {t('bots.stop')}
                    </button>
                  ) : (
                    <button
                      onClick={() => handleStart(bot.bot_config_id)}
                      disabled={actionLoading === bot.bot_config_id}
                      aria-label={`${t('bots.start')} ${bot.name}`}
                      className="w-full sm:w-auto sm:flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 text-sm bg-emerald-500/10 text-emerald-400 rounded-xl border border-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-50 transition-all duration-200"
                    >
                      {actionLoading === bot.bot_config_id ? (
                        <RefreshCw size={16} className="animate-spin" />
                      ) : (
                        <Play size={16} />
                      )}
                      {t('bots.start')}
                    </button>
                  )}
                  <button
                    onClick={() => setHistoryBot(bot)}
                    aria-label={t('bots.showTrades')}
                    className="p-2 text-gray-400 hover:text-primary-400 hover:bg-primary-500/10 transition-all duration-200 rounded-lg"
                    title={t('bots.tradeHistory')}
                  >
                    <TrendingUp size={16} />
                  </button>
                  {/* 3-dot menu for Edit, Duplicate, Delete */}
                  <div className="relative">
                    <button
                      onClick={(e) => { e.stopPropagation(); setMoreMenuOpen(moreMenuOpen === bot.bot_config_id ? null : bot.bot_config_id) }}
                      aria-label={t('bots.moreActions')}
                      className="p-3 -m-1 text-gray-400 hover:text-white transition-all duration-200 rounded-lg hover:bg-white/5"
                      title={t('bots.moreActions')}
                    >
                      <MoreVertical size={18} />
                    </button>
                  </div>
                </div>
                </>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Trade History Modal */}
      {historyBot && (
        <BotTradeHistoryModal bot={historyBot} onClose={() => setHistoryBot(null)} t={t} />
      )}

      {/* Mobile bottom sheet for 3-dot menu actions */}
      {moreMenuOpen !== null && (() => {
        const menuBot = bots.find(b => b.bot_config_id === moreMenuOpen);
        if (!menuBot) return null;
        return (
          <>
            <div className="fixed inset-0 bg-black/60 z-[9998] animate-in fade-in" onClick={() => setMoreMenuOpen(null)} />
            <div className="fixed bottom-0 left-0 right-0 z-[9999] bg-[#1a1f2e] border-t border-white/10 rounded-t-2xl p-4 pb-8 animate-in slide-in-from-bottom">
              <div className="w-10 h-1 bg-white/20 rounded-full mx-auto mb-4" />
              <p className="text-white/50 text-xs mb-3 px-1">{menuBot.name}</p>
              <button
                onClick={() => { setMoreMenuOpen(null); setEditBotId(menuBot.bot_config_id) }}
                disabled={menuBot.status === 'running'}
                className="w-full flex items-center gap-3 px-4 py-3.5 text-base text-gray-200 hover:bg-white/5 active:bg-white/10 disabled:opacity-30 transition-colors rounded-xl"
              >
                <Pencil size={18} />
                {t('bots.edit')}
              </button>
              <button
                onClick={() => { setMoreMenuOpen(null); handleDuplicate(menuBot.bot_config_id) }}
                className="w-full flex items-center gap-3 px-4 py-3.5 text-base text-gray-200 hover:bg-white/5 active:bg-white/10 transition-colors rounded-xl"
              >
                <Copy size={18} />
                {t('bots.duplicate')}
              </button>
              <div className="border-t border-white/5 my-1" />
              <button
                onClick={() => { setMoreMenuOpen(null); handleDelete(menuBot.bot_config_id, menuBot.name) }}
                disabled={menuBot.status === 'running'}
                className="w-full flex items-center gap-3 px-4 py-3.5 text-base text-red-400 hover:bg-red-500/5 active:bg-red-500/10 disabled:opacity-30 transition-colors rounded-xl"
              >
                <Trash2 size={18} />
                {t('bots.delete')}
              </button>
            </div>
          </>
        );
      })()}

      {/* Guided Tour */}
      <GuidedTour
        tourId="bots-page"
        steps={botsTourSteps}
        autoStart={!loading && !showBuilder && !editBotId}
      />
    </div>
  )
}

const botsTourSteps: TourStep[] = [
  {
    target: '[data-tour="new-bot"]',
    titleKey: 'tour.botsNewBotTitle',
    descriptionKey: 'tour.botsNewBotDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="bot-card"]',
    titleKey: 'tour.botsBotCardTitle',
    descriptionKey: 'tour.botsBotCardDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="bot-stats"]',
    titleKey: 'tour.botsStatsTitle',
    descriptionKey: 'tour.botsStatsDesc',
    position: 'top',
  },
  {
    target: '[data-tour="bot-actions"]',
    titleKey: 'tour.botsActionsTitle',
    descriptionKey: 'tour.botsActionsDesc',
    position: 'top',
  },
]
