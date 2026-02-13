import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import api from '../../api/client'
import { ArrowLeft, ArrowRight, Check, Play, Brain, TrendingUp, BarChart3, DollarSign, Activity, Building, LayoutGrid, List, Bot } from 'lucide-react'
import ExchangeLogo from '../ui/ExchangeLogo'
import FilterDropdown from '../ui/FilterDropdown'

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
  depends_on?: string
  options_map?: Record<string, ParamOption[]>
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

interface Preset {
  id: number
  name: string
  exchange_type: string
  trading_config: Record<string, any>
  strategy_config: Record<string, any>
  trading_pairs: string[]
}

interface BotBuilderProps {
  botId?: number | null
  onDone: () => void
  onCancel: () => void
}

// Strategies that use market data and should show the data sources step
const DATA_STRATEGIES = ['llm_signal', 'sentiment_surfer', 'liquidation_hunter']

const STRATEGY_DISPLAY_NAMES: Record<string, string> = {
  llm_signal: 'KI-Companion',
}

const STRATEGY_DESCRIPTIONS_DE: Record<string, string> = {
  llm_signal: 'KI-gestützte Signalgenerierung mittels Large Language Models. Die KI analysiert Marktdaten in jedem Zyklus und liefert LONG/SHORT-Empfehlungen mit Konfidenzbewertung.',
}

function getStrategyDisplayName(name: string): string {
  return STRATEGY_DISPLAY_NAMES[name] || name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

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
  const [validationErrors, setValidationErrors] = useState<string[]>([])

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
  const [customHours, setCustomHours] = useState<number[]>([])
  const [rotationEnabled, setRotationEnabled] = useState(false)
  const [rotationMinutes, setRotationMinutes] = useState(60)
  const [rotationStartTime, setRotationStartTime] = useState('08:00')
  const [discordWebhookUrl, setDiscordWebhookUrl] = useState('')
  const [telegramBotToken, setTelegramBotToken] = useState('')
  const [telegramChatId, setTelegramChatId] = useState('')

  // View modes for strategy, data sources, and schedule
  const [strategyView, setStrategyView] = useState<'grid' | 'list'>('grid')
  const [sourcesView, setSourcesView] = useState<'grid' | 'list'>('grid')
  const [scheduleView, setScheduleView] = useState<'grid' | 'list'>('grid')

  // Presets
  const [presets, setPresets] = useState<Preset[]>([])
  const [selectedPresetId, setSelectedPresetId] = useState<number | null>(null)

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

  // Load presets
  useEffect(() => {
    if (!isEdit) {
      api.get('/presets').then(res => {
        setPresets(res.data || [])
      }).catch(() => {})
    }
  }, [isEdit])

  const applyPreset = (presetId: number) => {
    const preset = presets.find(p => p.id === presetId)
    if (!preset) return
    setSelectedPresetId(presetId)
    const tc = preset.trading_config || {}
    if (tc.leverage) setLeverage(tc.leverage)
    if (tc.position_size_percent) setPositionSize(tc.position_size_percent)
    if (tc.max_trades_per_day) setMaxTrades(tc.max_trades_per_day)
    if (tc.take_profit_percent) setTakeProfit(tc.take_profit_percent)
    if (tc.stop_loss_percent) setStopLoss(tc.stop_loss_percent)
    if (tc.daily_loss_limit_percent) setDailyLossLimit(tc.daily_loss_limit_percent)
    // Apply strategy params
    if (preset.strategy_config && Object.keys(preset.strategy_config).length > 0) {
      setStrategyParams(prev => ({ ...prev, ...preset.strategy_config }))
    }
    // Apply trading pairs (convert based on current exchange)
    if (preset.trading_pairs && preset.trading_pairs.length > 0) {
      const converted = preset.trading_pairs.map(p => {
        const base = p.replace(/(USDT|USDC)$/i, '')
        return isHyperliquid ? base : (base.match(/(USDT|USDC)$/i) ? base : base + 'USDT')
      })
      setTradingPairs(converted)
    }
  }

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
      // New bots start with no sources selected; editing loads from bot config
      if (!isEdit) {
        setSelectedSources([])
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
        if (d.rotation_enabled) setRotationEnabled(true)
        if (d.rotation_interval_minutes) setRotationMinutes(d.rotation_interval_minutes)
        if (d.rotation_start_time) setRotationStartTime(d.rotation_start_time)
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

  // Auto-select first model when provider family changes
  useEffect(() => {
    if (!selectedStrategy) return
    const modelDef = selectedStrategy.param_schema['llm_model'] as ParamDef | undefined
    if (!modelDef?.options_map) return

    const family = strategyParams.llm_provider as string
    const models = modelDef.options_map[family] || []
    const currentModel = strategyParams.llm_model
    if (!models.some((m: ParamOption) => m.value === currentModel)) {
      setStrategyParams(prev => ({ ...prev, llm_model: models[0]?.value ?? '' }))
    }
  }, [strategyParams.llm_provider, selectedStrategy])

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
    const isRotationOnly = scheduleType === 'rotation_only'
    const scheduleConfig = scheduleType === 'interval'
      ? { interval_minutes: intervalMinutes }
      : scheduleType === 'custom_cron'
        ? { hours: customHours }
        : { hours: [1, 8, 14, 21] }

    // Include data_sources in strategy_params for data-using strategies
    const params = usesData
      ? { ...strategyParams, data_sources: selectedSources }
      : strategyParams

    const effectiveRotation = rotationEnabled || isRotationOnly

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
      schedule_config: isRotationOnly ? null : scheduleConfig,
      rotation_enabled: effectiveRotation,
      rotation_interval_minutes: effectiveRotation ? rotationMinutes : null,
      rotation_start_time: effectiveRotation ? rotationStartTime : null,
      discord_webhook_url: discordWebhookUrl || undefined,
      telegram_bot_token: telegramBotToken || undefined,
      telegram_chat_id: telegramChatId || undefined,
    }
  }

  const handleSave = async (andStart = false) => {
    // Validate all steps before saving
    for (let i = 0; i < steps.length - 1; i++) {
      const errors = getStepErrors(steps[i])
      if (errors.length > 0) {
        setStep(i)
        setValidationErrors(errors)
        return
      }
    }
    setSaving(true)
    setError('')
    setValidationErrors([])
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

  const getStepErrors = (stepKey: string): string[] => {
    const errors: string[] = []
    if (stepKey === 'step1' && !name.trim()) errors.push(t('bots.builder.errors.nameRequired'))
    if (stepKey === 'step2' && !strategyType) errors.push(t('bots.builder.errors.strategyRequired'))
    if (stepKey === 'step2b' && selectedSources.length === 0) errors.push(t('bots.builder.errors.dataSourcesRequired'))
    if (stepKey === 'step3' && tradingPairs.length === 0) errors.push(t('bots.builder.errors.pairsRequired'))
    if (stepKey === 'step5') {
      if (scheduleType === 'custom_cron' && customHours.length === 0) errors.push(t('bots.builder.errors.hoursRequired'))
      if (scheduleType === 'interval' && intervalMinutes < 5) errors.push(t('bots.builder.errors.intervalMinimum'))
      if ((scheduleType === 'rotation_only' || rotationEnabled) && rotationMinutes < 5) errors.push(t('bots.builder.errors.rotationMinimum'))
    }
    return errors
  }

  const handleNext = () => {
    const errors = getStepErrors(steps[step])
    if (errors.length > 0) {
      setValidationErrors(errors)
      return
    }
    setValidationErrors([])
    setStep(step + 1)
  }

  const handleStepClick = (targetStep: number) => {
    setValidationErrors([])
    setStep(targetStep)
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
              onClick={() => handleStepClick(i)}
              className={`px-3 py-1 text-sm rounded cursor-pointer transition-colors ${
                i === step ? 'bg-primary-600 text-white' :
                i < step ? 'bg-primary-900/50 text-primary-400 hover:bg-primary-800/60' :
                'bg-gray-800 text-gray-500 hover:bg-gray-700 hover:text-gray-300'
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
      <div className="border border-white/10 bg-white/[0.03] rounded-xl p-6 mb-6">
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
                className="filter-select w-full text-sm"
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
                className="filter-select w-full text-sm"
              />
            </div>

            {/* Preset selection */}
            {!isEdit && (
              <div className="pt-2 border-t border-white/5">
                <label className="block text-sm text-gray-400 mb-1">{t('bots.builder.loadFromPreset')}</label>
                {presets.length > 0 ? (
                  <>
                    <FilterDropdown
                      value={String(selectedPresetId ?? '')}
                      onChange={val => { const id = parseInt(val); if (id) applyPreset(id) }}
                      options={[
                        { value: '', label: t('bots.builder.selectPreset') },
                        ...presets.map(p => ({ value: String(p.id), label: `${p.name}${p.exchange_type !== 'any' ? ` (${p.exchange_type})` : ''}` }))
                      ]}
                      ariaLabel="Preset"
                    />
                    {selectedPresetId && (
                      <p className="text-xs text-green-400 mt-1">{t('bots.builder.presetLoaded')}</p>
                    )}
                  </>
                ) : (
                  <div className="text-sm text-gray-500">
                    {t('bots.builder.noPresets')} — <Link to="/presets" className="text-primary-400 hover:text-primary-300">{t('bots.builder.createPreset')}</Link>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Step 2: Strategy */}
        {currentStepKey === 'step2' && (
          <div className="space-y-6">
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="block text-sm text-gray-400">{b.selectStrategy}</label>
                <div className="flex items-center gap-1 bg-white/5 rounded-lg p-0.5">
                  <button
                    type="button"
                    onClick={() => setStrategyView('grid')}
                    className={`p-1.5 rounded-md transition-colors ${strategyView === 'grid' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
                    title="Kacheln"
                  >
                    <LayoutGrid size={14} />
                  </button>
                  <button
                    type="button"
                    onClick={() => setStrategyView('list')}
                    className={`p-1.5 rounded-md transition-colors ${strategyView === 'list' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
                    title="Liste"
                  >
                    <List size={14} />
                  </button>
                </div>
              </div>

              {strategyView === 'grid' ? (
                <div className="grid grid-cols-2 gap-2">
                  {strategies.map(s => {
                    const isSelected = strategyType === s.name
                    return (
                      <button
                        key={s.name}
                        onClick={() => handleStrategyChange(s.name)}
                        className={`text-left p-3 rounded-xl border transition-all ${
                          isSelected
                            ? 'border-primary-500 bg-primary-500/10 ring-1 ring-primary-500/30'
                            : 'border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]'
                        }`}
                      >
                        <div className={`flex items-center gap-1.5 text-sm font-medium ${isSelected ? 'text-primary-400' : 'text-white'}`}>
                          {getStrategyDisplayName(s.name)}
                          {s.name === 'llm_signal' && <Bot size={14} className="text-emerald-400" />}
                        </div>
                        <div className="text-xs text-gray-500 mt-1 line-clamp-2">
                          {STRATEGY_DESCRIPTIONS_DE[s.name] || s.description}
                        </div>
                      </button>
                    )
                  })}
                </div>
              ) : (
                <div className="space-y-1">
                  {strategies.map(s => {
                    const isSelected = strategyType === s.name
                    return (
                      <button
                        key={s.name}
                        onClick={() => handleStrategyChange(s.name)}
                        className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl border transition-all ${
                          isSelected
                            ? 'border-primary-500 bg-primary-500/10 ring-1 ring-primary-500/30'
                            : 'border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]'
                        }`}
                      >
                        {isSelected && <Check size={14} className="text-primary-400 shrink-0" />}
                        <div className={`flex items-center gap-1.5 text-sm font-medium ${isSelected ? 'text-primary-400' : 'text-white'}`}>
                          {getStrategyDisplayName(s.name)}
                          {s.name === 'llm_signal' && <Bot size={14} className="text-emerald-400" />}
                        </div>
                        <div className="text-xs text-gray-500 truncate ml-auto">
                          {(STRATEGY_DESCRIPTIONS_DE[s.name] || s.description).slice(0, 60)}...
                        </div>
                      </button>
                    )
                  })}
                </div>
              )}
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
                <div className="space-y-3">
                  {(() => {
                    const selectEntries = Object.entries(selectedStrategy.param_schema).filter(
                      ([, def]) => (def as ParamDef).type === 'select' || (def as ParamDef).type === 'dependent_select'
                    )
                    const otherEntries = Object.entries(selectedStrategy.param_schema).filter(
                      ([, def]) => (def as ParamDef).type !== 'select' && (def as ParamDef).type !== 'dependent_select'
                    )

                    return (
                      <>
                        {/* Dropdowns (Model Family + Model) compact in one row */}
                        {selectEntries.length > 0 && (
                          <div className="flex items-end gap-3 flex-wrap">
                            {selectEntries.map(([key, def]) => {
                              const d = def as ParamDef
                              if (d.type === 'select' && d.options) {
                                const selectOptions = d.options.map(opt => ({
                                  value: typeof opt === 'string' ? opt : opt.value,
                                  label: typeof opt === 'string' ? opt : opt.label,
                                }))
                                return (
                                  <div key={key}>
                                    <label className="block text-xs text-gray-500 mb-1" title={d.description}>{d.label}</label>
                                    <FilterDropdown
                                      value={String(strategyParams[key] ?? d.default)}
                                      onChange={val => setStrategyParams(prev => ({ ...prev, [key]: val }))}
                                      options={selectOptions}
                                      ariaLabel={d.label}
                                    />
                                  </div>
                                )
                              }
                              if (d.type === 'dependent_select' && d.options_map && d.depends_on) {
                                const parentValue = (strategyParams[d.depends_on] ?? '') as string
                                const depOptions = (d.options_map[parentValue] || []).map((opt: ParamOption) => ({
                                  value: opt.value,
                                  label: opt.label,
                                }))
                                const currentValue = strategyParams[key] ?? ''
                                const isValid = depOptions.some(opt => opt.value === currentValue)
                                const displayValue = isValid ? String(currentValue) : (depOptions[0]?.value ?? '')
                                return (
                                  <div key={key}>
                                    <label className="block text-xs text-gray-500 mb-1" title={d.description}>{d.label}</label>
                                    <FilterDropdown
                                      value={displayValue}
                                      onChange={val => setStrategyParams(prev => ({ ...prev, [key]: val }))}
                                      options={depOptions}
                                      ariaLabel={d.label}
                                    />
                                  </div>
                                )
                              }
                              return null
                            })}
                          </div>
                        )}

                        {/* Special fields: Prompt + Temperature slider */}
                        {otherEntries
                          .filter(([, def]) => {
                            const d = def as ParamDef
                            return d.type === 'textarea' || (d.type === 'float' && d.min !== undefined && d.max !== undefined && d.max <= 1)
                          })
                          .map(([key, def]) => {
                            const d = def as ParamDef
                            if (d.type === 'textarea') {
                              return (
                                <div key={key}>
                                  <label className="block text-xs text-gray-500 mb-1" title={d.description}>{d.label}</label>
                                  <textarea
                                    value={strategyParams[key] ?? ''}
                                    onChange={e => setStrategyParams(prev => ({ ...prev, [key]: e.target.value }))}
                                    rows={6}
                                    placeholder="Eigene Anweisungen für die KI-Analyse eingeben..."
                                    className="filter-select w-full text-sm font-mono !h-auto"
                                  />
                                </div>
                              )
                            }
                            const val = strategyParams[key] ?? d.default
                            return (
                              <div key={key} className="max-w-sm">
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
                                <p className="text-[11px] text-gray-600 mt-0.5">
                                  Niedrig = konsistente Antworten · Hoch = kreativere Analysen · Empfohlen: 0.2–0.4
                                </p>
                              </div>
                            )
                          })}

                        {/* Number inputs in 2-column grid */}
                        {(() => {
                          const numberEntries = otherEntries.filter(([, def]) => {
                            const d = def as ParamDef
                            return d.type !== 'textarea' && !(d.type === 'float' && d.min !== undefined && d.max !== undefined && d.max <= 1)
                          })
                          if (numberEntries.length === 0) return null
                          return (
                            <div className="grid grid-cols-2 gap-3">
                              {numberEntries.map(([key, def]) => {
                                const d = def as ParamDef
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
                                      className="filter-select w-full text-sm"
                                    />
                                  </div>
                                )
                              })}
                            </div>
                          )
                        })()}
                      </>
                    )
                  })()}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Step 2b: Data Sources */}
        {currentStepKey === 'step2b' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <label className="block text-sm text-gray-400">{b.dataSources || 'Data Sources'}</label>
                <p className="text-xs text-gray-500 mt-0.5">
                  {selectedSources.length} {b.sourcesSelected || 'sources selected'}
                </p>
              </div>
              <div className="flex items-center gap-1 bg-white/5 rounded-lg p-0.5">
                <button
                  type="button"
                  onClick={() => setSourcesView('grid')}
                  className={`p-1.5 rounded-md transition-colors ${sourcesView === 'grid' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
                  title="Kacheln"
                >
                  <LayoutGrid size={14} />
                </button>
                <button
                  type="button"
                  onClick={() => setSourcesView('list')}
                  className={`p-1.5 rounded-md transition-colors ${sourcesView === 'list' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
                  title="Liste"
                >
                  <List size={14} />
                </button>
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
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Icon size={15} className="text-gray-400" />
                      <span className="text-sm font-medium text-gray-300">{catLabel}</span>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => selectAllInCategory(cat)}
                        className={`text-xs px-2 py-0.5 rounded ${allSelected ? 'text-gray-600' : 'text-primary-400 hover:text-primary-300'}`}
                        disabled={allSelected}
                      >
                        {b.selectAll || 'Select All'}
                      </button>
                      <button
                        onClick={() => clearCategory(cat)}
                        className="text-xs px-2 py-0.5 rounded text-gray-500 hover:text-gray-400"
                      >
                        {b.clearAll || 'Clear'}
                      </button>
                    </div>
                  </div>

                  {sourcesView === 'grid' ? (
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 mb-4">
                      {sources.map(src => {
                        const isSelected = selectedSources.includes(src.id)
                        return (
                          <button
                            key={src.id}
                            onClick={() => toggleSource(src.id)}
                            className={`text-left px-3 py-2.5 rounded-xl border transition-all duration-200 ${
                              isSelected
                                ? 'border-green-400/70 bg-green-950/30 shadow-[0_0_10px_rgba(74,222,128,0.1)]'
                                : 'border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]'
                            }`}
                          >
                            <div className={`text-sm font-medium ${isSelected ? 'text-green-300' : 'text-white'}`}>
                              {src.name}
                            </div>
                            <div className="text-xs text-gray-500 mt-0.5 line-clamp-2">{src.description}</div>
                          </button>
                        )
                      })}
                    </div>
                  ) : (
                    <div className="space-y-1 mb-4">
                      {sources.map(src => {
                        const isSelected = selectedSources.includes(src.id)
                        return (
                          <button
                            key={src.id}
                            onClick={() => toggleSource(src.id)}
                            className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl border transition-all duration-200 ${
                              isSelected
                                ? 'border-green-400/70 bg-green-950/30'
                                : 'border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]'
                            }`}
                          >
                            <div className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                              isSelected ? 'border-green-400 bg-green-500/20' : 'border-gray-600'
                            }`}>
                              {isSelected && <Check size={11} className="text-green-400" />}
                            </div>
                            <span className={`text-sm font-medium ${isSelected ? 'text-green-300' : 'text-white'}`}>
                              {src.name}
                            </span>
                            <span className="text-xs text-gray-500 truncate ml-auto">{src.provider}</span>
                          </button>
                        )
                      })}
                    </div>
                  )}
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
              <div className="flex flex-wrap gap-1.5">
                {activePairs.map(pair => {
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

            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs text-gray-500 mb-1.5">{b.leverage}</label>
                <input type="number" value={leverage} onChange={e => setLeverage(parseInt(e.target.value) || 1)} min={1} max={20}
                  className="filter-select w-full text-sm tabular-nums" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1.5">{b.positionSize}</label>
                <input type="number" value={positionSize} onChange={e => setPositionSize(parseFloat(e.target.value) || 1)} min={1} max={25} step={0.5}
                  className="filter-select w-full text-sm tabular-nums" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1.5">{b.maxTrades}</label>
                <input type="number" value={maxTrades} onChange={e => setMaxTrades(parseInt(e.target.value) || 1)} min={1} max={10}
                  className="filter-select w-full text-sm tabular-nums" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1.5">{b.takeProfit}</label>
                <input type="number" value={takeProfit} onChange={e => setTakeProfit(parseFloat(e.target.value) || 0.5)} min={0.5} max={20} step={0.5}
                  className="filter-select w-full text-sm tabular-nums" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1.5">{b.stopLoss}</label>
                <input type="number" value={stopLoss} onChange={e => setStopLoss(parseFloat(e.target.value) || 0.5)} min={0.5} max={10} step={0.5}
                  className="filter-select w-full text-sm tabular-nums" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1.5">{b.dailyLossLimit}</label>
                <input type="number" value={dailyLossLimit} onChange={e => setDailyLossLimit(parseFloat(e.target.value) || 1)} min={1} max={20} step={0.5}
                  className="filter-select w-full text-sm tabular-nums" />
              </div>
            </div>
          </div>
        )}

        {/* Step 4: Exchange & Mode */}
        {currentStepKey === 'step4' && (
          <div className="space-y-6">
            <div>
              <label className="block text-sm text-gray-400 mb-2">{b.exchange}</label>
              <div className="flex gap-2">
                {EXCHANGES.map(ex => {
                  const active = exchangeType === ex
                  return (
                    <button key={ex} onClick={() => setExchangeType(ex)}
                      className={`px-4 py-2 rounded-xl border transition-all ${
                        active
                          ? 'border-primary-500 bg-primary-500/10 text-white ring-1 ring-primary-500/30'
                          : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-white/20 hover:bg-white/[0.06]'
                      }`}>
                      <ExchangeLogo exchange={ex} size={16} />
                    </button>
                  )
                })}
              </div>
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-2">{b.mode}</label>
              <div className="flex gap-2">
                {(['demo', 'live', 'both'] as const).map(m => {
                  const active = mode === m
                  const colorMap = {
                    demo: active ? 'border-blue-500 bg-blue-500/10 text-blue-400 ring-1 ring-blue-500/30' : '',
                    live: active ? 'border-orange-500 bg-orange-500/10 text-orange-400 ring-1 ring-orange-500/30' : '',
                    both: active ? 'border-purple-500 bg-purple-500/10 text-purple-400 ring-1 ring-purple-500/30' : '',
                  }
                  return (
                    <button key={m} onClick={() => setMode(m)}
                      className={`px-4 py-2 rounded-xl border transition-all ${
                        active
                          ? colorMap[m]
                          : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-white/20 hover:bg-white/[0.06]'
                      }`}>
                      {b[m]}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Notifications section */}
            <div className="pt-4 border-t border-white/5">
              <label className="block text-sm text-gray-400 mb-3">{t('settings.notifications')}</label>

              {/* Discord */}
              <div className="mb-4">
                <label className="block text-xs text-gray-500 mb-1.5">{t('bots.builder.discordWebhook')}</label>
                <input
                  type="url"
                  value={discordWebhookUrl}
                  onChange={e => setDiscordWebhookUrl(e.target.value)}
                  placeholder="https://discord.com/api/webhooks/..."
                  className="filter-select w-full text-sm"
                />
                <p className="text-xs text-gray-500 mt-1">{t('bots.builder.discordWebhookHint')}</p>
              </div>

              {/* Telegram */}
              <div className="space-y-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1.5">{t('bots.builder.telegramToken')}</label>
                  <input
                    type="password"
                    value={telegramBotToken}
                    onChange={e => setTelegramBotToken(e.target.value)}
                    placeholder="6123456789:ABCdef..."
                    className="filter-select w-full text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1.5">{t('bots.builder.telegramChatId')}</label>
                  <input
                    type="text"
                    value={telegramChatId}
                    onChange={e => setTelegramChatId(e.target.value)}
                    placeholder="123456789"
                    className="filter-select w-full text-sm"
                  />
                </div>
                <div className="bg-blue-900/20 border border-blue-800/50 rounded-xl p-2.5">
                  <p className="text-xs text-blue-300">{t('bots.builder.telegramHint')}</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Step 5: Schedule */}
        {currentStepKey === 'step5' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <label className="block text-sm text-gray-400">{b.schedule}</label>
              <div className="flex items-center gap-1 bg-white/5 rounded-lg p-0.5">
                <button type="button" onClick={() => setScheduleView('grid')}
                  className={`p-1.5 rounded-md transition-colors ${scheduleView === 'grid' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}>
                  <LayoutGrid size={14} />
                </button>
                <button type="button" onClick={() => setScheduleView('list')}
                  className={`p-1.5 rounded-md transition-colors ${scheduleView === 'list' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}>
                  <List size={14} />
                </button>
              </div>
            </div>

            {scheduleView === 'grid' ? (
              <div className="grid grid-cols-2 gap-2">
                {(['rotation_only', 'market_sessions', 'interval', 'custom_cron'] as const).map(st => {
                  const labelMap: Record<string, string> = {
                    rotation_only: b.rotationOnly || 'Trade Rotation Only',
                    market_sessions: b.marketSessions,
                    interval: b.interval,
                    custom_cron: b.customCron,
                  }
                  const descMap: Record<string, string> = {
                    rotation_only: b.rotationOnlyDesc || 'Auto-close and reopen at intervals',
                    market_sessions: '01, 08, 14, 21h UTC',
                    interval: '',
                    custom_cron: '',
                  }
                  const isSelected = scheduleType === st
                  return (
                    <button key={st} onClick={() => { setScheduleType(st); if (st === 'rotation_only') setRotationEnabled(true) }}
                      className={`text-left p-3 rounded-xl border transition-all ${
                        isSelected
                          ? 'border-primary-500 bg-primary-500/10 ring-1 ring-primary-500/30'
                          : 'border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]'
                      }`}>
                      <div className={`text-sm font-medium ${isSelected ? 'text-primary-400' : 'text-white'}`}>{labelMap[st]}</div>
                      {descMap[st] && <div className="text-xs text-gray-500 mt-0.5 line-clamp-2">{descMap[st]}</div>}
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="space-y-1">
                {(['rotation_only', 'market_sessions', 'interval', 'custom_cron'] as const).map(st => {
                  const labelMap: Record<string, string> = {
                    rotation_only: b.rotationOnly || 'Trade Rotation Only',
                    market_sessions: b.marketSessions,
                    interval: b.interval,
                    custom_cron: b.customCron,
                  }
                  const isSelected = scheduleType === st
                  return (
                    <button key={st} onClick={() => { setScheduleType(st); if (st === 'rotation_only') setRotationEnabled(true) }}
                      className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl border transition-all ${
                        isSelected
                          ? 'border-primary-500 bg-primary-500/10 ring-1 ring-primary-500/30'
                          : 'border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]'
                      }`}>
                      {isSelected && <Check size={14} className="text-primary-400 shrink-0" />}
                      <div className={`text-sm font-medium ${isSelected ? 'text-primary-400' : 'text-white'}`}>{labelMap[st]}</div>
                    </button>
                  )
                })}
              </div>
            )}

            {scheduleType === 'interval' && (
              <div className="mt-2">
                <label className="block text-xs text-gray-500 mb-1.5">{b.intervalMinutes}</label>
                <input type="number" value={intervalMinutes} onChange={e => setIntervalMinutes(parseInt(e.target.value) || 5)} min={5} max={1440}
                  className="filter-select w-36 text-sm tabular-nums" />
              </div>
            )}

            {scheduleType === 'custom_cron' && (
              <div className="mt-2">
                <label className="block text-xs text-gray-500 mb-2">{b.customHours}</label>
                <div className="grid grid-cols-8 gap-1.5">
                  {Array.from({ length: 24 }, (_, i) => {
                    const active = customHours.includes(i)
                    return (
                      <button key={i} onClick={() => toggleHour(i)}
                        className={`h-8 text-xs rounded-lg border transition-all ${
                          active
                            ? 'border-primary-500 bg-primary-500/15 text-primary-400 ring-1 ring-primary-500/30'
                            : 'border-white/10 bg-white/[0.03] text-gray-500 hover:border-white/20 hover:bg-white/[0.06] hover:text-gray-300'
                        }`}>
                        {String(i).padStart(2, '0')}h
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Trade Rotation toggle */}
            {scheduleType !== 'rotation_only' && (
              <div className="mt-4 pt-4 border-t border-white/5">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-sm text-gray-300">{b.tradeRotation || 'Trade Rotation'}</span>
                    <p className="text-xs text-gray-500 mt-0.5">{b.tradeRotationDesc || 'Auto-close and reopen trades at fixed intervals'}</p>
                  </div>
                  <button onClick={() => setRotationEnabled(!rotationEnabled)}
                    className={`relative w-11 h-6 rounded-full transition-colors ${rotationEnabled ? 'bg-primary-600' : 'bg-gray-700'}`}>
                    <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${rotationEnabled ? 'translate-x-5' : ''}`} />
                  </button>
                </div>
              </div>
            )}

            {/* Rotation settings */}
            {(scheduleType === 'rotation_only' || rotationEnabled) && (
              <div className="space-y-3 mt-3">
                <div className="flex flex-wrap gap-1.5">
                  {[
                    { label: '5m', value: 5 }, { label: '15m', value: 15 },
                    { label: '30m', value: 30 }, { label: '1h', value: 60 },
                    { label: '4h', value: 240 }, { label: '8h', value: 480 },
                    { label: '12h', value: 720 }, { label: '24h', value: 1440 },
                  ].map(preset => (
                    <button key={preset.value} onClick={() => setRotationMinutes(preset.value)}
                      className={`px-3 py-1.5 text-xs rounded-lg border transition-all ${
                        rotationMinutes === preset.value
                          ? 'border-primary-500 bg-primary-500/15 text-primary-400 ring-1 ring-primary-500/30'
                          : 'border-white/10 bg-white/[0.03] text-gray-500 hover:border-white/20 hover:bg-white/[0.06] hover:text-gray-300'
                      }`}>
                      {preset.label}
                    </button>
                  ))}
                </div>

                <div className="flex gap-4">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1.5">{b.customMinutes || 'Custom (minutes)'}</label>
                    <input type="number" value={rotationMinutes}
                      onChange={e => setRotationMinutes(Math.max(5, parseInt(e.target.value) || 5))}
                      min={5} max={10080}
                      className="filter-select w-36 text-sm tabular-nums" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1.5">{b.rotationStartTime || 'Start Time (UTC)'}</label>
                    <input type="time" value={rotationStartTime}
                      onChange={e => setRotationStartTime(e.target.value)}
                      className="filter-select w-36 text-sm" />
                  </div>
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
                {scheduleType === 'rotation_only' ? (b.rotationOnly || 'Rotation Only') :
                 scheduleType === 'interval' ? `Every ${intervalMinutes}min` :
                 scheduleType === 'custom_cron' ? customHours.map(h => `${h}:00`).join(', ') :
                 '01:00, 08:00, 14:00, 21:00 UTC'}
              </span></div>
              {(rotationEnabled || scheduleType === 'rotation_only') && (
                <div><span className="text-gray-500">{b.tradeRotation || 'Rotation'}:</span> <span className="text-white ml-2">
                  {rotationMinutes >= 60 ? `${rotationMinutes / 60}h` : `${rotationMinutes}min`}
                  {rotationStartTime ? ` (${b.rotationStartTime || 'Start'}: ${rotationStartTime} UTC)` : ''}
                </span></div>
              )}
            </div>
          </div>
        )}
      </div>

      {validationErrors.length > 0 && (
        <div className="mb-4 p-3 bg-amber-900/30 border border-amber-800 rounded text-amber-400 text-sm space-y-1">
          {validationErrors.map((err, i) => <div key={i}>{err}</div>)}
        </div>
      )}

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
              onClick={handleNext}
              className="flex items-center gap-1 px-4 py-2 text-sm bg-primary-600 text-white rounded font-medium hover:bg-primary-700 transition-colors"
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
