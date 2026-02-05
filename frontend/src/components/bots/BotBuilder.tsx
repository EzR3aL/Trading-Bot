import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../../api/client'
import { ArrowLeft, ArrowRight, Check, Play } from 'lucide-react'

interface Strategy {
  name: string
  description: string
  param_schema: Record<string, ParamDef>
}

interface ParamDef {
  type: string
  label: string
  description: string
  default: number | string | boolean
  min?: number
  max?: number
  options?: string[]
}

interface BotBuilderProps {
  botId?: number | null
  onDone: () => void
  onCancel: () => void
}

const STEPS = ['step1', 'step2', 'step3', 'step4', 'step5', 'step6'] as const
const EXCHANGES = ['bitget', 'weex', 'hyperliquid']
const PAIRS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'AVAXUSDT']

export default function BotBuilder({ botId, onDone, onCancel }: BotBuilderProps) {
  const { t } = useTranslation()
  const isEdit = botId !== null && botId !== undefined
  const [step, setStep] = useState(0)
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

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

  // Load strategies
  useEffect(() => {
    api.get('/bots/strategies').then(res => {
      setStrategies(res.data.strategies)
      if (res.data.strategies.length > 0 && !strategyType) {
        const first = res.data.strategies[0]
        setStrategyType(first.name)
        // Set default params
        const defaults: Record<string, any> = {}
        Object.entries(first.param_schema).forEach(([key, def]) => {
          defaults[key] = (def as ParamDef).default
        })
        setStrategyParams(defaults)
      }
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

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
      })
    }
  }, [botId, isEdit])

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

  const buildPayload = () => {
    const scheduleConfig = scheduleType === 'interval'
      ? { interval_minutes: intervalMinutes }
      : scheduleType === 'custom_cron'
        ? { hours: customHours }
        : { hours: [1, 8, 14, 21] }

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
      strategy_params: strategyParams,
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
    if (step === 0) return name.trim().length > 0
    if (step === 1) return strategyType.length > 0
    if (step === 2) return tradingPairs.length > 0
    if (step === 3) return true
    if (step === 4) return scheduleType === 'interval' ? intervalMinutes >= 5 : true
    return true
  }

  const b = t('bots.builder', { returnObjects: true }) as Record<string, string>

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
        {STEPS.map((s, i) => (
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
            {i < STEPS.length - 1 && <div className="w-4 h-px bg-gray-700 mx-1" />}
          </div>
        ))}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-900/30 border border-red-800 rounded text-red-400 text-sm">{error}</div>
      )}

      {/* Step content */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 mb-6">
        {/* Step 1: Name */}
        {step === 0 && (
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
        {step === 1 && (
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

            {selectedStrategy && Object.keys(selectedStrategy.param_schema).length > 0 && (
              <div>
                <label className="block text-sm text-gray-400 mb-3">{b.strategyParams}</label>
                <div className="grid grid-cols-2 gap-4">
                  {Object.entries(selectedStrategy.param_schema).map(([key, def]) => {
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

        {/* Step 3: Trading Parameters */}
        {step === 2 && (
          <div className="space-y-6">
            <div>
              <label className="block text-sm text-gray-400 mb-2">{b.tradingPairs}</label>
              <div className="flex flex-wrap gap-2">
                {PAIRS.map(pair => (
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
        {step === 3 && (
          <div className="space-y-6">
            <div>
              <label className="block text-sm text-gray-400 mb-2">{b.exchange}</label>
              <div className="flex gap-3">
                {EXCHANGES.map(ex => (
                  <button
                    key={ex}
                    onClick={() => setExchangeType(ex)}
                    className={`px-4 py-2 rounded border capitalize transition-colors ${
                      exchangeType === ex
                        ? 'border-primary-500 bg-primary-900/20 text-white'
                        : 'border-gray-700 bg-gray-800 text-gray-400 hover:border-gray-600'
                    }`}
                  >
                    {ex}
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
        {step === 4 && (
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
        {step === 5 && (
          <div className="space-y-4">
            <h3 className="text-white font-medium mb-4">{b.review}</h3>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div><span className="text-gray-500">{b.name}:</span> <span className="text-white ml-2">{name}</span></div>
              <div><span className="text-gray-500">{b.strategy}:</span> <span className="text-white ml-2">{strategyType}</span></div>
              <div><span className="text-gray-500">{b.exchange}:</span> <span className="text-white ml-2">{exchangeType}</span></div>
              <div><span className="text-gray-500">{b.mode}:</span> <span className="text-white ml-2">{mode}</span></div>
              <div><span className="text-gray-500">{b.tradingPairs}:</span> <span className="text-white ml-2">{tradingPairs.join(', ')}</span></div>
              <div><span className="text-gray-500">{b.leverage}:</span> <span className="text-white ml-2">{leverage}x</span></div>
              <div><span className="text-gray-500">{b.positionSize}:</span> <span className="text-white ml-2">{positionSize}%</span></div>
              <div><span className="text-gray-500">{b.maxTrades}:</span> <span className="text-white ml-2">{maxTrades}</span></div>
              <div><span className="text-gray-500">{b.takeProfit}:</span> <span className="text-white ml-2">{takeProfit}%</span></div>
              <div><span className="text-gray-500">{b.stopLoss}:</span> <span className="text-white ml-2">{stopLoss}%</span></div>
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
          {step < STEPS.length - 1 ? (
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
