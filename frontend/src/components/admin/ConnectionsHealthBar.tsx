import { useTranslation } from 'react-i18next'
import { Activity, Wifi, WifiOff } from 'lucide-react'

interface Props {
  totalOnline: number
  totalCount: number
  cbHealthy: number
  cbTotal: number
  connLoading: boolean
  onRefresh: () => void
}

/**
 * Top-of-tab health summary bar for the Connections admin section. Shows the
 * proportion of services online plus circuit breaker health and a refresh button.
 */
export default function ConnectionsHealthBar({
  totalOnline,
  totalCount,
  cbHealthy,
  cbTotal,
  connLoading,
  onRefresh,
}: Props) {
  const { t } = useTranslation()
  const healthPct = totalCount > 0 ? Math.round((totalOnline / totalCount) * 100) : 0

  return (
    <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
            healthPct === 100 ? 'bg-emerald-500/15' : healthPct >= 80 ? 'bg-yellow-500/15' : 'bg-red-500/15'
          }`}>
            {healthPct === 100
              ? <Wifi size={22} className="text-emerald-400" />
              : healthPct >= 80
                ? <Activity size={22} className="text-yellow-400" />
                : <WifiOff size={22} className="text-red-400" />
            }
          </div>
          <div>
            <h3 className="text-white font-semibold text-lg leading-tight">
              {healthPct === 100 ? t('settings.allSystemsOperational', 'Alle Systeme betriebsbereit') : healthPct >= 80 ? t('settings.partialOutage', 'Teilweise eingeschränkt') : t('settings.majorOutage', 'Systemstörung')}
            </h3>
            <p className="text-gray-500 text-sm mt-0.5">
              {totalOnline}/{totalCount} {t('settings.servicesOnline', 'Dienste online')}
              {cbTotal > 0 && <> &middot; {cbHealthy}/{cbTotal} {t('settings.circuitBreakers')}</>}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="w-24 h-2 bg-white/5 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  healthPct === 100 ? 'bg-emerald-500' : healthPct >= 80 ? 'bg-yellow-500' : 'bg-red-500'
                }`}
                style={{ width: `${healthPct}%` }}
              />
            </div>
            <span className={`text-sm font-bold tabular-nums ${
              healthPct === 100 ? 'text-emerald-400' : healthPct >= 80 ? 'text-yellow-400' : 'text-red-400'
            }`}>
              {healthPct}%
            </span>
          </div>
          <button onClick={onRefresh} disabled={connLoading}
            className="px-3 py-1.5 text-sm bg-white/5 border border-white/10 text-gray-300 rounded-xl hover:bg-white/10 disabled:opacity-50 transition-colors">
            {connLoading ? t('settings.refreshing') : t('settings.refreshStatus')}
          </button>
        </div>
      </div>
    </div>
  )
}
