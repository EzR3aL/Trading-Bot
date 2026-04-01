import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../../api/client'
import { getApiErrorMessage } from '../../utils/api-error'
import { useToastStore } from '../../stores/toastStore'
import { ArrowLeft, ArrowRight, Check, Play } from 'lucide-react'
import useHaptic from '../../hooks/useHaptic'
import { localHourToUtc, utcHourToLocal } from '../../utils/timezone'

import type { Strategy, DataSource, BalancePreview, SymbolConflict, PerAssetEntry } from './BotBuilderTypes'
import { DATA_STRATEGIES, FIXED_STRATEGY_SOURCES, CATEGORY_ORDER } from './BotBuilderTypes'

import BotBuilderStepName from './BotBuilderStepName'
import BotBuilderStepStrategy from './BotBuilderStepStrategy'
import BotBuilderStepDataSources from './BotBuilderStepDataSources'
import BotBuilderStepExchange from './BotBuilderStepExchange'
import BotBuilderStepNotifications from './BotBuilderStepNotifications'
import BotBuilderStepSchedule from './BotBuilderStepSchedule'
import BotBuilderStepReview from './BotBuilderStepReview'

interface BotBuilderProps {
  botId?: number | null
  onDone: () => void
  onCancel: () => void
}

export default function BotBuilder({ botId, onDone, onCancel }: BotBuilderProps) {
  const { t } = useTranslation()
  const haptic = useHaptic()
  const { addToast } = useToastStore()
  const isEdit = botId !== null && botId !== undefined
  const [step, setStep] = useState(0)
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [validationErrors, setValidationErrors] = useState<string[]>([])
  const [riskAccepted, setRiskAccepted] = useState(false)

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
  const [perAssetConfig, setPerAssetConfig] = useState<Record<string, PerAssetEntry>>({})
  const [scheduleType, setScheduleType] = useState('interval')
  const [intervalMinutes, setIntervalMinutes] = useState<number | ''>(60)
  const [customHours, setCustomHours] = useState<number[]>([])
  const [discordWebhookUrl, setDiscordWebhookUrl] = useState('')
  const [telegramBotToken, setTelegramBotToken] = useState('')
  const [telegramChatId, setTelegramChatId] = useState('')
  const [whatsappPhoneId, setWhatsappPhoneId] = useState('')
  const [whatsappToken, setWhatsappToken] = useState('')
  const [whatsappRecipient, setWhatsappRecipient] = useState('')

  // Hyperliquid gate status (referral + builder fee)
  const [hlGateStatus, setHlGateStatus] = useState<{ needs_approval: boolean; needs_referral: boolean }>({ needs_approval: false, needs_referral: false })

  // Symbol conflicts
  const [symbolConflicts, setSymbolConflicts] = useState<SymbolConflict[]>([])

  // Dynamic exchange symbols
  const [exchangeSymbols, setExchangeSymbols] = useState<string[]>([])
  const [symbolsLoading, setSymbolsLoading] = useState(false)

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

  const isHyperliquid = exchangeType === 'hyperliquid'
  const isBingx = exchangeType === 'bingx'

  // Dynamic steps: insert data sources step for strategies without fixed sources
  const steps = useMemo(() => {
    if (usesData && !hasFixedSources) {
      return ['step1', 'step2', 'step2b', 'step3', 'step4', 'step5', 'step6'] as const
    }
    return ['step1', 'step2', 'step3', 'step4', 'step5', 'step6'] as const
  }, [usesData, hasFixedSources])

  // Group data sources by category (for selectAll / clearCategory)
  const sourcesByCategory = useMemo(() => {
    const groups: Record<string, DataSource[]> = {}
    for (const cat of CATEGORY_ORDER) {
      const items = dataSources.filter(ds => ds.category === cat)
      if (items.length > 0) groups[cat] = items
    }
    return groups
  }, [dataSources])

  // ─── Data loading effects ───────────────────────────────────────────

  // Load strategies
  useEffect(() => {
    api.get('/bots/strategies').then(res => {
      setStrategies(res.data.strategies)
      if (res.data.strategies.length > 0 && !strategyType) {
        const first = res.data.strategies[0]
        setStrategyType(first.name)
        const defaults: Record<string, any> = {}
        Object.entries(first.param_schema).forEach(([key, def]) => {
          defaults[key] = (def as any).default
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
          if (d.schedule_config.hours) setCustomHours(d.schedule_config.hours.map((h: number) => utcHourToLocal(h)))
        }
        // Migrate legacy schedule types to supported ones
        if (d.schedule_type === 'rotation_only' || d.schedule_type === 'market_sessions') {
          setScheduleType('interval')
        }
        // Restore selected data sources from strategy_params
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

  // Fetch available symbols when exchange changes
  useEffect(() => {
    let cancelled = false
    setSymbolsLoading(true)
    api.get(`/exchanges/${exchangeType}/symbols`)
      .then(res => { if (!cancelled) setExchangeSymbols(res.data.symbols || []) })
      .catch(() => { if (!cancelled) setExchangeSymbols([]) })
      .finally(() => { if (!cancelled) setSymbolsLoading(false) })
    return () => { cancelled = true }
  }, [exchangeType])

  // Fetch Hyperliquid gate status when exchange is hyperliquid
  useEffect(() => {
    if (exchangeType !== 'hyperliquid') {
      setHlGateStatus({ needs_approval: false, needs_referral: false })
      return
    }
    api.get('/config/hyperliquid/builder-config')
      .then(res => {
        setHlGateStatus({
          needs_approval: !!res.data.needs_approval,
          needs_referral: !!res.data.needs_referral,
        })
      })
      .catch(() => setHlGateStatus({ needs_approval: false, needs_referral: false }))
  }, [exchangeType])

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

  // ─── Handlers ───────────────────────────────────────────────────────

  const toggleProMode = () => {
    const next = !proMode
    setProMode(next)
    localStorage.setItem('botBuilder_proMode', String(next))
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
        defaults[key] = (def as any).default
      })
      setStrategyParams(defaults)
    }
    if (FIXED_STRATEGY_SOURCES[name]) {
      setSelectedSources(FIXED_STRATEGY_SOURCES[name])
    } else {
      setSelectedSources([])
    }
  }

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

  const buildPayload = () => {
    const scheduleConfig = scheduleType === 'interval'
      ? { interval_minutes: intervalMinutes || 60 }
      : { hours: customHours.map(h => localHourToUtc(h)) }

    const params = usesData
      ? { ...strategyParams, data_sources: selectedSources }
      : strategyParams

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
      schedule_config: scheduleConfig,
      discord_webhook_url: discordWebhookUrl || undefined,
      telegram_bot_token: telegramBotToken || undefined,
      telegram_chat_id: telegramChatId || undefined,
      whatsapp_phone_id: whatsappPhoneId || undefined,
      whatsapp_token: whatsappToken || undefined,
      whatsapp_recipient: whatsappRecipient || undefined,
    }
  }

  const getStepErrors = (stepKey: string): string[] => {
    const errors: string[] = []
    if (stepKey === 'step1' && !name.trim()) errors.push(t('bots.builder.errors.nameRequired'))
    if (stepKey === 'step2' && !strategyType) errors.push(t('bots.builder.errors.strategyRequired'))
    if (stepKey === 'step2b' && !hasFixedSources && selectedSources.length === 0) errors.push(t('bots.builder.errors.dataSourcesRequired'))
    if (stepKey === 'step3' && tradingPairs.length === 0) errors.push(t('bots.builder.errors.pairsRequired'))
    if (stepKey === 'step5') {
      if (scheduleType === 'custom_cron' && customHours.length === 0) errors.push(t('bots.builder.errors.hoursRequired'))
      if (scheduleType === 'interval' && (intervalMinutes === '' || intervalMinutes < 5)) errors.push(t('bots.builder.errors.intervalMinimum'))
    }
    return errors
  }

  const handleSave = async (andStart = false) => {
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
      haptic.success()
      onDone()
    } catch (err) {
      setError(getApiErrorMessage(err, t('common.saveFailed')))
    }
    setSaving(false)
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

  // ─── Render ─────────────────────────────────────────────────────────

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
      <div className="flex items-center gap-1 mb-8 overflow-x-auto scrollbar-hide">
        {steps.map((s, i) => (
          <div key={s} className="flex items-center shrink-0">
            <button
              onClick={() => handleStepClick(i)}
              className={`px-3 py-1 text-sm rounded cursor-pointer transition-colors ${
                i === step ? 'bg-primary-600 text-white' :
                i < step ? 'bg-primary-900/50 text-primary-400 hover:bg-primary-800/60' :
                'bg-gray-800 text-gray-500 hover:bg-gray-700 hover:text-gray-300'
              }`}
            >
              {/* Mobile: show step number + name only for current step; Desktop: always show name */}
              <span className="sm:hidden">{i === step ? `${i + 1}. ${b[s]}` : i + 1}</span>
              <span className="hidden sm:inline">{b[s]}</span>
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
        {currentStepKey === 'step1' && (
          <BotBuilderStepName
            name={name} description={description}
            onNameChange={setName} onDescriptionChange={setDescription}
            b={b}
          />
        )}

        {currentStepKey === 'step2' && (
          <BotBuilderStepStrategy
            strategies={strategies} strategyType={strategyType}
            strategyParams={strategyParams} strategyView={strategyView}
            proMode={proMode}
            onStrategyChange={handleStrategyChange}
            onStrategyParamsChange={setStrategyParams}
            onStrategyViewChange={setStrategyView}
            onToggleProMode={toggleProMode}
            b={b}
          />
        )}

        {currentStepKey === 'step2b' && (
          <BotBuilderStepDataSources
            dataSources={dataSources} selectedSources={selectedSources}
            sourcesView={sourcesView}
            onToggleSource={toggleSource}
            onSelectAllInCategory={selectAllInCategory}
            onClearCategory={clearCategory}
            onSourcesViewChange={setSourcesView}
            b={b}
          />
        )}

        {currentStepKey === 'step3' && (
          <BotBuilderStepExchange
            exchangeType={exchangeType} mode={mode} marginMode={marginMode}
            tradingPairs={tradingPairs} perAssetConfig={perAssetConfig}
            exchangeSymbols={exchangeSymbols} symbolsLoading={symbolsLoading}
            balancePreview={balancePreview} balanceOverview={balanceOverview}
            overviewLoading={overviewLoading} symbolConflicts={symbolConflicts}
            hlGateStatus={hlGateStatus}
            onExchangeTypeChange={setExchangeType} onModeChange={setMode}
            onMarginModeChange={setMarginMode} onTogglePair={togglePair}
            onPerAssetConfigChange={setPerAssetConfig}
            b={b}
          />
        )}

        {currentStepKey === 'step4' && (
          <BotBuilderStepNotifications
            discordWebhookUrl={discordWebhookUrl}
            telegramBotToken={telegramBotToken} telegramChatId={telegramChatId}
            whatsappPhoneId={whatsappPhoneId} whatsappToken={whatsappToken}
            whatsappRecipient={whatsappRecipient} openNotif={openNotif}
            onDiscordWebhookUrlChange={setDiscordWebhookUrl}
            onTelegramBotTokenChange={setTelegramBotToken}
            onTelegramChatIdChange={setTelegramChatId}
            onWhatsappPhoneIdChange={setWhatsappPhoneId}
            onWhatsappTokenChange={setWhatsappToken}
            onWhatsappRecipientChange={setWhatsappRecipient}
            onOpenNotifChange={setOpenNotif}
          />
        )}

        {currentStepKey === 'step5' && (
          <BotBuilderStepSchedule
            scheduleType={scheduleType} intervalMinutes={intervalMinutes}
            customHours={customHours} scheduleView={scheduleView}
            strategyParams={strategyParams}
            onScheduleTypeChange={setScheduleType}
            onIntervalMinutesChange={setIntervalMinutes}
            onToggleHour={toggleHour}
            onScheduleViewChange={setScheduleView}
            b={b}
          />
        )}

        {currentStepKey === 'step6' && (
          <BotBuilderStepReview
            name={name} strategyType={strategyType}
            exchangeType={exchangeType} mode={mode} marginMode={marginMode}
            tradingPairs={tradingPairs} perAssetConfig={perAssetConfig}
            balancePreview={balancePreview}
            scheduleType={scheduleType} intervalMinutes={intervalMinutes}
            customHours={customHours}
            maxTrades={maxTrades} dailyLossLimit={dailyLossLimit}
            symbolConflicts={symbolConflicts}
            selectedSources={selectedSources} usesData={usesData}
            hasFixedSources={hasFixedSources}
            riskAccepted={riskAccepted} onRiskAcceptedChange={setRiskAccepted}
            b={b}
          />
        )}
      </div>

      {validationErrors.length > 0 && (
        <div className="mb-4 p-3 bg-amber-900/30 border border-amber-800 rounded text-amber-400 text-sm space-y-1">
          {validationErrors.map((err, i) => <div key={i}>{err}</div>)}
        </div>
      )}

      {/* Navigation — single row: Back/Cancel left, Next/Save right */}
      <div style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', width: '100%', marginTop: '1rem' }}>
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
                disabled={saving || (!isEdit && !riskAccepted)}
                className="flex items-center gap-1 px-3 sm:px-4 py-2 text-sm bg-gray-700 text-white rounded font-medium hover:bg-gray-600 disabled:opacity-50 transition-colors"
              >
                <Check size={16} />
                <span>{isEdit ? b.save : b.create}</span>
              </button>
              {!isEdit && (
                <button
                  onClick={() => handleSave(true)}
                  disabled={saving || !riskAccepted}
                  className="flex items-center gap-1 px-3 sm:px-4 py-2 text-sm bg-green-700 text-white rounded font-medium hover:bg-green-600 disabled:opacity-50 transition-colors"
                >
                  <Play size={16} />
                  <span className="hidden sm:inline">{b.createAndStart}</span>
                  <span className="sm:hidden">Start</span>
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
