import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../api/client'
import BotBuilder from '../components/bots/BotBuilder'
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
} from 'lucide-react'

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
  open_trades: number
}

const STATUS_COLORS: Record<string, string> = {
  running: 'text-green-400',
  stopped: 'text-gray-400',
  idle: 'text-gray-500',
  error: 'text-red-400',
  starting: 'text-yellow-400',
}

const STATUS_BG: Record<string, string> = {
  running: 'bg-green-900/30 border-green-800',
  stopped: 'bg-gray-800/50 border-gray-700',
  idle: 'bg-gray-800/50 border-gray-700',
  error: 'bg-red-900/30 border-red-800',
  starting: 'bg-yellow-900/30 border-yellow-800',
}

export default function Bots() {
  const { t } = useTranslation()
  const [bots, setBots] = useState<BotStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [showBuilder, setShowBuilder] = useState(false)
  const [editBotId, setEditBotId] = useState<number | null>(null)
  const [actionLoading, setActionLoading] = useState<number | null>(null)

  const fetchBots = useCallback(async () => {
    try {
      const res = await api.get('/bots')
      setBots(res.data.bots)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchBots()
    const interval = setInterval(fetchBots, 5000)
    return () => clearInterval(interval)
  }, [fetchBots])

  const handleStart = async (id: number) => {
    setActionLoading(id)
    try {
      await api.post(`/bots/${id}/start`)
      await fetchBots()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to start bot')
    }
    setActionLoading(null)
  }

  const handleStop = async (id: number) => {
    setActionLoading(id)
    try {
      await api.post(`/bots/${id}/stop`)
      await fetchBots()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to stop bot')
    }
    setActionLoading(null)
  }

  const handleDelete = async (id: number, name: string) => {
    if (!confirm(`${t('bots.confirmDelete')} (${name})`)) return
    try {
      await api.delete(`/bots/${id}`)
      await fetchBots()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to delete bot')
    }
  }

  const handleStopAll = async () => {
    try {
      await api.post('/bots/stop-all')
      await fetchBots()
    } catch {
      // ignore
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

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">{t('bots.title')}</h1>
        <div className="flex gap-2">
          {runningCount > 1 && (
            <button
              onClick={handleStopAll}
              className="px-3 py-2 text-sm bg-red-900/50 text-red-400 rounded hover:bg-red-900 transition-colors"
            >
              {t('bots.stopAll')} ({runningCount})
            </button>
          )}
          <button
            onClick={() => setShowBuilder(true)}
            className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded font-medium hover:bg-primary-700 transition-colors"
          >
            <Plus size={18} />
            {t('bots.newBot')}
          </button>
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="text-gray-400 text-center py-12">{t('common.loading')}</div>
      )}

      {/* Empty state */}
      {!loading && bots.length === 0 && (
        <div className="text-center py-16">
          <Activity className="mx-auto mb-4 text-gray-600" size={48} />
          <p className="text-gray-400">{t('bots.noBots')}</p>
        </div>
      )}

      {/* Bot Grid */}
      {!loading && bots.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {bots.map((bot) => (
            <div
              key={bot.bot_config_id}
              className={`rounded-lg border p-4 ${STATUS_BG[bot.status] || STATUS_BG.idle}`}
            >
              {/* Header row */}
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h3 className="text-white font-semibold text-lg">{bot.name}</h3>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-xs px-2 py-0.5 bg-gray-800 text-gray-300 rounded">
                      {bot.exchange_type}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      bot.mode === 'demo' ? 'bg-blue-900/50 text-blue-400' :
                      bot.mode === 'live' ? 'bg-orange-900/50 text-orange-400' :
                      'bg-purple-900/50 text-purple-400'
                    }`}>
                      {bot.mode}
                    </span>
                    <span className="text-xs text-gray-500">{bot.strategy_type}</span>
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  {bot.status === 'running' && (
                    <span className="relative flex h-2.5 w-2.5">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-green-500"></span>
                    </span>
                  )}
                  <span className={`text-sm font-medium ${STATUS_COLORS[bot.status] || 'text-gray-400'}`}>
                    {t(`bots.${bot.status}`)}
                  </span>
                </div>
              </div>

              {/* Pairs */}
              <div className="flex flex-wrap gap-1 mb-3">
                {bot.trading_pairs.map(pair => (
                  <span key={pair} className="text-xs px-1.5 py-0.5 bg-gray-800/80 text-gray-300 rounded">
                    {pair}
                  </span>
                ))}
              </div>

              {/* Stats row */}
              <div className="grid grid-cols-3 gap-2 mb-3 text-center">
                <div>
                  <div className="text-xs text-gray-500">{t('bots.totalPnl')}</div>
                  <div className={`text-sm font-mono ${bot.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    ${bot.total_pnl.toFixed(2)}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">{t('bots.trades')}</div>
                  <div className="text-sm text-white">{bot.total_trades}</div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">{t('bots.openTrades')}</div>
                  <div className="text-sm text-white">{bot.open_trades}</div>
                </div>
              </div>

              {/* Error message */}
              {bot.error_message && (
                <div className="flex items-center gap-1 mb-3 text-xs text-red-400">
                  <AlertCircle size={12} />
                  <span className="truncate">{bot.error_message}</span>
                </div>
              )}

              {/* Last analysis */}
              {bot.last_analysis && (
                <div className="flex items-center gap-1 mb-3 text-xs text-gray-500">
                  <Clock size={12} />
                  {t('bots.lastAnalysis')}: {new Date(bot.last_analysis).toLocaleTimeString()}
                </div>
              )}

              {/* Actions */}
              <div className="flex items-center gap-2 pt-2 border-t border-gray-700/50">
                {bot.status === 'running' ? (
                  <button
                    onClick={() => handleStop(bot.bot_config_id)}
                    disabled={actionLoading === bot.bot_config_id}
                    className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm bg-red-900/50 text-red-400 rounded hover:bg-red-900 disabled:opacity-50 transition-colors"
                  >
                    <Square size={14} />
                    {t('bots.stop')}
                  </button>
                ) : (
                  <button
                    onClick={() => handleStart(bot.bot_config_id)}
                    disabled={actionLoading === bot.bot_config_id}
                    className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm bg-green-900/50 text-green-400 rounded hover:bg-green-900 disabled:opacity-50 transition-colors"
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
                  onClick={() => setEditBotId(bot.bot_config_id)}
                  disabled={bot.status === 'running'}
                  className="p-1.5 text-gray-400 hover:text-white disabled:opacity-30 transition-colors"
                  title={t('bots.edit')}
                >
                  <Pencil size={14} />
                </button>
                <button
                  onClick={() => handleDelete(bot.bot_config_id, bot.name)}
                  disabled={bot.status === 'running'}
                  className="p-1.5 text-gray-400 hover:text-red-400 disabled:opacity-30 transition-colors"
                  title={t('bots.delete')}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
