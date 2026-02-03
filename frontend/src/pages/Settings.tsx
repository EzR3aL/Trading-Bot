import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../api/client'
import type { ConfigResponse, ExchangeInfo } from '../types'

const TABS = ['trading', 'strategy', 'apiKeys', 'discord', 'exchange'] as const

export default function Settings() {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState<typeof TABS[number]>('trading')
  const [config, setConfig] = useState<ConfigResponse | null>(null)
  const [exchanges, setExchanges] = useState<ExchangeInfo[]>([])
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

  // API Keys form
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [passphrase, setPassphrase] = useState('')
  const [selectedExchange, setSelectedExchange] = useState('bitget')

  // Discord form
  const [webhookUrl, setWebhookUrl] = useState('')

  useEffect(() => {
    const load = async () => {
      try {
        const [configRes, exchRes] = await Promise.all([
          api.get('/config'),
          api.get('/exchanges'),
        ])
        setConfig(configRes.data)
        setExchanges(exchRes.data.exchanges)
        setSelectedExchange(configRes.data.exchange_type)

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
      } catch { /* ignore */ }
    }
    load()
  }, [])

  const showMessage = (msg: string) => {
    setMessage(msg)
    setTimeout(() => setMessage(''), 3000)
  }

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

  const saveApiKeys = async () => {
    setSaving(true)
    try {
      await api.put('/config/api-keys', {
        exchange_type: selectedExchange,
        api_key: apiKey, api_secret: apiSecret, passphrase,
        demo_api_key: '', demo_api_secret: '', demo_passphrase: '',
      })
      showMessage(t('settings.saved'))
      setApiKey(''); setApiSecret(''); setPassphrase('')
    } catch { showMessage(t('common.error')) }
    setSaving(false)
  }

  const testConnection = async () => {
    try {
      const res = await api.post('/config/api-keys/test')
      showMessage(`Connected! Balance: $${res.data.balance}`)
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

      <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 max-w-2xl">
        {activeTab === 'trading' && (
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
              Demo Mode
            </label>
            <button onClick={saveTrading} disabled={saving}
              className="px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50">
              {t('settings.save')}
            </button>
          </div>
        )}

        {activeTab === 'apiKeys' && (
          <div className="space-y-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Exchange</label>
              <select value={selectedExchange} onChange={(e) => setSelectedExchange(e.target.value)}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white">
                {exchanges.map((ex) => (
                  <option key={ex.name} value={ex.name}>{ex.display_name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">API Key</label>
              <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                placeholder={config?.api_keys_configured ? '****configured****' : ''}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">API Secret</label>
              <input type="password" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Passphrase</label>
              <input type="password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
            </div>
            <div className="flex gap-2">
              <button onClick={saveApiKeys} disabled={saving}
                className="px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50">
                {t('settings.save')}
              </button>
              <button onClick={testConnection}
                className="px-4 py-2 bg-gray-700 text-white rounded hover:bg-gray-600">
                {t('settings.testConnection')}
              </button>
            </div>
          </div>
        )}

        {activeTab === 'discord' && (
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
        )}

        {activeTab === 'strategy' && (
          <div className="text-gray-400 text-sm">
            Strategy settings are configured per preset. Go to Presets to edit.
          </div>
        )}

        {activeTab === 'exchange' && (
          <div className="space-y-4">
            <p className="text-sm text-gray-400">Active exchange: <span className="text-white font-medium">{config?.exchange_type || 'bitget'}</span></p>
            <div className="grid grid-cols-3 gap-3">
              {exchanges.map((ex) => (
                <button
                  key={ex.name}
                  onClick={async () => {
                    await api.put('/config/exchange', { exchange_type: ex.name })
                    setConfig((c) => c ? { ...c, exchange_type: ex.name } : c)
                    setSelectedExchange(ex.name)
                    showMessage(`Exchange set to ${ex.display_name}`)
                  }}
                  className={`p-4 rounded-lg border text-left ${
                    config?.exchange_type === ex.name
                      ? 'border-primary-500 bg-primary-900/20'
                      : 'border-gray-700 bg-gray-800 hover:border-gray-600'
                  }`}
                >
                  <div className="font-medium text-white">{ex.display_name}</div>
                  <div className="text-xs text-gray-400 mt-1">{ex.auth_type}</div>
                  {ex.supports_demo && <div className="text-xs text-green-400 mt-1">Demo available</div>}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
