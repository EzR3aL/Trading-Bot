import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../api/client'
import type { Preset } from '../types'

export default function Presets() {
  const { t } = useTranslation()
  const [presets, setPresets] = useState<Preset[]>([])
  const [showForm, setShowForm] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [exchange, setExchange] = useState('bitget')
  const [leverage, setLeverage] = useState(4)
  const [positionSize, setPositionSize] = useState(7.5)
  const [stopLoss, setStopLoss] = useState(1.5)
  const [takeProfit, setTakeProfit] = useState(4.0)

  const loadPresets = async () => {
    try {
      const res = await api.get('/presets')
      setPresets(res.data)
    } catch { /* ignore */ }
  }

  useEffect(() => { loadPresets() }, [])

  const resetForm = () => {
    setName(''); setDescription(''); setExchange('bitget')
    setLeverage(4); setPositionSize(7.5); setStopLoss(1.5); setTakeProfit(4.0)
    setEditId(null); setShowForm(false)
  }

  const savePreset = async () => {
    const data = {
      name, description, exchange_type: exchange,
      trading_config: {
        leverage, position_size_percent: positionSize,
        take_profit_percent: takeProfit, stop_loss_percent: stopLoss,
        max_trades_per_day: 3, daily_loss_limit_percent: 5.0,
        trading_pairs: ['BTCUSDT', 'ETHUSDT'], demo_mode: true,
      },
      strategy_config: {
        fear_greed_extreme_fear: 20, fear_greed_extreme_greed: 80,
        long_short_crowded_longs: 2.5, long_short_crowded_shorts: 0.4,
        funding_rate_high: 0.0005, funding_rate_low: -0.0002,
        high_confidence_min: 85, low_confidence_min: 60,
      },
      trading_pairs: ['BTCUSDT', 'ETHUSDT'],
    }

    if (editId) {
      await api.put(`/presets/${editId}`, data)
    } else {
      await api.post('/presets', data)
    }
    resetForm()
    loadPresets()
  }

  const activate = async (id: number) => {
    await api.post(`/presets/${id}/activate`)
    loadPresets()
  }

  const duplicate = async (id: number) => {
    await api.post(`/presets/${id}/duplicate`)
    loadPresets()
  }

  const deletePreset = async (id: number) => {
    if (!confirm(t('presets.confirmDelete'))) return
    await api.delete(`/presets/${id}`)
    loadPresets()
  }

  const startEdit = (preset: Preset) => {
    setEditId(preset.id)
    setName(preset.name)
    setDescription(preset.description || '')
    setExchange(preset.exchange_type)
    if (preset.trading_config) {
      setLeverage(preset.trading_config.leverage)
      setPositionSize(preset.trading_config.position_size_percent)
      setTakeProfit(preset.trading_config.take_profit_percent)
      setStopLoss(preset.trading_config.stop_loss_percent)
    }
    setShowForm(true)
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">{t('presets.title')}</h1>
        <button
          onClick={() => { resetForm(); setShowForm(true) }}
          className="px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700"
        >
          + {t('presets.create')}
        </button>
      </div>

      {/* Preset form */}
      {showForm && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 mb-6 max-w-2xl">
          <h2 className="text-lg font-semibold text-white mb-4">
            {editId ? t('presets.edit') : t('presets.create')}
          </h2>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Name</label>
                <input type="text" value={name} onChange={(e) => setName(e.target.value)}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Exchange</label>
                <select value={exchange} onChange={(e) => setExchange(e.target.value)}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white">
                  <option value="bitget">Bitget</option>
                  <option value="weex">Weex</option>
                  <option value="hyperliquid">Hyperliquid</option>
                </select>
              </div>
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Description</label>
              <input type="text" value={description} onChange={(e) => setDescription(e.target.value)}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
            </div>
            <div className="grid grid-cols-4 gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Leverage</label>
                <input type="number" value={leverage} onChange={(e) => setLeverage(Number(e.target.value))} min={1} max={20}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Position %</label>
                <input type="number" value={positionSize} onChange={(e) => setPositionSize(Number(e.target.value))} step={0.5}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">TP %</label>
                <input type="number" value={takeProfit} onChange={(e) => setTakeProfit(Number(e.target.value))} step={0.5}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">SL %</label>
                <input type="number" value={stopLoss} onChange={(e) => setStopLoss(Number(e.target.value))} step={0.5}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white" />
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={savePreset}
                className="px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700">
                {t('settings.save')}
              </button>
              <button onClick={resetForm}
                className="px-4 py-2 bg-gray-700 text-gray-300 rounded hover:bg-gray-600">
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Preset cards */}
      <div className="space-y-3">
        {presets.map((preset) => (
          <div key={preset.id}
            className={`bg-gray-900 border rounded-lg p-4 ${
              preset.is_active ? 'border-primary-500' : 'border-gray-800'
            }`}
          >
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-white font-medium">{preset.name}</span>
                  <span className="text-xs text-gray-400 bg-gray-800 px-2 py-0.5 rounded">
                    {preset.exchange_type}
                  </span>
                  {preset.is_active && (
                    <span className="text-xs text-primary-400 bg-primary-900/30 px-2 py-0.5 rounded font-medium">
                      {t('presets.active')}
                    </span>
                  )}
                </div>
                {preset.trading_config && (
                  <div className="text-sm text-gray-400 mt-1">
                    {preset.trading_config.leverage}x Hebel |{' '}
                    {preset.trading_config.position_size_percent}% Position |{' '}
                    {preset.trading_config.stop_loss_percent}% SL
                  </div>
                )}
                {preset.description && (
                  <div className="text-xs text-gray-500 mt-1">{preset.description}</div>
                )}
              </div>
              <div className="flex gap-2">
                {!preset.is_active && (
                  <button onClick={() => activate(preset.id)}
                    className="px-3 py-1.5 text-sm bg-primary-600/20 text-primary-400 rounded hover:bg-primary-600/30">
                    {t('presets.activate')}
                  </button>
                )}
                <button onClick={() => startEdit(preset)}
                  className="px-3 py-1.5 text-sm bg-gray-800 text-gray-300 rounded hover:bg-gray-700">
                  {t('presets.edit')}
                </button>
                <button onClick={() => duplicate(preset.id)}
                  className="px-3 py-1.5 text-sm bg-gray-800 text-gray-300 rounded hover:bg-gray-700">
                  {t('presets.duplicate')}
                </button>
                <button onClick={() => deletePreset(preset.id)}
                  className="px-3 py-1.5 text-sm bg-red-900/20 text-red-400 rounded hover:bg-red-900/30">
                  {t('presets.delete')}
                </button>
              </div>
            </div>
          </div>
        ))}

        {presets.length === 0 && (
          <div className="text-center text-gray-500 py-12">
            No presets yet. Create your first one!
          </div>
        )}
      </div>
    </div>
  )
}
