import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Bar,
} from 'recharts'
import {
  ArrowLeft, Play, Square, Settings, TrendingUp, TrendingDown,
  Activity, AlertCircle, CheckCircle, Bot,
} from 'lucide-react'
import api from '../api/client'
import { useFilterStore } from '../stores/filterStore'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import PnlCell from '../components/ui/PnlCell'

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
  rotation_enabled: boolean
  rotation_interval_minutes: number | null
  is_enabled: boolean
  discord_webhook_configured: boolean
  telegram_configured: boolean
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
  const demoFilter = useFilterStore((s) => s.demoFilter)

  const [config, setConfig] = useState<BotConfig | null>(null)
  const [stats, setStats] = useState<BotStats | null>(null)
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [days, setDays] = useState(30)

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
        })
      }
      setError('')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load bot data')
    } finally {
      setLoading(false)
    }
  }, [botId, days, demoFilter])

  useEffect(() => { fetchData() }, [fetchData])

  // Auto-refresh every 10s
  useEffect(() => {
    const iv = setInterval(fetchData, 10_000)
    return () => clearInterval(iv)
  }, [fetchData])

  const handleStart = async () => {
    try {
      await api.post(`/bots/${botId}/start`)
      fetchData()
    } catch (err: any) {
      setError(err.response?.data?.detail || t('bots.failedStart'))
    }
  }

  const handleStop = async () => {
    try {
      await api.post(`/bots/${botId}/stop`)
      fetchData()
    } catch (err: any) {
      setError(err.response?.data?.detail || t('bots.failedStop'))
    }
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

  const formatSchedule = () => {
    if (config.schedule_type === 'market_sessions') return d('scheduleMarketSessions')
    if (config.schedule_type === 'interval') return t('botDetail.scheduleInterval', { minutes: config.schedule_config?.interval_minutes || 60 })
    if (config.schedule_type === 'rotation_only') return t('botDetail.scheduleRotation', { minutes: config.rotation_interval_minutes })
    if (config.schedule_type === 'custom_cron') return t('botDetail.scheduleCustom', { hours: (config.schedule_config?.hours || []).join(', ') })
    return config.schedule_type
  }

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
              <span>{config.strategy_type === 'llm_signal' ? 'KI-Companion' : config.strategy_type.replace(/_/g, ' ')}</span>
              {config.strategy_type === 'llm_signal' && (
                <Bot size={15} className="text-emerald-400" />
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {statusKey === 'running' || statusKey === 'starting' ? (
              <button onClick={handleStop} className="flex items-center gap-2 px-4 py-2 bg-red-900/30 text-red-400 border border-red-700 rounded-lg hover:bg-red-900/50 transition-colors">
                <Square size={14} /> {t('bots.stop')}
              </button>
            ) : (
              <button onClick={handleStart} className="flex items-center gap-2 px-4 py-2 bg-emerald-900/30 text-emerald-400 border border-emerald-700 rounded-lg hover:bg-emerald-900/50 transition-colors">
                <Play size={14} /> {t('bots.start')}
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
        <div className="glass-card rounded-xl p-5 border border-gray-800">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-white font-semibold">{d('pnlChart')}</h2>
            <div className="flex gap-1">
              {[7, 14, 30, 90].map(d_ => (
                <button
                  key={d_}
                  onClick={() => setDays(d_)}
                  className={`px-2.5 py-1 text-xs rounded transition-colors ${days === d_ ? 'bg-primary-900/40 text-primary-400 border border-primary-700' : 'text-gray-500 hover:text-gray-300'}`}
                >
                  {d_}d
                </button>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={stats.daily_series}>
              <defs>
                <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: 11 }} tickFormatter={v => v?.slice(5)} />
              <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} tickFormatter={v => `$${v}`} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
                labelStyle={{ color: '#9ca3af' }}
                formatter={(value: number, name: string) => [`$${value.toFixed(2)}`, name === 'cumulative_pnl' ? d('cumulativePnl') : d('dailyPnl')]}
              />
              <Area type="monotone" dataKey="cumulative_pnl" stroke="#6366f1" fill="url(#pnlGradient)" strokeWidth={2} />
              <Bar dataKey="pnl" fill="#4f46e5" opacity={0.4} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Trades Table */}
        <div className="lg:col-span-2 glass-card rounded-xl p-5 border border-gray-800">
          <h2 className="text-white font-semibold mb-4">{d('recentTrades')} ({stats.recent_trades.length})</h2>
          {stats.recent_trades.length === 0 ? (
            <p className="text-gray-500 text-sm py-8 text-center">{d('noTrades')}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 border-b border-gray-800">
                    <th className="text-left py-2 font-medium">Symbol</th>
                    <th className="text-left py-2 font-medium">Side</th>
                    <th className="text-right py-2 font-medium">Entry</th>
                    <th className="text-right py-2 font-medium">Exit</th>
                    <th className="text-right py-2 font-medium">PnL</th>
                    <th className="text-right py-2 font-medium">%</th>
                    <th className="text-left py-2 font-medium">Status</th>
                    <th className="text-left py-2 font-medium">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.recent_trades.map(trade => (
                    <tr key={trade.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                      <td className="py-2 text-white font-mono">{trade.symbol}</td>
                      <td className="py-2">
                        <span className={trade.side === 'long' ? 'text-emerald-400' : 'text-red-400'}>
                          {trade.side.toUpperCase()}
                        </span>
                      </td>
                      <td className="py-2 text-right text-gray-300 font-mono">${trade.entry_price.toLocaleString()}</td>
                      <td className="py-2 text-right text-gray-300 font-mono">
                        {trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '—'}
                      </td>
                      <td className="py-2 text-right"><PnlCell pnl={trade.pnl} fees={trade.fees || 0} fundingPaid={trade.funding_paid || 0} /></td>
                      <td className="py-2 text-right">
                        <span className={trade.pnl_percent >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                          {trade.pnl_percent >= 0 ? '+' : ''}{trade.pnl_percent.toFixed(1)}%
                        </span>
                      </td>
                      <td className="py-2">
                        <span className={`text-xs px-1.5 py-0.5 rounded ${trade.status === 'open' ? 'bg-blue-900/30 text-blue-400' : 'bg-gray-800 text-gray-400'}`}>
                          {trade.status}
                        </span>
                      </td>
                      <td className="py-2 text-gray-500 text-xs">
                        {trade.entry_time ? new Date(trade.entry_time).toLocaleDateString() : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Config Card */}
        <div className="glass-card rounded-xl p-5 border border-gray-800 space-y-4">
          <h2 className="text-white font-semibold flex items-center gap-2">
            <Settings size={16} className="text-gray-400" /> {d('config')}
          </h2>
          <ConfigRow label={d('strategy')} value={config.strategy_type.replace(/_/g, ' ')} />
          <ConfigRow label={d('pairs')} value={config.trading_pairs.join(', ')} />
          <ConfigRow label={d('leverage')} value={`${config.leverage}x`} />
          <ConfigRow label={d('positionSize')} value={`${config.position_size_percent}%`} />
          <ConfigRow label={d('takeProfit')} value={`${config.take_profit_percent}%`} />
          <ConfigRow label={d('stopLoss')} value={`${config.stop_loss_percent}%`} />
          <ConfigRow label={d('dailyLoss')} value={`${config.daily_loss_limit_percent}%`} />
          <ConfigRow label={d('maxTrades')} value={`${config.max_trades_per_day}`} />
          <ConfigRow label={d('schedule')} value={formatSchedule()} />
          <ConfigRow label={d('fees')} value={`$${s.total_fees.toFixed(2)}`} />
          <ConfigRow label={d('funding')} value={`$${s.total_funding.toFixed(2)}`} />
          {config.discord_webhook_configured && (
            <ConfigRow label="Discord" value={`✓ ${d('discordConfigured')}`} />
          )}
          {config.telegram_configured && (
            <ConfigRow label="Telegram" value={`✓ ${d('telegramConfigured')}`} />
          )}
          {config.created_at && (
            <ConfigRow label={d('created')} value={new Date(config.created_at).toLocaleDateString()} />
          )}
          {runtime?.started_at && (
            <ConfigRow label={d('started')} value={new Date(runtime.started_at).toLocaleString()} />
          )}
          {runtime?.last_analysis && (
            <ConfigRow label={d('lastAnalysis')} value={new Date(runtime.last_analysis).toLocaleString()} />
          )}
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
    <div className="glass-card rounded-xl p-4 border border-gray-800">
      <div className="flex items-center gap-2 text-gray-400 text-xs mb-1">
        {icon} {label}
      </div>
      <div className={`text-xl font-bold ${color}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-0.5">{sub}</div>}
    </div>
  )
}

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-center text-sm">
      <span className="text-gray-400">{label}</span>
      <span className="text-white font-mono text-right max-w-[60%] truncate">{value}</span>
    </div>
  )
}
