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
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import BotBuilder from '../components/bots/BotBuilder'
import BuilderFeeApproval from '../components/hyperliquid/BuilderFeeApproval'
import { SkeletonBotCard } from '../components/ui/Skeleton'
import PnlCell from '../components/ui/PnlCell'
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
  Layers,
  Bot,
} from 'lucide-react'
import GuidedTour, { TourHelpButton, type TourStep } from '../components/ui/GuidedTour'

const STRATEGY_DISPLAY: Record<string, string> = { llm_signal: 'KI-Companion', sentiment_surfer: 'Sentiment Surfer', liquidation_hunter: 'Liquidation Hunter', degen: 'Degen', edge_indicator: 'Edge Indicator', claude_edge_indicator: 'Claude-Edge' }
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
  active_preset_id?: number | null
  active_preset_name?: string | null
  builder_fee_approved?: boolean | null
  referral_verified?: boolean | null
}

interface Preset {
  id: number
  name: string
  exchange_type: string
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

/* ── Trade Detail Modal ──────────────────────────────────── */

function TradeDetailModal({ trade, onClose, t }: { trade: BotTrade; onClose: () => void; t: (key: string) => string }) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-md" onClick={onClose}>
      <div
        className="bg-[#0f1420] rounded-2xl p-7 max-w-lg w-full mx-4 border border-white/10 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
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
          <button onClick={onClose} className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-all" aria-label="Close">
            <X size={20} />
          </button>
        </div>

        {/* Result - Hero */}
        <div className="text-center py-6 mb-5 bg-white/[0.02] rounded-xl border border-white/5">
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-2">{t('bots.result')}</div>
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
            <div className="text-xs text-gray-500 mb-1.5">{t('bots.entryPrice')}</div>
            <div className="text-white font-semibold text-lg">${trade.entry_price.toLocaleString()}</div>
          </div>
          <div className="bg-white/[0.03] rounded-xl p-4 border border-white/5">
            <div className="text-xs text-gray-500 mb-1.5">{t('bots.exitPrice')}</div>
            <div className="text-white font-semibold text-lg">
              {trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}
            </div>
          </div>
        </div>

        {/* Confidence */}
        <div className="flex items-center justify-between mb-5 bg-white/[0.03] rounded-xl p-4 border border-white/5">
          <span className="text-sm text-gray-400">{t('bots.confidence')}</span>
          <span className={`font-bold text-lg ${confidenceColor(trade.confidence)}`}>{trade.confidence}%</span>
        </div>

        {/* Reasoning */}
        {trade.reason && (
          <div className="mb-5">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-2">{t('bots.reasoning')}</div>
            <p className="text-sm text-gray-300 leading-relaxed bg-white/[0.03] rounded-xl p-4 border border-white/5">
              {trade.reason}
            </p>
          </div>
        )}

        {/* Footer info */}
        <div className="flex items-center justify-between text-sm text-gray-500 pt-4 border-t border-white/5">
          <span>{new Date(trade.entry_time).toLocaleString()}</span>
          <span className={trade.status === 'open' ? 'text-amber-400 font-medium' : 'text-gray-500'}>
            {trade.status === 'open' ? t('bots.pending') : trade.exit_reason || trade.status}
          </span>
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
  const theme = useThemeStore((s) => s.theme)

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
      } catch { /* ignore */ }
      setLoading(false)
    }
    load()
  }, [bot.bot_config_id, bot.exchange_type])

  const [copied, setCopied] = useState(false)

  const handleCopyImage = async () => {
    if (!latestCardRef.current) return
    try {
      const blob = await toBlob(latestCardRef.current, {
        pixelRatio: 2,
        backgroundColor: theme === 'light' ? '#f8fafc' : '#0b0f19',
      })
      if (!blob) return
      await navigator.clipboard.write([
        new ClipboardItem({ 'image/png': blob }),
      ])
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* ignore */ }
  }

  const latestClosed = stats?.recent_trades.find(tr => tr.status === 'closed')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md" onClick={onClose}>
      <div
        className="bg-[#0b0f19] rounded-2xl max-w-5xl w-full mx-4 my-3 max-h-[96vh] flex flex-col border border-white/10 shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
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
              {/* Summary Stats Bar */}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-px bg-white/5">
                <div className="bg-[#0b0f19] px-5 py-3 text-center">
                  <div className="text-xs text-gray-500 uppercase tracking-wider mb-0.5">{t('bots.totalPnl')}</div>
                  <div className={`text-lg font-bold font-mono ${stats.summary.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                    <PnlCell
                      pnl={stats.summary.total_pnl}
                      fees={stats.summary.total_fees}
                      fundingPaid={stats.summary.total_funding ?? 0}
                      className={`text-lg font-bold font-mono ${stats.summary.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}
                    />
                  </div>
                </div>
                <div className="bg-[#0b0f19] px-5 py-3 text-center">
                  <div className="text-xs text-gray-500 uppercase tracking-wider mb-0.5">{t('bots.winRate')}</div>
                  <div className={`text-lg font-bold ${stats.summary.win_rate >= 60 ? 'text-profit' : stats.summary.win_rate >= 40 ? 'text-yellow-400' : 'text-loss'}`}>{stats.summary.win_rate}%</div>
                </div>
                <div className="bg-[#0b0f19] px-5 py-3 text-center">
                  <div className="text-xs text-gray-500 uppercase tracking-wider mb-0.5">{t('bots.trades')}</div>
                  <div className="text-lg font-bold text-white">
                    {stats.summary.total_trades}
                    <span className="text-xs font-normal text-gray-500 ml-1">
                      ({stats.summary.wins}W / {stats.summary.losses}L)
                    </span>
                  </div>
                </div>
                <div className="bg-[#0b0f19] px-5 py-3 text-center">
                  <div className="text-xs text-gray-500 uppercase tracking-wider mb-0.5 flex items-center justify-center gap-1">
                    <ArrowUpRight size={12} className="text-profit" /> {t('bots.bestTrade')}
                  </div>
                  <div className="text-lg font-bold text-profit font-mono">{formatPnl(stats.summary.best_trade)}</div>
                </div>
                <div className="bg-[#0b0f19] px-5 py-3 text-center">
                  <div className="text-xs text-gray-500 uppercase tracking-wider mb-0.5 flex items-center justify-center gap-1">
                    <ArrowDownRight size={12} className="text-loss" /> {t('bots.worstTrade')}
                  </div>
                  <div className="text-lg font-bold text-loss font-mono">{formatPnl(stats.summary.worst_trade)}</div>
                </div>
              </div>

              {/* Latest Trade Hero Card */}
              {latestClosed && (
                <div className="mx-6 mt-4 mb-2">
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-xs text-gray-500 uppercase tracking-wider font-semibold">{t('bots.latestTrade')}</div>
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
                  <div
                    ref={latestCardRef}
                    className="bg-white/[0.02] rounded-xl p-4 border border-white/5 cursor-pointer hover:border-white/10 transition-all"
                    onClick={() => setSelectedTrade(latestClosed)}
                  >
                    {/* Header: Symbol + Side + Date */}
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-3">
                        <span className="text-white font-bold text-lg">{latestClosed.symbol}</span>
                        <span className={`px-2.5 py-0.5 rounded-lg text-xs font-bold ${
                          latestClosed.side === 'long' ? 'bg-emerald-500/15 text-profit border border-emerald-500/20' : 'bg-red-500/15 text-loss border border-red-500/20'
                        }`}>
                          {latestClosed.side === 'long' ? '+ LONG' : '- SHORT'}
                        </span>
                      </div>
                      <span className="text-xs text-gray-500 cursor-default" title={new Date(latestClosed.entry_time).toLocaleTimeString('de-DE', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit' }) + ' UTC'}>{new Date(latestClosed.entry_time).toLocaleDateString()}</span>
                    </div>

                    {/* 4-column grid: PnL | Einstieg | Ausstieg | Konfidenz */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                      <div>
                        <div className="text-xs text-gray-500 uppercase tracking-wider mb-0.5">{t('bots.result')}</div>
                        <div className={`text-2xl font-bold tracking-tight ${latestClosed.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}`}>
                          {formatPnlPercent(latestClosed.pnl_percent)}
                        </div>
                        <div className={`text-sm font-medium ${latestClosed.pnl >= 0 ? 'text-profit/60' : 'text-loss/60'}`}>
                          <PnlCell
                            pnl={latestClosed.pnl}
                            fees={latestClosed.fees ?? 0}
                            fundingPaid={latestClosed.funding_paid ?? 0}
                            status={latestClosed.status}
                            className={`text-sm font-medium ${latestClosed.pnl >= 0 ? 'text-profit/60' : 'text-loss/60'}`}
                          />
                        </div>
                      </div>
                      <div>
                        <div className="text-xs text-gray-500 uppercase tracking-wider mb-0.5">{t('bots.entryPrice')}</div>
                        <div className="text-lg font-bold text-white">${latestClosed.entry_price.toLocaleString()}</div>
                      </div>
                      <div>
                        <div className="text-xs text-gray-500 uppercase tracking-wider mb-0.5">{t('bots.exitPrice')}</div>
                        <div className="text-lg font-bold text-white">
                          {latestClosed.exit_price ? `$${latestClosed.exit_price.toLocaleString()}` : '--'}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs text-gray-500 uppercase tracking-wider mb-0.5">{t('bots.confidence')}</div>
                        <div className={`text-lg font-bold ${confidenceColor(latestClosed.confidence)}`}>{latestClosed.confidence}%</div>
                      </div>
                    </div>

                    {/* Affiliate Link (inside card for screenshot capture) */}
                    {affiliateLink && (
                      <div className="mt-3 pt-2 border-t border-white/5 flex items-center justify-between">
                        <span className="text-xs text-gray-500">{affiliateLink.label || t('bots.affiliateLink')}</span>
                        <span className="text-xs text-primary-400 font-medium">{affiliateLink.affiliate_url}</span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Trade History Table */}
              <div className="px-6 pt-3 pb-2">
                <div className="text-xs text-gray-500 uppercase tracking-wider font-semibold">{t('bots.tradeHistory')}</div>
              </div>
              <div className="overflow-x-auto">
              <table className="w-full min-w-[640px]">
                <thead>
                  <tr className="border-t border-b border-white/5 bg-white/[0.02]">
                    <th className="text-left px-5 py-2.5 text-xs text-gray-500 uppercase font-semibold tracking-wider">{t('trades.date')}</th>
                    <th className="text-center px-3 py-2.5 text-xs text-gray-500 uppercase font-semibold tracking-wider">{t('trades.exchange')}</th>
                    <th className="text-left px-3 py-2.5 text-xs text-gray-500 uppercase font-semibold tracking-wider">{t('trades.symbol')}</th>
                    <th className="text-center px-3 py-2.5 text-xs text-gray-500 uppercase font-semibold tracking-wider">{t('trades.side')}</th>
                    <th className="text-right px-3 py-2.5 text-xs text-gray-500 uppercase font-semibold tracking-wider">{t('trades.entryPrice')}</th>
                    <th className="text-right px-3 py-2.5 text-xs text-gray-500 uppercase font-semibold tracking-wider">{t('trades.pnl')}</th>
                    <th className="text-center px-3 py-2.5 text-xs text-gray-500 uppercase font-semibold tracking-wider">{t('trades.mode')}</th>
                    <th className="text-center px-3 py-2.5 text-xs text-gray-500 uppercase font-semibold tracking-wider">{t('trades.status')}</th>
                    <th className="text-center px-3 py-2.5 text-xs text-gray-500 uppercase font-semibold tracking-wider">{t('bots.confidence')}</th>
                    <th className="text-center px-3 py-2.5 text-xs text-gray-500 uppercase font-semibold tracking-wider">{t('bots.details')}</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.recent_trades.map((trade) => (
                    <tr key={trade.id} className="border-b border-white/5 hover:bg-white/[0.02] transition-colors">
                      <td className="px-5 py-2.5 text-sm text-gray-300" title={new Date(trade.entry_time).toLocaleTimeString('de-DE', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit' }) + ' UTC'}>
                        {new Date(trade.entry_time).toLocaleDateString()}
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
            </>
          )}
        </div>
      </div>

      {/* Trade Detail Modal (nested, higher z-index) */}
      {selectedTrade && (
        <TradeDetailModal trade={selectedTrade} onClose={() => setSelectedTrade(null)} t={t} />
      )}
    </div>
  )
}

export default function Bots() {
  const { t } = useTranslation()
  const { demoFilter } = useFilterStore()
  const { addToast } = useToastStore()

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
  const [actionLoading, setActionLoading] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [historyBot, setHistoryBot] = useState<BotStatus | null>(null)
  const [presets, setPresets] = useState<Preset[]>([])
  const [presetDropdownOpen, setPresetDropdownOpen] = useState<number | null>(null)
  const [builderFeeModalBotId, setBuilderFeeModalBotId] = useState<number | null>(null)
  const [llmConnections, setLlmConnections] = useState<LlmConnection[]>([])

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
    api.get('/presets').then(res => setPresets(res.data)).catch(() => {})
    api.get('/config/llm-connections').then(res => setLlmConnections(res.data.connections || [])).catch(() => {})
  }, [])

  const handleStart = async (id: number) => {
    // Check if HL bot needs builder fee approval or referral first
    const bot = bots.find(b => b.bot_config_id === id)
    if (bot?.exchange_type === 'hyperliquid' && (bot?.builder_fee_approved === false || bot?.referral_verified === false)) {
      setBuilderFeeModalBotId(id)
      return
    }

    setActionLoading(id)
    try {
      await api.post(`/bots/${id}/start`)
      await fetchBots()
      addToast('success', t('bots.start') + ' - OK')
    } catch (err) {
      handleStartError(err)
    }
    setActionLoading(null)
  }

  const handleBuilderFeeApproved = async () => {
    const botId = builderFeeModalBotId
    setBuilderFeeModalBotId(null)
    if (botId) {
      await fetchBots()
      // Auto-start bot after approval
      setActionLoading(botId)
      try {
        await api.post(`/bots/${botId}/start`)
        await fetchBots()
        addToast('success', t('bots.start') + ' - OK')
      } catch (err) {
        handleStartError(err)
      }
      setActionLoading(null)
    }
  }

  const handleStop = async (id: number) => {
    setActionLoading(id)
    try {
      await api.post(`/bots/${id}/stop`)
      await fetchBots()
      addToast('info', t('bots.stop') + ' - OK')
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('bots.failedStop')))
    }
    setActionLoading(null)
  }

  const handleDelete = async (id: number, name: string) => {
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
    try {
      await api.post(`/bots/${id}/duplicate`)
      await fetchBots()
      addToast('success', t('bots.duplicated'))
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('bots.failedDuplicate')))
    }
  }

  const handleApplyPreset = async (botId: number, presetId: number) => {
    setPresetDropdownOpen(null)
    setActionLoading(botId)
    try {
      await api.post(`/bots/${botId}/apply-preset/${presetId}`)
      await fetchBots()
      addToast('success', t('bots.presetApplied'))
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('bots.presetSwitchFailed')))
    }
    setActionLoading(null)
  }

  const handleStopAll = async () => {
    try {
      await api.post('/bots/stop-all')
      await fetchBots()
      addToast('info', t('bots.stopAll') + ' - OK')
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
    <div className="animate-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white tracking-tight">{t('bots.title')}</h1>
        <div className="flex gap-2">
          {runningCount > 1 && (
            <button
              onClick={handleStopAll}
              aria-label={t('bots.stopAll')}
              className="px-4 py-2 text-sm bg-red-500/10 text-red-400 rounded-xl border border-red-500/10 hover:bg-red-500/20 transition-all duration-200 font-medium"
            >
              {t('bots.stopAll')} ({runningCount})
            </button>
          )}
          <button
            onClick={() => setShowBuilder(true)}
            aria-label={t('bots.newBot')}
            className="btn-gradient flex items-center gap-2"
            data-tour="new-bot"
          >
            <Plus size={18} />
            {t('bots.newBot')}
          </button>
          <TourHelpButton tourId="bots-page" />
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
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
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {bots.map((bot) => {
            const style = getStatusStyle(bot.status)
            return (
              <div
                key={bot.bot_config_id}
                className={`glass-card rounded-xl p-5 border transition-all duration-300 ${style.card}`}
                {...(bot === bots[0] ? { 'data-tour': 'bot-card' } : {})}
              >
                {/* Header row */}
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <Link to={`/bots/${bot.bot_config_id}`} className="text-white font-semibold text-lg hover:text-primary-400 transition-colors">{bot.name}</Link>
                    <div className="flex items-center gap-2 mt-1.5">
                      <span className="badge-neutral text-xs inline-flex items-center gap-1">
                        <ExchangeIcon exchange={bot.exchange_type} size={16} />
                      </span>
                      <span className={bot.mode === 'demo' ? 'badge-demo text-xs' : bot.mode === 'live' ? 'badge-live text-xs' : 'badge-open text-xs'}>
                        {bot.mode.toUpperCase()}
                      </span>
                      <span className="text-xs text-gray-500">{strategyLabel(bot.strategy_type)}</span>
                      {AI_STRATEGIES.has(bot.strategy_type) && (
                        <Bot size={15} className="text-emerald-400" />
                      )}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      {bot.status === 'running' && (
                        <span className="relative flex h-2.5 w-2.5">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
                        </span>
                      )}
                      <span className={`text-sm font-medium ${style.text}`}>
                        {t(`bots.${bot.status}`)}
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
                </div>

                {/* Pairs */}
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {bot.trading_pairs.map(pair => (
                    <span key={pair} className="text-xs px-2 py-0.5 bg-white/5 text-gray-300 rounded-md border border-white/5">
                      {pair}
                    </span>
                  ))}
                </div>

                {/* Preset Selector */}
                {presets.length > 0 && (
                  <div className="relative mb-3">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        if (bot.status === 'running') {
                          addToast('info', t('bots.stopBotFirst'))
                          return
                        }
                        setPresetDropdownOpen(presetDropdownOpen === bot.bot_config_id ? null : bot.bot_config_id)
                      }}
                      className={`w-full flex items-center justify-between gap-2 px-3 py-2 text-sm rounded-lg border transition-all ${
                        bot.active_preset_name
                          ? 'bg-primary-500/10 border-primary-500/20 text-primary-400'
                          : 'bg-white/[0.03] border-white/5 text-gray-400'
                      } ${bot.status === 'running' ? 'opacity-50 cursor-not-allowed' : 'hover:bg-white/[0.06] hover:border-white/10'}`}
                    >
                      <span className="flex items-center gap-1.5 truncate">
                        <Layers size={14} />
                        {bot.active_preset_name || t('bots.noPreset')}
                      </span>
                      <ChevronDown size={14} className={`transition-transform ${presetDropdownOpen === bot.bot_config_id ? 'rotate-180' : ''}`} />
                    </button>
                    {presetDropdownOpen === bot.bot_config_id && (
                      <>
                        <div className="fixed inset-0 z-10" onClick={() => setPresetDropdownOpen(null)} />
                        <div className="absolute z-20 mt-1 w-full bg-[#1a1f2e] border border-white/10 rounded-lg shadow-xl overflow-hidden">
                          {presets.map(preset => (
                            <button
                              key={preset.id}
                              onClick={() => handleApplyPreset(bot.bot_config_id, preset.id)}
                              className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                                preset.id === bot.active_preset_id
                                  ? 'bg-primary-500/15 text-primary-400'
                                  : 'text-gray-300 hover:bg-white/5'
                              }`}
                            >
                              <span className="font-medium">{preset.name}</span>
                              {preset.exchange_type !== 'any' && (
                                <span className="ml-1.5 text-gray-500">({preset.exchange_type})</span>
                              )}
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                )}

                {/* Stats row */}
                <div className="grid grid-cols-3 gap-1 sm:gap-2 mb-3 text-center" {...(bot === bots[0] ? { 'data-tour': 'bot-stats' } : {})}>
                  <div>
                    <div className="text-xs text-gray-500 uppercase tracking-wider">{t('bots.totalPnl')}</div>
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
                    <div className="text-xs text-gray-500 uppercase tracking-wider">{t('bots.trades')}</div>
                    <div className="text-base text-white font-semibold">{bot.total_trades}</div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 uppercase tracking-wider">{t('bots.openTrades')}</div>
                    <div className="text-base text-white font-semibold">{bot.open_trades}</div>
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

                {/* Last analysis */}
                {bot.last_analysis && (
                  <div className="flex items-center gap-1.5 mb-3 text-sm text-gray-500">
                    <Clock size={14} />
                    {t('bots.lastAnalysis')}: {new Date(bot.last_analysis).toLocaleTimeString()}
                  </div>
                )}

                {/* Actions */}
                <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-white/5" {...(bot === bots[0] ? { 'data-tour': 'bot-actions' } : {})}>
                  {bot.status === 'running' ? (
                    <button
                      onClick={() => handleStop(bot.bot_config_id)}
                      disabled={actionLoading === bot.bot_config_id}
                      aria-label={`${t('bots.stop')} ${bot.name}`}
                      className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 text-sm bg-red-500/10 text-red-400 rounded-xl border border-red-500/10 hover:bg-red-500/20 disabled:opacity-50 transition-all duration-200"
                    >
                      <Square size={16} />
                      {t('bots.stop')}
                    </button>
                  ) : (
                    <button
                      onClick={() => handleStart(bot.bot_config_id)}
                      disabled={actionLoading === bot.bot_config_id}
                      aria-label={`${t('bots.start')} ${bot.name}`}
                      className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 text-sm bg-emerald-500/10 text-emerald-400 rounded-xl border border-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-50 transition-all duration-200"
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
                  <button
                    onClick={() => setEditBotId(bot.bot_config_id)}
                    disabled={bot.status === 'running'}
                    aria-label={`${t('bots.edit')} ${bot.name}`}
                    className="p-2 text-gray-400 hover:text-white disabled:opacity-30 transition-all duration-200 rounded-lg hover:bg-white/5"
                    title={t('bots.edit')}
                  >
                    <Pencil size={16} />
                  </button>
                  <button
                    onClick={() => handleDuplicate(bot.bot_config_id)}
                    aria-label={`${t('bots.duplicate')} ${bot.name}`}
                    className="p-2 text-gray-400 hover:text-white transition-all duration-200 rounded-lg hover:bg-white/5"
                    title={t('bots.duplicate')}
                  >
                    <Copy size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(bot.bot_config_id, bot.name)}
                    disabled={bot.status === 'running'}
                    aria-label={`${t('bots.delete')} ${bot.name}`}
                    className="p-2 text-gray-400 hover:text-red-400 disabled:opacity-30 transition-all duration-200 rounded-lg hover:bg-red-500/5"
                    title={t('bots.delete')}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Trade History Modal */}
      {historyBot && (
        <BotTradeHistoryModal bot={historyBot} onClose={() => setHistoryBot(null)} t={t} />
      )}

      {/* Builder Fee Approval Modal */}
      {builderFeeModalBotId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-md" onClick={() => setBuilderFeeModalBotId(null)}>
          <div className="max-w-lg w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <BuilderFeeApproval
              onApproved={handleBuilderFeeApproved}
              onClose={() => setBuilderFeeModalBotId(null)}
            />
          </div>
        </div>
      )}

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
