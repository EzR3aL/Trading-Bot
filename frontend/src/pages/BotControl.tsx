import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useBotStore } from '../stores/botStore'
import api from '../api/client'
import type { ExchangeConnectionStatus, ExchangeInfo, Preset } from '../types'

export default function BotControl() {
  const { t } = useTranslation()
  const { statuses, isLoading, fetchStatus, startBot, stopBot, stopAll } = useBotStore()
  const [exchanges, setExchanges] = useState<ExchangeInfo[]>([])
  const [presets, setPresets] = useState<Preset[]>([])
  const [connections, setConnections] = useState<ExchangeConnectionStatus[]>([])
  // Per-exchange form state: { [exchangeType]: { preset, demoMode } }
  const [formState, setFormState] = useState<Record<string, { preset?: number; demoMode: boolean }>>({})

  useEffect(() => {
    fetchStatus()
    const load = async () => {
      try {
        const [exchRes, presetsRes, connRes] = await Promise.all([
          api.get('/exchanges'),
          api.get('/presets'),
          api.get('/config/exchange-connections'),
        ])
        setExchanges(exchRes.data.exchanges)
        setPresets(presetsRes.data)
        setConnections(connRes.data.connections || [])
      } catch { /* ignore */ }
    }
    load()
  }, [fetchStatus])

  const getStatus = (exchangeType: string) =>
    statuses.find((s) => s.exchange_type === exchangeType && s.is_running)

  const getConnection = (exchangeType: string) =>
    connections.find((c) => c.exchange_type === exchangeType)

  const hasKeys = (exchangeType: string) => {
    const conn = getConnection(exchangeType)
    return conn && (conn.api_keys_configured || conn.demo_api_keys_configured)
  }

  const getForm = (ex: string) => formState[ex] || { demoMode: true }
  const setForm = (ex: string, patch: Partial<{ preset?: number; demoMode: boolean }>) =>
    setFormState((prev) => ({ ...prev, [ex]: { ...getForm(ex), ...patch } }))

  const handleStart = async (exchangeType: string) => {
    const form = getForm(exchangeType)
    try {
      await startBot(exchangeType, form.preset, form.demoMode)
      // Refresh connections too
      const connRes = await api.get('/config/exchange-connections')
      setConnections(connRes.data.connections || [])
    } catch { /* error handled in store */ }
  }

  const handleStop = async (exchangeType: string) => {
    try {
      await stopBot(exchangeType)
    } catch { /* error handled in store */ }
  }

  const runningCount = statuses.filter((s) => s.is_running).length

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">{t('bot.title')}</h1>
        {runningCount > 1 && (
          <button
            onClick={() => stopAll().catch(() => {})}
            disabled={isLoading}
            className="px-4 py-2 bg-red-900/50 text-red-400 border border-red-800 rounded-lg text-sm hover:bg-red-900 disabled:opacity-50"
          >
            {t('bot.stopAll')}
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {exchanges.map((ex) => {
          const running = getStatus(ex.name)
          const keysConfigured = hasKeys(ex.name)
          const conn = getConnection(ex.name)
          const form = getForm(ex.name)
          const exchangePresets = presets.filter((p) => p.exchange_type === ex.name)

          return (
            <div key={ex.name} className={`bg-gray-900 border rounded-lg p-5 ${
              running ? 'border-green-800' : keysConfigured ? 'border-gray-800' : 'border-gray-800/50 opacity-70'
            }`}>
              {/* Header */}
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-white font-semibold">{ex.display_name}</h3>
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${
                  running
                    ? 'bg-green-900/30 text-green-400 animate-pulse'
                    : 'bg-gray-800 text-gray-500'
                }`}>
                  {running ? t('bot.running') : t('bot.stopped')}
                </span>
              </div>

              {/* Running state */}
              {running && (
                <>
                  <div className="space-y-1.5 text-sm mb-4">
                    <div className="flex justify-between">
                      <span className="text-gray-400">Mode:</span>
                      <span className={running.demo_mode ? 'text-yellow-400' : 'text-red-400'}>
                        {running.demo_mode ? t('bot.demoMode') : t('bot.liveMode')}
                      </span>
                    </div>
                    {running.active_preset_name && (
                      <div className="flex justify-between">
                        <span className="text-gray-400">Preset:</span>
                        <span className="text-white">{running.active_preset_name}</span>
                      </div>
                    )}
                    {running.started_at && (
                      <div className="flex justify-between">
                        <span className="text-gray-400">Started:</span>
                        <span className="text-gray-300 text-xs">{new Date(running.started_at).toLocaleString()}</span>
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => handleStop(ex.name)}
                    disabled={isLoading}
                    className="w-full py-2.5 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50"
                  >
                    {t('bot.stop')}
                  </button>
                </>
              )}

              {/* Stopped with keys → Start form */}
              {!running && keysConfigured && (
                <div className="space-y-3">
                  {/* Key status badges */}
                  <div className="flex gap-2 text-xs">
                    {conn?.api_keys_configured && (
                      <span className="px-2 py-0.5 rounded bg-green-900/30 text-green-400 border border-green-800">Live</span>
                    )}
                    {conn?.demo_api_keys_configured && (
                      <span className="px-2 py-0.5 rounded bg-yellow-900/30 text-yellow-400 border border-yellow-800">Demo</span>
                    )}
                  </div>

                  {exchangePresets.length > 0 && (
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">{t('bot.selectPreset')}</label>
                      <select
                        value={form.preset || ''}
                        onChange={(e) => setForm(ex.name, { preset: e.target.value ? Number(e.target.value) : undefined })}
                        className="w-full px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-white text-sm"
                      >
                        <option value="">Default</option>
                        {exchangePresets.map((p) => (
                          <option key={p.id} value={p.id}>{p.name}</option>
                        ))}
                      </select>
                    </div>
                  )}

                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={form.demoMode}
                      onChange={(e) => setForm(ex.name, { demoMode: e.target.checked })}
                      className="rounded"
                    />
                    <span className={form.demoMode ? 'text-yellow-400' : 'text-red-400'}>
                      {form.demoMode ? t('bot.demoMode') : t('bot.liveMode')}
                    </span>
                  </label>

                  {!form.demoMode && (
                    <div className="p-2 bg-red-900/20 border border-red-800 rounded text-red-400 text-xs">
                      LIVE MODE - Real money!
                    </div>
                  )}

                  <button
                    onClick={() => handleStart(ex.name)}
                    disabled={isLoading}
                    className="w-full py-2.5 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50"
                  >
                    {t('bot.start')}
                  </button>
                </div>
              )}

              {/* No keys configured */}
              {!running && !keysConfigured && (
                <div className="text-center py-4">
                  <p className="text-gray-500 text-sm mb-3">{t('bot.noKeysConfigured')}</p>
                  <a href="/settings" className="text-primary-400 text-sm hover:underline">
                    {t('bot.configureKeys')}
                  </a>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
