import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, LayoutGrid, List, AlertTriangle } from 'lucide-react'
import NumInput from '../ui/NumInput'
import { formatTimezone } from '../../utils/timezone'

interface Props {
  scheduleType: string
  intervalMinutes: number | ''
  customHours: number[]
  scheduleView: 'grid' | 'list'
  strategyParams: Record<string, any>
  onScheduleTypeChange: (val: string) => void
  onIntervalMinutesChange: (val: number | '') => void
  onToggleHour: (hour: number) => void
  onScheduleViewChange: (view: 'grid' | 'list') => void
  b: Record<string, string>
}

// Convert kline interval string to minutes for comparison with schedule
const klineToMinutes = (kline: string): number => {
  const map: Record<string, number> = { '15m': 15, '30m': 30, '1h': 60, '4h': 240 }
  return map[kline] || 60
}

export default function BotBuilderStepSchedule({
  scheduleType, intervalMinutes, customHours, scheduleView, strategyParams,
  onScheduleTypeChange, onIntervalMinutesChange, onToggleHour, onScheduleViewChange,
  b,
}: Props) {
  const { t } = useTranslation()

  // Check if schedule interval is shorter than kline interval
  const scheduleKlineMismatch = useMemo(() => {
    const kline = strategyParams.kline_interval as string | undefined
    if (!kline) return false
    const klineMin = klineToMinutes(kline)
    if (scheduleType === 'interval') return typeof intervalMinutes === 'number' && intervalMinutes < klineMin
    if (scheduleType === 'custom_cron' && customHours.length >= 2) {
      const sorted = [...customHours].sort((a, b) => a - b)
      let minGap = 1440
      for (let i = 1; i < sorted.length; i++) minGap = Math.min(minGap, (sorted[i] - sorted[i - 1]) * 60)
      minGap = Math.min(minGap, (24 - sorted[sorted.length - 1] + sorted[0]) * 60)
      return minGap < klineMin
    }
    return false
  }, [scheduleType, intervalMinutes, customHours, strategyParams.kline_interval])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <label className="block text-sm text-gray-400">{b.schedule}</label>
        <div className="flex items-center gap-1 bg-white/5 rounded-lg p-0.5">
          <button type="button" onClick={() => onScheduleViewChange('grid')}
            className={`p-1.5 rounded-md transition-colors ${scheduleView === 'grid' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}>
            <LayoutGrid size={14} />
          </button>
          <button type="button" onClick={() => onScheduleViewChange('list')}
            className={`p-1.5 rounded-md transition-colors ${scheduleView === 'list' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}>
            <List size={14} />
          </button>
        </div>
      </div>

      {scheduleView === 'grid' ? (
        <div className="grid grid-cols-2 gap-2">
          {(['interval', 'custom_cron'] as const).map(st => {
            const labelMap: Record<string, string> = {
              interval: b.interval,
              custom_cron: b.customCron,
            }
            const descMap: Record<string, string> = {
              interval: b.intervalDesc,
              custom_cron: b.customCronDesc,
            }
            const isSelected = scheduleType === st
            return (
              <button key={st} onClick={() => onScheduleTypeChange(st)}
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
          {(['interval', 'custom_cron'] as const).map(st => {
            const labelMap: Record<string, string> = {
              interval: b.interval,
              custom_cron: b.customCron,
            }
            const isSelected = scheduleType === st
            return (
              <button key={st} onClick={() => onScheduleTypeChange(st)}
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
          <NumInput value={intervalMinutes} onChange={e => { const v = e.target.value; onIntervalMinutesChange(v === '' ? '' : (parseInt(v) || '')) }} min={5} max={1440}
            className="filter-select w-36 text-sm tabular-nums" placeholder="5–1440" />
        </div>
      )}

      {scheduleType === 'custom_cron' && (
        <div className="mt-2">
          <label className="block text-xs text-gray-300 mb-2">{b.customHours}</label>
          <div className="flex flex-wrap gap-1">
            {Array.from({ length: 24 }, (_, i) => {
              const active = customHours.includes(i)
              return (
                <button key={i} onClick={() => onToggleHour(i)}
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
              {customHours.map(h => `${String(h).padStart(2, '0')}:00`).join(', ')}
            </p>
          )}
        </div>
      )}

      {/* Timezone hint */}
      {(scheduleType === 'interval' || scheduleType === 'custom_cron') && (
        <p className="text-xs text-zinc-500 mt-2">
          {t('bots.builder.timezone_hint', { tz: formatTimezone() })}
        </p>
      )}

      {/* Kline vs Schedule mismatch warning */}
      {scheduleKlineMismatch && (
        <div className="mt-3 flex items-start gap-2.5 rounded-xl border border-amber-500/20 bg-amber-500/5 px-3.5 py-3">
          <AlertTriangle size={16} className="text-amber-400 shrink-0 mt-0.5" />
          <div className="text-xs text-amber-300/90 leading-relaxed">
            {t('bots.builder.scheduleKlineWarning', {
              schedule: scheduleType === 'interval' ? `${intervalMinutes || '?'}m` : t('bots.builder.customCron'),
              kline: strategyParams.kline_interval ?? '1h',
              defaultValue: `Your analysis interval (${scheduleType === 'interval' ? `${intervalMinutes || '?'}m` : 'custom'}) is shorter than the Kline interval (${strategyParams.kline_interval ?? '1h'}). The bot will analyze the same candle multiple times without new information. Recommended: analysis interval >= Kline interval.`
            })}
          </div>
        </div>
      )}

    </div>
  )
}
