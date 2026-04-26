import { useTranslation } from 'react-i18next'
import { Shield } from 'lucide-react'
import type { ConnectionsStatusResponse } from '../../types'

interface Props {
  cbEntries: [string, ConnectionsStatusResponse['circuit_breakers'][string]][]
  cbHealthy: number
}

/**
 * Bottom of the Connections tab: circuit breaker pills colored by state
 * (closed = healthy, open = tripped, half-open = recovering).
 */
export default function CircuitBreakersGrid({ cbEntries, cbHealthy }: Props) {
  const { t } = useTranslation()

  const circuitLabel = (state: string) => {
    if (state === 'closed') return t('settings.circuitClosed')
    if (state === 'open') return t('settings.circuitOpen')
    return t('settings.circuitHalfOpen')
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Shield size={16} className="text-gray-500" />
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          {t('settings.circuitBreakers')}
        </h3>
        <span className="text-xs px-2 py-0.5 rounded-full bg-white/5 text-gray-500 border border-white/10 tabular-nums">
          {cbHealthy}/{cbEntries.length}
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
        {cbEntries.map(([name, cb]) => (
          <div key={name} className="border border-white/[0.08] bg-white/[0.02] rounded-xl px-4 py-3 flex items-center justify-between hover:bg-white/[0.04] transition-colors">
            <div className="flex items-center gap-2.5">
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                cb.state === 'closed' ? 'bg-emerald-400' : cb.state === 'open' ? 'bg-red-400 animate-pulse' : 'bg-yellow-400 animate-pulse'
              }`} />
              <span className="text-white text-xs font-medium">{cb.name}</span>
            </div>
            <span className={`text-[10px] font-medium px-2 py-0.5 rounded-md ${
              cb.state === 'closed'
                ? 'bg-emerald-500/10 text-emerald-400'
                : cb.state === 'open'
                  ? 'bg-red-500/10 text-red-400'
                  : 'bg-yellow-500/10 text-yellow-400'
            }`}>
              {circuitLabel(cb.state)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
