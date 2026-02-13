import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { LayoutGrid, List, Pencil, Copy, Trash2, Zap, CheckCircle } from 'lucide-react'
import api from '../api/client'
import type { Preset } from '../types'

export default function Presets() {
  const { t } = useTranslation()
  const [presets, setPresets] = useState<Preset[]>([])
  const [showForm, setShowForm] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [leverage, setLeverage] = useState(4)
  const [positionSize, setPositionSize] = useState(7.5)
  const [stopLoss, setStopLoss] = useState(1.5)
  const [takeProfit, setTakeProfit] = useState(4.0)
  const [view, setView] = useState<'grid' | 'list'>('grid')

  const loadPresets = async () => {
    try {
      const res = await api.get('/presets')
      setPresets(res.data)
    } catch { /* ignore */ }
  }

  useEffect(() => { loadPresets() }, [])

  const resetForm = () => {
    setName(''); setDescription('')
    setLeverage(4); setPositionSize(7.5); setStopLoss(1.5); setTakeProfit(4.0)
    setEditId(null); setShowForm(false)
  }

  const savePreset = async () => {
    const data = {
      name, description, exchange_type: 'any',
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
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-2xl font-bold text-white">{t('presets.title')}</h1>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-white/10 overflow-hidden">
            <button
              onClick={() => setView('grid')}
              className={`p-1.5 transition-colors ${view === 'grid' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
            >
              <LayoutGrid size={15} />
            </button>
            <button
              onClick={() => setView('list')}
              className={`p-1.5 transition-colors ${view === 'list' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
            >
              <List size={15} />
            </button>
          </div>
          <button
            onClick={() => { resetForm(); setShowForm(true) }}
            className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
          >
            + {t('presets.create')}
          </button>
        </div>
      </div>

      {/* Preset form */}
      {showForm && (
        <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5 mb-5 max-w-2xl">
          <h2 className="text-sm font-semibold text-white mb-3">
            {editId ? t('presets.edit') : t('presets.create')}
          </h2>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">{t('presets.name')}</label>
                <input type="text" value={name} onChange={(e) => setName(e.target.value)}
                  className="filter-select w-full text-sm" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">{t('presets.description')}</label>
                <input type="text" value={description} onChange={(e) => setDescription(e.target.value)}
                  className="filter-select w-full text-sm" />
              </div>
            </div>
            <div className="grid grid-cols-4 gap-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">{t('presets.leverage')}</label>
                <input type="number" value={leverage} onChange={(e) => setLeverage(Number(e.target.value))} min={1} max={20}
                  className="filter-select w-full text-sm" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">{t('presets.positionPercent')}</label>
                <input type="number" value={positionSize} onChange={(e) => setPositionSize(Number(e.target.value))} step={0.5}
                  className="filter-select w-full text-sm" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">{t('presets.tpPercent')}</label>
                <input type="number" value={takeProfit} onChange={(e) => setTakeProfit(Number(e.target.value))} step={0.5}
                  className="filter-select w-full text-sm" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">{t('presets.slPercent')}</label>
                <input type="number" value={stopLoss} onChange={(e) => setStopLoss(Number(e.target.value))} step={0.5}
                  className="filter-select w-full text-sm" />
              </div>
            </div>
            <div className="flex gap-2 pt-1">
              <button onClick={savePreset}
                className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors">
                {t('settings.save')}
              </button>
              <button onClick={resetForm}
                className="px-3 py-1.5 text-sm bg-white/5 border border-white/10 text-gray-300 rounded-lg hover:bg-white/10 transition-colors">
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Preset cards */}
      {view === 'grid' ? (
        <div className="grid grid-cols-2 xl:grid-cols-3 gap-2.5">
          {presets.map((preset) => (
            <div key={preset.id}
              className={`border bg-white/[0.03] rounded-xl px-3.5 py-3 hover:bg-white/[0.05] transition-colors ${
                preset.is_active ? 'border-primary-500 ring-1 ring-primary-500/30' : 'border-white/10'
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm font-medium text-white truncate">{preset.name}</span>
                {preset.is_active && (
                  <CheckCircle size={13} className="flex-shrink-0 text-primary-400" />
                )}
              </div>
              {preset.trading_config && (
                <div className="text-xs text-gray-400 mb-1">
                  {preset.trading_config.leverage}x | {preset.trading_config.position_size_percent}% | SL {preset.trading_config.stop_loss_percent}% | TP {preset.trading_config.take_profit_percent}%
                </div>
              )}
              {preset.description && (
                <div className="text-xs text-gray-500 truncate mb-2">{preset.description}</div>
              )}
              <div className="flex gap-1.5 pt-1.5 border-t border-white/5">
                {!preset.is_active && (
                  <button onClick={() => activate(preset.id)}
                    className="flex items-center gap-1 px-2 py-1 text-[11px] bg-primary-600/20 text-primary-400 rounded-md hover:bg-primary-600/30 transition-colors">
                    <Zap size={11} />
                    {t('presets.activate')}
                  </button>
                )}
                <button onClick={() => startEdit(preset)}
                  className="flex items-center gap-1 px-2 py-1 text-[11px] bg-white/5 text-gray-400 rounded-md hover:bg-white/10 hover:text-gray-300 transition-colors">
                  <Pencil size={11} />
                </button>
                <button onClick={() => duplicate(preset.id)}
                  className="flex items-center gap-1 px-2 py-1 text-[11px] bg-white/5 text-gray-400 rounded-md hover:bg-white/10 hover:text-gray-300 transition-colors">
                  <Copy size={11} />
                </button>
                <button onClick={() => deletePreset(preset.id)}
                  className="flex items-center gap-1 px-2 py-1 text-[11px] bg-red-900/20 text-red-400/70 rounded-md hover:bg-red-900/30 hover:text-red-400 transition-colors ml-auto">
                  <Trash2 size={11} />
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-1.5">
          {presets.map((preset) => (
            <div key={preset.id}
              className={`border bg-white/[0.03] rounded-lg flex items-center gap-3 px-3 py-2 hover:bg-white/[0.05] transition-colors ${
                preset.is_active ? 'border-primary-500 ring-1 ring-primary-500/30' : 'border-white/10'
              }`}
            >
              {preset.is_active && (
                <CheckCircle size={14} className="flex-shrink-0 text-primary-400" />
              )}
              <span className="text-sm font-medium text-white whitespace-nowrap">{preset.name}</span>
              {preset.trading_config && (
                <span className="text-xs text-gray-500 whitespace-nowrap">
                  {preset.trading_config.leverage}x | {preset.trading_config.position_size_percent}% | SL {preset.trading_config.stop_loss_percent}%
                </span>
              )}
              {preset.description && (
                <span className="text-xs text-gray-600 truncate hidden lg:block">{preset.description}</span>
              )}
              <div className="flex gap-1.5 ml-auto flex-shrink-0">
                {!preset.is_active && (
                  <button onClick={() => activate(preset.id)}
                    className="flex items-center gap-1 px-2 py-1 text-[11px] bg-primary-600/20 text-primary-400 rounded-md hover:bg-primary-600/30 transition-colors">
                    <Zap size={11} />
                  </button>
                )}
                <button onClick={() => startEdit(preset)}
                  className="p-1 text-gray-500 hover:text-gray-300 transition-colors">
                  <Pencil size={13} />
                </button>
                <button onClick={() => duplicate(preset.id)}
                  className="p-1 text-gray-500 hover:text-gray-300 transition-colors">
                  <Copy size={13} />
                </button>
                <button onClick={() => deletePreset(preset.id)}
                  className="p-1 text-red-400/50 hover:text-red-400 transition-colors">
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {presets.length === 0 && (
        <div className="text-center text-gray-500 py-12 text-sm">
          {t('presets.noPresets')}
        </div>
      )}
    </div>
  )
}
