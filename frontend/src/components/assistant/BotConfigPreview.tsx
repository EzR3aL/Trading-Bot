import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Cpu, Play, Loader2 } from 'lucide-react'
import api from '../../api/client'
import type { BotConfigPreviewData } from '../../types'

export default function BotConfigPreview({ config }: { config: BotConfigPreviewData }) {
  const { t } = useTranslation()
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleCreate = async (start: boolean) => {
    setCreating(true)
    setError(null)
    try {
      const res = await api.post('/bots', {
        name: config.name,
        strategy_type: config.strategy_type,
        exchange_type: config.exchange_type,
        mode: config.mode,
        trading_pairs: config.trading_pairs,
        leverage: config.leverage,
        position_size_percent: config.position_size_percent,
        max_trades_per_day: config.max_trades_per_day,
        take_profit_percent: config.take_profit_percent,
        stop_loss_percent: config.stop_loss_percent,
        daily_loss_limit_percent: config.daily_loss_limit_percent || 5.0,
        strategy_params: config.strategy_params || {},
        schedule_type: config.schedule_type || 'market_sessions',
      })
      if (start && res.data.id) {
        await api.post(`/bots/${res.data.id}/start`)
      }
      setCreated(true)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to create bot'
      setError(msg)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800/60 p-3 text-sm">
      <div className="flex items-center gap-2 mb-2 text-gray-300 font-medium">
        <Cpu size={14} />
        {t('assistant.botConfigPreview')}
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs mb-3">
        <div>
          <span className="text-gray-500">Name:</span>{' '}
          <span className="text-white">{config.name}</span>
        </div>
        <div>
          <span className="text-gray-500">Strategy:</span>{' '}
          <span className="text-white">{config.strategy_type}</span>
        </div>
        <div>
          <span className="text-gray-500">Exchange:</span>{' '}
          <span className="text-white">{config.exchange_type}</span>
        </div>
        <div>
          <span className="text-gray-500">Mode:</span>{' '}
          <span className={config.mode === 'live' ? 'text-orange-400' : 'text-blue-400'}>
            {config.mode}
          </span>
        </div>
        <div>
          <span className="text-gray-500">Leverage:</span>{' '}
          <span className="text-white">{config.leverage}x</span>
        </div>
        <div>
          <span className="text-gray-500">Size:</span>{' '}
          <span className="text-white">{config.position_size_percent}%</span>
        </div>
        <div>
          <span className="text-gray-500">TP:</span>{' '}
          <span className="text-green-400">{config.take_profit_percent}%</span>
        </div>
        <div>
          <span className="text-gray-500">SL:</span>{' '}
          <span className="text-red-400">{config.stop_loss_percent}%</span>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 mb-3">
        {config.trading_pairs.map((pair) => (
          <span key={pair} className="text-xs px-1.5 py-0.5 bg-gray-700 text-gray-300 rounded">
            {pair}
          </span>
        ))}
      </div>

      {error && <div className="text-xs text-red-400 mb-2">{error}</div>}

      {created ? (
        <div className="text-xs text-green-400 font-medium">Bot created successfully!</div>
      ) : (
        <div className="flex gap-2">
          <button
            onClick={() => handleCreate(false)}
            disabled={creating}
            className="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 text-xs bg-primary-600/20 text-primary-400 rounded hover:bg-primary-600/30 disabled:opacity-50 transition-colors"
          >
            {creating ? <Loader2 size={12} className="animate-spin" /> : <Cpu size={12} />}
            {t('assistant.createBot')}
          </button>
          <button
            onClick={() => handleCreate(true)}
            disabled={creating}
            className="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 text-xs bg-green-900/40 text-green-400 rounded hover:bg-green-900/60 disabled:opacity-50 transition-colors"
          >
            {creating ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            {t('assistant.createAndStart')}
          </button>
        </div>
      )}
    </div>
  )
}
