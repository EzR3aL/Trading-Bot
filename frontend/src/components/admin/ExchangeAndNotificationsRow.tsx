import { useTranslation } from 'react-i18next'
import { Activity, Zap } from 'lucide-react'
import { ExchangeIcon } from '../ui/ExchangeLogo'
import type { ServiceStatus } from '../../types'

interface Props {
  exchItems: [string, ServiceStatus][]
  notifItems: [string, ServiceStatus][]
}

/**
 * Two-column row inside the Connections tab: per-exchange API status on the
 * left, notification channel status on the right. Each card shows the
 * configured / online / offline badge.
 */
export default function ExchangeAndNotificationsRow({ exchItems, notifItems }: Props) {
  const { t } = useTranslation()

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {exchItems.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Zap size={16} className="text-gray-500" />
            <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
              {t('settings.exchangeApi')}
            </h3>
          </div>
          <div className="space-y-2">
            {exchItems.map(([key, svc]) => {
              const isConfigured = (svc as any).configured !== false
              return (
                <div key={key} className="border border-white/[0.08] bg-white/[0.02] rounded-xl p-4 flex items-center justify-between hover:bg-white/[0.04] transition-colors">
                  <div className="flex items-center gap-3">
                    <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${
                      !isConfigured ? 'bg-gray-500/10' : svc.reachable ? 'bg-emerald-500/10' : 'bg-red-500/10'
                    }`}>
                      <ExchangeIcon exchange={key.replace('exchange_', '')} size={20} />
                    </div>
                    <div>
                      <span className="text-white text-sm font-medium block">{svc.label}</span>
                      {isConfigured && svc.latency_ms != null && (
                        <span className="text-gray-600 text-[10px] tabular-nums">{svc.latency_ms}ms</span>
                      )}
                      {!isConfigured && (
                        <span className="text-gray-600 text-[10px]">{t('settings.notConfigured')}</span>
                      )}
                    </div>
                  </div>
                  <span className={`text-xs font-medium px-2.5 py-1 rounded-lg ${
                    !isConfigured
                      ? 'bg-white/5 text-gray-500 border border-white/10'
                      : svc.reachable
                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                        : 'bg-red-500/10 text-red-400 border border-red-500/20'
                  }`}>
                    {!isConfigured ? '—' : svc.reachable ? t('settings.online') : t('settings.offline')}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {notifItems.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Activity size={16} className="text-gray-500" />
            <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
              {t('settings.notifications')}
            </h3>
          </div>
          <div className="space-y-2">
            {notifItems.map(([key, svc]) => (
              <div key={key} className="border border-white/[0.08] bg-white/[0.02] rounded-xl p-4 flex items-center justify-between hover:bg-white/[0.04] transition-colors">
                <div className="flex items-center gap-3">
                  <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${
                    svc.reachable ? 'bg-emerald-500/10' : 'bg-red-500/10'
                  }`}>
                    <Activity size={16} className={svc.reachable ? 'text-emerald-400' : 'text-red-400'} />
                  </div>
                  <div>
                    <span className="text-white text-sm font-medium block">{svc.label}</span>
                    {svc.latency_ms != null && (
                      <span className="text-gray-600 text-[10px] tabular-nums">{svc.latency_ms}ms</span>
                    )}
                  </div>
                </div>
                <span className={`text-xs font-medium px-2.5 py-1 rounded-lg ${
                  svc.reachable
                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                    : 'bg-red-500/10 text-red-400 border border-red-500/20'
                }`}>
                  {svc.reachable ? t('settings.online') : t('settings.offline')}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
