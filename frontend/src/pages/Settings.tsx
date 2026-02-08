import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown } from 'lucide-react'
import api from '../api/client'
import type { ConnectionsStatusResponse, ExchangeConnectionStatus, ExchangeInfo, ServiceStatus } from '../types'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'

const TABS = ['apiKeys', 'llmKeys', 'discord', 'connections'] as const

/* ------------------------------------------------------------------ */
/*  Inline Key Form (used inside accordion)                           */
/* ------------------------------------------------------------------ */

function KeyForm({
  label, configured, keyValue, secretValue, passphraseValue,
  onKeyChange, onSecretChange, onPassphraseChange,
  onSave, onTest, saving, t, showPassphrase, authType,
}: {
  label: string
  configured: boolean
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
  authType?: string
}) {
  const isWallet = authType === 'eth_wallet'
  const keyLabel = isWallet ? t('settings.walletAddress') : t('settings.apiKey')
  const secretLabel = isWallet ? t('settings.privateKey') : t('settings.apiSecret')
  const keyPlaceholder = configured ? '****configured****' : isWallet ? '0x... (Main Wallet)' : ''
  const secretPlaceholder = isWallet ? '0x... (API Wallet Key)' : ''

  // Inline validation for wallet addresses / private keys
  const addrRegex = /^0x[0-9a-fA-F]{40}$/
  const keyRegex = /^(0x)?[0-9a-fA-F]{64}$/
  const addrError = isWallet && keyValue && !addrRegex.test(keyValue)
    ? 'Must be 0x + 40 hex characters' : ''
  const pkError = isWallet && secretValue && !keyRegex.test(secretValue)
    ? 'Must be 64 hex characters (with or without 0x)' : ''

  const formId = label.toLowerCase().replace(/\s+/g, '-')

  return (
    <div className="space-y-3">
      <h4 className="text-xs font-medium text-gray-400 uppercase tracking-wider">{label}</h4>
      {isWallet && (
        <div className="p-2.5 bg-blue-900/20 border border-blue-800/40 rounded text-xs text-blue-300">
          {t('settings.hyperliquidHint')}
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label htmlFor={`${formId}-key`} className="block text-xs text-gray-500 mb-1">{keyLabel}</label>
          <input id={`${formId}-key`} type={isWallet ? 'text' : 'password'} value={keyValue} onChange={(e) => onKeyChange(e.target.value)}
            placeholder={keyPlaceholder}
            className={`w-full px-3 py-1.5 bg-gray-800 border rounded text-white text-sm font-mono ${addrError ? 'border-red-500' : 'border-gray-700'}`} />
          {addrError && <p className="text-xs text-red-400 mt-1">{addrError}</p>}
        </div>
        <div>
          <label htmlFor={`${formId}-secret`} className="block text-xs text-gray-500 mb-1">{secretLabel}</label>
          <input id={`${formId}-secret`} type="password" value={secretValue} onChange={(e) => onSecretChange(e.target.value)}
            placeholder={secretPlaceholder}
            className={`w-full px-3 py-1.5 bg-gray-800 border rounded text-white text-sm ${pkError ? 'border-red-500' : 'border-gray-700'}`} />
          {pkError && <p className="text-xs text-red-400 mt-1">{pkError}</p>}
        </div>
        {showPassphrase !== false && (
          <div>
            <label htmlFor={`${formId}-passphrase`} className="block text-xs text-gray-500 mb-1">Passphrase</label>
            <input id={`${formId}-passphrase`} type="password" value={passphraseValue} onChange={(e) => onPassphraseChange(e.target.value)}
              className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-white text-sm" />
          </div>
        )}
      </div>
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
  const [activeTab, setActiveTab] = useState<typeof TABS[number]>('apiKeys')
  const [exchanges, setExchanges] = useState<ExchangeInfo[]>([])
  const [connections, setConnections] = useState<ExchangeConnectionStatus[]>([])
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  // Per-exchange API key forms
  const [keyForms, setKeyForms] = useState<Record<string, ExchangeKeyForm>>({})

  // Discord form
  const [webhookUrl, setWebhookUrl] = useState('')

  // LLM connections
  const [llmConnections, setLlmConnections] = useState<{provider_type: string; api_key_configured: boolean; display_name: string; free_tier: boolean}[]>([])
  const [llmKeyForms, setLlmKeyForms] = useState<Record<string, string>>({})

  // Accordion state
  const [openExchange, setOpenExchange] = useState<string | null>(null)
  const [openLlm, setOpenLlm] = useState<string | null>(null)

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

      {/* API Keys Tab — Accordion */}
      {activeTab === 'apiKeys' && (
        <div className="max-w-2xl space-y-2">
          {exchanges.map((ex) => {
            const conn = getConn(ex.name)
            const form = getForm(ex.name)
            const showPass = ex.requires_passphrase
            const isOpen = openExchange === ex.name
            const liveOk = conn?.api_keys_configured ?? false
            const demoOk = conn?.demo_api_keys_configured ?? false

            return (
              <div key={ex.name} className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
                {/* Accordion Header */}
                <button
                  onClick={() => setOpenExchange(isOpen ? null : ex.name)}
                  className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-800/50 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <ExchangeIcon exchange={ex.name} size={20} />
                    <h3 className="text-white font-semibold">{ex.display_name}</h3>
                  </div>
                  <div className="flex items-center gap-2">
                    {liveOk && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-green-900/40 text-green-400 border border-green-800">
                        Live
                      </span>
                    )}
                    {demoOk && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-900/40 text-yellow-400 border border-yellow-800">
                        Demo
                      </span>
                    )}
                    {!liveOk && !demoOk && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-gray-800 text-gray-500 border border-gray-700">
                        {t('settings.notConfigured')}
                      </span>
                    )}
                    <ChevronDown size={16} className={`text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
                  </div>
                </button>

                {/* Accordion Content */}
                {isOpen && (
                  <div className="px-5 pb-5 pt-1 space-y-5 border-t border-gray-800">
                    <KeyForm
                      label={ex.auth_type === 'eth_wallet' ? 'Mainnet' : 'Live'}
                      configured={liveOk}
                      keyValue={form.apiKey} secretValue={form.apiSecret} passphraseValue={form.passphrase}
                      onKeyChange={(v) => updateForm(ex.name, { apiKey: v })}
                      onSecretChange={(v) => updateForm(ex.name, { apiSecret: v })}
                      onPassphraseChange={(v) => updateForm(ex.name, { passphrase: v })}
                      onSave={() => saveLiveKeys(ex.name)}
                      onTest={() => testConnection(ex.name, 'live')}
                      saving={saving} t={t} showPassphrase={showPass} authType={ex.auth_type}
                    />

                    {ex.supports_demo && (
                      <>
                        <div className="border-t border-gray-800" />
                        <KeyForm
                          label={ex.auth_type === 'eth_wallet' ? 'Testnet' : 'Demo'}
                          configured={demoOk}
                          keyValue={form.demoApiKey} secretValue={form.demoApiSecret} passphraseValue={form.demoPassphrase}
                          onKeyChange={(v) => updateForm(ex.name, { demoApiKey: v })}
                          onSecretChange={(v) => updateForm(ex.name, { demoApiSecret: v })}
                          onPassphraseChange={(v) => updateForm(ex.name, { demoPassphrase: v })}
                          onSave={() => saveDemoKeys(ex.name)}
                          onTest={() => testConnection(ex.name, 'demo')}
                          saving={saving} t={t} showPassphrase={showPass} authType={ex.auth_type}
                        />
                        {ex.auth_type === 'eth_wallet' && (
                          <div className="p-2.5 bg-amber-900/20 border border-amber-800/40 rounded text-xs text-amber-300">
                            {t('settings.hyperliquidTestnetNote')}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* LLM Keys Tab — Accordion */}
      {activeTab === 'llmKeys' && (
        <div className="max-w-2xl">
          <p className="text-sm text-gray-400 mb-4">{t('settings.llmKeysDescription')}</p>
          <div className="space-y-2">
            {llmConnections.map(({ provider_type, api_key_configured, display_name, free_tier }) => {
              const isOpen = openLlm === provider_type
              return (
                <div key={provider_type} className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
                  {/* Accordion Header */}
                  <button
                    onClick={() => setOpenLlm(isOpen ? null : provider_type)}
                    className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-800/50 transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <h4 className="text-white text-sm font-medium">{display_name}</h4>
                      {free_tier && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-blue-900/40 text-blue-400 border border-blue-800">Free</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${api_key_configured ? 'bg-green-900/40 text-green-400 border border-green-800' : 'bg-gray-800 text-gray-500 border border-gray-700'}`}>
                        {api_key_configured ? t('settings.configured') : t('settings.notConfigured')}
                      </span>
                      <ChevronDown size={16} className={`text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
                    </div>
                  </button>

                  {/* Accordion Content */}
                  {isOpen && (
                    <div className="px-5 pb-5 pt-1 space-y-3 border-t border-gray-800">
                      <div>
                        <label htmlFor={`llm-key-${provider_type}`} className="block text-xs text-gray-500 mb-1">{t('settings.apiKey')}</label>
                        <input
                          id={`llm-key-${provider_type}`}
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
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Discord Tab */}
      {activeTab === 'discord' && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 max-w-2xl">
          <div className="space-y-4">
            <div>
              <label htmlFor="discord-webhook-url" className="block text-sm text-gray-400 mb-1">Webhook URL</label>
              <input id="discord-webhook-url" type="text" value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)}
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

    </div>
  )
}
