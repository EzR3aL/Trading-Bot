import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { LayoutGrid, List, Pencil, Copy, Trash2, ArrowLeft } from 'lucide-react'
import api from '../api/client'
import { getApiErrorMessage } from '../utils/api-error'
import { useToastStore } from '../stores/toastStore'
import NumInput from '../components/ui/NumInput'
import type { Preset } from '../types'

type PerAssetCfg = Record<string, { position_usdt?: number; leverage?: number; tp?: number; sl?: number; max_trades?: number; loss_limit?: number }>

const PAIRS_CEX = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'AVAXUSDT']

export default function Presets() {
  const { t } = useTranslation()
  const b = t('bots.builder', { returnObjects: true }) as Record<string, string>
  const [presets, setPresets] = useState<Preset[]>([])
  const [showForm, setShowForm] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [view, setView] = useState<'grid' | 'list'>('grid')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  // Form state
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [tradingPairs, setTradingPairs] = useState<string[]>(['BTCUSDT'])
  const [perAssetConfig, setPerAssetConfig] = useState<PerAssetCfg>({})

  const loadPresets = async () => {
    try {
      const res = await api.get('/presets')
      setPresets(res.data)
    } catch (err) { console.error('Failed to load presets:', err); useToastStore.getState().addToast('error', t('common.loadError', 'Failed to load data')) }
  }

  useEffect(() => { loadPresets() }, [])

  const resetForm = () => {
    setName('')
    setDescription('')
    setTradingPairs(['BTCUSDT'])
    setPerAssetConfig({})
    setEditId(null)
    setShowForm(false)
  }

  const togglePair = (pair: string) => {
    setTradingPairs(prev =>
      prev.includes(pair) ? prev.filter(p => p !== pair) : [...prev, pair]
    )
  }

  const savePreset = async () => {
    // Build per_asset_config (filter out empty entries)
    const filteredPerAsset: Record<string, Record<string, number>> = {}
    for (const [symbol, cfg] of Object.entries(perAssetConfig)) {
      const clean: Record<string, number> = {}
      if (cfg.position_usdt != null && cfg.position_usdt > 0) clean.position_usdt = cfg.position_usdt
      if (cfg.leverage != null && cfg.leverage > 0) clean.leverage = cfg.leverage
      if (cfg.tp != null && cfg.tp > 0) clean.tp = cfg.tp
      if (cfg.sl != null && cfg.sl > 0) clean.sl = cfg.sl
      if (cfg.max_trades != null && cfg.max_trades > 0) clean.max_trades = cfg.max_trades
      if (cfg.loss_limit != null && cfg.loss_limit > 0) clean.loss_limit = cfg.loss_limit
      if (Object.keys(clean).length > 0) filteredPerAsset[symbol] = clean
    }

    const data = {
      name,
      description: description || undefined,
      exchange_type: 'any',
      trading_config: {
        per_asset_config: Object.keys(filteredPerAsset).length > 0 ? filteredPerAsset : undefined,
      },
      trading_pairs: tradingPairs,
    }

    try {
      setError('')
      setSaving(true)
      const res = editId
        ? await api.put(`/presets/${editId}`, data)
        : await api.post('/presets', data)

      // Optimistic update — avoids a second HTTP roundtrip
      if (editId) {
        setPresets(prev => prev.map(p => p.id === editId ? res.data : p))
      } else {
        setPresets(prev => [...prev, res.data])
      }
      resetForm()
    } catch (err) {
      const detail = (err as any)?.response?.data?.detail
      const msg = typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : getApiErrorMessage(err, t('common.saveFailed'))
      setError(msg)
    } finally {
      setSaving(false)
    }
  }

  const duplicate = async (id: number) => {
    try {
      const res = await api.post(`/presets/${id}/duplicate`)
      setPresets(prev => [...prev, res.data])
    } catch {
      setError(t('common.error'))
    }
  }

  const deletePreset = async (id: number) => {
    if (!confirm(t('presets.confirmDelete'))) return
    try {
      await api.delete(`/presets/${id}`)
      setPresets(prev => prev.filter(p => p.id !== id))
    } catch {
      setError(t('common.error'))
    }
  }

  const startEdit = (preset: Preset) => {
    setEditId(preset.id)
    setName(preset.name)
    setDescription(preset.description || '')
    if (preset.trading_pairs) setTradingPairs(preset.trading_pairs)
    if (preset.trading_config?.per_asset_config) {
      setPerAssetConfig(preset.trading_config.per_asset_config)
    } else {
      setPerAssetConfig({})
    }
    setShowForm(true)
  }

  // Helper to get per-asset summary for cards
  const getAssetSummary = (preset: Preset) => {
    const pairs = preset.trading_pairs || []
    const pac = preset.trading_config?.per_asset_config || {}
    return pairs.map(p => {
      const cfg = pac[p] || {}
      const usdt = cfg.position_usdt
      const parts = usdt ? [`$${usdt.toFixed(0)}`] : ['auto']
      if (cfg.leverage) parts.push(`${cfg.leverage}x`)
      if (cfg.tp) parts.push(`TP ${cfg.tp}%`)
      if (cfg.sl) parts.push(`SL ${cfg.sl}%`)
      if (cfg.max_trades) parts.push(`${cfg.max_trades}T`)
      if (cfg.loss_limit) parts.push(`L${cfg.loss_limit}%`)
      return { symbol: p, label: parts.join(' · ') }
    })
  }

  // Form view
  if (showForm) {
    return (
      <div>
        <div className="flex items-center gap-4 mb-6">
          <button onClick={resetForm} className="text-gray-400 hover:text-white">
            <ArrowLeft size={20} />
          </button>
          <h1 className="text-2xl font-bold text-white">
            {editId ? t('presets.edit') : t('presets.create')}
          </h1>
        </div>

        {error && (
          <div role="alert" className="mb-4 p-3 bg-red-900/30 border border-red-800 rounded text-red-400 text-sm">{error}</div>
        )}

        <div className="border border-white/10 bg-white/[0.03] rounded-xl p-6 mb-6 space-y-6">
          {/* Name & Description */}
          <div className="grid grid-cols-2 gap-4 max-w-lg">
            <div>
              <label className="block text-xs text-gray-400 mb-1">{t('presets.name')}</label>
              <input type="text" value={name} onChange={e => setName(e.target.value)}
                className="filter-select w-full text-sm" autoFocus />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">{t('presets.description')}</label>
              <input type="text" value={description} onChange={e => setDescription(e.target.value)}
                className="filter-select w-full text-sm" />
            </div>
          </div>

          {/* Trading Pairs */}
          <div>
            <label className="block text-sm text-gray-400 mb-2">{b.tradingPairs}</label>
            <div className="flex flex-wrap gap-1.5">
              {PAIRS_CEX.map(pair => {
                const active = tradingPairs.includes(pair)
                return (
                  <button key={pair} onClick={() => togglePair(pair)}
                    className={`px-3 py-1.5 text-sm rounded-lg border transition-all ${
                      active
                        ? 'border-primary-500 bg-primary-500/15 text-primary-400 ring-1 ring-primary-500/30'
                        : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-white/20 hover:bg-white/[0.06] hover:text-gray-300'
                    }`}>
                    {pair}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Per-asset config */}
          {tradingPairs.length > 0 && (
            <div>
              <label className="block text-sm text-gray-400 mb-3">{t('bots.builder.perAssetConfig')}</label>
              <div className="space-y-3">
                {tradingPairs.map(pair => {
                  const cfg = perAssetConfig[pair] || {}
                  const updateAsset = (field: string, val: string) => {
                    const num = val === '' ? undefined : parseFloat(val)
                    setPerAssetConfig(prev => ({
                      ...prev,
                      [pair]: { ...prev[pair], [field]: num }
                    }))
                  }
                  return (
                    <div key={pair} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                      <div className="text-sm font-medium text-white mb-2">{pair}</div>
                      <div className="grid grid-cols-3 gap-2">
                        <div>
                          <label className="block text-[10px] text-gray-500 mb-1">{t('bots.builder.budgetUsdt')}</label>
                          <NumInput value={cfg.position_usdt ?? ''} onChange={e => updateAsset('position_usdt', e.target.value)}
                            placeholder="-" min={1} max={999999} step={1}
                            className="filter-select w-full text-sm tabular-nums text-center" />
                        </div>
                        <div>
                          <label className="block text-[10px] text-gray-500 mb-1">{b.leverage}</label>
                          <NumInput value={cfg.leverage ?? ''} onChange={e => updateAsset('leverage', e.target.value)}
                            placeholder="-" min={1} max={20}
                            className="filter-select w-full text-sm tabular-nums text-center" />
                        </div>
                        <div>
                          <label className="block text-[10px] text-gray-500 mb-1">TP %</label>
                          <NumInput value={cfg.tp ?? ''} onChange={e => updateAsset('tp', e.target.value)}
                            placeholder="-" min={0.5} max={20} step={0.5}
                            className="filter-select w-full text-sm tabular-nums text-center" />
                        </div>
                        <div>
                          <label className="block text-[10px] text-gray-500 mb-1">SL %</label>
                          <NumInput value={cfg.sl ?? ''} onChange={e => updateAsset('sl', e.target.value)}
                            placeholder="-" min={0.5} max={10} step={0.5}
                            className="filter-select w-full text-sm tabular-nums text-center" />
                        </div>
                        <div>
                          <label className="block text-[10px] text-gray-500 mb-1">{b.maxTrades}</label>
                          <NumInput value={cfg.max_trades ?? ''} onChange={e => updateAsset('max_trades', e.target.value)}
                            placeholder="-" min={1} max={50}
                            className="filter-select w-full text-sm tabular-nums text-center" />
                        </div>
                        <div>
                          <label className="block text-[10px] text-gray-500 mb-1">{b.dailyLossLimit}</label>
                          <NumInput value={cfg.loss_limit ?? ''} onChange={e => updateAsset('loss_limit', e.target.value)}
                            placeholder="-" min={1} max={50} step={0.5}
                            className="filter-select w-full text-sm tabular-nums text-center" />
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
              {/* Balance preview */}
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-gray-500">
                {(() => {
                  return tradingPairs.map(p => {
                    const usdt = perAssetConfig[p]?.position_usdt
                    return <span key={p} className="bg-white/5 px-2 py-0.5 rounded">{p}: {usdt ? `$${usdt.toFixed(0)}` : 'auto'}</span>
                  })
                })()}
              </div>
              <p className="text-xs text-gray-600 mt-1">{t('bots.builder.perAssetHint')}</p>
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center justify-between">
          <button onClick={resetForm}
            className="flex items-center gap-1 px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors">
            <ArrowLeft size={16} />
            {t('common.cancel')}
          </button>
          <button onClick={savePreset} disabled={saving || !name.trim() || tradingPairs.length === 0}
            className="px-4 py-2 text-sm bg-primary-600 text-white rounded font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors">
            {saving ? '...' : t('settings.save')}
          </button>
        </div>
      </div>
    )
  }

  // List view
  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-2xl font-bold text-white">{t('presets.title')}</h1>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-white/10 overflow-hidden">
            <button onClick={() => setView('grid')}
              className={`p-1.5 transition-colors ${view === 'grid' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}>
              <LayoutGrid size={15} />
            </button>
            <button onClick={() => setView('list')}
              className={`p-1.5 transition-colors ${view === 'list' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}>
              <List size={15} />
            </button>
          </div>
          <button onClick={() => { resetForm(); setShowForm(true) }}
            className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors">
            + {t('presets.create')}
          </button>
        </div>
      </div>

      {/* Preset cards */}
      {view === 'grid' ? (
        <div className="grid grid-cols-2 xl:grid-cols-3 gap-2.5">
          {presets.map(preset => {
            const summary = getAssetSummary(preset)
            return (
              <div key={preset.id}
                className="border border-white/10 bg-white/[0.03] rounded-xl px-3.5 py-3 hover:bg-white/[0.05] transition-colors">
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-sm font-medium text-white truncate">{preset.name}</span>
                </div>
                {preset.description && (
                  <div className="text-xs text-gray-500 truncate mb-1.5">{preset.description}</div>
                )}
                {summary.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-2">
                    {summary.map(s => (
                      <span key={s.symbol} className="text-[11px] bg-white/5 px-1.5 py-0.5 rounded">
                        <span className="text-white font-medium">{s.symbol}</span>
                        <span className="text-gray-400 ml-1">{s.label}</span>
                      </span>
                    ))}
                  </div>
                )}
                <div className="flex gap-1.5 pt-1.5 border-t border-white/5">
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
            )
          })}
        </div>
      ) : (
        <div className="space-y-1.5">
          {presets.map(preset => {
            const pairs = preset.trading_pairs || []
            return (
              <div key={preset.id}
                className="border border-white/10 bg-white/[0.03] rounded-lg flex items-center gap-3 px-3 py-2 hover:bg-white/[0.05] transition-colors">
                <span className="text-sm font-medium text-white whitespace-nowrap">{preset.name}</span>
                <span className="text-xs text-gray-500 whitespace-nowrap">{pairs.join(', ')}</span>
                {preset.description && (
                  <span className="text-xs text-gray-600 truncate hidden lg:block">{preset.description}</span>
                )}
                <div className="flex gap-1.5 ml-auto flex-shrink-0">
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
            )
          })}
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
