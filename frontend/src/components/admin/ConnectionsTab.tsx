import { useTranslation } from 'react-i18next'
import { Activity } from 'lucide-react'
import ConnectionsHealthBar from './ConnectionsHealthBar'
import DataSourceCategoryGrid from './DataSourceCategoryGrid'
import ExchangeAndNotificationsRow from './ExchangeAndNotificationsRow'
import CircuitBreakersGrid from './CircuitBreakersGrid'
import type { ConnectionsStatusResponse, ServiceStatus } from '../../types'

interface Props {
  connStatus: ConnectionsStatusResponse | null
  connLoading: boolean
  onRefresh: () => void
}

/**
 * Connections admin tab. Composes the health bar, data sources grid, exchange
 * + notification row, and circuit breakers grid. Falls back to the empty-state
 * spinner / refresh CTA when status hasn't loaded yet.
 */
export default function ConnectionsTab({ connStatus, connLoading, onRefresh }: Props) {
  const { t } = useTranslation()

  const groupServices = (services: Record<string, ServiceStatus>) => {
    const groups: Record<string, [string, ServiceStatus][]> = {
      data_source: [], exchange: [], notification: [],
    }
    for (const [key, svc] of Object.entries(services)) {
      const group = groups[svc.type]
      if (group) group.push([key, svc])
    }
    return groups
  }

  if (!connStatus) {
    return (
      <div className="space-y-6">
        <div className="flex flex-col items-center justify-center py-16 space-y-4">
          <div className="w-12 h-12 rounded-xl bg-white/5 flex items-center justify-center">
            <Activity size={22} className="text-gray-600" />
          </div>
          <div className="text-center">
            <p className="text-gray-400 text-sm">{connLoading ? t('settings.refreshing') : t('settings.connectionsDesc')}</p>
            {!connLoading && (
              <button onClick={onRefresh}
                className="mt-3 px-4 py-2 text-sm bg-primary-600 text-white rounded-xl hover:bg-primary-700 transition-colors">
                {t('settings.refreshStatus')}
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  const groups = groupServices(connStatus.services)
  const dsItems = groups['data_source'] || []
  const exchItems = groups['exchange'] || []
  const notifItems = groups['notification'] || []
  const allItems = [...dsItems, ...exchItems, ...notifItems].filter(([, s]) => (s as any).configured !== false)
  const totalOnline = allItems.filter(([, s]) => s.reachable).length
  const totalCount = allItems.length
  const cbEntries = Object.entries(connStatus.circuit_breakers)
  const cbHealthy = cbEntries.filter(([, cb]) => cb.state === 'closed').length

  return (
    <div className="space-y-6">
      <ConnectionsHealthBar
        totalOnline={totalOnline}
        totalCount={totalCount}
        cbHealthy={cbHealthy}
        cbTotal={cbEntries.length}
        connLoading={connLoading}
        onRefresh={onRefresh}
      />

      {dsItems.length > 0 && <DataSourceCategoryGrid dsItems={dsItems} />}

      <ExchangeAndNotificationsRow exchItems={exchItems} notifItems={notifItems} />

      {cbEntries.length > 0 && (
        <CircuitBreakersGrid cbEntries={cbEntries} cbHealthy={cbHealthy} />
      )}
    </div>
  )
}
