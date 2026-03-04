import { useState, useEffect, useMemo } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import api from '../../api/client'
import { getApiErrorMessage } from '../../utils/api-error'
import { useToastStore } from '../../stores/toastStore'
import { ArrowLeft, ArrowRight, Check, Play, Brain, TrendingUp, BarChart3, DollarSign, Activity, Building, LayoutGrid, List, Bot, Info, Zap, Clock, AlertTriangle, Wallet } from 'lucide-react'
import ExchangeLogo from '../ui/ExchangeLogo'
import FilterDropdown from '../ui/FilterDropdown'
import NumInput from '../ui/NumInput'

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

interface BalancePreview {
  exchange_type: string
  mode: string
  currency: string
  exchange_balance: number
  exchange_equity: number
  existing_allocated_pct: number
  existing_allocated_amount: number
  remaining_balance: number
  has_connection: boolean
  error: string | null
}

interface SymbolConflict {
  symbol: string
  existing_bot_id: number
  existing_bot_name: string
  existing_bot_mode: string
}

interface BotBuilderProps {
  botId?: number | null
  onDone: () => void
  onCancel: () => void
}

// Strategies that use market data and should show the data sources step
const DATA_STRATEGIES = ['llm_signal', 'sentiment_surfer', 'liquidation_hunter', 'degen', 'edge_indicator', 'contrarian_pulse']

// Fixed data sources for non-LLM strategies (these strategies use hardcoded sources internally)
const FIXED_STRATEGY_SOURCES: Record<string, string[]> = {
  sentiment_surfer: [
    'fear_greed', 'news_sentiment', 'vwap', 'supertrend', 'spot_volume', 'spot_price', 'oiwap',
  ],
  liquidation_hunter: [
    'fear_greed', 'long_short_ratio', 'funding_rate', 'open_interest', 'spot_price',
  ],
  degen: [
    'spot_price', 'fear_greed', 'news_sentiment', 'funding_rate', 'open_interest',
    'long_short_ratio', 'order_book', 'liquidations', 'supertrend', 'vwap',
    'oiwap', 'spot_volume', 'volatility', 'coingecko_market',
  ],
  edge_indicator: [
    'spot_price', 'vwap', 'supertrend', 'spot_volume', 'volatility',
  ],
  contrarian_pulse: [
    'fear_greed', 'spot_price', 'spot_volume', 'cvd', 'long_short_ratio',
    'open_interest', 'funding_rate',
  ],
}

const STRATEGY_DISPLAY_NAMES: Record<string, string> = {
  llm_signal: 'KI-Companion',
  sentiment_surfer: 'Sentiment Surfer',
  liquidation_hunter: 'Liquidation Hunter',
  degen: 'Degen',
  edge_indicator: 'Edge Indicator',
  contrarian_pulse: 'Contrarian Pulse',
}

// Strategy descriptions are now sourced from i18n keys: bots.builder.strategyDesc_{name}

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

// Backtest-based timeframe recommendations (90-day BTCUSDT backtest)
const STRATEGY_RECOMMENDATIONS: Record<string, { bestTimeframe: string }> = {
  edge_indicator: { bestTimeframe: '1h' },
}

const EXCHANGES = ['bitget', 'weex', 'hyperliquid', 'bitunix', 'bingx']
const PAIRS_CEX = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'AVAXUSDT']
const PAIRS_BINGX = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT', 'DOGE-USDT', 'AVAX-USDT']
const PAIRS_HL = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'AVAX']

export default function BotBuilder({ botId, onDone, onCancel }: BotBuilderProps) {
  const { t } = useTranslation()
  const { addToast } = useToastStore()
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
  const [marginMode, setMarginMode] = useState<'cross' | 'isolated'>('cross')
  const [tradingPairs, setTradingPairs] = useState<string[]>(['BTCUSDT'])
  const [maxTrades, setMaxTrades] = useState<number | null>(null)
  const [dailyLossLimit, setDailyLossLimit] = useState<number | null>(null)
  const [perAssetConfig, setPerAssetConfig] = useState<Record<string, { position_pct?: number; leverage?: number; tp?: number; sl?: number; max_trades?: number; loss_limit?: number }>>({})
  const [scheduleType, setScheduleType] = useState('market_sessions')
  const [intervalMinutes, setIntervalMinutes] = useState(60)
  const [customHours, setCustomHours] = useState<number[]>([])
  const [rotationEnabled, setRotationEnabled] = useState(false)
  const [rotationMinutes, setRotationMinutes] = useState(60)
  const [rotationStartTime, setRotationStartTime] = useState('08:00')
  const [discordWebhookUrl, setDiscordWebhookUrl] = useState('')
  const [telegramBotToken, setTelegramBotToken] = useState('')
  const [telegramChatId, setTelegramChatId] = useState('')
  const [whatsappPhoneId, setWhatsappPhoneId] = useState('')
  const [whatsappToken, setWhatsappToken] = useState('')
  const [whatsappRecipient, setWhatsappRecipient] = useState('')

  // Symbol conflicts
  const [symbolConflicts, setSymbolConflicts] = useState<SymbolConflict[]>([])

  // Balance preview for Step 3
  const [balancePreview, setBalancePreview] = useState<BalancePreview | null>(null)
  const [balanceOverview, setBalanceOverview] = useState<BalancePreview[]>([])
  const [overviewLoading, setOverviewLoading] = useState(false)

  // View modes for strategy, data sources, and schedule
  const [strategyView, setStrategyView] = useState<'grid' | 'list'>('grid')
  const [sourcesView, setSourcesView] = useState<'grid' | 'list'>('grid')
  const [scheduleView, setScheduleView] = useState<'grid' | 'list'>('grid')

  // Pro Mode: show data source customization for fixed-source strategies
  const [proMode, setProMode] = useState(() => localStorage.getItem('botBuilder_proMode') === 'true')

  // Presets
  const [presets, setPresets] = useState<Preset[]>([])
  const [selectedPresetId, setSelectedPresetId] = useState<number | null>(null)

  // Whether current strategy uses market data
  const usesData = DATA_STRATEGIES.includes(strategyType)
  // Fixed strategies have predetermined sources — no manual selection needed
  const hasFixedSources = !!FIXED_STRATEGY_SOURCES[strategyType]

  // Dynamic steps: insert data sources step only for LLM strategy (manual selection)
  const steps = useMemo(() => {
    if (usesData && !hasFixedSources) {
      return ['step1', 'step2', 'step2b', 'step3', 'step4', 'step5', 'step6'] as const
    }
    return ['step1', 'step2', 'step3', 'step4', 'step5', 'step6'] as const
  }, [usesData, hasFixedSources])

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
      }).catch((err) => { console.error('Failed to load presets:', err); addToast('error', 'Failed to load data') })
    }
  }, [isEdit])

  const applyPreset = (presetId: number) => {
    const preset = presets.find(p => p.id === presetId)
    if (!preset) return
    setSelectedPresetId(presetId)
    const tc = preset.trading_config || {}
    if (tc.max_trades_per_day) setMaxTrades(tc.max_trades_per_day)
    if (tc.daily_loss_limit_percent) setDailyLossLimit(tc.daily_loss_limit_percent)
    // Apply strategy params — preserve data_sources
    if (preset.strategy_config && Object.keys(preset.strategy_config).length > 0) {
      setStrategyParams(prev => {
        const { data_sources, ...rest } = prev
        return { ...rest, ...preset.strategy_config, ...(data_sources ? { data_sources } : {}) }
      })
    }
    // Apply trading pairs (convert based on current exchange)
    if (preset.trading_pairs && preset.trading_pairs.length > 0) {
      const converted = preset.trading_pairs.map(p => {
        const base = p.replace(/[-](USDT|USDC)$/i, '').replace(/(USDT|USDC)$/i, '')
        if (isHyperliquid) return base
        if (isBingx) return `${base}-USDT`
        return base + 'USDT'
      })
      setTradingPairs(converted)
    }
    // Apply per-asset config from preset
    if (tc.per_asset_config && typeof tc.per_asset_config === 'object') {
      setPerAssetConfig(tc.per_asset_config)
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
    }).catch((err) => { console.error('Failed to load data sources:', err); addToast('error', 'Failed to load data') })
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
        setMarginMode(d.margin_mode || 'cross')
        setTradingPairs(d.trading_pairs)
        setMaxTrades(d.max_trades_per_day ?? null)
        setDailyLossLimit(d.daily_loss_limit_percent ?? null)
        if (d.per_asset_config) setPerAssetConfig(d.per_asset_config)
        setScheduleType(d.schedule_type)
        if (d.schedule_config) {
          if (d.schedule_config.interval_minutes) setIntervalMinutes(d.schedule_config.interval_minutes)
          if (d.schedule_config.hours) setCustomHours(d.schedule_config.hours)
        }
        if (d.rotation_enabled) setRotationEnabled(true)
        if (d.rotation_interval_minutes) setRotationMinutes(d.rotation_interval_minutes)
        if (d.rotation_start_time) setRotationStartTime(d.rotation_start_time)
        // Restore selected data sources from strategy_params
        // Fixed strategies always use their predetermined sources
        if (FIXED_STRATEGY_SOURCES[d.strategy_type]) {
          setSelectedSources(FIXED_STRATEGY_SOURCES[d.strategy_type])
        } else if (d.strategy_params?.data_sources) {
          setSelectedSources(d.strategy_params.data_sources)
        } else if (defaultSourceIds.length > 0) {
          setSelectedSources(defaultSourceIds)
        }
      })
    }
  }, [botId, isEdit, defaultSourceIds])

  const isHyperliquid = exchangeType === 'hyperliquid'
  const isBingx = exchangeType === 'bingx'
  const activePairs = isHyperliquid ? PAIRS_HL : isBingx ? PAIRS_BINGX : PAIRS_CEX

  const selectedStrategy = strategies.find(s => s.name === strategyType)

  const toggleProMode = () => {
    const next = !proMode
    setProMode(next)
    localStorage.setItem('botBuilder_proMode', String(next))
    // Reset to fixed sources when disabling Pro Mode
    if (!next && FIXED_STRATEGY_SOURCES[strategyType]) {
      setSelectedSources(FIXED_STRATEGY_SOURCES[strategyType])
    }
  }

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
    // Auto-set fixed data sources for non-LLM strategies
    if (FIXED_STRATEGY_SOURCES[name]) {
      setSelectedSources(FIXED_STRATEGY_SOURCES[name])
    } else {
      setSelectedSources([])
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
      // Strip any suffix/format to get the base symbol
      const base = p.replace(/[-](USDT|USDC)$/i, '').replace(/(USDT|USDC)$/i, '')
      if (isHyperliquid) {
        return base
      } else if (isBingx) {
        return `${base}-USDT`
      } else {
        return base + 'USDT'
      }
    }))
  }, [exchangeType]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch exchange balance preview when exchange/mode changes
  useEffect(() => {
    const effectiveMode = mode === 'both' ? 'both' : mode
    const params = new URLSearchParams({ exchange_type: exchangeType, mode: effectiveMode })
    if (isEdit && botId) params.append('exclude_bot_id', String(botId))
    api.get(`/bots/balance-preview?${params}`)
      .then(res => setBalancePreview(res.data))
      .catch(() => setBalancePreview(null))
  }, [exchangeType, mode, botId, isEdit])

  // Fetch symbol conflicts when exchange, mode, or pairs change
  useEffect(() => {
    if (tradingPairs.length === 0) {
      setSymbolConflicts([])
      return
    }
    const params = new URLSearchParams({
      exchange_type: exchangeType,
      mode,
      trading_pairs: tradingPairs.join(','),
    })
    if (isEdit && botId) params.append('exclude_bot_id', String(botId))
    api.get(`/bots/symbol-conflicts?${params}`)
      .then(res => setSymbolConflicts(res.data.conflicts || []))
      .catch(() => setSymbolConflicts([]))
  }, [exchangeType, mode, tradingPairs, botId, isEdit])

  // Fetch balance overview for all exchanges once
  useEffect(() => {
    setOverviewLoading(true)
    const params = new URLSearchParams()
    if (isEdit && botId) params.append('exclude_bot_id', String(botId))
    api.get(`/bots/balance-overview?${params}`)
      .then(res => setBalanceOverview(res.data.exchanges || []))
      .catch(() => setBalanceOverview([]))
      .finally(() => setOverviewLoading(false))
  }, [botId, isEdit])

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

    // Build per_asset_config (filter out empty entries)
    const filteredPerAsset: Record<string, Record<string, number>> = {}
    for (const [symbol, cfg] of Object.entries(perAssetConfig)) {
      const clean: Record<string, number> = {}
      if (cfg.position_pct != null && cfg.position_pct > 0) clean.position_pct = cfg.position_pct
      if (cfg.leverage != null && cfg.leverage > 0) clean.leverage = cfg.leverage
      if (cfg.tp != null && cfg.tp > 0) clean.tp = cfg.tp
      if (cfg.sl != null && cfg.sl > 0) clean.sl = cfg.sl
      if (cfg.max_trades != null && cfg.max_trades > 0) clean.max_trades = cfg.max_trades
      if (cfg.loss_limit != null && cfg.loss_limit > 0) clean.loss_limit = cfg.loss_limit
      if (Object.keys(clean).length > 0) filteredPerAsset[symbol] = clean
    }

    return {
      name,
      description: description || undefined,
      strategy_type: strategyType,
      exchange_type: exchangeType,
      mode,
      margin_mode: marginMode,
      trading_pairs: tradingPairs,
      max_trades_per_day: maxTrades || undefined,
      daily_loss_limit_percent: dailyLossLimit || undefined,
      per_asset_config: Object.keys(filteredPerAsset).length > 0 ? filteredPerAsset : undefined,
      strategy_params: params,
      schedule_type: scheduleType,
      schedule_config: isRotationOnly ? null : scheduleConfig,
      rotation_enabled: effectiveRotation,
      rotation_interval_minutes: effectiveRotation ? rotationMinutes : null,
      rotation_start_time: effectiveRotation ? rotationStartTime : null,
      discord_webhook_url: discordWebhookUrl || undefined,
      telegram_bot_token: telegramBotToken || undefined,
      telegram_chat_id: telegramChatId || undefined,
      whatsapp_phone_id: whatsappPhoneId || undefined,
      whatsapp_token: whatsappToken || undefined,
      whatsapp_recipient: whatsappRecipient || undefined,
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
    } catch (err) {
      setError(getApiErrorMessage(err, t('common.saveFailed')))
    }
    setSaving(false)
  }

  const getStepErrors = (stepKey: string): string[] => {
    const errors: string[] = []
    if (stepKey === 'step1' && !name.trim()) errors.push(t('bots.builder.errors.nameRequired'))
    if (stepKey === 'step2' && !strategyType) errors.push(t('bots.builder.errors.strategyRequired'))
    if (stepKey === 'step2b' && !hasFixedSources && selectedSources.length === 0) errors.push(t('bots.builder.errors.dataSourcesRequired'))
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
                    title={b.viewGrid}
                  >
                    <LayoutGrid size={14} />
                  </button>
                  <button
                    type="button"
                    onClick={() => setStrategyView('list')}
                    className={`p-1.5 rounded-md transition-colors ${strategyView === 'list' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
                    title={b.viewList}
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
                          {['llm_signal', 'degen'].includes(s.name) && <Bot size={14} className="text-emerald-400" />}
                        </div>
                        <div className="text-xs text-gray-500 mt-1 line-clamp-2">
                          {t(`bots.builder.strategyDesc_${s.name}`, { defaultValue: s.description })}
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
                        className={`w-full flex flex-col gap-1 px-3 py-2.5 rounded-xl border transition-all text-left ${
                          isSelected
                            ? 'border-primary-500 bg-primary-500/10 ring-1 ring-primary-500/30'
                            : 'border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]'
                        }`}
                      >
                        <div className="flex items-center gap-1.5">
                          {isSelected && <Check size={14} className="text-primary-400 shrink-0" />}
                          <span className={`text-sm font-medium ${isSelected ? 'text-primary-400' : 'text-white'}`}>
                            {getStrategyDisplayName(s.name)}
                          </span>
                          {['llm_signal', 'degen'].includes(s.name) && <Bot size={14} className="text-emerald-400" />}
                        </div>
                        <p className="text-xs text-gray-500 leading-relaxed">
                          {t(`bots.builder.strategyDesc_${s.name}`, { defaultValue: s.description })}
                        </p>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>

            {/* LLM info banner */}
            {(strategyType === 'llm_signal' || strategyType === 'degen') && (
              <div className="bg-blue-900/20 border border-blue-800 rounded-lg p-3">
                <p className="text-xs text-blue-300">{b.llmNote}</p>
              </div>
            )}

            {/* Strategy Recommendations from Backtest */}
            {strategyType && strategyType === 'edge_indicator' && STRATEGY_RECOMMENDATIONS[strategyType] && (
              <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-primary-500/10 border border-primary-500/20">
                <Clock size={14} className="text-primary-400 shrink-0" />
                <span className="text-xs text-primary-300">
                  <Trans i18nKey="bots.builder.recommendedTimeframe" values={{ timeframe: STRATEGY_RECOMMENDATIONS[strategyType].bestTimeframe }} components={{ strong: <strong /> }} />
                </span>
                <span className="text-[10px] text-gray-500 ml-auto">{t('bots.builder.backtestDays')}</span>
              </div>
            )}

            {selectedStrategy && Object.keys(selectedStrategy.param_schema).length > 0 && (() => {
              const selectEntries = Object.entries(selectedStrategy.param_schema).filter(
                ([, def]) => (def as ParamDef).type === 'select' || (def as ParamDef).type === 'dependent_select'
              )
              const textareaEntries = Object.entries(selectedStrategy.param_schema).filter(
                ([, def]) => (def as ParamDef).type === 'textarea'
              )
              // All non-select, non-textarea params go behind Pro Mode
              const proModeEntries = Object.entries(selectedStrategy.param_schema).filter(
                ([, def]) => {
                  const d = def as ParamDef
                  return d.type !== 'select' && d.type !== 'dependent_select' && d.type !== 'textarea'
                }
              )
              const hasAlwaysVisible = selectEntries.length > 0 || textareaEntries.length > 0
              const hasProParams = proModeEntries.length > 0

              return (
                <div>
                  {/* Always visible: LLM provider/model selects + custom prompt textarea */}
                  {hasAlwaysVisible && (
                    <div className="space-y-3">
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
                                  <label className="block text-xs text-gray-500 mb-1">{d.label}</label>
                                  <FilterDropdown
                                    value={String(strategyParams[key] ?? d.default)}
                                    onChange={val => setStrategyParams(prev => ({ ...prev, [key]: val }))}
                                    options={selectOptions}
                                    ariaLabel={d.label}
                                  />
                                  {d.description && <p className="text-[10px] text-gray-600 mt-1">{d.description}</p>}
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
                                  <label className="block text-xs text-gray-500 mb-1">{d.label}</label>
                                  <FilterDropdown
                                    value={displayValue}
                                    onChange={val => setStrategyParams(prev => ({ ...prev, [key]: val }))}
                                    options={depOptions}
                                    ariaLabel={d.label}
                                  />
                                  {d.description && <p className="text-[10px] text-gray-600 mt-1">{d.description}</p>}
                                </div>
                              )
                            }
                            return null
                          })}
                        </div>
                      )}

                      {textareaEntries.map(([key, def]) => {
                        const d = def as ParamDef
                        return (
                          <div key={key}>
                            <label className="block text-xs text-gray-500 mb-1">{d.label}</label>
                            {d.description && <p className="text-[10px] text-gray-600 mb-1.5">{d.description}</p>}
                            <textarea
                              value={strategyParams[key] ?? ''}
                              onChange={e => setStrategyParams(prev => ({ ...prev, [key]: e.target.value }))}
                              rows={6}
                              placeholder={t('bots.builder.customPromptPlaceholder')}
                              className="filter-select w-full text-sm font-mono !h-auto"
                            />
                          </div>
                        )
                      })}
                    </div>
                  )}

                  {/* Pro Mode toggle — reveals ALL strategy params */}
                  {hasProParams && (
                    <div className={`${hasAlwaysVisible ? 'mt-6' : ''} border-t border-white/5 pt-4`}>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Zap size={15} className={proMode ? 'text-amber-400' : 'text-gray-500'} />
                          <div>
                            <span className="text-sm font-medium text-gray-300">Pro Mode</span>
                            <p className="text-xs text-gray-500">
                              {proMode
                                ? b.proModeParamsActiveHint
                                : b.proModeParamsHint}
                            </p>
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={toggleProMode}
                          className={`relative w-11 h-6 rounded-full transition-colors ${proMode ? 'bg-amber-500' : 'bg-gray-700'}`}
                        >
                          <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${proMode ? 'translate-x-5' : ''}`} />
                        </button>
                      </div>

                      {proMode && (() => {
                        const tempEntry = proModeEntries.find(([k]) => k === 'temperature')
                        const boolEntries = proModeEntries.filter(([, def]) => (def as ParamDef).type === 'bool')
                        const numericEntries = proModeEntries.filter(([k, def]) => {
                          const d = def as ParamDef
                          return k !== 'temperature' && d.type !== 'bool'
                        })

                        // Range position as percentage (0-100)
                        const rangePercent = (val: number, min: number, max: number) => {
                          if (max === min) return 50
                          return Math.max(0, Math.min(100, ((val - min) / (max - min)) * 100))
                        }

                        return (
                          <div className="mt-4 space-y-3">
                            {/* Temperature — dedicated slider */}
                            {tempEntry && (() => {
                              const [tKey, tDef] = tempEntry
                              const td = tDef as ParamDef
                              const tVal = Number(strategyParams[tKey] ?? td.default)
                              const pct = rangePercent(tVal, td.min ?? 0, td.max ?? 1)
                              return (
                                <div className="relative overflow-hidden rounded-lg bg-gradient-to-r from-gray-800/40 to-gray-800/20 px-3 py-2 max-w-md">
                                  <div className="flex items-center justify-between mb-1.5">
                                    <span className="text-[10px] font-medium text-gray-400 uppercase tracking-wider">{td.label}</span>
                                    <span className="text-xs font-mono font-semibold text-amber-400">{tVal.toFixed(1)}</span>
                                  </div>
                                  <div className="relative h-1.5 rounded-full bg-gray-900/60 overflow-hidden">
                                    <div
                                      className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-blue-500 via-amber-400 to-red-500 transition-all"
                                      style={{ width: `${pct}%` }}
                                    />
                                  </div>
                                  <input
                                    type="range" min={td.min} max={td.max} step={0.1} value={tVal}
                                    onChange={e => setStrategyParams(prev => ({ ...prev, [tKey]: parseFloat(e.target.value) }))}
                                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                                  />
                                  <div className="flex justify-between mt-1">
                                    <span className="text-[9px] text-gray-600">{t('bots.builder.deterministic')}</span>
                                    <span className="text-[9px] text-gray-600">{t('bots.builder.creative')}</span>
                                  </div>
                                </div>
                              )
                            })()}

                            {/* Bool toggles — compact inline pills */}
                            {boolEntries.length > 0 && (
                              <div className="flex flex-wrap gap-1.5">
                                {boolEntries.map(([key, def]) => {
                                  const d = def as ParamDef
                                  const isOn = strategyParams[key] ?? d.default
                                  return (
                                    <button
                                      key={key} type="button"
                                      onClick={() => setStrategyParams(prev => ({ ...prev, [key]: !isOn }))}
                                      title={d.description}
                                      className={`inline-flex items-center gap-1.5 pl-2 pr-2.5 py-1.5 rounded-full text-[11px] font-medium transition-all ${
                                        isOn
                                          ? 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/25'
                                          : 'bg-gray-800/40 text-gray-500 ring-1 ring-white/[0.04]'
                                      }`}
                                    >
                                      <span className={`w-1.5 h-1.5 rounded-full ${isOn ? 'bg-emerald-400' : 'bg-gray-600'}`} />
                                      {d.label}
                                    </button>
                                  )
                                })}
                              </div>
                            )}

                            {/* Numeric params — compact 2-col grid */}
                            {numericEntries.length > 0 && (
                              <div className="grid grid-cols-2 gap-2">
                                {numericEntries.map(([key, def]) => {
                                  const d = def as ParamDef
                                  const val = Number(strategyParams[key] ?? d.default)

                                  return (
                                    <div
                                      key={key}
                                      className="rounded-md bg-gray-800/30 px-2.5 py-2 border border-white/[0.04] hover:border-white/[0.08] transition-colors"
                                    >
                                      <label className="block text-[11px] text-gray-500 mb-1 truncate">{d.label}</label>
                                      <NumInput
                                        value={val}
                                        onChange={e => setStrategyParams(prev => ({ ...prev, [key]: parseFloat(e.target.value) || 0 }))}
                                        min={d.min}
                                        max={d.max}
                                        step={d.type === 'float' ? 0.0001 : 1}
                                        className="filter-select text-sm !w-full text-gray-200"
                                      />
                                      {d.description && <p className="text-[9px] text-gray-600 mt-1 leading-tight">{d.description}</p>}
                                    </div>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                        )
                      })()}
                    </div>
                  )}
                </div>
              )
            })()}
          </div>
        )}

        {/* Step 2b: Data Sources */}
        {currentStepKey === 'step2b' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <label className="block text-sm text-gray-400">{b.dataSources}</label>
                <p className="text-xs text-gray-500 mt-0.5">
                  {selectedSources.length} {b.sourcesSelected}
                </p>
              </div>
              <div className="flex items-center gap-1 bg-white/5 rounded-lg p-0.5">
                <button
                  type="button"
                  onClick={() => setSourcesView('grid')}
                  className={`p-1.5 rounded-md transition-colors ${sourcesView === 'grid' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
                  title={b.viewGrid}
                >
                  <LayoutGrid size={14} />
                </button>
                <button
                  type="button"
                  onClick={() => setSourcesView('list')}
                  className={`p-1.5 rounded-md transition-colors ${sourcesView === 'list' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
                  title={b.viewList}
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
                        {b.selectAll}
                      </button>
                      <button
                        onClick={() => clearCategory(cat)}
                        className="text-xs px-2 py-0.5 rounded text-gray-500 hover:text-gray-400"
                      >
                        {b.clearAll}
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
                            <div className="flex items-center justify-between gap-1">
                              <span className={`text-sm font-medium ${isSelected ? 'text-green-300' : 'text-white'}`}>
                                {src.name}
                              </span>
                              <span className="text-[10px] text-gray-500 shrink-0">{src.provider}</span>
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
            {/* Trading pairs */}
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

            {/* Exchange Balance Overview — all exchanges */}
            {(() => {
              if (overviewLoading) {
                return (
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 animate-pulse">
                    <div className="flex items-center gap-2">
                      <Wallet size={16} className="text-gray-500" />
                      <div className="h-4 w-32 bg-white/10 rounded" />
                    </div>
                  </div>
                )
              }
              if (balanceOverview.length === 0 && !overviewLoading) {
                return (
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 flex items-center gap-2">
                    <Wallet size={16} className="text-gray-500" />
                    <p className="text-sm text-gray-500">{t('bots.builder.noConnections')}</p>
                  </div>
                )
              }

              // Calculate this bot's allocation for warning on selected exchange
              const thisBotPct = tradingPairs.reduce((sum, p) => sum + (perAssetConfig[p]?.position_pct || 0), 0)
              const effectiveMode = mode === 'both' ? 'live' : mode
              const selectedEntry = balanceOverview.find(e => e.exchange_type === exchangeType && e.mode === effectiveMode)
              const totalPctWithThis = selectedEntry ? selectedEntry.existing_allocated_pct + thisBotPct : 0
              const thisBotAmount = selectedEntry && selectedEntry.exchange_equity > 0 ? selectedEntry.exchange_equity * thisBotPct / 100 : 0
              const isOverAllocated = totalPctWithThis > 100
              const isInsufficientBalance = selectedEntry ? thisBotAmount > selectedEntry.remaining_balance && thisBotPct > 0 : false

              return (
                <div className={`rounded-xl border p-4 ${
                  isOverAllocated ? 'border-amber-500/40 bg-amber-900/10' :
                  isInsufficientBalance ? 'border-amber-500/30 bg-amber-900/5' :
                  'border-white/[0.06] bg-white/[0.02]'
                }`}>
                  <div className="flex items-center gap-2 mb-3">
                    <Wallet size={16} className="text-primary-400" />
                    <span className="text-sm font-medium text-gray-300">{t('bots.builder.allExchanges')}</span>
                    {mode === 'both' && (
                      <span className="text-[10px] text-gray-500 ml-auto">{t('bots.builder.bothModeNote')}</span>
                    )}
                  </div>

                  {/* Compact table */}
                  <div className="overflow-hidden rounded-lg border border-white/[0.04]">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-white/[0.03] text-gray-500 text-[10px] uppercase tracking-wider">
                          <th className="text-left px-3 py-1.5 font-medium">{t('bots.builder.exchange')}</th>
                          <th className="text-left px-2 py-1.5 font-medium">{t('bots.builder.mode')}</th>
                          <th className="text-right px-2 py-1.5 font-medium">{t('bots.builder.equity')}</th>
                          <th className="text-right px-2 py-1.5 font-medium">{t('bots.builder.allocated')}</th>
                          <th className="text-right px-3 py-1.5 font-medium">{t('bots.builder.available')}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/[0.04]">
                        {balanceOverview.map(entry => {
                          const isSelected = entry.exchange_type === exchangeType && entry.mode === effectiveMode
                          const isOver = entry.existing_allocated_pct > 100
                          return (
                            <tr key={`${entry.exchange_type}-${entry.mode}`} className={`transition-colors ${
                              isSelected ? 'bg-primary-500/5' : 'hover:bg-white/[0.02]'
                            }`}>
                              <td className="px-3 py-2 flex items-center gap-1.5">
                                <ExchangeLogo exchange={entry.exchange_type} size={14} />
                                {isSelected && <span className="w-1 h-1 rounded-full bg-primary-400" />}
                              </td>
                              <td className="px-2 py-2">
                                <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                                  entry.mode === 'demo' ? 'bg-blue-500/10 text-blue-400' : 'bg-orange-500/10 text-orange-400'
                                }`}>
                                  {entry.mode.toUpperCase()}
                                </span>
                              </td>
                              <td className="px-2 py-2 text-right tabular-nums text-gray-300">
                                ${entry.exchange_equity.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                                <span className="text-gray-600 ml-0.5 text-[10px]">{entry.currency}</span>
                              </td>
                              <td className={`px-2 py-2 text-right tabular-nums ${isOver ? 'text-red-400' : 'text-amber-400'}`}>
                                {entry.existing_allocated_pct.toFixed(0)}%
                                <span className="text-gray-600 ml-1">(${entry.existing_allocated_amount.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })})</span>
                              </td>
                              <td className="px-3 py-2 text-right tabular-nums text-green-400">
                                ${entry.remaining_balance.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>

                  {/* Warnings for the selected exchange */}
                  {isOverAllocated && (
                    <div className="mt-3 flex items-center gap-1.5 text-xs text-amber-400">
                      <AlertTriangle size={13} />
                      {t('bots.builder.overAllocatedWarning', { pct: totalPctWithThis.toFixed(0) })}
                    </div>
                  )}
                  {!isOverAllocated && isInsufficientBalance && (
                    <div className="mt-3 flex items-center gap-1.5 text-xs text-amber-400">
                      <AlertTriangle size={13} />
                      {t('bots.builder.insufficientBalanceWarning', {
                        needed: thisBotAmount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
                        available: (selectedEntry?.remaining_balance ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
                      })}
                    </div>
                  )}
                </div>
              )
            })()}

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
                            <label className="block text-[10px] text-gray-500 mb-1">{t('bots.builder.balancePct')}</label>
                            <NumInput value={cfg.position_pct ?? ''} onChange={e => updateAsset('position_pct', e.target.value)}
                              placeholder="-" min={1} max={100} step={1}
                              className="filter-select w-full text-sm tabular-nums text-center" />
                          </div>
                          <div>
                            <label className="flex items-center gap-0.5 text-[10px] text-gray-500 mb-1">
                              {b.leverage}
                              <span className="relative group">
                                <Info size={10} className="text-blue-400 cursor-help" />
                                <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block w-44 p-1.5 text-[10px] text-gray-200 bg-gray-800 border border-gray-600 rounded-lg shadow-lg z-50 whitespace-normal leading-relaxed">
                                  {t('bots.builder.leverageHint')}
                                </span>
                              </span>
                            </label>
                            <NumInput value={cfg.leverage ?? ''} onChange={e => updateAsset('leverage', e.target.value)}
                              placeholder="-" min={1} max={20}
                              className="filter-select w-full text-sm tabular-nums text-center" />
                          </div>
                          <div>
                            <label className="flex items-center gap-0.5 text-[10px] text-gray-500 mb-1">
                              TP %
                              <span className="relative group">
                                <Info size={10} className="text-blue-400 cursor-help" />
                                <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block w-44 p-1.5 text-[10px] text-gray-200 bg-gray-800 border border-gray-600 rounded-lg shadow-lg z-50 whitespace-normal leading-relaxed">
                                  {t('bots.builder.tpHint')}
                                </span>
                              </span>
                            </label>
                            <NumInput value={cfg.tp ?? ''} onChange={e => updateAsset('tp', e.target.value)}
                              placeholder="-" min={0.5} max={20} step={0.5}
                              className="filter-select w-full text-sm tabular-nums text-center" />
                          </div>
                          <div>
                            <label className="flex items-center gap-0.5 text-[10px] text-gray-500 mb-1">
                              SL %
                              <span className="relative group">
                                <Info size={10} className="text-blue-400 cursor-help" />
                                <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block w-44 p-1.5 text-[10px] text-gray-200 bg-gray-800 border border-gray-600 rounded-lg shadow-lg z-50 whitespace-normal leading-relaxed">
                                  {t('bots.builder.slHint')}
                                </span>
                              </span>
                            </label>
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
                    const fixed = tradingPairs.reduce((sum, p) => sum + (perAssetConfig[p]?.position_pct || 0), 0)
                    const unfixedCount = tradingPairs.filter(p => !perAssetConfig[p]?.position_pct).length
                    const remaining = Math.max(0, 100 - fixed)
                    const perUnfixed = unfixedCount > 0 ? remaining / unfixedCount : 0
                    const equity = balancePreview?.exchange_equity || 0
                    return tradingPairs.map(p => {
                      const pct = perAssetConfig[p]?.position_pct || perUnfixed
                      const dollar = equity > 0 ? (equity * pct / 100) : 0
                      return (
                        <span key={p} className="bg-white/5 px-2 py-0.5 rounded">
                          {p}: {pct.toFixed(1)}%
                          {equity > 0 && <span className="text-gray-600 ml-1">(${dollar.toFixed(0)})</span>}
                        </span>
                      )
                    })
                  })()}
                </div>
                <p className="text-xs text-gray-600 mt-1">{t('bots.builder.perAssetHint')}</p>
                {/* TP/SL warning */}
                {(() => {
                  const pairsWithoutSl = tradingPairs.filter(p => !perAssetConfig[p]?.sl)
                  const pairsWithoutTpSl = tradingPairs.filter(p => !perAssetConfig[p]?.tp && !perAssetConfig[p]?.sl)
                  if (pairsWithoutTpSl.length > 0 && pairsWithoutTpSl.length === pairsWithoutSl.length) {
                    return (
                      <div className="mt-2 flex items-start gap-2 p-2.5 bg-amber-900/20 border border-amber-800/50 rounded-lg">
                        <AlertTriangle size={14} className="text-amber-400 mt-0.5 flex-shrink-0" />
                        <p className="text-xs text-amber-400">{t('bots.builder.noTpSlWarning')}</p>
                      </div>
                    )
                  }
                  if (pairsWithoutSl.length > 0) {
                    return (
                      <div className="mt-2 flex items-start gap-2 p-2.5 bg-yellow-900/20 border border-yellow-800/50 rounded-lg">
                        <AlertTriangle size={14} className="text-yellow-400 mt-0.5 flex-shrink-0" />
                        <p className="text-xs text-yellow-400">{t('bots.builder.noSlWarning')}</p>
                      </div>
                    )
                  }
                  return null
                })()}
              </div>
            )}

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

            {/* Margin Mode */}
            <div>
              <label className="block text-sm text-gray-400 mb-2">{t('bots.builder.marginMode')}</label>
              <div className="flex gap-2">
                {(['cross', 'isolated'] as const).map(mm => {
                  const active = marginMode === mm
                  return (
                    <button key={mm} onClick={() => setMarginMode(mm)}
                      className={`px-4 py-2 rounded-xl border transition-all ${
                        active
                          ? 'border-primary-500 bg-primary-500/10 text-white ring-1 ring-primary-500/30'
                          : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-white/20 hover:bg-white/[0.06]'
                      }`}>
                      {t(`bots.builder.${mm}`)}
                    </button>
                  )
                })}
              </div>
              <p className="text-xs text-gray-500 mt-1.5">{t('bots.builder.marginModeHint')}</p>
            </div>

            {/* Symbol conflict warning */}
            {symbolConflicts.length > 0 && (
              <div className="p-3 bg-amber-900/30 border border-amber-800 rounded-xl space-y-1.5">
                <div className="flex items-center gap-2 text-amber-400 font-medium text-sm">
                  <AlertTriangle size={16} />
                  {t('bots.builder.symbolConflictTitle')}
                </div>
                {symbolConflicts.map((c, i) => (
                  <div key={i} className="text-sm text-amber-300/80 ml-6">
                    {t('bots.builder.symbolConflictItem', { symbol: c.symbol, botName: c.existing_bot_name, mode: c.existing_bot_mode.toUpperCase() })}
                  </div>
                ))}
                <p className="text-xs text-amber-400/60 ml-6">{t('bots.builder.symbolConflictHint')}</p>
              </div>
            )}

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

              {/* WhatsApp */}
              <div className="space-y-3 mt-4">
                <div>
                  <label className="block text-xs text-gray-500 mb-1.5">{t('bot.builder.whatsappPhoneId')}</label>
                  <input
                    type="text"
                    value={whatsappPhoneId}
                    onChange={e => setWhatsappPhoneId(e.target.value)}
                    placeholder="100123456789012"
                    className="filter-select w-full text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1.5">{t('bot.builder.whatsappToken')}</label>
                  <input
                    type="password"
                    value={whatsappToken}
                    onChange={e => setWhatsappToken(e.target.value)}
                    placeholder="EAABs..."
                    className="filter-select w-full text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1.5">{t('bot.builder.whatsappRecipient')}</label>
                  <input
                    type="text"
                    value={whatsappRecipient}
                    onChange={e => setWhatsappRecipient(e.target.value)}
                    placeholder="491701234567"
                    className="filter-select w-full text-sm"
                  />
                </div>
                <div className="bg-green-900/20 border border-green-800/50 rounded-xl p-2.5">
                  <p className="text-xs text-green-300">{t('bot.builder.whatsappHint')}</p>
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
                    rotation_only: b.rotationOnly,
                    market_sessions: b.marketSessions,
                    interval: b.interval,
                    custom_cron: b.customCron,
                  }
                  const descMap: Record<string, string> = {
                    rotation_only: b.rotationOnlyDesc,
                    market_sessions: '01, 08, 14, 21h UTC',
                    interval: b.intervalDesc,
                    custom_cron: b.customCronDesc,
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
                    rotation_only: b.rotationOnly,
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
                <NumInput value={intervalMinutes} onChange={e => setIntervalMinutes(parseInt(e.target.value) || 5)} min={5} max={1440}
                  className="filter-select w-36 text-sm tabular-nums" />
              </div>
            )}

            {scheduleType === 'custom_cron' && (
              <div className="mt-2">
                <label className="block text-xs text-gray-500 mb-2">{b.customHours}</label>
                <div className="flex flex-wrap gap-1">
                  {Array.from({ length: 24 }, (_, i) => {
                    const active = customHours.includes(i)
                    return (
                      <button key={i} onClick={() => toggleHour(i)}
                        className={`w-9 h-7 text-[11px] rounded-md transition-all ${
                          active
                            ? 'bg-primary-500/20 text-primary-400 font-semibold ring-1 ring-primary-500/40'
                            : 'bg-white/[0.04] text-gray-500 hover:bg-white/[0.08] hover:text-gray-300'
                        }`}>
                        {String(i).padStart(2, '0')}
                      </button>
                    )
                  })}
                </div>
                {customHours.length > 0 && (
                  <p className="text-[11px] text-gray-500 mt-1.5">
                    {customHours.map(h => `${String(h).padStart(2, '0')}:00`).join(', ')} UTC
                  </p>
                )}
              </div>
            )}

            {/* Trade Rotation toggle */}
            {scheduleType !== 'rotation_only' && (
              <div className="mt-4 pt-4 border-t border-white/5">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-sm text-gray-300">{b.tradeRotation}</span>
                    <p className="text-xs text-gray-500 mt-0.5">{b.tradeRotationDesc}</p>
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
                    <label className="block text-xs text-gray-500 mb-1.5">{b.customMinutes}</label>
                    <NumInput value={rotationMinutes}
                      onChange={e => setRotationMinutes(Math.max(5, parseInt(e.target.value) || 5))}
                      min={5} max={10080}
                      className="filter-select w-36 text-sm tabular-nums" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1.5">{b.rotationStartTime}</label>
                    <FilterDropdown
                      value={rotationStartTime}
                      onChange={val => setRotationStartTime(val)}
                      options={Array.from({ length: 24 }, (_, h) => {
                        const t = `${String(h).padStart(2, '0')}:00`
                        return { value: t, label: `${t} UTC` }
                      })}
                      ariaLabel="Start Time"
                    />
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
              <div><span className="text-gray-500">{b.strategy}:</span> <span className="text-white ml-2">{getStrategyDisplayName(strategyType)}</span></div>
              <div><span className="text-gray-500">{b.exchange}:</span> <span className="text-white ml-2"><ExchangeLogo exchange={exchangeType} size={14} /></span></div>
              <div><span className="text-gray-500">{b.mode}:</span> <span className="text-white ml-2">{mode}</span></div>
              <div><span className="text-gray-500">{t('bots.builder.marginMode')}:</span> <span className="text-white ml-2">{t(`bots.builder.${marginMode}`)}</span></div>
              <div><span className="text-gray-500">{b.tradingPairs}:</span> <span className="text-white ml-2">{tradingPairs.join(', ')}</span></div>
              {usesData && (
                <div><span className="text-gray-500">{b.dataSources}:</span> <span className="text-white ml-2">{hasFixedSources ? `${selectedSources.length} (${b.fixedSources})` : `${selectedSources.length} ${b.sourcesSelected}`}</span></div>
              )}
              {maxTrades != null && (
                <div><span className="text-gray-500">{b.maxTrades}:</span> <span className="text-white ml-2">{maxTrades}</span></div>
              )}
              {dailyLossLimit != null && (
                <div><span className="text-gray-500">{b.dailyLossLimit}:</span> <span className="text-white ml-2">{dailyLossLimit}%</span></div>
              )}
              <div><span className="text-gray-500">{b.schedule}:</span> <span className="text-white ml-2">
                {scheduleType === 'rotation_only' ? (b.rotationOnly) :
                 scheduleType === 'interval' ? `Alle ${intervalMinutes} Min.` :
                 scheduleType === 'custom_cron' ? customHours.map(h => `${h}:00`).join(', ') :
                 '01:00, 08:00, 14:00, 21:00 UTC'}
              </span></div>
              {(rotationEnabled || scheduleType === 'rotation_only') && (
                <div><span className="text-gray-500">{b.tradeRotation}:</span> <span className="text-white ml-2">
                  {rotationMinutes >= 60 ? `${rotationMinutes / 60}h` : `${rotationMinutes}min`}
                  {rotationStartTime ? ` (${b.rotationStartTime}: ${rotationStartTime} UTC)` : ''}
                </span></div>
              )}
            </div>

            {/* Symbol conflict warning (compact) */}
            {symbolConflicts.length > 0 && (
              <div className="flex items-center gap-2 p-2.5 bg-amber-900/30 border border-amber-800 rounded-lg text-sm text-amber-400">
                <AlertTriangle size={15} className="flex-shrink-0" />
                <span>{t('bots.builder.symbolConflictTitle')}: {symbolConflicts.map(c => c.symbol).join(', ')}</span>
              </div>
            )}

            {/* Per-asset config review */}
            {tradingPairs.length > 0 && (
              <div className="mt-4 pt-4 border-t border-white/5">
                <h4 className="text-sm text-gray-400 mb-2">{t('bots.builder.perAssetConfig')}</h4>
                <div className="flex flex-wrap gap-2 text-xs">
                  {(() => {
                    const fixed = tradingPairs.reduce((sum, p) => sum + (perAssetConfig[p]?.position_pct || 0), 0)
                    const unfixedCount = tradingPairs.filter(p => !perAssetConfig[p]?.position_pct).length
                    const remaining = Math.max(0, 100 - fixed)
                    const perUnfixed = unfixedCount > 0 ? remaining / unfixedCount : 0
                    return tradingPairs.map(p => {
                      const cfg = perAssetConfig[p] || {}
                      const pct = cfg.position_pct || perUnfixed
                      const parts = [`${pct.toFixed(0)}%`]
                      if (cfg.leverage) parts.push(`${cfg.leverage}x`)
                      if (cfg.tp) parts.push(`TP ${cfg.tp}%`)
                      if (cfg.sl) parts.push(`SL ${cfg.sl}%`)
                      if (!cfg.tp && !cfg.sl) parts.push(t('bots.builder.noTpSlLabel'))
                      if (cfg.max_trades) parts.push(`${cfg.max_trades} Trades`)
                      if (cfg.loss_limit) parts.push(`Verlust ${cfg.loss_limit}%`)
                      return (
                        <span key={p} className="bg-white/5 px-2 py-1 rounded">
                          <span className="text-white font-medium">{p}</span>
                          <span className="text-gray-400 ml-1">{parts.join(' · ')}</span>
                        </span>
                      )
                    })
                  })()}
                </div>
              </div>
            )}
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
