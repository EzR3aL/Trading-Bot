import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  ComposedChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Bar,
} from 'recharts'
import {
  ArrowLeft, Play, Square, TrendingUp, TrendingDown,
  Activity, AlertCircle, CheckCircle, Bot, ShieldCheck,
} from 'lucide-react'
import api from '../api/client'
import { getApiErrorMessage } from '../utils/api-error'
import { useToastStore } from '../stores/toastStore'
import { useFilterStore } from '../stores/filterStore'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import PnlCell from '../components/ui/PnlCell'
import type { LlmConnection } from '../types'
import { formatDate, formatTime, formatChartCurrency } from '../utils/dateUtils'
import MobileTradeCard from '../components/ui/MobileTradeCard'
import useIsMobile from '../hooks/useIsMobile'

import { strategyLabel } from '../constants/strategies'

interface BotConfig {
  id: number
  name: string
  description: string | null
  strategy_type: string
  exchange_type: string
  mode: string
  trading_pairs: string[]
  leverage: number
  position_size_percent: number
  max_trades_per_day: number
  take_profit_percent: number
  stop_loss_percent: number
  daily_loss_limit_percent: number
  schedule_type: string
  schedule_config: Record<string, any> | null
  is_enabled: boolean
  discord_webhook_configured: boolean
  telegram_configured: boolean
  whatsapp_configured: boolean
  created_at: string | null
}

interface DailySeries {
  date: string
  pnl: number
  cumulative_pnl: number
  trades: number
  wins: number
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
  entry_time: string | null
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

interface BotStats {
  bot_id: number
  bot_name: string
  strategy_type: string
  exchange_type: string
  mode: string
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
  daily_series: DailySeries[]
  recent_trades: BotTrade[]
}

interface RuntimeStatus {
  bot_config_id: number
  status: string
  error_message: string | null
  started_at: string | null
  last_analysis: string | null
  trades_today: number
  llm_provider?: string | null
  llm_model?: string | null
}

const STATUS_STYLES: Record<string, { dot: string; badge: string; i18nKey: string }> = {
  running:  { dot: 'bg-emerald-400 animate-pulse', badge: 'bg-emerald-900/30 text-emerald-400 border-emerald-700', i18nKey: 'bots.running' },
  starting: { dot: 'bg-yellow-400 animate-pulse',  badge: 'bg-yellow-900/30 text-yellow-400 border-yellow-700',   i18nKey: 'bots.starting' },
  idle:     { dot: 'bg-gray-400',                   badge: 'bg-gray-800 text-gray-400 border-gray-700',           i18nKey: 'bots.idle' },
  stopped:  { dot: 'bg-gray-500',                   badge: 'bg-gray-800 text-gray-400 border-gray-700',           i18nKey: 'bots.stopped' },
  error:    { dot: 'bg-red-400',                     badge: 'bg-red-900/30 text-red-400 border-red-700',           i18nKey: 'bots.error' },
}

export default function BotDetail() {
  const { botId } = useParams<{ botId: string }>()
  const navigate = useNavigate()
  const { t } = useTranslation()
  const d = (key: string) => t(`botDetail.${key}`)
  const isMobile = useIsMobile()
  const demoFilter = useFilterStore((s) => s.demoFilter)

  const [config, setConfig] = useState<BotConfig | null>(null)
  const [stats, setStats] = useState<BotStats | null>(null)
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [days, setDays] = useState(30)
  const [llmConnections, setLlmConnections] = useState<LlmConnection[]>([])

  const modelNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const conn of llmConnections) {
      for (const m of conn.models || []) map[m.id] = m.name
    }
    return map
  }, [llmConnections])

  const providerNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const conn of llmConnections) map[conn.provider_type] = conn.family_name || conn.display_name
    return map
  }, [llmConnections])

  const fetchData = useCallback(async () => {
    if (!botId) return
    try {
      const demoParam = demoFilter !== 'all' ? `&demo_mode=${demoFilter === 'demo'}` : ''
      const [configRes, statsRes, listRes] = await Promise.all([
        api.get(`/bots/${botId}`),
        api.get(`/bots/${botId}/statistics?days=${days}${demoParam}`),
        api.get('/bots'),
      ])
      setConfig(configRes.data)
      setStats(statsRes.data)
      const match = listRes.data.bots?.find((b: any) => b.bot_config_id === Number(botId))
      if (match) {
        setRuntime({
          bot_config_id: match.bot_config_id,
          status: match.status,
          error_message: match.error_message,
          started_at: match.started_at,
          last_analysis: match.last_analysis,
          trades_today: match.trades_today,
          llm_provider: match.llm_provider,
          llm_model: match.llm_model,
        })
      }
      setError('')
    } catch (err) {
      setError(getApiErrorMessage(err, t('common.error')))
    } finally {
      setLoading(false)
    }
  }, [botId, days, demoFilter])

  useEffect(() => { fetchData() }, [fetchData])

  useEffect(() => {
    api.get('/config/llm-connections').then(res => setLlmConnections(res.data.connections || [])).catch((err) => { console.error('Failed to load LLM connections:', err); useToastStore.getState().addToast('error', t('common.loadError', 'Failed to load data')) })
  }, [])

  // Auto-refresh every 10s
  useEffect(() => {
    const iv = setInterval(fetchData, 10_000)
    return () => clearInterval(iv)
  }, [fetchData])

  const [actionLoading, setActionLoading] = useState(false)
  const [confirmStop, setConfirmStop] = useState(false)

  const handleStart = async () => {
    setActionLoading(true)
    try {
      await api.post(`/bots/${botId}/start`)
      await fetchData()
    } catch (err) {
      setError(getApiErrorMessage(err, t('bots.failedStart')))
    }
    setActionLoading(false)
  }

  const handleStopClick = () => {
    if (!confirmStop) {
      setConfirmStop(true)
      setTimeout(() => setConfirmStop(false), 3000)
      return
    }
    doStop()
  }

  const doStop = async () => {
    setConfirmStop(false)
    setActionLoading(true)
    try {
      await api.post(`/bots/${botId}/stop`)
      await fetchData()
    } catch (err) {
      setError(getApiErrorMessage(err, t('bots.failedStop')))
    }
    setActionLoading(false)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (!config || !stats) {
    return (
      <div className="p-6">
        <button onClick={() => navigate('/bots')} className="flex items-center gap-2 text-gray-400 hover:text-white mb-4">
          <ArrowLeft size={16} /> {d('back')}
        </button>
        <div className="text-red-400">{error || t('common.error')}</div>
      </div>
    )
  }

  const s = stats.summary
  const statusKey = runtime?.status || 'idle'
  const style = STATUS_STYLES[statusKey] || STATUS_STYLES.idle


  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Back + Header */}
      <div>
        <button onClick={() => navigate('/bots')} className="flex items-center gap-2 text-gray-400 hover:text-white text-sm mb-3 transition-colors">
          <ArrowLeft size={14} /> {d('back')}
        </button>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-white">{config.name}</h1>
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs border ${style.badge}`}>
                <span className={`w-2 h-2 rounded-full ${style.dot}`} />
                {t(style.i18nKey)}
              </span>
            </div>
            <div className="flex items-center gap-2 mt-1.5 text-sm text-gray-400">
              <ExchangeIcon exchange={config.exchange_type} size={14} />
              <span className="capitalize">{config.exchange_type}</span>
              <span className="text-gray-600">·</span>
              <span className={config.mode === 'demo' ? 'text-blue-400' : config.mode === 'live' ? 'text-orange-400' : 'text-purple-400'}>
                {config.mode.toUpperCase()}
              </span>
              <span className="text-gray-600">·</span>
              <span>{strategyLabel(config.strategy_type)}</span>
              {['llm_signal', 'degen'].includes(config.strategy_type) && (
                <Bot size={15} className="text-emerald-400" />
              )}
              {runtime?.llm_provider && (
                <>
                  <span className="text-gray-600">·</span>
                  <span className="text-gray-400">{providerNameMap[runtime.llm_provider] || runtime.llm_provider}</span>
                  {runtime.llm_model && (
                    <span className="text-gray-300 font-medium">{modelNameMap[runtime.llm_model] || runtime.llm_model}</span>
                  )}
                </>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {statusKey === 'running' || statusKey === 'starting' ? (
              <button onClick={handleStopClick} disabled={actionLoading} className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${confirmStop ? 'bg-red-600 text-white border border-red-500 animate-pulse' : 'bg-red-900/30 text-red-400 border border-red-700 hover:bg-red-900/50'} ${actionLoading ? 'opacity-60 cursor-not-allowed' : ''}`}>
                {actionLoading ? <div className="w-4 h-4 border-2 border-red-400 border-t-transparent rounded-full animate-spin" /> : <Square size={14} />} {confirmStop ? t('bots.confirmStop') : t('bots.stop')}
              </button>
            ) : (
              <button onClick={handleStart} disabled={actionLoading} className={`flex items-center gap-2 px-4 py-2 bg-emerald-900/30 text-emerald-400 border border-emerald-700 rounded-lg hover:bg-emerald-900/50 transition-colors ${actionLoading ? 'opacity-60 cursor-not-allowed' : ''}`}>
                {actionLoading ? <div className="w-4 h-4 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" /> : <Play size={14} />} {t('bots.start')}
              </button>
            )}
          </div>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 p-3 bg-red-900/20 border border-red-800 rounded-lg text-red-400 text-sm">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={<TrendingUp size={16} />} label={d('totalPnl')} value={`$${s.total_pnl.toFixed(2)}`} color={s.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'} />
        <StatCard icon={<Activity size={16} />} label={d('winRate')} value={`${s.win_rate}%`} color={s.win_rate >= 60 ? 'text-emerald-400' : s.win_rate >= 40 ? 'text-yellow-400' : 'text-red-400'} />
        <StatCard icon={<CheckCircle size={16} />} label={d('totalTrades')} value={`${s.total_trades}`} color="text-blue-400" sub={`${s.wins}W / ${s.losses}L`} />
        <StatCard icon={<TrendingDown size={16} />} label={d('bestTrade')} value={`$${s.best_trade.toFixed(2)}`} color="text-emerald-400" sub={`${d('worstTrade')}: $${s.worst_trade.toFixed(2)}`} />
      </div>

      {/* PnL Chart */}
      {stats.daily_series.length > 0 && (
        <div className="glass-card rounded-xl p-5 border border-white/10">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-white font-semibold">{d('pnlChart')}</h2>
            <div className="flex gap-1">
              {[7, 14, 30, 90].map(d_ => (
                <button
                  key={d_}
                  onClick={() => setDays(d_)}
                  className={`px-2.5 py-1 text-xs rounded transition-colors ${days === d_ ? 'bg-primary-900/40 text-primary-400 border border-primary-700' : 'text-gray-400 hover:text-gray-300'}`}
                >
                  {d_}d
                </button>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={stats.daily_series}>
              <defs>
                <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: 10 }} tickFormatter={v => v?.slice(5)} />
              <YAxis width={45} tick={{ fill: '#6b7280', fontSize: 10 }} tickFormatter={formatChartCurrency} />
              <Tooltip
                contentStyle={{ backgroundColor: 'rgba(20, 26, 42, 0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '12px', backdropFilter: 'blur(24px)' }}
                labelStyle={{ color: '#9ca3af' }}
                formatter={(value: number, name: string) => [`$${value.toFixed(2)}`, name === 'cumulative_pnl' ? d('cumulativePnl') : d('dailyPnl')]}
              />
              <Area type="monotone" dataKey="cumulative_pnl" stroke="#6366f1" fill="url(#pnlGradient)" strokeWidth={2} />
              <Bar dataKey="pnl" fill="#4f46e5" opacity={0.4} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="grid gap-6">
        {/* Trades Table */}
        <div className="glass-card rounded-xl p-5 border border-white/10">
          <h2 className="text-white font-semibold mb-4">{d('recentTrades')} ({stats.recent_trades.length})</h2>
          {stats.recent_trades.length === 0 ? (
            <p className="text-gray-400 text-sm py-8 text-center">{d('noTrades')}</p>
          ) : isMobile ? (
              <div className="space-y-1.5">
                {stats.recent_trades.map(trade => (
                  <MobileTradeCard key={trade.id} trade={{ ...trade, bot_exchange: config.exchange_type, entry_time: trade.entry_time || '' }} />
                ))}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="table-premium">
                  <thead>
                    <tr>
                      <th className="text-left">{t('trades.date')}</th>
                      <th className="text-center hidden lg:table-cell">{t('trades.exchange')}</th>
                      <th className="text-left">{t('trades.symbol')}</th>
                      <th className="text-center">{t('trades.side')}</th>
                      <th className="text-right hidden xl:table-cell">{t('trades.entryPrice')}</th>
                      <th className="text-right">{t('trades.pnl')}</th>
                      <th className="text-center hidden xl:table-cell">{t('trades.trailingStop')}</th>
                      <th className="text-center hidden 2xl:table-cell">{t('trades.mode')}</th>
                      <th className="text-center">{t('trades.status')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.recent_trades.map(trade => (
                      <tr key={trade.id}>
                        <td className="text-gray-300 cursor-default" title={formatTime(trade.entry_time)}>
                          {formatDate(trade.entry_time)}
                        </td>
                        <td className="text-center hidden lg:table-cell">
                          <span className="inline-flex justify-center">
                            <ExchangeIcon exchange={config.exchange_type} size={18} />
                          </span>
                        </td>
                        <td className="text-white font-medium">{trade.symbol}</td>
                        <td className="text-center">
                          <span className={trade.side === 'long' ? 'text-profit' : 'text-loss'}>
                            {trade.side === 'long' ? '+' : '-'} {trade.side.toUpperCase()}
                          </span>
                        </td>
                        <td className="text-right text-gray-300 hidden xl:table-cell">
                          ${trade.entry_price.toLocaleString()}
                        </td>
                        <td className="text-right">
                          <PnlCell pnl={trade.pnl} fees={trade.fees || 0} fundingPaid={trade.funding_paid || 0} status={trade.status} className={trade.pnl >= 0 ? 'pnl-positive' : 'pnl-negative'} />
                        </td>
                        <td className="text-center hidden xl:table-cell">
                          {trade.status === 'open' && trade.trailing_stop_active && trade.trailing_stop_price != null ? (
                            <span className="inline-flex items-center justify-center gap-1 text-emerald-400">
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
                    ))}
                  </tbody>
                </table>
              </div>
            )
          }
        </div>

        
      </div>
    </div>
  )
}

function StatCard({ icon, label, value, color, sub }: {
  icon: React.ReactNode
  label: string
  value: string
  color: string
  sub?: string
}) {
  return (
    <div className="glass-card rounded-xl p-4 border border-white/10">
      <div className="flex items-center gap-2 text-gray-400 text-[10px] sm:text-xs mb-1">
        {icon} {label}
      </div>
      <div className={`text-xl font-bold ${color}`}>{value}</div>
      {sub && <div className="text-[10px] sm:text-xs text-gray-400 mt-0.5">{sub}</div>}
    </div>
  )
}


