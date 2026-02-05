import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../api/client'
import type { ConnectionsStatusResponse, ExchangeConnectionStatus, ExchangeInfo, ServiceStatus } from '../types'

const TABS = ['trading', 'strategy', 'apiKeys', 'llmKeys', 'discord', 'connections'] as const

/* ------------------------------------------------------------------ */
/*  Reusable API Key Section                                          */
/* ------------------------------------------------------------------ */

function ApiKeySection({
  title, configured, borderClass, badgeClass, badgeActiveClass,
  keyValue, secretValue, passphraseValue,
  onKeyChange, onSecretChange, onPassphraseChange,
  onSave, onTest, saving, t, showPassphrase,
}: {
  title: string
  configured: boolean
  borderClass: string
  badgeClass: string
  badgeActiveClass: string
  keyValue: string
  secretValue: string
  passphraseValue: string
  onKeyChange: (v: string) => void
  onSecretChange: (v: string) => void
  onPassphraseChange: (v: string) => void
  onSave: () => void
  onTest: () => void
  saving: boolean
  t: (key: string) => string
  showPassphrase?: boolean
}) {
  return (
    <div className={`border rounded-lg p-4 space-y-3 ${borderClass}`}>
      <div className="flex items-center justify-between">
        <h4 className="text-white text-sm font-medium">{title}</h4>
        <span className={`text-xs px-2 py-0.5 rounded-full ${configured ? badgeActiveClass : badgeClass}`}>
          {configured ? t('settings.configured') : t('settings.notConfigured')}
        </span>
      </div>
      <div>
        <label className="block text-xs text-gray-500 mb-1">API Key</label>
        <input type="password" value={keyValue} onChange={(e) => onKeyChange(e.target.value)}
          placeholder={configured ? '****configured****' : ''}
          className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-white text-sm" />
      </div>
      <div>
        <label className="block text-xs text-gray-500 mb-1">API Secret</label>
        <input type="password" value={secretValue} onChange={(e) => onSecretChange(e.target.value)}
          className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-white text-sm" />
      </div>
      {showPassphrase !== false && (
        <div>
          <label className="block text-xs text-gray-500 mb-1">Passphrase</label>
          <input type="password" value={passphraseValue} onChange={(e) => onPassphraseChange(e.target.value)}
            className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-white text-sm" />
        </div>
      )}
      <div className="flex gap-2">
        <button onClick={onSave} disabled={saving}
          className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50">
          {t('settings.save')}
        </button>
        <button onClick={onTest} disabled={!configured}
          className="px-3 py-1.5 text-sm bg-gray-700 text-white rounded hover:bg-gray-600 disabled:opacity-50">
          {t('settings.testConnection')}
        </button>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Connection Status Indicator                                       */
/* ------------------------------------------------------------------ */

function StatusDot({ reachable }: { reachable: boolean }) {
  return (
    <span className={`inline-block w-2.5 h-2.5 rounded-full ${reachable ? 'bg-green-400' : 'bg-red-400'}`} />
  )
}

/* ------------------------------------------------------------------ */
/*  Per-Exchange Key Form State                                       */
/* ------------------------------------------------------------------ */

interface ExchangeKeyForm {
  apiKey: string; apiSecret: string; passphrase: string
  demoApiKey: string; demoApiSecret: string; demoPassphrase: string
}

const emptyForm = (): ExchangeKeyForm => ({
  apiKey: '', apiSecret: '', passphrase: '',
  demoApiKey: '', demoApiSecret: '', demoPassphrase: '',
})

/* ------------------------------------------------------------------ */
/*  Main Settings Page                                                */
/* ------------------------------------------------------------------ */

export default function Settings() {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState<typeof TABS[number]>('trading')
  const [exchanges, setExchanges] = useState<ExchangeInfo[]>([])
  const [connections, setConnections] = useState<ExchangeConnectionStatus[]>([])
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  // Trading form
  const [leverage, setLeverage] = useState(4)
  const [positionSize, setPositionSize] = useState(7.5)
  const [maxTrades, setMaxTrades] = useState(3)
  const [takeProfit, setTakeProfit] = useState(4.0)
  const [stopLoss, setStopLoss] = useState(1.5)
  const [lossLimit, setLossLimit] = useState(5.0)
  const [demoMode, setDemoMode] = useState(true)

  // Per-exchange API key forms
  const [keyForms, setKeyForms] = useState<Record<string, ExchangeKeyForm>>({})

  // Discord form
  const [webhookUrl, setWebhookUrl] = useState('')

  // LLM connections
  const [llmConnections, setLlmConnections] = useState<{provider_type: string; api_key_configured: boolean; display_name: string; free_tier: boolean}[]>([])
  const [llmKeyForms, setLlmKeyForms] = useState<Record<string, string>>({})

  // Connections status
  const [connStatus, setConnStatus] = useState<ConnectionsStatusResponse | null>(null)
  const [connLoading, setConnLoading] = useState(false)

  useEffect(() => {
    const load = async () => {
      try {
        const [configRes, exchRes, connRes, llmRes] = await Promise.all([
          api.get('/config'),
          api.get('/exchanges'),
          api.get('/config/exchange-connections'),
          api.get('/config/llm-connections'),
        ])
        setExchanges(exchRes.data.exchanges)
        setConnections(connRes.data.connections || [])
        setLlmConnections(llmRes.data.connections || [])

        if (configRes.data.discord?.webhook_url) {
          setWebhookUrl(configRes.data.discord.webhook_url)
        }
        if (configRes.data.trading) {
          const tc = configRes.data.trading
          setLeverage(tc.leverage)
          setPositionSize(tc.position_size_percent)
          setMaxTrades(tc.max_trades_per_day)
          setTakeProfit(tc.take_profit_percent)
          setStopLoss(tc.stop_loss_percent)
          setLossLimit(tc.daily_loss_limit_percent)
          setDemoMode(tc.demo_mode)
        }
      } catch {
        setMessage(t('common.error'))
      }
    }
    load()
  }, [])

  const showMessage = (msg: string) => {
    setMessage(msg)
    setTimeout(() => setMessage(''), 3000)
  }

  const getForm = (ex: string): ExchangeKeyForm => keyForms[ex] || emptyForm()
  const updateForm = (ex: string, patch: Partial<ExchangeKeyForm>) =>
    setKeyForms((prev) => ({ ...prev, [ex]: { ...getForm(ex), ...patch } }))

  const getConn = (ex: string) => connections.find((c) => c.exchange_type === ex)

  // ── Save Handlers ──

  const saveTrading = async () => {
    setSaving(true)
    try {
      await api.put('/config/trading', {
        leverage, position_size_percent: positionSize,
        max_trades_per_day: maxTrades, take_profit_percent: takeProfit,
        stop_loss_percent: stopLoss, daily_loss_limit_percent: lossLimit,
        trading_pairs: ['BTCUSDT', 'ETHUSDT'], demo_mode: demoMode,
      })
      showMessage(t('settings.saved'))
    } catch { showMessage(t('common.error')) }
    setSaving(false)
  }

  const saveLiveKeys = async (exchangeType: string) => {
    const form = getForm(exchangeType)
    setSaving(true)
    try {
      await api.put(`/config/exchange-connections/${exchangeType}`, {
        api_key: form.apiKey, api_secret: form.apiSecret, passphrase: form.passphrase,
      })
      const res = await api.get('/config/exchange-connections')
      setConnections(res.data.connections || [])
      updateForm(exchangeType, { apiKey: '', apiSecret: '', passphrase: '' })
      showMessage(t('settings.saved'))
    } catch { showMessage(t('common.error')) }
    setSaving(false)
  }

  const saveDemoKeys = async (exchangeType: string) => {
    const form = getForm(exchangeType)
    setSaving(true)
    try {
      await api.put(`/config/exchange-connections/${exchangeType}`, {
        demo_api_key: form.demoApiKey, demo_api_secret: form.demoApiSecret, demo_passphrase: form.demoPassphrase,
      })
      const res = await api.get('/config/exchange-connections')
      setConnections(res.data.connections || [])
      updateForm(exchangeType, { demoApiKey: '', demoApiSecret: '', demoPassphrase: '' })
      showMessage(t('settings.saved'))
    } catch { showMessage(t('common.error')) }
    setSaving(false)
  }

  const testConnection = async (exchangeType: string, mode: 'live' | 'demo') => {
    try {
      const res = await api.post(`/config/exchange-connections/${exchangeType}/test?mode=${mode}`)
      const label = mode === 'demo' ? 'Demo' : 'Live'
      showMessage(`${label} ${exchangeType} connected! Balance: $${res.data.balance}`)
    } catch { showMessage('Connection failed') }
  }

  const saveDiscord = async () => {
    setSaving(true)
    try {
      await api.put('/config/discord', { webhook_url: webhookUrl })
      showMessage(t('settings.saved'))
    } catch { showMessage(t('common.error')) }
    setSaving(false)
  }

  const testWebhook = async () => {
    try {
      await api.post('/config/discord/test')
      showMessage('Test message sent!')
    } catch { showMessage('Failed to send test') }
  }

  const saveLlmKey = async (provider: string) => {
    const key = llmKeyForms[provider]
    if (!key) return
    setSaving(true)
    try {
      await api.put(`/config/llm-connections/${provider}`, { api_key: key })
      const res = await api.get('/config/llm-connections')
      setLlmConnections(res.data.connections || [])
      setLlmKeyForms(prev => ({ ...prev, [provider]: '' }))
      showMessage(t('settings.saved'))
    } catch { showMessage(t('common.error')) }
    setSaving(false)
  }

  const testLlmKey = async (provider: string) => {
    setSaving(true)
    try {
      const res = await api.post(`/config/llm-connections/${provider}/test`)
      showMessage(`${t('settings.connectionSuccess')}: ${res.data.display_name}`)
    } catch (err: any) {
      showMessage(err?.response?.data?.detail || t('common.error'))
    }
    setSaving(false)
  }

  const deleteLlmKey = async (provider: string) => {
    setSaving(true)
    try {
      await api.delete(`/config/llm-connections/${provider}`)
      const res = await api.get('/config/llm-connections')
      setLlmConnections(res.data.connections || [])
      showMessage(t('settings.saved'))
    } catch { showMessage(t('common.error')) }
    setSaving(false)
  }

  const loadConnectionStatus = async () => {
    setConnLoading(true)
    try {
      const res = await api.get('/config/connections')
      setConnStatus(res.data)
    } catch { showMessage(t('common.error')) }
    setConnLoading(false)
  }

  useEffect(() => {
    if (activeTab === 'connections' && !connStatus) {
      loadConnectionStatus()
    }
  }, [activeTab])

  const groupServices = (services: Record<string, ServiceStatus>) => {
    const groups: Record<string, [string, ServiceStatus][]> = {
      data_source: [], exchange: [], notification: [],
    }
    for (const [key, svc] of Object.entries(services)) {
      const group = groups[svc.type]
      if (group) group.push([key, svc])
    }
    return groups
  }

  const circuitLabel = (state: string) => {
    if (state === 'closed') return t('settings.circuitClosed')
    if (state === 'open') return t('settings.circuitOpen')
    return t('settings.circuitHalfOpen')
  }

  const circuitColor = (state: string) => {
    if (state === 'closed') return 'text-green-400'
    if (state === 'open') return 'text-red-400'
    return 'text-yellow-400'
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">{t('settings.title')}</h1>

      {message && (
        <div className="mb-4 p-3 bg-primary-900/30 border border-primary-800 rounded text-primary-400 text-sm">
          {message}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-gray-900 p-1 rounded-lg w-fit">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm rounded ${
              activeTab === tab
                ? 'bg-primary-600 text-white'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {t(`settings.${tab}`)}
          </button>
        ))}
      </div>

      {/* Trading Tab */}
      {activeTab === 'trading' && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 max-w-2xl">
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Leverage (1-20x)</label>
                <input type="number" value={leverage} onChange={(e) => setLeverage(Number(e.target.value))} min={1} max={20}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Position Size %</label>
                <input type="number" value={positionSize} onChange={(e) => setPositionSize(Number(e.target.value))} step={0.5}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Max Trades/Day</label>
                <input type="number" value={maxTrades} onChange={(e) => setMaxTrades(Number(e.target.value))} min={1} max={10}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Daily Loss Limit %</label>
                <input type="number" value={lossLimit} onChange={(e) => setLossLimit(Number(e.target.value))} step={0.5}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Take Profit %</label>
                <input type="number" value={takeProfit} onChange={(e) => setTakeProfit(Number(e.target.value))} step={0.5}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Stop Loss %</label>
                <input type="number" value={stopLoss} onChange={(e) => setStopLoss(Number(e.target.value))} step={0.5}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-300">
              <input type="checkbox" checked={demoMode} onChange={(e) => setDemoMode(e.target.checked)} className="rounded" />
              {t('bot.demoMode')}
            </label>
            <button onClick={saveTrading} disabled={saving}
              className="px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50">
              {t('settings.save')}
            </button>
          </div>
        </div>
      )}

      {/* API Keys Tab — Per-Exchange Cards */}
      {activeTab === 'apiKeys' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
          {exchanges.map((ex) => {
            const conn = getConn(ex.name)
            const form = getForm(ex.name)
            const showPass = ex.requires_passphrase

            return (
              <div key={ex.name} className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
                {/* Exchange header */}
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-white font-semibold">{ex.display_name}</h3>
                    <span className="text-xs text-gray-500">{ex.auth_type}</span>
                  </div>
                  {ex.supports_demo && <span className="text-xs text-green-500">Demo</span>}
                </div>

                {/* Live Keys */}
                <ApiKeySection
                  title={t('settings.liveApiKeys')}
                  configured={conn?.api_keys_configured ?? false}
                  borderClass="border-gray-700"
                  badgeClass="bg-gray-800 text-gray-500 border border-gray-700"
                  badgeActiveClass="bg-green-900/40 text-green-400 border border-green-800"
                  keyValue={form.apiKey} secretValue={form.apiSecret} passphraseValue={form.passphrase}
                  onKeyChange={(v) => updateForm(ex.name, { apiKey: v })}
                  onSecretChange={(v) => updateForm(ex.name, { apiSecret: v })}
                  onPassphraseChange={(v) => updateForm(ex.name, { passphrase: v })}
                  onSave={() => saveLiveKeys(ex.name)}
                  onTest={() => testConnection(ex.name, 'live')}
                  saving={saving} t={t} showPassphrase={showPass}
                />

                {/* Demo Keys */}
                {ex.supports_demo && (
                  <ApiKeySection
                    title={t('settings.demoApiKeys')}
                    configured={conn?.demo_api_keys_configured ?? false}
                    borderClass="border-yellow-800/50"
                    badgeClass="bg-gray-800 text-gray-500 border border-gray-700"
                    badgeActiveClass="bg-yellow-900/40 text-yellow-400 border border-yellow-800"
                    keyValue={form.demoApiKey} secretValue={form.demoApiSecret} passphraseValue={form.demoPassphrase}
                    onKeyChange={(v) => updateForm(ex.name, { demoApiKey: v })}
                    onSecretChange={(v) => updateForm(ex.name, { demoApiSecret: v })}
                    onPassphraseChange={(v) => updateForm(ex.name, { demoPassphrase: v })}
                    onSave={() => saveDemoKeys(ex.name)}
                    onTest={() => testConnection(ex.name, 'demo')}
                    saving={saving} t={t} showPassphrase={showPass}
                  />
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* LLM Keys Tab */}
      {activeTab === 'llmKeys' && (
        <div className="max-w-2xl">
          <p className="text-sm text-gray-400 mb-4">{t('settings.llmKeysDescription')}</p>
          <div className="space-y-3">
            {llmConnections.map(({ provider_type, api_key_configured, display_name, free_tier }) => (
              <div key={provider_type} className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <h4 className="text-white text-sm font-medium">{display_name}</h4>
                    {free_tier && <span className="text-xs px-1.5 py-0.5 rounded bg-green-900/40 text-green-400 border border-green-800">Free</span>}
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${api_key_configured ? 'bg-green-900/40 text-green-400 border border-green-800' : 'bg-gray-800 text-gray-500 border border-gray-700'}`}>
                    {api_key_configured ? t('settings.configured') : t('settings.notConfigured')}
                  </span>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">API Key</label>
                  <input
                    type="password"
                    value={llmKeyForms[provider_type] || ''}
                    onChange={(e) => setLlmKeyForms(prev => ({ ...prev, [provider_type]: e.target.value }))}
                    placeholder={api_key_configured ? '****configured****' : ''}
                    className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-white text-sm"
                  />
                </div>
                <div className="flex gap-2">
                  <button onClick={() => saveLlmKey(provider_type)} disabled={saving}
                    className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50">
                    {t('settings.save')}
                  </button>
                  <button onClick={() => testLlmKey(provider_type)} disabled={!api_key_configured || saving}
                    className="px-3 py-1.5 text-sm bg-gray-700 text-white rounded hover:bg-gray-600 disabled:opacity-50">
                    {t('settings.testConnection')}
                  </button>
                  {api_key_configured && (
                    <button onClick={() => deleteLlmKey(provider_type)} disabled={saving}
                      className="px-3 py-1.5 text-sm bg-red-900/50 text-red-400 rounded hover:bg-red-900 disabled:opacity-50">
                      {t('presets.delete')}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Discord Tab */}
      {activeTab === 'discord' && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 max-w-2xl">
          <div className="space-y-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Webhook URL</label>
              <input type="text" value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)}
                placeholder="https://discord.com/api/webhooks/..."
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
            </div>
            <div className="flex gap-2">
              <button onClick={saveDiscord} disabled={saving}
                className="px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50">
                {t('settings.save')}
              </button>
              <button onClick={testWebhook}
                className="px-4 py-2 bg-gray-700 text-white rounded hover:bg-gray-600">
                {t('settings.testWebhook')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Connections Tab */}
      {activeTab === 'connections' && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 max-w-2xl">
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <p className="text-sm text-gray-400">{t('settings.connectionsDesc')}</p>
              <button onClick={loadConnectionStatus} disabled={connLoading}
                className="px-3 py-1.5 text-sm bg-gray-800 text-gray-300 rounded hover:bg-gray-700 disabled:opacity-50">
                {connLoading ? t('settings.refreshing') : t('settings.refreshStatus')}
              </button>
            </div>

            {connStatus ? (() => {
              const groups = groupServices(connStatus.services)
              const sectionLabels: Record<string, string> = {
                data_source: t('settings.dataSources'),
                exchange: t('settings.exchangeApi'),
                notification: t('settings.notifications'),
              }
              return (
                <>
                  {(['data_source', 'exchange', 'notification'] as const).map((groupKey) => {
                    const items = groups[groupKey]
                    if (!items || items.length === 0) return null
                    return (
                      <div key={groupKey}>
                        <h3 className="text-sm font-medium text-gray-400 mb-3 uppercase tracking-wider">
                          {sectionLabels[groupKey]}
                        </h3>
                        <div className="space-y-2">
                          {items.map(([key, svc]) => (
                            <div key={key} className="flex items-center justify-between p-3 bg-gray-800 rounded-lg">
                              <div className="flex items-center gap-3">
                                <StatusDot reachable={svc.reachable} />
                                <span className="text-white text-sm">{svc.label}</span>
                              </div>
                              <div className="flex items-center gap-3 text-xs">
                                {svc.latency_ms != null && (
                                  <span className="text-gray-500">{svc.latency_ms}ms</span>
                                )}
                                <span className={svc.reachable ? 'text-green-400' : 'text-red-400'}>
                                  {svc.reachable ? t('settings.online') : t('settings.offline')}
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )
                  })}

                  {Object.keys(connStatus.circuit_breakers).length > 0 && (
                    <div>
                      <h3 className="text-sm font-medium text-gray-400 mb-3 uppercase tracking-wider">
                        {t('settings.circuitBreakers')}
                      </h3>
                      <div className="space-y-2">
                        {Object.entries(connStatus.circuit_breakers).map(([name, cb]) => (
                          <div key={name} className="flex items-center justify-between p-3 bg-gray-800 rounded-lg">
                            <div className="flex items-center gap-3">
                              <span className={`inline-block w-2.5 h-2.5 rounded-full ${
                                cb.state === 'closed' ? 'bg-green-400' :
                                cb.state === 'open' ? 'bg-red-400' : 'bg-yellow-400'
                              }`} />
                              <span className="text-white text-sm">{cb.name}</span>
                            </div>
                            <div className="flex items-center gap-4 text-xs">
                              <span className="text-gray-500">
                                {cb.stats.successful_calls}/{cb.stats.total_calls}
                              </span>
                              <span className={circuitColor(cb.state)}>
                                {circuitLabel(cb.state)}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )
            })() : (
              <div className="text-center text-gray-500 py-8">
                {connLoading ? t('settings.refreshing') : t('common.loading')}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Strategy Tab */}
      {activeTab === 'strategy' && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 max-w-2xl">
          <div className="text-gray-400 text-sm">
            {t('settings.strategyHint')}
          </div>
        </div>
      )}
    </div>
  )
}
