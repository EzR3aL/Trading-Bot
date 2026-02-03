import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useBotStore } from '../stores/botStore'
import api from '../api/client'
import type { ExchangeInfo, Preset } from '../types'

export default function BotControl() {
  const { t } = useTranslation()
  const { status, isLoading, fetchStatus, startBot, stopBot } = useBotStore()
  const [exchanges, setExchanges] = useState<ExchangeInfo[]>([])
  const [presets, setPresets] = useState<Preset[]>([])
  const [selectedExchange, setSelectedExchange] = useState('bitget')
  const [selectedPreset, setSelectedPreset] = useState<number | undefined>()
  const [demoMode, setDemoMode] = useState(true)

  useEffect(() => {
    fetchStatus()
    const load = async () => {
      try {
        const [exchRes, presetsRes] = await Promise.all([
          api.get('/exchanges'),
          api.get('/presets'),
        ])
        setExchanges(exchRes.data.exchanges)
        setPresets(presetsRes.data)
      } catch { /* ignore */ }
    }
    load()
  }, [fetchStatus])

  const handleStart = async () => {
    try {
      await startBot(selectedExchange, selectedPreset, demoMode)
    } catch { /* error handled in store */ }
  }

  const handleStop = async () => {
    try {
      await stopBot()
    } catch { /* error handled in store */ }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">{t('bot.title')}</h1>

      {/* Status card */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 mb-6 max-w-2xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">Status</h2>
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${
            status?.is_running
              ? 'bg-green-900/30 text-green-400 animate-pulse'
              : 'bg-gray-800 text-gray-400'
          }`}>
            {status?.is_running ? t('bot.running') : t('bot.stopped')}
          </span>
        </div>

        {status?.is_running && (
          <div className="space-y-2 text-sm mb-4">
            <div className="flex justify-between">
              <span className="text-gray-400">Exchange:</span>
              <span className="text-white">{status.exchange_type}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Mode:</span>
              <span className={status.demo_mode ? 'text-yellow-400' : 'text-red-400'}>
                {status.demo_mode ? t('bot.demoMode') : t('bot.liveMode')}
              </span>
            </div>
            {status.active_preset_name && (
              <div className="flex justify-between">
                <span className="text-gray-400">Preset:</span>
                <span className="text-white">{status.active_preset_name}</span>
              </div>
            )}
            {status.started_at && (
              <div className="flex justify-between">
                <span className="text-gray-400">Started:</span>
                <span className="text-gray-300">{new Date(status.started_at).toLocaleString()}</span>
              </div>
            )}
          </div>
        )}

        {status?.is_running ? (
          <button
            onClick={handleStop}
            disabled={isLoading}
            className="w-full py-3 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 disabled:opacity-50"
          >
            {t('bot.stop')}
          </button>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">{t('bot.selectExchange')}</label>
                <select
                  value={selectedExchange}
                  onChange={(e) => setSelectedExchange(e.target.value)}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white"
                >
                  {exchanges.map((ex) => (
                    <option key={ex.name} value={ex.name}>{ex.display_name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">{t('bot.selectPreset')}</label>
                <select
                  value={selectedPreset || ''}
                  onChange={(e) => setSelectedPreset(e.target.value ? Number(e.target.value) : undefined)}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white"
                >
                  <option value="">Default</option>
                  {presets.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={demoMode}
                onChange={(e) => setDemoMode(e.target.checked)}
                className="rounded"
              />
              <span className={demoMode ? 'text-yellow-400' : 'text-red-400'}>
                {demoMode ? t('bot.demoMode') : t('bot.liveMode')}
              </span>
            </label>
            {!demoMode && (
              <div className="p-3 bg-red-900/20 border border-red-800 rounded text-red-400 text-sm">
                LIVE MODE - Real money will be used for trading!
              </div>
            )}
            <button
              onClick={handleStart}
              disabled={isLoading}
              className="w-full py-3 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 disabled:opacity-50"
            >
              {t('bot.start')}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
