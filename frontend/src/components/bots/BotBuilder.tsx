import { useState, useEffect, useMemo, useRef } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import api from '../../api/client'
import { getApiErrorMessage } from '../../utils/api-error'
import { useToastStore } from '../../stores/toastStore'
import { ArrowLeft, ArrowRight, Check, Play, Brain, TrendingUp, BarChart3, DollarSign, Activity, Building, LayoutGrid, List, Bot, Info, Zap, Clock, AlertTriangle, Wallet, ChevronDown, Search, X, Loader2 } from 'lucide-react'
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
const DATA_STRATEGIES = ['sentiment_surfer', 'liquidation_hunter', 'edge_indicator', 'llm_signal', 'degen', 'contrarian_pulse']

// Fixed data sources per strategy (used after selection to show which sources are used)
const FIXED_STRATEGY_SOURCES: Record<string, string[]> = {
  sentiment_surfer: [
    'fear_greed', 'news_sentiment', 'vwap', 'supertrend', 'spot_volume', 'spot_price', 'oiwap',
  ],
  liquidation_hunter: [
    'fear_greed', 'long_short_ratio', 'funding_rate', 'open_interest', 'spot_price',
  ],
  edge_indicator: [
    'spot_price', 'vwap', 'supertrend', 'spot_volume', 'volatility',
  ],
  // Hidden strategies — kept for existing bots that still use them
  degen: [
    'spot_price', 'fear_greed', 'news_sentiment', 'funding_rate', 'open_interest',
    'long_short_ratio', 'order_book', 'liquidations', 'supertrend', 'vwap',
    'oiwap', 'spot_volume', 'volatility', 'coingecko_market',
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
const POPULAR_BASES = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'AVAX']

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
  const [perAssetConfig, setPerAssetConfig] = useState<Record<string, { position_usdt?: number; leverage?: number; tp?: number; sl?: number; max_trades?: number; loss_limit?: number }>>({})
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

  // Dynamic exchange symbols
  const [exchangeSymbols, setExchangeSymbols] = useState<string[]>([])
  const [symbolsLoading, setSymbolsLoading] = useState(false)
  const [symbolSearch, setSymbolSearch] = useState('')
  const [symbolDropdownOpen, setSymbolDropdownOpen] = useState(false)
  const symbolDropdownRef = useRef<HTMLDivElement>(null)

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

  // Notification accordion: which service is currently expanded
  const [openNotif, setOpenNotif] = useState<string | null>(null)

  // Whether current strategy uses market data
  const usesData = DATA_STRATEGIES.includes(strategyType)
  // Fixed strategies have predetermined sources — no manual selection needed
  const hasFixedSources = !!FIXED_STRATEGY_SOURCES[strategyType]

  // Dynamic steps: insert data sources step only for LLM strategy (manual selection)
  // step3 = Exchange & Assets (merged), step4 = Notifications, step5 = Schedule, step6 = Review
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
    }).catch((err) => { console.error('Failed to load strategies:', err); addToast('error', t('common.loadError', 'Failed to load data')) })
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
    }).catch((err) => { console.error('Failed to load data sources:', err); addToast('error', t('common.loadError', 'Failed to load data')) })
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

  // Fetch available symbols when exchange changes
  useEffect(() => {
    let cancelled = false
    setSymbolsLoading(true)
    api.get(`/exchanges/${exchangeType}/symbols`)
      .then(res => {
        if (!cancelled) setExchangeSymbols(res.data.symbols || [])
      })
      .catch(() => {
        if (!cancelled) setExchangeSymbols([])
      })
      .finally(() => { if (!cancelled) setSymbolsLoading(false) })
    return () => { cancelled = true }
  }, [exchangeType])

  // Close dropdown on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (symbolDropdownRef.current && !symbolDropdownRef.current.contains(e.target as Node)) {
        setSymbolDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  // Filter symbols by search query
  const filteredSymbols = useMemo(() => {
    if (!symbolSearch.trim()) return exchangeSymbols
    const q = symbolSearch.toUpperCase()
    return exchangeSymbols.filter(s => s.toUpperCase().includes(q))
  }, [exchangeSymbols, symbolSearch])

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

  // Convert trading pairs when exchange type changes and new symbols are loaded
  useEffect(() => {
    if (exchangeSymbols.length === 0) return
    setTradingPairs(prev => {
      const converted = prev.map(p => {
        const base = p.replace(/[-](USDT|USDC)$/i, '').replace(/(USDT|USDC)$/i, '')
        let target: string
        if (isHyperliquid) {
          target = base
        } else if (isBingx) {
          target = `${base}-USDT`
        } else {
          target = base + 'USDT'
        }
        // Only keep if the converted symbol exists on this exchange
        return exchangeSymbols.includes(target) ? target : null
      }).filter((p): p is string => p !== null)
      return converted.length > 0 ? converted : prev
    })
  }, [exchangeType, exchangeSymbols]) // eslint-disable-line react-hooks/exhaustive-deps

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
      prev.includes(pair) ? prev.filter(p => p !== pair) : prev.length >= 20 ? prev : [...prev, pair]
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

  // Convert kline interval string to minutes for comparison with schedule
  const klineToMinutes = (kline: string): number => {
    const map: Record<string, number> = { '15m': 15, '30m': 30, '1h': 60, '4h': 240 }
    return map[kline] || 60
  }

  // Check if schedule interval is shorter than kline interval
  const scheduleKlineMismatch = useMemo(() => {
    const kline = strategyParams.kline_interval as string | undefined
    if (!kline) return false
    const klineMin = klineToMinutes(kline)
    if (scheduleType === 'interval') return intervalMinutes < klineMin
    if (scheduleType === 'custom_cron' && customHours.length >= 2) {
      const sorted = [...customHours].sort((a, b) => a - b)
      let minGap = 1440
      for (let i = 1; i < sorted.length; i++) minGap = Math.min(minGap, (sorted[i] - sorted[i - 1]) * 60)
      minGap = Math.min(minGap, (24 - sorted[sorted.length - 1] + sorted[0]) * 60)
      return minGap < klineMin
    }
    return false
  }, [scheduleType, intervalMinutes, customHours, strategyParams.kline_interval])

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
      if (cfg.position_usdt != null && cfg.position_usdt > 0) clean.position_usdt = cfg.position_usdt
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
        <button onClick={onCancel} aria-label={t('common.back')} className="text-gray-400 hover:text-white">
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
        <div role="alert" className="mb-4 p-3 bg-red-900/30 border border-red-800 rounded text-red-400 text-sm">{error}</div>
      )}

      {/* Step content */}
      <div className="border border-white/10 bg-white/[0.03] rounded-xl p-6 mb-6">
        {/* Step 1: Name */}
        {currentStepKey === 'step1' && (
          <div className="space-y-4 max-w-md">
            <div>
              <label htmlFor="bot-name" className="block text-sm text-gray-400 mb-1">{b.name}</label>
              <input
                id="bot-name"
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder={b.namePlaceholder}
                className="filter-select w-full text-sm"
                autoFocus
              />
            </div>
            <div>
              <label htmlFor="bot-description" className="block text-sm text-gray-400 mb-1">{b.description}</label>
              <input
                id="bot-description"
                type="text"
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder={b.descriptionPlaceholder}
                className="filter-select w-full text-sm"
              />
            </div>

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
                        <div className="text-xs text-gray-400 mt-1 line-clamp-2">
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
                        <p className="text-xs text-gray-400 leading-relaxed">
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
                <span className="text-xs text-gray-400 ml-auto">{t('bots.builder.backtestDays')}</span>
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
                              const selectOptions = d.options.map(opt => {
                                const value = typeof opt === 'string' ? opt : opt.value
                                const rawLabel = typeof opt === 'string' ? opt : opt.label
                                const i18nKey = `bots.builder.paramOption_${key}_${value}`
                                const translated = t(i18nKey, '')
                                return { value, label: translated || rawLabel }
                              })
                              const paramLabel = t(`bots.builder.paramLabel_${key}`, '') || d.label
                              const paramDesc = t(`bots.builder.paramDesc_${key}`, '') || d.description
                              return (
                                <div key={key}>
                                  <label className="block text-xs text-gray-300 mb-1">{paramLabel}</label>
                                  <FilterDropdown
                                    value={String(strategyParams[key] ?? d.default)}
                                    onChange={val => {
                                      const updates: Record<string, any> = { [key]: val }
                                      if (key === 'risk_profile') {
                                        const klineMap: Record<string, string> = { conservative: '4h', standard: '1h', aggressive: '15m' }
                                        if (klineMap[val]) updates.kline_interval = klineMap[val]
                                      }
                                      setStrategyParams(prev => ({ ...prev, ...updates }))
                                    }}
                                    options={selectOptions}
                                    ariaLabel={paramLabel}
                                  />
                                  {paramDesc && <p className="text-[10px] text-gray-400 mt-1">{paramDesc}</p>}
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
                                  <label className="block text-xs text-gray-300 mb-1">{d.label}</label>
                                  <FilterDropdown
                                    value={displayValue}
                                    onChange={val => setStrategyParams(prev => ({ ...prev, [key]: val }))}
                                    options={depOptions}
                                    ariaLabel={d.label}
                                  />
                                  {d.description && <p className="text-[10px] text-gray-400 mt-1">{d.description}</p>}
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
                            <label className="block text-xs text-gray-300 mb-1">{d.label}</label>
                            {d.description && <p className="text-[10px] text-gray-400 mb-1.5">{d.description}</p>}
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
                            <p className="text-xs text-gray-400">
                              {proMode
                                ? b.proModeParamsActiveHint
                                : b.proModeParamsHint}
                            </p>
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={toggleProMode}
                          role="switch"
                          aria-checked={proMode}
                          aria-label="Pro Mode"
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
                                    aria-label={td.label}
                                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                                  />
                                  <div className="flex justify-between mt-1">
                                    <span className="text-[10px] text-gray-400">{t('bots.builder.deterministic')}</span>
                                    <span className="text-[10px] text-gray-400">{t('bots.builder.creative')}</span>
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
                                      <label className="block text-xs text-gray-400 mb-1 truncate">{d.label}</label>
                                      <NumInput
                                        value={val}
                                        onChange={e => setStrategyParams(prev => ({ ...prev, [key]: parseFloat(e.target.value) || 0 }))}
                                        min={d.min}
                                        max={d.max}
                                        step={d.type === 'float' ? 0.0001 : 1}
                                        className="filter-select text-sm !w-full text-gray-200"
                                      />
                                      {d.description && <p className="text-[10px] text-gray-400 mt-1 leading-tight">{d.description}</p>}
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
                <p className="text-xs text-gray-400 mt-0.5">
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
                        className={`text-xs px-2 py-0.5 rounded ${allSelected ? 'text-gray-400' : 'text-primary-400 hover:text-primary-300'}`}
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
                              <span className="text-xs text-gray-400 shrink-0">{src.provider}</span>
                            </div>
                            <div className="text-xs text-gray-400 mt-0.5 line-clamp-2">{src.description}</div>
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
                            <span className="text-xs text-gray-400 truncate ml-auto">{src.provider}</span>
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

        {/* Step 3: Exchange & Assets (merged) */}
        {currentStepKey === 'step3' && (
          <div className="space-y-6">
            {/* Exchange selection */}
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
              {exchangeType === 'bitget' && (
                <div className="flex items-start gap-2 p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-300 text-xs">
                  <AlertTriangle size={16} className="shrink-0 mt-0.5" />
                  <div>
                    <span className="font-semibold">{t('bots.builder.bitgetWarningTitle', 'Hinweis fuer deutsche Neukunden:')}</span>{' '}
                    {t('bots.builder.bitgetWarningText', 'Bitget Futures sind fuer neue deutsche Kunden voraussichtlich bis 2027 nicht verfuegbar. Bestehende Konten mit aktiviertem Futures-Trading sind nicht betroffen.')}
                  </div>
                </div>
              )}
            </div>

            {/* Mode + Margin Mode */}
            <div className="grid grid-cols-2 gap-4">
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
                <p className="text-xs text-gray-400 mt-1.5">{t('bots.builder.marginModeHint')}</p>
              </div>
            </div>

            {/* Trading pairs — searchable multi-select */}
            <div>
              <label className="block text-sm text-gray-400 mb-2">{b.tradingPairs}</label>

              {/* Selected pairs as chips */}
              {tradingPairs.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {tradingPairs.map(pair => (
                    <span key={pair} className="inline-flex items-center gap-1 px-2.5 py-1 text-sm rounded-lg border border-primary-500/30 bg-primary-500/15 text-primary-400">
                      {pair}
                      <button onClick={() => togglePair(pair)} className="hover:text-white transition-colors" aria-label={`Remove ${pair}`}>
                        <X size={13} />
                      </button>
                    </span>
                  ))}
                </div>
              )}

              {/* Popular quick buttons */}
              <div className="flex flex-wrap gap-1.5 mb-2">
                {POPULAR_BASES.map(base => {
                  const symbol = isHyperliquid ? base : isBingx ? `${base}-USDT` : `${base}USDT`
                  const isSelected = tradingPairs.includes(symbol)
                  const isAvailable = exchangeSymbols.includes(symbol)
                  if (!isAvailable && !symbolsLoading) return null
                  return (
                    <button key={base} onClick={() => togglePair(symbol)} disabled={symbolsLoading}
                      className={`px-3 py-1.5 text-xs rounded-lg border transition-all ${
                        isSelected
                          ? 'border-primary-500 bg-primary-500/15 text-primary-400'
                          : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-white/20 hover:bg-white/[0.06]'
                      }`}>
                      {base}
                    </button>
                  )
                })}
              </div>

              {/* Searchable dropdown */}
              <div className="relative" ref={symbolDropdownRef}>
                <div className="relative">
                  <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                  <input
                    type="text"
                    value={symbolSearch}
                    onChange={e => { setSymbolSearch(e.target.value); setSymbolDropdownOpen(true) }}
                    onFocus={() => setSymbolDropdownOpen(true)}
                    placeholder={t('bots.builder.searchSymbols')}
                    className="filter-select w-full text-sm pl-9 pr-10"
                  />
                  {symbolsLoading && (
                    <Loader2 size={15} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 animate-spin" />
                  )}
                  {!symbolsLoading && exchangeSymbols.length > 0 && (
                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-gray-500">
                      {exchangeSymbols.length} {t('bots.builder.available')}
                    </span>
                  )}
                </div>

                {symbolDropdownOpen && !symbolsLoading && filteredSymbols.length > 0 && (
                  <div className="absolute z-30 w-full mt-1 max-h-60 overflow-y-auto rounded-xl border border-white/10 bg-[#0f1420] shadow-2xl">
                    {filteredSymbols.slice(0, 100).map(sym => {
                      const isSelected = tradingPairs.includes(sym)
                      return (
                        <button
                          key={sym}
                          onClick={() => { togglePair(sym); setSymbolSearch('') }}
                          className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                            isSelected
                              ? 'bg-primary-500/10 text-primary-400'
                              : 'text-gray-300 hover:bg-white/[0.04] hover:text-white'
                          }`}
                        >
                          <span className="font-medium">{sym}</span>
                          {isSelected && <Check size={14} className="float-right mt-0.5 text-primary-400" />}
                        </button>
                      )
                    })}
                    {filteredSymbols.length > 100 && (
                      <div className="px-3 py-2 text-xs text-gray-500 text-center">
                        {t('bots.builder.moreResults', { count: filteredSymbols.length - 100 })}
                      </div>
                    )}
                  </div>
                )}
              </div>
              <p className="text-xs text-gray-400 mt-1">{t('bots.builder.maxPairs')}</p>
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
              const thisBotUsdt = tradingPairs.reduce((sum, p) => sum + (perAssetConfig[p]?.position_usdt || 0), 0)
              const effectiveMode = mode === 'both' ? 'live' : mode
              const selectedEntry = balanceOverview.find(e => e.exchange_type === exchangeType && e.mode === effectiveMode)
              const totalAllocated = selectedEntry ? selectedEntry.existing_allocated_amount + thisBotUsdt : 0
              const isOverAllocated = selectedEntry ? totalAllocated > selectedEntry.exchange_equity : false
              const isInsufficientBalance = selectedEntry ? thisBotUsdt > selectedEntry.remaining_balance && thisBotUsdt > 0 : false

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
                      <span className="text-xs text-gray-400 ml-auto">{t('bots.builder.bothModeNote')}</span>
                    )}
                  </div>

                  {/* Compact table */}
                  <div className="overflow-hidden rounded-lg border border-white/[0.04]">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-white/[0.03] text-gray-400 text-xs uppercase tracking-wider">
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
                                <span className="text-gray-400 ml-0.5 text-xs">{entry.currency}</span>
                              </td>
                              <td className={`px-2 py-2 text-right tabular-nums ${isOver ? 'text-red-400' : 'text-amber-400'}`}>
                                {entry.existing_allocated_pct.toFixed(0)}%
                                <span className="text-gray-400 ml-1">(${entry.existing_allocated_amount.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })})</span>
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
                      {t('bots.builder.overAllocatedWarning', { pct: selectedEntry ? (totalAllocated / selectedEntry.exchange_equity * 100).toFixed(0) : '0' })}
                    </div>
                  )}
                  {!isOverAllocated && isInsufficientBalance && (
                    <div className="mt-3 flex items-center gap-1.5 text-xs text-amber-400">
                      <AlertTriangle size={13} />
                      {t('bots.builder.insufficientBalanceWarning', {
                        needed: thisBotUsdt.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
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
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-sm font-medium text-white">{pair}</span>
                          {balancePreview && balancePreview.remaining_balance > 0 && (
                            <span className="text-[10px] text-gray-400">
                              {t('bots.builder.availableShort')}: <span className="text-green-400 tabular-nums">${balancePreview.remaining_balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                            </span>
                          )}
                        </div>
                        <div className="grid grid-cols-3 gap-2">
                          <div>
                            <label className="block text-xs text-gray-300 mb-1">{t('bots.builder.budgetUsdt')}</label>
                            <NumInput value={cfg.position_usdt ?? ''} onChange={e => updateAsset('position_usdt', e.target.value)}
                              placeholder="-" min={1} max={999999} step={1}
                              className={`filter-select w-full text-sm tabular-nums text-center ${
                                balancePreview && cfg.position_usdt && cfg.position_usdt > balancePreview.remaining_balance ? 'border-amber-500/50' : ''
                              }`} />
                          </div>
                          <div>
                            <label className="flex items-center gap-0.5 text-xs text-gray-300 mb-1">
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
                            <label className="flex items-center gap-0.5 text-xs text-gray-300 mb-1">
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
                            <label className="flex items-center gap-0.5 text-xs text-gray-300 mb-1">
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
                            <label className="block text-xs text-gray-300 mb-1">{b.maxTrades}</label>
                            <NumInput value={cfg.max_trades ?? ''} onChange={e => updateAsset('max_trades', e.target.value)}
                              placeholder="-" min={1} max={50}
                              className="filter-select w-full text-sm tabular-nums text-center" />
                          </div>
                          <div>
                            <label className="block text-xs text-gray-300 mb-1">{b.dailyLossLimit}</label>
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
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-gray-400">
                  {(() => {
                    const totalFixed = tradingPairs.reduce((sum, p) => sum + (perAssetConfig[p]?.position_usdt || 0), 0)
                    const unfixedCount = tradingPairs.filter(p => !perAssetConfig[p]?.position_usdt).length
                    const equity = balancePreview?.exchange_equity || 0
                    const remaining = Math.max(0, equity - totalFixed)
                    const perUnfixed = unfixedCount > 0 ? remaining / unfixedCount : 0
                    return tradingPairs.map(p => {
                      const usdt = perAssetConfig[p]?.position_usdt || perUnfixed
                      return (
                        <span key={p} className="bg-white/5 px-2 py-0.5 rounded">
                          {p}: <span className="tabular-nums">${usdt.toFixed(0)}</span>
                          {equity > 0 && <span className="text-gray-400 ml-1">({(usdt / equity * 100).toFixed(1)}%)</span>}
                        </span>
                      )
                    })
                  })()}
                </div>
                <p className="text-xs text-gray-400 mt-1">{t('bots.builder.perAssetHint')}</p>
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

        {/* Step 4: Notifications */}
        {currentStepKey === 'step4' && (
          <div className="space-y-6">
            <div>
              <label className="block text-sm text-gray-300 mb-3">{t('settings.notifications')}</label>
              <div className="space-y-2">

              {/* Discord */}
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] overflow-hidden">
                <button
                  type="button"
                  onClick={() => setOpenNotif(openNotif === 'discord' ? null : 'discord')}
                  className="w-full flex items-center gap-3 p-3.5 hover:bg-white/[0.02] transition-colors"
                >
                  <svg viewBox="0 0 24 24" className="w-5 h-5 shrink-0" fill="#5865F2"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>
                  <span className="text-sm font-medium text-white">Discord</span>
                  {discordWebhookUrl && <Check size={14} className="text-emerald-400" />}
                  <span className="text-[10px] text-gray-400 ml-auto mr-2">{t('bots.builder.optional')}</span>
                  <ChevronDown size={16} className={`text-gray-400 transition-transform duration-200 ${openNotif === 'discord' ? 'rotate-180' : ''}`} />
                </button>
                {openNotif === 'discord' && (
                  <div className="px-3.5 pb-3.5 space-y-3">
                    <div>
                      <label htmlFor="notif-discord-webhook" className="block text-xs text-gray-300 mb-1.5">{t('bots.builder.discordWebhook')}</label>
                      <input
                        id="notif-discord-webhook"
                        type="url"
                        value={discordWebhookUrl}
                        onChange={e => setDiscordWebhookUrl(e.target.value)}
                        placeholder="https://discord.com/api/webhooks/..."
                        className="filter-select w-full text-sm"
                      />
                      <p className="text-xs text-gray-400 mt-1.5">{t('bots.builder.discordWebhookHint')}</p>
                    </div>
                    <div className="bg-indigo-900/15 border border-indigo-800/40 rounded-lg p-2.5">
                      <p className="text-xs text-indigo-300 leading-relaxed">{t('bots.builder.discordSetupGuide')}</p>
                    </div>
                  </div>
                )}
              </div>

              {/* Telegram */}
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] overflow-hidden">
                <button
                  type="button"
                  onClick={() => setOpenNotif(openNotif === 'telegram' ? null : 'telegram')}
                  className="w-full flex items-center gap-3 p-3.5 hover:bg-white/[0.02] transition-colors"
                >
                  <svg viewBox="0 0 24 24" className="w-5 h-5 shrink-0" fill="#26A5E4"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0h-.056zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.479.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg>
                  <span className="text-sm font-medium text-white">Telegram</span>
                  {telegramBotToken && telegramChatId && <Check size={14} className="text-emerald-400" />}
                  <span className="text-[10px] text-gray-400 ml-auto mr-2">{t('bots.builder.optional')}</span>
                  <ChevronDown size={16} className={`text-gray-400 transition-transform duration-200 ${openNotif === 'telegram' ? 'rotate-180' : ''}`} />
                </button>
                {openNotif === 'telegram' && (
                  <div className="px-3.5 pb-3.5 space-y-3">
                    <div>
                      <label htmlFor="notif-telegram-token" className="block text-xs text-gray-300 mb-1.5">{t('bots.builder.telegramToken')}</label>
                      <input
                        id="notif-telegram-token"
                        type="password"
                        value={telegramBotToken}
                        onChange={e => setTelegramBotToken(e.target.value)}
                        placeholder="6123456789:ABCdef..."
                        className="filter-select w-full text-sm"
                      />
                    </div>
                    <div>
                      <label htmlFor="notif-telegram-chatid" className="block text-xs text-gray-300 mb-1.5">{t('bots.builder.telegramChatId')}</label>
                      <input
                        id="notif-telegram-chatid"
                        type="text"
                        value={telegramChatId}
                        onChange={e => setTelegramChatId(e.target.value)}
                        placeholder="123456789"
                        className="filter-select w-full text-sm"
                      />
                    </div>
                    <div className="bg-blue-900/15 border border-blue-800/40 rounded-lg p-2.5">
                      <p className="text-xs text-blue-300 leading-relaxed">{t('bots.builder.telegramHint')}</p>
                    </div>
                  </div>
                )}
              </div>

              {/* WhatsApp */}
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] overflow-hidden">
                <button
                  type="button"
                  onClick={() => setOpenNotif(openNotif === 'whatsapp' ? null : 'whatsapp')}
                  className="w-full flex items-center gap-3 p-3.5 hover:bg-white/[0.02] transition-colors"
                >
                  <svg viewBox="0 0 24 24" className="w-5 h-5 shrink-0" fill="#25D366"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 0 1-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 0 1-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 0 1 2.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0 0 12.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 0 0 5.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 0 0-3.48-8.413z"/></svg>
                  <span className="text-sm font-medium text-white">WhatsApp</span>
                  {whatsappPhoneId && whatsappToken && whatsappRecipient && <Check size={14} className="text-emerald-400" />}
                  <span className="text-[10px] text-gray-400 ml-auto mr-2">{t('bots.builder.optional')}</span>
                  <ChevronDown size={16} className={`text-gray-400 transition-transform duration-200 ${openNotif === 'whatsapp' ? 'rotate-180' : ''}`} />
                </button>
                {openNotif === 'whatsapp' && (
                  <div className="px-3.5 pb-3.5 space-y-3">
                    <div>
                      <label htmlFor="notif-wa-phoneid" className="block text-xs text-gray-300 mb-1.5">{t('bots.builder.whatsappPhoneId')}</label>
                      <input
                        id="notif-wa-phoneid"
                        type="text"
                        value={whatsappPhoneId}
                        onChange={e => setWhatsappPhoneId(e.target.value)}
                        placeholder="100123456789012"
                        className="filter-select w-full text-sm"
                      />
                    </div>
                    <div>
                      <label htmlFor="notif-wa-token" className="block text-xs text-gray-300 mb-1.5">{t('bots.builder.whatsappToken')}</label>
                      <input
                        id="notif-wa-token"
                        type="password"
                        value={whatsappToken}
                        onChange={e => setWhatsappToken(e.target.value)}
                        placeholder="EAABs..."
                        className="filter-select w-full text-sm"
                      />
                    </div>
                    <div>
                      <label htmlFor="notif-wa-recipient" className="block text-xs text-gray-300 mb-1.5">{t('bots.builder.whatsappRecipient')}</label>
                      <input
                        id="notif-wa-recipient"
                        type="text"
                        value={whatsappRecipient}
                        onChange={e => setWhatsappRecipient(e.target.value)}
                        placeholder="491701234567"
                        className="filter-select w-full text-sm"
                      />
                    </div>
                    <div className="bg-green-900/15 border border-green-800/40 rounded-lg p-2.5">
                      <p className="text-xs text-green-300 leading-relaxed">{t('bots.builder.whatsappHint')}</p>
                    </div>
                  </div>
                )}
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
                      {descMap[st] && <div className="text-xs text-gray-400 mt-0.5 line-clamp-2">{descMap[st]}</div>}
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
                <label className="block text-xs text-gray-300 mb-1.5">{b.intervalMinutes}</label>
                <NumInput value={intervalMinutes} onChange={e => setIntervalMinutes(parseInt(e.target.value) || 5)} min={5} max={1440}
                  className="filter-select w-36 text-sm tabular-nums" />
              </div>
            )}

            {scheduleType === 'custom_cron' && (
              <div className="mt-2">
                <label className="block text-xs text-gray-300 mb-2">{b.customHours}</label>
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
                  <p className="text-xs text-gray-400 mt-1.5">
                    {customHours.map(h => `${String(h).padStart(2, '0')}:00`).join(', ')} UTC
                  </p>
                )}
              </div>
            )}

            {/* Kline vs Schedule mismatch warning */}
            {scheduleKlineMismatch && (
              <div className="mt-3 flex items-start gap-2.5 rounded-xl border border-amber-500/20 bg-amber-500/5 px-3.5 py-3">
                <AlertTriangle size={16} className="text-amber-400 shrink-0 mt-0.5" />
                <div className="text-xs text-amber-300/90 leading-relaxed">
                  {t('bots.builder.scheduleKlineWarning', {
                    schedule: scheduleType === 'interval' ? `${intervalMinutes}m` : t('bots.builder.customCron'),
                    kline: strategyParams.kline_interval ?? '1h',
                    defaultValue: `Your analysis interval (${scheduleType === 'interval' ? `${intervalMinutes}m` : 'custom'}) is shorter than the Kline interval (${strategyParams.kline_interval ?? '1h'}). The bot will analyze the same candle multiple times without new information. Recommended: analysis interval ≥ Kline interval.`
                  })}
                </div>
              </div>
            )}

            {/* Trade Rotation toggle */}
            {scheduleType !== 'rotation_only' && (
              <div className="mt-4 pt-4 border-t border-white/5">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-sm text-gray-300">{b.tradeRotation}</span>
                    <p className="text-xs text-gray-400 mt-0.5">{b.tradeRotationDesc}</p>
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
                    <label className="block text-xs text-gray-300 mb-1.5">{b.customMinutes}</label>
                    <NumInput value={rotationMinutes}
                      onChange={e => setRotationMinutes(Math.max(5, parseInt(e.target.value) || 5))}
                      min={5} max={10080}
                      className="filter-select w-36 text-sm tabular-nums" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-300 mb-1.5">{b.rotationStartTime}</label>
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
                    const totalFixed = tradingPairs.reduce((sum, p) => sum + (perAssetConfig[p]?.position_usdt || 0), 0)
                    const unfixedCount = tradingPairs.filter(p => !perAssetConfig[p]?.position_usdt).length
                    const equity = balancePreview?.exchange_equity || 0
                    const remaining = Math.max(0, equity - totalFixed)
                    const perUnfixed = unfixedCount > 0 ? remaining / unfixedCount : 0
                    return tradingPairs.map(p => {
                      const cfg = perAssetConfig[p] || {}
                      const usdt = cfg.position_usdt || perUnfixed
                      const parts = [`$${usdt.toFixed(0)}`]
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
