import { useTranslation } from 'react-i18next'
import { CheckCircle, Settings2, Shield } from 'lucide-react'
import type { HlRevenueInfo } from '../../types'

interface Props {
  hlRevenue: HlRevenueInfo | null
  hlLoading: boolean
  onRefresh: () => void
}

/**
 * Top-of-tab status overview for the Hyperliquid admin section. Shows the
 * builder/referral readiness at a glance plus a refresh button.
 */
export default function HyperliquidStatusOverview({ hlRevenue, hlLoading, onRefresh }: Props) {
  const { t } = useTranslation()

  if (!hlRevenue) {
    return (
      <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-white/5 flex items-center justify-center">
              <Settings2 size={22} className="text-gray-600" />
            </div>
            <div>
              <h3 className="text-white font-semibold text-lg leading-tight">Hyperliquid</h3>
              <p className="text-gray-500 text-sm mt-0.5">{hlLoading ? t('settings.refreshing') : t('settings.hlNoConnection')}</p>
            </div>
          </div>
          {!hlLoading && (
            <button onClick={onRefresh}
              className="px-4 py-2 text-sm bg-primary-600 text-white rounded-xl hover:bg-primary-700 transition-colors">
              {t('settings.refreshStatus')}
            </button>
          )}
        </div>
      </div>
    )
  }

  const builderOk = hlRevenue.builder?.configured && hlRevenue.builder?.user_approved
  const referralOk = hlRevenue.referral?.configured && hlRevenue.referral?.user_referred
  const statusCount = (builderOk ? 1 : 0) + (referralOk ? 1 : 0)
  const statusPct = Math.round((statusCount / 2) * 100)

  return (
    <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
            statusPct === 100 ? 'bg-emerald-500/15' : statusPct >= 50 ? 'bg-yellow-500/15' : 'bg-red-500/15'
          }`}>
            {statusPct === 100
              ? <CheckCircle size={22} className="text-emerald-400" />
              : statusPct >= 50
                ? <Settings2 size={22} className="text-yellow-400" />
                : <Shield size={22} className="text-red-400" />
            }
          </div>
          <div>
            <h3 className="text-white font-semibold text-lg leading-tight">
              {statusPct === 100
                ? t('settings.hlAllConfigured', 'Vollständig konfiguriert')
                : statusPct >= 50
                  ? t('settings.hlPartialConfig', 'Teilweise konfiguriert')
                  : t('settings.hlNotReady', 'Einrichtung erforderlich')
              }
            </h3>
            <p className="text-gray-500 text-sm mt-0.5">
              {statusCount}/2 {t('settings.hlServicesActive', 'Dienste aktiv')}
              {hlRevenue.earnings && (
                <> &middot; ${(hlRevenue.earnings.total_builder_fees_30d || 0).toFixed(4)} (30d)</>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="w-24 h-2 bg-white/5 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  statusPct === 100 ? 'bg-emerald-500' : statusPct >= 50 ? 'bg-yellow-500' : 'bg-red-500'
                }`}
                style={{ width: `${statusPct}%` }}
              />
            </div>
            <span className={`text-sm font-bold tabular-nums ${
              statusPct === 100 ? 'text-emerald-400' : statusPct >= 50 ? 'text-yellow-400' : 'text-red-400'
            }`}>
              {statusPct}%
            </span>
          </div>
          <button onClick={onRefresh} disabled={hlLoading}
            className="px-3 py-1.5 text-sm bg-white/5 border border-white/10 text-gray-300 rounded-xl hover:bg-white/10 disabled:opacity-50 transition-colors">
            {hlLoading ? t('settings.refreshing') : t('settings.refreshStatus')}
          </button>
        </div>
      </div>
    </div>
  )
}
