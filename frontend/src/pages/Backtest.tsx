import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import {
  FlaskConical, Play, Trash2, Clock, CheckCircle, XCircle,
  Loader2, TrendingUp, TrendingDown, Activity, BarChart3,
  Target, Bot, Info,
} from 'lucide-react'
import api from '../api/client'
import DatePicker from '../components/ui/DatePicker'
import FilterDropdown from '../components/ui/FilterDropdown'
import type { BacktestRun, BacktestHistoryItem } from '../types'

const STRATEGY_DISPLAY: Record<string, string> = {
  liquidation_hunter: 'Liquidation Hunter',
  sentiment_surfer: 'Sentiment Surfer',
  llm_signal: 'KI-Companion',
}

const TRADING_PAIRS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'AVAXUSDT']

const TIMEFRAMES = [
  { value: '1m', label: '1m' },
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '30m', label: '30m' },
  { value: '1h', label: '1h' },
  { value: '4h', label: '4h' },
  { value: '1d', label: '1D' },
]

function strategyLabel(type: string): string {
  return STRATEGY_DISPLAY[type] || type.replace(/_/g, ' ')
}

export default function Backtest() {
  const { t } = useTranslation()

  // Form state
  const [strategies, setStrategies] = useState<{ name: string; description: string }[]>([])
  const [strategyType, setStrategyType] = useState('')
  const [symbol, setSymbol] = useState('BTCUSDT')
  const [timeframe, setTimeframe] = useState('1d')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [initialCapital, setInitialCapital] = useState(10000)
  const [customPrompt, setCustomPrompt] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Results state
  const [activeRun, setActiveRun] = useState<BacktestRun | null>(null)
  const [history, setHistory] = useState<BacktestHistoryItem[]>([])
  const [loadingHistory, setLoadingHistory] = useState(true)
  const pollRef = useRef<ReturnType<typeof setInterval>>()

  // Fetch strategies on mount
  useEffect(() => {
    api.get('/backtest/strategies').then(res => {
      setStrategies(res.data.strategies || [])
      if (res.data.strategies?.length > 0 && !strategyType) {
        setStrategyType(res.data.strategies[0].name)
      }
    }).catch(() => {})
  }, [])

  // Fetch history on mount
  const fetchHistory = useCallback(() => {
    api.get('/backtest/history?per_page=50').then(res => {
      setHistory(res.data.runs || [])
    }).catch(() => {}).finally(() => setLoadingHistory(false))
  }, [])

  useEffect(() => { fetchHistory() }, [fetchHistory])

  // Poll for active run status
  useEffect(() => {
    if (activeRun && (activeRun.status === 'pending' || activeRun.status === 'running')) {
      pollRef.current = setInterval(async () => {
        try {
          const res = await api.get(`/backtest/${activeRun.id}`)
          setActiveRun(res.data)
          if (res.data.status === 'completed' || res.data.status === 'failed') {
            fetchHistory()
          }
        } catch { /* ignore */ }
      }, 2000)
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [activeRun?.id, activeRun?.status, fetchHistory])

  const handleSubmit = async () => {
    if (!strategyType || !startDate || !endDate) return
    setSubmitting(true)
    try {
      const params: Record<string, any> = {}
      if (strategyType === 'llm_signal' && customPrompt.trim()) {
        params.custom_prompt = customPrompt.trim()
      }
      const res = await api.post('/backtest/run', {
        strategy_type: strategyType,
        symbol,
        timeframe,
        start_date: startDate,
        end_date: endDate,
        initial_capital: initialCapital,
        strategy_params: Object.keys(params).length > 0 ? params : undefined,
      })
      const runRes = await api.get(`/backtest/${res.data.run_id}`)
      setActiveRun(runRes.data)
      fetchHistory()
    } catch { /* ignore */ }
    setSubmitting(false)
  }

  const handleLoadRun = async (runId: number) => {
    try {
      const res = await api.get(`/backtest/${runId}`)
      setActiveRun(res.data)
    } catch { /* ignore */ }
  }

  const handleDelete = async (runId: number) => {
    try {
      await api.delete(`/backtest/${runId}`)
      setHistory(prev => prev.filter(h => h.id !== runId))
      if (activeRun?.id === runId) setActiveRun(null)
    } catch { /* ignore */ }
  }

  const isRunning = activeRun?.status === 'pending' || activeRun?.status === 'running'
  const hasResults = activeRun?.status === 'completed' && activeRun.metrics

  // Build dropdown options
  const strategyOptions = [
    { value: '', label: t('backtest.selectStrategy') },
    ...strategies.map(s => ({ value: s.name, label: strategyLabel(s.name) })),
  ]

  const symbolOptions = TRADING_PAIRS.map(p => ({ value: p, label: p }))

  const timeframeOptions = TIMEFRAMES.map(tf => ({ value: tf.value, label: tf.label }))

  return (
    <div className="space-y-6 animate-in">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-1">
          <FlaskConical size={22} className="text-primary-400" />
          <h1 className="text-2xl font-bold text-white">{t('backtest.title')}</h1>
        </div>
        <p className="text-gray-400 text-sm">{t('backtest.subtitle')}</p>
      </div>

      {/* Configuration Card – backdrop-filter disabled to prevent clipping of DatePicker popups */}
      <div className="glass-card rounded-xl p-6 border border-gray-800 overflow-visible !backdrop-blur-none">
        <h2 className="text-white font-semibold mb-5">{t('backtest.configuration')}</h2>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-x-5 gap-y-4">
          {/* Strategy */}
          <div className="relative z-40">
            <label className="text-xs text-gray-400 mb-1.5 block font-medium">{t('backtest.strategy')}</label>
            <FilterDropdown
              value={strategyType}
              onChange={setStrategyType}
              ariaLabel={t('backtest.strategy')}
              options={strategyOptions}
            />
            <p className="text-[11px] text-gray-500 mt-1">{t('backtest.strategyDesc')}</p>
          </div>

          {/* Symbol */}
          <div className="relative z-40">
            <label className="text-xs text-gray-400 mb-1.5 block font-medium">{t('backtest.symbol')}</label>
            <FilterDropdown
              value={symbol}
              onChange={setSymbol}
              ariaLabel={t('backtest.symbol')}
              options={symbolOptions}
            />
            <p className="text-[11px] text-gray-500 mt-1">{t('backtest.symbolDesc')}</p>
          </div>

          {/* Timeframe */}
          <div className="relative z-40">
            <label className="text-xs text-gray-400 mb-1.5 block font-medium">{t('backtest.timeframe')}</label>
            <FilterDropdown
              value={timeframe}
              onChange={setTimeframe}
              ariaLabel={t('backtest.timeframe')}
              options={timeframeOptions}
            />
            <p className="text-[11px] text-gray-500 mt-1">{t('backtest.timeframeDesc')}</p>
          </div>

          {/* Period: Start + End Date side by side */}
          <div className="sm:col-span-2 relative z-30">
            <label className="text-xs text-gray-400 mb-1.5 block font-medium">{t('backtest.period')}</label>
            <div className="flex items-center gap-3">
              <DatePicker
                value={startDate}
                onChange={setStartDate}
                label={t('backtest.startDate')}
                placeholder={t('backtest.startDate')}
              />
              <span className="text-gray-500 text-sm">&ndash;</span>
              <DatePicker
                value={endDate}
                onChange={setEndDate}
                label={t('backtest.endDate')}
                placeholder={t('backtest.endDate')}
              />
            </div>
            <p className="text-[11px] text-gray-500 mt-1">{t('backtest.periodDesc')}</p>
          </div>

          {/* Initial Capital */}
          <div>
            <label className="text-xs text-gray-400 mb-1.5 block font-medium">{t('backtest.initialCapital')}</label>
            <input
              type="number"
              value={initialCapital}
              onChange={e => setInitialCapital(Number(e.target.value))}
              className="input-dark w-full"
              min={100}
              max={10000000}
            />
            <p className="text-[11px] text-gray-500 mt-1">{t('backtest.capitalDesc')}</p>
          </div>
        </div>

        {/* KI-Companion Custom Prompt */}
        {strategyType === 'llm_signal' && (
          <div className="mt-5">
            <div className="flex items-center gap-2 mb-2">
              <Bot size={14} className="text-emerald-400" />
              <label className="text-xs text-gray-400 font-medium">{t('backtest.customPrompt')}</label>
            </div>
            <textarea
              value={customPrompt}
              onChange={e => setCustomPrompt(e.target.value)}
              className="input-dark w-full h-24 resize-none"
              placeholder={t('backtest.customPromptHint')}
            />
            <div className="flex items-start gap-2 mt-2 p-3 rounded-lg bg-amber-900/20 border border-amber-700/30">
              <Info size={14} className="text-amber-400 mt-0.5 shrink-0" />
              <p className="text-xs text-amber-300/80">{t('backtest.llmNote')}</p>
            </div>
          </div>
        )}

        {/* Submit */}
        <div className="mt-6">
          <button
            onClick={handleSubmit}
            disabled={submitting || isRunning || !strategyType || !startDate || !endDate}
            className="btn-gradient px-6 py-2.5 rounded-lg flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {submitting || isRunning ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                {t('backtest.running')}
              </>
            ) : (
              <>
                <Play size={16} />
                {t('backtest.startBacktest')}
              </>
            )}
          </button>
        </div>
      </div>

      {/* Running State */}
      {isRunning && (
        <div className="glass-card rounded-xl p-8 border border-gray-800 flex flex-col items-center justify-center">
          <div className="w-10 h-10 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mb-4" />
          <p className="text-gray-300 font-medium">{t('backtest.running')}</p>
          <p className="text-gray-500 text-sm mt-1">{strategyLabel(activeRun?.strategy_type || '')} &middot; {activeRun?.symbol}</p>
        </div>
      )}

      {/* Error State */}
      {activeRun?.status === 'failed' && (
        <div className="glass-card rounded-xl p-6 border border-red-800/50 bg-red-900/10">
          <div className="flex items-center gap-2 text-red-400 mb-2">
            <XCircle size={18} />
            <span className="font-semibold">{t('backtest.failed')}</span>
          </div>
          <p className="text-red-300/70 text-sm">{activeRun.error_message || 'Unknown error'}</p>
        </div>
      )}

      {/* Results */}
      {hasResults && activeRun.metrics && (
        <div className="space-y-6">
          <h2 className="text-white font-semibold text-lg">{t('backtest.results')}</h2>

          {/* Metrics Cards */}
          <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
            <MetricCard
              icon={<TrendingUp size={16} />}
              label={t('backtest.totalReturn')}
              value={`${activeRun.metrics.total_return_percent >= 0 ? '+' : ''}${activeRun.metrics.total_return_percent.toFixed(2)}%`}
              color={activeRun.metrics.total_return_percent >= 0 ? 'text-profit' : 'text-loss'}
            />
            <MetricCard
              icon={<Activity size={16} />}
              label={t('backtest.winRate')}
              value={`${activeRun.metrics.win_rate.toFixed(1)}%`}
              color={activeRun.metrics.win_rate >= 60 ? 'text-profit' : activeRun.metrics.win_rate >= 40 ? 'text-yellow-400' : 'text-loss'}
            />
            <MetricCard
              icon={<TrendingDown size={16} />}
              label={t('backtest.maxDrawdown')}
              value={`-${activeRun.metrics.max_drawdown_percent.toFixed(2)}%`}
              color="text-red-400"
            />
            <MetricCard
              icon={<BarChart3 size={16} />}
              label={t('backtest.sharpeRatio')}
              value={activeRun.metrics.sharpe_ratio?.toFixed(2) ?? 'N/A'}
              color={activeRun.metrics.sharpe_ratio && activeRun.metrics.sharpe_ratio > 1 ? 'text-profit' : 'text-gray-300'}
            />
            <MetricCard
              icon={<Target size={16} />}
              label={t('backtest.profitFactor')}
              value={activeRun.metrics.profit_factor.toFixed(2)}
              color={activeRun.metrics.profit_factor > 1 ? 'text-profit' : 'text-loss'}
            />
            <MetricCard
              icon={<CheckCircle size={16} />}
              label={t('backtest.totalTrades')}
              value={`${activeRun.metrics.total_trades}`}
              color="text-blue-400"
              sub={`${activeRun.metrics.winning_trades}W / ${activeRun.metrics.losing_trades}L`}
            />
          </div>

          {/* Capital Summary */}
          <div className="grid sm:grid-cols-2 gap-3">
            <div className="glass-card rounded-xl p-4 border border-gray-800">
              <div className="text-xs text-gray-400 mb-1">{t('backtest.startingCapital')}</div>
              <div className="text-lg font-bold text-gray-300">${activeRun.metrics.starting_capital.toLocaleString()}</div>
            </div>
            <div className="glass-card rounded-xl p-4 border border-gray-800">
              <div className="text-xs text-gray-400 mb-1">{t('backtest.endingCapital')}</div>
              <div className={`text-lg font-bold ${activeRun.metrics.ending_capital >= activeRun.metrics.starting_capital ? 'text-profit' : 'text-loss'}`}>
                ${activeRun.metrics.ending_capital.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
            </div>
          </div>

          {/* Equity Curve */}
          {activeRun.equity_curve && activeRun.equity_curve.length > 0 && (
            <div className="glass-card rounded-xl p-5 border border-gray-800">
              <h3 className="text-white font-semibold mb-4">{t('backtest.equityCurve')}</h3>
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={activeRun.equity_curve}>
                  <defs>
                    <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis
                    dataKey="timestamp"
                    tick={{ fill: '#6b7280', fontSize: 11 }}
                    tickFormatter={v => v?.slice(5, 10) || v}
                  />
                  <YAxis
                    tick={{ fill: '#6b7280', fontSize: 11 }}
                    tickFormatter={v => `$${Number(v).toLocaleString()}`}
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
                    labelStyle={{ color: '#9ca3af' }}
                    formatter={(value: number) => [`$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, 'Equity']}
                  />
                  <Area type="monotone" dataKey="equity" stroke="#10b981" fill="url(#equityGradient)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Trade Log */}
          {activeRun.trades && activeRun.trades.length > 0 && (
            <div className="glass-card rounded-xl overflow-hidden border border-gray-800">
              <div className="px-5 pt-5 pb-3">
                <h3 className="text-white font-semibold">
                  {t('backtest.tradeLog')} ({activeRun.trades.length})
                </h3>
              </div>
              <div className="overflow-x-auto">
                <table className="table-premium">
                  <thead>
                    <tr>
                      <th className="text-left">#</th>
                      <th className="text-left">{t('backtest.direction')}</th>
                      <th className="text-left">Symbol</th>
                      <th className="text-right">{t('backtest.entryPrice')}</th>
                      <th className="text-right">{t('backtest.exitPrice')}</th>
                      <th className="text-right">{t('backtest.pnl')}</th>
                      <th className="text-right">{t('backtest.netPnl')}</th>
                      <th className="text-right">{t('backtest.confidence')}</th>
                      <th className="text-left">{t('backtest.result')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeRun.trades.map((trade, idx) => (
                      <tr key={idx}>
                        <td className="text-gray-500 text-xs">{idx + 1}</td>
                        <td>
                          <span className={trade.direction === 'long' ? 'text-profit' : 'text-loss'}>
                            {trade.direction === 'long' ? '+' : '-'} {trade.direction.toUpperCase()}
                          </span>
                        </td>
                        <td className="text-white font-medium">{trade.symbol}</td>
                        <td className="text-right text-gray-300 font-mono">${trade.entry_price.toLocaleString()}</td>
                        <td className="text-right text-gray-300 font-mono">
                          {trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}
                        </td>
                        <td className={`text-right font-mono ${trade.pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                          {trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}
                        </td>
                        <td className={`text-right font-mono ${trade.net_pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                          {trade.net_pnl >= 0 ? '+' : ''}${trade.net_pnl.toFixed(2)}
                        </td>
                        <td className="text-right text-gray-400">{trade.confidence}%</td>
                        <td>
                          <span className={`text-xs ${
                            trade.result === 'take_profit' ? 'text-emerald-400' :
                            trade.result === 'stop_loss' ? 'text-red-400' : 'text-yellow-400'
                          }`}>
                            {trade.result.replace(/_/g, ' ')}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* No Results Hint */}
      {!activeRun && !isRunning && (
        <div className="glass-card rounded-xl p-10 border border-gray-800 text-center">
          <FlaskConical size={40} className="text-gray-600 mx-auto mb-3" />
          <p className="text-gray-500">{t('backtest.noResults')}</p>
        </div>
      )}

      {/* History */}
      <div className="glass-card rounded-xl overflow-hidden border border-gray-800">
        <div className="px-5 pt-5 pb-3">
          <h2 className="text-white font-semibold">{t('backtest.history')}</h2>
        </div>
        {loadingHistory ? (
          <div className="flex justify-center py-6">
            <Loader2 size={20} className="animate-spin text-gray-500" />
          </div>
        ) : history.length === 0 ? (
          <p className="text-gray-500 text-sm py-6 text-center">{t('backtest.noHistory')}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="table-premium">
              <thead>
                <tr>
                  <th className="text-left">{t('backtest.strategy')}</th>
                  <th className="text-left">Symbol</th>
                  <th className="text-left">{t('backtest.timeframe')}</th>
                  <th className="text-left">{t('backtest.startDate')}</th>
                  <th className="text-left">{t('backtest.endDate')}</th>
                  <th className="text-right">{t('backtest.totalReturn')}</th>
                  <th className="text-right">{t('backtest.winRate')}</th>
                  <th className="text-right">{t('backtest.totalTrades')}</th>
                  <th className="text-center">Status</th>
                  <th className="text-right"></th>
                </tr>
              </thead>
              <tbody>
                {history.map(run => (
                  <tr
                    key={run.id}
                    className="cursor-pointer"
                    onClick={() => handleLoadRun(run.id)}
                  >
                    <td className="text-white font-medium">{strategyLabel(run.strategy_type)}</td>
                    <td className="text-gray-300">{run.symbol}</td>
                    <td className="text-gray-400">{run.timeframe}</td>
                    <td className="text-gray-400">{run.start_date}</td>
                    <td className="text-gray-400">{run.end_date}</td>
                    <td className={`text-right font-mono ${
                      run.total_return_percent !== null
                        ? (run.total_return_percent >= 0 ? 'text-profit' : 'text-loss')
                        : 'text-gray-500'
                    }`}>
                      {run.total_return_percent !== null
                        ? `${run.total_return_percent >= 0 ? '+' : ''}${run.total_return_percent.toFixed(2)}%`
                        : '--'}
                    </td>
                    <td className={`text-right font-mono ${
                      run.win_rate !== null
                        ? (run.win_rate >= 60 ? 'text-profit' : run.win_rate >= 40 ? 'text-yellow-400' : 'text-loss')
                        : 'text-gray-500'
                    }`}>
                      {run.win_rate !== null ? `${run.win_rate.toFixed(1)}%` : '--'}
                    </td>
                    <td className="text-right text-gray-400">
                      {run.total_trades ?? '--'}
                    </td>
                    <td className="text-center">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="text-right">
                      <button
                        onClick={e => { e.stopPropagation(); handleDelete(run.id) }}
                        className="p-1.5 text-gray-500 hover:text-red-400 transition-colors rounded"
                        title={t('backtest.deleteConfirm')}
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function MetricCard({ icon, label, value, color, sub }: {
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

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { icon: React.ReactNode; cls: string }> = {
    pending: { icon: <Clock size={12} />, cls: 'bg-yellow-900/30 text-yellow-400 border-yellow-700' },
    running: { icon: <Loader2 size={12} className="animate-spin" />, cls: 'bg-emerald-900/30 text-emerald-400 border-emerald-700' },
    completed: { icon: <CheckCircle size={12} />, cls: 'bg-emerald-900/30 text-emerald-400 border-emerald-700' },
    failed: { icon: <XCircle size={12} />, cls: 'bg-red-900/30 text-red-400 border-red-700' },
  }
  const c = config[status] || config.pending
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full border ${c.cls}`}>
      {c.icon}
      {status}
    </span>
  )
}
