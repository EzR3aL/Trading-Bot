import { useTranslation } from 'react-i18next'
import { Activity, BarChart3, Cpu, Database, TrendingUp, Zap } from 'lucide-react'
import type { ServiceStatus } from '../../types'

interface Props {
  dsItems: [string, ServiceStatus][]
}

/**
 * Data sources grid grouped by category (sentiment, futures, options, spot,
 * technical, tradfi). Each category card lists its services with online dot
 * and latency tag.
 */
export default function DataSourceCategoryGrid({ dsItems }: Props) {
  const { t } = useTranslation()

  const CAT_ICONS: Record<string, typeof Activity> = {
    sentiment: TrendingUp,
    futures: BarChart3,
    options: Cpu,
    spot: Database,
    technical: Activity,
    tradfi: Zap,
  }
  const catLabels: Record<string, string> = {
    sentiment: t('settings.sentimentNews', 'Sentiment & News'),
    futures: t('settings.futuresData', 'Futures Data'),
    options: t('settings.optionsData', 'Options Data'),
    spot: t('settings.spotMarket', 'Spot Market'),
    technical: t('settings.technicalIndicators', 'Technical Indicators'),
    tradfi: t('settings.tradfiCme', 'TradFi / CME'),
  }
  const catOrder = ['sentiment', 'futures', 'options', 'spot', 'technical', 'tradfi']

  const byCategory: Record<string, [string, ServiceStatus][]> = {}
  for (const [key, svc] of dsItems) {
    const cat = (svc as any).category || 'other'
    if (!byCategory[cat]) byCategory[cat] = []
    byCategory[cat].push([key, svc])
  }
  const dsOnline = dsItems.filter(([, s]) => s.reachable).length

  return (
    <div>
      <div className="flex items-center gap-3 mb-3">
        <Database size={16} className="text-gray-500" />
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          {t('settings.dataSources')}
        </h3>
        <span className="text-xs px-2 py-0.5 rounded-full bg-white/5 text-gray-500 border border-white/10 tabular-nums">
          {dsOnline}/{dsItems.length}
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {catOrder.map(cat => {
          const catItems = byCategory[cat]
          if (!catItems || catItems.length === 0) return null
          const catOnline = catItems.filter(([, s]) => s.reachable).length
          const allUp = catOnline === catItems.length
          const CatIcon = CAT_ICONS[cat] || Activity
          return (
            <div key={cat} className="border border-white/[0.08] bg-white/[0.02] rounded-xl overflow-hidden">
              <div className={`px-4 py-2.5 flex items-center justify-between border-b ${
                allUp ? 'border-emerald-500/10 bg-emerald-500/[0.03]' : 'border-red-500/10 bg-red-500/[0.03]'
              }`}>
                <div className="flex items-center gap-2">
                  <CatIcon size={14} className={allUp ? 'text-emerald-400/70' : 'text-red-400/70'} />
                  <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                    {catLabels[cat] || cat}
                  </span>
                </div>
                <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                  allUp ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
                }`}>
                  {catOnline}/{catItems.length}
                </span>
              </div>
              <div className="px-3 py-2 space-y-0.5">
                {catItems.map(([key, svc]) => (
                  <div key={key} className="flex items-center justify-between py-1.5 px-1.5 rounded-lg hover:bg-white/[0.04] transition-colors">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${svc.reachable ? 'bg-emerald-400' : 'bg-red-400'} ${svc.reachable ? '' : 'animate-pulse'}`} />
                      <span className="text-white text-xs truncate">{svc.label}</span>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0 ml-2">
                      {(svc as any).provider && (svc as any).provider !== 'Calculated' && (
                        <span className="text-gray-600 text-[10px] hidden sm:inline">{(svc as any).provider}</span>
                      )}
                      {svc.latency_ms != null && svc.latency_ms > 0 && (
                        <span className={`text-[10px] tabular-nums px-1.5 py-0.5 rounded ${
                          svc.latency_ms < 500 ? 'text-emerald-400/60' : svc.latency_ms < 2000 ? 'text-yellow-400/60' : 'text-red-400/60'
                        }`}>
                          {svc.latency_ms}ms
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
