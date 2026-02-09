import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../../api/client'
import { ArrowLeft, ArrowRight, Check, Play, Brain, TrendingUp, BarChart3, DollarSign, Activity, Building } from 'lucide-react'
import ExchangeLogo from '../ui/ExchangeLogo'

interface Strategy {
  name: string
  description: string
  param_schema: Record<string, ParamDef>
}

interface ParamOption {
  value: string
  label: string
}

interface ParamDef {
  type: string
  label: string
  description: string
  default: number | string | boolean
  min?: number
  max?: number
  options?: (string | ParamOption)[]
}

interface DataSource {
  id: string
  name: string
  description: string
  category: string
  provider: string
  free: boolean
  default: boolean
}

interface BotBuilderProps {
  botId?: number | null
  onDone: () => void
  onCancel: () => void
}

// Strategies that use market data and should show the data sources step
const DATA_STRATEGIES = ['llm_signal', 'sentiment_surfer', 'liquidation_hunter']

const CATEGORY_ORDER = ['sentiment', 'futures', 'options', 'spot', 'technical', 'tradfi']
const CATEGORY_ICONS: Record<string, typeof Brain> = {
  sentiment: Brain,
  futures: TrendingUp,
  options: BarChart3,
  spot: DollarSign,
  technical: Activity,
  tradfi: Building,
}

const EXCHANGES = ['bitget', 'weex', 'hyperliquid']
const PAIRS_CEX = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'AVAXUSDT']
const PAIRS_HL = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'AVAX']

export default function BotBuilder({ botId, onDone, onCancel }: BotBuilderProps) {
  const { t } = useTranslation()
  const isEdit = botId !== null && botId !== undefined
  const [step, setStep] = useState(0)
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // Data sources catalog
  const [dataSources, setDataSources] = useState<DataSource[]>([])
  const [defaultSourceIds, setDefaultSourceIds] = useState<string[]>([])
  const [selectedSources, setSelectedSources] = useState<string[]>([])

  // Form state
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [strategyType, setStrategyType] = useState('')
  const [strategyParams, setStrategyParams] = useState<Record<string, any>>({})
  const [exchangeType, setExchangeType] = useState('bitget')
  const [mode, setMode] = useState('demo')
  const [tradingPairs, setTradingPairs] = useState<string[]>(['BTCUSDT'])
  const [leverage, setLeverage] = useState(4)
  const [positionSize, setPositionSize] = useState(7.5)
  const [maxTrades, setMaxTrades] = useState(2)
  const [takeProfit, setTakeProfit] = useState(4.0)
  const [stopLoss, setStopLoss] = useState(1.5)
  const [dailyLossLimit, setDailyLossLimit] = useState(5.0)
  const [scheduleType, setScheduleType] = useState('market_sessions')
  const [intervalMinutes, setIntervalMinutes] = useState(60)
  const [customHours, setCustomHours] = useState<number[]>([1, 8, 14, 21])

  // Whether current strategy uses market data
  const usesData = DATA_STRATEGIES.includes(strategyType)

  // Dynamic steps: insert data sources step after strategy for data-using strategies
  const steps = useMemo(() => {
    if (usesData) {
      return ['step1', 'step2', 'step2b', 'step3', 'step4', 'step5', 'step6'] as const
    }
    return ['step1', 'step2', 'step3', 'step4', 'step5', 'step6'] as const
  }, [usesData])

  // Group data sources by category
  const sourcesByCategory = useMemo(() => {
    const groups: Record<string, DataSource[]> = {}
    for (const cat of CATEGORY_ORDER) {
      const items = dataSources.filter(ds => ds.category === cat)
      if (items.length > 0) groups[cat] = items
    }
    return groups
  }, [dataSources])

  // Load strategies
  useEffect(() => {
    api.get('/bots/strategies').then(res => {
      setStrategies(res.data.strategies)
      if (res.data.strategies.length > 0 && !strategyType) {
        const first = res.data.strategies[0]
        setStrategyType(first.name)
        const defaults: Record<string, any> = {}
        Object.entries(first.param_schema).forEach(([key, def]) => {
          defaults[key] = (def as ParamDef).default
        })
        setStrategyParams(defaults)
      }
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Load data sources catalog
  useEffect(() => {
    api.get('/bots/data-sources').then(res => {
      setDataSources(res.data.sources)
      setDefaultSourceIds(res.data.defaults)
      // Only set defaults if not editing (editing loads from bot config)
      if (!isEdit) {
        setSelectedSources(res.data.defaults)
      }
    }).catch(() => {})
  }, [isEdit])

  // Load existing bot if editing
  useEffect(() => {
    if (isEdit) {
      api.get(`/bots/${botId}`).then(res => {
        const d = res.data
        setName(d.name)
        setDescription(d.description || '')
        setStrategyType(d.strategy_type)
        setStrategyParams(d.strategy_params || {})
        setExchangeType(d.exchange_type)
        setMode(d.mode)
        setTradingPairs(d.trading_pairs)
        setLeverage(d.leverage)
        setPositionSize(d.position_size_percent)
        setMaxTrades(d.max_trades_per_day)
        setTakeProfit(d.take_profit_percent)
        setStopLoss(d.stop_loss_percent)
        setDailyLossLimit(d.daily_loss_limit_percent)
        setScheduleType(d.schedule_type)
        if (d.schedule_config) {
          if (d.schedule_config.interval_minutes) setIntervalMinutes(d.schedule_config.interval_minutes)
          if (d.schedule_config.hours) setCustomHours(d.schedule_config.hours)
        }
        // Restore selected data sources from strategy_params
        if (d.strategy_params?.data_sources) {
          setSelectedSources(d.strategy_params.data_sources)
        } else if (defaultSourceIds.length > 0) {
          setSelectedSources(defaultSourceIds)
        }
      })
    }
  }, [botId, isEdit, defaultSourceIds])

  const isHyperliquid = exchangeType === 'hyperliquid'
  const activePairs = isHyperliquid ? PAIRS_HL : PAIRS_CEX

  const selectedStrategy = strategies.find(s => s.name === strategyType)

  const handleStrategyChange = (name: string) => {
    setStrategyType(name)
    const strat = strategies.find(s => s.name === name)
    if (strat) {
      const defaults: Record<string, any> = {}
      Object.entries(strat.param_schema).forEach(([key, def]) => {
        defaults[key] = (def as ParamDef).default
      })
      setStrategyParams(defaults)
    }
  }

  // Convert trading pairs when exchange type changes
  useEffect(() => {
    setTradingPairs(prev => prev.map(p => {
      if (isHyperliquid) {
        return p.replace(/(USDT|USDC)$/i, '')
      } else {
        return p.match(/(USDT|USDC)$/i) ? p : p + 'USDT'
      }
    }))
  }, [exchangeType]) // eslint-disable-line react-hooks/exhaustive-deps

  const togglePair = (pair: string) => {
    setTradingPairs(prev =>
      prev.includes(pair) ? prev.filter(p => p !== pair) : [...prev, pair]
    )
  }

  const toggleHour = (hour: number) => {
    setCustomHours(prev =>
      prev.includes(hour) ? prev.filter(h => h !== hour) : [...prev, hour].sort((a, b) => a - b)
    )
  }

  const toggleSource = (id: string) => {
    setSelectedSources(prev =>
      prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id]
    )
  }

  const selectAllInCategory = (category: string) => {
    const ids = (sourcesByCategory[category] || []).map(ds => ds.id)
    setSelectedSources(prev => [...new Set([...prev, ...ids])])
  }

  const clearCategory = (category: string) => {
    const ids = new Set((sourcesByCategory[category] || []).map(ds => ds.id))
    setSelectedSources(prev => prev.filter(s => !ids.has(s)))
  }

  const buildPayload = () => {
    const scheduleConfig = scheduleType === 'interval'
      ? { interval_minutes: intervalMinutes }
      : scheduleType === 'custom_cron'
        ? { hours: customHours }
        : { hours: [1, 8, 14, 21] }

    // Include data_sources in strategy_params for data-using strategies
    const params = usesData
      ? { ...strategyParams, data_sources: selectedSources }
      : strategyParams

    return {
      name,
      description: description || undefined,
      strategy_type: strategyType,
      exchange_type: exchangeType,
      mode,
      trading_pairs: tradingPairs,
      leverage,
      position_size_percent: positionSize,
      max_trades_per_day: maxTrades,
      take_profit_percent: takeProfit,
      stop_loss_percent: stopLoss,
      daily_loss_limit_percent: dailyLossLimit,
      strategy_params: params,
      schedule_type: scheduleType,
      schedule_config: scheduleConfig,
    }
  }

  const handleSave = async (andStart = false) => {
    setSaving(true)
    setError('')
    try {
      let newId: number
      if (isEdit) {
        await api.put(`/bots/${botId}`, buildPayload())
        newId = botId!
      } else {
        const res = await api.post('/bots', buildPayload())
        newId = res.data.id
      }
      if (andStart) {
        await api.post(`/bots/${newId}/start`)
      }
      onDone()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Save failed')
    }
    setSaving(false)
  }

  const canGoNext = () => {
    const stepKey = steps[step]
    if (stepKey === 'step1') return name.trim().length > 0
    if (stepKey === 'step2') return strategyType.length > 0
    if (stepKey === 'step2b') return selectedSources.length > 0
    if (stepKey === 'step3') return tradingPairs.length > 0
    if (stepKey === 'step4') return true
    if (stepKey === 'step5') return scheduleType === 'interval' ? intervalMinutes >= 5 : true
    return true
  }

  const b = t('bots.builder', { returnObjects: true }) as Record<string, string>
  const currentStepKey = steps[step]

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <button onClick={onCancel} className="text-gray-400 hover:text-white">
          <ArrowLeft size={20} />
        </button>
        <h1 className="text-2xl font-bold text-white">
          {isEdit ? b.editTitle : b.title}
        </h1>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-1 mb-8">
        {steps.map((s, i) => (
          <div key={s} className="flex items-center">
            <button
              onClick={() => i <= step && setStep(i)}
              className={`px-3 py-1 text-sm rounded ${
                i === step ? 'bg-primary-600 text-white' :
                i < step ? 'bg-primary-900/50 text-primary-400' :
                'bg-gray-800 text-gray-500'
              }`}
            >
              {b[s]}
            </button>
            {i < steps.length - 1 && <div className="w-4 h-px bg-gray-700 mx-1" />}
          </div>
        ))}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-900/30 border border-red-800 rounded text-red-400 text-sm">{error}</div>
      )}

      {/* Step content */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 mb-6">
        {/* Step 1: Name */}
        {currentStepKey === 'step1' && (
          <div className="space-y-4 max-w-md">
            <div>
              <label className="block text-sm text-gray-400 mb-1">{b.name}</label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder={b.namePlaceholder}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white focus:border-primary-500 focus:outline-none"
                autoFocus
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">{b.description}</label>
              <input
                type="text"
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder={b.descriptionPlaceholder}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white focus:border-primary-500 focus:outline-none"
              />
            </div>
          </div>
        )}

        {/* Step 2: Strategy */}
        {currentStepKey === 'step2' && (
          <div className="space-y-6">
            <div>
              <label className="block text-sm text-gray-400 mb-2">{b.selectStrategy}</label>
              <div className="grid gap-3">
                {strategies.map(s => (
                  <button
                    key={s.name}
                    onClick={() => handleStrategyChange(s.name)}
                    className={`text-left p-4 rounded border transition-colors ${
                      strategyType === s.name
                        ? 'border-primary-500 bg-primary-900/20'
                        : 'border-gray-700 bg-gray-800 hover:border-gray-600'
                    }`}
                  >
                    <div className="text-white font-medium">{s.name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</div>
                    <div className="text-sm text-gray-400 mt-1">{s.description}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* LLM info banner */}
            {strategyType === 'llm_signal' && (
              <div className="bg-blue-900/20 border border-blue-800 rounded-lg p-3">
                <p className="text-xs text-blue-300">{b.llmNote || 'This bot uses AI for signal generation. Configure your API key in Settings → LLM Keys.'}</p>
              </div>
            )}

            {selectedStrategy && Object.keys(selectedStrategy.param_schema).length > 0 && (
              <div>
                <label className="block text-sm text-gray-400 mb-3">{b.strategyParams}</label>
                <div className="grid grid-cols-2 gap-4">
                  {Object.entries(selectedStrategy.param_schema).map(([key, def]) => {
                    const d = def as ParamDef

                    if (d.type === 'select' && d.options) {
                      return (
                        <div key={key}>
                          <label className="block text-xs text-gray-500 mb-1" title={d.description}>{d.label}</label>
                          <select
                            value={strategyParams[key] ?? d.default}
                            onChange={e => setStrategyParams(prev => ({ ...prev, [key]: e.target.value }))}
                            className="w-full px-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded text-white focus:border-primary-500 focus:outline-none"
                          >
                            {d.options.map(opt => {
                              const val = typeof opt === 'string' ? opt : opt.value
                              const label = typeof opt === 'string' ? opt : opt.label
                              return <option key={val} value={val}>{label}</option>
                            })}
                          </select>
                        </div>
                      )
                    }

                    if (d.type === 'textarea') {
                      return (
                        <div key={key} className="col-span-2">
                          <label className="block text-xs text-gray-500 mb-1" title={d.description}>{d.label}</label>
                          <textarea
                            value={strategyParams[key] ?? ''}
                            onChange={e => setStrategyParams(prev => ({ ...prev, [key]: e.target.value }))}
                            rows={5}
                            placeholder={b.customPromptPlaceholder || d.description}
                            className="w-full px-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded text-white font-mono focus:border-primary-500 focus:outline-none"
                          />
                        </div>
                      )
                    }

                    if (d.type === 'float' && d.min !== undefined && d.max !== undefined && d.max <= 1) {
                      const val = strategyParams[key] ?? d.default
                      return (
                        <div key={key}>
                          <label className="block text-xs text-gray-500 mb-1" title={d.description}>
                            {d.label}: {Number(val).toFixed(1)}
                          </label>
                          <input
                            type="range"
                            min={d.min}
                            max={d.max}
                            step={0.1}
                            value={val}
                            onChange={e => setStrategyParams(prev => ({ ...prev, [key]: parseFloat(e.target.value) }))}
                            className="w-full accent-primary-500"
                          />
                          <p className="text-xs text-gray-600 mt-0.5">{d.description}</p>
                        </div>
                      )
                    }

                    return (
                      <div key={key}>
                        <label className="block text-xs text-gray-500 mb-1" title={d.description}>{d.label}</label>
                        <input
                          type="number"
                          value={strategyParams[key] ?? d.default}
                          onChange={e => setStrategyParams(prev => ({ ...prev, [key]: parseFloat(e.target.value) || 0 }))}
                          min={d.min}
                          max={d.max}
                          step={d.type === 'float' ? 0.0001 : 1}
                          className="w-full px-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded text-white focus:border-primary-500 focus:outline-none"
                        />
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Step 2b: Data Sources */}
        {currentStepKey === 'step2b' && (
          <div className="space-y-6">
            <div>
              <label className="block text-sm text-gray-400 mb-1">{b.dataSources || 'Data Sources'}</label>
              <p className="text-xs text-gray-500 mb-4">{b.dataSourcesDesc || 'Select which market data your bot should analyze'}</p>
              <div className="text-xs text-gray-400 mb-4">
                {selectedSources.length} {b.sourcesSelected || 'sources selected'}
              </div>
            </div>

            {CATEGORY_ORDER.map(cat => {
              const sources = sourcesByCategory[cat]
              if (!sources) return null
              const Icon = CATEGORY_ICONS[cat] || Activity
              const catLabel = b[cat] || cat
              const allSelected = sources.every(s => selectedSources.includes(s.id))

              return (
                <div key={cat}>
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <Icon size={16} className="text-gray-400" />
                      <span className="text-sm font-medium text-gray-300">{catLabel}</span>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => selectAllInCategory(cat)}
                        className={`text-[10px] px-2 py-0.5 rounded ${allSelected ? 'text-gray-600' : 'text-primary-400 hover:text-primary-300'}`}
                        disabled={allSelected}
                      >
                        {b.selectAll || 'Select All'}
                      </button>
                      <button
                        onClick={() => clearCategory(cat)}
                        className="text-[10px] px-2 py-0.5 rounded text-gray-500 hover:text-gray-400"
                      >
                        {b.clearAll || 'Clear'}
                      </button>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 mb-4">
                    {sources.map(src => {
                      const isSelected = selectedSources.includes(src.id)
                      return (
                        <button
                          key={src.id}
                          onClick={() => toggleSource(src.id)}
                          className={`text-left p-3 rounded-lg border transition-all duration-200 ${
                            isSelected
                              ? 'border-green-400/70 bg-green-950/30 shadow-[0_0_15px_rgba(74,222,128,0.15)]'
                              : 'border-gray-700 bg-gray-800/50 hover:border-gray-600'
                          }`}
                        >
                          <div className={`text-sm font-medium ${isSelected ? 'text-green-300' : 'text-white'}`}>
                            {src.name}
                          </div>
                          <div className="text-[11px] text-gray-400 mt-1 line-clamp-2">{src.description}</div>
                          <div className="text-[10px] text-gray-500 mt-1.5">{src.provider}</div>
                        </button>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* Step 3: Trading Parameters */}
        {currentStepKey === 'step3' && (
          <div className="space-y-6">
            <div>
              <label className="block text-sm text-gray-400 mb-2">{b.tradingPairs}</label>
              <div className="flex flex-wrap gap-2">
                {activePairs.map(pair => (
                  <button
                    key={pair}
                    onClick={() => togglePair(pair)}
                    className={`px-3 py-1.5 text-sm rounded border transition-colors ${
                      tradingPairs.includes(pair)
                        ? 'border-primary-500 bg-primary-900/30 text-primary-400'
                        : 'border-gray-700 bg-gray-800 text-gray-400 hover:border-gray-600'
                    }`}
                  >
                    {pair}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs text-gray-500 mb-1">{b.leverage}</label>
                <input type="number" value={leverage} onChange={e => setLeverage(parseInt(e.target.value) || 1)} min={1} max={20}
                  className="w-full px-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded text-white focus:border-primary-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">{b.positionSize}</label>
                <input type="number" value={positionSize} onChange={e => setPositionSize(parseFloat(e.target.value) || 1)} min={1} max={25} step={0.5}
                  className="w-full px-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded text-white focus:border-primary-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">{b.maxTrades}</label>
                <input type="number" value={maxTrades} onChange={e => setMaxTrades(parseInt(e.target.value) || 1)} min={1} max={10}
                  className="w-full px-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded text-white focus:border-primary-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">{b.takeProfit}</label>
                <input type="number" value={takeProfit} onChange={e => setTakeProfit(parseFloat(e.target.value) || 0.5)} min={0.5} max={20} step={0.5}
                  className="w-full px-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded text-white focus:border-primary-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">{b.stopLoss}</label>
                <input type="number" value={stopLoss} onChange={e => setStopLoss(parseFloat(e.target.value) || 0.5)} min={0.5} max={10} step={0.5}
                  className="w-full px-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded text-white focus:border-primary-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">{b.dailyLossLimit}</label>
                <input type="number" value={dailyLossLimit} onChange={e => setDailyLossLimit(parseFloat(e.target.value) || 1)} min={1} max={20} step={0.5}
                  className="w-full px-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded text-white focus:border-primary-500 focus:outline-none" />
              </div>
            </div>
          </div>
        )}

        {/* Step 4: Exchange & Mode */}
        {currentStepKey === 'step4' && (
          <div className="space-y-6">
            <div>
              <label className="block text-sm text-gray-400 mb-2">{b.exchange}</label>
              <div className="flex gap-3">
                {EXCHANGES.map(ex => (
                  <button
                    key={ex}
                    onClick={() => setExchangeType(ex)}
                    className={`px-4 py-2 rounded border transition-colors ${
                      exchangeType === ex
                        ? 'border-primary-500 bg-primary-900/20 text-white'
                        : 'border-gray-700 bg-gray-800 text-gray-400 hover:border-gray-600'
                    }`}
                  >
                    <ExchangeLogo exchange={ex} size={16} />
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-2">{b.mode}</label>
              <div className="flex gap-3">
                {(['demo', 'live', 'both'] as const).map(m => (
                  <button
                    key={m}
                    onClick={() => setMode(m)}
                    className={`px-4 py-2 rounded border transition-colors ${
                      mode === m
                        ? m === 'demo' ? 'border-blue-500 bg-blue-900/20 text-blue-400' :
                          m === 'live' ? 'border-orange-500 bg-orange-900/20 text-orange-400' :
                          'border-purple-500 bg-purple-900/20 text-purple-400'
                        : 'border-gray-700 bg-gray-800 text-gray-400 hover:border-gray-600'
                    }`}
                  >
                    {b[m]}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Step 5: Schedule */}
        {currentStepKey === 'step5' && (
          <div className="space-y-4">
            <label className="block text-sm text-gray-400 mb-2">{b.schedule}</label>
            <div className="space-y-3">
              {(['market_sessions', 'interval', 'custom_cron'] as const).map(st => (
                <button
                  key={st}
                  onClick={() => setScheduleType(st)}
                  className={`block w-full text-left p-3 rounded border transition-colors ${
                    scheduleType === st
                      ? 'border-primary-500 bg-primary-900/20'
                      : 'border-gray-700 bg-gray-800 hover:border-gray-600'
                  }`}
                >
                  <div className="text-white text-sm">{b[st === 'market_sessions' ? 'marketSessions' : st === 'interval' ? 'interval' : 'customCron']}</div>
                </button>
              ))}
            </div>

            {scheduleType === 'interval' && (
              <div className="mt-4">
                <label className="block text-xs text-gray-500 mb-1">{b.intervalMinutes}</label>
                <input type="number" value={intervalMinutes} onChange={e => setIntervalMinutes(parseInt(e.target.value) || 5)} min={5} max={1440}
                  className="w-32 px-2 py-1.5 text-sm bg-gray-800 border border-gray-700 rounded text-white focus:border-primary-500 focus:outline-none" />
              </div>
            )}

            {scheduleType === 'custom_cron' && (
              <div className="mt-4">
                <label className="block text-xs text-gray-500 mb-2">{b.customHours}</label>
                <div className="flex flex-wrap gap-1.5">
                  {Array.from({ length: 24 }, (_, i) => (
                    <button
                      key={i}
                      onClick={() => toggleHour(i)}
                      className={`w-10 h-8 text-xs rounded border transition-colors ${
                        customHours.includes(i)
                          ? 'border-primary-500 bg-primary-900/30 text-primary-400'
                          : 'border-gray-700 bg-gray-800 text-gray-500 hover:border-gray-600'
                      }`}
                    >
                      {String(i).padStart(2, '0')}h
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Step 6: Review */}
        {currentStepKey === 'step6' && (
          <div className="space-y-4">
            <h3 className="text-white font-medium mb-4">{b.review}</h3>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div><span className="text-gray-500">{b.name}:</span> <span className="text-white ml-2">{name}</span></div>
              <div><span className="text-gray-500">{b.strategy}:</span> <span className="text-white ml-2">{strategyType}</span></div>
              <div><span className="text-gray-500">{b.exchange}:</span> <span className="text-white ml-2"><ExchangeLogo exchange={exchangeType} size={14} /></span></div>
              <div><span className="text-gray-500">{b.mode}:</span> <span className="text-white ml-2">{mode}</span></div>
              <div><span className="text-gray-500">{b.tradingPairs}:</span> <span className="text-white ml-2">{tradingPairs.join(', ')}</span></div>
              <div><span className="text-gray-500">{b.leverage}:</span> <span className="text-white ml-2">{leverage}x</span></div>
              <div><span className="text-gray-500">{b.positionSize}:</span> <span className="text-white ml-2">{positionSize}%</span></div>
              <div><span className="text-gray-500">{b.maxTrades}:</span> <span className="text-white ml-2">{maxTrades}</span></div>
              <div><span className="text-gray-500">{b.takeProfit}:</span> <span className="text-white ml-2">{takeProfit}%</span></div>
              <div><span className="text-gray-500">{b.stopLoss}:</span> <span className="text-white ml-2">{stopLoss}%</span></div>
              {usesData && (
                <div><span className="text-gray-500">{b.dataSources || 'Data Sources'}:</span> <span className="text-white ml-2">{selectedSources.length} {b.sourcesSelected || 'selected'}</span></div>
              )}
              <div><span className="text-gray-500">{b.schedule}:</span> <span className="text-white ml-2">
                {scheduleType === 'interval' ? `Every ${intervalMinutes}min` :
                 scheduleType === 'custom_cron' ? customHours.map(h => `${h}:00`).join(', ') :
                 '01:00, 08:00, 14:00, 21:00 UTC'}
              </span></div>
            </div>
          </div>
        )}
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => step > 0 ? setStep(step - 1) : onCancel()}
          className="flex items-center gap-1 px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={16} />
          {step > 0 ? b.back : t('common.cancel')}
        </button>

        <div className="flex gap-2">
          {step < steps.length - 1 ? (
            <button
              onClick={() => setStep(step + 1)}
              disabled={!canGoNext()}
              className="flex items-center gap-1 px-4 py-2 text-sm bg-primary-600 text-white rounded font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors"
            >
              {b.next}
              <ArrowRight size={16} />
            </button>
          ) : (
            <>
              <button
                onClick={() => handleSave(false)}
                disabled={saving}
                className="flex items-center gap-1 px-4 py-2 text-sm bg-gray-700 text-white rounded font-medium hover:bg-gray-600 disabled:opacity-50 transition-colors"
              >
                <Check size={16} />
                {isEdit ? b.save : b.create}
              </button>
              {!isEdit && (
                <button
                  onClick={() => handleSave(true)}
                  disabled={saving}
                  className="flex items-center gap-1 px-4 py-2 text-sm bg-green-700 text-white rounded font-medium hover:bg-green-600 disabled:opacity-50 transition-colors"
                >
                  <Play size={16} />
                  {b.createAndStart}
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
