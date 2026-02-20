import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Bell, Plus, Trash2, ToggleLeft, ToggleRight,
  TrendingUp, TrendingDown, Shield, X, Loader2, Clock,
} from 'lucide-react'
import api from '../api/client'
import type { Alert, AlertHistory, AlertCreate } from '../types'

/* ── Constants ────────────────────────────────────────────── */

const ALERT_TYPES = ['price', 'strategy', 'portfolio'] as const
type AlertTab = typeof ALERT_TYPES[number] | 'all'

const PRICE_CATEGORIES = ['price_above', 'price_below', 'price_change_percent']
const STRATEGY_CATEGORIES = ['signal_missed', 'low_confidence', 'consecutive_losses']
const PORTFOLIO_CATEGORIES = ['daily_loss', 'drawdown', 'profit_target']

function categoriesForType(type: 'price' | 'strategy' | 'portfolio'): string[] {
  switch (type) {
    case 'price': return PRICE_CATEGORIES
    case 'strategy': return STRATEGY_CATEGORIES
    case 'portfolio': return PORTFOLIO_CATEGORIES
  }
}

/* ── Main Component ───────────────────────────────────────── */

export default function Alerts() {
  const { t } = useTranslation()

  // Data state
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [history, setHistory] = useState<AlertHistory[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // UI state
  const [activeTab, setActiveTab] = useState<AlertTab>('all')
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [togglingId, setTogglingId] = useState<number | null>(null)

  // Create form state
  const [formType, setFormType] = useState<'price' | 'strategy' | 'portfolio'>('price')
  const [formCategory, setFormCategory] = useState('')
  const [formSymbol, setFormSymbol] = useState('')
  const [formThreshold, setFormThreshold] = useState<number>(0)
  const [formDirection, setFormDirection] = useState<'above' | 'below'>('above')
  const [formCooldown, setFormCooldown] = useState<number>(60)

  // WebSocket reference for real-time alert events
  const wsRef = useRef<WebSocket | null>(null)

  /* ── Data Fetching ──────────────────────────────────────── */

  const fetchAlerts = useCallback(async () => {
    try {
      const res = await api.get('/alerts')
      setAlerts(res.data.alerts || res.data || [])
    } catch {
      setError(t('common.error'))
    }
  }, [t])

  const fetchHistory = useCallback(async () => {
    try {
      const res = await api.get('/alerts/history?limit=20')
      setHistory(res.data.history || res.data || [])
    } catch {
      // History is non-critical; silently ignore
    }
  }, [])

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError('')
      await Promise.all([fetchAlerts(), fetchHistory()])
      setLoading(false)
    }
    load()
  }, [fetchAlerts, fetchHistory])

  /* ── WebSocket for live alert_triggered events ──────────── */

  useEffect(() => {
    const token = localStorage.getItem('access_token')
    if (!token) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/ws?token=${token}`

    try {
      const socket = new WebSocket(wsUrl)

      socket.onmessage = (event) => {
        if (event.data === 'pong') return
        try {
          const msg = JSON.parse(event.data) as { type: string; data: unknown }
          if (msg.type === 'alert_triggered') {
            const alertData = msg.data as AlertHistory
            setHistory((prev) => [alertData, ...prev].slice(0, 20))
          }
        } catch {
          // Ignore non-JSON messages
        }
      }

      socket.onopen = () => {
        // Keep alive
        const ping = setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) socket.send('ping')
        }, 30000)
        socket.addEventListener('close', () => clearInterval(ping))
      }

      wsRef.current = socket
    } catch {
      // WebSocket not available
    }

    return () => {
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [])

  /* ── Actions ────────────────────────────────────────────── */

  const handleCreate = async () => {
    if (!formCategory || formThreshold <= 0) return
    setCreating(true)
    try {
      const payload: AlertCreate = {
        alert_type: formType,
        category: formCategory,
        threshold: formThreshold,
      }
      if (formType === 'price') {
        payload.symbol = formSymbol || null
        payload.direction = formDirection
        payload.cooldown_minutes = formCooldown
      }
      await api.post('/alerts', payload)
      setShowCreate(false)
      resetForm()
      await fetchAlerts()
    } catch {
      setError(t('common.error'))
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id: number) => {
    setDeletingId(id)
    try {
      await api.delete(`/alerts/${id}`)
      setAlerts((prev) => prev.filter((a) => a.id !== id))
    } catch {
      setError(t('common.error'))
    } finally {
      setDeletingId(null)
    }
  }

  const handleToggle = async (id: number) => {
    setTogglingId(id)
    try {
      await api.patch(`/alerts/${id}/toggle`)
      setAlerts((prev) =>
        prev.map((a) => (a.id === id ? { ...a, is_enabled: !a.is_enabled } : a))
      )
    } catch {
      setError(t('common.error'))
    } finally {
      setTogglingId(null)
    }
  }

  const resetForm = () => {
    setFormType('price')
    setFormCategory('')
    setFormSymbol('')
    setFormThreshold(0)
    setFormDirection('above')
    setFormCooldown(60)
  }

  /* ── Derived Data ───────────────────────────────────────── */

  const filteredAlerts = activeTab === 'all'
    ? alerts
    : alerts.filter((a) => a.alert_type === activeTab)

  const activeCount = alerts.filter((a) => a.is_enabled).length

  /* ── Category Translation Helper ────────────────────────── */

  function categoryLabel(category: string): string {
    const keyMap: Record<string, string> = {
      price_above: 'alerts.priceAbove',
      price_below: 'alerts.priceBelow',
      price_change_percent: 'alerts.priceChangePercent',
      signal_missed: 'alerts.signalMissed',
      low_confidence: 'alerts.lowConfidence',
      consecutive_losses: 'alerts.consecutiveLosses',
      daily_loss: 'alerts.dailyLoss',
      drawdown: 'alerts.drawdown',
      profit_target: 'alerts.profitTarget',
    }
    return t(keyMap[category] || category)
  }

  function typeIcon(type: string) {
    switch (type) {
      case 'price': return <TrendingUp size={14} className="text-blue-400" />
      case 'strategy': return <Shield size={14} className="text-yellow-400" />
      case 'portfolio': return <TrendingDown size={14} className="text-purple-400" />
      default: return <Bell size={14} className="text-gray-400" />
    }
  }

  /* ── Loading State ──────────────────────────────────────── */

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  /* ── Render ─────────────────────────────────────────────── */

  return (
    <div className="animate-in">
      {/* Error */}
      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError('')} className="text-red-400 hover:text-red-300">
            <X size={16} />
          </button>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">{t('alerts.title')}</h1>
          <p className="text-sm text-gray-400 mt-1">{t('alerts.subtitle')}</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-xs text-gray-400">
            {t('alerts.activeAlerts')}: <span className="text-emerald-400 font-medium">{activeCount}</span>
          </div>
          <button
            onClick={() => { resetForm(); setShowCreate(true) }}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-primary-600 to-primary-500 text-white text-sm font-medium rounded-xl hover:from-primary-500 hover:to-primary-400 transition-all shadow-glow-sm"
          >
            <Plus size={16} />
            {t('alerts.newAlert')}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1.5 bg-white/5 rounded-xl p-0.5 border border-white/5 mb-6 w-fit">
        {(['all', ...ALERT_TYPES] as AlertTab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-xs font-medium rounded-lg transition-all duration-200 ${
              activeTab === tab
                ? 'bg-gradient-to-r from-primary-600 to-primary-500 text-white shadow-glow-sm'
                : 'text-gray-400 hover:text-white hover:bg-white/5'
            }`}
          >
            {tab === 'all' ? t('alerts.all') : t(`alerts.${tab}`)}
          </button>
        ))}
      </div>

      {/* Alert List */}
      <div className="space-y-3 mb-8">
        {filteredAlerts.length === 0 ? (
          <div className="glass-card rounded-2xl p-10 text-center">
            <Bell size={40} className="mx-auto text-gray-600 mb-3" />
            <p className="text-gray-400">{t('alerts.noAlerts')}</p>
          </div>
        ) : (
          filteredAlerts.map((alert) => (
            <div
              key={alert.id}
              className={`glass-card rounded-xl p-4 flex flex-col sm:flex-row items-start sm:items-center gap-3 transition-all duration-200 ${
                !alert.is_enabled ? 'opacity-50' : ''
              }`}
            >
              {/* Type icon + info */}
              <div className="flex items-center gap-3 flex-1 min-w-0">
                <div className="w-9 h-9 rounded-lg bg-white/5 flex items-center justify-center shrink-0">
                  {typeIcon(alert.alert_type)}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-white font-medium text-sm">
                      {categoryLabel(alert.category)}
                    </span>
                    {alert.symbol && (
                      <span className="text-xs px-2 py-0.5 bg-white/10 rounded-md text-gray-300 font-mono">
                        {alert.symbol}
                      </span>
                    )}
                    {alert.direction && (
                      <span className={`text-xs px-2 py-0.5 rounded-md ${
                        alert.direction === 'above'
                          ? 'bg-emerald-500/10 text-emerald-400'
                          : 'bg-red-500/10 text-red-400'
                      }`}>
                        {t(`alerts.${alert.direction}`)}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                    <span>{t('alerts.threshold')}: <span className="text-gray-300">{alert.threshold}</span></span>
                    <span>
                      {t('alerts.lastTriggered')}:{' '}
                      <span className="text-gray-300">
                        {alert.last_triggered_at
                          ? new Date(alert.last_triggered_at).toLocaleString()
                          : t('alerts.never')}
                      </span>
                    </span>
                    <span>{t('alerts.triggerCount')}: <span className="text-gray-300">{alert.trigger_count}</span></span>
                    {alert.cooldown_minutes > 0 && (
                      <span className="flex items-center gap-1">
                        <Clock size={10} />
                        {alert.cooldown_minutes}m
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Actions */}
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => handleToggle(alert.id)}
                  disabled={togglingId === alert.id}
                  className="p-1.5 rounded-lg hover:bg-white/5 transition-colors"
                  title={alert.is_enabled ? t('alerts.enabled') : t('alerts.disabled')}
                >
                  {togglingId === alert.id ? (
                    <Loader2 size={18} className="animate-spin text-gray-400" />
                  ) : alert.is_enabled ? (
                    <ToggleRight size={22} className="text-emerald-400" />
                  ) : (
                    <ToggleLeft size={22} className="text-gray-500" />
                  )}
                </button>
                <button
                  onClick={() => handleDelete(alert.id)}
                  disabled={deletingId === alert.id}
                  className="p-1.5 rounded-lg hover:bg-red-500/10 text-gray-400 hover:text-red-400 transition-colors"
                  title={t('alerts.delete')}
                >
                  {deletingId === alert.id ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Trash2 size={16} />
                  )}
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Create Alert Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="glass-card rounded-2xl p-6 w-full max-w-lg border border-white/10 animate-in">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold text-white">{t('alerts.create')}</h2>
              <button
                onClick={() => setShowCreate(false)}
                className="p-1.5 rounded-lg hover:bg-white/5 text-gray-400 hover:text-white transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Alert type selector */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
                {t('alerts.type')}
              </label>
              <div className="flex gap-2">
                {ALERT_TYPES.map((type) => (
                  <button
                    key={type}
                    onClick={() => {
                      setFormType(type)
                      setFormCategory('')
                    }}
                    className={`flex-1 px-3 py-2 text-sm rounded-xl transition-all ${
                      formType === type
                        ? 'bg-gradient-to-r from-primary-600 to-primary-500 text-white shadow-glow-sm'
                        : 'bg-white/5 text-gray-400 hover:text-white hover:bg-white/10 border border-white/5'
                    }`}
                  >
                    {t(`alerts.${type}`)}
                  </button>
                ))}
              </div>
            </div>

            {/* Category */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
                {t('alerts.category')}
              </label>
              <select
                value={formCategory}
                onChange={(e) => setFormCategory(e.target.value)}
                className="w-full px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-white text-sm focus:outline-none focus:border-primary-500 transition-colors"
              >
                <option value="" className="bg-[#0a0e17]">{t('alerts.selectCategory')}</option>
                {categoriesForType(formType).map((cat) => (
                  <option key={cat} value={cat} className="bg-[#0a0e17]">
                    {categoryLabel(cat)}
                  </option>
                ))}
              </select>
            </div>

            {/* Symbol (price type only) */}
            {formType === 'price' && (
              <div className="mb-4">
                <label className="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
                  {t('alerts.symbol')}
                </label>
                <input
                  type="text"
                  value={formSymbol}
                  onChange={(e) => setFormSymbol(e.target.value.toUpperCase())}
                  placeholder={t('alerts.selectSymbol')}
                  className="w-full px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-white text-sm placeholder-gray-500 focus:outline-none focus:border-primary-500 transition-colors"
                />
              </div>
            )}

            {/* Threshold */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
                {t('alerts.threshold')}
              </label>
              <input
                type="number"
                value={formThreshold || ''}
                onChange={(e) => setFormThreshold(Number(e.target.value))}
                step="any"
                min="0"
                className="w-full px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-white text-sm focus:outline-none focus:border-primary-500 transition-colors"
              />
            </div>

            {/* Direction (price type only) */}
            {formType === 'price' && (
              <div className="mb-4">
                <label className="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
                  {t('alerts.direction')}
                </label>
                <div className="flex gap-2">
                  {(['above', 'below'] as const).map((dir) => (
                    <button
                      key={dir}
                      onClick={() => setFormDirection(dir)}
                      className={`flex-1 px-3 py-2 text-sm rounded-xl transition-all ${
                        formDirection === dir
                          ? dir === 'above'
                            ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                            : 'bg-red-500/20 text-red-400 border border-red-500/30'
                          : 'bg-white/5 text-gray-400 hover:text-white border border-white/5'
                      }`}
                    >
                      {t(`alerts.${dir}`)}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Cooldown (price type only) */}
            {formType === 'price' && (
              <div className="mb-6">
                <label className="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
                  {t('alerts.cooldown')}
                </label>
                <input
                  type="number"
                  value={formCooldown}
                  onChange={(e) => setFormCooldown(Number(e.target.value))}
                  min="1"
                  className="w-full px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-white text-sm focus:outline-none focus:border-primary-500 transition-colors"
                />
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-3">
              <button
                onClick={() => setShowCreate(false)}
                className="flex-1 px-4 py-2.5 bg-white/5 text-gray-300 text-sm font-medium rounded-xl hover:bg-white/10 border border-white/5 transition-all"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleCreate}
                disabled={creating || !formCategory || formThreshold <= 0}
                className="flex-1 px-4 py-2.5 bg-gradient-to-r from-primary-600 to-primary-500 text-white text-sm font-medium rounded-xl hover:from-primary-500 hover:to-primary-400 transition-all shadow-glow-sm disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {creating && <Loader2 size={16} className="animate-spin" />}
                {t('alerts.create')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Alert History */}
      <div className="glass-card rounded-2xl overflow-hidden">
        <div className="p-5 border-b border-white/5">
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <Clock size={16} className="text-gray-400" />
            {t('alerts.historyTitle')}
          </h2>
        </div>
        {history.length === 0 ? (
          <div className="p-8 text-center text-gray-500">{t('alerts.noHistory')}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="table-premium">
              <thead>
                <tr>
                  <th className="text-left">{t('alerts.triggeredAt')}</th>
                  <th className="text-left">{t('alerts.message')}</th>
                  <th className="text-right">{t('alerts.value')}</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id}>
                    <td className="text-gray-300 text-sm whitespace-nowrap">
                      {new Date(h.triggered_at).toLocaleString()}
                    </td>
                    <td className="text-white text-sm">{h.message}</td>
                    <td className="text-right text-gray-300 text-sm font-mono">
                      {h.current_value !== null ? h.current_value.toFixed(2) : '--'}
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
